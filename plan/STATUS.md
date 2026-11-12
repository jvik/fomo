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
- [ ] 03c fix(security): --log redaction, token-cache permissions, Graph token lock
- [ ] 03d fix(tui): blank duration, Entra error wrap, dbus parsing
- [ ] 03e fix(tui): auth-error classification, modal and Retry
- [ ] 03f fix(azure): user lookup once, bounded loads, logged lookups, device-code hardening
- [ ] 04a fix(tui): h/l tab switching, list highlight on focus, Enter in the filter
- [ ] 04b feat(tui): activation screen layout, readable errors, consistent Escape
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
