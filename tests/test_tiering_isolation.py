"""Tier data can never break role loading (F02, F19, F40).

The tiering load used to share the role fetch's ``try``: one malformed
upstream entry, or an unwritable cache directory, became the subscription's
error and the screen said "No eligible PIM roles found".  The UI callback sat
in the same ``try``, so an exception in it counted the subscription twice
("Loading roles… 2/1").  Tier data now loads in its own worker, which never
raises, and demo mode never touches the network.

These tests run against the fake Azure boundary with ``demo_mode=False`` and
``dry_run=True`` unless they test demo mode.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

import pytest
from textual.pilot import Pilot
from textual.widgets import Label
from textual.worker import WorkerFailed

from fomo import app as app_module
from fomo import tiering
from fomo.app import PimApp
from fomo.screens.roles_screen import RolesScreen
from fomo.screens.scope_screen import ScopeScreen
from fomo.widgets import FomoSelectionList
from tests.conftest import TIERING_AZURE, TIERING_ENTRA
from tests.test_tui_smoke import SIZE, _prompts, wait_for

NO_TIER_DATA = "No tiering data available for this role."
MALFORMED = [{"id": None, "tier": 1}]


@pytest.fixture
def make_tui(monkeypatch: pytest.MonkeyPatch) -> Callable[..., PimApp]:
    """PimApp with theme detection and the dbus watcher stubbed; live (fake Azure) by default."""
    monkeypatch.setattr(app_module, "_system_is_dark", lambda: True)
    monkeypatch.setattr(PimApp, "_watch_color_scheme", lambda self: None)

    def _make(demo_mode: bool = False) -> PimApp:
        return PimApp(demo_mode=demo_mode, dry_run=True)

    return _make


def _serve(monkeypatch: pytest.MonkeyPatch, data: list | None, gate: threading.Event | None = None) -> list[str]:
    """Serve *data* from ``tiering._fetch_json``, optionally after *gate* opens; return the URLs fetched."""
    calls: list[str] = []

    def _fetch(url: str) -> list | None:
        calls.append(url)
        if gate is not None:
            gate.wait(5)
        return [dict(item) for item in data] if data is not None else None

    monkeypatch.setattr(tiering, "_fetch_json", _fetch)
    return calls


def _text(label: Label) -> str:
    return str(label.visual)


async def _scope_ready(pilot: Pilot) -> ScopeScreen:
    await wait_for(pilot, lambda: isinstance(pilot.app.screen, ScopeScreen))
    screen = pilot.app.screen
    assert isinstance(screen, ScopeScreen)
    return screen


async def _roles_listed(pilot: Pilot, sub_ids: list[str]) -> RolesScreen:
    await _scope_ready(pilot)
    screen = RolesScreen(sub_ids)
    await pilot.app.push_screen(screen)
    role_list = screen.query_one("#role-list", FomoSelectionList)
    await wait_for(pilot, lambda: role_list.option_count > 0)
    return screen


async def _entra_listed(pilot: Pilot) -> ScopeScreen:
    screen = await _scope_ready(pilot)
    screen.action_next_tab()
    entra_list = screen.query_one("#entra-role-list", FomoSelectionList)
    await wait_for(pilot, lambda: entra_list.option_count > 0)
    return screen


async def _workers_done(pilot: Pilot) -> None:
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


# ---------------------------------------------------------------------------
# Azure roles screen
# ---------------------------------------------------------------------------


def test_malformed_tier_data_still_lists_roles(make_tui, fake_azure, monkeypatch) -> None:
    calls = _serve(monkeypatch, MALFORMED)

    async def scenario() -> None:
        app = make_tui()
        async with app.run_test(size=SIZE) as pilot:
            screen = await _roles_listed(pilot, ["s1"])
            await _workers_done(pilot)
            assert calls == [tiering._AZURE_URL]
            assert _prompts(screen.query_one("#role-list", FomoSelectionList))
            assert _text(screen.query_one("#detail", Label)).endswith(NO_TIER_DATA)
            assert app.return_code is None

    asyncio.run(scenario())


def test_unwritable_cache_dir_still_lists_roles(make_tui, fake_azure, monkeypatch, tmp_path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    monkeypatch.setattr(tiering, "_CACHE_DIR", str(blocker / "fomo"))
    _serve(monkeypatch, TIERING_AZURE)

    async def scenario() -> None:
        app = make_tui()
        async with app.run_test(size=SIZE) as pilot:
            screen = await _roles_listed(pilot, ["s1", "s2"])
            await _workers_done(pilot)
            prompts = _prompts(screen.query_one("#role-list", FomoSelectionList))
            assert any(p.startswith("Key Vault Reader") for p in prompts), prompts
            assert screen._loaded_count == 2
            assert app.return_code is None

    asyncio.run(scenario())


def test_roles_loading_counts_each_subscription_once_when_callback_raises(make_tui, fake_azure, monkeypatch) -> None:
    raised: list[str] = []
    original = RolesScreen._rebuild_list

    def _raise_once(self: RolesScreen, query: str) -> None:
        if not raised:
            raised.append(query)
            raise RuntimeError("UI boom")
        original(self, query)

    monkeypatch.setattr(RolesScreen, "_rebuild_list", _raise_once)
    screen = RolesScreen(["s1", "s2"])
    labels: list[str] = []

    async def scenario() -> None:
        app = make_tui()
        async with app.run_test(size=SIZE) as pilot:
            await _scope_ready(pilot)
            await app.push_screen(screen)
            await wait_for(pilot, lambda: raised)
            await pilot.pause()
            labels.append(_text(screen.query_one("#loading-label", Label)))

    # The UI error surfaces as itself (Textual's worker failure), not as a
    # misleading fetch error that counts the subscription a second time.
    with pytest.raises(WorkerFailed, match="UI boom"):
        asyncio.run(scenario())
    assert screen._loaded_count == 2
    assert labels == ["Loading roles… 2/2"]


def test_detail_pane_refreshes_when_tier_data_arrives_late(make_tui, fake_azure, monkeypatch) -> None:
    gate = threading.Event()
    _serve(monkeypatch, TIERING_AZURE, gate)
    fake_azure.roles = {"s1": [fake_azure.roles["s1"][0]]}  # Reader, Tier 3

    async def scenario() -> None:
        app = make_tui()
        async with app.run_test(size=SIZE) as pilot:
            screen = await _roles_listed(pilot, ["s1"])
            detail = screen.query_one("#detail", Label)
            assert _text(detail).endswith(NO_TIER_DATA)
            gate.set()
            await wait_for(pilot, lambda: "Tier 3" in _text(detail))
            assert "Reads" in _text(detail)

    asyncio.run(scenario())


def test_late_tier_data_after_leaving_roles_screen_is_harmless(make_tui, fake_azure, monkeypatch) -> None:
    gate = threading.Event()
    _serve(monkeypatch, TIERING_AZURE, gate)

    async def scenario() -> None:
        app = make_tui()
        async with app.run_test(size=SIZE) as pilot:
            await _roles_listed(pilot, ["s1"])
            app.pop_screen()
            await wait_for(pilot, lambda: isinstance(app.screen, ScopeScreen))
            gate.set()
            await wait_for(pilot, lambda: tiering.get_azure_tier("Reader"))
            await pilot.pause(0.1)
            assert isinstance(app.screen, ScopeScreen)
            assert app.return_code is None

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Entra tab
# ---------------------------------------------------------------------------


def test_malformed_tier_data_still_lists_entra_roles(make_tui, fake_azure, monkeypatch) -> None:
    calls = _serve(monkeypatch, MALFORMED)

    async def scenario() -> None:
        app = make_tui()
        async with app.run_test(size=SIZE) as pilot:
            screen = await _entra_listed(pilot)
            await _workers_done(pilot)
            assert calls == [tiering._ENTRA_URL]
            assert len(_prompts(screen.query_one("#entra-role-list", FomoSelectionList))) == 3
            assert _text(screen.query_one("#entra-detail", Label)).endswith(NO_TIER_DATA)
            assert app.return_code is None

    asyncio.run(scenario())


def test_entra_detail_pane_refreshes_when_tier_data_arrives_late(make_tui, fake_azure, monkeypatch) -> None:
    gate = threading.Event()
    _serve(monkeypatch, TIERING_ENTRA, gate)

    async def scenario() -> None:
        app = make_tui()
        async with app.run_test(size=SIZE) as pilot:
            screen = await _entra_listed(pilot)
            detail = screen.query_one("#entra-detail", Label)
            assert _text(detail).endswith(NO_TIER_DATA)
            gate.set()
            await wait_for(pilot, lambda: "Tier 2" in _text(detail))

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Demo mode
# ---------------------------------------------------------------------------


def test_demo_mode_never_fetches_tier_data(make_tui, monkeypatch) -> None:
    calls = _serve(monkeypatch, TIERING_AZURE + TIERING_ENTRA)

    async def scenario() -> None:
        app = make_tui(demo_mode=True)
        async with app.run_test(size=SIZE) as pilot:
            await _entra_listed(pilot)
            await _roles_listed(pilot, ["11111111-1111-1111-1111-111111111111"])
            await _workers_done(pilot)
            assert app.return_code is None

    asyncio.run(scenario())
    assert calls == []
