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

# Detection patterns
COLD_OUTREACH_BUZZWORDS = [
    "synergy", "revenue", "growth", "scale", "explore opportunities",
    "quick chat", "quick call", "would you be open", "open to",
    "connect on this", "hop on a call", "15 minutes",
    "synergie", "opportunités", "discuter ensemble"
]

GENERIC_OPENERS = [
    "I came across your profile", "I noticed your experience",
    "impressed by your", "saw your background", "noticed you",
    "je me permets", "votre profil", "votre parcours", "j'ai vu que"
]

COMMERCIAL_TONE = [
    "we help", "we specialize", "we work with", "our clients",
    "our platform", "our solution", "help teams", "struggling with",
    "nous aidons", "nous proposons", "notre solution", "clé en main"
]

RECRUITING_PATTERNS = [
    "opportunity", "hiring", "position", "role", "recruit", "talent", "headhunt",
    "salaire", "rémunération", "CDI", "poste", "profil", "candidat", "mission"
]

TECHNICAL_TERMS = [
    "RAG", "AI", "ML", "encryption", "architecture", "security",
    "API", "backend", "frontend", "deployment", "infrastructure"
]

AUTHENTIC_MARKERS = [
    "ton approche", "si ça t'intéresse", "your approach", "if you're interested",
    "vraiment", "honestly", "personnellement", "personally", "je pense",
    "I think", "I noticed that", "would love to hear"
]

# --- Extended response templates ---
DEFAULT_TEMPLATES = {
    # Recruitment / job offer
    "recruiter_en": "Hi {name},\n\nThanks for reaching out. I'm not actively looking for new opportunities at the moment — I'm fully committed to my current projects.\n\nBest regards,\nMaxime",
    "recruiter_fr": "Bonjour {name},\n\nMerci pour votre message. Je ne suis pas en recherche active en ce moment, je suis pleinement engagé dans mes projets actuels.\n\nCordialement,\nMaxime",

    # Outsourcing / team augmentation / staffing
    "outsourcing_en": "Hi {name},\n\nThanks for the message. I'm not looking to work with external staffing or outsourcing partners at the moment.\n\nBest regards,\nMaxime",
    "outsourcing_fr": "Bonjour {name},\n\nMerci pour votre message. Je ne suis pas en recherche de partenaires en externalisation ou augmentation d'équipe pour le moment.\n\nCordialement,\nMaxime",

    # Commercial service pitch
    "service_en": "Hi {name},\n\nThanks for reaching out. This isn't something I need at the moment, but I'll keep you in mind.\n\nBest regards,\nMaxime",
    "service_fr": "Bonjour {name},\n\nMerci pour votre message. Ce n'est pas quelque chose dont j'ai besoin pour l'instant, mais je garde votre contact.\n\nCordialement,\nMaxime",

    # Crypto / DeFi / Web3
    "crypto_en": "Hi {name},\n\nThanks for thinking of me. I'm not available for new engineering engagements at the moment.\n\nBest regards,\nMaxime",
    "crypto_fr": "Bonjour {name},\n\nMerci pour votre message. Je ne suis pas disponible pour de nouvelles missions en ce moment.\n\nCordialement,\nMaxime",

    # Networking / community / event
    "networking_en": "Hi {name},\n\nThanks for the invitation. I'm not available for this kind of exchange at the moment.\n\nBest regards,\nMaxime",
    "networking_fr": "Bonjour {name},\n\nMerci pour l'invitation. Je ne suis pas disponible pour ce type d'échange en ce moment.\n\nCordialement,\nMaxime",

    # Generic fallback
    "spam_en": "Hi {name},\n\nThanks for reaching out. This isn't something I'm interested in at the moment.\n\nBest regards,\nMaxime",
    "spam_fr": "Bonjour {name},\n\nMerci pour votre message. Ce n'est malheureusement pas quelque chose qui m'intéresse pour le moment.\n\nCordialement,\nMaxime",
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
    request_data = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments}
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
            for line in raw_response.strip().split('\n'):
                if line.startswith('data: '):
                    json_str = line[6:]
                    result = json.loads(json_str)
                    if "error" in result:
                        log.error(f"MCP error: {result['error']}")
                        return None
                    if "result" in result and "content" in result["result"]:
                        content = result["result"]["content"]
                        if isinstance(content, list) and len(content) > 0:
                            first_block = content[0]
                            if first_block.get("type") == "text":
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
    result = {"chats": [], "messages": []}
    try:
        data = json.loads(content_text)
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
        if "chats" in data:
            result["chats"] = data["chats"]
        if "messages" in data:
            result["messages"] = data["messages"]
        return result
    except json.JSONDecodeError:
        pass
    if tool_name == "search_chats":
        chat_pattern = r'##\s+([^\(]+)\s+\(chatID:\s+([^\)]+)\)'
        for match in re.finditer(chat_pattern, content_text):
            result["chats"].append({"chatID": match.group(2).strip(), "title": match.group(1).strip()})
    return result


