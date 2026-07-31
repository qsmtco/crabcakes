"""Pure-Python probe: verify stale-delta race fix in AgentRuntimeHandler.

Instantiates the real handler with GLib=None (synchronous path) and exercises
the four edits without any GTK dependency. TEMPORARY — deleted after verification.
"""
import sys
sys.path.insert(0, "/home/q/projects/crabcakes")

from ui.handlers.agent_runtime_handler import AgentRuntimeHandler


class FakeMC:
    def get_chat_box_for_session(self, *a, **k):
        return None  # not needed for these paths


class FakeCRH:
    def __init__(self):
        self.streaming = set()
        self.updated = []

    def is_streaming(self, sk):
        return sk in self.streaming

    def start_streaming(self, sk, box, name):
        self.streaming.add(sk)

    def update_streaming(self, sk, text):
        self.updated.append((sk, text))


results = []

# --- Build handler with GLib=None (synchronous dispatch) ---
h = AgentRuntimeHandler(FakeMC(), FakeCRH(), GLib_module=None)

# Edit 1: _delta_generation dict exists
assert isinstance(h._delta_generation, dict), "Edit 1: _delta_generation not a dict"
assert h._delta_generation == {}, "Edit 1: _delta_generation should start empty"
results.append("Edit 1 OK: _delta_generation dict initialized empty")

# --- Edit 4: gen must increment ---
h._on_response_complete("sk1", "final text")
assert h._delta_generation.get("sk1") == 1, f"Edit 4: gen={h._delta_generation.get('sk1')}, expected 1"
results.append("Edit 4 OK: _on_response_complete incremented gen to 1")

# --- Edit 3: stale delta (queued before completion, gen 0) dropped ---
h._on_response_complete("sk2", "final2")  # gen["sk2"] = 1
h._do_text_delta("sk2", "stale-partial", delta_gen=0)
assert "sk2" not in h._streaming_text, f"Edit 3: stale delta accumulated text: {h._streaming_text}"
assert "sk2" not in h._crh.streaming, "Edit 3: stale delta started a streaming bubble"
results.append("Edit 3 OK: stale delta (gen 0 < current 1) dropped, no accumulation, no bubble")

# --- Edit 2/3: fresh deltas still accumulate (happy path) ---
h._on_text_delta("sk3", "hello ")
h._on_text_delta("sk3", "world")
assert h._streaming_text.get("sk3") == "hello world", f"happy path broken: {h._streaming_text}"
assert "sk3" in h._crh.streaming, "happy path: streaming should have started"
assert ("sk3", "hello world") in h._crh.updated, f"update_streaming not called: {h._crh.updated}"
results.append("Edit 2/3 OK: fresh deltas accumulate and stream normally")

# --- Edit 3 backward compat: 2-arg _do_text_delta call (default delta_gen=0) ---
h._do_text_delta("sk4", "compat")
assert h._streaming_text.get("sk4") == "compat", f"backward-compat broken: {h._streaming_text}"
results.append("Edit 3 OK: 2-arg _do_text_delta works (delta_gen default 0)")

# --- Full race scenario end-to-end (the user-visible bug) ---
h._on_text_delta("sk5", "Hello ")          # captured gen 0
h._on_response_complete("sk5", "Hello world")  # gen 0 -> 1
h._do_text_delta("sk5", "Hello ", delta_gen=0)  # stale idle callback runs late
assert "sk5" not in h._streaming_text, "RACE: stale delta re-accumulated after completion"
assert "sk5" not in h._crh.streaming, "RACE: stale delta restarted streaming"
results.append("RACE SCENARIO OK: stale delta after completion does not restart bubble")

# --- Fresh delta in a NEW turn after completion still works ---
h._on_text_delta("sk5", "New turn")
assert h._streaming_text.get("sk5") == "New turn", f"new turn broken: {h._streaming_text}"
assert "sk5" in h._crh.streaming, "new turn: streaming should have restarted"
results.append("NEW TURN OK: delta with current gen still streams after completion")

print("\n".join(results))
print(f"\nALL {len(results)} CHECKS PASSED")
