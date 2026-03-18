#!/usr/bin/env python3
"""LinkedIn message fetcher via Beeper MCP.
Fetches unseen LinkedIn messages and returns them for AI judgment.
"""
import json, os, urllib.request, urllib.error, logging, argparse
from pathlib import Path

BEEPER_MCP_URL = os.environ.get("BEEPER_MCP_URL", "http://localhost:23373/v0/mcp")
BEEPER_TOKEN   = os.environ.get("BEEPER_TOKEN", "d3970894-6957-4599-83df-6bf7899f4fb3")
STATE_FILE     = os.environ.get("LINKEDIN_STATE", os.path.expanduser("~/.openclaw-linkedin-state.json"))
LOG_FILE       = os.environ.get("LINKEDIN_LOG",   os.path.expanduser("~/logs/linkedin-spam-filter.log"))

Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
log = logging.getLogger()


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"seen_messages": [], "pending_responses": []}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def mcp_call(tool_name, params):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": tool_name, "arguments": params}}).encode()
    req = urllib.request.Request(
        BEEPER_MCP_URL, data=payload,
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream",
                 "Authorization": f"Bearer {BEEPER_TOKEN}"})
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
                return parse_response(text, tool_name)
    except Exception as e:
        log.error(f"MCP {tool_name} failed: {e}")
    return None


def parse_response(text, tool_name=None):
    try:
        data = json.loads(text)
        if "items" in data:
            return {"messages": [{
                "messageID": i.get("id"),
                "text": i.get("text", ""),
                "sender": i.get("senderName", ""),
                "isOwnMessage": i.get("isSender", False),
                "timestamp": i.get("timestamp"),
                "isUnread": i.get("isUnread", False),
            } for i in data["items"]]}
        return data
    except json.JSONDecodeError:
        pass
    # Parse markdown chat list
    import re
    chats = []
    for m in re.finditer(r"## (.+?) \(chatID: ([^)]+)\)", text):
        chats.append({"title": m.group(1).strip(), "chatID": m.group(2).strip()})
    return {"chats": chats}


def fetch_messages(dry_run=False):
    """Fetch all unseen LinkedIn messages from single chats."""
    state = load_state()
    seen = set(state.get("seen_messages", []))
    pending_ids = {m.get("message_id") for m in state.get("pending_responses", [])}

    result = mcp_call("search_chats", {"query": "LinkedIn", "limit": 50, "unreadOnly": False})
    chats = result.get("chats", []) if result else []

    new_messages = []
    for chat in chats:
        chat_id = chat.get("chatID", "")
        if not chat_id:
            continue
        msgs_result = mcp_call("list_messages", {"chatID": chat_id})
        if not msgs_result:
            continue
        messages = msgs_result.get("messages", [])
        for msg in messages:
            mid = msg.get("messageID", "")
            if not mid or mid in seen or msg.get("isOwnMessage", True):
                if not msg.get("isOwnMessage", True) and mid not in seen and mid not in pending_ids:
                    pass
                elif mid not in seen and not msg.get("isOwnMessage", True) and mid not in pending_ids:
                    pass
                else:
                    if not msg.get("isOwnMessage", False):
                        pass
                    continue
            if msg.get("isOwnMessage", False):
                seen.add(mid)
                continue
            # New message from other person — not yet seen or pending
            if mid in seen or mid in pending_ids:
                continue
            new_messages.append({
                "chat_id": chat_id,
                "sender": msg.get("sender", ""),
                "message_id": mid,
                "text": msg.get("text", ""),
                "timestamp": msg.get("timestamp", ""),
                "status": "pending_confirmation",
            })
            log.info(f"New message from {msg.get('sender', '?')} (id={mid})")

    if not dry_run and new_messages:
        state["pending_responses"] = state.get("pending_responses", []) + new_messages
        save_state(state)

    # Return new messages + existing pending (not yet confirmed)
    all_pending = state.get("pending_responses", []) + new_messages
    # Deduplicate
    seen_ids = set()
    deduplicated = []
    for m in all_pending:
        if m.get("message_id") not in seen_ids:
            seen_ids.add(m.get("message_id"))
            deduplicated.append(m)

    return {"status": "ok", "detected": len(deduplicated), "messages": deduplicated}


def main():
    parser = argparse.ArgumentParser(description="LinkedIn message fetcher via Beeper MCP")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--reply-to", type=str, help="Chat ID to reply to")
    parser.add_argument("--message", type=str, help="Message to send")
    parser.add_argument("--ignore", type=str, help="Message ID to dismiss without reply")
    args = parser.parse_args()

    # --ignore: dismiss without reply
    if args.ignore:
        state = load_state()
        if args.ignore not in state["seen_messages"]:
            state["seen_messages"].append(args.ignore)
        state["pending_responses"] = [m for m in state.get("pending_responses", []) if m.get("message_id") != args.ignore]
        save_state(state)
        print("ignored")
        return

    # --reply-to: send and confirm
    if args.reply_to and args.message:
        mcp_call("send_message", {"chatId": args.reply_to, "text": args.message})
        state = load_state()
        for m in state.get("pending_responses", []):
            if m.get("chat_id") == args.reply_to:
                mid = m.get("message_id")
                if mid and mid not in state["seen_messages"]:
                    state["seen_messages"].append(mid)
        state["pending_responses"] = [m for m in state.get("pending_responses", []) if m.get("chat_id") != args.reply_to]
        save_state(state)
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
