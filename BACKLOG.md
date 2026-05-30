# CrabCakes Backlog

## Keyring Integration for API Keys

**Priority:** Medium
**When:** Before public release or multi-user support

Integrate `keyring` library for API key storage with graceful fallback to plaintext.

**Requirements:**
- Try system keyring (libsecret/GNOME Keyring) first on read/write
- If keyring unavailable (locked, no daemon), fall back to current plaintext path (0o600/0o700)
- Migrate existing plaintext keys to keyring on first successful access
- No disruption to existing setups — fallback must be seamless
- Add `keyring` to `pyproject.toml` dependencies

**Why:** LLM API keys are bearer tokens for billable cloud services. Higher-value credential than typical local secrets like SSH keys. The "everyone stores in plaintext" argument is weak for remotely-billable tokens.

**Context:** Raised in security review (2026-05-29). Pushback on Finding 3 was valid. See `docs/THREAT_MODEL.md` § Attack Surface 3.
