# fomo improvement plan

This folder turns the audit in [REPORT.md](REPORT.md) into phases that run unattended. You choose what runs and review each finished group. A script does everything in between: it starts Claude, checks the result, retries, and waits out usage limits.

| File | What it is |
|---|---|
| [REPORT.md](REPORT.md) | The audit: findings F01–F47, CLI characterization matrix, doc mismatches, UX proposals |
| [RULES.md](RULES.md) | Hard constraints every phase must follow. The runner appends this file to Claude's system prompt |
| [DECISIONS.md](DECISIONS.md) | Your choices: dev dependencies, opt-in items, contract changes. **Edit before running** |
| [QUEUE](QUEUE) | Which phases run, in what order, in which group. Comment a line out to skip it |
| [STATUS.md](STATUS.md) | Checklist. Each phase ticks itself in its last commit, and blockers are recorded here |
| [phases/](phases/) | One self-contained brief per phase |
| [run.sh](run.sh) | The runner |
| [bin/az](bin/az) | A stub `az` that always fails. The runner puts it first on `PATH`, so nothing can reach Azure |

## Phases

| Group | Phases | Kind |
|---|---|---|
| 1 | 01 | Characterization tests (CLI contract and Pilot smoke tests). Must land first |
| 2 | 02a 02b 02c 02d | Tooling, refactors and docs. No behaviour change |
| 3 | 03a–03f | Bug fixes. No CLI contract change |
| 4 | 04a–04g, 04z | TUI UX and UI. 04z regenerates screenshots and is run by the script alone |
| 5 | 05 | Additive CLI flags. **Opt-in**: commented out in QUEUE |
| 6 | 06a 06b | CLI contract changes. **Opt-in per item** in DECISIONS.md, and commented out in QUEUE |

## Quick start

You need bash 4 or newer, `uv`, `python3` and the `claude` CLI, logged in. The runner's own `uv` calls run in your shell and need PyPI access. Claude's tool calls run inside your normal Claude Code sandbox and permission settings.

```sh
git switch -c audit/improvements           # never run the plan on main
$EDITOR plan/DECISIONS.md plan/QUEUE       # make your choices
git add plan && git commit -m "docs(plan): add audit report and phased plan"

plan/run.sh --dry                          # show what would run next
plan/run.sh                                # run the next pending group, then stop for review
```

### Reviewing a group

After each group the runner stops and tags the commit `plan-group-<N>-done`. Phase 01 also gets the tag `plan-01-done`. To review:

```sh
git log --stat plan-group-1-done~..HEAD    # or: git log -p <previous tag>..HEAD
uv run pytest -q && uv run fomo --demo     # try it yourself
plan/run.sh                                # continue with the next group
```

If you don't like a phase, revert its commits, untick it in STATUS.md, adjust DECISIONS.md or the phase brief, and rerun it with `plan/run.sh --phase <id>`.

### Running unattended

```sh
tmux new -d -s fomo-plan 'plan/run.sh --until 4'   # groups 1–4, no review stops
tail -f plan/logs/run.log                          # watch from anywhere
```

- **Usage limits:** when a run fails with a usage or rate limit, the runner sleeps. It sleeps until the reset time if the message contains one, otherwise for `FOMO_PLAN_LIMIT_WAIT` (default 30 min). Then it reruns the same phase, which resumes from its last commit. That repeats up to `FOMO_PLAN_MAX_LIMIT_WAITS` times. Limit detection is heuristic; see `hit_limit` in run.sh.
- **Notifications:** with `notify-send` installed you get a desktop notification when the runner stops, blocks or sleeps.

### What the runner does for each phase

1. Switches to `audit/improvements` if you're on main, and refuses to run on a dirty tree.
2. Runs `uv sync --group dev` in **your** shell, plus any phase pre-step that needs the network:
   - `uv add --dev …` for the dependencies you approved
   - resolving GitHub Action commit SHAs
   - resolving the tiering repo SHA
3. Runs `claude -p` headless with:
   - `--permission-mode acceptEdits --permission-prompts none`, so nothing ever waits for a prompt
   - an allowlist of Bash commands (tests, ruff, mypy, git add/commit/diff/log)
   - a denylist: `az`, `git push`/`reset`/`rebase`/`switch`/`checkout`, `uv add/sync/lock`, `pip`, `curl`, `wget`, WebFetch, WebSearch, subagents
   - `plan/RULES.md` appended to the system prompt
4. Verifies the phase independently. Every check must pass:
   - `pytest`
   - ruff and mypy, once 02a has added them
   - `uv build`
   - the wheel contains the man page, and after 02d the man EXAMPLES render in full
   - a clean tree
   - the phase is ticked in STATUS.md
   - `tests/test_cli_contract.py` is byte-identical to `plan-01-done`, for every phase except 06a/06b
5. If verification fails, Claude gets one fix-up run with the failure log (`FOMO_PLAN_MAX_FIX`). If it still fails, the runner stops.
6. If Claude reports `PHASE <id>: BLOCKED — …` (a missing decision or an impossible step), the runner stops. Read the "Blocked" section of STATUS.md.

The runner never pushes. When a group looks good, push the branch and open a PR yourself:

```sh
git push -u origin audit/improvements
gh pr create --fill
```

To get one PR per group instead, branch from the group tags.

### Knobs

| Variable | Default | Meaning |
|---|---|---|
| `FOMO_PLAN_BRANCH` | `audit/improvements` | Branch the plan runs on |
| `FOMO_PLAN_MODEL` | your default | Model for every phase. A QUEUE line's 4th column overrides it per phase |
| `FOMO_PLAN_EFFORT` | your default | Effort for every phase. A QUEUE line's 5th column overrides it |
| `FOMO_PLAN_BUDGET_USD` | none | `--max-budget-usd` per Claude call |
| `FOMO_PLAN_LIMIT_WAIT` | `1800` | Seconds to sleep after a usage limit when no reset time is known |
| `FOMO_PLAN_MAX_LIMIT_WAITS` | `24` | Give up after this many limit sleeps in one phase |
| `FOMO_PLAN_MAX_FIX` | `1` | Fix-up runs after a failed verification |

Logs go to `plan/logs/`, which git ignores:
- `run.log`
- each prompt
- Claude's JSON result, its stderr and exit code for every call
- `gate-<id>.log` from every verification

## Alternative: a scheduled cloud routine

If you'd rather not keep a machine running, push the branch, including `plan/`, to GitHub. Then create a routine in Claude Code with `/schedule`, for example every 6 hours, with a prompt like this:

> In jvik/fomo on branch `audit/improvements`: read `plan/README.md`, `plan/RULES.md` and `plan/DECISIONS.md`. Take the first phase in `plan/QUEUE` that isn't commented out and isn't ticked in `plan/STATUS.md`, and run that phase only, following its brief in `plan/phases/`. Before you tick it, run `uv run pytest -q` and `uv build`, and check that `tests/test_cli_contract.py` is unchanged since tag `plan-01-done` (except in phases 06a/06b). Commit, push the branch, and stop. If blocked, record the blocker in STATUS.md, commit, push and stop.

Every run gets a fresh session, so usage windows take care of themselves. It's less guarded than `run.sh` in three ways:
- the routine verifies its own work instead of a separate script doing it
- there's no `az` stub
- the pre-steps that need the network (dependency installs, SHA lookups) must happen inside the routine

Confirm that the cloud environment has `uv` and Python 3.11 or newer.
