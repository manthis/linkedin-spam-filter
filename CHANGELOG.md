# LinkedIn Spam Filter - Changelog

## 2026-02-19 - Context-Aware Detection

### Problem Fixed
**False Positive:** Messages from Philippe Fischer were incorrectly flagged as spam due to the keyword "RAG" (Retrieval Augmented Generation) appearing in legitimate technical discussions about security architecture.

### Root Cause
Previous detection used simple keyword matching without context analysis. A single technical term like "RAG" would trigger spam detection even in authentic professional conversations.

### Improvements Implemented

#### 1. **Conversation Context Analysis**
- Detects if message is a reply vs cold outreach
- Existing conversation threads get higher spam threshold (0.8 vs 0.5)
- Reply indicators: "thanks for your message", "as you mentioned", "following up", etc.

#### 2. **Tone Analysis** 
- Distinguishes authentic/personal tone from generic/commercial pitch
- **Authentic markers** (reduce spam score):
  - "ton approche", "if you're interested", "I think", "personally"
- **Commercial markers** (increase spam score):
  - "we help", "our solution", "we specialize", "nous proposons"
- Tone score: 0.0 (authentic) to 1.0 (commercial)

#### 3. **Buzzword Density Analysis**
- Calculates density of technical buzzwords vs message substance
- 1-2 technical terms in context → legitimate
- 3+ buzzwords in short message or >10% density → spam
- Context matters: "RAG" alone in technical discussion = OK

#### 4. **Multi-Factor Scoring**
Spam detection now combines multiple signals:
- Recruiting keywords: +0.6
- Generic openers ("I came across your profile"): +0.4
- Commercial tone (>0.7): +0.3
- High buzzword density: +0.3
- Cold outreach buzzwords (2+): +0.3
- Commercial pitch patterns (2+): +0.4
- Authentic tone (<0.3): -0.2

#### 5. **Category-Based Keywords**
Instead of one big regex, keywords are now categorized:
- `RECRUITING_PATTERNS`: job-related keywords
- `COMMERCIAL_TONE`: sales pitch indicators
- `COLD_OUTREACH_BUZZWORDS`: synergy, scale, quick call, etc.
- `TECHNICAL_TERMS`: RAG, AI, encryption, etc. (NOT spam alone)
- `AUTHENTIC_MARKERS`: personal/genuine tone indicators
- `GENERIC_OPENERS`: "I came across your profile", etc.

### Test Results

✅ **Philippe's message (technical discussion):**
```
"Salut, ton approche est solide sur l'architecture de sécurité. 
Si ça t'intéresse, on pourrait discuter de RAG et encryption 
pour ton système. Qu'en penses-tu ?"
```
- Result: **NOT SPAM** (score: 0.10 / threshold: 0.5)
- Reason: Authentic tone detected, technical context valid

✅ **Generic spam with buzzwords:**
```
"Bonjour, nous proposons une solution innovante avec RAG et 
synergy pour transformer votre entreprise. Notre plateforme 
aide les équipes à scaler rapidement."
```
- Result: **SPAM** (score: 0.80 / threshold: 0.5)
- Reasons: Commercial keywords, cold outreach buzzwords, high density

✅ **Reply in conversation:**
```
"Merci pour ta réponse. Pour répondre à ta question, notre 
plateforme aide les équipes avec RAG et AI features."
```
- Result: **NOT SPAM** (score: 0.30 / threshold: 0.8)
- Reason: Reply context detected, higher threshold applied

### Technical Changes

- Replaced simple regex matching with multi-factor analysis
- Added `is_reply_context()` to detect conversation replies
- Added `analyze_tone()` to score authentic vs commercial tone
- Added `calculate_buzzword_density()` for contextual keyword analysis
- Updated `detect_prospection()` signature: returns `(is_spam: bool, details: dict)`
- Enhanced `--test-text` output to show detailed scoring breakdown

### Backward Compatibility
- Existing state files and configuration remain compatible
- Response templates unchanged
- MCP integration unchanged
- Command-line interface enhanced but backward compatible
