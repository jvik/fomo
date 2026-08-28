# Contributing

## Setup

```sh
git clone https://github.com/jvik/fomo.git
cd fomo
uv sync --group dev
```

## Running the app

```sh
uv run fomo              # full app — requires `az login` and PIM-eligible roles
uv run fomo --dry-run    # simulates activation without calling Azure APIs
uv run fomo --demo       # loads dummy data, no Azure account needed
```

## Running tests

```sh
uv run pytest
```

## Code conventions

- `from __future__ import annotations` at the top of every module.
- All Azure API calls live in `azure.py`; screens are UI-only.
- No new runtime dependencies without updating `pyproject.toml`.
- No credentials, tokens, or secrets in the codebase.

See [AGENTS.md](AGENTS.md) for a full project overview and architecture notes.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <short description>
```

| Type       | When to use                            |
| ---------- | -------------------------------------- |
| `feat`     | New user-facing feature                |
| `fix`      | Bug fix                                |
| `chore`    | Maintenance, dependency bumps, tooling |
| `docs`     | Documentation only                     |
| `refactor` | Code change with no behaviour change   |
| `test`     | Adding or updating tests               |
| `style`    | Formatting, whitespace only            |

Breaking changes: append `!` after the type (`feat!:`) and include a `BREAKING CHANGE:` footer in the commit body.

Commits drive automated releases via [release-please](https://github.com/googleapis/release-please): `feat` bumps the minor version, `fix` bumps the patch, breaking changes bump the major. Do not manually update the version.

## Opening a PR

- Target `main`.
- Keep PRs focused — one concern per PR.
- CI must pass (build + pytest) before merging.
