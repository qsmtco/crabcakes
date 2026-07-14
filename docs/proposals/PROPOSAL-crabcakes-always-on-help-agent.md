# PROPOSAL: Crabcakes — Always-On Help Agent

**Date:** 2026-05-30
**Author:** Qaster
**Status:** ⚠️ PARTIALLY DONE — help agent exists with `auto_open: true` and `auto_add_to_projects: true` in `crabcakes.yaml`; system prompt at `prompts/system/crabcakes.md`; auto-open at `ui/window.py:167-179`. However, it has no built-in provider key (uses `openrouter` by default), so fresh installs get `RuntimeError: no provider configured`. Superseded by `PROPOSAL-auxilium-three-tier-help-agent.md`.

> **Status (verified 2026-06-12):** ⚠️ **PARTIALLY DONE** — 
> **status:** `PARTIAL` — sortable tag for `ls | grep STATUS` The help agent **is** implemented. Evidence: `prompts/system/crabcakes.md` (3.8K, May 30) is the help agent's system prompt; `~/.config/crabcakes/agents/crabcakes.yaml` has `auto_open: true` and `auto_add_to_projects: true`; `agent/special_agents.py:44-46` has the `auto_open` and `auto_add_to_projects` fields; `ui/window.py:167-179` opens a tab for each `auto_open` agent on app launch. The `SPEC-crabcakes-always-on-help-agent.md` (55K, May 30) exists and describes the full implementation plan. However, the SPEC is still in **"Draft — for implementation"** status — meaning the Captain never formally approved it. The core features (system prompt + auto-open) are live, but the full SPEC scope (per-conversation context injection, built-in provider, team.json integration) may be partially implemented. **Marked PARTIAL; full spec approval and implementation audit needed.**
**Priority:** High
**Effort:** ~8-12 hours

---

## Why

### The Problem

New users open Crabcakes and see an empty app. No agent tabs, no guidance, no help. They must already have an OpenClaw gateway running and API keys configured to get any value. The learning curve starts with a cliff.

Even experienced users have no in-app reference. Questions like "how do slash commands work?" or "why won't my agent connect?" require leaving the app to check docs. There's no one home.

### The Solution

Ship Crabcakes with an always-on help agent — a pre-configured local agent (like Coder and Debugger) that opens automatically every time the app launches. It works out of the box with zero configuration, answers questions about anything Crabcakes-related, and pulls its knowledge base live from GitHub so it's always up to date.

**It's the app's voice.** When you open Crabcakes, the first tab is "Crabcakes" 🦀 — your assistant, always at their desk.

### Why Now

- Crabcakes is approaching launch — new users need a guided experience
- The agent runtime infrastructure (Phase 1.4) fully supports this — YAML definition + system prompt + auto-registration
- Free-tier LLM APIs (Google Gemini) make zero-config AI assistance possible at no cost
- Knowledge base can live on GitHub and be read live — no app releases needed for doc updates

---

## What

### Before (current)

App opens to an empty workspace. No agent tabs visible. User must manually configure API keys, connect to a gateway, and discover agents before any conversation can happen. The Agents tab shows Coder and Debugger but neither auto-opens and both require a configured provider.

### After (proposed)

App opens with a "Crabcakes" 🦀 tab already open and ready. The agent greets the user and can immediately answer questions about setup, features, configuration, troubleshooting — anything about the app. No configuration required. The knowledge base is read live from GitHub, so updating docs there instantly updates what every user's Crabcakes agent knows.

### Agent Definition

| Field | Value |
|-------|-------|
| **Name** | Crabcakes |
| **Emoji** | 🦀 |
| **Role** | `crabcakes` (maps to `prompts/system/crabcakes.md`) |
| **Type** | Local special agent (runs against LLM API, no gateway needed) |
| **Default Provider** | `google` (Gemini 2.0 Flash — free tier) |
| **Default Model** | `gemini-2.0-flash` |
| **Tools** | `read_file`, `list_files`, `web_search`, `web_fetch` |
| **Can Write** | No — read-only |
| **Auto-Open** | Yes — every launch |
| **Built-in Key** | Yes — ships with free-tier Google Gemini key |

### Key Behaviors

1. **Auto-opens on every launch.** The Crabcakes tab is always the first tab, always visible. Not just first run — every time. Like walking into the office and your assistant is already at their desk.

