# Plan status

Each phase ticks its own line (`- [x] <id> …`) in its last commit. The runner treats a ticked line as done.

## Phases

- [ ] 01 test: CLI characterization tests and Pilot smoke tests
- [ ] 02a chore: lint/type tooling, CI, lockfile, untrack _version.py
- [ ] 02b refactor(cli): share logic across the three _cli_activate* functions
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
