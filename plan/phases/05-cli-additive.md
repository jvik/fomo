# Phase 05: feat(cli), additive flags (opt-in)

**Group:** 5. Runs only if uncommented in QUEUE.
**Findings:** REPORT §3 row 10, F41 (help text only), F13 (`--no-browser`), F12 (`--timeout`, off by default)
**Decisions:** D4, D9, and `CLI_*`. Skip any flag whose decision is `no`.

**Contract:** additive only. **Every existing invocation keeps identical stdout, stderr and exit code.** `tests/test_cli_contract.py` must not change; the runner checks it byte for byte. New tests go in `tests/test_cli_additive.py`.

## The `usage:` line (D4)

Every new flag changes argparse's usage block, which is printed for exit-2 errors and `-h`.
- **`snapshot`:** update `tests/test_cli_usage_snapshot.py` in the **same commit** as each flag, and say so in the commit body.
- **`freeze`:** set `usage=` in `build_parser()` to today's exact usage string, so the usage block never changes. Add a test that `-h` lists the new flags in the options section.

## Flags

| Flag | Behaviour | Decision |
|---|---|---|
| `--version` | Prints `fomo <version>` to stdout and exits 0 (argparse `version` action, using `fomo.__version__` imported lazily). **Keep `__main__.py` top-level imports stdlib-only**: read the version via `importlib.metadata` inside a callable, or a custom action | CLI_VERSION |
| `--list` | Read-only. Never activates and doesn't require `-r`. Lists the eligible roles that the given positionals and mode would match, using the **same** matching code. `fomo --list` lists subscriptions. `fomo --list SUB` lists eligible roles in matching subs. `fomo --list --mg MG` lists the MG's roles. `fomo --entra --list` lists Entra roles. Output goes to stdout, one per line: `<role>\t<scope display>\t<active\|eligible>`. Errors reuse the existing wording and exit codes | CLI_LIST |
| `--json` | With activation or `--list`: suppresses progress lines and prints one JSON document to stdout. For activation: `{"mode": "...", "activated": [{"role", "scope", "status"}], "skipped_active": n, "failed": [{"role", "scope", "error"}]}`. Exit codes are unchanged. Errors stay on stderr with the same wording | CLI_JSON |
| `-q`, `--quiet` | Suppresses stdout progress lines (`Fetching…`, `Activating…`, per-role lines). Errors and warnings on stderr are unchanged. Exit codes are unchanged | CLI_QUIET |
| `--no-browser` | Device-code flow never opens a browser | CLI_NO_BROWSER |
| `--timeout SECONDS` | Opt-in timeout for each `az` call and HTTP request. Default `None` (today's behaviour) | CLI_TIMEOUT |
| `--logout` | Deletes the cached Graph token file, prints `Signed out of Microsoft Graph (removed <path>).` and exits 0. If there's no cache, prints `No cached Graph sign-in.` and exits 0 | CLI_LOGOUT |

Thread `quiet`, `json` and `timeout` through the 02b helpers with defaults equal to today's behaviour.

## Help text (D9 = `yes`)

- `--mg`: "Provide a management group display-name substring or its exact ID (the short name, e.g. `mg-contoso`)."
- `--demo`: "Launch the TUI with dummy data, no Azure auth required. Has no effect with -r/--reason." Use this exact wording unless F41 is opted in (06b); if 06b runs later, it updates this text.

These change `-h` output and the man page, not the frozen contract.

## Tests (`tests/test_cli_additive.py`)

For each flag:
- its happy path and its error path
- the flag combined with an existing invocation, showing that the existing output changes only as the flag defines

Also add a test that runs a representative sample of the contract rows (S1, S6, M2, E1, U1) **without** the new flags and gets identical results. That's redundant with the frozen file, but documents intent.

## Docs

README "Non-interactive (CLI) mode" and the man include EXAMPLES get a short example for each flag.

## Verify

- `.venv/bin/python -m pytest -q` passes.
- `git diff plan-01-done -- tests/test_cli_contract.py` is empty.
- Lint and the type checker are clean.

## Commits

One per flag, `feat(cli): add --<flag>`, plus `docs(cli): clarify --mg and --demo help` if D9.

Tick `05`.
