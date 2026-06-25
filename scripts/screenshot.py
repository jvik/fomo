#!/usr/bin/env python3
"""
Generate SVG screenshots of fomo screens in demo mode.

Usage:
    uv run python scripts/screenshot.py

Outputs SVGs to docs/screenshots/.  Commit and reference them in README.md:

    ![Scope screen](docs/screenshots/01-scope.svg)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import Input, SelectionList

# ── Output directory ──────────────────────────────────────────────────────────
OUT = Path(__file__).parent.parent / "docs" / "screenshots"

# ── Terminal size for all screenshots ─────────────────────────────────────────
# 120 × 36 renders well at typical GitHub README widths.
COLS, ROWS = 120, 36


def _sl(app, selector: str) -> SelectionList:
    """Query the current screen for a SelectionList (Textual 8.x: use app.screen)."""
    return app.screen.query_one(selector, SelectionList)


def _has_options(app, selector: str, min_count: int = 1) -> bool:
    try:
        return _sl(app, selector).option_count >= min_count
    except Exception:
        return False


async def _wait_for(pilot, condition_fn, *, steps: int = 80) -> None:
    """Pause (via pilot) until condition_fn() is truthy."""
    for _ in range(steps):
        await pilot.pause(0.05)
        try:
            if condition_fn():
                return
        except Exception:
            pass


async def take_scope_screen(out: Path) -> None:
    """Subscription selection screen with three subs selected."""
    from fomo.app import PimApp

    app = PimApp(demo_mode=True, dry_run=True)
    async with app.run_test(size=(COLS, ROWS)) as pilot:
        await _wait_for(pilot, lambda: _has_options(app, "#sub-list"))

        sl = _sl(app, "#sub-list")
        sl.focus()
        for i in range(min(3, sl.option_count)):
            sl.select(sl.get_option_at_index(i))

        await pilot.pause(0.1)
        app.save_screenshot(str(out / "01-scope.svg"))
        print(f"  ✓  {out / '01-scope.svg'}")


async def take_roles_screen(out: Path) -> None:
    """Role multiselect screen — roles loaded, a few selected."""
    from fomo.app import PimApp

    app = PimApp(demo_mode=True, dry_run=True)
    async with app.run_test(size=(COLS, ROWS)) as pilot:
        await _wait_for(pilot, lambda: _has_options(app, "#sub-list"))

        sl = _sl(app, "#sub-list")
        for i in range(sl.option_count):
            sl.select(sl.get_option_at_index(i))
        await pilot.pause(0.05)
        await pilot.press("enter")

        await _wait_for(pilot, lambda: _has_options(app, "#role-list"))

        _sl(app, "#role-list").focus()
        await pilot.pause(0.1)
        app.save_screenshot(str(out / "02-roles-empty.svg"))
        print(f"  ✓  {out / '02-roles-empty.svg'}")

        rl = _sl(app, "#role-list")
        for i in range(min(3, rl.option_count)):
            rl.select(rl.get_option_at_index(i))

        await pilot.pause(0.1)
        app.save_screenshot(str(out / "02-roles-selected.svg"))
        print(f"  ✓  {out / '02-roles-selected.svg'}")


async def take_activation_screen(out: Path) -> None:
    """Activation form — roles table + justification input filled in."""
    from fomo.app import PimApp

    app = PimApp(demo_mode=True, dry_run=True)
    async with app.run_test(size=(COLS, ROWS)) as pilot:
        await _wait_for(pilot, lambda: _has_options(app, "#sub-list"))

        sl = _sl(app, "#sub-list")
        for i in range(sl.option_count):
            sl.select(sl.get_option_at_index(i))
        await pilot.pause(0.05)
        await pilot.press("enter")

        await _wait_for(pilot, lambda: _has_options(app, "#role-list"))

        rl = _sl(app, "#role-list")
        for i in range(min(3, rl.option_count)):
            rl.select(rl.get_option_at_index(i))
        rl.focus()          # must focus the list, not the filter, for proceed to work
        await pilot.pause(0.05)
        await pilot.press("enter")

        await _wait_for(pilot, lambda: bool(app.screen.query("#justification")))
        await pilot.pause(0.1)

        app.screen.query_one("#justification", Input).value = (
            "Break-glass access — production incident"
        )

        await pilot.pause(0.1)

        # Click Activate and wait for the worker to finish (button label → "Done")
        await pilot.click("#btn-activate")
        await _wait_for(
            pilot,
            lambda: app.screen.query_one("#btn-back").label == "Done",
            steps=120,
        )
        await pilot.pause(0.15)
        app.save_screenshot(str(out / "03-activation-done.svg"))
        print(f"  ✓  {out / '03-activation-done.svg'}")



async def take_entra_screen(out: Path) -> None:
    """Entra role multiselect screen — roles loaded, a few selected."""
    from fomo.app import PimApp

    app = PimApp(demo_mode=True, dry_run=True)
    async with app.run_test(size=(COLS, ROWS)) as pilot:
        await _wait_for(pilot, lambda: _has_options(app, "#sub-list"))

        # Navigate to the Entra screen via the 'e' keybind on the scope screen
        await pilot.press("e")

        await _wait_for(
            pilot,
            lambda: _has_options(app, "#role-list"),
            steps=120,
        )

        rl = _sl(app, "#role-list")
        rl.focus()
        for i in range(min(2, rl.option_count)):
            rl.select(rl.get_option_at_index(i))

        await pilot.pause(0.1)
        app.save_screenshot(str(out / "04-entra.svg"))
        print(f"  ✓  {out / '04-entra.svg'}")


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Saving screenshots to {OUT}/\n")

    await take_scope_screen(OUT)
    await take_roles_screen(OUT)
    await take_activation_screen(OUT)
    await take_entra_screen(OUT)

    print("\nDone.  Reference in README.md:")
    for svg in sorted(OUT.glob("*.svg")):
        rel = svg.relative_to(Path(__file__).parent.parent)
        print(f"  ![{svg.stem}]({rel})")


if __name__ == "__main__":
    asyncio.run(main())
