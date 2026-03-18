#!/usr/bin/env python3
"""LinkedIn message fetcher via Beeper MCP.
Fetches unseen LinkedIn messages and returns them for AI judgment.
"""
import json, os, re, urllib.request, logging, argparse
from pathlib import Path

BEEPER_MCP_URL = os.environ.get("BEEPER_MCP_URL", "http://localhost:23373/v0/mcp")
BEEPER_TOKEN   = os.environ.get("BEEPER_TOKEN", "d3970894-6957-4599-83df-6bf7899f4fb3")
STATE_FILE     = os.environ.get("LINKEDIN_STATE", os.path.expanduser("~/.openclaw-linkedin-state.json"))
LOG_FILE       = os.environ.get("LINKEDIN_LOG",   os.path.expanduser("~/logs/linkedin-spam-filter.log"))

Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
log = logging.getLogger()


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"seen_messages": [], "pending_responses": []}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Beeper MCP
# ---------------------------------------------------------------------------

def mcp_call(tool_name, params):
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool_name, "arguments": params}
    }).encode()
    req = urllib.request.Request(
        BEEPER_MCP_URL, data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {BEEPER_TOKEN}",
        })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
        for line in raw.split("\n"):
            if line.startswith("data: "):
                d = json.loads(line[6:])
                if "error" in d:
                    log.error(f"MCP error {tool_name}: {d['error']}")
                    return None
                text = d.get("result", {}).get("content", [{}])[0].get("text", "")
                return _parse(text)
    except Exception as e:
        log.error(f"MCP {tool_name} failed: {e}")
    return None


def _parse(text):
    """Parse MCP response text: JSON object or markdown chat list."""
    try:
        data = json.loads(text)
        # list_messages returns {items: [...]}
        if "items" in data:
            return {"messages": [{
                "messageID":   i.get("id"),
                "text":        i.get("text", ""),
                "sender":      i.get("senderName", ""),
                "isOwnMessage": i.get("isSender", False),
                "timestamp":   i.get("timestamp"),
            } for i in data["items"]]}
        return data
    except (json.JSONDecodeError, TypeError):
        pass
    # search_chats returns markdown: ## Name (chatID: ...)
    chats = []
    for m in re.finditer(r"## (.+?) \(chatID: ([^)]+)\)", text):
        chats.append({"title": m.group(1).strip(), "chatID": m.group(2).strip()})
    return {"chats": chats}


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def fetch_messages(dry_run=False):
    """Fetch all new unseen LinkedIn messages. Pending messages are re-returned until confirmed."""
    state = load_state()
    seen        = set(state.get("seen_messages", []))
    pending_ids = {m.get("message_id") for m in state.get("pending_responses", [])}

    result = mcp_call("search_chats", {"query": "LinkedIn", "limit": 50, "unreadOnly": False})
    chats = (result or {}).get("chats", [])

    new_messages = []
    for chat in chats:
        chat_id = chat.get("chatID", "")
        if not chat_id:
            continue
        msgs_result = mcp_call("list_messages", {"chatID": chat_id})
        if not msgs_result:
            continue
        for msg in msgs_result.get("messages", []):
            mid = msg.get("messageID", "")
            if not mid:
                continue
            if msg.get("isOwnMessage", False):
                # Own messages: mark seen so we don't re-process
                seen.add(mid)
                continue
            if mid in seen or mid in pending_ids:
                # Already handled or already pending
                continue
            new_messages.append({
                "chat_id":   chat_id,
                "sender":    msg.get("sender", ""),
                "message_id": mid,
                "text":      msg.get("text", ""),
                "timestamp": msg.get("timestamp", ""),
                "status":    "pending_confirmation",
            })
            log.info(f"New message from {msg.get('sender', '?')} (id={mid})")

    if not dry_run:
        state["seen_messages"] = list(seen)[-2000:]
        if new_messages:
            state["pending_responses"] = state.get("pending_responses", []) + new_messages
        save_state(state)

    # Return existing pending + newly found (deduplicated)
    all_pending = state.get("pending_responses", []) + new_messages
    seen_ids, deduplicated = set(), []
    for m in all_pending:
        if m.get("message_id") not in seen_ids:
            seen_ids.add(m["message_id"])
            deduplicated.append(m)

    return {"status": "ok", "detected": len(deduplicated), "messages": deduplicated}


def send_reply(chat_id, message):
    """Send a reply and mark the chat's pending message as confirmed."""
    mcp_call("send_message", {"chatID": chat_id, "text": message})
    state = load_state()
    for m in state.get("pending_responses", []):
        if m.get("chat_id") == chat_id:
            mid = m.get("message_id")
            if mid and mid not in state["seen_messages"]:
                state["seen_messages"].append(mid)
    state["pending_responses"] = [m for m in state.get("pending_responses", []) if m.get("chat_id") != chat_id]
    save_state(state)


def ignore_message(message_id):
    """Dismiss a message without reply."""
    state = load_state()
    if message_id not in state["seen_messages"]:
        state["seen_messages"].append(message_id)
    state["pending_responses"] = [m for m in state.get("pending_responses", []) if m.get("message_id") != message_id]
    save_state(state)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LinkedIn message fetcher via Beeper MCP")
    parser.add_argument("--dry-run",  action="store_true",  help="Don't update state")
    parser.add_argument("--json",     action="store_true",  help="JSON output")
    parser.add_argument("--reply-to", type=str, metavar="CHAT_ID", help="Chat ID to reply to")
    parser.add_argument("--message",  type=str, help="Message to send (use with --reply-to)")
    parser.add_argument("--ignore",   type=str, metavar="MSG_ID",  help="Message ID to dismiss without reply")
    args = parser.parse_args()

    if args.ignore:
        ignore_message(args.ignore)
        print("ignored")
        return

    if args.reply_to and args.message:
        send_reply(args.reply_to, args.message)
        print("sent")
        return

    result = fetch_messages(dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        if result["detected"] > 0:
            for m in result["messages"]:
                print(f"[{m['sender']}] {m['text'][:100]}")
        else:
            print("No new messages")


if __name__ == "__main__":
    main()
