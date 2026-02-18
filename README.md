# 🎯 openclaw-skill-linkedin-prospection

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![OpenClaw Skill](https://img.shields.io/badge/OpenClaw-Skill-blue)](https://github.com/OpenAgentsInc/openclaw)

Detect LinkedIn prospection and spam messages via Beeper MCP. Auto-generates suggested responses (FR/EN) with human-in-the-loop confirmation.

## Quick Start

```bash
git clone https://github.com/manthis/openclaw-skill-linkedin-prospection.git
cd openclaw-skill-linkedin-prospection

# Test detection locally
python3 scripts/linkedin-prospection.py --test-text "Hi, I have an exciting opportunity for you"

# Full check (requires Beeper MCP)
export BEEPER_SERVER="beeper"
python3 scripts/linkedin-prospection.py --dry-run --json
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `BEEPER_SERVER` | `beeper` | Beeper MCP server name |
| `LINKEDIN_ROOM_PATTERN` | `linkedin` | Room name filter |
| `SPAM_PATTERNS` | (built-in) | Detection regex |
| `RESPONSE_TEMPLATES` | (built-in) | JSON response templates |

> ⚠️ **Security:** Never store MCP tokens or credentials in config files.

## Features

- 🔍 Pattern-based prospection detection (FR + EN)
- 💬 Auto-generated response suggestions
- 🌍 Language auto-detection (French/English)
- 🛡️ Human-in-the-loop — never auto-sends
- 📊 JSON output for automation
- 🧪 Standalone test mode (`--test-text`)

## Requirements

- Python 3.8+
- `mcporter` CLI with Beeper MCP (for live checks)

## License

MIT
