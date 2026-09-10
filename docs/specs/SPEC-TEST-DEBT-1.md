# SPEC: Test Debt 1 — BUG-21 Turn-Start Signal Redesign (dedicated `on_turn_start` callback)

**Date:** 2026-09-10
**Author:** Supervisor (option (b) per PM decision — complete the fix, not fix-the-tests-only)
**Status:** Draft — for implementation
**Depends on:** SPEC-AUDIT-CLEANUP-3 (Part A delta coalescing — its empty-delta bypass is preserved); RACE-FIX v4 (send-side clear + turn tokens)
**Target branch:** main (base `64c73f4`)
**Closes:** 2 of the 40-failure baseline — `TestLocalAgentDrawerEmissions::test_tool_only_turn_tool_starts_not_suppressed` and `::test_started_turn_sessions_clears_ended_flag_on_fresh_tool_start` (replaced)

> Architecture compliance: follows ARCHITECTURE.md §3.21m.3 (callback Protocols in `agent/callbacks.py`, `agent/` imports only from `typing`), §8.6 layer rules, and the handler-dispatch pattern (`_on_*` wrapper → GLib.idle_add → `_do_*` main-thread body). No handler-to-handler imports. No new modules.

---

## DISCOVERY (Rule 1 — read before writing)

- Read `agent/runtime.py`: `_dispatch` (:573-597) wraps callbacks in `GLib.idle_add` (main thread in production) and passes `_turn_token` as a keyword arg. `_run_loop` (:1218) registers the turn token in `_turn_tokens[sk]` under `_state_lock` BEFORE the early-exit paths, then dispatches the BUG #21 empty-delta signal at :1281-1287 (`if self._on_text_delta: _dispatch(self._on_text_delta, sk, "", _turn_token=turn_token)`). Real text deltas dispatch at :2226. `cancel()` (:973) dispatches `_on_error` with the session's ACTIVE token (same token as the in-flight turn). `send_message` (:944) passes `self._turn_token` (runtime-global, assigned by the handler's send path) as the thread arg.
- Read `agent/callbacks.py` (268 lines): 9 Protocols, all with keyword-only `_turn_token: object | None = None`. `OnTextDelta` docstring says "Empty strings are valid — the runtime uses them as turn-start signals" (now stale). Names `OnTurnStart` / `on_turn_start` / `_do_turn_start` are unused anywhere (collision sweep: empty).
- Read `ui/handlers/agent_runtime_handler.py` (1986 lines): `_on_text_delta` (:1005) has the AC3 empty-bypass (uncoalesced dispatch of empty deltas). `_do_text_delta_inner` (:1106) early-returns on `not text and not streaming_text` (:1121-1125) BEFORE the start-bubble block (:1146-1162) — **this ordering is the BUG-21 root cause**: the runtime's turn-start signal (empty delta) never reaches the start-bubble logic. The start-bubble block starts the streaming bubble, fires `_on_agent_start_cb` (progress bar) and the drawer-lifecycle "start" separator — but does NOT clear `_ended_sessions` (RACE-FIX v4 moved the clear to `send_to_special_agent` :878, the ONLY clear site). `_do_tool_call_start` (:1189+) suppresses tool_starts when `sk in _ended_sessions`. Three `end_streaming` callers lack the BUG #22 render-guard that `_do_response_complete` has (:1640-1645): `_do_error` (:1957), `_do_compaction_bubble` (:1811), `_do_usage_warning` (:1859). **`_started_turn_sessions` is DEAD CODE**: initialized (:131), discarded 3× (:1158, :1701, :1986), never added to, never read (grep-verified).
- Read `tests/test_agent_runtime.py` (5737 lines): both failing tests assert mechanisms that don't exist (empty-delta clear; `_started_turn_sessions` tracking). `test_text_delta_fires_incrementally` (:1431) expects 4 deltas incl. the leading `""`. `test_tool_only_turn_no_empty_chat_bubble` (:4287) currently PASSES (1 passed, 2 failed verified live). `_QueueGLib` is module-level. `_make_handler` (:3171) builds the handler with `GLib_module=None` and a MagicMock `crh`. `TestLocalAgentDrawerEmissions._make_handler` (:3879) registers a Coder `SpecialAgentDef` (no `llm_name` → `_resolve_agent_model` returns None) and captures bubbles + lifecycle events. 10 fixtures construct `AgentRuntime(..., on_text_delta=lambda ...)` with no `on_turn_start` (runtime skips the dispatch when None — degradation-safe).
- Read `ui/handlers/chat_render_handler.py`: `end_streaming(sk, agent_name=None, render=True)` (:623) no-ops when no streaming bubble exists; `update_streaming` (:495) no-ops when no bubble — degradation-safe. `start_streaming(sk, container, role="Agent")` (:434).
- Read `agent/special_agents.py`: `SpecialAgentDef` is a dataclass; `get_self_improvement_config()` exists (traced through `send_to_special_agent` for the send-side test).
- Architecture owner: `agent/callbacks.py` owns the callback contract; `agent/runtime.py` owns dispatch; `AgentRuntimeHandler` owns render-pipeline state (`_ended_sessions`, `_session_completed`, `_turn_tokens`).
- Existing patterns copied: the `_on_*` → GLib.idle_add → `_do_*` wrapper pattern; the token-mismatch rejection pattern (`_do_response_complete` :1570-1576); the BUG #22 render-guard pattern (:1640-1645).

