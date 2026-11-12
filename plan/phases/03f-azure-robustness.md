# Phase 03f: fix(azure), user lookup once, bounded loads, logged lookups, device-code hardening

**Group:** 3
**Findings:** F13, F16, F17
**Contract:** none. No CLI output changes; only the number of `az` calls changes, and the contract tests fake above that level.
**Out of scope:** timeouts (F12) and pagination (F11), which are opt-in (06a).

## Steps

### 1. F16: user lookup once

- `fomo/azure.py`: cache `get_current_user()` in a module-level variable guarded by a lock. Add `reset_caches()` for tests, and call it in `tests/conftest.py`'s autouse fixture.
- `list_eligible_roles` and `list_eligible_roles_mg` still call `get_current_user()`; they just hit the cache.

### 2. F16: bounded parallel loads

`RolesScreen` currently starts one thread per subscription. Bound concurrency to 4 with a shared `threading.BoundedSemaphore(4)`, acquired around the backend call inside `_load_roles_for_sub`. Progress ("Loading roles… k/N") still updates per subscription.

### 3. F17: logged lookups

`_list_active_role_keys` and `_list_active_entra_role_def_ids` keep swallowing errors (behaviour unchanged), but `log.warning("could not read active assignments for %s: %s", scope, exc)`.

### 4. F13: device-code hardening (`_device_code_flow`)

- Open the browser only when `_can_open_browser()`:
  - Linux: `DISPLAY` or `WAYLAND_DISPLAY` set, and not over SSH (`SSH_CONNECTION`/`SSH_TTY` unset)
  - macOS: always
  - WSL: `wslview` on PATH or `BROWSER` set

  Wrap the call in `try`. Never let a text-mode browser take over the terminal: if `webbrowser.get()` returns a console browser (lynx, w3m, links, elinks, www-browser), skip it.
- Poll errors: parse the JSON body defensively. A non-JSON body, or HTTP 429/5xx, counts as "retry after interval", with the interval capped at 30 s. After 3 consecutive non-JSON responses, raise `RuntimeError(f"Graph sign-in failed: HTTP {code}")`.
- Initial device-code request: an HTTP error raises `RuntimeError("Could not start Graph sign-in: HTTP <code> <error_description>")` instead of a raw `HTTPError`. The CLI already catches `Exception` and prints `Error fetching Entra roles: {exc}`. That's a wording change only in a currently-broken path; add a line to STATUS "Notes".

## Tests

- Fake `subprocess.run` counts `ad signed-in-user show` calls across `list_eligible_roles` for 3 subs: exactly 1.
- Semaphore: with 10 subs and a fake loader that tracks concurrent entries (with sleeps), the maximum is at most 4, and all 10 load.
- A failing active-assignment lookup produces a `caplog` warning, and roles are still returned with `is_active=False`.
- `_can_open_browser` combinations via `monkeypatch.setenv`/`delenv`, plus a console-browser detection test.
- Device-code poll with a fake `urlopen`: a 502 HTML body twice, then success, returns the token. Three 502s raise a `RuntimeError` mentioning HTTP 502. No `JSONDecodeError` escapes.

## Verify

- `.venv/bin/python -m pytest -q` passes, with the contract tests unchanged.
- Lint and the type checker are clean.

## Commits

- `fix(azure): look up the signed-in user once per process`
- `fix(tui): limit parallel subscription loads to 4`
- `fix(azure): log failed active-assignment lookups`
- `fix(entra): harden device-code polling and browser launch`

Tick `03f`.
