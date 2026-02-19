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
# Cold outreach buzzwords (only suspicious in cold context)
COLD_OUTREACH_BUZZWORDS = [
    "synergy", "revenue", "growth", "scale", "explore opportunities",
    "quick chat", "quick call", "would you be open", "open to", 
    "connect on this", "hop on a call", "15 minutes",
    "synergie", "opportunités", "discuter ensemble"
]

# Generic flattery openers (strong spam signal)
GENERIC_OPENERS = [
    "I came across your profile", "I noticed your experience", 
    "impressed by your", "saw your background", "noticed you",
    "je me permets", "votre profil", "votre parcours", "j'ai vu que"
]

# Commercial pitch indicators
COMMERCIAL_TONE = [
    "we help", "we specialize", "we work with", "our clients",
    "our platform", "our solution", "help teams", "struggling with",
    "nous aidons", "nous proposons", "notre solution", "clé en main"
]

# Recruiting keywords
RECRUITING_PATTERNS = [
    "opportunity", "hiring", "position", "role", "recruit", "talent", "headhunt",
    "salaire", "rémunération", "CDI", "poste", "profil", "candidat", "mission"
]

# Technical terms that need context analysis (NOT spam alone)
TECHNICAL_TERMS = [
    "RAG", "AI", "ML", "encryption", "architecture", "security",
    "API", "backend", "frontend", "deployment", "infrastructure"
]

# Authentic personal tone indicators (reduce spam score)
AUTHENTIC_MARKERS = [
    "ton approche", "si ça t'intéresse", "your approach", "if you're interested",
    "vraiment", "honestly", "personnellement", "personally", "je pense",
    "I think", "I noticed that", "would love to hear"
]

