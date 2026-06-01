# CrabCakes Security & Quality Review Report

**Date:** 2026-05-29
**Reviewer:** Qaster (with Captain JAQx)
**Scope:** Security audit findings raised during review session

---

## Summary

Five findings were raised during a review of the CrabCakes codebase. Of the five, two resulted in code changes (low-effort, proportional fixes), and three were assessed as valid observations but not worth acting on given the current threat model and project maturity.

**Key principle applied throughout:** CrabCakes is a single-user desktop development tool running on the developer's own machine. The threat model is "trusted user, trusted agents, local machine." Recommendations that assume untrusted actors or multi-tenant environments were deferred.

---

## Finding 1: No Dependency Manifest

**Severity:** Medium (quality/UX, not security)
**Status:** ✅ Fixed — `bf76617`

**The Problem:** The README listed `pip install pygobject websockets cryptography gitpython inline` with no pinned versions and no dependency file. No reproducible installs, no version constraints.

**Our Assessment:** This was the most impactful finding. Not a security issue — a developer experience problem. New contributors (or future-you) have no idea which versions work. PyGObject 3.42 vs 3.48 have API differences. Websockets 11 vs 13 have breaking changes.

**What We Did:** Added `pyproject.toml` with pinned minimum versions based on the actually-installed versions:

```
PyGObject>=3.48
websockets>=12.0
cryptography>=41.0
GitPython>=3.1
```

Note: `inline` was listed in the README but not imported anywhere in the codebase. Dropped from dependencies.

**What We Did NOT Do:** No lockfile, no Dependabot, no pip-audit. CrabCakes is not a library or a service — it's a desktop app. Reproducible CI and automated scanning add process without proportional benefit at this stage.

---

## Finding 2: Pickle Deserialization Risk

**Severity:** Low (theoretical, private repo)
**Status:** ✅ Mitigated — `535d146` (documentation)

**The Problem:** `converge/model.pkl` and `vectorizer.pkl` are committed binary artifacts loaded via `joblib` (pickle under the hood). Pickle deserialization is arbitrary code execution. A malicious `.pkl` file in the repo could RCE any machine that loads it.

**Our Assessment:** The risk is real in theory but doesn't match the threat model. This is a private repo with two contributors. The `.pkl` files are generated locally by us, not downloaded from untrusted sources. For a supply chain attack to work, someone would need to get a malicious PR merged — and we review everything.

**What We Did:** Added a security comment in `converge/converge.py` above the `joblib.load` calls documenting the risk and specifying the remediation path if the repo ever goes public:

```python
# SECURITY NOTE: .pkl files are loaded via joblib (pickle under the hood).
# Pickle deserialization is an arbitrary code execution vector. These files
# are generated locally and committed to a private repo, so the risk is low.
# If this repo ever accepts external contributions or goes public:
#   - .gitignore the .pkl files
#   - Ship a training script (converge/train.py) that generates them
#   - Document the training data and process
```

**What We Did NOT Do:** No switch to ONNX/JSON export (adds `onnxruntime` dependency for no current benefit). No joblib hash verification (verifying hashes of files we generated ourselves is security theater). No training script refactor (premature — the model is a local TF-IDF classifier, not a distributed artifact).

---

## Finding 3: API Key Plaintext Storage

**Severity:** Low (standard for single-user desktop tools)
**Status:** ✅ Hardened — `3ea0ff2`

**The Problem:** API keys stored in plaintext in `~/.config/crabcakes/agent.json`. Any process running as the user can read it.

**Our Assessment:** This is how virtually every developer tool handles keys. Your SSH keys in `~/.ssh/`, your Git credentials, your AWS CLI config, your `.env` files — all plaintext, all readable by your user. The system keyring (`secretstorage`/`keyring`) is the "right" answer architecturally, but it adds fragility: no keyring daemon on headless servers, unlock prompts on some desktops, doesn't exist in CI. The `keyring` library is a nice abstraction until it breaks in environments you haven't tested.

