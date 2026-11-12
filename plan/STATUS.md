# Plan status

Each phase ticks its own line (`- [x] <id> …`) in its last commit. The runner treats a ticked line as done.

## Phases

- [x] 01 test: CLI characterization tests and Pilot smoke tests
- [x] 02a chore: lint/type tooling, CI, lockfile, untrack _version.py
- [x] 02b refactor(cli): share logic across the three _cli_activate* functions
- [x] 02c refactor(tui): de-duplicate screens, Backend, public imports
- [x] 02d docs: align README, man page and AGENTS.md with the code
- [x] 03a fix(tui): escape external text in markup
- [x] 03b fix(tui): tiering can never break role loading
- [x] 03c fix(security): --log redaction, token-cache permissions, Graph token lock
- [x] 03d fix(tui): blank duration, Entra error wrap, dbus parsing
- [x] 03e fix(tui): auth-error classification, modal and Retry
- [x] 03f fix(azure): user lookup once, bounded loads, logged lookups, device-code hardening
- [x] 04a fix(tui): h/l tab switching, list highlight on focus, Enter in the filter
- [x] 04b feat(tui): activation screen layout, readable errors, consistent Escape
- [ ] 04c feat(tui): next steps after activation
- [ ] 04d feat(tui): time left, selected-row styling, counts and order
- [ ] 04e feat(tui): help panel, footers, theme override
- [ ] 04f feat(tui): recent activations
- [ ] 04g feat(tui): parity and demo data (decision-gated)
- [ ] 04z docs: regenerate screenshots (runner only)
- [ ] 05 feat(cli): additive flags (opt-in)
- [ ] 06a fix(cli)!: contract changes for currently broken cases (opt-in per item)
- [ ] 06b feat(cli)!: breaking contract changes (opt-in per item)

## Blocked

## Notes

