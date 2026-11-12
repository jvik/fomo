# AGENTS.md

Guidelines for AI agents working in this repository.

## Project overview

**fomo** is a Textual TUI for activating Azure PIM eligible roles with multiselect.  
Azure (ARM) authentication is fully delegated to the active `az` CLI session.  
Entra role management uses Microsoft Graph via an OAuth 2.0 device code flow; the refresh token is cached at `~/.cache/fomo/graph_token.json` (mode `0600`).

## Tech stack

- Python ≥ 3.11, managed with **uv**
- [Textual](https://textual.textualize.io/) for the TUI
- Azure CLI (`az rest`) as the Azure Resource Manager transport; stdlib `urllib` for Microsoft Graph, the OAuth token endpoint and tier data (see Conventions)
- Build backend: **hatchling**

## Key commands

```sh
uv sync --group dev        # install runtime + dev dependencies (pytest, ruff, mypy)
uv run fomo                # run the app
uv run fomo --dry-run      # real data, simulated activation (no write calls)
uv run fomo --demo         # TUI with built-in demo data, no Azure account needed
uv run pytest -q           # run the test suite
uv run ruff check .        # lint
uv run ruff format --check .  # check formatting (`uv run ruff format .` to fix)
uv run mypy fomo           # type check
```

The same checks are available as `just test`, `just lint` and `just typecheck`, and CI runs all of them.

## Project layout

```
fomo/
  __main__.py          # CLI entry point: build_parser() and the non-interactive (-r) mode, else PimApp
  app.py               # PimApp(App) root, pushes ScopeScreen on mount; AuthErrorModal
  app.tcss             # Textual CSS
  azure.py             # All Azure I/O: `az rest` for ARM, urllib for Graph/OAuth; dataclasses
  backend.py           # Backend: AzureBackend (real APIs) or DemoBackend (--demo) for the TUI
  demo.py              # Dummy data for --demo mode and screenshots
  tiering.py           # Blast-radius tier data (emiliensocchi/azure-tiering), fetched and cached
  timefmt.py           # Pure helpers for end times: "47m left", "14:32 (47m left)", dates
  widgets.py           # Custom Textual widgets (FomoSelectionList)
  screens/
    scope_screen.py    # Step 1 — Azure tab (subscriptions) and Entra tab (Entra roles)
    roles_screen.py    # Step 2 — multiselect eligible Azure roles
    activation_screen.py  # Step 3 — Azure justification form + per-role progress table
    entra_screen.py    # Entra activation screen
    assignments_screen.py  # Currently active Azure and Entra assignments (`i`)
    _activation_base.py    # Shared logic for the Azure and Entra activation screens
    _common.py         # Shared screen helpers (safe_markup, Vim navigation, device-code markup, error wrapping)
hatch_build.py         # Hatchling build hook: generates man/fomo.1 from build_parser()
man/fomo.1.include     # Hand-written man page sections (argparse-manpage include format)
scripts/screenshot.py  # Regenerates docs/screenshots/*.svg in demo mode
tests/                 # pytest suite; conftest.py has the hermetic kill switch and fake Azure
```

## Conventions

- All Azure I/O lives in `azure.py`; screens are UI-only.
- Screens communicate by passing data as constructor args when pushing the next screen.
- `@work` (Textual worker) for async/background tasks inside screens.
- No external HTTP libraries — use `subprocess` + `az rest` for Azure Resource Manager.
  Exception: Microsoft Graph (Entra PIM) and the OAuth token endpoint are called with stdlib `urllib`, because `az`'s first-party app lacks the PIM Graph scope. Tier data is fetched with `urllib` from GitHub (`tiering.py`). Don't add other HTTP code.
- `from __future__ import annotations` at the top of every module.
- External text (Azure names and IDs, error messages, tiering data) never goes into Textual markup through an f-string: use `safe_markup("[bold]$name[/bold]", name=...)` from `screens/_common.py`, `Content(text)` for unstyled text, `rich.text.Text(text)` for `DataTable` cells and `RichLog`, and `notify(..., markup=False)`.

## CLI contract

The non-interactive CLI (`fomo … -r REASON`) is a public contract used by scripts.

- `tests/test_cli_contract.py` is frozen: it pins flags, defaults, exit codes, stdout/stderr wording and matching rules. Don't edit it to make a change pass.
- `fomo/__main__.py` keeps stdlib-only top-level imports, because `hatch_build.py` executes it standalone in the isolated build environment to call `build_parser()`. Import `fomo.azure`, Textual and friends inside functions.
- Any change to that behaviour needs an explicit breaking-change commit (`feat!:`/`fix!:` with a `BREAKING CHANGE:` footer) that updates the affected contract rows, README and man page.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <short description>
```

| Type       | When to use                              |
| ---------- | ---------------------------------------- |
| `feat`     | New user-facing feature                  |
| `fix`      | Bug fix                                  |
| `chore`    | Maintenance, dependency bumps, tooling   |
| `docs`     | Documentation only                       |
| `refactor` | Code change with no behaviour change     |
| `test`     | Adding or updating tests                 |
| `style`    | Formatting, whitespace (no logic change) |

Breaking changes: append `!` after the type (`feat!:`) and add a `BREAKING CHANGE:` footer.  
Releases are driven by release-please; `feat` bumps the minor version, `fix` bumps the patch, breaking changes bump the major.

## Do / don't

- **Do** keep Azure logic in `azure.py`, not in screens.
- **Do** use `--dry-run` when testing activation flows to avoid real API calls.
- **Don't** add credentials, tokens, or secrets anywhere in the codebase.
- **Don't** introduce new dependencies without updating `pyproject.toml`.