# Response templates
DEFAULT_TEMPLATES = {
    "recruiter_en": "Hi {name},\n\nThank you for reaching out and thinking of me for this opportunity. I really appreciate you taking the time to connect.\n\nAt the moment, I'm fully committed to my current projects and not actively exploring new roles. However, I'm always happy to stay connected and keep the conversation open for the future.\n\nWishing you all the best in your search!\n\nBest regards,\nMaxime",
    "recruiter_fr": "Bonjour {name},\n\nMerci d'avoir pris le temps de me contacter, j'apprécie votre démarche.\n\nActuellement, je suis pleinement engagé dans mes projets en cours et ne suis pas en recherche active. Cependant, je reste ouvert aux échanges et serai ravi de rester en contact pour d'éventuelles opportunités futures.\n\nJe vous souhaite beaucoup de succès dans vos recherches.\n\nCordialement,\nMaxime",
    "spam_en": "Hi {name},\n\nThank you for reaching out. I appreciate the opportunity, but this isn't something I'm interested in pursuing at the moment.\n\nI wish you the best of luck with your project.\n\nBest regards,\nMaxime",
    "spam_fr": "Bonjour {name},\n\nMerci pour votre message. J'apprécie votre démarche, mais ce n'est malheureusement pas quelque chose qui m'intéresse pour le moment.\n\nJe vous souhaite beaucoup de succès dans votre projet.\n\nCordialement,\nMaxime",
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


def is_reply_context(text):
    """Detect if message appears to be a reply to existing conversation."""
    if not text:
        return False
    
    # Reply indicators (explicit references to previous messages)
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
    """Analyze if message has authentic/personal tone vs generic/commercial."""
    if not text:
        return 0.5
    
    text_lower = text.lower()
    
    # Count authentic markers
    authentic_count = sum(1 for marker in AUTHENTIC_MARKERS 
                         if marker.lower() in text_lower)
    
    # Count commercial/generic markers  
    commercial_count = sum(1 for marker in COMMERCIAL_TONE 
                          if marker.lower() in text_lower)
    
    # Count generic openers
    generic_opener_count = sum(1 for opener in GENERIC_OPENERS 
                               if opener.lower() in text_lower)
    
    # Scoring: authentic reduces score, commercial increases it
    # Range: 0 (very authentic) to 1 (very commercial)
    score = 0.5  # neutral baseline
    
    if authentic_count > 0:
        score -= 0.3 * min(authentic_count, 3)  # cap at -0.9
    
    if commercial_count > 0:
        score += 0.2 * commercial_count
    
    if generic_opener_count > 0:
        score += 0.4  # strong signal
    
    return max(0.0, min(1.0, score))


def calculate_buzzword_density(text):
    """Calculate density of technical buzzwords vs substance."""
    if not text:
        return 0.0
    
    words = text.split()
    total_words = len(words)
    
    if total_words < 10:
        return 0.0  # too short to judge
    
    # Count buzzwords
    buzzword_count = 0
    text_lower = text.lower()
    
    for term in COLD_OUTREACH_BUZZWORDS + TECHNICAL_TERMS:
        # Count occurrences (case-insensitive)
        buzzword_count += text_lower.count(term.lower())
    
    # Density = buzzwords per 100 words
    density = (buzzword_count / total_words) * 100
    
    return density


def detect_prospection(text, is_conversation_reply=False):
    """
    Intelligent spam detection with context analysis.
    
    Args:
        text: Message text to analyze
        is_conversation_reply: True if this is a reply in an existing thread
    
    Returns:
        (is_spam: bool, details: dict)
    """
    if not text:
        return False, {}
    
    text_lower = text.lower()
    
    # 1. Check if it's a reply in existing conversation
    detected_reply = is_reply_context(text)
    if is_conversation_reply or detected_reply:
        # Existing conversations get lower scrutiny
        spam_threshold = 0.8  # very high bar
    else:
        spam_threshold = 0.5  # normal threshold
    
    # 2. Analyze tone (authentic vs commercial)
    tone_score = analyze_tone(text)
    
    # 3. Calculate buzzword density
    buzzword_density = calculate_buzzword_density(text)
    
    # 4. Check for recruiting patterns (always flag)
    recruiting_matches = [term for term in RECRUITING_PATTERNS 
                         if term.lower() in text_lower]
    
    # 5. Check for generic openers (strong spam signal)
    generic_openers = [opener for opener in GENERIC_OPENERS 
                       if opener.lower() in text_lower]
    
    # 6. Check for commercial pitch patterns
    commercial_matches = [term for term in COMMERCIAL_TONE 
                         if term.lower() in text_lower]
    
    # 7. Cold outreach buzzwords
    cold_outreach_matches = [term for term in COLD_OUTREACH_BUZZWORDS 
                            if term.lower() in text_lower]
    
    # 8. Technical terms (only spam if high density + commercial tone)
    technical_matches = [term for term in TECHNICAL_TERMS 
                        if term.lower() in text_lower]
    
    # Calculate final spam score
    spam_score = 0.0
    reasons = []
    
    # Recruiting = instant high score
    if recruiting_matches:
        spam_score += 0.6
        reasons.append(f"recruiting keywords: {', '.join(recruiting_matches[:3])}")
    
    # Generic openers = strong signal
    if generic_openers:
        spam_score += 0.4
        reasons.append(f"generic opener: {generic_openers[0]}")
    
    # Commercial tone
    if tone_score > 0.7:
        spam_score += tone_score * 0.3
        reasons.append(f"commercial tone (score: {tone_score:.2f})")
    
    # Commercial pitch patterns (1 = moderate, 2+ = strong)
    if len(commercial_matches) >= 2:
        spam_score += 0.4
        reasons.append(f"commercial pitch: {', '.join(commercial_matches[:2])}")
    elif len(commercial_matches) == 1:
        spam_score += 0.2
        reasons.append(f"commercial keyword: {commercial_matches[0]}")
    
    # Cold outreach buzzwords (2+ = likely spam)
    if len(cold_outreach_matches) >= 2:
        spam_score += 0.3
        reasons.append(f"cold outreach: {', '.join(cold_outreach_matches[:2])}")
    
    # High buzzword density (3+ in short message or >10 per 100 words)
    if buzzword_density > 10 or (len(text.split()) < 50 and len(technical_matches) >= 3):
        spam_score += 0.3
        reasons.append(f"high buzzword density ({buzzword_density:.1f}%)")
    
    # Reduce score for authentic tone
    if tone_score < 0.3:
        spam_score -= 0.2
        reasons.append(f"authentic tone (score: {tone_score:.2f})")
    
    # Technical terms alone (1-2 in context) are NOT spam
    if technical_matches and len(technical_matches) <= 2 and tone_score < 0.5:
        # Valid technical discussion
        spam_score -= 0.1
    
    # Decision
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


def suggest_response(text, sender_name="", detection_details=None):
    """Generate a suggested response based on message content and language."""
    lang = detect_language(text)
    is_french = (lang == "fr")

    # Extract first name only (everything before first space)
    first_name = sender_name.split()[0] if sender_name else ""

    # Use detection details if available
    is_recruiting = False
    if detection_details and "matches" in detection_details:
        recruiting_matches = detection_details["matches"].get("recruiting", [])
        is_recruiting = len(recruiting_matches) > 0
    else:
        # Fallback to regex check
        is_recruiting = bool(re.search(r"recruit|hiring|position|role|poste|candidat|mission", text, re.I))

    if is_recruiting:
        template_key = "recruiter_fr" if is_french else "recruiter_en"
    else:
        template_key = "spam_fr" if is_french else "spam_en"

    template = RESPONSE_TEMPLATES.get(template_key, RESPONSE_TEMPLATES.get("spam_en", ""))
    return template.replace("{name}", first_name or "")


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
        
        # Count messages in this thread to determine if it's an ongoing conversation
        total_messages = len(messages)
        is_ongoing_conversation = total_messages > 2  # More than just initial exchange

        for idx, msg in enumerate(messages):
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
            
            # Check if this is a reply (not the first message from sender)
            is_reply = idx > 0 or is_ongoing_conversation

            # Detect spam with context
            is_spam, details = detect_prospection(text, is_conversation_reply=is_reply)

            if is_spam:
                suggestion = suggest_response(text, sender, details)
                result = {
                    "chat_id": chat_id,
                    "sender": sender,
                    "message_id": msg_id,
                    "text_preview": text[:200],
                    "text_full": text,  # Full message for review
                    "detection_details": details,
                    "suggested_response": suggestion,
                    "status": "pending_confirmation",
                }
                results.append(result)
                log.info(f"Prospection detected from {sender} (score: {details['spam_score']}, reasons: {', '.join(details['reasons'][:2])})")

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
        is_spam, details = detect_prospection(args.test_text)
        suggestion = suggest_response(args.test_text, detection_details=details) if is_spam else None
        result = {
            "is_prospection": is_spam,
            "detection_details": details,
            "suggested_response": suggestion,
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if is_spam:
                print(f"🎯 Prospection detected!")
                print(f"   Spam score: {details['spam_score']:.2f} (threshold: {details['threshold']})")
                print(f"   Tone score: {details['tone_score']:.2f} (0=authentic, 1=commercial)")
                print(f"   Buzzword density: {details['buzzword_density']:.1f}%")
                print(f"   Reasons: {', '.join(details['reasons'])}")
                if suggestion:
                    print(f"\n💬 Suggested response:\n{suggestion}")
            else:
                print("✅ Not detected as prospection")
                print(f"   Spam score: {details['spam_score']:.2f} (threshold: {details['threshold']})")
                print(f"   Reasons: {', '.join(details['reasons']) if details['reasons'] else 'No spam indicators'}")
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
