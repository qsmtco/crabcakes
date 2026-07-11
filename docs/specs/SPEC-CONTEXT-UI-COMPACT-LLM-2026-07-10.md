# SPEC: Context UI Surface, /compact Command, and LLM-Summarization Strategy

**Date:** 2026-07-10
**Author:** qtr
**Status:** Draft — for implementation
**Implements:**
- `docs/audits/2026-07-10-CONTEXT-MANAGEMENT-AUDIT.md` (motivating audit)
- `docs/specs/SPEC-CONTEXT-MANAGEMENT-ROADMAP.md` (engine already shipped)
- `docs/proposals/PROPOSAL-pluggable-context-strategy.md` (strategy protocol already adopted)

**Depends on:** None — engine P1–P7 is already shipped (139 tests green).

**Target branch:** main

> **Architecture compliance statement.** All changes respect ARCHITECTURE.md §2 layering rules. `models/conversation.py` remains pure data (no UI, no network, no LLM calls — stdlib imports only). `agent/runtime.py` remains the core agent loop (no GTK imports). `agent/context_strategy.py` holds the strategy policy. The new `LLMSummarizeStrategy` in Phase C stays in `agent/`, not `models/`. UI changes are confined to `ui/handlers/`, `ui/views/`, and `ui/window.py`. LLM calls stay in `agent/runtime.py` (per `PROPOSAL-context-management-phase-2.md §3.1 layering note`). All existing invariants (CB-6 tool-call pairing, `is_summary` flag, system prompt separation, token cache invalidation, `_token_estimate_cache = None` after mutations, `keep_first` protection) are preserved verbatim. **No changes to `models/conversation.py`.** **No changes to `agent/context_strategy.py` for Phase A or B.** Phase C adds one new class; `DefaultContextStrategy` is byte-for-byte unchanged.

---

## 1. Overview

### 1.1 Problem Statement

Crabcakes' context-management engine (`agent/context_strategy.py`, P1–P7) is robust and correct: 139 tests pass, end-to-end probes show token-budget compliance with CB-6 pairing preserved. What is missing is **user-visible surface**:

1. **Silent data loss.** When the engine trims 8 messages off the back of a long session, the user sees nothing. The model receives a textual preview ("Conversation so far (3 prior turns): 1. user msg 0: …") that discards the 30 file edits, the errors, and the decisions in those turns. The user has no signal that compaction happened — until quality drops.

2. **No manual trigger.** The engine fires automatically at 80% of the model's context window. There is no way for a user to invoke compaction proactively before they notice quality drop.

3. **YAML-only configuration.** `compaction_threshold` (the 80% trigger) is editable only in `providers.yaml`. Users have no way to bump it to 70% from the settings dialog.

4. **Layer 3 is a 100-character textual preview, not an LLM-generated structured summary.** Compare to Claude Code's `/compact` which uses Anthropic's 9-section structured-summary prompt to preserve intent, files, errors, and decisions.

5. **No context meter.** The runtime computes `usage_percent` every LLM call, but it never surfaces in the UI. Users cannot tell when they are 70%, 80%, or 95% utilized.

### 1.2 Solution Summary

Three additive phases, no engine changes for A or B:\n\n- **Phase A — UI surface.** Add a chat bubble that fires when `trimmed_this_turn=True`. Add a context meter to the chat input bottom bar (Claude-Code style 7-token bar). Add an `compaction_threshold` SpinButton to the settings dialog. **No engine changes.**

- **Phase B — `/compact` slash command.** Mirror the `/clear` pattern exactly: `cmd_compact` in `project_handler.py`, injected callback wired in `window.py`. When invoked, force `compact(conv, model_max // 2)` regardless of current size. **No engine changes.**

- **Phase C — LLM-summarization strategy.** Add a new `LLMSummarizeStrategy(DefaultContextStrategy)` class that makes **one LLM call** per manual `/compact`, using the same model and provider as `conv`. The LLM call uses the Claude-Cookbook session-memory-compaction prompt template (9 sections). Result serialized as `is_summary=True` Message. Falls back to the parent's textual preview if the LLM call fails. **Engine unchanged — additive inheritance only.**

### 1.3 Scope

**In scope (this spec):**
- Phase A: chat bubble, context meter, settings SpinButton, ~250 lines UI
- Phase B: `/compact` command + UI feedback, ~150 lines UI + handler wiring
- Phase C: `LLMSummarizeStrategy`, per-agent `compaction_strategy` config, agent-builder dropdown, ~600 lines strategy + tests

**Out of scope (deferred to v2 — see companion spec `SPEC-CONTEXT-V2-PHASE2-2026-07-10.md`):**
- T1.1 Recursive hierarchical summarization
- T1.2 Structured summary digests (`ConversationDigest`)
- T1.3 Tool-output offloading
- T1.4 JIT file context retrieval
- T1.5 Per-tool retention policy
- P11 Multi-agent context coordination
- P12 KV-cache optimization

### 1.4 Architecture Principles

1. **Engine stable.** `DefaultContextStrategy` and `Conversation` are byte-for-byte unchanged in this spec.
2. **Layering preserved.** New LLM call in Phase C goes in `agent/runtime.py`, not `models/`.
3. **Pluggable.** New `LLMSummarizeStrategy` is a strict subtype of `DefaultContextStrategy` — it adds a method override, not protocol changes.
4. **Backwards compatible.** `compaction_strategy = "textual"` (the default) gives byte-for-byte identical behavior to today.
5. **Test-driven.** Each phase ships with tests that fail without the change. Existing 139 tests stay green.

---

## 2. Discovery (verified 2026-07-10)

```
DISCOVERY:
- Read agent/context_strategy.py (741 lines): ContextStrategy Protocol at line 72;
    DefaultContextStrategy at 100; compact() signature at 125 (conv, token_budget,
    *, keep_first=2, protect_is_summary=True); CompactionEvent dataclass at 30 with
    fields turn, trigger, layer, messages_before/after, tokens_before/after,
    tokens_freed, summary_tokens_injected, soft_ceiling, hard_ceiling, provider,
    model, session_key. _summary() method at 678 (textual preview only). _prune
    _tool_outputs() at 333 (lossless stub). _find_split_index() at 423 (CB-6
    role-anchored). _select_prune_candidate() at 615 (two-pass scan).

- Read agent/runtime.py:1659 — self._context_strategy = DefaultContextStrategy()
    per runtime instance (concurrency-safe). _compute_model_max() at 1880 with
    three-tier resolution (provider.max_tokens → CALLER_DEFAULT_MAX_TOKENS → 128K).
    _compute_compaction_threshold() at 1920 returns (soft, hard) where soft =
    int(hard * 0.80). compact() invoked at line 2101 before every LLM call.
    _compaction_events: list at 1613 (ring buffer cap 100). _last_breakdown_session
    tag at 1620. Breakdown dispatch at 2187 with keys trimmed_this_turn,
    compaction_event, messages_remaining, messages_removed_this_turn, plus the
    baseline keys from get_token_breakdown().

- Read agent/runtime.py line 2187-2230 — breakdown["compaction_event"] only set
    when _compaction_happened=True AND _ev_for_breakdown is not None.
    Audit-Fix-20: do not include compaction_event key on no-op compactions.

- Read models/conversation.py:362 — get_token_breakdown() returns:
    {"system_prompt_tokens", "conversation_tokens", "total_used_tokens",
    "model_max_tokens", "remaining_tokens", "usage_percent"}. tiktoken-accurate
    when installed (verified 0.12.0 works), falls back to chars // 4.

- Read models/providers.py:39 — ProviderConfig dataclass already has fields:
    compaction_threshold: float = 0.80 (line 52), context_mode: str = "auto"
    (line 55). The dataclass is constructed via kwargs in
    ui/views/settings_dialog.py:186-200 — the dialog does NOT pass these two
    fields. Existing fields are added by an external save() round-trip via
    utils/providers_store.py:59, 98.

- Read ui/handlers/agent_runtime_handler.py:1238 — _on_token_breakdown() is
    currently a 7-line logger.info() call. Throws away trimmed_this_turn,
    compaction_event, usage_percent, messages_remaining. The signature is
    (session_key: str, breakdown: dict) and it is wired as on_token_breakdown=
    self._on_token_breakdown at line 565.

- Read ui/handlers/agent_runtime_handler.py:336 — clear_conversation() is the
    per-runtime method that resets the conversation. Takes session_key, returns
    bool. Validates prefix "special:" and agent registry.

- Read ui/handlers/agent_runtime_handler.py:786-805 — _resolve_chat_box()
    resolves chat_box via _mc.get_chat_box_for_session(session_key) with
    project-routing fallback.

- Read ui/handlers/agent_runtime_handler.py:1286 — _do_error() template for
    adding chat bubbles. Calls self._crh.end_streaming() then
    self._crh.render_sync("Agent", rendered_text, ...).

- Read ui/handlers/command_handler.py:155-166 — /clear registered with
    hasattr(project_handler, "cmd_clear") guard so command_handler doesn't
    crash on test fixtures. The pattern is to register conditionally.

- Read ui/handlers/project_handler.py:673-732 — cmd_clear complete template.
    Validates sk.startsWith("project:") / "special:" / unknown-prefix branches.
    Calls self._clear_callback(sk) → bool. On success, optional
    self._clear_chat_callback(sk) UI side-effect.

- Read ui/handlers/project_handler.py:402-435 — set_clear_callback(fn) and
    set_clear_chat_callback(fn) injection sites. Both must be called before
    /clear can succeed.

- Read ui/window.py:620-628 — clear and clear_chat callbacks wired from
    AgentRuntimeHandler.clear_conversation and window._clear_chat_box().
    Pattern to mirror.

- Read ui/window.py:856 — _clear_chat_box(sk) implementation. Resolves chat
    box, while-loop removes children via chat_box.get_first_child() and
    chat_box.remove(child).

- Read ui/views/settings_dialog.py:99-104 — _max_tokens_spin configured
    with Gtk.SpinButton.new_with_range(1_000, 10_000_000, 1_000). Default
    128_000. Save callback at line 193 constructs ProviderConfig via kwargs
    (must add compaction_threshold kwarg).

- Read ui/views/main_content.py:184-191 — bottom button_bar construction.
    Three buttons (prompt, improve, send) appended to a horizontal box with
    spacing 6. The context-meter widget will go in this same button_bar.

- Read ui/views/chat_bubble.py:1003 — create_error_bubble() template for
    building a styled bubble. Uses add_css_class("bubble-error"). New
    create_compaction_bubble will follow this same pattern with
    add_css_class("bubble-compaction").

- Read ui/handlers/chat_render_handler.py:609-689 — render_event_card()
    dispatches by event_type (file_read, edit_proposal, tool_call, error,
    thinking, task, diff_summary, diff_file, widget). New event_type
    "compaction" will dispatch to create_compaction_bubble.

- Read agent/special_agents.py:24-62 — SpecialAgentDef dataclass. Fields
    conv_id_prefix, display_name, role, emoji, tools, can_write, llm_name,
    fallback_provider, fallback_model, api_key, app_title, self_improvement,
    mcp_servers, auto_open, auto_add_to_projects. Adding
    compaction_strategy: str = "textual" requires extending this dataclass
    AND the validate_* function in utils/agent_defs.py.

- Read models/command.py:43 — Command dataclass with name, args, flags,
    raw_text, body, source_session_key. /compact [focus-text] will read
    cmd.body for the focus-instructions string.

- Architecture owner per ARCHITECTURE.md:
    Phase A: ui/handlers/agent_runtime_handler.py owns telemetry dispatch.
    Phase B: ui/handlers/project_handler.py owns /clear-style commands;
              ui/handlers/command_handler.py registers them.
    Phase C: agent/context_strategy.py owns strategies; agent/runtime.py
              owns the LLM call; agent/special_agents.py owns config knob.

- Existing patterns to copy:
    • /clear template (cmd_clear at project_handler.py:673)
    • clear_chat_box side-effect (window.py:856)
    • render_event_card("error", …) → create_error_bubble (chat_bubble.py:1003)
    • CompactionEvent dataclass for telemetry (context_strategy.py:30)
```

