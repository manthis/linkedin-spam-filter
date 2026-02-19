#!/usr/bin/env python3
"""
send-response.py — Send LinkedIn response and archive chat via Beeper MCP.
"""

import json
import os
import sys
import urllib.request
import argparse

BEEPER_MCP_URL = os.environ.get("BEEPER_MCP_URL", "http://localhost:23373/v0/mcp")
BEEPER_TOKEN = os.environ.get("BEEPER_TOKEN", "d3970894-6957-4599-83df-6bf7899f4fb3")


def mcp_call(tool_name, arguments):
    """Call a Beeper MCP tool via HTTP JSON-RPC (SSE format)."""
    request_data = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }
    
    headers = {
        "Authorization": f"Bearer {BEEPER_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"
    }
    
    try:
        req = urllib.request.Request(
            BEEPER_MCP_URL,
            data=json.dumps(request_data).encode('utf-8'),
            headers=headers,
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read().decode('utf-8')
            
    except Exception as e:
        print(f"Error calling {tool_name}: {e}", file=sys.stderr)
        return None


def send_and_archive(chat_id, message):
    """Send a message and archive the chat.
    
    Args:
        chat_id: Beeper chat ID
        message: Message text to send
    
    Returns:
        bool: True if successful
    """
    # Send message
    print(f"Sending message to {chat_id}...")
    result = mcp_call("send_message", {"chatID": chat_id, "text": message})
    
    if not result:
        print("❌ Failed to send message", file=sys.stderr)
        return False
    
    print("✅ Message sent")
    
    # Archive chat
    print(f"Archiving chat {chat_id}...")
    result = mcp_call("archive_chat", {"chatID": chat_id})
    
    if not result:
        print("⚠️ Failed to archive chat (message was sent)", file=sys.stderr)
        return False
    
    print("✅ Chat archived")
    return True


def main():
    parser = argparse.ArgumentParser(description="Send LinkedIn response and archive chat")
    parser.add_argument("--chat-id", required=True, help="Beeper chat ID")
    parser.add_argument("--message", required=True, help="Message text to send")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually send")
    args = parser.parse_args()
    
    if args.dry_run:
        print(f"[DRY RUN] Would send to {args.chat_id}:")
        print(args.message)
        print("[DRY RUN] Would then archive the chat")
        return
    
    success = send_and_archive(args.chat_id, args.message)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
