# SPEC: Tools Section Redesign — Agent Builder Dialog

**Date:** 2026-05-27
**Author:** Qaster
**Status:** Draft — for implementation
**Implements:** Captain's request for better tools UI
**Depends on:** None
**Target branch:** main

> Complies with ARCHITECTURE.md §9: all CSS in `ui/styles.py`, views use `add_css_class()` only.
> Pure view change — no handler, model, or persistence changes.

---

## 1. Overview

### Problem
The Tools section in the Edit Agent dialog has three UX issues:

1. **Description spam** — Each checkbox label is `"{name} — {description[:60]}"`. The descriptions from `get_all_tools()` contain multi-line "WHEN TO USE:" developer docs that truncate poorly, leaving noise.
2. **Tiny scroll box for 8 items** — A `ScrolledWindow` capped at 160px height holds only 8 checkboxes. Overkill scrolling for what could fit on screen.
3. **No visual grouping** — Tools have natural categories (Read, Write, Execute, Web) but appear as a flat list with no structure, making it hard to scan.

### Solution
Replace the flat `ListBox` + `ScrolledWindow` with a **categorized `FlowBox` grid**:

- Tools grouped into 4 categories with section headers
- 2 columns of checkboxes per category (no scrolling needed for 8 items)
- Checkbox labels show **tool name only** — full description in tooltip on hover
- **Count badge** ("4/8 tools selected") next to the "Tools" section label
- Preset buttons remain, moved into the header row with the count badge

### Scope

| In scope | Out of scope |
|----------|-------------|
| `_build_tools_section()` rewrite | Handler/model/persistence layer |
| New CSS classes in `ui/styles.py` | Changing tool definitions or descriptions |
| `_apply_preset()` update (category-aware) | Prompt list or MCP section |
| Count badge label | New presets or preset customization |
| Tooltip wiring | Accessibility (separate future work) |

---

## 2. Changes by File

### 2.1 `ui/views/agent_builder.py`

**What changes:** Replace `_build_tools_section()` body. Add `_build_tool_category()`. Add `_update_tool_count()`. Add `_tool_count_label`. Update `_apply_preset()` to call `_update_tool_count()`. Update `_fill_form()` to call `_update_tool_count()` after setting checks.

**No method signatures change.** Public API (`get_values()`, `show()`, `close()`, `show_errors()`) unchanged.

#### New instance variables

```python
# In __init__, alongside existing self._tool_checks:
self._tool_count_label: Gtk.Label = None  # "4/8 tools selected"
```

#### `_build_tools_section()` — full replacement