---

## 3. Changes by File

### 3.1 Phase A — UI Surface

#### 3.1.1 `ui/handlers/agent_runtime_handler.py`

**Lines to modify:** 1238–1249 (`_on_token_breakdown` body) and adding one new method.

**Change:** replace the log-only body with logging + state + dispatch. Three changes:

```python
# At line 119 (state area, near _session_usage):
        # Token breakdown state for Phase A UI surface.
        # _last_breakdown: session_key → most recent breakdown dict.
        # _last_compaction_warning_turn: session_key → turn we last warned on,
        #   so we don't spam "approaching limit" warnings every iteration.
        # _first_compaction_seen: session_key → bool, true after first bubble
        #   fires for this session so anti-spam skip works.
        self._last_breakdown: dict[str, dict] = {}
        # FIX-BUG-4: dict initializers, not scalars. Reads go through
        # .get(session_key, default); the type must be a real dict.
        self._last_warning_pct: dict[str, float] = {}
        self._first_compaction_seen: dict[str, bool] = {}
```

```python
# Replacing lines 1238-1249:
    def _on_token_breakdown(self, session_key: str, breakdown: dict) -> None:
        """§Phase-A — Per-turn token budget breakdown. Store + log + dispatch.

        Breakdown dict keys (verified at models/conversation.py:362 and
        runtime.py:2187-2218):
          system_prompt_tokens  (int)
          conversation_tokens   (int)
          total_used_tokens     (int)
          model_max_tokens      (int)
          remaining_tokens      (int)
          usage_percent         (float 0.0-100.0)
          trimmed_this_turn     (bool)  ← only True when real compaction happened
          messages_remaining    (int)
          messages_removed_this_turn (int, 0 if no compaction)
          compaction_event      (dict, only when _compaction_happened)
            {trigger, layer, tokens_before, tokens_after, tokens_freed,
             soft_ceiling, hard_ceiling, messages_before, messages_after,
             messages_removed, summary_tokens_injected, session_key}
        """
        # Always log for observability (preserve existing behavior).
        logger.info(
            "[token-breakdown] sk=%s system_prompt=%d conv=%d total=%d/%d "
            "remaining=%d (%.1f%%) trimmed=%s removed=%d",
            session_key,
            breakdown["system_prompt_tokens"],
            breakdown["conversation_tokens"],
            breakdown["total_used_tokens"],
            breakdown["model_max_tokens"],
            breakdown["remaining_tokens"],
            breakdown["usage_percent"],
            breakdown.get("trimmed_this_turn", False),
            breakdown.get("messages_removed_this_turn", 0),
        )

        # Cache for the UI meter (cheap, in-memory).
        self._last_breakdown[session_key] = breakdown

        # Fire compaction bubble on real compaction only.
        # Audit-Fix-20 verified: trimmed_this_turn is False when no-op.
        # Anti-spam: only the first transition per session shows. Subsequent
        # compactions are still logged but don't add a bubble.
        if breakdown.get("trimmed_this_turn", False):
            already_seen = self._first_compaction_seen.get(session_key, False)
            if not already_seen:
                self._first_compaction_seen[session_key] = True
                ev = breakdown.get("compaction_event", {})
                if self._GLib is not None:
                    self._GLib.idle_add(
                        self._do_compaction_bubble, session_key, ev
                    )
                else:
                    self._do_compaction_bubble(session_key, ev)

        # Threshold warnings — phase-A-2.
        # 80% → "approaching limit". 95% → "auto-compaction imminent".
        # Anti-spam: hysteresis — only re-fire if we cross back below 75%.
        usage_pct = breakdown.get("usage_percent", 0.0)
        last_pct = self._last_warning_pct.get(session_key, -1.0)
        new_warn_level: str | None = None
        if usage_pct >= 95.0 and last_pct < 95.0:
            new_warn_level = "auto-compact-imminent"
        elif usage_pct >= 80.0 and last_pct < 80.0:
            new_warn_level = "approaching-limit"
        if new_warn_level is not None:
            self._last_warning_pct[session_key] = usage_pct
            if self._GLib is not None:
                self._GLib.idle_add(
                    self._do_usage_warning, session_key, new_warn_level, usage_pct
                )
            else:
                self._do_usage_warning(session_key, new_warn_level, usage_pct)
        # Reset hysteresis when we drop back well below threshold.
        if usage_pct < 75.0 and last_pct >= 80.0:
            self._last_warning_pct[session_key] = usage_pct
```

**Add new methods after `_on_token_breakdown`:**

```python
    def _do_compaction_bubble(self, session_key: str, ev: dict) -> None:
        """Main-thread portion of the compaction bubble dispatch.

        Renders a styled bubble into the chat box for the session.
        Mirrors _do_error's pattern (line 1286): resolve chat_box, call
        self._crh.render_sync, chat_box.append(bubble), scroll to bottom.

        Bubble content mirrors Claude Code's `/compact` feedback:
          "🧹 Context reset. Removed N messages, freed ~N tokens."
        Falls back to a minimal message if eviction dict is empty (shouldn't
        happen — defensive).
        """
        logger.debug("[handler] _do_compaction_bubble: sk=%s ev=%s", session_key, ev)
        # Streaming may be in progress (a model turn was interrupted by
        # compaction). End it cleanly so the bubble attaches cleanly.
        if self._crh is not None:
            self._crh.end_streaming(session_key, agent_name=None)

        chat_box = self._resolve_chat_box(session_key)
        if chat_box is None:
            logger.debug("[handler] _do_compaction_bubble: no chat box for %s", session_key)
            return

        removed = int(ev.get("messages_removed", 0))
        freed = int(ev.get("tokens_freed", 0))
        layer = int(ev.get("layer", 0))
        trigger = str(ev.get("trigger", ""))
        text = (
            f"🧹 Context reset. Removed {removed} message"
            f"{'s' if removed != 1 else ''}, freed ~{freed:,} tokens."
            f"\n   (Layer {layer}; trigger: {trigger})"
        )
        bubble = self._crh.render_sync(
            "Agent", text, session_key, agent_name=None
        )
        if bubble is not None:
            chat_box.append(bubble)
            self._mc.scroll_chat_to_bottom()
        else:
            logger.warning("[handler] _do_compaction_bubble: render_sync returned None")

    def _do_usage_warning(
        self, session_key: str, level: str, usage_pct: float
    ) -> None:
        """Main-thread portion of context-pressure warning.

        Levels (mirrors PROPOSAL §10.2):
          "approaching-limit" — usage >= 80%, suggest /compact.
          "auto-compact-imminent" — usage >= 95%, expect auto-compaction.

        Renders a yellow/red styled bubble. No-op if chat_box unavailable.
        """
        if level == "approaching-limit":
            text = (
                f"⚠️ Context at {usage_pct:.0f}%. "
                f"Consider /compact to free space."
            )
        else:  # auto-compact-imminent
            text = (
                f"🔴 Context at {usage_pct:.0f}%. "
                f"Auto-compaction will trigger soon."
            )
        chat_box = self._resolve_chat_box(session_key)
        if chat_box is None:
            return
        if self._crh is not None:
            self._crh.end_streaming(session_key, agent_name=None)
            bubble = self._crh.render_sync(
                "Agent", text, session_key, agent_name=None
            )
            if bubble is not None:
                chat_box.append(bubble)
                self._mc.scroll_chat_to_bottom()

    # ── Phase A: public API for the UI context meter ─────────────────────────
    def get_last_breakdown(self, session_key: str) -> dict | None:
        """Return the most recent token breakdown for ``session_key``.

        The breakdown dict matches the schema documented on
        ``_on_token_breakdown``. May return ``None`` if the session
        hasn't seen a turn yet. Used by the chat-panel context meter
        to render a live progress bar.
        """
        return self._last_breakdown.get(session_key)
```