2. **Works with zero config.** Ships with a built-in Google Gemini free-tier API key. No signup, no API keys, no gateway. Open the app, start chatting.

3. **Reads knowledge live from GitHub.** No local cache, no sync, no stale docs. When the agent needs to look something up, it fetches the relevant file directly from `https://raw.githubusercontent.com/qsmtco/crabcakes/main/knowledge/`. Update a doc on GitHub → every user's agent knows about it immediately.

4. **Upgrades gracefully.** When the user configures their own API keys (which the agent helps them do), it switches to their provider. Better models, no shared rate limits.

5. **General help, not just setup.** Answers anything about Crabcakes: features, commands, architecture, troubleshooting, tips. It's the app's permanent help desk.

6. **Conversation persists.** The conversation is saved and restored across restarts (via existing `conversations/` persistence). On subsequent opens, the agent doesn't re-greet — it waits for the user to ask something.

---

## Technical Design

### LLM Provider — Google Gemini Free Tier

The built-in provider uses Google Gemini 2.0 Flash via the OpenAI-compatible endpoint.

| Factor | Details |
|--------|---------|
| **Free tier** | 1,500 requests/day, 1M tokens/min — permanent, not a trial |
| **No credit card** | Key created in Google AI Studio with just a Google account |
| **OpenAI-compatible** | Supports `/v1/chat/completions` — works with our existing `_call_openai()` adapter |
| **Quality** | Gemini 2.0 Flash is fast and capable for Q&A/help |
| **Rate limits** | 15 RPM, 1M TPM, 1,500 RPD — generous for a help bot |
| **Cost** | $0/month on free tier |

**API configuration:**
```json
{
  "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
  "api_key": "<free-tier key>",
  "default_model": "gemini-2.0-flash"
}
```

**Shared key strategy:** The built-in key is a free-tier key, not a secret. It ships in open-source code with rate limits. If abused, we rotate it in a new release. When users configure their own `google` provider in `agent.json`, their key takes priority.

### Knowledge Base — Live GitHub Reads

Seven documentation files live in the repo at `knowledge/`. The agent reads them on demand using `web_fetch` — no local caching, no sync, no stale data.

```
knowledge/
├── setup.md              # Installation & first-run guide
├── configuration.md      # All config options, env vars, agent.json
├── agents.md             # How agents work, Coder/Debugger, custom agents
├── features.md           # Feature overview: projects, prompts, commands, group chat
├── commands.md           # Slash command reference
├── gateway.md            # OpenClaw gateway connection
└── troubleshooting.md    # Common issues & fixes
```

**How it works:**
1. User asks a question
2. System prompt instructs the agent to `web_fetch` the relevant knowledge file from GitHub
3. Agent reads the content, answers based on it
4. If GitHub is unreachable, the agent answers from its system prompt knowledge (basic answers) and notes that detailed docs are unavailable offline

**Why live reads instead of cache:**
- Knowledge is always current — update GitHub, done
- No sync timing, no stale cache, no local file management
- Simpler architecture — no `knowledge_sync.py`, no cache directory, no sync marker files
- Offline graceful degradation via system prompt baked-in knowledge

### System Prompt

The system prompt (`prompts/system/crabcakes.md`) gives the agent its personality, instructions, and basic knowledge. Detailed knowledge is fetched on demand from GitHub.

Key instructions in the prompt:
- Reference `knowledge/{file}.md` files via `web_fetch` for detailed answers
- Friendly, concise, helpful tone
- Don't over-explain — give the answer, then offer more detail
- Use markdown formatting for clarity
- For code changes, suggest the user ask the Coder agent
- For debugging, suggest the Debugger agent
- Greet naturally on new conversations, stay quiet on existing ones

### Auto-Open Mechanism

New fields on `SpecialAgentDef`:
- `auto_open: bool = False` — signals `window.py` to open this agent's tab on every launch
- `api_key_built_in: bool = False` — signals this agent has a built-in API key

In `window.py._build()`, after special agents are registered:
```python
from agent.special_agents import get_auto_open_agents
for agent_def in get_auto_open_agents():
    self._main_content.create_chat_tab(agent_def.conv_id_prefix, agent_def.display_name)
```

`create_chat_tab()` already handles the "switch to existing tab" case — if the tab exists from a previous session, it just focuses it.

