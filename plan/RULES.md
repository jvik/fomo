# Rules for every phase

You're running one phase of the fomo improvement plan, **unattended**. Nobody will answer questions. These rules override anything in a phase brief that seems to contradict them.

## Hard constraints

1. **No CLI regressions.** The non-interactive CLI is a frozen public contract:
   - every flag in short and long form (`-r/--reason`, `-t/--time`, `--dry-run`, `--entra`, `--mg`, `--demo`, `--log`), its default (`PT1H`) and what the positional arguments mean in each mode
   - exit codes: 0 for success or "already active", 1 for runtime failure, 2 for argparse usage errors
   - which messages go to stdout and which to stderr, and their exact wording, including `…`, `—`, `✓`, `✗` and spacing
   - matching rules: an exact role name wins, otherwise substring matching (all matches are activated). Subscriptions match by name substring or exact ID. A management group matching several groups is an error. Roles inherited from parent MGs are dropped in subscription mode. Already-active roles are skipped
   - the name and behaviour of `build_parser()`, which `hatch_build.py` calls at build time. `fomo/__main__.py` **must keep stdlib-only top-level imports**, because the hook executes that file standalone in the isolated build environment

   `tests/test_cli_contract.py` is the executable contract. After phase 01 it may only change in phases 06a/06b, and only in the rows that an approved item changes. The runner checks this byte for byte.
2. **Never call real Azure write APIs, or Azure at all.** The `az` on `PATH` is a stub that fails on purpose. Test against fakes at the `fomo.azure` function boundary or at `subprocess`. Use `--demo` data for the TUI. No network: don't try to download anything.
3. **Follow the AGENTS.md conventions:**
   - All Azure I/O stays in `fomo/azure.py`. The existing `urllib` calls to Graph and the token endpoints are a known, documented exception; don't add new HTTP code.
   - No HTTP libraries and no new runtime dependencies.
   - `from __future__ import annotations` comes first in every module (after the docstring).
   - Conventional Commits.
4. **The code is the source of truth, not the docs.** Don't change behaviour to match the docs unless your phase brief says so.

## Environment

- The runner already ran `uv sync --group dev` and any network pre-step. **Don't run `uv sync`, `uv add`, `uv lock` or `pip`**; they're blocked.
- Run tools straight from the venv:
  - `.venv/bin/python -m pytest -q`
  - `.venv/bin/ruff …` and `.venv/bin/mypy …`, once phase 02a adds them
- `uv run` may fail inside the sandbox because of its cache. Prefer `.venv/bin/...`.
- Don't run `uv build`. The runner builds the package and checks the man page after you finish.
- Drive the TUI only through Textual's `App.run_test()` and Pilot, in tests or in throwaway scripts. Use `demo_mode=True`, or fakes plus `dry_run=True`. Never run the interactive app.
- Throwaway scripts and screenshots go in `plan/logs/scratch/`, which git ignores. Never put them anywhere else in the repo.

## Git

- You're on the plan branch. **Never** push, switch branches, reset, rebase or rewrite history.
- Stage explicit paths (`git add fomo/x.py tests/test_x.py`), never `git add -A` or `git add .`.
- Never commit modifications to `fomo/_version.py` (a generated file) or anything under `plan/logs/`. Phase 02a removes `_version.py` from the index; that deletion is the only exception.
- Use the Conventional Commit messages from your brief: one concern per commit, with a body that says why.
- Tick your phase (`- [x] <id>`) in `plan/STATUS.md` as part of your **last** commit. Leave the tree clean.

## Quality bar

- Every behaviour change ships with a test that fails before the change and passes after it. Characterization tests describe current behaviour and must not be "fixed" to match the docs.
- Tests stay hermetic. The autouse kill switch in `tests/conftest.py` (blocking `subprocess.run`, `urlopen` and `webbrowser.open`) must stay autouse. Keep the suite under about 30 s.
- Keep these widget IDs stable, because tests and `scripts/screenshot.py` use them: `#sub-list`, `#filter`, `#role-list`, `#entra-role-list`, `#entra-filter`, `#justification`, `#duration`, `#btn-activate`, `#btn-back`, `#azure-table`, `#entra-table`, `#scope-tabs`. If a brief requires changing one, update `scripts/screenshot.py` and the tests in the same commit.
- From phase 03a on, put external text (Azure names, error messages, tiering data) into markup only through the escaping helper 03a introduces.
- Keep changes focused on your phase. If you notice something out of scope, add one line under "## Notes" in `plan/STATUS.md` instead of fixing it.

## When stuck

Don't guess at product decisions. If your brief depends on a decision that `plan/DECISIONS.md` doesn't make, or a step is impossible:
1. Add one line under "## Blocked" in `plan/STATUS.md` (`- <id>: <reason>`).
2. Commit that line.
3. Stop.

End every run with exactly one line: `PHASE <id>: DONE` or `PHASE <id>: BLOCKED — <reason>`.
