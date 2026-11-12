# Phase 02a: chore, tooling, CI and lockfile

**Group:** 2
**Findings:** F24, F25, F26, F27, F30
**Contract:** none (no behaviour change)
**Decisions:** D1, D2

**Runner pre-step (already done when you start):**
- `uv add --dev <D1 tools>` (ruff, mypy or basedpyright)
- `uv add 'textual>=8.2,<9'` if D2 is `yes`
- GitHub Action SHAs written to `plan/logs/action-shas.txt`, one `owner/repo@tag SHA` per line (`UNRESOLVED` if the lookup failed)

## Steps

### 1. Untrack the generated version file (F25)

- `.gitignore`: replace `fzf_pim/_version.py` with `fomo/_version.py`.
- Run `git rm --cached fomo/_version.py`.
- `fomo/__init__.py` already falls back to `importlib.metadata`, so keep that path working.
- Convert the tab indentation in `fomo/__init__.py` to spaces.

### 2. Lockfile and Textual pin (F24, if D2 is `yes`)

- Remove `uv.lock` from `.gitignore` and `git add uv.lock pyproject.toml`.
- If D2 is `no`, revert nothing the runner did. Just note it in STATUS "Notes".

### 3. Replace private Textual imports (F24)

- `textual.widgets._selection_list.Selection` becomes `from textual.widgets.selection_list import Selection`, in `scope_screen.py` and `roles_screen.py`.
- `textual.widgets._option_list.OptionDoesNotExist` becomes `from textual.widgets.option_list import OptionDoesNotExist`.
- `textual.widgets._toggle_button.ToggleButton` was only used for `BUTTON_LEFT`/`BUTTON_RIGHT`. Replace it with local constants holding the same characters (read them from the installed Textual source first).

Verify each public path exists in the installed Textual before switching.

### 4. Ruff config in `pyproject.toml` (F26)

```toml
[tool.ruff]
target-version = "py311"
line-length = 120
[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "ARG"]
```

Add a `[tool.ruff.lint.per-file-ignores]` entry only where justified.

- Fix the findings without changing behaviour: unused imports (`scope_screen.py` `Text`, the unused `log` in `assignments_screen.py`), import order (`roles_screen.py` constants above imports), `print(f"✗")` becoming `print("✗")` with identical output, and existing `# noqa` comments that no longer apply.
- Then run `ruff format` as a **separate** commit. Contract tests prove the output is unchanged.

### 5. Type checker (D1 says which)

- **mypy:** add a `[tool.mypy]` section with `python_version = "3.11"`, `warn_unused_ignores = true` and `check_untyped_defs = false` for now. Fix real errors. Use narrowly scoped `# type: ignore[code]` only for Textual dynamic attributes (`self.app.dry_run` and similar). Prefer typing `self.app` via a `PimApp` cast helper.
- **basedpyright:** use the equivalent `[tool.basedpyright]` with `typeCheckingMode = "basic"`.

### 6. Package metadata (F30)

Add `readme = "README.md"` and `license` to `pyproject.toml`. Match `LICENSE`: check its header, it looks like GPL-3.0. Also add `[project.urls]` (Homepage and Issues on github.com/jvik/fomo), classifiers for Python 3.11–3.13 and Environment :: Console, and keywords. Don't change `description` strings inside `build_parser()`.

### 7. CI (F27), `.github/workflows/ci.yml`

- Top-level `permissions: contents: read`.
- `concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: true }`.
- A matrix over `python-version: ["3.11", "3.12", "3.13"]` using setup-uv's `python-version` input.
- Steps:
  - `uv sync --group dev` (add `--locked` when uv.lock is tracked)
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - the type checker
  - `uv run pytest -q`
  - `uv build`
  - `unzip -l dist/*.whl | grep share/man/man1/fomo.1`
- Pin every action to the SHA from `plan/logs/action-shas.txt`, with a trailing `# vN` comment. Keep the tag for any `UNRESOLVED` entry and add a line to STATUS "Notes".
- Keep the `if: github.actor != 'release-please[bot]'` guard and `fetch-depth: 0`, which hatch-vcs needs.

### 8. `release-please.yml`

- Pin the actions by SHA in the same way.
- **Don't change release behaviour.** Keep `release-type: simple` and the trigger. Add a STATUS "Notes" line saying that `release-type` is duplicated in the workflow and config and the owner should decide.

### 9. `justfile` and CONTRIBUTING.md

- Add `lint`, `fmt` and `typecheck` recipes.
- In CONTRIBUTING.md, mention `just lint` / `uv run ruff check .` and the type checker under "Running tests". Keep it short.

## Verify

- `.venv/bin/python -m pytest -q` passes.
- `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .` pass.
- The type checker passes on `fomo`.
- `git status` shows only intended changes.

## Commits

- `chore: stop tracking generated fomo/_version.py`
- `chore(deps): commit uv.lock and pin textual to 8.x` (only if D2)
- `refactor: use public Textual imports`
- `chore(lint): add ruff and <type checker> with fixes`
- `style: apply ruff format`
- `chore: add package metadata`
- `ci: test on Python 3.11-3.13, lint, type check and pin actions`

The last commit ticks `02a`.
