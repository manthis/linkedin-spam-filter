#!/usr/bin/env python3
"""
linkedin-spam-filter.py — Detect LinkedIn spam/prospection messages via Beeper MCP.
Direct MCP HTTP client (no mcporter CLI).
"""

import json
import os
import re
import logging
from datetime import datetime
from pathlib import Path
import urllib.request
import urllib.error

# --- Config from env ---
BEEPER_MCP_URL = os.environ.get("BEEPER_MCP_URL", "http://localhost:23373/v0/mcp")
BEEPER_TOKEN = os.environ.get("BEEPER_TOKEN", "d3970894-6957-4599-83df-6bf7899f4fb3")
LOG_FILE = os.environ.get("LINKEDIN_LOG", os.path.expanduser("~/logs/linkedin-spam-filter.log"))
STATE_FILE = os.environ.get("LINKEDIN_STATE", os.path.expanduser("~/.openclaw-linkedin-state.json"))

# Detection patterns (improved for LinkedIn prospection)
DEFAULT_PATTERNS = (
    # Recruiting
    r"opportunity|hiring|position|role|recruit|talent|headhunt|"
    r"salaire|rémunération|CDI|poste|profil|candidat|mission|"
    # Business development
    r"partnership|collaboration|synergy|revenue|growth|scale|explore|"
    r"quick chat|quick call|would you be open|open to|connect on this|"
    # Flattery openers (generic)
    r"I came across your profile|I noticed your experience|I like how you|"
    r"impressed by your|saw your background|noticed you|"
    r"je me permets|votre profil|votre parcours|j'ai vu que|"
    # Sales/pitch keywords
    r"automation layer|help teams|struggling with|our platform|our solution|"
    r"we help|we specialize|we work with|our clients|RAG|AI features"
)
SPAM_PATTERNS = os.environ.get("SPAM_PATTERNS", DEFAULT_PATTERNS)

# Response templates
DEFAULT_TEMPLATES = {
    "recruiter_en": "Hi {name}, thanks for reaching out! I'm not actively looking for new opportunities at the moment, but feel free to connect — I'm always open to interesting conversations.",
    "recruiter_fr": "Bonjour {name}, merci pour votre message ! Je ne suis pas en recherche active actuellement, mais n'hésitez pas à rester en contact.",
    "spam_en": "Thanks for the message, but I'm not interested. Best of luck!",
    "spam_fr": "Merci pour le message, mais ce n'est pas pour moi. Bonne continuation !",
}
RESPONSE_TEMPLATES = json.loads(os.environ.get("RESPONSE_TEMPLATES", json.dumps(DEFAULT_TEMPLATES)))

# Setup logging
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"seen_messages": [], "pending_responses": []}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


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
            raw_response = response.read().decode('utf-8')
            
            # Parse SSE format: "event: message\ndata: {json}\n\n"
            for line in raw_response.strip().split('\n'):
                if line.startswith('data: '):
                    json_str = line[6:]  # Remove "data: " prefix
                    result = json.loads(json_str)
                    
                    if "error" in result:
                        log.error(f"MCP error: {result['error']}")
                        return None
                    
                    # Extract content from MCP response
                    if "result" in result and "content" in result["result"]:
                        content = result["result"]["content"]
                        # MCP returns list of content blocks
                        if isinstance(content, list) and len(content) > 0:
                            first_block = content[0]
                            if first_block.get("type") == "text":
                                # Parse response (JSON or markdown)
                                return parse_beeper_response(first_block.get("text", ""), tool_name)
                    
                    return result.get("result")
            
            return None
            
    except urllib.error.HTTPError as e:
        log.error(f"HTTP error calling {tool_name}: {e.code} {e.reason}")
        return None
    except Exception as e:
        log.error(f"Error calling {tool_name}: {e}")
        return None


def parse_beeper_response(content_text, tool_name=None):
    """Parse Beeper's response (markdown or JSON)."""
    result = {
        "chats": [],
        "messages": []
    }
    
    # Try to parse as JSON first
    try:
        data = json.loads(content_text)
        
        # Handle list_messages JSON response
        if "items" in data:
            for item in data.get("items", []):
                result["messages"].append({
                    "messageID": item.get("id"),
                    "text": item.get("text", ""),
                    "sender": {"displayName": item.get("senderName", "")},
                    "isOwnMessage": item.get("isSender", False),
                    "timestamp": item.get("timestamp"),
                    "isUnread": item.get("isUnread", False)
                })
            return result
        
        # Handle other JSON formats
        if "chats" in data:
            result["chats"] = data["chats"]
        if "messages" in data:
            result["messages"] = data["messages"]
        
        return result
        
    except json.JSONDecodeError:
        # Fall back to markdown parsing
        pass
    
    # Markdown parsing
    if tool_name == "search_chats":
        # Parse chat entries: "## Name (chatID: !xxx:beeper.local)"
        chat_pattern = r'##\s+([^\(]+)\s+\(chatID:\s+([^\)]+)\)'
        for match in re.finditer(chat_pattern, content_text):
            name = match.group(1).strip()
            chat_id = match.group(2).strip()
            result["chats"].append({
                "chatID": chat_id,
                "title": name
            })
    
    return result


