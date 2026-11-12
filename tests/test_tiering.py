"""tiering: load once, thread-safe, never raise, no network in demo mode."""

from __future__ import annotations

import logging
import threading
import time

import pytest

from fomo import tiering


def _counting_fetch(monkeypatch: pytest.MonkeyPatch, data: list | None) -> list[str]:
    calls: list[str] = []

    def _fetch(url: str) -> list | None:
        calls.append(url)
        time.sleep(0.05)  # widen the race window
        return [dict(item) for item in data] if data else None

    monkeypatch.setattr(tiering, "_fetch_json", _fetch)
    return calls


@pytest.mark.parametrize(
    ("ensure", "get_tier", "url", "guid"),
    [
        (tiering.ensure_azure_loaded, tiering.get_azure_tier, tiering._AZURE_URL, "/x/roleDefinitions/abc"),
        (tiering.ensure_entra_loaded, tiering.get_entra_tier, tiering._ENTRA_URL, "abc"),
    ],
)
def test_ensure_loaded_fetches_once_across_threads(monkeypatch, ensure, get_tier, url, guid) -> None:
    calls = _counting_fetch(monkeypatch, [{"id": "abc", "tier": "1", "assetName": "X", "shortestPath": "p"}])

    threads = [threading.Thread(target=ensure) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ensure()

    assert calls == [url]
    info = get_tier(guid)
    assert info is not None and info["tier"] == 1


def test_ensure_loaded_retries_while_index_is_empty(monkeypatch) -> None:
    calls = _counting_fetch(monkeypatch, None)
    tiering.ensure_azure_loaded()
    tiering.ensure_azure_loaded()
    assert calls == [tiering._AZURE_URL, tiering._AZURE_URL]


# ---------------------------------------------------------------------------
# allow_network=False (demo mode) and the never-raise guarantee
# ---------------------------------------------------------------------------

LOADERS = [
    pytest.param(tiering.load_azure, "azure", id="azure"),
    pytest.param(tiering.load_entra, "entra", id="entra"),
]
ENSURERS = [
    pytest.param(tiering.ensure_azure_loaded, "azure", id="azure"),
    pytest.param(tiering.ensure_entra_loaded, "entra", id="entra"),
]
ENTRY = {"id": "abc", "tier": "1", "assetName": "X", "shortestPath": "p"}


def _index(kind: str) -> dict:
    return tiering._azure_index if kind == "azure" else tiering._entra_index


def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fetch(url: str) -> list | None:
        raise AssertionError(f"network used: {url}")

    monkeypatch.setattr(tiering, "_fetch_json", _fetch)


@pytest.mark.parametrize(("load", "kind"), LOADERS)
def test_load_without_network_never_fetches(monkeypatch, load, kind) -> None:
    _no_network(monkeypatch)
    load(allow_network=False)
    assert _index(kind) == {}


@pytest.mark.parametrize(("load", "kind"), LOADERS)
def test_load_without_network_reads_the_cache(monkeypatch, load, kind) -> None:
    _no_network(monkeypatch)
    tiering._save_disk_cache(kind, [ENTRY])
    load(allow_network=False)
    assert set(_index(kind)) == {"abc"}


@pytest.mark.parametrize(("ensure", "kind"), ENSURERS)
def test_ensure_loaded_without_network_never_fetches(monkeypatch, ensure, kind) -> None:
    calls = _counting_fetch(monkeypatch, [ENTRY])
    ensure(allow_network=False)
    assert calls == []
    assert _index(kind) == {}


@pytest.mark.parametrize(("ensure", "kind"), ENSURERS)
def test_ensure_loaded_never_raises(monkeypatch, caplog, ensure, kind) -> None:
    _counting_fetch(monkeypatch, [ENTRY])

    def _boom(data: list) -> dict:
        raise RuntimeError("bad tier data")

    monkeypatch.setattr(tiering, "_build_index", _boom)
    with caplog.at_level(logging.WARNING, logger="fomo.tiering"):
        ensure()
    assert _index(kind) == {}
    assert any(r.levelno == logging.WARNING and r.exc_info for r in caplog.records)
