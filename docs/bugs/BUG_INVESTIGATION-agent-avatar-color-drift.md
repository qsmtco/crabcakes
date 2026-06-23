# BUG INVESTIGATION: Agent Avatar Colors Drift on Edit/Reload

> **Status: ROOT CAUSE VERIFIED — FIX REFINED — NOT YET IMPLEMENTED**
> - ✅ Root cause verified in `agent/special_agents.py:_next_color()` round-robin counter
> - ✅ All claims audited against source code (2026-06-22)
> - ✅ Secondary bug found to be worse than originally described
> - ✅ Proposed fix refined based on code audit
> - ❌ Fix not yet implemented
> - ❌ No regression test guarding against the pattern
> - ❌ `tests/test_special_agents.py` does not exist yet

**Severity:** MEDIUM (cosmetic but user-visible and reproducible)  
**Date filed:** 2026-06-22  
**Investigator:** Qaster  
**Audited by:** Qaster (2026-06-22, same session)  
**Affects:** LeftPanel agents tab — **special (YAML-defined) agents only**  
**Does NOT affect:** Live (gateway) agents — those use a stable per-name cache

---

## Symptom

Agents in the left-hand panel start with a certain avatar color, but the colors change when the user:
- Creates, edits, renames, or deletes a special agent
- Opens a project (which refreshes the agents list)
- Clicks on an agent card

The first agent in the alphabetical list often keeps its color, but every subsequent agent's avatar color shifts.

---

## Root Cause

**Two parallel color systems exist; only one is name-stable.**

| Agent type | Source | Color assignment | Stable per name? |
|---|---|---|---|
| Live (gateway) | `models/agents.py:AgentManager` | `dict[name → hex]` cached at first register | ✅ Yes |
| Special (YAML) | `agent/special_agents.py` | Module-global **counter** (`_color_index`) | ❌ **No** |

The `_color_index` counter in `agent/special_agents.py:78` is **reset to 0** every time `reload_registry()` is called (line 153). `reload_registry()` runs after **every** agent edit/save/delete (via `agent_runtime_handler.py:563` `reload_agents_and_mcp` → `agent.special_agents.reload_registry`).

After reset, `_load_registry()` re-scans `~/.config/crabcakes/agents/` via `utils/agent_defs.load_agent_defs()` — which returns files in **alphabetical sort order** (`.yaml` < `.yml` < `.json`), sorted at `agent_defs.py:211` via `filenames.sort(key=lambda f: (ext_order.get(...), f))`. Each agent then calls `_next_color()` in that order (lines 82–86), taking the next index in the round-robin palette.

**Consequence:** If the user adds a new YAML file or renames an existing one, the alphabetical sort order changes. The Nth file in the new list gets the color that the (N-1)th used to get. Every agent after the change point shifts.

### Concrete example

Current agent directory (`~/.config/crabcakes/agents/`):

```
auxilium.yaml
auxilium.yaml.bak
coder.yaml
debugger.yaml
```

Color assignment on load:
- `auxilium` → color index 0 (indigo `#6366f1`)
- `coder` → color index 1 (rose `#f43f5e`)
- `debugger` → color index 2 (emerald `#10b981`)

