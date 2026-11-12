# Phase 04f: feat(tui), recent activations

**Group:** 4
**Findings:** F38, REPORT §4 (recents mockup, 2-key flow)
**Contract:** none
**Decision:** D6 must be `yes`. If it's `no`, tick the phase with a STATUS "Notes" line "skipped by D6" and finish with `PHASE 04f: DONE`.

## Design

### State file

- Path: `${XDG_STATE_HOME:-~/.local/state}/fomo/state.json`. Directory 0700, file 0600, written atomically (reuse the 03c helper if there is one).
- Contents: `{"version": 1, "recent": [...]}`, at most 5 entries, newest first, de-duplicated by target set.
- Each entry:
  - `kind`: `azure` | `entra`
  - `subscriptions`: list of sub IDs (azure only)
  - `targets`: `[role_definition_guid, scope]` pairs for Azure, or `[role_definition_id, directory_scope_id]` pairs for Entra
  - `labels`: short display text
  - `justification`
  - `duration`
  - `ts`
- Written after an activation where at least one role succeeded or is pending.
- **Never** written in demo mode (use an in-memory store), and never when `FOMO_NO_STATE=1` is set.
- A corrupt or unreadable file is ignored with a debug log, and never crashes.

### UI

- A third tab, **Recent**, on ScopeScreen, hidden when there are no entries. Rows look like `1  Key Vault Administrator · Contoso Production   1h · "INC-…"`.
- Number keys `1`–`5` (on the Recent tab, or anywhere on ScopeScreen when no Input is focused) start that entry:
  - **azure:** push `RolesScreen(subs, preselect=targets, autoadvance=True)`. When loading finishes, if every target is present and inactive, it pushes `ActivationScreen` directly, prefilled with the justification and duration. Otherwise it shows the list with the available targets preselected and a toast naming what's missing or already active.
  - **entra:** the same, from the Entra data.
- The justification is prefilled but fully editable. The duration is preselected.
- The keystroke goal for the common case is `1` then `⏎`.

## Tests (fakes, `tmp_path` state dir via `XDG_STATE_HOME`)

- After a successful fake activation, `state.json` holds 1 entry with mode 0600 (directory 0700). Demo mode writes nothing.
- Restarting the app shows the Recent tab with that entry. Pressing `1` reaches ActivationScreen with the justification and duration prefilled, and Enter activates the same role. Assert the fake call.
- A target that's now active: the list shows it disabled, a toast appears, and there's no auto-advance.
- A corrupt `state.json` is ignored.
- `FOMO_NO_STATE=1` means nothing is written.

## Docs

- README: a "Recent activations" note, including that the justification is stored locally and how to disable it (`FOMO_NO_STATE=1`).
- man include: keys and FILES.

## Verify

- `.venv/bin/python -m pytest -q` passes.
- Lint and the type checker are clean.

## Commit

`feat(tui): recent activations for one-key re-activation`

Tick `04f`.