- 01: REPORT.md §1 row E1 omits the first stdout line `Fetching Entra eligible roles…` (printed before the device-code block); test_E1 pins the real output. fake_azure also has `mg_roles_err` (M11) and `auth_err` (AuthErrorModal) toggles, and run_cli pins `COLUMNS=80` so the usage block is stable.
- 02a: `release-type: simple` is duplicated in `.github/workflows/release-please.yml` and `release-please-config.json`; owner should decide which one is authoritative (left unchanged).
- 02a: CI `check` is now a Python matrix, so its status checks are named `check (3.11)`/`(3.12)`/`(3.13)`; update branch-protection required checks if they name `check`.
- 02a: `license = "GPL-3.0-only"` matches the GPLv3 LICENSE text, which doesn't say "or later"; owner should confirm only vs or-later.
- 02a: ruff excludes `plan/`, and `ruff format` excludes the frozen `tests/test_cli_contract.py`. The existing narrow `# type: ignore[attr-defined]` on `self.app.dry_run`/`demo_mode` were kept as-is; a typed `PimApp` accessor fits 02c.
- 02c: the demo branches in ScopeScreen's Entra load and both AssignmentsScreen loads sat outside the `try`; with the Backend they now share the live path's `try`, which only matters if demo data raised. `PimApp._load_account_info` and the title still branch on `demo_mode` (app, not a screen). Screens reach the backend via `self.app.backend  # type: ignore[attr-defined]`.
- 02c: `tiering.ensure_*_loaded()` keeps the old "reload while the index is empty" semantics (a failed fetch is retried by the next caller), now serialised per index; 03b may want to cache the failure.
- 02d: argparse-manpage isn't installed in .venv, so the new `[FILES]` include section was only checked in a hand-built roff page (renders cleanly, examples complete); the runner's build is the first real check of where it lands. The existing `Step 1 \(em …` WORKFLOW headings render as `Step 1 —— …` (pre-existing, left as is).
- 03a: the helper is `safe_markup(template, **values)` in `fomo/screens/_common.py` (`$name` placeholders via `Content.from_markup`). `textual.markup.escape` was rejected: it doubles a trailing backslash and leaves `[Legacy]`, `[ x ]` and `[$var]` unescaped, all of which Textual swallows. `DataTable` cells are now `rich.text.Text`, which has no ordering, so `AssignmentsScreen` sorts with `key=str`.
- 03a: the device-code prompt uses a bare `[link]$url[/link]` tag, so the URL isn't a clickable hyperlink (pre-existing; `$` placeholders don't substitute inside tags, so a fix needs `Content.stylize` with a link style).
- 03b: tier data now loads in its own worker alongside the role fetch, so on a slow first download (no fresh cache) a user who activates before it arrives gets no blast-radius warning. A UI-callback exception now surfaces as Textual's WorkerFailed crash instead of a fake fetch error. `Backend.allow_network` (False for demo) gates the download.
- 03b: the cache isn't keyed by `_TIERING_REF`, so after a ref bump users keep the old data until the 7-day TTL expires. Demo mode no longer downloads tier data, so `scripts/screenshot.py` (04z) shows tier badges only if `~/.cache/fomo/tiering_*.json` exists. The man page's Network access/FILES text doesn't mention pinning, the stale fallback or offline demo (README only, per the brief).
- 03c: beyond the brief, a caller waiting on `_graph_token_lock` gives up with "Authentication cancelled." once its `stop_event` is set, and a caller with a set `stop_event` never starts a device-code flow; otherwise a closed screen's worker could open a browser after the other flow ended. A screen that waits shows its loading state, not the other screen's code.
- 03c: `_redact` also masks the raised `RuntimeError` text of `_run_az` (az stderr) and `_run_graph`, since the screens log it. `az account show`/`account list` bodies (user name, tenant) are still logged; only the token and profile calls skip the body.
- 03d: `dbus-monitor` likely prints the SettingChanged value on one line as `variant       uint32 1` (dbus-print-message writes `variant ` before the inner value), so `_parse_color_scheme_line`, like the loop it replaced, probably never matches a real signal and live theme switching never fires; the `uint32`-first match was kept as-is (out of scope). `isdigit()` became `isdecimal()` there, because `int("²")` raised too.
- 03e: loaders that fail together share one dialog via `PimApp.show_auth_error` (Retry runs each one's reload). Beyond the brief, the app's own Retry also reloads ScopeScreen's subscription list when it is empty, because without a session `az account list` returns `[]` instead of failing. The session check opens the dialog for expired, not_logged_in and mfa; the subscription and role loads only for expired/not_logged_in. The raw error line is cut to 200 characters so the dialog fits 80x24.
- 03e: added `azure.forget_graph_access_token()`; Assignments `r` calls it when the Entra tab failed, otherwise "delete graph_token.json and press r" would reuse the in-memory access token for up to an hour. The man page got an `r` entry. ScopeScreen's inline subscription and Entra-tab session errors still say "restart fomo" (no reload key there).
- 03f: wording change in a broken path: when the device-code request itself fails, the CLI's stderr line is now `Error fetching Entra roles: Could not start Graph sign-in: HTTP <code> <error_description>` (or `… HTTP <code> <reason>` for a non-JSON body, `… HTTP 200 unexpected response` for a non-JSON success) instead of urllib's `HTTP Error <code>: <reason>` or a JSONDecodeError. The TUI shows the same text.
- 03f: beyond the brief, on WSL without `BROWSER` fomo launches `wslview` itself (Python's `webbrowser` doesn't know it), and `_is_console_browser` also resolves symlinks (alternatives → w3m). The kill switch now blocks `webbrowser.get` and `BackgroundBrowser.open` too, since fomo opens the browser it picked. The load semaphore is per RolesScreen, and loads still queued when the screen closes still run (four at a time). A network error (URLError) while polling still ends the sign-in (06a territory). The cached user ID survives the auth dialog's Retry, so `az login` as another user mid-session keeps the old ID until restart.
- 04a: Enter on the scope and roles screens is now two priority bindings, `to_list` ("To list") and `proceed`, and `check_action` enables exactly one depending on whether a filter has focus, so the footer reads "⏎ To list" in a filter. When the Entra tab is still loading after `h`/`l`, its list gets focus on arrival only if focus is still on the tab bar; switching with ←/→ on the tab bar keeps focus there as before.
- 04a: a focused list that is rebuilt (Ctrl+s sort, a load finishing while it has focus) now highlights its first selectable row; the previously highlighted row isn't kept. The new tab tests set `app.animation_level = "none"`; the shared `make_app` fixtures don't, so every `_switch_to_entra` still waits ~0.25 s for the tab underline animation (an easy saving if the ~30 s budget gets tight; the suite is at ~29 s).
- 04b: the activation tables use the brief's target columns, Role · Scope · Tier · Status (Entra: Role · Tier · Status), so the eligibility "Expires" column is gone there (the roles screen and its detail pane still show it). A Tier cell shows "—" when tier data hasn't loaded yet and isn't refreshed if it arrives later. An Azure selection of only global roles no longer shows an empty subscription table.
- 04b: `RoleTable` sizes columns by setting DataTable's public `Column.width`/`auto_width` and rewriting a cell so the table re-measures, and `#roles-scroll DataTable { max-height: 999 }` lifts DataTable's default `max-height: 100%` (`initial` falls back to it); both are worth a check on a Textual upgrade. The Details panel writes with `expand=True`, because RichLog otherwise wraps at the console width (80 under `run_test`), not the panel's.
- 04b: the suite now takes ~32.5 s (the new Pilot tests add ~3 s). `animation_level = "none"` in all shared fixtures saved almost nothing: Pilot's own idle wait after every key press (~40–100 ms) dominates, so real savings need fewer key presses in tests (e.g. setting an Input's value where typing isn't under test).