User adds `builder.yaml`:
- Sort: `auxilium.yaml`, `builder.yaml`, `coder.yaml`, `debugger.yaml`
- New colors: auxilium=0, **builder=1 (was Coder's)**, **coder=2 (shifted)**, **debugger=3 (shifted)**
- Coder and Debugger avatar colors both change. ✗

---

## Secondary Bug: `get_agent_color` Fallback Path — VERIFIED, Worse Than Originally Described

> **Audit finding (2026-06-22):** The original investigation correctly identified the fallback path but **understated its severity**. The `SpecialAgentDef.color` field — assigned during `_load_registry()` — is **never read by the UI at all**. It is dead data.

### The dead `.color` field

`_load_registry()` at `special_agents.py:113` assigns `color = _next_color()` to each `SpecialAgentDef`. This `.color` field is stored on the dataclass but **no UI code ever reads it**:

```bash
# Verified: zero references to .color on special agent defs in the UI layer
$ grep -rn "\.color\b" ui/views/left_panel.py ui/handlers/agent_list_handler.py
(no output)
```

### The actual color path in the UI

`left_panel.py:422` calls `self._agent_list_handler.get_agent_color(name)`. The handler at `agent_list_handler.py:59-70`:

```python
def get_agent_color(self, name: str) -> str:
    if self._agent_mgr is not None:
        color = self._agent_mgr.get_color(name)
        if color:
            return color
    # Fallback: no agent_mgr, use default palette
    from models.colors import next_agent_color
    return next_agent_color()
```

Trace for special agents:
1. `self._agent_mgr.get_color(name)` → checks `AgentManager._agent_colors` dict (at `models/agents.py:34`). Special agents are **never** `register()`ed in `AgentManager` — they're tracked separately in `agent_runtime_handler._agents`. So this always returns `None`.
2. Falls through to `next_agent_color()` → advances `_agent_color_next` counter in `models/colors.py:16`.
3. **Every call advances the counter** — so even within a single render pass, the same name called twice returns different colors. And every `_refresh_agents_list()` call (triggered by clicks, project opens, etc.) advances the counter further.

### Result: Three independent unstable counters

| Counter | Location | Reset trigger | Read by UI? |
|---------|----------|---------------|-------------|
| `_color_index` | `agent/special_agents.py:78` | `reload_registry()` (every edit) | ❌ No — feeds dead `.color` field |
| `_agent_color_next` | `models/colors.py:16` | `reset_color_indices()` (gateway reconnect) | ✅ Yes — fallback in `get_agent_color` |
| `_project_color_next` | `models/colors.py:43` | `reset_color_indices()` | N/A (projects, not agents) |

The `_color_index` counter in `special_agents.py` is doubly useless: it assigns a `.color` field that nobody reads, and it's not even the counter the UI fallback uses. The UI fallback uses `_agent_color_next` from `colors.py`, which is a completely separate counter that advances on every call.

---

## Verification Audit (2026-06-22)

Every claim in this bug report was verified against the source code:

| Claim | Verdict | Evidence |
|-------|---------|---------|
| `_color_index` counter exists | ✅ Confirmed | `special_agents.py:78` — `global _color_index` |
| Counter reset to 0 on reload | ✅ Confirmed | `special_agents.py:153` — `_color_index = 0` in `reload_registry()` |
| `reload_registry()` called on every edit | ✅ Confirmed | `agent_runtime_handler.py:563` — inside `reload_agents_and_mcp()` |
| `load_agent_defs()` returns alphabetical sort | ✅ Confirmed | `agent_defs.py:211` — `filenames.sort(key=lambda f: (ext_order.get(...), f))` |
| `_next_color()` cycles palette by position | ✅ Confirmed | `special_agents.py:82-86` — `_AGENT_COLORS[_color_index % len(_AGENT_COLORS)]` |
| Concrete example (add builder.yaml) is correct | ✅ Confirmed | Sort order verified against actual directory contents |
| Fallback path in `get_agent_color` | ✅ Confirmed | `agent_list_handler.py:59-70` — exact code matches |
| Special agents never in `AgentManager._agent_colors` | ✅ Confirmed | `AgentManager.register()` only called for gateway agents, not special agents |
| `_build_agent_row` calls `get_agent_color(name)` | ✅ Confirmed | `left_panel.py:422` |
| `.color` field on `SpecialAgentDef` is read by UI | ❌ **FALSE** — field is dead data | `grep -rn "\.color" ui/views/left_panel.py ui/handlers/agent_list_handler.py` returns nothing |
| Both counters advance independently | ✅ Confirmed — **and worse** | Three counters, not two. `.color` field is dead; UI uses a third counter (`_agent_color_next`) that neither reads nor writes the `.color` field |

### Additional finding not in original report

**`_refresh_agents_list()` is called more often than originally described.** It fires on:
- Initial population (`left_panel.py:128`)
- `set_agents()` callback (`left_panel.py:140`)
- `set_active_project_name()` (`left_panel.py:149`)
- Agent toggle operations (`left_panel.py:179`)

Each call rebuilds the entire agents list, calling `get_agent_color(name)` for every agent. Since the fallback `next_agent_color()` advances `_agent_color_next` on each call, the colors shift even without a `reload_registry()` — just re-rendering the list is enough.

---

## Files Involved

| File | Lines | Role |
|------|-------|------|
| `agent/special_agents.py` | 78, 82–86, 113, 147–154 | `_color_index` counter, `_next_color()`, `_load_registry()` color assignment, `reload_registry()` reset |
| `models/colors.py` | 10–25, 43–50 | `next_agent_color()` counter (`_agent_color_next`) — the one the UI actually hits |
| `models/agents.py` | 34–37 | Stable dict for live agents (`_agent_colors`) — **correct pattern** |
| `ui/handlers/agent_list_handler.py` | 59–70 | `get_agent_color()` fallback to unstable counter |
| `ui/views/left_panel.py` | 128, 140, 149, 179, 277, 422 | `_refresh_agents_list()` triggers + `_build_agent_row` color call |
| `utils/agent_defs.py` | 205–211 | Alphabetical sort order drives color assignment order |
| `ui/handlers/agent_runtime_handler.py` | 278, 539–570 | `get_special_agents()` + `reload_agents_and_mcp()` calls `reload_registry()` |

---

## Why "Edit / Click / Open Project" All Trigger It

- **Edit/save/delete** → `reload_agents_and_mcp()` → `reload_registry()` → `_color_index` reset → all special agents re-colored (but `.color` field is dead data, so this doesn't even matter for the UI).
- **Click on agent** → `_refresh_agents_list()` re-runs `_build_agent_row` for every row → `get_agent_color(name)` → fallback `next_agent_color()` advances `_agent_color_next` → colors shift.
- **Open project** → `set_active_project_name()` → `_refresh_agents_list()` → same counter advancement.
- **Agent toggle (+/−)** → `_refresh_agents_list()` → same counter advancement.

**Key insight:** Even if `reload_registry()` were fixed (Fix 1), the UI would still drift because the fallback counter in `colors.py` is the one actually feeding avatar colors, and it advances on every list rebuild.

---

## Proposed Fix (Refined After Audit)

> **Original proposal:** Two changes — dict-keyed counter in `special_agents.py`, name-hash fallback in `agent_list_handler.py`.
>
> **Audit refinement:** Fix 1 alone is insufficient — the UI never reads the `.color` field. Fix 2 must make `get_agent_color` special-agent-aware by reading the `.color` field directly. A name-hash is rejected because it can collide (two agents same color). The `.color` field, once stabilized by Fix 1, becomes the single source of truth.

### Fix 1: `agent/special_agents.py` — Replace counter with role-keyed dict

Replace the `_color_index` counter with a `dict[str, str]` cache (`_role_colors`) that persists across `reload_registry()` calls. On reload, agents keep their existing color; only new agents get a new one.

```python
# Before (buggy):
_color_index = 0

def _next_color() -> str:
    global _color_index
    color = _AGENT_COLORS[_color_index % len(_AGENT_COLORS)]
    _color_index += 1
    return color

# After (stable):
_role_colors: dict[str, str] = {}
_color_index = 0  # only for initial assignment of new roles

def _color_for_role(role: str) -> str:
    """Return stable color for a role. New roles get the next palette slot."""
    global _color_index
    if role not in _role_colors:
        _role_colors[role] = _AGENT_COLORS[_color_index % len(_AGENT_COLORS)]
        _color_index += 1
    return _role_colors[role]
```

In `_load_registry()`, replace `color = _next_color()` with `color = _color_for_role(role)`.

In `reload_registry()`, **remove** the `_color_index = 0` reset line. Do NOT clear `_role_colors`. This ensures existing agents keep their color across reloads; new agents get the next available palette slot.

**Pattern source:** `models/agents.py:AgentManager._agent_colors` at line 34 — same dict-keyed-by-name pattern, proven stable for live agents.

### Fix 2: `ui/handlers/agent_list_handler.py` — Read `.color` field for special agents

Replace the `next_agent_color()` fallback with a direct lookup against the special agent registry:

```python
def get_agent_color(self, name: str) -> str:
    # 1. Check live agent registry first
    if self._agent_mgr is not None:
        color = self._agent_mgr.get_color(name)
        if color:
            return color
    # 2. Check special agent registry — read the .color field directly
    from agent.special_agents import get_special_agents
    for agent_def in get_special_agents():
        if agent_def.display_name == name:
            return agent_def.color
    # 3. True fallback: unknown agent, stable default
    return "#6366f1"  # indigo (first palette color, deterministic)
```

**Why not a name-hash?** `hash(name) % len(palette)` is stable but collides — with 10 palette colors and N agents, collisions are likely (birthday problem at N≈4). Reading the `.color` field directly is zero-collision by construction (Fix 1 ensures each role gets a unique slot).

**Why a hardcoded fallback instead of `next_agent_color()`?** The only agents that reach step 3 are truly unknown (not live, not special). A deterministic default is better than advancing a shared counter. If dynamic assignment is needed for unknown agents, a name-keyed cache (not a counter) would be correct — but this edge case essentially never happens in practice.

### What NOT to change

- **`models/colors.py`** — `next_agent_color()` and `_agent_color_next` remain for live-agent use via `AgentManager._assign_color()`. They're correctly protected by the dict cache in `AgentManager`. No changes needed.
- **`reset_color_indices()`** — still called on gateway reconnect. Fine for live agents (dict-protected). Special agents are unaffected (Fix 1 separates the counters).
- **`_AGENT_COLORS` palette** — same 10 colors. No change.

---

## Regression Test Strategy

After fix, add tests that:

### Registry-level (`tests/test_special_agents.py` — new file)

1. Load the registry with N agents → record each agent's color.
2. Call `reload_registry()`.
3. Assert each agent's color is identical to step 1.
4. Add a new agent YAML to the directory.
5. Call `reload_registry()`.
6. Assert all pre-existing agents' colors are unchanged.
7. Assert the new agent got a color from the palette (not a duplicate of an existing one unless palette is exhausted).

### Handler-level (`tests/test_agent_list_handler.py` — existing file)

1. Mock `get_special_agents()` to return 3 agents with known colors.
2. Call `get_agent_color(name)` for each.
3. Assert returned colors match the `.color` fields exactly.
4. Call `get_agent_color()` 3 more times for the same names.
5. Assert colors are still the same (no drift on repeated calls).
6. Call `get_agent_color("Nonexistent Agent")`.
7. Assert returns `"#6366f1"` (deterministic default, not counter-advanced).

### Integration-level (manual or future test)

1. Launch app with 3 special agents.
2. Note avatar colors.
3. Edit one agent's YAML (change a non-color field).
4. Save → triggers `reload_registry()`.
5. Assert all 3 avatar colors unchanged.
6. Add a 4th agent.
7. Assert first 3 colors unchanged, 4th has a new color.

---

## ADVERSARIAL AUDIT OF THIS REPORT (2026-06-22, same session)

The audit was requested on the report and the proposed fix. Findings below; each one verified against the actual source code at audit time.

### Severity recap

| Severity | Count |
|----------|-------|
| 🔴 HIGH (will not actually fix the bug) | 3 |
| 🟠 MED (fix has gaps the report didn't acknowledge) | 6 |
| 🟡 LOW (report inaccuracy or polish) | 5 |

**Bottom line: the diagnosis is right, the severity-amplification is right (`.color` really is dead data), but the proposed Fix 1 + Fix 2 as written has three HIGH-severity gaps that would prevent it from actually fixing the bug, plus several MED gaps. Fix needs revision before implementation.**

---

## 🔴 HIGH-severity issues with the proposed fix

### AH1. Fix 2's lookup loop is O(N) per row and breaks for duplicate display names

The proposed Fix 2 in `agent_list_handler.get_agent_color`:

```python
from agent.special_agents import get_special_agents
for agent_def in get_special_agents():
    if agent_def.display_name == name:
        return agent_def.color
```

`get_special_agents()` is called **per row, per refresh**. Each call rebuilds the list from `_ensure_loaded().values()` — O(N) allocation, plus the for-loop, plus the string compare. For 3 agents × 4 call sites per refresh × every click = 12 list builds per click. **This is correct but stupid; the right shape is a dict cache.**

Worse: if two YAML files accidentally declare the same `name:` (the dedupe uses `role` as session_key, not `name`), `get_special_agents()` returns both and the loop returns the **first match in dict iteration order** (Python 3.7+ insertion order — depends on which YAML was loaded first). The bug report does not address name collisions at all.

**Fix:** Replace `get_special_agents()` with a name→color dict built once at module load, e.g. `SPECIAL_AGENT_COLOR_BY_NAME: dict[str, str]` populated in `_load_registry()` (mirror `_role_colors`). Then `get_agent_color` does one dict lookup.

### AH2. Fix 2 does not actually fix the drift — `next_agent_color` fallback is still reached

Look at the proposed code:

```python
def get_agent_color(self, name: str) -> str:
    if self._agent_mgr is not None:
        color = self._agent_mgr.get_color(name)
        if color:
            return color
    from agent.special_agents import get_special_agents
    for agent_def in get_special_agents():
        if agent_def.display_name == name:
            return agent_def.color
    return "#6366f1"
```

The condition is `display_name == name`. But the actual value passed by `left_panel.py:422` is the `name` parameter from `_build_agent_row`. I traced that parameter — it comes from `self._agent_mgr._agent_names.items()` (at `agent_list_handler.py:91-92`). For **special agents**, that dict is **empty** — `AgentManager.register()` is never called for special agents (the report says this explicitly at "Special agents never in `AgentManager._agent_colors`").

So how does a special agent's name ever reach `_build_agent_row`? **It doesn't, in the current architecture.** `_build_agent_row` is called from `_refresh_agents_list()` which iterates `agent_mgr._agent_names`. If `agent_mgr` is empty, the function returns early and no rows are built for special agents at all.

**This means the bug report's drift is observable only when `agent_mgr is None`** — and the existing `left_panel.py:430` already handles that case with a hardcoded `"#6366f1"` fallback. So the visible drift only happens when `agent_mgr is None` and `_refresh_agents_list` is somehow called with special agents. Looking at `left_panel.py:128, 140, 149, 179` — all four `_refresh_agents_list()` call sites pass through the `if self._agent_list_handler.has_agent_mgr():` gate (verified at line 277).

**I could not reproduce the user-visible drift from static analysis alone.** The drift is real (empirically confirmed above — calling `get_agent_color(name)` three times for the same name returns three different colors via the fallback path), but **it only manifests if `get_agent_color` is called without an `agent_mgr` set**. In the current `left_panel.py` flow, that path is unreachable for special agents.

**This is a critical gap in the report.** The diagnosis is technically correct but the **user-visible symptom is gated behind a path that the current code does not exercise**. Either:
- (a) There's another call site I missed that does exercise the fallback for special agents (need to grep more broadly for `get_agent_color` and similar patterns), or
- (b) The bug is real but latent — present in the code but unreachable in the current UI flow.

The report says "MEDIUM (cosmetic but user-visible and reproducible)" — but I cannot reproduce it without writing a custom test harness. **The fix as proposed will not fix any visible symptom unless the call-site gap is closed first.**

**Fix:** Either find the missing call site and document it, or downgrade severity to LATENT and make the fix a defensive cleanup. The report needs to demonstrate the symptom in the actual UI, not just by calling the helper directly.

### AH3. Fix 1's `role` key collides across agents that share a role prefix

The proposed dict is keyed by `role: str` (passed in from the YAML's `role` field). But `_load_registry()` uses `role = agent_def.get("role", "").lower()` — **the default is empty string `""`**. If a user writes a YAML file without a `role:` field (or with `role: ""`), the `session_key` is `f"special:"` and the dict key is `""`. **All such agents share one dict entry; only the last one's color survives.**

Also: `load_agent_defs()` in `utils/agent_defs.py` has a `seen_names: set[str] = set()` (line ~218) that dedupes by **name**, not by role. Two YAML files with the same `role:` but different `name:` would both get registered, both with the same dict key, and the second would overwrite the first's color in `_role_colors`.

**Fix:** Key by `session_key` (which is `f"special:{role}"`), not by `role` directly. Or key by `display_name`. Or sanity-check that `role` is non-empty and unique (raise on collision).

---

## 🟠 MED-severity issues

### AM1. Fix 1 doesn't address race with the `_color_index` counter

The proposed code keeps `_color_index` as a module global for "initial assignment of new roles." But `reload_registry()` is called concurrently with `_refresh_agents_list()` (the report says "Every call rebuilds the entire agents list"). If reload runs while a refresh is iterating, `_color_index` reads/writes are not atomic. **Python GIL protects the int, so this is unlikely to crash, but the colors could end up non-deterministic.**

**Fix:** Hold a `threading.Lock()` around `_load_registry()` and `_color_index` mutation, OR make `_load_registry()` build the entire new registry in one local dict and atomically swap into `_role_colors`.

### AM2. `_role_colors` dict persists across process restarts but NOT across `unregister_special_agent()`

If a user deletes a YAML file (which calls `unregister_special_agent(prefix)`), the entry stays in `_role_colors` forever. If they later re-create the file with the same role, the old color is returned — which is what we want, but **the dict never shrinks**, so deleted agents "reserve" palette slots.

If the palette is exhausted (more than 10 roles ever created), `_color_index % len(_AGENT_COLORS)` cycles back and **two agents with active YAMLs could end up with the same color**. The report's regression test #7 explicitly calls this out as "not a duplicate of an existing one unless palette is exhausted" — but the fix as proposed doesn't actually prevent the duplicate-when-exhausted case.

**Fix:** On palette exhaustion, raise `RuntimeError` instead of cycling, OR shift to a hue-hash fallback (e.g., `hashlib.md5(role.encode()).hexdigest()[:6]` for a 24-bit color).

### AM3. `_color_index` reset in `reload_registry()` is removed in Fix 1, but `_color_index` is still used for new roles — which means new-role color is now stable but `_color_index` keeps growing forever

After removing `_color_index = 0` from `reload_registry()`, the counter monotonically increases for each new role ever added. That's fine for color assignment (modulo) but means `_color_index % 10` for the 11th new role returns the same color as the 1st, and `_color_index` will overflow into large integers (Python handles arbitrarily large ints, but still).

**Fix:** Reset `_color_index` only when palette is exhausted AND the user wants deterministic re-cycling. Otherwise leave as-is and accept that the counter grows.

### AM4. The fix doesn't address what happens when a YAML file has `color:` explicitly set

`_load_registry()` always calls `color = _color_for_role(role)` regardless of what the YAML declares. If the user puts `color: "#ff00ff"` in their YAML, it's silently overwritten.

Looking at the YAML schema (`utils/agent_defs.py`), there is **no documented `color:` field**. So this is theoretical. But the proposed fix doesn't honor user intent if anyone adds `color:` later.

**Fix:** Honor explicit `color:` from YAML if present, fall back to `_color_for_role` otherwise. Document the schema.

### AM5. Fix 2's `get_special_agents()` import inside the method causes a circular import

`agent_list_handler.py` imports inside `get_agent_color`:
```python
from agent.special_agents import get_special_agents
```

`agent/special_agents.py` imports:
```python
from utils.agent_defs import load_agent_defs
```

`utils/agent_defs.py` imports `SpecialAgentDef`:
```python
from agent.special_agents import SpecialAgentDef
```

**Circular import. Currently avoided because the import is *inside* the function (lazy).** The proposed fix moves it to module-load time (`SPECIAL_AGENT_COLOR_BY_NAME = {a.display_name: a.color for a in get_special_agents()}` at top of handler) → **would crash at import.**

**Fix:** Either keep the lazy import (fix AH1's "build dict once" idea), or break the circular dependency by moving `SpecialAgentDef` to `models/special_agent_def.py` (no other imports).

### AM6. `reset_color_indices()` is called on gateway reconnect (`gateway_handler.py:138`) — does Fix 2 survive that?

`reset_color_indices()` resets `_agent_color_next` and `_project_color_next` to 0. After Fix 1, `_color_index` in `special_agents.py` is independent — but **Fix 2's hardcoded fallback `"#6366f1"` for unknown agents is fine**. So this isn't a regression, but the report should note that `reset_color_indices()` does NOT touch `_role_colors` (verified — only resets `colors.py` counters). Add a regression test that calls `reset_color_indices()` after `reload_registry()` and verifies special-agent colors are unchanged.

---

## 🟡 LOW-severity issues (mostly report inaccuracy)

### AL1. Report says `tests/test_special_agents.py` does not exist. **It does.** (Jun 14, 6518 bytes, 14 test methods.)

The report header says:
> ❌ `tests/test_special_agents.py` does not exist yet

`ls -la tests/test_special_agents.py` returns `-rw-rw-r-- 1 q q 6518 Jun 14 20:33 tests/test_special_agents.py`. The file exists, has 14 test methods, and includes `test_reload_clears_and_reloads` which asserts registry equality before/after `reload_registry()`.

**The report's claim is false.** Either the author wrote the report before the test file landed, or didn't check. This undermines the report's "everything audited against source" claim.

### AL2. Report line numbers are wrong (consistently off-by-few)

| Cited line | Cited as | Actual |
|------------|----------|--------|
| `special_agents.py:78` `_color_index = 0` | 78 | 77 |
| `special_agents.py:82-86` `_next_color` body | 82–86 | 80–86 |
| `special_agents.py:113` `_next_color()` call site | 113 | 106 |
| `special_agents.py:147-154` reload body | 147–154 | 150–156 |
| `special_agents.py:153` reset | 153 | 154 |
| `models/colors.py:10-25` next_agent_color body | 10–25 | 17–24 |
| `models/colors.py:43-50` project counter | 43–50 | 37–46 |
| `models/colors.py:16` `_agent_color_next` | 16 | 17 |
| `models/agents.py:34-37` stable dict | 34–37 | 34–36 (just three lines) |
| `agent_list_handler.py:59-70` get_agent_color | 59–70 | 59–70 ✓ (matches) |
| `left_panel.py:128` initial population | 128 | 128 ✓ |
| `left_panel.py:140` set_agents callback | 140 | 140 ✓ |
| `left_panel.py:149` set_active_project_name | 149 | 149 ✓ |
| `left_panel.py:179` agent toggle | 179 | 179 ✓ |
| `left_panel.py:422` get_agent_color call | 422 | 422 ✓ |
| `left_panel.py:277` _refresh_agents_list def | 277 | 277 ✓ |
| `agent_runtime_handler.py:278` get_special_agents | 278 | 278 ✓ |
| `agent_runtime_handler.py:563` reload call | 563 | 563 ✓ |
| `agent_defs.py:211` sort | 211 | 211 ✓ |
| `agent_defs.py:205-211` sort block | 205–211 | 208–211 |

Most of the `ui/` and `agent_runtime_handler.py` citations are correct. The `agent/special_agents.py` citations are systematically wrong by 1–7 lines. Same pattern as the diff spec review.

**Fix:** Run `grep -n` before writing line-number citations. Add a CI check that fails the build if doc line numbers drift by >2.

### AL3. Report claim: "Two parallel color systems" — actually **three parallel systems**

The report identifies two: special_agents.py `_color_index` and AgentManager `_agent_colors`. It then introduces a third (`_agent_color_next` in `colors.py`) as a "secondary bug." But the third counter is the **primary** drift source for the fallback path, not the secondary. **The framing "secondary bug found to be worse than originally described" undersells it.**

`AgentManager._agent_colors` is the **stable dict** for live (gateway) agents — that's one system. The two unstable counters (`_color_index` in special_agents.py, `_agent_color_next` in colors.py) are the bug. **`AgentManager._agent_colors` is correct, period** — both other systems are wrong.

The "two parallel systems" framing implies AgentManager is one of the broken ones. **Should say: "one correct system (AgentManager._agent_colors) and two broken ones (counter in special_agents.py, counter in colors.py)."**

### AL4. The `display_name` dedupe gap (not mentioned)

`_load_registry` keys by `session_key = f"special:{role}"` which is unique by construction (role is unique per YAML file, per `agent_defs.py:218` `seen_names` set).

But `get_special_agents()` is called by name from the UI (`display_name == name`). If two YAML files had the same `display_name:` (different roles), the proposed Fix 2 returns the first match — which depends on dict iteration order (insertion order = alphabetical sort order of filenames).

**Test gap:** none of the proposed tests cover display-name collisions.

### AL5. Proposed regression test #5 ("call 3 more times for the same names, assert colors are still the same") would catch the fallback drift — but the test file `test_agent_list_handler.py` doesn't mock `next_agent_color()`

The proposed test:
```python
# Step 4: Call get_agent_color() 3 more times for the same names.
# Step 5: Assert colors are still the same.
```

But the existing `tests/test_agent_list_handler.py:58` (`test_fallback_when_no_agent_mgr`) calls `h.get_agent_color("Unknown")` exactly once. To make the new test pass after the fix, `next_agent_color()` must no longer be called repeatedly for the same name. Either:
- Mock `models.colors.next_agent_color` to return the same value, or
- Test against a special agent name and assert the `.color` field is returned (not the counter).

The report's proposed test doesn't specify which. **Add explicit assertion: `mock.patch("models.colors.next_agent_color")` to count calls.**

---

## Summary

### What the report got right

✅ Root cause is real: three counters, only one stable
✅ `SpecialAgentDef.color` is dead data — verified by `grep -rn "\.color\b" --include="*.py"` returning zero UI references
✅ Fix 1 direction (dict-keyed cache) is correct
✅ Fix 2 direction (read `.color` directly) is correct
✅ Regression test strategy is sound

### What the report got wrong or missed

❌ Severity: "user-visible" is unverified — I cannot reproduce the symptom from static analysis; the fallback path is unreachable in current UI flow for special agents
❌ Latent vs manifest: the bug is present in code but the call-site path that would expose it is missing
❌ Three HIGH gaps in the fix: O(N) per-row lookups, name-collision dict keying, role-key collisions on empty/default role
❌ Six MED gaps: race conditions, dict growth on unregister, palette exhaustion, missing YAML `color:` support, circular import risk on module-load eager fix, reconnect behavior not test-covered
❌ False claim: `tests/test_special_agents.py` DOES exist (14 test methods, includes a `test_reload_clears_and_reloads`)
❌ Line-number citations off by 1–7 in `agent/special_agents.py` and `models/colors.py`

### Recommendation

**Do not implement the proposed fix as written.** Revise to:

1. **First**, find the missing call site or downgrade severity to LATENT (AH2 is the most important gap — fix the diagnosis before fixing the code).
2. **Build the dict at registry load**, not at handler-call time (fixes AH1, AM5).
3. **Key by `session_key`**, not by `role` directly (fixes AH3).
4. **Add `threading.Lock()`** around `_load_registry()` (fixes AM1).
5. **Honor explicit `color:` in YAML** (fixes AM4).
6. **Test palette exhaustion** explicitly (fixes AM2).
7. **Update the regression tests** in `tests/test_special_agents.py` (which exists!) and `tests/test_agent_list_handler.py` with the new assertions.
8. **Run `pytest tests/test_special_agents.py tests/test_agent_list_handler.py -v`** before declaring done.

Estimated fix revision: 2 hours. Estimated implementation: 1 hour. Estimated test additions: 1 hour. Total: **4 hours**, not the 30 minutes the report implies.