```python
def _build_tools_section(self) -> Gtk.Box:
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

    # ── Header row: presets left, count badge right ──
    header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

    presets = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    presets.add_css_class("agent-builder-presets")

    full_btn = Gtk.Button(label="Full Access")
    full_btn.add_css_class("flat")
    full_btn.connect("clicked", lambda *_: self._apply_preset("full"))

    readonly_btn = Gtk.Button(label="Read Only")
    readonly_btn.add_css_class("flat")
    readonly_btn.connect("clicked", lambda *_: self._apply_preset("readonly"))

    custom_btn = Gtk.Button(label="Custom")
    custom_btn.add_css_class("flat")
    custom_btn.connect("clicked", lambda *_: self._apply_preset("custom"))

    presets.append(full_btn)
    presets.append(readonly_btn)
    presets.append(custom_btn)
    header_row.append(presets)

    # Count badge (right-aligned)
    self._tool_count_label = Gtk.Label(label="0/8 tools")
    self._tool_count_label.add_css_class("agent-builder-tool-count")
    self._tool_count_label.set_hexpand(True)
    self._tool_count_label.set_xalign(1.0)
    header_row.append(self._tool_count_label)

    outer.append(header_row)

    # ── Categorized tool grid ──
    tools = self._handler.get_tool_options()

    # Define categories: (display_name, {tool_name, ...})
    # Tool names verified against get_all_tools() output:
    #   read_file, write_file, edit_file, exec_command,
    #   list_files, search_files, web_search, web_fetch
    categories = [
        ("Read", {"read_file", "list_files", "search_files"}),
        ("Write", {"write_file", "edit_file"}),
        ("Execute", {"exec_command"}),
        ("Web", {"web_search", "web_fetch"}),
    ]

    # Build a name→tool_info lookup for O(1) access
    tool_map = {t["name"]: t for t in tools}

    # Track which tools we placed (to catch new tools added later)
    placed = set()

    for cat_name, cat_tools in categories:
        # Find tools in this category that actually exist
        cat_items = [(name, tool_map[name]) for name in cat_tools if name in tool_map]
        if not cat_items:
            continue
        placed.update(name for name, _ in cat_items)

        # Category header
        cat_label = Gtk.Label(label=cat_name)
        cat_label.add_css_class("agent-builder-tool-cat-label")
        cat_label.set_xalign(0.0)
        outer.append(cat_label)

        # FlowBox grid for this category
        flow = Gtk.FlowBox()
        flow.add_css_class("agent-builder-tool-grid")
        flow.set_min_children_per_line(2)
        flow.set_max_children_per_line(3)
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_homogeneous(True)

        for name, t in cat_items:
            check = Gtk.CheckButton(label=name)
            check.add_css_class("agent-builder-tool-check")
            # Full description in tooltip — first line only (before "WHEN TO USE")
            desc_first_line = t["description"].split("\n")[0].strip()
            check.set_tooltip_text(desc_first_line)
            check.connect("toggled", lambda *_: self._update_tool_count())
            self._tool_checks[name] = check

            child = Gtk.FlowBoxChild()
            child.set_can_focus(False)
            child.set_child(check)
            flow.append(child)

        outer.append(flow)

    # Safety: place any tools not in any category (uncategorized)
    unplaced = set(tool_map.keys()) - placed
    if unplaced:
        cat_label = Gtk.Label(label="Other")
        cat_label.add_css_class("agent-builder-tool-cat-label")
        cat_label.set_xalign(0.0)
        outer.append(cat_label)

        flow = Gtk.FlowBox()
        flow.add_css_class("agent-builder-tool-grid")
        flow.set_min_children_per_line(2)
        flow.set_max_children_per_line(3)
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_homogeneous(True)

        for name in sorted(unplaced):
            t = tool_map[name]
            check = Gtk.CheckButton(label=name)
            check.add_css_class("agent-builder-tool-check")
            desc_first_line = t["description"].split("\n")[0].strip()
            check.set_tooltip_text(desc_first_line)
            check.connect("toggled", lambda *_: self._update_tool_count())
            self._tool_checks[name] = check

            child = Gtk.FlowBoxChild()
            child.set_can_focus(False)
            child.set_child(check)
            flow.append(child)

        outer.append(flow)

    # Initial count
    self._update_tool_count()

    return outer
```

**Traced code paths:**
- `self._handler.get_tool_options()` → verified returns `list[dict]` with keys `{"name", "description"}` (from `get_available_tools()` in `utils/agent_defs.py:418`)
- `Gtk.FlowBox()`, `.set_min_children_per_line()`, `.set_max_children_per_line()`, `.set_selection_mode()` — verified in GTK4
- `Gtk.FlowBoxChild()`, `.set_can_focus(False)`, `.set_child()` — standard GTK4 API
- `check.connect("toggled", ...)` — `Gtk.CheckButton` has "toggled" signal
- `check.set_tooltip_text()` — inherited from `Gtk.Widget`, verified

#### `_update_tool_count()` — new method

```python
def _update_tool_count(self) -> None:
    """Update the 'N/M tools' count badge."""
    total = len(self._tool_checks)
    selected = sum(1 for c in self._tool_checks.values() if c.get_active())
    if self._tool_count_label:
        self._tool_count_label.set_label(f"{selected}/{total} tools")
```

#### `_apply_preset()` — update to call `_update_tool_count()`

