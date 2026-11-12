Run the whole fomo improvement plan in `plan/` from start to finish in this session, without stopping for review between groups. You are the orchestrator and act as "the runner" that `plan/README.md` and `plan/RULES.md` refer to. A fresh subagent does each phase. You do setup, the network pre-steps, independent verification, fix-up loops, tags and the final report. `plan/run.sh` is not used.

## Keep your own context small

- Read these in full once: `plan/README.md`, `plan/RULES.md`, `plan/DECISIONS.md`, `plan/QUEUE` and `plan/STATUS.md`. Don't read `plan/REPORT.md`, the phase briefs (beyond their first ~15 header lines) or source files. The subagents read those.
- Don't read diffs. Send verification output to `plan/logs/gate-<id>.log` and read only its tail when something fails.
- Ask subagents for a short final report (10 lines at most), not a narrative.

## Setup (once; skip any step that's already done)

1. If you're on `main`, switch to `audit/improvements`, creating it from `main` if it doesn't exist. Never run the plan on `main`.
2. If `plan/` isn't tracked yet, commit it as `docs(plan): add audit report and phased plan`. Stage `plan/` explicitly. `plan/.gitignore` keeps `plan/logs/` out. Never stage `fomo/_version.py`.
3. `mkdir -p plan/logs/scratch`, then `uv sync --group dev`.

## Which phases

Run, in QUEUE order, every uncommented line in `plan/QUEUE` whose phase isn't ticked (`- [x] <id>`) in `plan/STATUS.md`. Run them one at a time, never in parallel, because they share one branch and one tree. This prompt is idempotent: if the session is cut off (usage limit, crash), running it again resumes from STATUS.md and git history.

## For each phase

**1. Pre-steps (you, because they need the network). Then `uv sync --group dev`.**
- `01`: if `D3_SNAPSHOT_TESTS=yes`, run `uv add --dev pytest-textual-snapshot`.
- `02a`: `uv add --dev <D1_DEV_DEPS, comma-separated, unless none>`. If `D2_LOCK_AND_PIN=yes`, also run `uv add 'textual>=8.2,<9'`. Then resolve commit SHAs with `git ls-remote --tags https://github.com/<repo>` (prefer the peeled `^{}` SHA) for `actions/checkout@v4`, `astral-sh/setup-uv@v6`, `googleapis/release-please-action@v4`, `actions/upload-artifact@v4` and `softprops/action-gh-release@v2`. Write them as `<action>@<tag> <sha>` lines to `plan/logs/action-shas.txt`.
- `03b`: if `D5_TIERING=pin-sha`, write the `main` SHA of `https://github.com/emiliensocchi/azure-tiering` (from `git ls-remote`) to `plan/logs/tiering-sha.txt`.

**2. Runner-only phase `04z`: do it yourself, with no subagent.** Run `uv run python scripts/screenshot.py`, tick `04z` in STATUS.md, then `git add docs/screenshots plan/STATUS.md` and commit as `docs: regenerate screenshots`. If the script fails, have a subagent fix `scripts/screenshot.py` or the widget ID that broke it (commit `fix(scripts): …`), then retry once.

**3. Delegate.** Spawn one fresh `general-purpose` subagent in the foreground and wait for it. Its prompt:

> You're running phase `<id>` of the fomo improvement plan in /home/jorgen/repos/fomo, unattended. Nobody will answer questions.
> 1. Read `plan/RULES.md`. Its rules are binding and override anything in the brief. "The runner" means the orchestrator that started you: it has already run `uv sync` and any network pre-step, and its outputs are in `plan/logs/` (`action-shas.txt`, `tiering-sha.txt`). Then read `plan/DECISIONS.md` and `plan/<brief>`. Read only the parts of `plan/REPORT.md` that the brief cites.
> 2. Run `git status` and `git log --oneline -25`. An earlier attempt may have stopped part-way: keep its committed work and continue from there.
> 3. Do every step of the brief in order, and verify as it says. Use `.venv/bin/python -m pytest -q`, plus `.venv/bin/ruff` and `.venv/bin/mypy` once they exist.
> 4. Forbidden: running `az` or the interactive app, `git push/switch/checkout/reset/rebase/tag`, `git add -A` or `git add .`, `uv add/sync/lock/build`, `pip`, `curl`, `wget`, any web access, and spawning agents. Throwaway files go only in `plan/logs/scratch/`.
> 5. Commit with the brief's Conventional Commit messages. Tick `- [x] <id>` in `plan/STATUS.md` in your last commit, and leave the tree clean (`fomo/_version.py` may stay modified, uncommitted).
> 6. If a step is impossible or needs a decision DECISIONS.md doesn't make, don't guess. Add `- <id>: <reason>` under `## Blocked` in STATUS.md, commit it, and stop.
>
> Reply with at most 10 lines: the commits you made, anything notable you added under `## Notes`, then exactly one final line, `PHASE <id>: DONE` or `PHASE <id>: BLOCKED — <reason>`.

**4. Verify it yourself, independently.** Don't trust the subagent's report. Run every check below with `PATH="$PWD/plan/bin:$PATH"` (`plan/bin/az` is a stub that always fails) and append the output to `plan/logs/gate-<id>.log`. If `uv.lock` is tracked, use `uv run --frozen`. All of these must pass:
- `uv run pytest -q`
- once `02a` is ticked, and only for the tools that are installed: `ruff check .`, `ruff format --check .`, `mypy fomo` (or `basedpyright fomo`)
- `uv build`, and the newest `dist/*.whl` contains `share/man/man1/fomo.1` (`unzip -l`)
- once `02d` is ticked: `MANWIDTH=140 man -l man/fomo.1 | grep -q 'Break-glass access'`
- a clean tree: no tracked changes except `fomo/_version.py`, and no untracked files in `fomo tests scripts docs man .github plan`, apart from `plan/logs/`
- `- [x] <id>` is ticked in STATUS.md
- for every phase except `01` and `06*`: `git diff --quiet plan-01-done -- tests/test_cli_contract.py`
- `git log --name-only` for the phase's commits shows no `plan/logs/` files and no `fomo/_version.py` (except the one deletion in `02a`)

**5. Fix-up loop.** If verification fails, send the tail of the gate log (at most 150 lines) to **the same subagent** with SendMessage. If SendMessage isn't loaded, load it with ToolSearch `select:SendMessage`. Tell the subagent to fix the cause without weakening, skipping or deleting tests and without touching `tests/test_cli_contract.py` (except in 01/06a/06b), to commit, and to end with the status line again. Allow at most 2 fix-ups, then treat the phase as blocked.

**6. Tags.** When `01` passes, run `git tag -f plan-01-done`. When the last queued phase of a group passes, run `git tag -f plan-group-<N>-done`.

## When a phase is blocked

- If `01` is blocked, stop everything; nothing else is safe without the contract tests.
- Otherwise make sure the blocker is recorded and committed in STATUS.md, then continue with the remaining phases. Skip a later phase whose brief header says it depends on a blocked phase, and record it under `## Blocked` as `- <id>: skipped, depends on <blocked id>`.

## Hard limits for you too

Never push, never call `az` or Azure, never edit phase work yourself (apart from 04z and STATUS.md bookkeeping), never commit `fomo/_version.py`, and don't change DECISIONS.md or QUEUE.

## When finished

Report in at most 25 lines:
- a table of the phases with status (done, blocked or skipped) and their number of commits
- everything under `## Blocked` and `## Notes` in STATUS.md
- the range to review: `git log --oneline main..audit/improvements`
- the next commands: `uv run pytest -q`, `uv run fomo --demo`, `git push -u origin audit/improvements && gh pr create --fill`
