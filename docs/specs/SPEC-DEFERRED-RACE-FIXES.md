# SPEC: Deferred Race Fixes (3 findings)

**Date:** 2026-07-31
**Status:** Ready for implementation
**Depends on:** The `_ended_sessions` flag fix (already in place)

---

## 1. Overview

Three findings from Debugger's audit of the `_ended_sessions` race fix remain unfixed:

1. **HIGH — Cross-turn stale deltas:** A delta from turn A can survive into turn B after `send_to_special_agent` clears `_ended_sessions`. Needs a per-turn generation token.
2. **MEDIUM — Duplicate completion:** If `_do_response_complete` is called twice, it renders two final bubbles. Needs an idempotency check.
3. **LOW — Early-return gap:** `_do_response_complete` returns before setting `_ended_sessions` when `_crh is None`.

## 2. Root Cause Analysis

### Why the first generation counter failed
The previous generation counter incremented in `_on_response_complete` — which runs as an idle callback on the main thread, BEFORE `_do_response_complete` (also an idle callback). Since `_on_text_delta` (also idle) captures the generation BEFORE `_on_response_complete` runs, all deltas got gen=0, then completion bumped to gen=1, and ALL deltas were dropped (0 < 1).

### The correct approach
**Capture generation in `_on_text_delta` (main thread idle callback). Increment generation at the TOP of `_do_response_complete` and `_do_error` (main thread, synchronously).** This way:
- A delta's generation is captured when `_on_text_delta` runs (main thread)
- Generation is incremented when `_do_response_complete` runs (main thread)
- Both happen on the main thread, so FIFO ordering is deterministic
- A delta that ran BEFORE completion (same generation) is NOT dropped — it's from the same turn
- A delta that runs AFTER completion (old generation) IS dropped — it's stale

The key difference from the failed attempt: **the increment happens on the main thread inside `_do_response_complete`, not in `_on_response_complete` before queueing.**

## 3. Changes by File

### File: `ui/handlers/agent_runtime_handler.py`

#### Edit 1: Add generation counter + completion tracking to `__init__`

After `self._ended_sessions: set[str] = set()`:
```python
# RACE-FIX v3: per-session turn generation. Incremented at the TOP of
# _do_response_complete and _do_error (main thread, synchronously).
# Deltas capture the generation when _on_text_delta runs (main thread).
# A delta with an old generation (from a previous turn) is dropped.
self._turn_generation: dict[str, int] = {}
# RACE-FIX v3: track which (session_key, generation) pairs have already
# been completed. Prevents duplicate completion from rendering twice.
self._completed_turns: set[tuple[str, int]] = set()
```

#### Edit 2: Capture generation in `_on_text_delta`

Current:
```python
    def _on_text_delta(self, session_key: str, text: str) -> None:
        if self._GLib is not None:
            self._GLib.idle_add(self._do_text_delta, session_key, text)
        else:
            self._do_text_delta(session_key, text)
```

Fixed:
```python
    def _on_text_delta(self, session_key: str, text: str) -> None:
        gen = self._turn_generation.get(session_key, 0)
        if self._GLib is not None:
            self._GLib.idle_add(self._do_text_delta, session_key, text, gen)
        else:
            self._do_text_delta(session_key, text, gen)
```

#### Edit 3: Add generation param + stale check in `_do_text_delta`

Current signature: `def _do_text_delta(self, session_key: str, text: str) -> None:`

Fixed signature: `def _do_text_delta(self, session_key: str, text: str, delta_gen: int | None = None) -> None:`

After the existing `_ended_sessions` check, add:
```python
        # RACE-FIX v3: If this delta belongs to a previous turn (generation
        # mismatch), drop it. This handles the cross-turn case where
        # send_to_special_agent cleared _ended_sessions for the new turn
        # but a stale delta from the old turn is still in the idle queue.
        # delta_gen=None means a 2-arg caller (backward-compat tests) —
        # treat as current generation (never stale).
        if delta_gen is not None:
            current_gen = self._turn_generation.get(session_key, 0)
            if delta_gen < current_gen:
                logger.debug(
                    "_do_text_delta: dropping stale delta (gen %d < current %d) for %s",
                    delta_gen, current_gen, session_key,
                )
                return
```

#### Edit 4: Increment generation + idempotency check at TOP of `_do_response_complete`

Current top:
```python
        if self._crh is None:
            return
        self._ended_sessions.add(session_key)
```

Fixed top (move flag BEFORE the _crh check, add generation + idempotency):
```python
        # RACE-FIX v3: Mark session ended + increment generation BEFORE any
        # rendering work or early returns. This ensures:
        # 1. Stale deltas see the flag (regardless of idle ordering)
        # 2. The generation bump happens on the main thread (deterministic)
        # 3. Even if _crh is None, the flag is set (fixes early-return gap)
        self._ended_sessions.add(session_key)
        gen = self._turn_generation.get(session_key, 0)
        self._turn_generation[session_key] = gen + 1
        # Idempotency: if this (session, gen) was already completed, skip.
        # Prevents duplicate completion from rendering two bubbles.
        if (session_key, gen) in self._completed_turns:
            logger.debug("_do_response_complete: duplicate completion for %s gen %d, skipping", session_key, gen)
            return
        self._completed_turns.add((session_key, gen))

        if self._crh is None:
            return
```

#### Edit 5: Increment generation + idempotency at TOP of `_do_error`

Current top:
```python
        # RACE-FIX: Mark session ended IMMEDIATELY
        self._ended_sessions.add(session_key)
        logger.debug(...)
```

Fixed top (add generation + idempotency):
```python
        # RACE-FIX v3: Mark session ended + increment generation (same as _do_response_complete).
        self._ended_sessions.add(session_key)
        gen = self._turn_generation.get(session_key, 0)
        self._turn_generation[session_key] = gen + 1
        if (session_key, gen) in self._completed_turns:
            logger.debug("_do_error: duplicate completion for %s gen %d, skipping", session_key, gen)
            return
        self._completed_turns.add((session_key, gen))

        logger.debug(...)
```

#### Edit 6: Clear generation + completed_turns in `send_to_special_agent`

After `self._ended_sessions.discard(session_key)`:
```python
        # RACE-FIX v3: Clear turn tracking for the new turn.
        self._completed_turns.discard((session_key, self._turn_generation.get(session_key, 0)))
```

## 4. Why This Time Is Different

The previous generation counter incremented in `_on_response_complete` (before
`_do_response_complete` ran), which dropped ALL deltas. This version increments
inside `_do_response_complete` (the main-thread execution), so:

- Deltas that run BEFORE completion have gen=0, completion bumps to gen=1
- Deltas that run AFTER completion have gen=0 < current gen=1 → DROPPED ✓
- Deltas from the SAME turn that run BEFORE completion: gen=0 == current gen=0 → NOT dropped ✓
- New turn: send_to_special_agent doesn't change the generation counter —
  the next completion will increment from 1 to 2. Deltas from the new turn
  capture gen=1 (current). Old deltas from turn A had gen=0 < 1 → DROPPED ✓

## 5. Acceptance Criteria

- [ ] `_turn_generation` dict and `_completed_turns` set added to `__init__`
- [ ] `_on_text_delta` captures and passes generation
- [ ] `_do_text_delta` signature has `delta_gen: int | None = None` + stale check
- [ ] `_do_response_complete` increments generation + idempotency check at TOP (before `_crh` check)
- [ ] `_do_error` increments generation + idempotency check at TOP
- [ ] `send_to_special_agent` clears completed_turns entry
- [ ] All existing tests pass
