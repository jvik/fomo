# Phase 03e: fix(tui), auth-error classification, readable modal and Retry

**Group:** 3
**Findings:** F15, REPORT §3 row 16
**Contract:** none. `is_auth_error` is used only by the TUI; check with `git grep`.

## Problem (verified)

- `is_auth_error` matches any `aadsts`, `unauthorized` or `please run`. MFA and conditional-access errors (AADSTS50076, 53003 …) show "Azure session expired… restart fomo", which is wrong and unhelpful.
- The modal body Label doesn't wrap inside the 52-column dialog, so "fomo." is clipped.
- There's no way to retry after running `az login` in another terminal.
- `assignments_screen.py:178` says "Re-run fomo --entra to re-authorise", which doesn't work because the refresh token is reused.

## Steps

### 1. Classifier in `fomo/azure.py`

Add `classify_auth_error(msg) -> Literal["expired", "not_logged_in", "mfa", "consent", "other"]`:

| Class | Matches |
|---|---|
| expired | AADSTS700082, 70043, 50173, 700084, 50133, "refresh token has expired", "token is expired" |
| not_logged_in | "Please run 'az login'", "az login" combined with "not logged in", "No subscription found" |
| mfa | AADSTS50076, 50079, 50158, 53003, 50078, "multi-factor", "conditional access" |
| consent | `is_scope_error`'s tokens, AADSTS65001, 7000112 |

Keep `is_auth_error(msg)` as a wrapper returning `classify_auth_error(msg) in {"expired", "not_logged_in"}`, so callers keep working.

### 2. AuthErrorModal (`app.py`)

- Takes `kind` and `message`.
- The title and body depend on the kind:
  - **expired/not_logged_in:** "Run `az login` in another terminal, then press Retry."
  - **mfa:** "Your tenant requires MFA or a compliant device for this request. Run `az login --scope https://management.azure.com/.default` (or `az login --tenant <id>`), then Retry."
- Show the first line of the raw message, escaped (03a), in dim text.
- The body wraps (`width: 1fr`). Fix the CSS so nothing is clipped at 80x24.
- Buttons: **Retry** (the default focus), Dismiss, Quit. Retry dismisses with a result, and the pushing screen reloads: ScopeScreen reloads subscriptions; RolesScreen reloads only the failed subscriptions; the app re-runs `_load_account_info`.

### 3. RolesScreen

Only `expired`/`not_logged_in` push the modal (once). `mfa` and `other` stay per-subscription errors. 04d adds the persistent status line; here, just make sure the classification routes correctly.

### 4. Assignments and Entra texts

Replace "Re-run fomo --entra to re-authorise" with: "Sign in to Graph again: delete ~/.cache/fomo/graph_token.json and press r to retry." Add an `r` binding on AssignmentsScreen that reloads both tabs. 04c may extend it.

## Tests

- Classifier table test covering every listed code and phrase, plus negatives like "AuthorizationFailed" (should be `other`).
- **Pilot:**
  - `check_auth` raises an expired-type message: the modal shows the full body ("…then press Retry", nothing clipped; check `render_strips` text at 80x24).
  - Retry after the fake is switched to succeed: the title shows the user, and the subscriptions load.
  - A sub fails with AADSTS50076 in RolesScreen: no modal, and the error is reported for that sub only.
- Assignments: `r` reloads, and the fake is called twice.

## Verify

- `.venv/bin/python -m pytest -q` passes.
- Lint and the type checker are clean.

## Commits

- `fix(tui): distinguish expired sessions from MFA and consent errors`
- `feat(tui): retry after re-login from the auth error dialog`
- `fix(tui): accurate Graph re-authentication hint and reload key on Assignments`

Tick `03e`.
