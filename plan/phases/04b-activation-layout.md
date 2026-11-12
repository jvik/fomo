# Phase 04b: feat(tui), activation screen layout, readable errors, consistent Escape

**Group:** 4
**Findings:** F07, F32, F36 (status styling and error mapping), REPORT §4 mockup
**Contract:** none

## Problem (verified)

- At 80x24 with 5 roles, the Duration field isn't rendered. After a partial failure the justification and duration form vanishes, and the error log is cut off.
- At 120x36, the Duration select collapses after an error.
- The Status column is 36 wide, so it scrolls horizontally at 80 columns. The RichLog doesn't wrap, so the actual cause ("exceeds the maximum allowed PT4H") is invisible.
- Failure statuses are plain text while successes are green.
- Escape differs: Entra pops immediately (a priority binding) and loses the typed justification; Azure blurs first.

## Target layout

This applies to both Azure and Entra through the shared base from 02c.

```
 Activate 3 roles                                       Duration [1 hour ▾]
 Reason ▏_____________________________________________________________
 ─────────────────────────────────────────────────────────────────────
 (scrollable) Role · Scope · Tier · Status   ← Status column takes the rest
 ─────────────────────────────────────────────────────────────────────
 (only after failures) Details: wrapped error text, max ~8 rows, scrollable
 [Activate] [Back]                                   ⏎ Activate  esc Back
```

- The form sits at the top, so it's always visible. The table goes in a container with `height: 1fr` that scrolls. The details panel uses `RichLog(wrap=True, markup=True)`, `height: auto` and `max-height: 8`, and it doesn't push the form out.
- Keep the IDs `#justification`, `#duration`, `#btn-activate`, `#btn-back`, `#roles-table` (and `#global-roles-table` with its warning box for Azure global roles), and `#error-log`.
- Remove the fixed Status width; let the Status column expand. At 80 columns, show the Scope column truncated with `…` rather than scrolling Status out of view.
- **Enter in Reason activates** when the reason isn't blank. With a blank reason, it shows the existing "Justification is required." warning. Tab moves to Duration as before.
- Status styling: success is green `✓`, pending is yellow `⏳`, failure is red `✗` plus a short human message.

  Add a pure helper, `summarize_activation_error(msg) -> str`, for the common ARM and Graph errors:

  | Error | Short message |
  |---|---|
  | `RoleAssignmentRequestPolicyValidationFailed` + `ExpirationRule` | "Exceeds max duration (PTxH)", parsing the allowed maximum when present |
  | `JustificationRule` | "Justification rejected by policy" |
  | `MfaRule` / `MFA` | "MFA required" |
  | `RoleAssignmentExists` / "already exists" | "Already active" |
  | `AuthorizationFailed` | "Not authorized" |
  | `PendingApproval`-type statuses | (status, not an error) |

  Anything else falls back to the first 40 characters. The full text always goes to the details panel.
- **Escape rule** for both screens: a focused, non-empty Input means blur, keep the text, stop. Otherwise go back, unless activating. Remove the Entra priority Escape and the hidden `q` Back binding inconsistency. `q` should behave the same on both: back when not typing.

## Tests (Pilot, fake azure, `dry_run=False` with the fake `activate_role`)

- At 80x24 with 5 roles, `#justification` and `#duration` regions lie fully inside the screen before and after a partial failure. Compute this from widget `region`s against the screen size.
- At 120x36 after a failure, `#duration` keeps height ≥ 3.
- An activation failure with the ExpirationRule message shows the short text in the Status cell, and the full text appears wrapped in `#error-log`. Assert that every word of the message appears in the RichLog lines.
- Enter in a non-empty Reason triggers activation. A blank Reason plus Enter warns and doesn't activate.
- Escape with text in Reason on **both** screens keeps the screen and the text; a second Escape goes back.
- `summarize_activation_error` table test.

## Docs

Update the man include "Activation screen" keys: Enter in Reason activates, Escape blurs then goes back, `q`.

## Verify

- `.venv/bin/python -m pytest -q` passes.
- Lint and the type checker are clean.
- Save before and after text dumps at 80x24 in `plan/logs/scratch/`; they aren't committed.

## Commits

- `feat(tui): rework activation screen layout for small terminals`
- `feat(tui): readable activation status and error details`
- `fix(tui): consistent Escape behaviour on activation screens`

Tick `04b`.