def is_reply_context(text):
    if not text:
        return False
    reply_markers = [
        r"\bthanks for your (message|reply|response)\b",
        r"\bmerci (pour|de) (ton|votre) (message|réponse)\b",
        r"\bas you (mentioned|said)\b",
        r"\bcomme (tu|vous) (l'as|l'avez) (dit|mentionné)\b",
        r"\bregarding your (question|point|message)\b",
        r"\bconcernant (votre|ta) (question|remarque)\b",
        r"\bto answer your\b",
        r"\bpour répondre\b",
        r"\bfollowing up on\b",
        r"\bsuivi de notre\b"
    ]
    for marker in reply_markers:
        if re.search(marker, text, re.I):
            return True
    return False


def analyze_tone(text):
    if not text:
        return 0.5
    text_lower = text.lower()
    authentic_count = sum(1 for m in AUTHENTIC_MARKERS if m.lower() in text_lower)
    commercial_count = sum(1 for m in COMMERCIAL_TONE if m.lower() in text_lower)
    generic_opener_count = sum(1 for o in GENERIC_OPENERS if o.lower() in text_lower)
    score = 0.5
    if authentic_count > 0:
        score -= 0.3 * min(authentic_count, 3)
    if commercial_count > 0:
        score += 0.2 * commercial_count
    if generic_opener_count > 0:
        score += 0.4
    return max(0.0, min(1.0, score))


def calculate_buzzword_density(text):
    if not text:
        return 0.0
    words = text.split()
    total_words = len(words)
    if total_words < 10:
        return 0.0
    buzzword_count = 0
    text_lower = text.lower()
    for term in COLD_OUTREACH_BUZZWORDS + TECHNICAL_TERMS:
        buzzword_count += text_lower.count(term.lower())
    return (buzzword_count / total_words) * 100


