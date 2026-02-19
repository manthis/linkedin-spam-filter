#!/usr/bin/env python3
"""
linkedin-prospection.py — Detect LinkedIn spam/prospection messages via Beeper MCP.
Generates suggested responses and supports confirmation workflow.
Pure stdlib (except MCP interaction via mcporter CLI).
"""

import json
import os
import re
import subprocess
import sys
import argparse
import logging
from datetime import datetime
from pathlib import Path

# --- Config from env ---
MCPORTER_CMD = os.environ.get("MCPORTER_CMD", "mcporter")
BEEPER_SERVER = os.environ.get("BEEPER_SERVER", "beeper")
LINKEDIN_ROOM_PATTERN = os.environ.get("LINKEDIN_ROOM_PATTERN", "linkedin")
LOG_FILE = os.environ.get("LINKEDIN_LOG", os.path.expanduser("~/logs/linkedin-prospection.log"))
STATE_FILE = os.environ.get("LINKEDIN_STATE", os.path.expanduser("~/.openclaw-linkedin-state.json"))

# Detection patterns (comma-separated regexes)
DEFAULT_PATTERNS = (
    r"opportunity|hiring|position|role|recruit|talent|headhunt|"
    r"salaire|rémunération|CDI|poste|profil|candidat|mission|"
    r"partnership|collaboration|revenue|growth|scale|"
    r"I came across your profile|I noticed your experience|"
    r"je me permets|votre profil|votre parcours"
)
SPAM_PATTERNS = os.environ.get("SPAM_PATTERNS", DEFAULT_PATTERNS)

# Response templates
DEFAULT_TEMPLATES = json.dumps({
    "recruiter_en": "Hi {name}, thanks for reaching out! I'm not actively looking for new opportunities at the moment, but feel free to connect — I'm always open to interesting conversations.",
    "recruiter_fr": "Bonjour {name}, merci pour votre message ! Je ne suis pas en recherche active actuellement, mais n'hésitez pas à rester en contact.",
    "spam_en": "Thanks for the message, but I'm not interested. Best of luck!",
    "spam_fr": "Merci pour le message, mais ce n'est pas pour moi. Bonne continuation !",
})
RESPONSE_TEMPLATES = json.loads(os.environ.get("RESPONSE_TEMPLATES", DEFAULT_TEMPLATES))

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


def run_mcporter(args):
    """Run mcporter command and return output."""
    cmd = [MCPORTER_CMD] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout.strip(), result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return str(e), False


def detect_prospection(text):
    """Check if message matches prospection/spam patterns."""
    pattern = re.compile(SPAM_PATTERNS, re.IGNORECASE)
    matches = pattern.findall(text)
    return len(matches) > 0, matches


def suggest_response(text, sender_name=""):
    """Generate a suggested response based on message content."""
    is_french = bool(re.search(r"[éèêëàâäùûüôöîïç]|bonjour|merci|profil", text, re.I))

    if re.search(r"recruit|hiring|position|role|poste|candidat|mission", text, re.I):
        template_key = "recruiter_fr" if is_french else "recruiter_en"
    else:
        template_key = "spam_fr" if is_french else "spam_en"

    template = RESPONSE_TEMPLATES.get(template_key, RESPONSE_TEMPLATES.get("spam_en", ""))
    return template.replace("{name}", sender_name or "")


def check_linkedin_messages(dry_run=False):
    """Check for new LinkedIn messages via Beeper MCP."""
    # This attempts to use mcporter to interact with Beeper
    # The actual implementation depends on the Beeper MCP API
    output, ok = run_mcporter(["call", BEEPER_SERVER, "list_rooms"])

    if not ok:
        return {"status": "error", "error": f"mcporter failed: {output}"}

    try:
        rooms = json.loads(output) if output else []
    except json.JSONDecodeError:
        return {"status": "error", "error": f"Invalid JSON from mcporter: {output[:200]}"}

    state = load_state()
    seen = set(state.get("seen_messages", []))
    results = []

    for room in rooms:
        room_name = room.get("name", "")
        room_id = room.get("id", "")

        # Filter LinkedIn rooms
        if LINKEDIN_ROOM_PATTERN.lower() not in room_name.lower():
            continue

        # Get recent messages
        msgs_output, msgs_ok = run_mcporter([
            "call", BEEPER_SERVER, "get_messages",
            "--room", room_id, "--limit", "5"
        ])

        if not msgs_ok:
            continue

        try:
            messages = json.loads(msgs_output) if msgs_output else []
        except json.JSONDecodeError:
            continue

        for msg in messages:
            msg_id = msg.get("id", "")
            if msg_id in seen:
                continue

            text = msg.get("body", "")
            sender = msg.get("sender", "")
            is_spam, matches = detect_prospection(text)

            if is_spam:
                suggestion = suggest_response(text, sender)
                result = {
                    "room": room_name,
                    "room_id": room_id,
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
    parser = argparse.ArgumentParser(description="LinkedIn prospection detector")
    parser.add_argument("--dry-run", action="store_true", help="Don't update state or send")
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
