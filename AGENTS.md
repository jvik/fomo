# AGENTS.md

Guidelines for AI agents working in this repository.

## Project overview

**fomo** is a Textual TUI for activating Azure PIM eligible roles with multiselect.  
Azure (ARM) authentication is fully delegated to the active `az` CLI session.  
Entra role management uses Microsoft Graph via an OAuth 2.0 device code flow; the refresh token is cached at `~/.cache/fomo/graph_token.json` (mode `0600`).

## Tech stack

- Python ≥ 3.11, managed with **uv**
- [Textual](https://textual.textualize.io/) for the TUI
- Azure CLI (`az rest`) as the only Azure API transport
- Build backend: **hatchling**

## Key commands

```sh
uv run fomo            # run the app
uv run fomo --dry-run  # simulate activation without calling Azure APIs
uv run pytest             # run tests (if present)
```

## Project layout

```
fomo/
  __main__.py          # CLI entry point (argparse → PimApp)
  app.py               # PimApp(App) root, pushes ScopeScreen on mount
  app.tcss             # Textual CSS
  azure.py             # All Azure API calls via `az rest`; dataclasses: Subscription, EligibleRole
  screens/
    scope_screen.py    # Step 1 — pick subscription scope
    roles_screen.py    # Step 2 — multiselect eligible roles
    activation_screen.py  # Step 3 — justification form + per-role progress table
```

## Conventions

- All Azure I/O lives in `azure.py`; screens are UI-only.
- Screens communicate by passing data as constructor args when pushing the next screen.
- `@work` (Textual worker) for async/background tasks inside screens.
- No external HTTP libraries — use `subprocess` + `az rest` only.
- `from __future__ import annotations` at the top of every module.

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
