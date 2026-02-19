#!/usr/bin/env python3
"""
handle-action.py — Handle LinkedIn spam filter actions (ignore/modify/send).
"""

import json
import os
import sys
import argparse
import subprocess

STATE_FILE = os.path.expanduser("~/.openclaw-linkedin-state.json")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"seen_messages": [], "pending_responses": []}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def handle_ignore(chat_id):
    """Mark message as ignored (remove from pending)."""
    state = load_state()
    pending = state.get("pending_responses", [])
    
    # Remove from pending
    state["pending_responses"] = [p for p in pending if p["chat_id"] != chat_id]
    save_state(state)
    
    print(f"✅ Message ignoré (chat_id: {chat_id})")
    return True


def handle_send(chat_id):
    """Send the suggested response and archive."""
    state = load_state()
    pending = state.get("pending_responses", [])
    
    # Find the message
    msg = next((p for p in pending if p["chat_id"] == chat_id), None)
    if not msg:
        print(f"❌ Message not found in pending (chat_id: {chat_id})", file=sys.stderr)
        return False
    
    suggested_response = msg.get("suggested_response", "")
    if not suggested_response:
        print(f"❌ No suggested response found", file=sys.stderr)
        return False
    
    # Send via send-response.py
    script_dir = os.path.dirname(os.path.abspath(__file__))
    send_script = os.path.join(script_dir, "send-response.py")
    
    result = subprocess.run(
        [sys.executable, send_script, "--chat-id", chat_id, "--message", suggested_response],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print(f"❌ Failed to send: {result.stderr}", file=sys.stderr)
        return False
    
    # Remove from pending
    state["pending_responses"] = [p for p in pending if p["chat_id"] != chat_id]
    save_state(state)
    
    print(f"✅ Réponse envoyée et chat archivé (chat_id: {chat_id})")
    return True


def handle_modify(chat_id):
    """Return the pending message info for modification."""
    state = load_state()
    pending = state.get("pending_responses", [])
    
    msg = next((p for p in pending if p["chat_id"] == chat_id), None)
    if not msg:
        print(f"❌ Message not found in pending (chat_id: {chat_id})", file=sys.stderr)
        return False
    
    # Return info as JSON for the agent to prompt user
    print(json.dumps({
        "action": "modify",
        "chat_id": chat_id,
        "sender": msg.get("sender", ""),
        "current_response": msg.get("suggested_response", ""),
        "prompt": f"Quelle réponse veux-tu envoyer à {msg.get('sender', '')} ?"
    }, ensure_ascii=False))
    return True


def send_custom_response(chat_id, custom_message):
    """Send a custom response (user-provided) and archive."""
    state = load_state()
    pending = state.get("pending_responses", [])
    
    # Send via send-response.py
    script_dir = os.path.dirname(os.path.abspath(__file__))
    send_script = os.path.join(script_dir, "send-response.py")
    
    result = subprocess.run(
        [sys.executable, send_script, "--chat-id", chat_id, "--message", custom_message],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print(f"❌ Failed to send: {result.stderr}", file=sys.stderr)
        return False
    
    # Remove from pending
    state["pending_responses"] = [p for p in pending if p["chat_id"] != chat_id]
    save_state(state)
    
    print(f"✅ Réponse personnalisée envoyée et chat archivé (chat_id: {chat_id})")
    return True


def main():
    parser = argparse.ArgumentParser(description="Handle LinkedIn spam filter actions")
    parser.add_argument("action", choices=["ignore", "send", "modify", "send-custom"])
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--message", help="Custom message for send-custom action")
    args = parser.parse_args()
    
    if args.action == "ignore":
        success = handle_ignore(args.chat_id)
    elif args.action == "send":
        success = handle_send(args.chat_id)
    elif args.action == "modify":
        success = handle_modify(args.chat_id)
    elif args.action == "send-custom":
        if not args.message:
            print("❌ --message required for send-custom", file=sys.stderr)
            sys.exit(1)
        success = send_custom_response(args.chat_id, args.message)
    else:
        success = False
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