def detect_prospection(text):
    """Check if message matches prospection/spam patterns."""
    if not text:
        return False, []
    pattern = re.compile(SPAM_PATTERNS, re.IGNORECASE)
    matches = pattern.findall(text)
    return len(matches) > 0, matches


def detect_language(text):
    """Detect if message is in French or English based on content."""
    if not text:
        return "en"
    
    # Check for French accents
    has_accents = bool(re.search(r"[éèêëàâäùûüôöîïç]", text))
    
    # Check for common French words/phrases
    french_markers = [
        r"\bbonjour\b", r"\bmerci\b", r"\bvous\b", r"\bvotre\b", 
        r"\bje\b", r"\bsuis\b", r"\bpour\b", r"\bavez\b",
        r"\bparcours\b", r"\bprofil\b", r"\bposte\b", r"\brecherche\b"
    ]
    french_count = sum(1 for marker in french_markers if re.search(marker, text, re.I))
    
    # Check for common English words
    english_markers = [
        r"\bhope\b", r"\byou\b", r"\byour\b", r"\bwould\b",
        r"\bcould\b", r"\btouch\b", r"\bteam\b", r"\blooking\b"
    ]
    english_count = sum(1 for marker in english_markers if re.search(marker, text, re.I))
    
    # Decide based on markers
    if has_accents or french_count >= 2:
        return "fr"
    elif english_count >= 2:
        return "en"
    else:
        # Default to English if uncertain
        return "en"


def suggest_response(text, sender_name=""):
    """Generate a suggested response based on message content and language."""
    lang = detect_language(text)
    is_french = (lang == "fr")

    if re.search(r"recruit|hiring|position|role|poste|candidat|mission", text, re.I):
        template_key = "recruiter_fr" if is_french else "recruiter_en"
    else:
        template_key = "spam_fr" if is_french else "spam_en"

    template = RESPONSE_TEMPLATES.get(template_key, RESPONSE_TEMPLATES.get("spam_en", ""))
    return template.replace("{name}", sender_name or "")


def check_linkedin_messages(dry_run=False):
    """Check for new LinkedIn messages via Beeper MCP."""
    # Search for unread LinkedIn chats
    search_result = mcp_call("search_chats", {
        "query": "LinkedIn",
        "limit": 50,
        "unreadOnly": True
    })

    if not search_result:
        return {"status": "error", "error": "Failed to search chats"}

    # Extract chat IDs from parsed result
    chats = search_result.get("chats", [])
    
    if not chats:
        return {
            "status": "ok",
            "detected": 0,
            "messages": []
        }

    state = load_state()
    seen = set(state.get("seen_messages", []))
    results = []

    for chat in chats:
        chat_id = chat.get("chatID", "")
        if not chat_id:
            continue

        # Get messages from this chat
        msgs_result = mcp_call("list_messages", {"chatID": chat_id})
        
        if not msgs_result:
            continue

        messages = msgs_result.get("messages", [])

        for msg in messages:
            msg_id = msg.get("messageID", "")
            if msg_id in seen:
                continue

            text = msg.get("text", "")
            sender_info = msg.get("sender", {})
            sender = sender_info.get("displayName", "") if isinstance(sender_info, dict) else str(sender_info)
            
            # Skip my own messages
            if msg.get("isOwnMessage", False):
                seen.add(msg_id)
                continue

            is_spam, matches = detect_prospection(text)

            if is_spam:
                suggestion = suggest_response(text, sender)
                result = {
                    "chat_id": chat_id,
                    "sender": sender,
                    "message_id": msg_id,
                    "text_preview": text[:200],
                    "matches": matches[:5],
                    "suggested_response": suggestion,
                    "status": "pending_confirmation",
                }
                results.append(result)
                log.info(f"Prospection detected from {sender}: {matches[:3]}")

            seen.add(msg_id)

    # Update state
    if not dry_run:
        state["seen_messages"] = list(seen)[-1000:]
        if results:
            state["pending_responses"] = state.get("pending_responses", []) + results
        save_state(state)

    return {
        "status": "ok",
        "detected": len(results),
        "messages": results,
    }


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="LinkedIn spam filter via Beeper MCP")
    parser.add_argument("--dry-run", action="store_true", help="Don't update state")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--test-text", type=str, help="Test detection on provided text")
    args = parser.parse_args()

    # Test mode
    if args.test_text:
        is_spam, matches = detect_prospection(args.test_text)
        suggestion = suggest_response(args.test_text) if is_spam else None
        result = {
            "is_prospection": is_spam,
            "matches": matches,
            "suggested_response": suggestion,
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            if is_spam:
                print(f"🎯 Prospection detected! Matches: {', '.join(matches[:5])}")
                print(f"💬 Suggested response: {suggestion}")
            else:
                print("✅ Not detected as prospection")
        return

    # Normal mode
    result = check_linkedin_messages(dry_run=args.dry_run)

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        if result.get("status") == "error":
            print(f"❌ Error: {result['error']}")
        elif result.get("detected", 0) > 0:
            print(f"🎯 LinkedIn: {result['detected']} prospection message(s) detected")
            for msg in result.get("messages", []):
                print(f"  • From: {msg['sender']}")
                print(f"    Preview: {msg['text_preview'][:100]}...")
                print(f"    Response: {msg['suggested_response']}")
                print()
        else:
            print("✅ LinkedIn: No prospection detected")


if __name__ == "__main__":
    main()