**What We Did:** The codebase already had good practices — `0o600` on the config file, a warning on startup if permissions are loose. We added enforcement of `0o700` on the config directory itself (same protection SSH uses for `~/.ssh/`):

- `_create_default_config()` now sets `os.chmod(dir_path, 0o700)` on creation
- `_fix_config_dir_permissions()` runs on every config load, auto-tightening if needed
- Logged as info, not warning — non-disruptive, automatic

**What We Did NOT Do:** No `keyring` library integration. No encrypted keystore. No credential rotation mechanism. All of these would add complexity and fragility disproportionate to the actual risk on a single-user desktop app.

---

## Finding 4: Shell Execution Trust Boundary

**Severity:** Acknowledged (by design, not a vulnerability)
**Status:** No code changes — correct as-is

**The Problem:** Three sub-questions were raised:
1. Are shell commands sandboxed (chroot, namespace, container)?
2. What prevents write-then-execute bypass of the approval gate?
3. Is the approval gate in the runtime or the UI?

**Our Assessment:**

**1. No sandbox.** Commands run directly on the host as the user. This is intentional. CrabCakes is a development tool — sandboxing breaks filesystem access, Docker, git, networking. Developers need these. If isolation is needed, that's OpenClaw's job at the gateway level, not CrabCakes' responsibility.

**2. Write-then-execute is possible.** An agent could write a Python script via the file tool, then exec it. The approval gate only prompts on `exec` calls — file writes don't require approval. But the agent is already trusted code that you configured and gave tools to. If you don't trust it, don't give it exec access. The approval gate is a speed bump for accidents, not a security boundary against malicious agents.

**3. The gate is in the UI.** The agent runtime sends the command, the UI prompts, the user approves/denies. If you bypass the UI (direct API call), there's no gate. This is correct — the gate is a UX feature, not a security architecture.

**The real answer:** CrabCakes is a power tool, not a sandbox. The trust model is: you trust the agent you configured, running on your machine, as your user. If that trust breaks, no approval gate saves you — a malicious agent with file write access can plant persistence mechanisms that never need shell execution.

**What Would Change This:** If CrabCakes ever runs untrusted agents, namespace isolation via `podman` or `bwrap` would be the right approach. That's an OpenClaw-level feature requiring significant architecture work, not a CrabCakes patch.

---

## Finding 5: Manual Provider/Model Entry (Feature Request)

**Severity:** Enhancement
**Status:** ✅ Implemented — uncommitted in `ui/views/agent_builder.py`

**The Problem:** The agent edit dialog had hardcoded provider and model dropdowns (3 providers, ~7 models). No way to use a provider or model not on the list without editing source code.

**What We Did:** Added a "Manual" toggle button on the provider/model row. When toggled:
- Dropdowns hide, two text entries appear (provider ID, model ID)
- Pre-fills from current dropdown selection
- Tries to match back to dropdowns when toggled off
- Auto-switches to manual mode when editing an agent with an unknown provider or model
- Save button validates manual fields are non-empty

Single file change (`ui/views/agent_builder.py`), ~50 lines of new code, 37 existing tests pass.

---

## Commits

| Commit | Description |
|--------|-------------|
| `bf76617` | `feat: add pyproject.toml with pinned dependencies` |
| `535d146` | `docs: add security note about pickle deserialization risk` |
| `3ea0ff2` | `fix: enforce 0o700 on config dir containing API keys` |
| (uncommitted) | Manual provider/model toggle in agent builder |

---

## Pattern

The consistent theme: **proportional response to actual threat model.** Every finding was valid to raise. Not every finding requires code. Some just need documentation. Some need a one-line permissions fix. Some need nothing right now but should be revisited if the project's scope changes (public repo, untrusted agents, multi-user deployments).

The worst security posture is over-engineered security theater that adds complexity without adding protection. The second worst is ignoring real risks. We aimed for the middle: honest assessment, proportional fixes, documented decisions for future reference.