**Current signature:** `def _apply_preset(self, preset: str) -> None:` — unchanged.

Add one line at the end, after the existing if/elif block:

```python
def _apply_preset(self, preset: str) -> None:
    """Apply a tool preset to all checkboxes."""
    all_tools = list(self._tool_checks.keys())
    read_only = {"read_file", "list_files", "search_files", "web_search", "web_fetch"}

    if preset == "full":
        for name, check in self._tool_checks.items():
            check.set_active(True)
    elif preset == "readonly":
        for name, check in self._tool_checks.items():
            check.set_active(name in read_only)
    # "custom" — leave as-is

    self._update_tool_count()  # NEW: update count badge after preset
```

**Verified:** The `read_only` set names match actual tool names returned by `get_all_tools()`.

#### `_fill_form()` — update to refresh count badge after setting tools

After the existing tool pre-fill block:

```python
        # Check tools
        selected_tools = set(agent_def.get("tools", []))
        for name, check in self._tool_checks.items():
            check.set_active(name in selected_tools)

        self._update_tool_count()  # NEW: update count after pre-fill
```

**Verified:** `_fill_form()` is called once during `__init__` when `agent_def is not None`. At that point `self._tool_count_label` exists because `_build_tools_section()` is called before `_fill_form()` in `__init__`.

#### `_get_selected_tools()` — no changes

Current implementation returns `[name for name, check in self._tool_checks.items() if check.get_active()]` which still works — `self._tool_checks` is populated the same way, just with different widget parents.

### 2.2 `ui/styles.py`

**What changes:** Add 4 new CSS classes for the categorized tool grid. No existing CSS modified.

**Location:** Insert after the existing `.agent-builder-mcp-check` block (around line 158), before the "Prompt library" comment.

```css
/* Agent Builder — Tool category grid */
.agent-builder-tool-count {
    font-size: 0.8em;
    opacity: 0.6;
}
.agent-builder-tool-cat-label {
    font-size: 0.85em;
    font-weight: 600;
    opacity: 0.7;
    margin-top: 4px;
}
.agent-builder-tool-grid {
    background: rgba(255, 255, 255, 0.04);
    border-radius: 6px;
    padding: 4px;
}
.agent-builder-tool-check {
    padding: 6px 8px;
}
```

