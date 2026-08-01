# Delta Generation Debug Findings

## Root cause: a partial stream can become the “streaming” path

The generation counter does drop all queued deltas that were captured before completion, but that is not by itself the truncation mechanism. The visible `Type` result occurs when the first `_do_text_delta` happens to run before the completion callback, while later deltas run after completion.

Exact main-thread ordering for the observed symptom:

1. Runtime `_dispatch(_on_text_delta, "Type")` queues an idle wrapper **#1**.
2. Runtime `_dispatch(_on_text_delta, " test…")` queues wrapper **#2**.
3. Runtime `_dispatch(_on_response_complete, full_text)` queues wrapper **#3**.
4. Wrapper **#1** runs `_on_text_delta`. It captures generation `0` and queues `_do_text_delta("Type", 0)` as **#4**.
5. **#4 runs before #3**. `_do_text_delta` sees `0 == current_gen(0)`, appends `Type`, and starts the ChatRenderHandler streaming bubble. The bubble's `plain_text` is now `Type`.
6. Wrapper **#2** runs and queues `_do_text_delta(" test…", 0)` as **#5** (or #5 may already be queued; the relevant fact is it executes after completion).
7. Wrapper **#3** runs `_on_response_complete`, increments generation to `1`, and queues `_do_response_complete` as **#6**.
8. **#5** runs: `0 < current_gen(1)`, so it is dropped.
9. **#6** runs: `was_streaming = True`, because #4 already created the bubble. It calls `end_streaming(render=True)`. That finalizer renders `sb.plain_text`, which is only `Type`.

The full `text` argument is deliberately ignored in this branch: `_do_response_complete` only uses `text` for the `not was_streaming` fallback. Therefore the final bubble is truncated to the first delta that won the scheduling race.

## Why the “all dropped => full fallback” reasoning is insufficient

If completion (#3) runs before every `_do_text_delta`, then `was_streaming` is false and the `not was_streaming and text` branch at `agent_runtime_handler.py:1507-1527` does render the full response. That ordering is correct.

The failure is the mixed ordering above: one delta runs before completion and starts streaming; the generation increment then drops the rest. Once `was_streaming` is true, the full-text fallback is not entered. This explains both the first-word truncation and why it can appear timing-dependent.

## Relevant code evidence

- `ui/handlers/agent_runtime_handler.py:978-980`: captures generation in `_on_text_delta`, then adds a second idle callback.
- `ui/handlers/agent_runtime_handler.py:1007-1013`: drops captured generation `0` after completion has advanced current generation to `1`; accumulation occurs only after this check.
- `ui/handlers/agent_runtime_handler.py:1015-1018`: the first accepted delta starts the streaming bubble.
- `ui/handlers/agent_runtime_handler.py:1417-1421`: completion advances generation before queuing `_do_response_complete`.
- `ui/handlers/agent_runtime_handler.py:1451`: completion samples `is_streaming()` after the race.
- `ui/handlers/agent_runtime_handler.py:1486-1490`: streaming branch finalizes the ChatRenderHandler buffer and chooses render based on its accumulated text.
- `ui/handlers/agent_runtime_handler.py:1507-1527`: full `text` fallback is conditional on `not was_streaming`.
- `ui/handlers/chat_render_handler.py:461-462`: accepted updates replace `sb.plain_text`; after only #4, it is `Type`.
- `ui/handlers/chat_render_handler.py:570-605`: `end_streaming` renders `sb.plain_text`, not the completion callback's `text` argument.
- `agent/runtime.py:419-425`: each callback is itself wrapped in `GLib.idle_add`, creating the two-stage idle queue.

## Conclusion

The generation guard is placed at the wrong abstraction boundary for this two-stage dispatch. Completion can advance the generation between the first-stage callback and its second-stage delta callback. A single early delta is enough to set `was_streaming=True`; all subsequent captured-generation deltas are then discarded, and completion finalizes that partial buffer instead of rendering the authoritative full response.