**Root cause (both failures):** the BUG #21 fix's mechanism (empty text delta as turn-start signal) contradicts the code it was supposed to trigger — `_do_text_delta_inner`'s empty-return fires before the start-bubble block, and the RACE-FIX v4 flag clear lives on the send side, not in the delta path. The BUG #14 mechanism (`_started_turn_sessions`) was never implemented at all. Fix and tests disagree on mechanism; both shipped failing (pattern `incomplete-fix-test-pair`, AC3 post-mortem §4).

---

## 1. Overview

**Problem.** Tool-only turns (LLM streams zero text deltas) never get a turn-start signal that works: the runtime's empty-delta signal dies at `_do_text_delta_inner`'s empty-return, so the streaming bubble, progress bar, and drawer separator never start, and the previous turn's `_ended_sessions` flag suppresses the new turn's tool_starts (2 baseline failures). Additionally, three `end_streaming` callers can render an empty header bubble on tool-only turns (BUG #22 class), and `_started_turn_sessions` is dead code.

**Solution.** Replace the overloaded empty-delta signal with a dedicated `on_turn_start` callback dispatched at the top of `_run_loop`. The handler's `_do_turn_start` starts the streaming bubble + lifecycle for EVERY turn, guarded against the two out-of-order cases (stale token, terminal-event-first). The flag lifecycle stays exactly as RACE-FIX v4 designed it: `_ended_sessions` is cleared ONLY by `send_to_special_agent`. Add the BUG #22 render-guard to the three unguarded `end_streaming` callers. Delete the dead `_started_turn_sessions` set. Rewrite/replace the 4 affected tests, add 6 new ones.

**Scope.**

| In | Out |
|---|---|
| `agent/callbacks.py` — new `OnTurnStart` Protocol | `chat_render_handler.py` — `end_streaming` contract already correct |
| `agent/runtime.py` — ctor param + `_run_loop` dispatch swap | `gateway_handler.py` — gateway path doesn't use this pipeline (grep-verified) |
| `ui/handlers/agent_runtime_handler.py` — `_on_turn_start`/`_do_turn_start`, wiring, render-guards, dead-set deletion, comment truth-fixes | `window.py`, `models/`, `tools.py` — no wiring needed (handler wires itself in `_get_runtime`) |
| `tests/test_agent_runtime.py` — 4 rewrites + 6 new tests | The other 38 baseline failures (later phases of this unit) |
| `docs/ARCHITECTURE.md` — §3.21m.3 + ctor signature | |

**Architecture principles that apply:** callback Protocols as the runtime↔UI contract (§3.21m.3); single-chokepoint dispatch through `_dispatch`; main-thread-only GTK work via GLib.idle_add; per-turn token staleness rejection (RACE-FIX v4).

---

## 2. Changes by File

### 2.1 `agent/callbacks.py`

**Edit A — module docstring (line 3):** "The runtime accepts 9 callbacks" → "The runtime accepts 10 callbacks".

**Edit B — `OnTextDelta` docstring (~line 45):** DELETE the sentence "Empty strings are valid — the runtime uses them as turn-start signals." Replace with: "Empty strings are valid (providers may send empty content deltas); the turn-start signal is the separate `OnTurnStart` callback."

**Edit C — add `OnTurnStart` Protocol immediately after `OnTextDelta` (before `OnToolCallStart`):**

```python
class OnTurnStart(Protocol):
    """Turn-start callback.

    Fires once at the top of ``_run_loop`` BEFORE any LLM call or tool
    processing — for every turn, including tool-only turns (which stream
    zero text deltas). Replaces the BUG #21 empty-delta signal (an
    ``on_text_delta`` dispatch with ``""``) that never reached the
    handler's start-bubble logic (``_do_text_delta_inner``'s empty-return
    fired first, so the regression tests shipped failing).

    Args:
        session_key: Conversation session key (e.g. "special:coder").
        _turn_token: See ``OnTextDelta``.
    """

    def __call__(
        self,
        session_key: str,
        *,
        _turn_token: object | None = None,
    ) -> None: ...
```

### 2.2 `agent/runtime.py`

**Edit A — import block (:36-44):** add `OnTurnStart` to the `from agent.callbacks import (...)` list (alphabetical position after `OnTextDelta`).

**Edit B — constructor (:461-471):** add parameter after `on_text_delta`:
```python
        on_turn_start: OnTurnStart | None = None,
```
and attr assignment after `self._on_text_delta = on_text_delta` (:473):
```python
        self._on_turn_start = on_turn_start
```

**Edit C — constructor docstring param list (~:437):** add `on_turn_start: (session_key) — fired once at the top of _run_loop, before any LLM call (BUG #21 redesign).` after the `on_text_delta` line.

**Edit D — `_run_loop` (:1281-1287): REPLACE the comment block + dispatch:**

```python
            # BUG #21 (redesigned): Fire a dedicated turn-start signal BEFORE
            # any LLM call or tool processing. This guarantees the handler
            # starts the streaming bubble + emits the drawer lifecycle-start
            # separator for EVERY turn — including tool-only turns (LLM
            # streams zero text_delta events). The old mechanism (an empty
            # on_text_delta dispatch) never reached the handler's start-bubble
            # logic: _do_text_delta_inner's empty-return fired first, so the
            # BUG #21 regression tests shipped failing (see
            # docs/specs/SPEC-TEST-DEBT-1.md).
            if self._on_turn_start:
                self._dispatch(self._on_turn_start, session_key, _turn_token=turn_token)
```

Note: the dispatch keeps `_turn_token=turn_token` so the handler can reject stale cross-turn signals. When `on_turn_start` is None (legacy fixtures), no dispatch happens — identical to the old `if self._on_text_delta:` guard.

### 2.3 `ui/handlers/agent_runtime_handler.py`

**Edit A — wiring in `_get_runtime` (:741-753):** add after the `on_text_delta=self._on_text_delta,` line:
```python
            on_turn_start=self._on_turn_start,
```

**Edit B — add `_on_turn_start` + `_do_turn_start` immediately BEFORE `_on_text_delta` (:1005):**

```python
    def _on_turn_start(self, session_key: str, _turn_token: object = None) -> None:
        """AgentRuntime turn-start callback (BUG #21 redesign).

        Dispatched once by the runtime at the top of _run_loop, BEFORE any
        LLM call or tool processing — for every turn, including tool-only
        turns. Runs in the runtime's dispatch context (GLib.idle_add wraps
        it onto the main thread in production). Delegates to _do_turn_start.
        """
        if self._GLib is not None:
            self._GLib.idle_add(self._do_turn_start, session_key, _turn_token)
        else:
            self._do_turn_start(session_key, _turn_token)

    def _do_turn_start(self, session_key: str, turn_start_token: object = None) -> None:
        """Main-thread portion of _on_turn_start (BUG #21 redesign).

        Starts the streaming bubble + fires the agent-start lifecycle for
        EVERY turn — including tool-only turns (which stream zero text
        deltas). The old mechanism (an empty text delta) never reached this
        logic: _do_text_delta_inner's empty-return fired first.

        Flag lifecycle (RACE-FIX v4, unchanged): _ended_sessions is cleared
        ONLY by send_to_special_agent at new-turn send time. This method
        does NOT clear it — clearing here would re-open the stale-delta
        race (a stale dispatch arriving after completion would clear the
        flag and start an orphan bubble). The guards below handle the two
        out-of-order cases:

        1. Stale cross-turn signal: turn_start_token doesn't match the
           current token (a newer turn's send already reassigned it) → drop.
        2. Terminal-first race: a terminal event for THIS turn (error /
           complete / cancel, same token) already landed on the main thread
           before this dispatch ran → session is in _ended_sessions → drop
           (starting a bubble now would orphan it after the error bubble).
        """
        if turn_start_token is not None:
            current_token = self._turn_tokens.get(session_key)
            if turn_start_token is not current_token:
                logger.debug(
                    "_do_turn_start: dropping stale turn-start (token mismatch) for %s",
                    session_key,
                )
                return
        if session_key in self._ended_sessions:
            logger.debug(
                "_do_turn_start: dropping turn-start for ended session %s "
                "(terminal event landed first)",
                session_key,
            )
            return
        if self._crh is None:
            return
        if not self._crh.is_streaming(session_key):
            chat_box = self._resolve_chat_box(session_key)
            if chat_box is not None:
                self._crh.start_streaming(session_key, chat_box, "Agent")
                # Fire lifecycle: agent started → ActivityHandler progress bar
                if self._on_agent_start_cb:
                    self._on_agent_start_cb(session_key)
                # Do NOT clear _ended_sessions here — send_to_special_agent
                # owns the clear (RACE-FIX v4; see docstring).
                # drawer-lifecycle start → drawer separator
                if self._on_drawer_lifecycle is not None:
                    agent_def_dl = self._agents.get(session_key)
                    agent_name_dl = agent_def_dl.display_name if agent_def_dl else "Agent"
                    self._on_drawer_lifecycle(session_key, agent_name_dl, "start")
```

**Edit C — `_on_text_delta` empty-bypass comment (:1019-1031): REPLACE the comment** (keep the code):
```python
        # Empty deltas bypass coalescing: providers may send empty content
        # deltas (delta: {content: ""}); routing them uncoalesced is cheap
        # and _do_text_delta_inner's empty-return makes them a no-op when
        # no text has accumulated. (The turn-start signal used to ride this
        # path as an empty delta — it moved to the dedicated on_turn_start
        # callback; see _do_turn_start.)
```

**Edit D — `_do_text_delta` docstring (~:1088-1097):** replace the phrase "and the empty-delta turn-start signal (empty `text` returns before any rendering, exactly as before)" with "and provider-sent empty deltas (empty `text` with no accumulated text returns before any rendering)".

**Edit E — `_do_text_delta_inner`:**
- Keep the empty-return (:1121-1125), the ended-guard, the token guard, and the start-bubble fallback block **as the degradation path** (bubble start when turn-start was missed — legacy callers / `on_turn_start=None`).
- DELETE line :1158 `self._started_turn_sessions.discard(session_key)` and its stale BUG #2 comment lines referencing it; keep the RACE-FIX comment ("Do NOT clear _ended_sessions here...") and the drawer-lifecycle block.
- Update the block's leading comment: the fallback now reads "starts the bubble if turn-start didn't (degradation path)".

**Edit F — `_do_tool_call_start` comment block (:1189-1199): REPLACE:**
```python
        # BUG #2 / BUG #18: Suppress ALL tool_start dispatches that arrive while
        # the session is in the ended state. We do NOT clear the flag here —
        # clearing on the first stale call let a second stale call proceed
        # (BUG #18). The flag is cleared ONLY by send_to_special_agent when a
        # NEW turn starts (RACE-FIX v4), so a genuine new turn's tool_starts
        # are never suppressed. Tool-only turns are covered by the runtime's
        # on_turn_start dispatch (BUG #21 redesign) — the old "Known limitation
        # (BUG #14)" no longer applies.
```

**Edit G — `_do_response_complete` (:1697-1701):** DELETE `self._started_turn_sessions.discard(session_key)` + its BUG #14 comment lines; keep the `_ended_sessions` idempotent-add comment.

**Edit H — `_do_error` (:1956-1958): REPLACE the end_streaming call with the BUG #22 render-guard:**
```python
        if self._crh is not None:
            # BUG #22 guard (same pattern as _do_response_complete): on a
            # tool-only turn the streaming bubble exists but holds no text —
            # end_streaming must clean up WITHOUT rendering an empty bubble.
            streaming_text = self._crh.get_streaming_text(session_key) or ""
            self._crh.end_streaming(
                session_key,
                agent_name=resolved_name,
                render=bool(streaming_text.strip()),
            )
```

**Edit I — `_do_compaction_bubble` (:1810-1812): REPLACE:**
```python
        if self._crh is not None:
            # BUG #22 guard: tool-only turn — no empty bubble on cleanup.
            streaming_text = self._crh.get_streaming_text(session_key) or ""
            self._crh.end_streaming(
                session_key, agent_name=None, render=bool(streaming_text.strip()),
            )
```

**Edit J — `_do_usage_warning` (:1858-1860): REPLACE** (inside the existing `if self._crh is not None:` block):
```python
            # BUG #22 guard: tool-only turn — no empty bubble on cleanup.
            streaming_text = self._crh.get_streaming_text(session_key) or ""
            self._crh.end_streaming(
                session_key, agent_name=None, render=bool(streaming_text.strip()),
            )
```

**Edit K — `_do_error` (:1984-1986):** DELETE `self._started_turn_sessions.discard(session_key)` + its BUG #14 comment lines.

**Edit L — `__init__` (:129-131):** DELETE the `_started_turn_sessions` init + its BUG #14 comment block.

**Note on `end_streaming` no-op safety:** when no streaming bubble exists, `end_streaming` returns at its top guard and the `render` kwarg is moot — the guards change nothing for non-streaming sessions (traced: `end_streaming` :627 `if session_key not in self._streaming_bubbles: return`).

### 2.4 `tests/test_agent_runtime.py`

All tests below live in `TestLocalAgentDrawerEmissions` unless noted. Line numbers as of `64c73f4`; anchor to the test names, not the lines.

**Edit A — class docstring (~:3866-3877):** update "- drawer-lifecycle start from _do_text_delta agent-start site" → "- drawer-lifecycle start from _do_turn_start (BUG #21 redesign)".

**Edit B — REWRITE `test_text_delta_fires_incrementally` (TestStreaming, :1431-1462):** same mock-provider setup; add a turn-start capture and drop the leading-empty expectation:
```python
        deltas = []
        rt._on_text_delta = lambda sk, d: deltas.append(d)
        turn_starts = []
        rt._on_turn_start = lambda sk: turn_starts.append(sk)
        # ... (unchanged mock provider + patch block) ...
        # The turn-start signal moved to on_turn_start (BUG #21 redesign):
        # exactly one turn-start, one delta per chunk — no leading "".
        assert turn_starts == [sk], (
            f"Expected exactly 1 turn-start for {sk}, got {turn_starts}"
        )
        assert len(deltas) == 3, f"Expected 3 deltas, got {len(deltas)}: {deltas}"
        assert deltas[0] == "Hello"
        assert deltas[1] == " world"
        assert deltas[2] == "!"
        rt.stop()
```
(Note: `rt._run_loop(sk, "say hello")` is called directly with `turn_token=None`, so `_dispatch` invokes the patched lambda with no kwarg — `lambda sk:` is the correct arity. Production always passes the token.)

**Edit C — REWRITE `test_tool_only_turn_tool_starts_not_suppressed` (:4248-4281):**
```python
        handler, crh, mc = self._make_handler_with_agent()
        crh.is_streaming.return_value = False
        chat_box = MagicMock()
        handler._resolve_chat_box = MagicMock(return_value=chat_box)
        handler._crh = crh

        # Simulate the real sequence: prior turn ended → new send cleared the
        # flag (send_to_special_agent is the ONLY clear site — see
        # test_send_to_special_agent_clears_ended_sessions). So at turn-start
        # time the flag is already absent; this test starts from that state.

        # Simulate the runtime's turn-start signal — this is the fix.
        handler._do_turn_start("special:coder")

        # Now a tool_start arrives (tool-only turn, no real text)
        handler._do_tool_call_start("special:coder", "read_file", {"path": "test.txt"})

        types = [b.type for b in self._bubbles]
        assert "tool_start" in types, (
            f"BUG #21: tool_start suppressed for tool-only turn; got {types}"
        )
        start_events = [e for e in self._lifecycle_events if e[2] == "start"]
        assert len(start_events) == 1, (
            f"BUG #21: expected 1 lifecycle-start event, got {len(start_events)}: {self._lifecycle_events}"
        )
```

**Edit D — UPDATE `test_tool_only_turn_no_empty_chat_bubble` (:4287-4308):** replace the `_do_text_delta("special:coder", "")` line with `handler._do_turn_start("special:coder")` (docstring: "starts a streaming bubble" — now via turn-start). All assertions unchanged (traced: still passes — `get_streaming_text` stubbed `""` → `render=False`).

**Edit E — REPLACE `test_started_turn_sessions_clears_ended_flag_on_fresh_tool_start` (:4316-4351) with:**
```python
    def test_send_to_special_agent_clears_ended_sessions(self):
        """RACE-FIX v4 send-side clear: send_to_special_agent is the ONLY
        site that clears _ended_sessions — the previous turn's ended flag
        must not suppress the new turn's tool_starts.

        Replaces the BUG #14 _started_turn_sessions test: that mechanism
        was never implemented (the set was dead code) and is superseded by
        the on_turn_start redesign.
        """
        handler, crh, mc = self._make_handler_with_agent()
        handler._ended_sessions.add("special:coder")
        handler._session_completed.add("special:coder")

        # Stub the runtime so no real AgentRuntime/LLM is constructed.
        rt = MagicMock()
        rt.get_conversation.return_value = None
        rt.load_conversation.return_value = None
        handler._get_runtime = MagicMock(return_value=rt)

        handler.send_to_special_agent("special:coder", "hello")

        assert "special:coder" not in handler._ended_sessions, (
            "send_to_special_agent must clear _ended_sessions for the new turn"
        )
        assert "special:coder" not in handler._session_completed
        rt.send_message.assert_called_once_with("special:coder", "hello")
        assert handler._turn_tokens["special:coder"] is not None
```
(Traced through `send_to_special_agent`: agent registered, `_active_project` set by the class fixture → no early return; `_resolve_agent_model` → None (no `llm_name`); mocked rt absorbs `create_conversation`; the clear at :878 fires before `send_message`.)

**Edit F — ADD 6 new tests** (same class):

```python
    def test_on_turn_start_dispatches_via_glib(self):
        """The _on_turn_start wrapper queues _do_turn_start onto the main
        thread via GLib.idle_add (same pattern as the other _on_* methods)."""
        handler, crh, mc = self._make_handler_with_agent()
        glib = _QueueGLib()
        handler._GLib = glib
        crh.is_streaming.return_value = False
        chat_box = MagicMock()
        handler._resolve_chat_box = MagicMock(return_value=chat_box)

        handler._on_turn_start("special:coder")

        assert len(glib.queue) == 1, "turn-start must be dispatched via idle_add"
        glib.drain()
        start_events = [e for e in self._lifecycle_events if e[2] == "start"]
        assert len(start_events) == 1

    def test_turn_start_stale_token_rejected(self):
        """_do_turn_start drops a signal whose token doesn't match the
        current turn (stale cross-turn dispatch after a newer send)."""
        handler, crh, mc = self._make_handler_with_agent()
        crh.is_streaming.return_value = False
        chat_box = MagicMock()
        handler._resolve_chat_box = MagicMock(return_value=chat_box)
        handler._crh = crh
        handler._turn_tokens["special:coder"] = object()
        stale = object()

        handler._do_turn_start("special:coder", stale)

        crh.start_streaming.assert_not_called()
        assert not [e for e in self._lifecycle_events if e[2] == "start"]

    def test_turn_start_after_terminal_event_dropped(self):
        """Cancel-race guard: a terminal event (error/complete/cancel) that
        lands BEFORE the turn-start dispatch must win — no orphan bubble,
        no flag clear. (cancel() dispatches _do_error with the SAME token
        as the in-flight turn, so the token check alone can't order them.)"""
        handler, crh, mc = self._make_handler_with_agent()
        crh.is_streaming.return_value = False
        chat_box = MagicMock()
        handler._resolve_chat_box = MagicMock(return_value=chat_box)
        handler._crh = crh
        token = object()
        handler._turn_tokens["special:coder"] = token
        handler._ended_sessions.add("special:coder")  # terminal landed first

        handler._do_turn_start("special:coder", token)  # same-token race

        crh.start_streaming.assert_not_called()
        assert "special:coder" in handler._ended_sessions
        assert not [e for e in self._lifecycle_events if e[2] == "start"]

    def test_do_error_renders_no_empty_bubble_on_tool_only_turn(self):
        """BUG #22 guard on _do_error: tool-only turn (bubble from
        turn-start, no text) — error path must end_streaming(render=False)."""
        handler, crh, mc = self._make_handler_with_agent()
        crh.is_streaming.return_value = True  # bubble exists from turn-start
        chat_box = MagicMock()
        handler._resolve_chat_box = MagicMock(return_value=chat_box)
        handler._crh = crh
        crh.get_streaming_text.return_value = ""  # tool-only: no content

        handler._do_error("special:coder", "boom")

        crh.end_streaming.assert_called_once()
        kwargs = crh.end_streaming.call_args.kwargs
        assert kwargs.get("render") is False, (
            f"BUG #22: _do_error must pass render=False for empty streaming "
            f"text; got {kwargs}"
        )

    def test_do_compaction_bubble_renders_no_empty_bubble_on_tool_only_turn(self):
        """BUG #22 guard on _do_compaction_bubble (same pattern)."""
        handler, crh, mc = self._make_handler_with_agent()
        chat_box = MagicMock()
        handler._resolve_chat_box = MagicMock(return_value=chat_box)
        handler._crh = crh
        crh.get_streaming_text.return_value = ""

        handler._do_compaction_bubble("special:coder", {
            "messages_removed": 3, "tokens_freed": 1200,
            "layer": 2, "trigger": "auto",
        })

        crh.end_streaming.assert_called_once()
        assert crh.end_streaming.call_args.kwargs.get("render") is False

    def test_do_usage_warning_renders_no_empty_bubble_on_tool_only_turn(self):
        """BUG #22 guard on _do_usage_warning (same pattern)."""
        handler, crh, mc = self._make_handler_with_agent()
        chat_box = MagicMock()
        handler._resolve_chat_box = MagicMock(return_value=chat_box)
        handler._crh = crh
        crh.get_streaming_text.return_value = ""

        handler._do_usage_warning("special:coder", "approaching-limit", 82.0)

        crh.end_streaming.assert_called_once()
        assert crh.end_streaming.call_args.kwargs.get("render") is False
```

**Edit G — `TestDeltaCoalescing::test_empty_delta_still_reaches_main_thread` (:5695-5705):** update the DOCSTRING only (assertions unchanged, traced still-green): "(4) empty-delta bypass preserved: provider-sent empty deltas still dispatch to the main thread uncoalesced, and the empty delta still returns before accumulation. (The runtime's turn-start signal moved to on_turn_start.)"

### 2.5 `docs/ARCHITECTURE.md`

- **:1797** (runtime ctor signature): add `on_turn_start` to the documented parameter list.
- **§3.21m.3 (:1890-1912):** "9 Protocol classes" → "10 Protocol classes" (two places: Responsibility line and Owns line); add `OnTurnStart` to both name lists; update the Public API comment "All 9 protocols" → "All 10"; optionally add `OnTurnStart` to the sample block.
- Grep-verified: ARCHITECTURE.md contains no "BUG #21" or empty-delta-mechanism prose to correct beyond these.

**Files NOT changed (Rule 8):**
- `ui/handlers/chat_render_handler.py` — `end_streaming`'s `render` contract and no-op guard already correct.
- `ui/handlers/gateway_handler.py` — gateway sessions use the ChatHandler delta path, not `AgentRuntimeHandler`'s (grep-verified: no `_do_text_delta` refs).
- `ui/window.py` — no wiring needed; the handler wires `on_turn_start` in `_get_runtime`.
- `agent/tools.py`, `models/` — untouched by the callback change.

---

## 3. Data Flow

**New turn (any kind):** `ChatHandler.on_send` → `AgentRuntimeHandler.send_to_special_agent` (:760) → clears `_ended_sessions`/`_session_completed` + assigns new token (:878-886) → `rt.send_message` → background `_run_loop(sk, text, token)` → registers token in runtime `_turn_tokens[sk]` (:1234) → **`_dispatch(self._on_turn_start, sk, _turn_token=token)`** (GLib.idle_add) → handler `_on_turn_start` → idle_add `_do_turn_start` → guards (token, ended) → `start_streaming` + `_on_agent_start_cb` + drawer-lifecycle "start".

**Tool-only turn continues:** `_run_loop` executes tools → `_dispatch(self._on_tool_call_start, ...)` → `_do_tool_call_start` — NOT suppressed (`sk` no longer in `_ended_sessions`) → tool bubbles emit. Turn ends → `_do_response_complete(sk, "")` (or `_do_error`) → BUG #22 guard reads `get_streaming_text` → `""` → `end_streaming(render=False)` → cleanup, no empty bubble.

**Text turn:** turn-start starts the bubble early (cursor shows during LLM latency — improvement over first-delta start); each SSE chunk → `_on_text_delta` (accumulate + coalesce, AC3 Part A unchanged) → `_do_text_delta_inner` renders; the start-bubble fallback block is skipped (`is_streaming` True). Completion overwrites with authoritative text (unchanged).

**Races:** stale turn-start (older token) → dropped by token check. Terminal-first (cancel/error lands before turn-start, same token) → dropped by ended-guard. Stale terminal from previous turn → dropped by existing token checks in `_do_error`/`_do_response_complete`.

---

## 4. File Change Summary

| File | Change | ~Lines | Risk |
|---|---|---|---|
| `agent/callbacks.py` | +OnTurnStart, docstring fixes | +28/−3 | Low |
| `agent/runtime.py` | ctor + dispatch swap | +10/−8 | Medium (hot path) |
| `ui/handlers/agent_runtime_handler.py` | +2 methods, wiring, 3 render-guards, dead-set deletion, comment truth-fixes | +95/−55 | Medium |
| `tests/test_agent_runtime.py` | 4 rewrites, 6 new, 1 docstring | +150/−60 | Low |
| `docs/ARCHITECTURE.md` | §3.21m.3 + ctor line | +6/−4 | Low |

## 5. Implementation Order

1. `agent/callbacks.py` (Edits A-C) → import-smoke: `python3 -c "from agent.callbacks import OnTurnStart"`.
2. `agent/runtime.py` (Edits A-D) → run `TestStreaming` rewritten test (Edit B in tests first if you want red-first evidence: it fails with 4≠3 deltas + AttributeError on `rt._on_turn_start` patch — capture that output).
3. Handler Edits A-F (turn-start methods, wiring, comments, dead-set deletion in init/inner).
4. Handler Edits G-L (render-guards + remaining dead-set deletions).
5. Tests: all edits in §2.4. **Red-first evidence required** for the 3 render-guard tests (they fail on pre-change code with `render=None ≠ False`) and the 2 new turn-start methods (AttributeError). Capture pasted failing output BEFORE the source edits for at least the render-guards.
6. `docs/ARCHITECTURE.md`.
7. Verification (§6).

**Environment notes (from context.md):** run GTK-touching suites under `PYTHONDONTWRITEBYTECODE=1 xvfb-run -a python3 -m pytest ...`; run `test_agent_runtime.py` PER-CLASS (full-file single-process run OOMs at the pre-existing `TestEndStreaming*` classes — not ours, do not attempt to fix); the `kb_server ... errno 98` log noise in captured output is pre-existing and ignorable.

## 6. Acceptance Criteria

- [ ] The 2 baseline failures are GREEN: `test_tool_only_turn_tool_starts_not_suppressed`, `test_send_to_special_agent_clears_ended_sessions` (replacing `test_started_turn_sessions_clears_ended_flag_on_fresh_tool_start`).
- [ ] `TestLocalAgentDrawerEmissions` class: ALL tests green in one per-class run (was 2F/rest-pass).
- [ ] `TestStreaming` green incl. rewritten `test_text_delta_fires_incrementally` (3 deltas + 1 turn-start).
- [ ] `TestDeltaCoalescing` 7/7 green (empty-delta bypass untouched).
- [ ] 3 render-guard tests green, each with pasted red-first evidence.
- [ ] 2 race-guard tests + GLib-wrapper test green.
- [ ] Grep sweeps: `_started_turn_sessions` → ZERO matches repo-wide; `_dispatch(self._on_text_delta, session_key, ""` → ZERO matches; `on_turn_start=self._on_turn_start` present in `_get_runtime`.
- [ ] pyflakes: 0 undefined-name findings on the 3 touched source files.
- [ ] No review-layer history surgery: spec'd commits only (conventional-commit messages, e.g. `fix(runtime): dedicated on_turn_start callback replaces empty-delta turn-start signal (BUG-21)`).
- [ ] Supervisor unit-close gate: worktree full-suite baseline comparison — failure set shrinks 40 → 38, exactly the 2 closed (Supervisor runs this).

## 7. Edge Cases

| Case | Expected behavior |
|---|---|
| Tool-only turn (no text deltas) | turn-start → bubble + lifecycle; tool_starts fire; `render=False` on all 4 `end_streaming` callers; no empty bubble |
| Text turn | bubble starts at turn-start (cursor during LLM latency); final text byte-identical (AC3 invariants untouched) |
| Cancel/error lands before turn-start (same token) | turn-start dropped by ended-guard; no orphan bubble; flag stays set |
| Stale turn-start (older token) | dropped by token check |
| `on_turn_start=None` (legacy fixtures) | runtime skips dispatch; first real delta's fallback block still starts the bubble (degradation path preserved in `_do_text_delta_inner`) |
| Provider empty-content delta mid-turn | existing empty-bypass routes it uncoalesced; inner's empty-return no-ops (unchanged, tested by `TestDeltaCoalescing`) |
| `chat_box` None at turn-start | bubble not started; first delta retries via fallback; `update_streaming` no-ops without a bubble |
| Duplicate turn-start dispatch | `is_streaming` guard → second call no-ops for bubble/lifecycle |
| `_run_loop` early-exit (no conversation / prompt-build fail / runtime stopped) | `_terminate_turn` fires BEFORE the turn-start dispatch → no bubble, error renders normally |
| Non-streaming session hits error/compaction/usage-warning | `end_streaming` no-ops at its top guard; `render` kwarg moot (traced) |

## 8. ARCHITECTURE.md Updates Required

Listed in §2.5 — §3.21m.3 protocol count/lists, runtime ctor signature at :1797. Same-commit rule per ARCHITECTURE.md §0.

---

## Self-Audit (Rule 9)

1. Every code sample traced against source read this session: `_dispatch` kwarg mechanics (direct `_run_loop` call → token=None → plain call → `lambda sk:` arity correct); `send_to_special_agent` full path with mocked rt (agent registered, project set, `_resolve_agent_model`→None, create-path absorbs kwargs, clear at :878 before `send_message`); `end_streaming` no-op guard; `update_streaming` no-bubble skip; `start_streaming` positional args.
2. Exception types: `_dispatch` wraps callback exceptions (try/except + logger.exception) — a wrong-arity handler lambda degrades to a logged error, not a crash. No new raise sites.
3. Key structures verified: `_turn_tokens: dict[str, object]` (handler :127, runtime :534); `_ended_sessions`/`_session_completed` sets; `_QueueGLib.queue` tuples `(fn, args, kwargs)`.
4. Data flow traced end-to-end (§3) including both race orders.
5. Red-first plan: render-guards fail on current code (`render` absent → `kwargs.get("render") is None`); new methods AttributeError; T1 count mismatch. All failures verified live this session (2F/1P reproduced at `64c73f4`).
6. Both failing tests' mechanisms confirmed non-existent in source (empty-return precedes start-bubble; `_started_turn_sessions` never written).

**Deviations from the original BUG #21/BUG #14 intent, documented:** the flag clear stays send-side only (RACE-FIX v4) rather than moving into the turn-start handler — clearing there would re-open the stale-dispatch race; the `_started_turn_sessions` mechanism is deleted rather than implemented — superseded by the dedicated signal.
