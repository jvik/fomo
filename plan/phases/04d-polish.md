# Phase 04d: feat(tui), time left, selected-row styling, counts and order

**Group:** 4
**Findings:** F33, F34, F36 (counts, order, persistent partial-failure status)
**Contract:** none. The CLI doesn't print expiry, and dataclass field additions must have defaults.

## Steps

### 1. Time left on active roles (F33)

- `_list_active_role_keys` returns a mapping `(role_def_id, scope) -> endDateTime | None` instead of a frozenset. Update the callers, keeping the `in` checks working.
- `EligibleRole` and `EntraEligibleRole` get `active_until: str | None = None`.
- Add a pure helper in `fomo/timefmt.py`: `format_remaining(iso, now) -> str`, giving "47m left", "3h 05m left", "expired" or "permanent".
- **Roles list row:** `Role  —  Scope   ● active · 47m left` for active roles. Non-active roles show `eligible until 2026-12-31` instead of `[expires …]`.
- **Detail pane:** show "Active until 14:32 (47m left)" and "Eligible until 2026-12-31".
- **Assignments:** the Expiry column shows local time plus time left for activations under 7 days away, otherwise the date. The Entra scope `/` shows as "Directory". Keep sorting correct: sort on the underlying ISO value, not the display text.

### 2. Selected rows stand out (F34)

In `FomoSelectionList.render_line`, selected rows get bold text and the success colour on the `◉`. Check the contrast in both themes with an SVG screenshot in `plan/logs/scratch/`.

### 3. Counts and order (F36)

- The RolesScreen status line counts active (disabled) rows as shown: "N selected · M/T shown", where shown counts every visible row except separators.
- `ActivationScreen` receives roles in the **current display order**, not `sorted(self._selected)` index order.
- **Persistent partial-failure status:** when one or more subscriptions failed to load, the status line shows "⚠ 2 of 5 subscriptions failed · e details". `e` opens a small modal listing each failed subscription with its escaped error and a Retry for just those.

## Tests

- `format_remaining` table test, using a fixed `now`.
- Pilot (fakes): an active role with an `endDateTime` 47 minutes ahead shows "47m left" in its row. The Assignments Entra scope shows "Directory".
- Status-line count with one active role: "0 selected · 3/3 shown".
- Activation order matches display order when sorted by name.
- One failing sub out of 3: the status line shows "1 of 3"; `e` lists it; retry in the modal loads it once the fake succeeds.

## Docs

Update the man include for `e`.

## Verify

- `.venv/bin/python -m pytest -q` passes.
- Lint and the type checker are clean.

## Commits

- `feat(tui): show time left on active roles and assignments`
- `feat(tui): make selected rows stand out`
- `fix(tui): accurate counts, display-order activation, persistent load-failure status`

Tick `04d`.
