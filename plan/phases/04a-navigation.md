# Phase 04a: fix(tui), h/l tab switching, list highlight on focus, Enter in the filter

**Group:** 4
**Findings:** F08, F09, F31 (new Enter semantics)
**Contract:** none

## Problem (verified)

- **F08:** with a list focused, `l`/`h` call `TabbedContent.active = …`. The focused list's pane is hidden, so Textual moves focus to the next focusable widget in that same pane (the filter). `TabbedContent._on_tab_pane_focused` then switches back. Net effect: the tab doesn't change, focus lands in the filter, and the following `i`/`a`/`q` are typed as text. Switching works only while the tab bar is focused (the initial state).
- **F09:** after Enter in a filter moves focus to the list, `highlighted` is `None`, so the first Space does nothing. Users then press Enter and get "Select at least one …".
- After Escape back from Roles, focus returns to whatever was focused before. That's fine, but it can be the filter.

## Steps

### 1. Tab switching

In `ScopeScreen`, `action_next_tab` and `action_prev_tab`:
1. Focus the `Tabs` widget (`self.query_one("#scope-tabs").query_one(Tabs)`) first.
2. Switch `active`.
3. With `call_after_refresh`, focus the target pane's list if it's loaded (`#sub-list` / `#entra-role-list`), otherwise leave focus on the tab bar.

Starting the Entra load on first activation must still happen.

### 2. Highlight on focus

In `FomoSelectionList` (`fomo/widgets.py`), on focus, if `highlighted is None` and `option_count > 0`, set `highlighted` to the first **enabled** option. Disabled rows are the active roles and the "Global assignments" separator. Apply the same after a rebuild (`clear_options`/`add_option`) when the list has focus.

### 3. Enter in the filter

Already "focus the list". Combined with step 2, the first row is highlighted, so `⏎ Space ⏎` works. Update the footer label for Enter when the filter is focused, if feasible ("⏎ To list"); otherwise leave it.

### 4. Docs

- README: the `l`/`h` sentence becomes true. Make it "`h`/`l` (or ←/→ on the tab bar)".
- man include: add `h`/`l` if 02d didn't.

## Tests (Pilot, demo mode)

- With the sub list focused, `l` activates `tab-entra` and focuses `#entra-role-list` once loaded. `h` goes back and focuses `#sub-list`.
- Reproduce the old bug path (Roles → Escape → `l`): the tab switches. Then `i` opens AssignmentsScreen.
- `prod` + Enter in the filter, then Space: `_selected_ids == {"1111…"}`.
- Roles screen: `key vault` + Enter + Space selects Key Vault Administrator. Assert `len(_selected) == 1` and the right index.
- Active (disabled) first rows are skipped by the initial highlight.

## Verify

- `.venv/bin/python -m pytest -q` passes.
- Lint and the type checker are clean.

## Commits

- `fix(tui): h/l switch tabs from anywhere on the scope screen`
- `fix(tui): highlight the first selectable row when a list gains focus`

Tick `04a`.