**Note:** Uses `rgba(255, 255, 255, 0.04)` matching existing `.agent-builder-mcp-list` pattern (the project doesn't use `@CLR_PANEL` CSS variables — verified all existing agent-builder CSS uses inline rgba values).

---

## 3. Data Flow

```
User opens Edit Agent dialog
  → __init__() calls _build_tools_section()
    → handler.get_tool_options() returns [{name, description}]  (8 items)
    → Build categorized FlowBox grid with CheckButtons
    → Tool names as labels, first-line descriptions as tooltips
    → _update_tool_count() sets "0/8 tools"

User clicks preset button
  → _apply_preset("full"|"readonly"|"custom")
    → Set all CheckButton active states
    → _update_tool_count() updates badge

User toggles individual tool
  → CheckButton "toggled" signal fires
    → _update_tool_count() updates badge

User clicks Save
  → _do_save() → get_values() → _get_selected_tools()
    → Returns list[str] of active tool names (unchanged API)
    → handler.save(agent_def) → save_agent_def() → YAML (unchanged)
```

No changes to handler, model, persistence, or downstream consumers.

---

## 4. File Change Summary

| File | Change | Lines added | Lines removed | Risk |
|------|--------|-------------|---------------|------|
| `ui/views/agent_builder.py` | Rewrite `_build_tools_section()`, add `_update_tool_count()`, update `_apply_preset()` + `_fill_form()` | ~95 | ~35 | Medium (view rewrite) |
| `ui/styles.py` | Add 4 CSS classes | ~18 | 0 | Low (additive only) |

**Total:** ~113 lines added, ~35 removed. Net +78 lines.

---

## 5. Implementation Order

1. **Add CSS classes** to `ui/styles.py` — 4 new classes, additive, zero risk
2. **Add `_update_tool_count()` method** — 4 lines, no dependencies
3. **Rewrite `_build_tools_section()`** — the main body of work
4. **Update `_apply_preset()`** — add `_update_tool_count()` call at end
5. **Update `_fill_form()`** — add `_update_tool_count()` call after tool pre-fill
6. **Verify:** Launch CrabCakes → Edit Agent → check tool grid renders correctly → test presets → test individual toggles → test count badge → test save/load round-trip

---

## 6. Acceptance Criteria

- [ ] Tools appear in categorized groups: Read (3), Write (2), Execute (1), Web (2)
- [ ] Each category has a bold header label
- [ ] Checkbox labels show tool name only (no "WHEN TO USE" text)
- [ ] Hovering a checkbox shows the first line of its description as tooltip
- [ ] Count badge shows "N/8 tools" and updates on every toggle or preset click
- [ ] "Full Access" preset checks all tools, count shows "8/8 tools"
- [ ] "Read Only" preset checks read_file, list_files, search_files, web_search, web_fetch, count shows "5/8 tools"
- [ ] "Custom" preset leaves tools unchanged
- [ ] Tools that aren't in any category appear under "Other"
- [ ] Saving an agent with selected tools persists correctly (round-trip test)
- [ ] Re-opening Edit Agent on a saved agent shows correct checkboxes pre-filled
- [ ] No `ScrolledWindow` wrapping the tool checkboxes — all 8 visible without scrolling
- [ ] CSS uses `add_css_class()` only, no inline styles — ARCHITECTURE.md §9 compliant

---

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| New tool added to `get_all_tools()` not in any category | Appears under "Other" section automatically |
| `get_tool_options()` returns empty list | No categories rendered, count shows "0/0 tools" |
| `get_tool_options()` returns tools with no description | Tooltip shows empty string (no crash) |
| Description is single line (no `\n`) | Tooltip shows full line — `split("\n")[0]` handles this |
| Description is empty string | Tooltip shows empty string — safe |
| `_fill_form()` called on new agent (no tools key) | `agent_def.get("tools", [])` returns `[]` → all unchecked, count "0/8 tools" |
| Rapid toggling | Each toggle fires `_update_tool_count()` — lightweight label update, no performance concern |

---

## 8. ARCHITECTURE.md Updates Required

None. The change follows existing architecture:
- View-only change (§3: views are stateless rendering)
- CSS in `ui/styles.py` only (§9)
- CSS class naming follows `agent-builder-*` convention (§9.3)
- No handler or model changes

---

## Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?** ✅ Traced all GTK4 APIs, verified `get_tool_options()` return format, verified tool names match `get_all_tools()` output, verified `_tool_checks` dict contract.

2. **Did I catch all exception types?** ✅ No new exception-generating code. `get_tool_options()` wraps `get_all_tools()` in a try/except ImportError returning `[]` — handled by "empty list" edge case.

3. **Did I verify key structures?** ✅ `self._tool_checks` is `dict[str, Gtk.CheckButton]` — same key structure as current code, just different widget parents.

4. **Did I trace the data flow end-to-end?** ✅ Traced from `get_tool_options()` → category partitioning → FlowBox → CheckButton toggling → `_get_selected_tools()` → `get_values()` → `save()` → YAML. No break in the chain.

5. **Would an implementer produce working code?** ✅ Yes. All GTK4 APIs verified, all data contracts verified, all edge cases documented. The only judgment call is the category grouping which is explicit in the spec.

---

**Files NOT changed** (already correct):
- `ui/handlers/agent_builder_handler.py` — `get_tool_options()` returns correct format, no changes needed
- `utils/agent_defs.py` — `get_available_tools()` provides correct data, no changes needed
- `agent/tools.py` — tool definitions unchanged (tooltips handle description format)
- `ui/window.py` — `_on_agent_saved()` consumes `get_values()` dict, contract unchanged
