"""Recent activations (F38): the state file, and one key to activate again.

The store tests call ``fomo.state`` directly; the autouse fixture in
``conftest.py`` points ``XDG_STATE_HOME`` at ``tmp_path``, so nothing here
touches the real state directory.  The Pilot tests run against the fake
Azure boundary with dry run off, so the fake records real (fake)
activations.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from textual.pilot import Pilot
from textual.widgets import Input, OptionList, Select, TabbedContent

from fomo import app as app_module
from fomo import state, timefmt
from fomo.app import PimApp
from fomo.screens.activation_screen import ActivationScreen
from fomo.screens.entra_screen import EntraActivationScreen
from fomo.screens.roles_screen import RolesScreen
from fomo.screens.scope_screen import ScopeScreen, recent_prompt
from fomo.widgets import FomoSelectionList
from tests.test_tui_markup import _toasts
from tests.test_tui_smoke import SIZE, _status_cells, wait_for


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def _azure(role: str, reason: str = "INC-1", duration: str = "PT1H") -> state.Recent:
    return state.Recent(
        kind="azure",
        targets=((role, "/subscriptions/s1"),),
        labels=(f"{role} · Contoso Production",),
        justification=reason,
        duration=duration,
        subscriptions=("s1",),
    )


# ---------------------------------------------------------------------------
# The state file
# ---------------------------------------------------------------------------


def test_state_file_is_private_newest_first_and_one_entry_per_role_set(tmp_path: Path) -> None:
    path = Path(state.state_path())
    assert path == tmp_path / "state" / "fomo" / "state.json"
    store = state.open_store(demo_mode=False)
    assert isinstance(store, state.FileRecentStore)
    for n in range(7):
        store.add(_azure(f"Role {n}"))
    # The same role set again (IDs in another case): replaces its entry and moves it to the front.
    store.add(_azure("ROLE 3", reason="again", duration="PT2H"))

    assert _mode(path) == 0o600
    assert _mode(path.parent) == 0o700
    entries = state.FileRecentStore(str(path)).entries()
    assert [entry.targets[0][0] for entry in entries] == ["ROLE 3", "Role 6", "Role 5", "Role 4", "Role 2"]
    assert (entries[0].justification, entries[0].duration, entries[0].subscriptions) == ("again", "PT2H", ("s1",))
    assert json.loads(path.read_text())["version"] == 1


def test_a_corrupt_or_unreadable_state_file_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "state" / "fomo" / "state.json"
    path.parent.mkdir(parents=True)
    for content in (b"{not json", b"\xff\xfe", b"[1, 2]", b'{"version": 2, "recent": []}', b'{"version": 1}'):
        path.write_bytes(content)
        assert state.FileRecentStore(str(path)).entries() == [], content

    # Malformed entries are skipped, the others kept.
    good = _azure("Reader").to_json()
    no_subs = {**good, "subscriptions": []}
    path.write_text(json.dumps({"version": 1, "recent": ["x", {"kind": "azure", "targets": []}, no_subs, good]}))
    assert [entry.targets for entry in state.FileRecentStore(str(path)).entries()] == [
        (("Reader", "/subscriptions/s1"),)
    ]

    # The app starts with a corrupt file, and the next activation replaces it.
    path.write_text("{oops")
    app = PimApp(dry_run=True)
    assert app.recents.entries() == []
    app.recents.add(_azure("Owner"))
    assert json.loads(path.read_text())["recent"][0]["targets"] == [["Owner", "/subscriptions/s1"]]

    # A directory where the file should be: nothing to read, and saving only logs.
    path.unlink()
    path.mkdir()
    store = state.FileRecentStore(str(path))
    assert store.entries() == []
    store.add(_azure("Owner"))
    assert path.is_dir()


def test_demo_mode_and_fomo_no_state_keep_recents_for_the_session_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _azure("Reader")
    demo_app = PimApp(demo_mode=True, dry_run=True)
    assert type(demo_app.recents) is state.RecentStore
    demo_app.recents.add(entry)
    assert demo_app.recents.entries() == [entry]

    monkeypatch.setenv("FOMO_NO_STATE", "1")
    app = PimApp()
    assert type(app.recents) is state.RecentStore
    app.recents.add(entry)
    assert not (tmp_path / "state").exists()

    monkeypatch.setenv("FOMO_NO_STATE", "0")
    assert isinstance(state.open_store(demo_mode=False), state.FileRecentStore)


def test_state_path_follows_xdg_state_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", "relative/dir")  # not absolute: ignored, as the spec says
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert state.state_path() == str(tmp_path / "home" / ".local" / "state" / "fomo" / "state.json")


def test_recent_rows_and_target_matching() -> None:
    assert [timefmt.format_duration(d) for d in ("PT1H", "PT30M", "PT1H30M", "P1D", "PT")] == [
        "1h",
        "30m",
        "1h 30m",
        "P1D",
        "PT",
    ]
    entry = state.Recent(
        kind="azure",
        targets=(("kv", "/subscriptions/s1"), ("r", "/subscriptions/s1")),
        labels=("[red]Key Vault[/red] · Prod",),  # external text: shown as is; a missing label is made up
        justification="INC-4711 the long story of a production hotfix",
        duration="PT2H",
        subscriptions=("s1",),
    )
    assert recent_prompt(1, entry).plain.splitlines() == [
        "1  [red]Key Vault[/red] · Prod",
        "   r · /subscriptions/s1",
        '   2h · "INC-4711 the long story of a…"',
    ]

    match = state.match_targets(entry, [], state.azure_target)
    assert (match.ready, match.complete) == ((), False)
    assert match.problems() == (
        "Not eligible or not loaded: [red]Key Vault[/red] · Prod, r · /subscriptions/s1\nNothing left to activate."
    )


# ---------------------------------------------------------------------------
# One key to activate again
# ---------------------------------------------------------------------------


@pytest.fixture
def make_live_app(monkeypatch: pytest.MonkeyPatch, fake_azure: Any) -> Callable[[], PimApp]:
    """PimApp on the fake Azure boundary with dry run off, animations off."""
    monkeypatch.setattr(app_module, "_system_is_dark", lambda: True)
    monkeypatch.setattr(PimApp, "_watch_color_scheme", lambda self: None)

    def _make() -> PimApp:
        app = PimApp(demo_mode=False, dry_run=False)
        app.animation_level = "none"
        return app

    return _make


def _recent_tab_shown(app: PimApp) -> bool:
    tabs = app.screen.query_one("#scope-tabs", TabbedContent)
    return bool(tabs.query("#tab-recent")) and tabs.get_tab("tab-recent").display


async def _wait_done(pilot: Pilot) -> None:
    await wait_for(pilot, lambda: str(pilot.app.screen.query_one("#btn-back").label) == "Done")


def test_an_activation_is_remembered_and_1_then_enter_activates_it_again(make_live_app, fake_azure) -> None:
    async def first_run() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))
            scope = app.screen
            assert not _recent_tab_shown(app)  # nothing activated yet

            roles = RolesScreen(["s1"], {"s1": "Contoso Production"})
            await app.push_screen(roles)
            role_list = roles.query_one("#role-list", FomoSelectionList)
            await wait_for(pilot, lambda: role_list.option_count > 0)
            role_list.select(next(i for i, r in enumerate(roles.all_roles) if r.role_name == "Key Vault Reader"))
            role_list.focus()
            await pilot.press("enter")
            await wait_for(pilot, lambda: isinstance(app.screen, ActivationScreen))
            app.screen.query_one("#justification", Input).value = "INC-1 hotfix"
            app.screen.query_one("#duration", Select).value = "PT2H"
            await pilot.click("#btn-activate")
            await _wait_done(pilot)

            path = Path(state.state_path())
            assert _mode(path) == 0o600 and _mode(path.parent) == 0o700
            saved = json.loads(path.read_text())["recent"]
            assert len(saved) == 1
            assert {k: saved[0][k] for k in ("kind", "subscriptions", "targets", "justification", "duration")} == {
                "kind": "azure",
                "subscriptions": ["s1"],
                "targets": [["Key Vault Reader", "/subscriptions/s1"]],
                "justification": "INC-1 hotfix",
                "duration": "PT2H",
            }

            # Done: back on the scope screen, which now shows the Recent tab.
            await pilot.press("enter")
            await wait_for(pilot, lambda: app.screen is scope and _recent_tab_shown(app))
            assert scope.query_one("#recent-list", OptionList).option_count == 1

    async def second_run() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE) as pilot:
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen) and _recent_tab_shown(app))
            await pilot.press("1")
            await wait_for(pilot, lambda: isinstance(app.screen, ActivationScreen))
            screen = app.screen
            reason = screen.query_one("#justification", Input)
            assert reason.value == "INC-1 hotfix"
            assert screen.query_one("#duration", Select).value == "PT2H"
            await wait_for(pilot, lambda: app.focused is reason)
            await pilot.press("enter")
            await _wait_done(pilot)
            assert fake_azure.activations[-1] == ("Key Vault Reader", "/subscriptions/s1", "PT2H", False)
            assert fake_azure.justifications[-1] == "INC-1 hotfix"
            assert len(app.recents.entries()) == 1  # the same roles: still one entry

    asyncio.run(first_run())
    assert len(fake_azure.activations) == 1
    asyncio.run(second_run())
    assert len(fake_azure.activations) == 2


def test_a_recent_with_an_active_role_waits_and_an_entra_recent_starts(make_live_app, fake_azure) -> None:
    store = state.open_store(demo_mode=False)
    global_reader = fake_azure.entra[0]
    store.add(state.entra_recent([global_reader], "Audit", "PT30M"))  # 2
    store.add(  # 1: Contributor on s1 is active now
        state.Recent(
            kind="azure",
            targets=(("Contributor", "/subscriptions/s1"), ("Reader", "/subscriptions/s1")),
            labels=("Contributor · s1", "Reader · s1"),
            justification="INC-2",
            duration="PT1H",
            subscriptions=("s1",),
        )
    )

    async def scenario() -> None:
        app = make_live_app()
        async with app.run_test(size=SIZE, notifications=True) as pilot:
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen) and _recent_tab_shown(app))
            await pilot.press("1")
            await wait_for(pilot, lambda: isinstance(app.screen, RolesScreen))
            roles = app.screen
            role_list = roles.query_one("#role-list", FomoSelectionList)
            # No activation screen: the list, with the role that is left selected.
            await wait_for(pilot, lambda: app.focused is role_list)
            assert isinstance(app.screen, RolesScreen)
            selected = [(roles.all_roles[i].role_name, roles.all_roles[i].scope) for i in role_list.selected]
            assert selected == [("Reader", "/subscriptions/s1")]
            contributor = next(i for i, r in enumerate(roles.all_roles) if r.role_name == "Contributor")
            options = [role_list.get_option_at_index(k) for k in range(role_list.option_count)]
            assert next(option for option in options if option.value == contributor).disabled
            await wait_for(pilot, lambda: _toasts(app))
            assert _toasts(app) == [
                "Recent activation\nAlready active: Contributor · s1\nCheck the selection, then press Enter."
            ]

            await pilot.press("escape")
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))
            await pilot.press("2")  # Entra: loads the Entra tab, then goes straight on
            await wait_for(pilot, lambda: isinstance(app.screen, EntraActivationScreen))
            screen = app.screen
            assert screen.query_one("#justification", Input).value == "Audit"
            assert screen.query_one("#duration", Select).value == "PT30M"
            await wait_for(pilot, lambda: app.focused is screen.query_one("#justification"))
            await pilot.press("enter")
            await _wait_done(pilot)
            assert _status_cells(screen.query_one("#roles-table"), 2) == ["✓ Provisioned"]

    asyncio.run(scenario())
    assert fake_azure.activations == [("Global Reader", "/", "PT30M", False)]
