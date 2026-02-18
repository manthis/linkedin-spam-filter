# openclaw-skill-linkedin-prospection

Detect LinkedIn prospection/spam messages via Beeper MCP. Generates suggested responses with confirmation workflow.

## Usage

```bash
# Check LinkedIn messages
python3 scripts/linkedin-prospection.py [--dry-run] [--json]

# Test detection on text
python3 scripts/linkedin-prospection.py --test-text "Hi, I have an exciting opportunity..."
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
| `LINKEDIN_LOG` | | `~/logs/linkedin-prospection.log` | Log file |

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
  - name: "LinkedIn Check"
    schedule: "0 */6 * * *"
    command: "python3 scripts/linkedin-prospection.py --json"
```
