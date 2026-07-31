# SPEC: Stale Delta Race Fix

**Date:** 2026-07-31
**Author:** Supervisor (root cause found by Debugger per `docs/specs/SUPERVISOR-TRUNCATION-FINDINGS.md`)
**Status:** Ready for implementation
**Depends on:** None
**Target branch:** main

> **Architecture compliance:** Fix touches `ui/handlers/agent_runtime_handler.py` only. No layer violations.

---

## 1. Overview

### Problem
Agent messages (Supervisor, Coder, Debugger) truncate to the first word ("Send", "Okay", "C"). The full text is stored correctly in the conversation JSON. No Pango warning appears.

### Root Cause (verified by Debugger)
**Race condition between `_on_text_delta` and `_on_response_complete`.** Both independently call `GLib.idle_add` to queue their work on the GTK main thread. Because they are separate idle callbacks, **completion can execute before a queued delta**:

1. Runtime sends delta "Send..." → `_on_text_delta` queues `_do_text_delta` via `idle_add`
2. Runtime sends response-complete → `_on_response_complete` queues `_do_response_complete` via `idle_add`
3. GTK main loop runs `_do_response_complete` first → renders the full final bubble, ends streaming, sets `_ended_sessions`
4. GTK main loop then runs the stale `_do_text_delta` → `is_streaming()` is False (completion ended it) → starts a **NEW streaming bubble** with just that delta's partial text ("Send")
5. User sees "Send" stuck as a streaming widget; the correct full bubble is buried underneath

### Why existing `_ended_sessions` doesn't fix this
`_ended_sessions` is `.discard()`ed INSIDE `_do_text_delta` (line 1007) when it starts a new streaming bubble. A top-level check would also block new turns (the first delta of turn 2 would see the flag from turn 1's completion).

### Solution
**Generation counter.** Each completion increments a per-session generation number. Deltas capture the generation at dispatch time (`_on_text_delta`). When `_do_text_delta` runs, it compares its captured generation to the current one — if the delta's generation is stale (lower), it's dropped.

- Turn 1: delta captures gen=0, completion increments to gen=1
- Stale delta (gen=0) runs after completion: 0 < 1 → **DROPPED** ✓
- Turn 2: first delta captures gen=1 (current): 1 ≥ 1 → **proceeds** ✓

---

## 2. Changes by File

### 2.1 `ui/handlers/agent_runtime_handler.py`

**Edit 1: Add generation counter to `__init__`**

After `self._ended_sessions: set[str] = set()` (line 106), add:
```python
# RACE-FIX: per-session generation counter. Incremented on each
# _on_response_complete. Deltas capture the generation at dispatch time;
# stale deltas (old generation) are dropped in _do_text_delta.
self._delta_generation: dict[str, int] = {}
```

**Edit 2: Capture generation in `_on_text_delta` and pass to `_do_text_delta`**

Current (line 970):
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
        gen = self._delta_generation.get(session_key, 0)
        if self._GLib is not None:
            self._GLib.idle_add(self._do_text_delta, session_key, text, gen)
        else:
            self._do_text_delta(session_key, text, gen)
```

**Edit 3: Add generation check at top of `_do_text_delta`**

Current signature (line 978):
```python
    def _do_text_delta(self, session_key: str, text: str) -> None:
```

Fixed:
```python
    def _do_text_delta(self, session_key: str, text: str, delta_gen: int = 0) -> None:
```

Add the stale-delta check at the TOP of the method body, after the `if self._crh is None: return` and `if not text: return` guards, BEFORE text accumulation:
```python
        # RACE-FIX: If this delta's generation is stale (completion already
        # incremented the counter), drop it. This prevents stale idle callbacks
        # from starting a new streaming bubble after completion has rendered
        # the final bubble.
        current_gen = self._delta_generation.get(session_key, 0)
        if delta_gen < current_gen:
            logger.debug(
                "_do_text_delta: dropping stale delta (gen %d < current %d) for %s",
                delta_gen, current_gen, session_key,
            )
            return
```

**Edit 4: Increment generation in `_on_response_complete`**

Current (line 1397):
```python
    def _on_response_complete(self, session_key: str, text: str) -> None:
        if self._GLib is not None:
            self._GLib.idle_add(self._do_response_complete, session_key, text)
        else:
            self._do_response_complete(session_key, text)
```

Fixed:
```python
    def _on_response_complete(self, session_key: str, text: str) -> None:
        # RACE-FIX: Increment generation so stale _do_text_delta callbacks
        # (queued before completion but not yet executed) know they're outdated.
        self._delta_generation[session_key] = self._delta_generation.get(session_key, 0) + 1
        if self._GLib is not None:
            self._GLib.idle_add(self._do_response_complete, session_key, text)
        else:
            self._do_response_complete(session_key, text)
```

---

## 3. Acceptance Criteria

- [ ] `_delta_generation: dict[str, int]` added to `__init__`
- [ ] `_on_text_delta` captures and passes generation to `_do_text_delta`
- [ ] `_do_text_delta` signature accepts `delta_gen: int = 0`
- [ ] `_do_text_delta` checks `delta_gen < current_gen` and returns early if stale
- [ ] `_on_response_complete` increments `_delta_generation` before dispatching
- [ ] Agent messages render in full (not truncated to first word)
- [ ] All existing tests pass

---

## 4. Implementation Order

Single phase — one file, four edits, all in the same handler module.