### Built-in Provider Injection

In `agent/config.py`, the built-in Google provider is injected after loading `agent.json`:
```python
# After parsing user-configured providers:

# Inject built-in Google provider if not user-configured
if "google" not in providers:
    providers["google"] = LLMProviderConfig(
        name="google",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key=_BUILT_IN_GOOGLE_KEY,
        default_model="gemini-2.0-flash",
        supports_tools=True,
        supports_streaming=True,
        max_tokens=1_000_000,
    )
```

This means:
- Out of the box: built-in Google key works
- User adds their own `google` provider: their key takes priority
- User adds a different provider (OpenAI, MiniMax): the built-in Google provider still exists as a fallback

---

## Architecture Compliance

**Per ARCHITECTURE.md:**

| Rule | Compliance |
|------|-----------|
| §2 Directory structure | ✅ New files follow existing patterns. No new packages. |
| §3.2 `gateway/` no UI deps | ✅ No changes to `gateway/` |
| §3.3 `models/` pure data | ✅ No changes to `models/` |
| §3.5 CSS in `ui/styles.py` | ✅ No new CSS needed — the agent uses existing chat bubble styles |
| §3.6 `window.py` wires handlers | ✅ Window creates auto-open tabs, no business logic |
| Handler pattern (§3.16, §8.6) | ✅ Follows exact pattern of Coder/Debugger registration |
| `prompts/default_agents/*.yaml` | ✅ New YAML follows `coder.yaml` / `debugger.yaml` pattern |
| `prompts/system/*.md` | ✅ New system prompt follows existing template pattern |
| `agent/config.py` provider loading | ✅ Built-in provider injected alongside user providers |
| `agent/special_agents.py` registry | ✅ New fields added to existing dataclass, backward-compatible |

**No architectural violations.** Every change is additive — new files follow existing patterns, modifications extend existing data structures with defaults.

---

## File Changes

### New Files

| File | Lines | Purpose |
|------|-------|---------|
| `prompts/default_agents/crabcakes.yaml` | ~20 | Agent definition (like `coder.yaml`) |
| `prompts/system/crabcakes.md` | ~60 | System prompt + personality |
| `knowledge/setup.md` | ~80 | Installation & first-run guide |
| `knowledge/configuration.md` | ~100 | Config options, env vars, agent.json |
| `knowledge/agents.md` | ~80 | Agent system overview |
| `knowledge/features.md` | ~100 | Feature how-tos |
| `knowledge/commands.md` | ~80 | Slash command reference |
| `knowledge/gateway.md` | ~60 | OpenClaw gateway connection |
| `knowledge/troubleshooting.md` | ~80 | Common issues & fixes |
| `docs/SPEC_CRABCAKES_AGENT.md` | ~300 | Implementation spec |

### Modified Files

| File | Change | Lines | Risk |
|------|--------|-------|------|
| `agent/special_agents.py` | Add `auto_open`, `api_key_built_in` fields + `get_auto_open_agents()` | ~15 | Low — additive dataclass fields with defaults |
| `agent/config.py` | Built-in Google provider injection + `_BUILT_IN_GOOGLE_KEY` constant | ~25 | Low — additive, only activates if provider not configured |
| `utils/agent_defs.py` | Parse `auto_open` and `api_key_built_in` from YAML | ~10 | Low — `dict.get()` with defaults |
| `ui/window.py` | Auto-open Crabcakes agent tab in `_build()` | ~5 | Low — 3 lines, calls existing `create_chat_tab()` |
| `docs/ARCHITECTURE.md` | Update §2, §3, §11 for new files | ~30 | Low — documentation |

### Deleted Files

None.

### Total: ~580 net lines | ~85 lines modified

---

## Scope

| In Scope | Out of Scope |
|----------|-------------|
| Agent YAML definition | Custom agent builder UI changes |
| System prompt with GitHub knowledge fetching | Local/embedded LLM (Ollama, etc.) |
| Built-in Google Gemini free-tier provider | Other free-tier providers (Groq, etc.) |
| Auto-open tab on every launch | First-launch-only detection |
| Live GitHub knowledge reads | Knowledge file editor in UI |
| 7 knowledge base .md files in repo | Knowledge file auto-generation from docs |
| Graceful provider upgrade (user key overrides built-in) | Multi-provider fallback chain |
| Conversation persistence across restarts | Conversation reset/clear UI |

