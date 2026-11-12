# Plan status

Each phase ticks its own line (`- [x] <id> …`) in its last commit. The runner treats a ticked line as done.

## Phases

- [x] 01 test: CLI characterization tests and Pilot smoke tests
- [x] 02a chore: lint/type tooling, CI, lockfile, untrack _version.py
- [x] 02b refactor(cli): share logic across the three _cli_activate* functions
- [ ] 02c refactor(tui): de-duplicate screens, Backend, public imports
- [ ] 02d docs: align README, man page and AGENTS.md with the code
- [ ] 03a fix(tui): escape external text in markup
- [ ] 03b fix(tui): tiering can never break role loading
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
