# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 3.0.x   | ✅        |
| 2.0.x   | ✅        |
| < 2.0   | ❌        |

## Reporting a Vulnerability

**Please do not file a public GitHub issue for security problems.**

Instead, open a private security advisory at:

> <https://github.com/NaustudentX18/MiBud/security/advisories/new>

Include:

- Affected version / commit SHA
- A clear description of the vulnerability
- Reproduction steps and proof-of-concept (where possible)
- Your assessment of impact (data exposure, RCE, DoS, etc.)

We aim to acknowledge reports within **72 hours** and ship a fix or
mitigation plan within **14 days** for confirmed High/Critical issues.

## Threat model

MiBud runs locally on a Raspberry Pi and ships a small Flask web UI on the
LAN. We treat the following as in-scope:

- **Web API auth bypass** — endpoints that should require the PIN but don't.
- **Path traversal** — particularly in backup restore (`core/backup.py`),
  config file handling, and personality JSON loading.
- **MCP / plugin sandbox escape** — a malicious plugin or MCP server gaining
  more access than intended (note: plugins are explicitly opt-in and
  trusted-by-default — but unintended exposure of secrets/PII is in scope).
- **Secrets exposure** — `.env` contents written to disk-tracked locations,
  leaked in API responses, or copied into backups.
- **Memory DB exposure** — long-term memory readable without auth.

The following are **out of scope**:

- Physical attacks on the Pi itself.
- Issues requiring an attacker who already has shell access.
- DoS that needs sustained traffic to a self-hosted device.
- Cloud LLM provider issues — report those upstream.

## Hardening checklist (v3)

- All write/read endpoints (except `/api/health`) require a PIN once setup
  completes (`web/auth.py`).
- Backup restore uses a path-traversal-safe `_safe_extractall()` and rejects
  newer schemas without `force=True` (`core/backup.py`).
- `.env`, `.pem`, `.key` files are excluded from backup tarballs.
- API errors return clean JSON with no traceback leakage
  (verified by `tests/test_web_errors.py`).
- HA token never persisted to `config.json`.

Thanks for helping keep MiBud users safe.
