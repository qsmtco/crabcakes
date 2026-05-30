# CrabCakes Threat Model

**Last updated:** 2026-05-29
**Status:** Living document — update when architecture or trust assumptions change.

---

## System Description

CrabCakes is a GTK4 desktop application that connects to an OpenClaw gateway via WebSocket (device-auth, operator role). It provides a chat interface for interacting with AI agents, managing projects, and executing development tasks. Agents can read/write files, execute shell commands (with user approval), and interact with external services via the gateway.

**Runtime context:**
- Runs as the local user on a Linux desktop
- GTK4 GUI (requires display server)
- Connects to OpenClaw gateway on localhost or remote host
- Agents execute tools (file I/O, shell) on the host machine

---

## Trust Boundaries

### Boundary 1: User ↔ CrabCakes

**Trust level: Fully trusted**

The user configures agents, approves shell commands, and controls the application. There is no adversarial relationship between user and application.

**Implications:**
- Config files (agent.json, agent YAML) are trusted input
- UI approval gates are UX features, not security boundaries
- The user is assumed to read and understand agent configurations before deploying them

### Boundary 2: CrabCakes ↔ OpenClaw Gateway

**Trust level: Trusted transport, authenticated**

Connection is authenticated via Ed25519 device keys. The gateway is assumed to be under the user's control (localhost or trusted remote).

**Implications:**
- Gateway events are trusted data
- Session keys and message content are not tampered with in transit
- Gateway is responsible for agent lifecycle, not CrabCakes

### Boundary 3: CrabCakes ↔ Agent Runtime

**Trust level: Varies — see Agent Trust Tiers below**

Agents run locally with tool access (file I/O, shell execution). The level of trust depends on the agent's origin and configuration.

### Boundary 4: CrabCakes ↔ Host System

**Trust level: Full access, user-level**

CrabCakes and its agents run as the local user. They have access to everything the user can access — filesystem, network, processes. This is by design.

**Implications:**
- No sandboxing, no namespace isolation, no containerization
- File writes go directly to the host filesystem
- Shell commands execute as the user via the host shell
- Network access is unrestricted

---

## Agent Trust Tiers

### Tier 1: User-Configured Agents (Current Default)

**Trust: High**

Agents the user creates via the agent builder, with known system prompts, known tools, and known provider/model configurations. These are extensions of the user's intent.

**Assumptions:**
- The user chose the system prompt and tools
- The user trusts the LLM provider not to be actively malicious
- The agent acts in the user's interest

**Protection needed:** Accidental damage only (approval gates, confirmation dialogs).

### Tier 2: Community/Shared Agents (Future)

**Trust: Medium**

Agents shared by other users or loaded from external sources. System prompts may not be fully audited. Tool configurations may grant more access than the user realizes.

**Assumptions:**
- The agent prompt may contain instructions the user hasn't fully read
- The agent may attempt actions the user wouldn't explicitly approve
- The LLM provider may interpret prompts in unexpected ways

**Protection needed (when this tier is implemented):**
- Agent prompt review UI (show full system prompt before first run)
- Tool permission summary at agent launch
- Write-then-execute detection (flag when agent writes a file then tries to exec it)
- Optional namespace isolation via `bwrap` or `podman`
- Rate limiting on shell execution and file writes

### Tier 3: Untrusted Agents (Not Currently Supported)

**Trust: Low**

Agents from untrusted sources, potentially adversarial. Not currently a supported use case.

**Protection needed (if ever supported):**
- Full sandboxing (namespace isolation, filesystem mounts, network restrictions)
- No direct shell access — all operations through sandboxed tool implementations
- Resource limits (CPU, memory, time, file size)
- Audit logging of all agent actions

---

## Known Attack Surfaces

### 1. Shell Command Execution

**Current state:** Commands run directly on the host as the user. UI approval gate prompts before execution.

**Known bypass:** Write-then-execute. An agent can write a script to disk (no approval needed for file writes) and then execute it (approval needed, but the user sees only the exec command, not the file contents).

**Risk today (Tier 1 agents):** Low. The agent is user-configured and trusted. Approval gate catches accidents.

**Risk with Tier 2 agents:** Medium. The user may not realize what the agent wrote to disk before executing it.

**Mitigation path:** When Tier 2 is implemented, add a pre-execution check that warns if the target file was written by an agent in the current session. Log all file writes with timestamps for audit trail.

### 2. File System Access

**Current state:** Agents can read and write files anywhere the user has access. No restrictions on paths.

**Risk:** An agent could overwrite important files (`~/.bashrc`, `~/.ssh/authorized_keys`, project source). The approval gate only applies to shell execution, not file writes.

**Mitigation path:** When Tier 2 is implemented, add configurable path restrictions per agent (whitelist of allowed directories). For Tier 1, the current open access is correct — developers need it.

### 3. API Key Exposure

**Current state:** API keys stored in `~/.config/crabcakes/agent.json` (plaintext, 0o600 file, 0o700 directory).

**Risk:** Any process running as the user can read the keys. LLM API keys are bearer tokens for billable cloud services — a leaked key can rack up significant charges.

**Acknowledged gap:** The "everyone does it this way" argument is weak for LLM keys specifically. SSH keys are used locally; LLM keys are billable remotely. This is a higher-value credential than a typical local secret.

**Mitigation path:** Integrate `keyring` library with graceful fallback to plaintext. Try system keyring (libsecret/GNOME Keyring) first; if unavailable, fall back to current plaintext storage. Zero disruption, strictly better when keyring is available. Tracked as backlog item.

### 4. Pickle Deserialization

**Current state:** `converge/model.pkl` and `vectorizer.pkl` loaded via `joblib` on startup.

**Risk:** Arbitrary code execution if a malicious `.pkl` is substituted.

**Mitigation:** Documented in `converge/converge.py` with remediation path for when repo goes public. Private repo, two contributors — risk is theoretical today.

### 5. Gateway WebSocket

**Current state:** Device-auth Ed25519, connection to localhost or trusted remote.

**Risk:** If gateway is compromised, attacker controls all agent communication. If connection is to a remote host, MITM could inject events.

**Mitigation:** Localhost connections are safe by definition. Remote connections should use WSS (TLS). Device-auth Ed25519 prevents impersonation. Gateway security is OpenClaw's responsibility.

---

## Threats NOT in Scope

- **Physical access to the machine:** If someone has physical access, game over regardless of software security.
- **Malware on the host:** If the host is compromised, CrabCakes security measures are irrelevant.
- **LLM provider compromise:** If the provider is malicious or compromised, it can inject arbitrary responses. CrabCakes cannot defend against this.
- **Supply chain attacks on dependencies:** `PyGObject`, `websockets`, `cryptography` — if these are compromised, CrabCakes is compromised. Standard hygiene (pinning versions, monitoring advisories) applies.

---

## When to Revisit This Document

- Adding support for community/shared agents (Tier 2)
- Adding support for untrusted agents (Tier 3)
- Adding multi-user support
- Making the repo public
- Adding network-accessible API endpoints to CrabCakes
- Integrating third-party plugins or extensions
- Significant changes to the gateway protocol

---

## References

- `docs/SECURITY_REVIEW_2026-05-29.md` — Original audit findings and disposition
- `agent/config.py` — API key storage and permission enforcement
- `converge/converge.py` — Pickle deserialization security note
- `ui/views/agent_builder.py` — Agent configuration UI
