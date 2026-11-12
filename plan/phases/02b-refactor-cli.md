# Phase 02b: refactor(cli), share logic across the three activation paths

**Group:** 2
**Findings:** F22
**Contract:** none. Output must stay byte-identical, and `tests/test_cli_contract.py` must not change.

## Goal

Remove the triplication in `fomo/__main__.py` (`_cli_activate`, `_cli_activate_mg`, `_cli_activate_entra`) without changing **any** output, exit code, call order or matching behaviour.

## Constraints

- **Top-level imports in `fomo/__main__.py` stay stdlib-only.** `hatch_build.py` executes this file standalone to build the man page; test U11 guards this. Keep `from fomo import azure` lazy inside functions. If you move helpers to a new module (for example `fomo/cli.py`), import it lazily inside `main()`, and the new module may import `fomo.azure` at top level.
- `build_parser()` is untouched.
- Keep every quirk:
  - **MG mode still does NOT drop inherited parent-MG roles.** That fix is 06b and opt-in.
  - The MG ambiguity error still fires even for an exact ID (06a).
  - The Entra lines have no scope part: `  • {name}… `.
  - The progress line uses `end=""` and `flush=True`, then prints `✓ {status}` or `✗`, with the error detail on stderr indented 4 spaces.
  - Status lookups differ per mode: `result.get("properties", {}).get("status", "Submitted")` for ARM, and `result.get("status", "Submitted")` for Entra.
  - Messages that differ per mode differ exactly as today: "No eligible PIM roles found." vs "No eligible Entra PIM roles found."; "Available eligible roles:" vs "Available eligible Entra roles:"; "Activating N role(s)…" vs "Activating N Entra role(s)…"; "Error fetching roles:" vs "Error fetching Entra roles:".

## Suggested shape

| Helper | Does |
|---|---|
| `_parse_duration_or_exit(duration) -> str` | Duration validation with the current error text and exit 1 |
| `_match_roles(all_roles, role_name) -> list` | Exact (case-insensitive) match, otherwise substring |
| `_exit_no_role_match(role_name, all_roles, entra: bool)` | Exit 1 with the per-mode no-match text |
| `_drop_active(matching) -> list \| None` | Prints the "All N…already active." and "Skipping N already-active role(s)." lines |
| `_activate_all(roles, activate, *, header, line_for, status_of, duration, justification, dry_run) -> int` | The activation loop; returns the error count |

Keep the three `_cli_activate*` functions as thin wrappers with the same names and signatures.

## Verify

- `.venv/bin/python -m pytest -q`: all contract tests pass **unchanged**. Run `git diff plan-01-done -- tests/test_cli_contract.py` and confirm it's empty.
- Ruff and the type checker are clean, if installed.

## Commit

`refactor(cli): share matching and activation logic across modes`

The body should mention that the output is byte-identical, as guarded by the contract tests. Tick `02b`.