def detect_prospection(text, is_conversation_reply=False):
    if not text:
        return False, {}
    text_lower = text.lower()
    detected_reply = is_reply_context(text)
    spam_threshold = 0.8 if (is_conversation_reply or detected_reply) else 0.5
    tone_score = analyze_tone(text)
    buzzword_density = calculate_buzzword_density(text)
    recruiting_matches = [t for t in RECRUITING_PATTERNS if t.lower() in text_lower]
    generic_openers = [o for o in GENERIC_OPENERS if o.lower() in text_lower]
    commercial_matches = [t for t in COMMERCIAL_TONE if t.lower() in text_lower]
    cold_outreach_matches = [t for t in COLD_OUTREACH_BUZZWORDS if t.lower() in text_lower]
    technical_matches = [t for t in TECHNICAL_TERMS if t.lower() in text_lower]
    spam_score = 0.0
    reasons = []
    if recruiting_matches:
        spam_score += 0.6
        reasons.append(f"recruiting keywords: {', '.join(recruiting_matches[:3])}")
    if generic_openers:
        spam_score += 0.4
        reasons.append(f"generic opener: {generic_openers[0]}")
    if tone_score > 0.7:
        spam_score += tone_score * 0.3
        reasons.append(f"commercial tone (score: {tone_score:.2f})")
    if len(commercial_matches) >= 2:
        spam_score += 0.4
        reasons.append(f"commercial pitch: {', '.join(commercial_matches[:2])}")
    elif len(commercial_matches) == 1:
        spam_score += 0.2
        reasons.append(f"commercial keyword: {commercial_matches[0]}")
    if len(cold_outreach_matches) >= 2:
        spam_score += 0.3
        reasons.append(f"cold outreach: {', '.join(cold_outreach_matches[:2])}")
    if buzzword_density > 10 or (len(text.split()) < 50 and len(technical_matches) >= 3):
        spam_score += 0.3
        reasons.append(f"high buzzword density ({buzzword_density:.1f}%)")
    if tone_score < 0.3:
        spam_score -= 0.2
        reasons.append(f"authentic tone (score: {tone_score:.2f})")
    if technical_matches and len(technical_matches) <= 2 and tone_score < 0.5:
        spam_score -= 0.1
    is_spam = spam_score >= spam_threshold
    details = {
        "spam_score": round(spam_score, 2),
        "threshold": spam_threshold,
        "tone_score": round(tone_score, 2),
        "buzzword_density": round(buzzword_density, 1),
        "is_reply": detected_reply or is_conversation_reply,
        "reasons": reasons,
        "matches": {
            "recruiting": recruiting_matches[:3],
            "commercial": commercial_matches[:3],
            "technical": technical_matches[:3],
            "generic_openers": generic_openers[:2]
        }
    }
    return is_spam, details


def detect_language(text):
    if not text:
        return "en"
    has_accents = bool(re.search(r"[éèêëàâäùûüôöîïç]", text))
    french_markers = [
        r"\bbonjour\b", r"\bmerci\b", r"\bvous\b", r"\bvotre\b",
        r"\bje\b", r"\bsuis\b", r"\bpour\b", r"\bavez\b",
        r"\bparcours\b", r"\bprofil\b", r"\bposte\b", r"\brecherche\b"
    ]
    french_count = sum(1 for m in french_markers if re.search(m, text, re.I))
    english_markers = [
        r"\bhope\b", r"\byou\b", r"\byour\b", r"\bwould\b",
        r"\bcould\b", r"\btouch\b", r"\bteam\b", r"\blooking\b"
    ]
    english_count = sum(1 for m in english_markers if re.search(m, text, re.I))
    if has_accents or french_count >= 2:
        return "fr"
    elif english_count >= 2:
        return "en"
    return "en"


def categorize_message(text, detection_details=None):
    """
    Categorize message type: recruiting, outsourcing, service, crypto, networking, spam.
    Returns category string.
    """
    text_lower = text.lower() if text else ""
    matches = detection_details.get("matches", {}) if detection_details else {}
    recruiting = matches.get("recruiting", [])

    # Outsourcing / staffing / team augmentation
    outsourcing_keywords = [
        "outsourc", "staff augment", "team augment", "body shop",
        "external partner", "partenaire externe", "externalisation",
        "delivery cost", "offshore", "nearshore", "managed service"
    ]
    if any(kw in text_lower for kw in outsourcing_keywords):
        return "outsourcing"

    # Crypto / DeFi / Web3
    crypto_keywords = [
        "defi", "web3", "blockchain", "crypto", "nft", "token", "staking",
        "liquidity", "smart contract", "on-chain", "multi-chain", "solidity"
    ]
    if any(kw in text_lower for kw in crypto_keywords):
        return "crypto"

    # Networking / community / events
    networking_keywords = [
        "écosystème", "ecosystem", "communauté", "community", "échange", "exchange",
        "reflexion", "réflexion", "group of professionals", "groupe de professionnels",
        "synergies", "meetup", "webinar", "calendly", "hubspot", "zoom"
    ]
    if any(kw in text_lower for kw in networking_keywords):
        return "networking"

    # Recruitment / job offer
    if recruiting or any(kw in text_lower for kw in ["hiring", "position", "role", "poste", "mission", "CDI", "freelance", "contractor"]):
        return "recruiting"

    # Commercial service
    if detection_details and detection_details.get("matches", {}).get("commercial"):
        return "service"

    return "spam"


