# Phase 06b: feat(cli)!, breaking contract changes (opt-in per item)

**Group:** 6. Runs only if uncommented in QUEUE.
**Decisions:** `OPT_6B_*` (only approved items run), and D10.

Each item is a deliberate change to the frozen CLI contract and ships as its **own commit**. With D10 = `yes`, use `feat(cli)!:`/`fix(cli)!:` plus a `BREAKING CHANGE:` footer stating the old behaviour, the new behaviour and the justification. Never bundle an item with a refactor.

Rules for `tests/test_cli_contract.py` are the same as in 06a: edit only the stated rows, mark each with `# changed by <item> (F##)`, list the rows in the commit body, and add new rows for new cases.

## Items

### `OPT_6B_MG_INHERITED=yes` (F42)

`--mg` drops eligible roles whose scope isn't the selected management group itself. This matches subscription mode, which drops inherited parent-MG roles.

**Justification:** `fomo --mg Corp Owner -r …` currently activates Owner at *Tenant Root*, a broader scope than the user asked for.

**Rows:** M7 changes from exit 0 (activates at Tenant Root) to exit 1 with:
```
Error: No eligible role matching 'Owner' found.
Available eligible roles:
  Reader
```
M5's "Available eligible roles" list loses `Owner`.

### `OPT_6B_DEMO=honour` or `OPT_6B_DEMO=reject` (F41)

**Justification:** `--demo` promises "no Azure auth required", but with `-r` it currently performs a real activation.

- **`honour`:** CLI mode with `--demo` uses `fomo.demo` data and forces `dry_run=True`. Output follows the same templates, with demo names, ending in `✓ DryRun`. S15 changes to assert that demo data was used and no azure fake was called.
- **`reject`:** `parser.error("--demo cannot be combined with -r/--reason")`, exit 2. S15 changes accordingly.

Update the `--demo` help text (and the 05 wording if it exists), README and man.

### `OPT_6B_BLANK_REASON=yes` (F45)

`-r ""` or a whitespace-only reason gives `parser.error("-r/--reason must not be empty")`, exit 2.

**Justification:** parity with the TUI, which requires a justification. Many PIM policies reject blank justifications server-side anyway, with a less clear error.

**Rows:** S16 changes.

### `OPT_6B_STDERR_NAMES=yes` (F46)

The stderr line after a failed activation names the role and scope: `    Reader — Contoso Production: <error>` for ARM, and `    Security Reader: <error>` for Entra. The stdout `✗` lines are unchanged.

**Justification:** when stdout and stderr are captured separately, failures can't currently be attributed to roles.

**Rows:** S12, M9 and E6 change on their stderr lines only.

## Docs

README and the man page describe each new behaviour. If D10 is `yes`, the README notes the major-version bump.

## Verify

- `.venv/bin/python -m pytest -q` passes.
- Every changed row is marked and listed in its commit.
- Lint and the type checker are clean.

## Commits

One per approved item.

Tick `06b`, and record in STATUS "Notes" which items ran.
