# Decisions

Edit the values, then commit. The runner reads lines of the form `KEY=value`, using the first word after `=`. The phases read the whole file. Defaults are my recommendations; every opt-in item defaults to `no`.

## General

```
D1_DEV_DEPS=ruff,mypy      # dev-only tools for 02a: none | ruff | ruff,mypy | ruff,basedpyright
D2_LOCK_AND_PIN=yes        # 02a: commit uv.lock and pin textual>=8.2,<9 (yes | no)
D3_SNAPSHOT_TESTS=no       # 01: add the pytest-textual-snapshot dev dependency (yes | no)
D5_TIERING=pin-sha         # 03b: pin-sha (pin the upstream tiering data to a commit SHA) | keep-main
D6_RECENTS=yes             # 04f: remember recent activations, including the justification, in a 0600 state file (yes | no)
D7_PARALLEL_TUI=no         # 04g: activate TUI roles in parallel, at most 3 at a time (yes | no). The CLI stays sequential
D8_TUI_PARITY=no           # 04g: management-group tab and custom duration in the TUI (yes | no)
D10_BREAKING_MARKER=yes    # 06a/06b commits use "!" and a BREAKING CHANGE footer, which release-please turns into a major bump (yes | no)
```

Notes:
- **D1:** mypy and basedpyright both run offline. Plain `pyright` downloads Node.js on first use, which fails in the sandbox.
- **D5:** with `pin-sha`, the runner looks up the current `main` SHA of `emiliensocchi/azure-tiering` before phase 03b runs.

## Phase 05: additive CLI flags

Phase 05 runs only if you uncomment it in QUEUE.

```
D4_USAGE_LINE=snapshot     # snapshot | freeze. See below
D9_HELP_TEXT=yes           # fix wrong --help text (--mg "full ID", --demo in CLI mode)
CLI_VERSION=yes            # --version
CLI_LIST=yes               # --list: read-only listing of eligible roles, subscriptions or MGs
CLI_JSON=yes               # --json: machine-readable output
CLI_QUIET=yes              # -q/--quiet: suppress progress lines
CLI_NO_BROWSER=yes         # --no-browser: don't open a browser for the Graph device code
CLI_TIMEOUT=yes            # --timeout SECONDS: off by default
CLI_LOGOUT=yes             # --logout: delete the cached Graph token
```

Adding any flag changes argparse's `usage:` line. That line is printed on every exit-2 error and in `--help`.
- `snapshot`: the contract tests freeze only the exit code and the final `fomo: error: …` line. A separate snapshot test of the usage line gets updated deliberately in the same commit.
- `freeze`: `build_parser()` gets a fixed `usage=` string identical to today's, so the usage line never changes and new flags appear only in the option list of `--help`.

## Phase 06a: contract changes that only affect cases that currently fail, hang or target the wrong thing

Each item is a separate commit. It runs only if it's set to `yes` and 06a is uncommented in QUEUE.

```
OPT_6A_PAGINATION=no       # F11: follow nextLink/@odata.nextLink. The CLI may find roles it used to miss
OPT_6A_TENANT=no           # F05: don't reuse a Graph refresh token from another tenant. May show a device-code prompt
OPT_6A_TIMEOUTS=no         # F12: timeouts on az and HTTP calls. Hangs become exit 1 with a message
OPT_6A_ENTRA_SCOPE=no      # F18: an Entra role is "active" only for the same directory scope
OPT_6A_MG_EXACT=no         # F43: an exact MG id or name wins over substring matches
OPT_6A_DURATION=no         # F44: reject zero durations, accept lowercase ISO (pt1h)
OPT_6A_CTRL_C=no           # F47: Ctrl+C prints "Interrupted." on stderr and exits 130 instead of a traceback
```

## Phase 06b: true breaking changes

Each item is a separate commit. It runs only if it's set to `yes` (or a variant) and 06b is uncommented in QUEUE.

```
OPT_6B_MG_INHERITED=no     # F42: --mg drops roles inherited from parent MGs, as subscription mode does
OPT_6B_DEMO=no             # F41: no | honour (demo data plus forced dry-run) | reject (exit 2: "--demo cannot be combined with -r/--reason")
OPT_6B_BLANK_REASON=no     # F45: reject an empty or whitespace -r with exit 2
OPT_6B_STDERR_NAMES=no     # F46: stderr failure lines name the role and scope ("    <role> — <scope>: <error>")
```
