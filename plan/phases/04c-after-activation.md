# Phase 04c: feat(tui), next steps after activation

**Group:** 4
**Findings:** F10
**Contract:** none

## Problem (verified)

After activation, "Done" pops back to RolesScreen. There, the just-activated role is still selected and not marked active, so pressing Enter again re-submits it (in real Azure: RoleAssignmentExists). The Activate button stays disabled, so failed roles can't be retried. There's no quit and no way to see the new assignments.

## Steps

1. When activation finishes, the bottom bar and footer offer:
   - **`r` Retry failed:** only rows that failed. Re-enable Activate, relabelled "Retry failed (N)".
   - **`i` Assignments:** push AssignmentsScreen, which loads fresh.
   - **`q` Quit**
   - **Enter / Done:** pop back to ScopeScreen, discarding the roles screen. Keep the subscription selection, so the user can activate more roles in the same subscriptions.
2. If the user presses Escape after activation instead, they return to RolesScreen. The activated roles are marked `is_active=True` there (rebuild the list, so they show as disabled "(active)"), and the selection is cleared.
3. The end summary replaces "Activation requests submitted.", for example "2 activated · 1 pending approval · 1 failed". The severity is the worst outcome.
4. Do the same on the Entra activation screen (shared base). There, Done returns to the Entra tab with the selection cleared and the activated roles marked active.

## Tests (Pilot, demo or fakes)

- After a successful activation, Escape returns to RolesScreen. The activated role's option is disabled and `_selected` is empty.
- After a partial failure, `r` re-activates only the failed role. The fake records it once more, and the others aren't repeated.
- `i` after activation pushes AssignmentsScreen. `q` exits the app.
- The summary toast text matches the mix of outcomes.

## Docs

Update the man include "Activation screen" section with `r`, `i` and `q` after completion.

## Verify

- `.venv/bin/python -m pytest -q` passes.
- Lint and the type checker are clean.

## Commit

`feat(tui): next steps after activation (retry failed, assignments, quit)`

Tick `04c`.