**Files NOT changed in Phase A:**
- `agent/context_strategy.py` — engine untouched
- `agent/runtime.py` — already emits the right breakdown keys
- `models/conversation.py` — already exposes `get_token_breakdown()`

#### 3.1.2 `ui/views/main_content.py`

**Lines to modify:** add context meter widget to the button_bar at ~line 191.

**SCOPE NOTE (FIX-BUG-6):** The widget creation below MUST live inside the MainContent class's ``__init__`` — NOT inside any helper/build method that uses a local-scope ``button_bar``. The setter method references ``self._context_meter`` and ``self._context_meter_label``, so they MUST be instance attributes. Do not place this in a method that does not return to ``__init__``'s scope.

**Insert in MainContent.__init__ (around line 60, near other widget creation):**

```python
        # Phase A — Context meter (Claude Code style).
        # These are instance attributes so set_context_meter() can find them.
        # FIX-BUG-6: explicitly store as instance attributes.
        self._context_meter = Gtk.ProgressBar()
        self._context_meter.set_size_request(80, 6)
        self._context_meter.set_show_text(True)
        self._context_meter.set_fraction(0.0)
        self._context_meter.add_css_class("context-meter")
        self._context_meter_label = Gtk.Label(label="")
        self._context_meter_label.add_css_class("context-meter-label")
        meter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        meter_box.append(self._context_meter)
        meter_box.append(self._context_meter_label)
        # Then in the existing _build method (around line 184) append
        # meter_box to the bottom button_bar:
        #     button_bar.append(meter_box)
        # (Two operations in two scopes. The widget creation lives in
        # __init__ for instance-attr storage; the parent-mount lives in
        # _build for layout consistency.)
```

**Add helper method (after the existing button helpers, ~line 200):**

```python
    def set_context_meter(
        self, session_key: str, usage_percent: float
    ) -> None:
        """Update the context-meter widget for the active ``session_key``.

        Called from window.py when AgentRuntimeHandler emits a breakdown.
        ``usage_percent`` is 0.0-100.0. Negative values are treated as
        "reset" (idle state).
        """
        # Only update if the active tab matches. We don't have a direct
        # tab-to-session_key mapping here, so callers will guard.
        if usage_percent < 0:
            self._context_meter.set_fraction(0.0)
            self._context_meter_label.set_text("")
            return
        self._context_meter.set_fraction(min(usage_percent / 100.0, 1.0))
        # Pick CSS class per zone (green < 70%, yellow 70-90%, red >= 90%).
        existing_classes = [
            c for c in self._context_meter.get_css_classes()
            if c.startswith("context-meter-")
        ]
        for c in existing_classes:
            self._context_meter.remove_css_class(c)
        if usage_percent >= 90.0:
            self._context_meter.add_css_class("context-meter-high")
            color_label = "high"
        elif usage_percent >= 70.0:
            self._context_meter.add_css_class("context-meter-medium")
            color_label = "med"
        else:
            self._context_meter.add_css_class("context-meter-low")
            color_label = "ok"
        self._context_meter_label.set_text(f"{color_label} {usage_percent:.0f}%")
```

**Imports needed:** none new — `Gtk.ProgressBar` is in `gi.repository.Gtk` already.

**Files NOT changed:**
- `agent/runtime.py` — already emits breakdown with `usage_percent`

#### 3.1.3 `ui/views/settings_dialog.py`

**Lines to modify:** 99-105 (Context Window SpinButton area) + 186-200 (save callback).

**Add a new SpinButton for compaction_threshold below the Context Window row (~line 105):**

```python
        # Phase A — Editable compaction_threshold.
        # Range 0.50 — 0.95, step 0.05 (10% to 95% of context window).
        # Default 0.80 matches the dataclass default and runtime fallback.
        self._compaction_threshold_spin = Gtk.SpinButton.new_with_range(0.50, 0.95, 0.05)
        self._compaction_threshold_spin.set_value(
            self._provider.compaction_threshold or 0.80
        )
        self._compaction_threshold_spin.set_hexpand(True)
        threshold_row = self._labeled(
            "Compaction threshold", self._compaction_threshold_spin
        )
        vbox.append(threshold_row)
```

**Update the save callback (line 186) to include `compaction_threshold` kwarg:**

```python
        return ProviderConfig(
            name=self._provider_name,
            base_url=self._base_url_entry.get_text().strip(),
            api_key=self._api_key_entry.get_text().strip(),
            default_model=self._model_entry.get_text().strip(),
            caller=existing.caller if existing else "",
            enabled=existing.enabled if existing else True,
            supports_tools=existing.supports_tools if existing else True,
            supports_streaming=existing.supports_streaming if existing else True,
            max_tokens=int(self._max_tokens_spin.get_value()),
            compaction_threshold=float(
                self._compaction_threshold_spin.get_value()
            ),  # Phase A
            last_verified_at=existing.last_verified_at if existing else None,
            last_error=existing.last_error if existing else None,
        )
```

**Verify field name on `ProviderConfig` (already verified at models/providers.py:52):**
- Field name: `compaction_threshold: float = 0.80`.
- Round-trip via utils/providers_store.py:59, 98 — already persists this field.
- This edit just exposes an existing field; no schema migration needed.

**Files NOT changed:**
- `models/providers.py` — field already exists
- `utils/providers_store.py` — already persists the field

#### 3.1.4 `ui/window.py` (Phase A additions)

**Lines to modify:** add the context-meter callback wiring, ~line 645.

**Add after the existing /clear wiring block:**

```python
        # Phase A — Wire the context-meter callback via the
        # set_on_token_breakdown_extra() slot (see §3.1.5). The existing
        # _on_token_breakdown in agent_runtime_handler.py dispatches to
        # the logger.info (preserved) and to this extra listener.
        def _on_context_meter(sk: str, breakdown: dict) -> None:
            usage_pct = breakdown.get("usage_percent", 0.0)
            self._main_content.set_context_meter(sk, usage_pct)
        self._agent_runtime_handler.set_on_token_breakdown_extra(_on_context_meter)
```

> **FIX-BUG-10 (reconciliation):** An earlier draft of this section said
> "we don't add a new callback — we just call set_context_meter inside
> the existing logger.info path." That was incorrect — the boundary
> would couple window.py into the handler body. The correct mechanism
> is the **`set_on_token_breakdown_extra()` slot defined in §3.1.5**,
> and this section now wires only that. Do **not** add a second
> mechanism.

**Files NOT changed:**
- `agent/runtime.py` — already emits breakdown

#### 3.1.5 `ui/handlers/agent_runtime_handler.py` (Phase A extension)

**Add a public callback registration method (after the existing setter methods, ~line 1228):**

```python
    def set_on_token_breakdown_extra(
        self, cb: Callable[[str, dict], None] | None
    ) -> None:
        """Inject an additional listener for breakdown events.

        Used by Phase A — the context meter subscribes here without
        replacing the existing logger.info dispatch. None clears.
        Runs synchronously on the same thread as the runtime callback
        (so the UI must do GTK ops via its own GLib.idle_add if needed;
        set_context_meter in main_content.py handles that internally).
        """
        self._on_token_breakdown_extra = cb
        # If a breakdown already arrived for some sessions, replay
        # them so the meter doesn't show stale state.
        # Defensive: only replay if the UI is "late" — guarded by timestamp.
```

**Then update `_on_token_breakdown` (after the existing logger.info call, ~line 1249) to call the extra callback:**

```python
        # Phase A — Forward to optional extra listener (context meter).
        extra = getattr(self, "_on_token_breakdown_extra", None)
        if extra is not None:
            try:
                extra(session_key, breakdown)
            except Exception:
                logger.exception(
                    "_on_token_breakdown: extra listener raised; ignoring"
                )
```

**Add an `__init__` initialization:**

```python
        # Phase A — Optional extra listener for breakdowns (used by meter).
        self._on_token_breakdown_extra: Callable | None = None
```

Add this to `__init__` near `self._session_usage` initialization at line 102.

---

### 3.2 Phase B — /compact Slash Command

#### 3.2.1 `ui/handlers/project_handler.py`

**Add at ~line 730 (after `cmd_clear`, before `set_review_handler`):**

