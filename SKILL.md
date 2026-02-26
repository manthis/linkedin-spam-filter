---
name: beeper-linkedin
description: "Detect and filter LinkedIn spam/prospection messages via Beeper MCP. Scans LinkedIn DMs, analyzes patterns, suggests responses with confirmation workflow. Use when asked to filter LinkedIn messages, detect prospection, or manage LinkedIn DMs via Beeper."
homepage: https://github.com/manthis/linkedin-spam-filter
metadata: { "openclaw": { "emoji": "💼", "requires": { "bins": ["mcporter", "python3"] } } }
---

# openclaw-skill-linkedin-spam-filter

Detect LinkedIn spam/prospection messages via Beeper MCP. Generates suggested responses with confirmation workflow.

## Usage

```bash
# Check LinkedIn messages
python3 scripts/linkedin-spam-filter.py [--dry-run] [--json]

# Test detection on text
python3 scripts/linkedin-spam-filter.py --test-text "Hi, I have an exciting opportunity..."
```

## Configuration (env vars)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BEEPER_SERVER` | | `beeper` | Beeper MCP server name |
| `MCPORTER_CMD` | | `mcporter` | mcporter CLI path |
| `LINKEDIN_ROOM_PATTERN` | | `linkedin` | Pattern to match LinkedIn rooms |
| `SPAM_PATTERNS` | | (built-in) | Regex patterns for detection |
| `RESPONSE_TEMPLATES` | | (built-in) | JSON templates for responses |
| `LINKEDIN_STATE` | | `~/.openclaw-linkedin-state.json` | State file |
| `LINKEDIN_LOG` | | `~/logs/linkedin-spam-filter.log` | Log file |

## Workflow

1. **Detect** — Scans LinkedIn DMs via Beeper MCP
2. **Analyze** — Matches against prospection patterns
3. **Suggest** — Generates response (FR/EN auto-detect)
4. **Notify** — Reports to agent for confirmation
5. **Send** — After human confirmation (not auto-sent)

## Dependencies

- `mcporter` CLI with Beeper MCP configured
- Python 3.8+

## OpenClaw Integration

```yaml
cron:
  - name: "LinkedIn Spam Filter"
    schedule: "0 */6 * * *"
    command: "python3 scripts/linkedin-spam-filter.py --json"
```