def suggest_response(text, sender_name="", detection_details=None):
    """Generate a tailored response based on message category and language."""
    lang = detect_language(text)
    suffix = "_fr" if lang == "fr" else "_en"
    first_name = sender_name.split()[0] if sender_name else ""
    category = categorize_message(text, detection_details)
    template_key = category + suffix
    template = RESPONSE_TEMPLATES.get(template_key) or RESPONSE_TEMPLATES.get("spam" + suffix, "")
    return template.replace("{name}", first_name or "")


def check_linkedin_messages(dry_run=False):
    search_result = mcp_call("search_chats", {
        "query": "LinkedIn",
        "limit": 50,
        "unreadOnly": False
    })
    if not search_result:
        return {"status": "error", "error": "Failed to search chats"}
    chats = search_result.get("chats", [])
    if not chats:
        return {"status": "ok", "detected": 0, "messages": []}
    state = load_state()
    seen = set(state.get("seen_messages", []))
    results = []
    for chat in chats:
        chat_id = chat.get("chatID", "")
        if not chat_id:
            continue
        msgs_result = mcp_call("list_messages", {"chatID": chat_id})
        if not msgs_result:
            continue
        messages = msgs_result.get("messages", [])
        is_ongoing_conversation = len(messages) > 2
        for idx, msg in enumerate(messages):
            msg_id = msg.get("messageID", "")
            if msg_id in seen:
                continue
            text = msg.get("text", "")
            sender_info = msg.get("sender", {})
            sender = sender_info.get("displayName", "") if isinstance(sender_info, dict) else str(sender_info)
            if msg.get("isOwnMessage", False):
                seen.add(msg_id)
                continue
            is_reply = idx > 0 or is_ongoing_conversation
            is_spam, details = detect_prospection(text, is_conversation_reply=is_reply)
            if is_spam:
                suggestion = suggest_response(text, sender, details)
                category = categorize_message(text, details)
                result = {
                    "chat_id": chat_id,
                    "sender": sender,
                    "message_id": msg_id,
                    "text_full": text,
                    "category": category,
                    "detection_details": details,
                    "suggested_response": suggestion,
                    "status": "pending_confirmation",
                }
                results.append(result)
                log.info(f"Prospection detected from {sender} (category: {category}, score: {details['spam_score']})")
            seen.add(msg_id)
    if not dry_run:
        state["seen_messages"] = list(seen)[-1000:]
        if results:
            state["pending_responses"] = state.get("pending_responses", []) + results
        save_state(state)
    return {"status": "ok", "detected": len(results), "messages": results}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="LinkedIn spam filter via Beeper MCP")
    parser.add_argument("--dry-run", action="store_true", help="Don't update state")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--test-text", type=str, help="Test detection on provided text")
    args = parser.parse_args()

    if args.test_text:
        is_spam, details = detect_prospection(args.test_text)
        suggestion = suggest_response(args.test_text, detection_details=details) if is_spam else None
        result = {"is_prospection": is_spam, "detection_details": details, "suggested_response": suggestion}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if is_spam:
                print(f"Prospection detected (score: {details['spam_score']:.2f})")
                if suggestion:
                    print(f"\nSuggested response:\n{suggestion}")
            else:
                print("Not detected as prospection")
        return

    result = check_linkedin_messages(dry_run=args.dry_run)

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        if result.get("status") == "error":
            print(f"Error: {result['error']}")
        elif result.get("detected", 0) > 0:
            print(f"LinkedIn: {result['detected']} prospection message(s) detected")
            for msg in result.get("messages", []):
                print(f"\n--- From: {msg['sender']} [{msg.get('category', '?')}] ---")
                print(f"Message:\n{msg['text_full']}")
                print(f"\nSuggested response:\n{msg['suggested_response']}")
                print()
        else:
            print("LinkedIn: No prospection detected")


if __name__ == "__main__":
    main()