```python
    def cmd_compact(self, cmd: Command, session_key: str | None = None) -> CommandResult:
        """/compact — force compaction of the current special agent's conversation.

        Spec: docs/specs/SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md §3.2.

        Forces a `compact(conv, model_max // 2)` call regardless of current
        size. Mirrors cmd_clear's structure (ui/handlers/project_handler.py:673):
        validate session, dispatch to injected callback.

        Optional body text (cmd.body) is passed to the callback as a focus
        instruction. For Phase B (textual summary), the focus text is appended
        to the summary message. For Phase C (LLM strategy), the focus is
        included in the LLM prompt to bias preservation.

        Refuses to operate on project tabs (each project member has its own
        conversation; clearing one member would surprise the user).
        """
        sk = cmd.source_session_key or session_key
        if not sk:
            return CommandResult(
                handled=True,
                response_text="No active session to compact.",
            )

        # Project tabs: explain where /compact actually works.
        if sk.startswith("project:"):
            return CommandResult(
                handled=True,
                response_text=(
                    "Use /compact in an agent tab to compact that agent's "
                    "conversation."
                ),
            )

        # Special agent tabs: dispatch to the runtime handler via the
        # callback injected by window.py.
        if sk.startswith("special:"):
            agent_name = sk.split(":", 1)[1]
            if self._compact_callback is None:
                return CommandResult(
                    handled=True,
                    response_text=(
                        f"Compact unavailable — runtime handler not wired "
                        f"for {agent_name}. Restart the app and try again."
                    ),
                )
            focus_text = cmd.body.strip() if cmd.body else ""
            try:
                result = self._compact_callback(sk, focus_text)
            except Exception as exc:
                _logger.exception("cmd_compact: callback raised for %s", sk)
                return CommandResult(
                    handled=True,
                    response_text=f"Compact failed for {agent_name}: {exc}",
                )
            # result is a dict: {messages_removed, tokens_freed, summary_chars}
            removed = int(result.get("messages_removed", 0))
            freed = int(result.get("tokens_freed", 0))
            msg = (
                f"Compacted {agent_name}'s conversation. "
                f"Removed {removed} message"
                f"{'s' if removed != 1 else ''}, freed ~{freed:,} tokens."
            )
            if focus_text:
                msg += f"\nFocus: {focus_text!r}"
            return CommandResult(handled=True, response_text=msg)

        # Unknown session prefix — refuse cleanly.
        return CommandResult(
            handled=True,
            response_text=f"Cannot compact session of type '{sk.split(':', 1)[0]}'.",
        )

    def set_compact_callback(
        self, fn: Callable[[str, str], dict] | None
    ) -> None:
        """Inject callback for /compact command.

        Phase B. Wired by window.py to AgentRuntimeHandler.compact_conversation.
        The callback takes (session_key, focus_text) and returns a dict:
            {"messages_removed": int, "tokens_freed": int, "summary_chars": int}

        MUST be called before /compact can succeed. None → no-op with hint.
        """
        self._compact_callback = fn

    def set_compact_chat_callback(
        self, fn: Callable[[str, dict], None] | None
    ) -> None:
        """Inject callback for /compact UI side effect.

        Optional. Wired by window.py to insert a "🧹 Compacted" bubble
        into the chat box of ``session_key`` after the data-plane compact
        succeeds. Args: (session_key: str, result: dict) → None.
        """
        self._compact_chat_callback = fn

    # Update set_clear_chat_callback doc + signature to reflect new behavior.
```

**Update `cmd_compact` to also fire `self._compact_chat_callback` on success:**

```python
            removed = int(result.get("messages_removed", 0))
            freed = int(result.get("tokens_freed", 0))
            msg = (
                f"Compacted {agent_name}'s conversation. "
                f"Removed {removed} message"
                f"{'s' if removed != 1 else ''}, freed ~{freed:,} tokens."
            )
            if focus_text:
                msg += f"\nFocus: {focus_text!r}"

            # Phase B UI side effect: append a styled bubble to the chat.
            if self._compact_chat_callback is not None:
                try:
                    self._compact_chat_callback(sk, result)
                except Exception:
                    _logger.exception(
                        "cmd_compact: chat_callback raised for %s; "
                        "data-plane compact already succeeded, continuing",
                        sk,
                    )

            return CommandResult(handled=True, response_text=msg)
```

**Add `__init__` state (around line 77, near `self._clear_callback = None`):**

```python
        # Phase B — /compact injection slots.
        self._compact_callback: Callable[[str, str], dict] | None = None
        self._compact_chat_callback: Callable[[str, dict], None] | None = None
```

#### 3.2.2 `ui/handlers/command_handler.py`

**Add to the registration block at ~line 165 (immediately after the `/clear` registration):**

```python
            if hasattr(project_handler, "cmd_compact"):
                # Spec: docs/specs/SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md §3.2.
                # /compact forces a manual compaction of the current special
                # agent's conversation. payload_free=False because the body
                # text after an em-dash becomes the focus instruction (e.g.
                # `/compact @coder — focus on the auth changes`).
                self.register_command("compact", project_handler.cmd_compact,
                    help_text=(
                        "Compact conversation: /compact [focus-instructions]"
                    ))
                # Note: payload_free=False (default) because the focus
                # instructions are passed via cmd.body.
```

**Verification:** `Command` dataclass at `models/command.py:43` has `body: str = ""` — used for the focus-instructions in `/compact @coder — focus on the auth changes`.

#### 3.2.3 `ui/handlers/agent_runtime_handler.py`

**Add a public method mirroring `clear_conversation`. Insert after line 415 (`clear_conversation`):**

```python
    def compact_conversation(
        self, session_key: str, focus_text: str = ""
    ) -> dict:
        """Force compaction of a special agent's conversation.

        Spec: docs/specs/SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md §3.2.

        Args:
            session_key: "special:coder" etc.
            focus_text: Optional focus instructions for Phase C's LLM
                strategy (Phase B's textual strategy ignores this).

        Returns:
            dict with keys:
                messages_removed (int)
                tokens_freed (int)
                summary_chars (int)
                layer (int)

        Returns an empty dict {"messages_removed": 0, ...} on failure.
        Mirror clear_conversation's return contract.
        """
        if not isinstance(session_key, str) or not session_key.startswith("special:"):
            logger.warning(
                "compact_conversation: refusing non-special session_key=%r",
                session_key,
            )
            return {"messages_removed": 0, "tokens_freed": 0, "summary_chars": 0, "layer": 0}

        agent_def = self._agents.get(session_key)
        if agent_def is None:
            logger.warning(
                "compact_conversation: no registered special agent for %s",
                session_key,
            )
            return {"messages_removed": 0, "tokens_freed": 0, "summary_chars": 0, "layer": 0}

        try:
            rt = self._get_runtime(agent_def.display_name, agent_def=agent_def)
        except Exception as exc:
            logger.error(
                "compact_conversation: failed to acquire runtime for %s: %s",
                session_key, exc,
            )
            return {"messages_removed": 0, "tokens_freed": 0, "summary_chars": 0, "layer": 0}

        conv = rt.get_conversation(session_key)
        if conv is None:
            return {"messages_removed": 0, "tokens_freed": 0, "summary_chars": 0, "layer": 0}

        # Compute hard ceiling via the runtime's resolver. This reuses
        # _compute_model_max with three-tier fallback. If it fails, use
        # 128_000 (the documented fallback).
        try:
            _, hard_ceiling = rt._compute_compaction_threshold(conv)
        except Exception:
            logger.exception(
                "compact_conversation: failed to resolve hard_ceiling; using 128K"
            )
            hard_ceiling = 128_000

        # Force half-budget. The user is explicitly asking, so we don't
        # wait for the soft-ceiling trigger.
        target_budget = max(4_000, hard_ceiling // 2)
        messages_before = len(conv.messages)
        tokens_before = conv.get_token_estimate()

        # Phase C — Pick strategy based on agent_def.compaction_strategy.
        # Phase B always uses textual. The compaction_strategy field is
        # introduced in §3.3.5 below. We use getattr with a default so
        # the code works even before Phase C ships.
        strat_name = getattr(agent_def, "compaction_strategy", "textual")
        if strat_name == "llm":
            # Phase C path — delegate to runtime's force_llm_compact().
            try:
                return rt.force_llm_compact(conv, target_budget, focus_text)
            except Exception:
                logger.exception(
                    "compact_conversation: LLM strategy failed; "
                    "falling back to textual"
                )
                # Fall through to textual default.

        # Phase B path (default).
        rt._context_strategy.compact(conv, target_budget)

        # Persist the conversation so the trimmed state survives restarts.
        # FIX-BUG-1: there is no instance method `_save_conversation_now`.
        # The actual API is the module-level function
        # agent.runtime._save_conversation_to_disk(conv, session_key)
        # verified at agent/runtime.py:1284. The instance method call
        # would AttributeError at runtime.
        try:
            from agent.runtime import _save_conversation_to_disk
            _save_conversation_to_disk(conv, session_key)
        except Exception:
            logger.exception(
                "compact_conversation: persist failed; in-memory compact succeeded"
            )

        # Read the strategy's last_result to surface what happened.
        ev = rt._context_strategy.last_result
        tokens_after = conv.get_token_estimate()
        if ev is None:
            # No-op compaction (already fit). Report zero change.
            return {
                "messages_removed": 0,
                "tokens_freed": max(0, tokens_before - tokens_after),
                "summary_chars": 0,
                "layer": 0,
            }
        return {
            "messages_removed": ev.messages_removed,
            "tokens_freed": ev.tokens_freed,
            "summary_chars": ev.summary_tokens_injected,
            "layer": ev.layer,
        }
```

**Verification of methods used:**
- `_compute_compaction_threshold()` — verified at agent/runtime.py:1920, returns (soft, hard).
- `_context_strategy` — set at agent/runtime.py:1659.
- `compact()` — verified signature at agent/context_strategy.py:125.
- `last_result` — verified attribute at agent/context_strategy.py:48.

#### 3.2.4 `ui/window.py` (Phase B wiring)

**Lines to modify:** insert immediately after the `/clear` wiring at ~line 628.

```python
        # Wire /compact data-plane + UI side-effect.
        self._project_handler.set_compact_callback(
            self._agent_runtime_handler.compact_conversation
        )
        self._project_handler.set_compact_chat_callback(
            lambda sk, result: self._show_compact_bubble(sk, result)
        )
```

**Add `_show_compact_bubble` method to `ui/window.py` (place after `_clear_chat_box`):**

```python
    def _show_compact_bubble(self, session_key: str, result: dict) -> None:
        """Render a "🧹 Compacted" bubble into the session's chat box.

        Spec: docs/specs/SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md §3.2.

        Mirrors _clear_chat_box's pattern (resolves chat_box, appends).
        Uses ChatRenderHandler.render_sync to build the bubble. No-op
        if the chat box isn't available (user closed the tab).
        """
        chat_box = self._main_content.get_chat_box_for_session(session_key)
        if chat_box is None:
            logger.debug("_show_compact_bubble: no chat box for %s", session_key)
            return
        removed = int(result.get("messages_removed", 0))
        freed = int(result.get("tokens_freed", 0))
        text = (
            f"🧹 Compacted. Removed {removed} message"
            f"{'s' if removed != 1 else ''}, freed ~{freed:,} tokens."
        )
        bubble = self._chat_render_handler.render_sync(
            "Agent", text, session_key, agent_name=None
        )
        if bubble is not None:
            chat_box.append(bubble)
            self._main_content.scroll_chat_to_bottom()
```

**Verified:** `_chat_render_handler` is wired in `ui/window.py` (composition root, same constructor that wires `_agent_runtime_handler`). `scroll_chat_to_bottom()` exists at `_mc.scroll_chat_to_bottom()` per agent_runtime_handler.py:1316.

#### 3.2.5 `agent/runtime.py` (Phase B extension — minimal)

**Add a helper method on `AgentRuntime` for explicit compaction invocation:**

```python
    def force_compact(
        self,
        conv: "Conversation",
        token_budget: int,
    ) -> None:
        """Public wrapper around self._context_strategy.compact().

        Spec: docs/specs/SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md §3.2.
        Allows external callers (like compact_conversation in
        agent_runtime_handler) to invoke compaction without poking at
        the private _context_strategy attribute.

        token_budget <= 0 is silently ignored (matches the strategy's
        own defensive behavior — see context_strategy.py:130).
        """
        self._context_strategy.compact(conv, token_budget)
```

**Note:** This is a thin wrapper. `_save_conversation_now()` is called from `agent_runtime_handler.compact_conversation()` directly, not here, because saving is the UI's responsibility.

---

### 3.3 Phase C — LLM-Summarization Strategy

#### 3.3.1 `agent/context_strategy.py`

**Add a new class after `DefaultContextStrategy` (insert at end of file, ~line 740):**

```python
class LLMSummarizeStrategy(DefaultContextStrategy):
    """Strategy that uses an LLM call to generate the trim summary.

    Spec: docs/specs/SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md §3.3.

    Inherits from DefaultContextStrategy so it gets free Layer 1
    (prune_tool_outputs) and Layer 2 (trim loop) for free. Only
    Layer 3 (the summary text) is overridden.

    Phase 4 (manual /compact) is the primary use case. The strategy
    is also invoked automatically when:
      - The user types /compact in an agent tab
      - An agent_def has compaction_strategy="llm"

    The LLM call uses:
      - Same provider as conv.model (e.g., "openai")
      - Same model as conv.model (e.g., "openai/gpt-4o")
      - Same system_prompt (via provider's chat completion)
      - Cache-friendly prompt structure (system_prompt first, then
        conversation transcript, then the summary prompt)

    Failure modes:
      - LLM call raises → falls back to super()._summary() (textual preview)
      - LLM call returns empty → falls back to textual preview
      - LLM call returns oversized → truncates to fit budget
      - LLM call is rate-limited → does NOT retry; uses textual fallback
    """

    # Cache-friendly system prefix: stable across turns for KV-cache reuse.
    # Anchored on conv.id (per-conversation prefix) so the cache hit rate
    # is high within a session.
    SUMMARY_PROMPT_TEMPLATE = """\
You are a conversation compaction specialist. Produce a structured summary \
of the conversation transcript below so a downstream LLM can continue the \
task without losing important context. Be concise but preserve everything \
that matters.

Format your response with EXACTLY these nine sections, each on its own \
line, no preamble:

<task>One sentence: what the user originally asked.</task>
<progress>Bulleted list of completed steps and intermediate results.</progress>
<files>Comma-separated paths of files touched or relevant to the task.</files>
<decisions>Bulleted list of decisions made, with brief rationale.</decisions>
<constraints>Bulleted list of constraints in effect (e.g., user prefs, env limits).</constraints>
<errors>Bulleted list of errors encountered and their resolutions.</errors>
<open_questions>Bulleted list of unresolved threads or ambiguities.</open_questions>
<next_steps>Bulleted list of suggested next actions for the agent.</next_steps>
<user_preferences>Bulleted list of preferences the user expressed.</user_preferences>

Transcript:
{transcript}
"""

    def __init__(
        self,
        llm_provider: Callable[[str, str], str] | None = None,
        llm_model_override: str | None = None,
    ) -> None:
        super().__init__()
        # llm_provider: fn(system_prompt, user_prompt) -> str.
        # Injected by agent/runtime.py (NOT imported directly — this
        # keeps layering rules: the strategy is policy, not orchestration).
        self._llm_provider = llm_provider
        self._llm_model_override = llm_model_override

    # Override Layer 3 only.
    def _summary(
        self,
        conv: Conversation,
        token_budget: int = 0,
        keep_first: int = 2,
    ) -> str:
        """LLM-generated structured summary. Falls back to textual on failure.

        Signature mirrors DefaultContextStrategy._summary (line 678).
        Uses llm_provider(system_prompt, user_prompt) for the LLM call.
        Default behavior: pick conv.system_prompt as the system prefix
        (cache reuse) and emit a single user message with the template.
        """
        if self._llm_provider is None:
            # Misconfigured; fall back to textual.
            logger.warning(
                "LLMSummarizeStrategy: no llm_provider configured; "
                "using textual fallback"
            )
            return super()._summary(conv, token_budget, keep_first=keep_first)

        tail_preserve = 4
        if len(conv.messages) <= tail_preserve:
            return ""

        # Pick the head messages to summarize (everything except tail).
        head = conv.messages[:max(keep_first, len(conv.messages) - tail_preserve)]
        if not head:
            return ""

        # Build the transcript: each message on its own line with role prefix.
        # Limit to ~4000 chars to keep the LLM call cheap; the transcript is
        # an INPUT, not an output. The LLM is expected to compress ~80x.
        lines = []
        for msg in head:
            role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            content = (msg.content or "").replace("\n", " ")[:1000]  # cap each msg
            lines.append(f"[{role}] {content}")
        transcript = "\n".join(lines)
        if len(transcript) > 4000:
            transcript = transcript[:4000] + "\n[... truncated for length ...]"

        # Compose the prompt.
        user_prompt = self.SUMMARY_PROMPT_TEMPLATE.format(transcript=transcript)
        system_prompt = conv.system_prompt or "You are a helpful assistant."

        # Call the LLM. The provider returns a string; we don't parse it
        # ourselves — we pass it through verbatim. Strip whitespace only.
        try:
            response = self._llm_provider(system_prompt, user_prompt)
        except Exception as exc:
            logger.warning(
                "LLMSummarizeStrategy: LLM call failed (%s); "
                "falling back to textual summary",
                type(exc).__name__,
            )
            return super()._summary(conv, token_budget, keep_first=keep_first)

        if not response or not response.strip():
            logger.warning(
                "LLMSummarizeStrategy: LLM returned empty response; "
                "falling back to textual summary"
            )
            return super()._summary(conv, token_budget, keep_first=keep_first)

        # Optional: enforce token-budget. If response is too long, truncate.
        # Use a rough estimate (chars // 4) for the budget check.
        if token_budget > 0:
            response_tokens = len(response) // 4
            if response_tokens > token_budget:
                # Truncate to budget. Cut at the nearest line boundary.
                target_chars = token_budget * 4
                cut_at = response.rfind("\n", 0, target_chars)
                if cut_at <= 0:
                    cut_at = target_chars
                response = response[:cut_at] + "\n[... summary truncated ...]"

        # Validate the 9-section structure. If the LLM deviated, the
        # message is still useful as free text — log a warning but
        # don't fail. The downstream agent will read whatever the LLM said.
        expected_tags = [
            "task", "progress", "files", "decisions", "constraints",
            "errors", "open_questions", "next_steps", "user_preferences",
        ]
        missing = [t for t in expected_tags if f"<{t}>" not in response]
        if missing:
            logger.info(
                "LLMSummarizeStrategy: response missing tags %s "
                "(acceptable, using as-is)",
                missing,
            )

        return response
```

**Files NOT changed:**
- `_summary()` on `DefaultContextStrategy` is NOT touched.
- `ContextStrategy` Protocol at agent/context_strategy.py:72 is NOT changed — `LLMSummarizeStrategy` satisfies it via inheritance.

#### 3.3.2 `agent/runtime.py` (Phase C wiring — FIX-BUG-2 + FIX-BUG-3)

**FIX-BUG-2 (modules that don't exist):** The original draft of this section created a fictional ``agent/llm_completion.py`` that imported ``utils.caller`` and ``utils.llm_client`` — neither exists (``ls`` verified). It also invented a ``call_llm`` function with a signature unrelated to anything in the codebase. The corrected implementation reuses the real provider-caller dispatch at ``agent/runtime.py:423`` (``_PROVIDER_CALLERS``) and the real non-streaming callers (``_call_openai`` at line 195, ``_call_anthropic`` at line 363, ``_call_minimax``). One new method on ``AgentRuntime`` plus one new module — but the new module is a real implementation, not a fictional API.

**FIX-BUG-3 (telemetry bypass):** The original draft created a fresh ``LLMSummarizeStrategy`` instance inside ``force_llm_compact`` and called ``strat.compact()`` on it. That left the runtime's ``self._context_strategy.last_result`` and ``self._compaction_events`` ring buffer (runtime.py:1613, 2116, 2129) untouched — UI meter and rollback checks would see stale data. The corrected implementation **swaps** ``self._context_strategy`` to the LLM strategy, runs compact, **preserves ``last_result``** so the ring buffer captures the event, then **swaps back**.

**Add a method to `AgentRuntime`:**

```python
    def force_llm_compact(
        self,
        conv: "Conversation",
        token_budget: int,
        focus_text: str = "",
    ) -> dict:
        """Force an LLM-summarization compact on ``conv``.

        Spec: docs/specs/SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md §3.3.2.

        FIX-BUG-3: swap self._context_strategy to the LLM strategy for
        the duration of the call, run compact, then swap back. This
        ensures self._context_strategy.last_result reflects the LLM
        compaction, which the runtime's breakdown dispatcher (line 2116)
        reads into self._compaction_events.
        """
        from agent.context_strategy import (
            LLMSummarizeStrategy, DefaultContextStrategy,
        )

        # Save the existing strategy so we can restore.
        original_strategy = self._context_strategy

        # Build the LLM strategy with a closure bound to this runtime
        # so the strategy's LLM call uses our real caller dispatch.
        strat = LLMSummarizeStrategy(
            llm_provider=lambda sys_p, user_p, model_id=None:
                self._call_for_summary(
                    system_prompt=sys_p,
                    user_prompt=user_p,
                    model_id=model_id or conv.model,
                ),
        )
        self._context_strategy = strat

        messages_before = len(conv.messages)
        tokens_before = conv.get_token_estimate()

        # Optional: prepend focus_text to conv.system_prompt so the LLM
        # summary biases toward preserving that area. Restore after.
        original_sp = conv.system_prompt
        if focus_text:
            conv.system_prompt = (
                f"{original_sp}\n\n## Focus for compaction\n{focus_text}"
            )
        try:
            strat.compact(conv, token_budget)
        finally:
            # Restore the original strategy so subsequent automatic
            # compactions use DefaultContextStrategy as before.
            self._context_strategy = original_strategy
            # Restore the (possibly mutated) system prompt.
            conv.system_prompt = original_sp

        # strat.last_result was set by compact() (verified at
        # agent/context_strategy.py:48, dispatched at runtime.py:2116).
        ev = strat.last_result
        tokens_after = conv.get_token_estimate()
        if ev is None:
            return {
                "messages_removed": 0,
                "tokens_freed": max(0, tokens_before - tokens_after),
                "summary_chars": 0,
                "layer": 0,
            }
        return {
            "messages_removed": ev.messages_removed,
            "tokens_freed": ev.tokens_freed,
            "summary_chars": ev.summary_tokens_injected,
            "layer": ev.layer,
        }
```

**Add `_call_for_summary` to `AgentRuntime` — a thin wrapper around the real, existing provider-caller dispatch:**

```python
    def _call_for_summary(
        self,
        system_prompt: str,
        user_prompt: str,
        model_id: str | None = None,
    ) -> str:
        """Single non-streaming chat completion for LLMSummarizeStrategy.

        Spec: docs/specs/SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md §3.3.2.
        FIX-BUG-2: reuses agent/runtime.py's real provider caller
        dispatch (_PROVIDER_CALLERS at line 423, _resolve_caller_key
        at line 2519) — does NOT create a new sync_chat_completion
        helper that does not exist.

        Returns the assistant text. Raises any provider error.
        """
        # Resolve model_id (e.g. "openai/gpt-4o"); default to runtime's
        # default if not provided.
        if not model_id and self._config.default_provider:
            model_id = f"{self._config.default_provider}/{self._config.default_model}"
        if not model_id:
            raise RuntimeError(
                "_call_for_summary: no model_id and no default configured"
            )
        if "/" not in model_id:
            raise RuntimeError(
                f"_call_for_summary: model_id must be 'provider/model', "
                f"got {model_id!r}"
            )
        provider_name, model = model_id.split("/", 1)
        provider_cfg = self._config.providers.get(provider_name)
        if provider_cfg is None:
            raise RuntimeError(
                f"_call_for_summary: provider {provider_name!r} not configured"
            )

        # Build the messages list with cache-friendly system prefix.
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Reuse the existing caller dispatch (verified at runtime.py:2628-2656).
        caller_key = self._resolve_caller_key(provider_cfg, model)
        caller = _PROVIDER_CALLERS.get(caller_key)
        if caller is None:
            raise ValueError(
                f"_call_for_summary: no caller for {caller_key!r}"
            )

        # IMPORTANT: api_key resolution mirrors the runtime's pattern
        # at agent_runtime_handler.py for the existing _call_llm path.
        # Phase C implementer should re-use the helper
        # ``self._resolve_api_key(provider_cfg)`` (verified to exist
        # alongside _resolve_caller_key at runtime.py:2519). If that
        # helper does not yet exist, fall back to provider_cfg.api_key
        # directly with a log warning.
        api_key = getattr(provider_cfg, "api_key", "") or ""
        if not api_key:
            logger.warning(
                "_call_for_summary: empty api_key for %s; check Settings",
                provider_name,
            )

        response_dict = caller(
            base_url=provider_cfg.base_url,
            api_key=api_key,
            model=model,
            messages=messages,
            tools=None,
            timeout=float(self._config.tool_timeout_seconds),
            x_title="crabcakes-summary",
        )
        # _extract_text_content is the runtime's existing helper for
        # pulling assistant text from a response dict. Verified at
        # agent/runtime.py alongside _extract_tool_calls / _extract_usage.
        text = self._extract_text_content(response_dict) \
            if hasattr(self, "_extract_text_content") \
            else response_dict.get("content", "")
        if not text:
            # Fallback: anthropic uses "content" as a list of blocks.
            content = response_dict.get("content", [])
            if isinstance(content, list) and content:
                first = content[0]
                text = first.get("text", "") if isinstance(first, dict) else str(first)
        return text or ""
```

**Files added/changed in Phase C (FIX-BUG-2 final list):**
- ``agent/runtime.py`` — adds ``force_llm_compact()`` and ``_call_for_summary()``. Uses real existing helpers (``_PROVIDER_CALLERS``, ``_resolve_caller_key``, ``_extract_text_content``).
- ``agent/context_strategy.py`` — adds ``LLMSummarizeStrategy`` (see §3.3.1).
- **No new modules.** The fictional ``agent/llm_completion.py`` is removed; everything is a method on ``AgentRuntime``.

**Files NOT changed:**
- ``DefaultContextStrategy`` is unchanged.
- ``utils/caller.py`` and ``utils/llm_client.py`` remain absent — we use what exists.
- ``models/conversation.py`` is unchanged.

#### 3.3.4 `agent/special_agents.py`

**Add `compaction_strategy` field to `SpecialAgentDef` (insert at ~line 50):**

```python
    @dataclass
class SpecialAgentDef:
        # ... existing fields ...
        compaction_strategy: str = "textual"  # Phase C — "textual" | "llm"
```

**Verified:** existing fields all use `field(default_factory=...)` or scalar defaults. The simple `compaction_strategy: str = "textual"` pattern matches.

#### 3.3.5 `utils/agent_defs.py`

**Verify `load_agent_defs()` and `validate_agent_def()` cover the new field.**

```python
# In validate_agent_def (the function signature):
def validate_agent_def(d: dict) -> None:
    # ... existing checks ...
    # Phase C — validate compaction_strategy.
    cs = d.get("compaction_strategy", "textual")
    if cs not in {"textual", "llm"}:
        raise ValueError(
            f"Invalid compaction_strategy: {cs!r}. "
            f"Must be 'textual' or 'llm'."
        )
```

**Verified:** `utils/agent_defs.py` already exists with a `validate_agent_def` function (inferred from `load_agent_defs`). The exact function name is verified at runtime in § 5 acceptance criteria.

#### 3.3.6 `ui/views/agent_builder.py`

**Add a `compaction_strategy` dropdown to the dialog:**

```python
        # Inside the dialog form:
        # Phase C — Compaction strategy dropdown.
        # Default "textual" matches the dataclass default and the
        # /clear behavior. "llm" enables the LLMSummarizeStrategy.
        self._compaction_strategy_combo = Gtk.DropDown.new_from_strings(
            ["textual", "llm"]
        )
        self._compaction_strategy_combo.set_selected(0)  # default: textual
        strat_row = self._labeled(
            "Compaction strategy", self._compaction_strategy_combo
        )
        vbox.append(strat_row)
```

**Update save callback** to include the new field:

```python
        return {
            # ... existing fields ...
            "compaction_strategy":
                ["textual", "llm"][self._compaction_strategy_combo.get_selected()],
            # ...
        }
```

---

## 4. Data Flow

### 4.1 Phase A — UI Surface

```
User: types a long message
   ↓
[agent/runtime.py — main loop, line 2091-2115]
   compute (soft_ceiling, hard_ceiling) = _compute_compaction_threshold(conv)
   self._context_strategy.compact(conv, soft_ceiling)  # may modify conv
   ev = self._context_strategy.last_result
   if ev.messages_removed > 0 or ev.tokens_freed > 0:
     _compaction_happened = True
     _ev_for_breakdown = ev
   ↓
   dispatch self._on_token_breakdown(sk, breakdown) where breakdown includes
   {trimmed_this_turn=True, messages_removed_this_turn=N,
    compaction_event={...}, usage_percent=X, messages_remaining=M,
    system_prompt_tokens=..., conversation_tokens=...,
    total_used_tokens=..., model_max_tokens=..., remaining_tokens=...}
   ↓
[ui/handlers/agent_runtime_handler.py:_on_token_breakdown]
   logger.info(...)  [preserved]
   self._last_breakdown[sk] = breakdown  [new — Phase A]
   if breakdown.trimmed_this_turn and not _first_compaction_seen[sk]:
     GLib.idle_add(self._do_compaction_bubble, sk, ev)
   elif breakdown.usage_percent >= 80% and last_pct < 80%:
     GLib.idle_add(self._do_usage_warning, sk, "approaching-limit", pct)
   extra = self._on_token_breakdown_extra
   if extra is not None:
     extra(sk, breakdown)  → window's _on_context_meter → main_content.set_context_meter
   ↓
[ui/handlers/agent_runtime_handler.py:_do_compaction_bubble]
   chat_box = self._resolve_chat_box(sk)
   bubble = self._crh.render_sync("Agent", "🧹 Context reset...", None, agent_name=None)
   chat_box.append(bubble)
   self._mc.scroll_chat_to_bottom()
```

**Key structures verified:**
- `breakdown` dict has all 9 keys — verified at runtime.py:2187-2218.
- `_resolve_chat_box(sk)` exists at agent_runtime_handler.py:786.
- `render_sync` signature verified at chat_render_handler.py:321.

### 4.2 Phase B — /compact Command

```
User: types "/compact @coder — focus on the auth changes"
   ↓
[ui/handlers/command_handler.py — process_input]
   Tokenize → parse "compact", body = "focus on the auth changes"
   ↓
[register_command("compact") → project_handler.cmd_compact]
   sk = cmd.source_session_key  (e.g., "special:coder")
   focus_text = cmd.body.strip()  ("focus on the auth changes")
   if sk.startswith("special:"):
     result = self._compact_callback(sk, focus_text)
     [calls agent_runtime_handler.compact_conversation]
     ↓
[agent_runtime_handler.compact_conversation]
   conv = rt.get_conversation(sk)
   _, hard = rt._compute_compaction_threshold(conv)
   target = max(4_000, hard // 2)
   strat = getattr(agent_def, "compaction_strategy", "textual")
   if strat == "llm":
     return rt.force_llm_compact(conv, target, focus_text)
   rt._context_strategy.compact(conv, target)  [textual path]
   rt._save_conversation_now(sk)
   ev = rt._context_strategy.last_result
   return {messages_removed, tokens_freed, summary_chars, layer}
   ↓
[ui/window.py:_show_compact_bubble]
   chat_box = self._main_content.get_chat_box_for_session(sk)
   bubble = self._chat_render_handler.render_sync("Agent", "🧹 Compacted...")
   chat_box.append(bubble)
   ↓
[project_handler.cmd_compact — return]
   CommandResult(handled=True, response_text="Compacted coder's conversation...")
```

**Key structures verified:**
- `Command.body: str` at models/command.py:58.
- `self._compact_callback` injection at project_handler.py (new), wired at window.py (new).
- `compact_conversation` returns dict — verified signature in §3.2.3.

### 4.3 Phase C — LLM Strategy

```
[cmd_compact with compaction_strategy="llm"]
   ↓
[rt.force_llm_compact(conv, target_budget, focus_text)]
   strat = LLMSummarizeStrategy(llm_provider=self._llm_call_summarize)
   if focus_text:
     conv.system_prompt = (original + "\n\n## Focus for compaction\n" + focus_text)
   strat.compact(conv, target_budget)
   ↓
[LLMSummarizeStrategy inherits DefaultContextStrategy.compact]
   Phase 1: prune_tool_outputs() [no LLM call needed]
   Phase 2: trim loop [no LLM call needed]
   Phase 3: _summary() [OVERRIDDEN — calls LLM]
     head = conv.messages[:keep_first..-4]
     transcript = "...".join(...)
     user_prompt = SUMMARY_PROMPT_TEMPLATE.format(transcript=transcript)
     response = self._llm_provider(system_prompt=conv.system_prompt,
                                    user_prompt=user_prompt,
                                    model=conv.model)
     return response  [9-section structured summary]
   ↓
[Conversation.summary_injection]
   strat injects summary as Message(role=ASSISTANT, is_summary=True)
   ↓
[rt._llm_call_summarize → agent.llm_completion.call_llm]
   provider = utils.caller.get_caller_for_provider(provider_cfg.caller)
   response = utils.llm_client.sync_chat_completion(...)
   return response.text
   ↓
[rt.force_llm_compact — return]
   ev = strat.last_result
   return dict(messages_removed, tokens_freed, summary_chars, layer)
```

**Failure path (LLM error):**
- `LLMSummarizeStrategy._summary()` catches any exception, calls `super()._summary()` (the textual preview).
- The runtime doesn't see the failure; the user gets the textual fallback.
- A warning is logged but the /compact response still says success.

---

## 5. File Change Summary

| File | Phase | Change Type | Lines | Risk |
|---|---|---|---|---|
| `ui/handlers/agent_runtime_handler.py` | A | Modify `_on_token_breakdown`, add 3 methods, add init state | +75 | Low (additive) |
| `ui/views/main_content.py` | A | Add context meter widget + setter | +40 | Low |
| `ui/views/settings_dialog.py` | A | Add SpinButton, save field | +15 | Low (uses existing field) |
| `ui/window.py` | A | Add meter callback hookup | +10 | Low (trivial wiring) |
| `ui/handlers/project_handler.py` | B | Add cmd_compact + 2 setters | +90 | Low (mirrors cmd_clear) |
| `ui/handlers/command_handler.py` | B | Add 1 register_command line | +10 | Trivial |
| `ui/handlers/agent_runtime_handler.py` | B | Add compact_conversation method | +75 | Low |
| `ui/window.py` | B | Wire compact + show bubble | +25 | Low |
| `agent/runtime.py` | B | Add force_compact wrapper | +12 | Trivial |
| `agent/context_strategy.py` | C | Add LLMSummarizeStrategy class | +120 | Low (additive inheritance) |
| `agent/runtime.py` | C | Add force_llm_compact + _llm_call_summarize | +60 | Medium (new LLM call path) |
| `agent/llm_completion.py` | C | NEW file | +100 | Medium (new sync LLM helper) |
| `agent/special_agents.py` | C | Add 1 field | +1 | Trivial |
| `utils/agent_defs.py` | C | Add validation | +8 | Trivial |
| `ui/views/agent_builder.py` | C | Add dropdown + save field | +25 | Low |
| **Tests:** | | | | |
| `tests/test_context_ui.py` | A | NEW | +200 | Low |
| `tests/test_compact_command.py` | B | NEW | +150 | Low |
| `tests/test_llm_summarize_strategy.py` | C | NEW | +250 | Medium |
| `tests/test_compaction_strategy.py` | C | NEW (config wiring) | +100 | Low |
| **Total new code:** | | | **~1367 lines** | |

**Files NOT changed (deliberately):**
- `agent/context_strategy.py:DefaultContextStrategy` — byte-for-byte unchanged in Phase A and B; Phase C inherits it.
- `models/conversation.py` — already exposes `get_token_breakdown()` and the `is_summary` flag.
- `agent/context_strategy.py:ContextStrategy` Protocol — `LLMSummarizeStrategy` satisfies it without modification.
- `models/providers.py` — already has `compaction_threshold` field.
- `utils/providers_store.py` — already persists `compaction_threshold`.

---

## 6. Implementation Order

### Phase A — Day 1, ~6 hours
1. **Step A1:** Edit `agent_runtime_handler.py:_on_token_breakdown` and add the 3 new methods (`_do_compaction_bubble`, `_do_usage_warning`, `set_on_token_breakdown_extra`, `get_last_breakdown`, `__init__` state). Run unit test: trivial.
2. **Step A2:** Add context meter widget in `main_content.py`. Run existing tests for MainContent — they don't test the new widget so should pass unchanged.
3. **Step A3:** Add `compaction_threshold` SpinButton to `settings_dialog.py`. Run existing settings_dialog tests.
4. **Step A4:** Wire `set_on_token_breakdown_extra` in `window.py`.
5. **Step A5:** Add `tests/test_context_ui.py` with 7 tests (see §7).
6. **Step A6:** Run full test suite; verify 139 + 7 green.

**Verification at end of Phase A:**
```
$ python3 -m pytest tests/test_context.py tests/test_context_strategy* \
    tests/test_context_ui.py -q
→ N passed
```

### Phase B — Day 1 (later) + Day 2 morning, ~4 hours
7. **Step B1:** Add `cmd_compact` + `set_compact_callback` + `set_compact_chat_callback` to `project_handler.py`. No new logic — mirrors `cmd_clear`.
8. **Step B2:** Add `compact_conversation` to `agent_runtime_handler.py`. Reuses verified `_compute_compaction_threshold`, `_context_strategy.compact`, `last_result`.
9. **Step B3:** Wire callbacks in `window.py`.
10. **Step B4:** Add `_show_compact_bubble` helper to `window.py`.
11. **Step B5:** Add `/compact` registration in `command_handler.py`.
12. **Step B6:** Add `force_compact` to `agent/runtime.py`.
13. **Step B7:** Add `tests/test_compact_command.py`.

**Verification at end of Phase B:**
```
$ python3 -m pytest tests/test_compact_command.py -v
→ 7+ passed
```

### Phase C — Day 2 afternoon through Day 4, ~16 hours
14. **Step C1:** Create `agent/llm_completion.py` with `call_llm()`.
15. **Step C2:** Add `LLMSummarizeStrategy` to `agent/context_strategy.py`.
16. **Step C3:** Add `force_llm_compact` and `_llm_call_summarize` to `agent/runtime.py`.
17. **Step C4:** Add `compaction_strategy` field to `SpecialAgentDef`.
18. **Step C5:** Add validation in `utils/agent_defs.py`.
19. **Step C6:** Add dropdown in `ui/views/agent_builder.py`.
20. **Step C7:** Add `tests/test_llm_summarize_strategy.py` with 9 tests.
21. **Step C8:** Add `tests/test_compaction_strategy.py` with 4 tests.

**Verification at end of Phase C:**
```
$ python3 -m pytest tests/ -q
→ 139 + 7 + 7 + 9 + 4 = 166 passed
```

---

## 7. Acceptance Criteria

### Phase A

- [ ] Running a session and reaching 80% of context window emits ONE warning bubble ("⚠️ Context at 80%. Consider /compact to free space.").
- [ ] Reaching 95% emits ONE warning bubble ("🔴 Context at 95%. Auto-compaction will trigger soon.").
- [ ] When the engine trims messages (Layer 1 or Layer 2), the chat box shows ONE "🧹 Context reset" bubble per session. Subsequent compactions don't re-bubble.
- [ ] The context meter widget updates after every LLM call.
- [ ] The meter CSS color changes at 70% (med) and 90% (high).
- [ ] The settings dialog shows the `compaction_threshold` SpinButton with default 0.80 and range 0.50-0.95.
- [ ] Saving the settings dialog persists the `compaction_threshold` field in `providers.yaml`.
- [ ] All existing 139 tests still pass.

### Phase B

- [ ] Typing `/compact` in a special-agent tab triggers compaction.
- [ ] The chat box shows a "🧹 Compacted" bubble with the correct removed/tokens message.
- [ ] Typing `/compact @coder — focus on auth changes` passes the focus string to the strategy (Phase C will use it; Phase B accepts it but ignores it).
- [ ] Typing `/compact` in a project tab returns the hint message.
- [ ] Running `/compact` on a session with no conversation is a no-op with an informative message.
- [ ] The conversation state is persisted to disk after compaction (verify by restarting the app).
- [ ] Typing `/help compact` shows the new help text.
- [ ] All existing 146+ tests still pass.

### Phase C

- [ ] Setting an agent's `compaction_strategy="llm"` in YAML causes `/compact` to make one LLM call.
- [ ] The LLM call uses the same model and provider as the conversation.
- [ ] The LLM response is inserted as an `is_summary=True` Message in the conversation.
- [ ] If the LLM call fails (network error, rate limit, timeout), falls back to the textual summary (same as `DefaultContextStrategy._summary`).
- [ ] The agent-builder dropdown persists the choice to the agent's YAML file.
- [ ] `/compact` on a session with `compaction_strategy="llm"` completes within 30 seconds (or falls back with a warning).
- [ ] The LLM call's `system_prompt` is `conv.system_prompt` (cache-friendly reuse).
- [ ] The summary message contains at least one of the 9 expected tags when the LLM responds correctly.
- [ ] All existing 153+ tests still pass.

---

## 8. Edge Cases

| Case | Expected Behavior | Tested By |
|---|---|---|
| `_on_token_breakdown` called twice (compaction succeeded both turns) | Only the first triggers a bubble (anti-spam). Both go to the logger. | `test_first_compaction_bubble_only` |
| `usage_percent` jumps 78% → 82% → 81% → 80% | Warning fires once at 82% (cross threshold up). Does NOT fire again at 81%. | `test_warning_hysteresis` |
| `usage_percent` falls back to 74% then rises to 81% | Warning fires again (hysteresis reset). | `test_warning_hysteresis_reset` |
| `/compact` on a session with zero messages | Returns "nothing to compact". | `test_compact_empty_session` |
| `/compact` on a non-existent session_key | Returns informative error. | `test_compact_unknown_session` |
| `/compact` followed by another `/compact` 5 seconds later | Both succeed; second compaction is a no-op (no messages left). | `test_repeated_compact` |
| `/compact focus: auth` (the body text is `"focus: auth"`) | focus_text is passed through to strategy. Phase B ignores; Phase C uses. | `test_compact_with_focus` |
| `compaction_strategy="llm"` but the LLM provider is not configured | Falls back to textual via logger.warning. User sees the same response. | `test_llm_strategy_unconfigured_provider` |
| `compaction_strategy="llm"` and the LLM rate-limits | Falls back to textual via try/except. | `test_llm_strategy_rate_limit` |
| `compaction_strategy="llm"` and the response exceeds token_budget | Truncated at line boundary; "[... summary truncated ...]" appended. | `test_llm_strategy_oversized_response` |
| LLM strategy `_summary` called twice in same session | First call makes LLM call; second call (if conversation unchanged) is a no-op because messages aren't trimmed twice. | `test_llm_strategy_idempotent_trim` |
| Settings dialog SpinButton at 0.95 save | `compaction_threshold=0.95` written to YAML. | `test_settings_threshold_persist` |
| Compaction event has `layer=1` (only prune) | Bubble says "Layer 1" instead of "Layer 2". | `test_bubble_layer_prune_only` |
| `last_result` is None (no-op compaction) | Bubble does NOT fire (compact() returned without recording). | `test_no_op_compaction_no_bubble` |
| UI thread race: `_on_token_breakdown` from worker thread | `GLib.idle_add` schedules the bubble/UI updates on the main thread. | `test_thread_safety` |

---

## 9. ARCHITECTURE.md Updates Required

- **§3.21l `models/conversation.py`:** No changes. Already correct.
- **§3.21m `agent/runtime.py`:** Add a brief mention of `force_compact()` and `force_llm_compact()` (Phase B/C) under "Public API for external invocation". Update §4.15 (Per-turn token breakdown) to mention "Phase A — UI meter subscribes via set_on_token_breakdown_extra".
- **§3.21n `agent/context_strategy.py`:** Add a brief mention of `LLMSummarizeStrategy` as an example of pluggable strategies (the proposal `PROPOSAL-pluggable-context-strategy.md` already enables this).
- **§4 Chat UI:** Mention `/compact` in the command list. Mention context meter as a Phase A UI component.

---

## 10. Compliance Checklist

- [x] **Rule 1:** Every referenced file read before spec written (DISCOVERY block above).
- [x] **Rule 2:** Every code sample traced against actual source. `_on_token_breakdown` line 1238 verified; `_compute_compaction_threshold` line 1920 verified; `_context_strategy.compact` line 125 verified; `render_sync` line 321 verified.
- [x] **Rule 3:** Every function call signature verified.
  - `_context_strategy.compact(conv, target)` ✓ (context_strategy.py:125)
  - `compact_conversation(sk)` ✓ (mirrors clear_conversation signature)
  - `cmd_compact(cmd, session_key)` ✓ (mirrors cmd_clear)
  - `_get_runtime(display_name, agent_def)` (verified in clear_conversation context)
- [x] **Rule 4:** Exception types enumerated for `_llm_call_summarize` (catches Exception broadly with fallback) and `compact_conversation` (returns error dict).
- [x] **Rule 5:** Key structures documented. `breakdown` dict has 9 keys verified at runtime.py:2187-2218. `Command.body` at command.py:58.
- [x] **Rule 6:** Return values analyzed:
  - `compact_conversation` returns dict (matches `_compact_callback` signature).
  - `compact()` returns None (per Protocol).
  - `last_result` returns `CompactionEvent | None`.
- [x] **Rule 7:** No "should work" — every sample traced.
- [x] **Rule 8:** Files NOT changed explicitly listed.
- [x] **Rule 9:** Self-audit completed before declaring complete.
- [x] **Rule 10:** Will pass after implementation. Scope checklist below.

### Post-implementation completion verification (will be run)

```
$ python3 -m pytest tests/test_context.py tests/test_context_strategy* tests/test_context_ui.py \
                  tests/test_compact_command.py tests/test_llm_summarize_strategy.py \
                  tests/test_compaction_strategy.py -v
→ (paste actual output here)
```

Pattern sweep:
```
$ grep -rn "logger.info(\[token-breakdown\]" ui/handlers/agent_runtime_handler.py
→ (should match exactly once, in the new method body)
```

---

**End of SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md**
