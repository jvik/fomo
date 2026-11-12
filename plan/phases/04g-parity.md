# Phase 04g: feat(tui), parity and demo data (decision-gated)

**Group:** 4
**Findings:** F39, F40, REPORT §3 rows 2 and 17
**Contract:** none. **The CLI stays sequential**, because its output order is part of the contract.
**Decisions:** D7 and D8 gate parts 1 and 2. Part 3 always runs.

## Part 1: parallel TUI activation (only if D7 is `yes`)

Activate at most 3 roles concurrently inside the activation worker, using a `ThreadPoolExecutor(3)`. Each row's status still updates as its own result arrives, and the done summary waits for all of them. Update README and man: "the TUI activates up to 3 roles in parallel; the CLI activates them one after another".

**Test:** a fake `activate_role` sleeps 0.3 s and tracks concurrency. The maximum is at most 3, and 6 roles finish in under 1.2 s.

## Part 2: management-group scope and custom duration (only if D8 is `yes`)

- **MG tab.** A "Mgmt groups" tab on ScopeScreen lists `backend.list_management_groups()`, with filter and multiselect. Proceeding opens `RolesScreen` in MG mode, which uses `backend.list_eligible_roles_mg` for each selected MG.
  - Inherited parent-MG roles appear under the existing "⚠ Global assignments" separator, the same as today's TUI behaviour for subscriptions.
  - Demo data needs at least two MGs.
  - Add `list_management_groups` and `list_eligible_roles_mg` to `Backend` and `DemoBackend`.
- **Custom duration.** Duration options end with "Custom…", which reveals an Input validated by `azure.parse_duration`. Show an inline error for invalid input; the validated value is used.

**Tests:** Pilot through the MG tab to activation in demo mode. Custom duration "90m" becomes `PT90M` in the fake call, and "abc" shows an error and blocks activation.

## Part 3: demo data (always)

- `demo.list_eligible_roles(sub_id)` also returns the management-group "Reader" role (scope `mg-contoso`) for Contoso Production, as real Azure does with `asTarget()`. The "Global assignments" section then appears in demo mode.
- Demo expiries and active assignments are computed relative to `datetime.now(UTC)`: active ones end 30–90 minutes from now, and eligibilities end in 1–6 months. Demo screenshots then never look stale.

**Tests:** demo roles for Contoso Production include an `is_global` role. Every active demo assignment's expiry is in the future.

## Verify

- `.venv/bin/python -m pytest -q` passes.
- Lint and the type checker are clean.

## Commits (one per part that runs)

- `feat(tui): activate up to three roles in parallel`
- `feat(tui): management-group scope tab and custom duration`
- `fix(demo): include a global role and use relative dates`

Tick `04g`. In STATUS "Notes", record which parts ran.
