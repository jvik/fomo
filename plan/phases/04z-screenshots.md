# Phase 04z: docs, regenerate screenshots (runner only)

`plan/run.sh` does this phase itself, without Claude, because it needs the network for tier badges:
1. runs `uv run python scripts/screenshot.py`
2. ticks `04z` in STATUS.md
3. commits `docs/screenshots/` as `docs: regenerate screenshots`

**Prerequisite:** the 04x phases keep `scripts/screenshot.py` working (stable widget IDs, see RULES.md). If it fails, the runner stops. Fix the script in a follow-up run with `plan/run.sh --phase <the phase that broke it>`, or by hand, then rerun `plan/run.sh --phase 04z`.

To run it manually: `just screenshots && git add docs/screenshots && git commit -m "docs: regenerate screenshots"`, then tick 04z.