---

## Security Considerations

| Concern | Mitigation |
|---------|-----------|
| Built-in API key visible in source code | Free-tier key with rate limits, not a secret. Comparable to Google Maps embed keys. |
| Key abuse exhausting daily quota | Rate limits per-key. Rotate in new release if abused. Upgrade path: user configures own key. |
| User conversations sent to Google | Free-tier Gemini ToS allows Google to use prompts for training. Mitigated when user provides own key. Will document in `knowledge/privacy.md` if needed. |
| Agent reading arbitrary files | `read_file` + `list_files` only. System prompt instructs agent to stay within knowledge/ and project docs. Runtime enforces tool allowlist. |
| GitHub knowledge fetching privacy | Fetches public repo files. No auth, no tracking. Standard HTTPS. |

---

## Knowledge Base Content Plan

Each file targets < 3KB for fast fetching. Written in user-facing language (not developer docs). Self-contained — each file answers its topic completely.

| File | Content |
|------|---------|
| `setup.md` | Installation (pip/flatpak/source), dependencies, first-run experience, what you see |
| `configuration.md` | `agent.json` schema, environment variables, config directory layout, provider setup |
| `agents.md` | Coder, Debugger, custom agents, agent builder, how to add API keys, provider options |
| `features.md` | Projects, prompts, prompt library, group chat, slash commands, MCP, file browser, review layer |
| `commands.md` | Full slash command reference with syntax and examples |
| `gateway.md` | OpenClaw gateway setup, WebSocket URL, device auth, multi-agent discovery, connecting |
| `troubleshooting.md` | Connection errors, API key issues, missing dependencies, GTK4 problems, known bugs |

---

## Acceptance Criteria

- [ ] "Crabcakes" 🦀 agent YAML exists in `prompts/default_agents/crabcakes.yaml`
- [ ] System prompt exists at `prompts/system/crabcakes.md` with personality and GitHub knowledge instructions
- [ ] 7 knowledge base files exist in `knowledge/` directory
- [ ] Agent auto-opens on every app launch — tab is visible and focused when window appears
- [ ] Agent works with zero configuration — no API keys, no gateway, no setup needed
- [ ] Built-in Google Gemini provider injected automatically when user hasn't configured `google`
- [ ] Agent can answer questions about Crabcakes setup, features, and configuration
- [ ] Agent uses `web_fetch` to read knowledge files from GitHub on demand
- [ ] When user configures their own API keys, Crabcakes agent uses those instead of built-in
- [ ] Conversation persists across app restarts (existing persistence mechanism)
- [ ] Agent does not re-greet on subsequent launches with existing conversation
- [ ] Graceful offline behavior — agent can answer basic questions from system prompt when GitHub unreachable
- [ ] No impact on Coder, Debugger, or other existing special agents
- [ ] ARCHITECTURE.md updated with new files, modules, and data flow

---

## Future Enhancements (Not In Scope)

1. **Privacy-focused mode** — Option to disable GitHub fetching, rely only on system prompt knowledge
2. **Multi-provider fallback** — If Google key is rate-limited, fall back to Groq free tier, etc.
3. **Knowledge file auto-generation** — Script to generate `knowledge/*.md` from `docs/` at release time
4. **User feedback loop** — "Was this helpful?" tracking to improve knowledge base coverage
5. **Proactive tips** — Agent notices what the user is doing and offers relevant tips ("I see you opened a project — did you know about group chat?")
6. **Changelog announcements** — Agent reads `CHANGELOG.md` from GitHub and tells users about new features after updates

---

## Why This Is The Right Scope

This proposal makes Crabcakes immediately useful to everyone who opens it. The first experience is no longer an empty workspace — it's a conversation with an expert who knows the app inside and out. The live GitHub knowledge base means the documentation evolves independently of app releases. The built-in free-tier key means zero friction.

The architecture already fully supports this. The agent runtime, special agent registry, YAML definitions, system prompt templates, and conversation persistence are all built and working. This proposal is purely additive — new files that follow existing patterns, and small extensions to existing data structures with backward-compatible defaults.

The name says everything: the tab is "Crabcakes" because the agent IS the app. It's the app's voice, always there, always ready.
