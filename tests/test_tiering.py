"""tiering: load once, thread-safe, never raise, no network in demo mode."""

from __future__ import annotations

import json
import logging
import os
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


# ---------------------------------------------------------------------------
# Malformed entries, atomic cache writes and the stale-cache fallback
# ---------------------------------------------------------------------------


def test_build_index_skips_malformed_entries(caplog) -> None:
    data = [None, {"id": None}, {"id": "x", "tier": "a"}, {"id": " ABC ", "tier": "1", "assetName": "X"}]
    with caplog.at_level(logging.DEBUG, logger="fomo.tiering"):
        index = tiering._build_index(data)
    assert index == {"abc": {"tier": 1, "name": "X", "attack_path": ""}}
    skipped = [r for r in caplog.records if "skipping entry" in r.getMessage()]
    assert len(skipped) == 3


@pytest.mark.parametrize(
    "item",
    [
        {"id": 7, "tier": 1},
        {"id": "", "tier": 1},
        {"id": "   ", "tier": 1},
        {"id": "x"},
        {"id": "x", "tier": None},
        {"id": "x", "tier": [1]},
        {"id": "x", "tier": float("inf")},
        "x",
        ["x", 1],
    ],
)
def test_build_index_skips_each_kind_of_malformed_entry(item) -> None:
    assert tiering._build_index([item]) == {}


def test_build_index_treats_non_string_text_as_empty() -> None:
    data = [{"id": "x", "tier": 0, "assetName": None, "shortestPath": 5, "worstCaseScenario": "w"}]
    assert tiering._build_index(data) == {"x": {"tier": 0, "name": "", "attack_path": "w"}}


@pytest.mark.parametrize("data", [None, {"id": "x", "tier": 1}, "x", 3])
def test_build_index_ignores_data_that_is_not_a_list(data) -> None:
    assert tiering._build_index(data) == {}


def _unwritable_cache_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    monkeypatch.setattr(tiering, "_CACHE_DIR", str(blocker / "fomo"))


@pytest.mark.parametrize(("load", "kind"), LOADERS)
def test_unwritable_cache_dir_still_loads_fetched_data(monkeypatch, tmp_path, caplog, load, kind) -> None:
    _unwritable_cache_dir(monkeypatch, tmp_path)
    _counting_fetch(monkeypatch, [ENTRY])
    with caplog.at_level(logging.WARNING, logger="fomo.tiering"):
        load()
    assert set(_index(kind)) == {"abc"}
    assert any("could not write cache" in r.getMessage() for r in caplog.records)


def test_save_disk_cache_writes_atomically(monkeypatch, tmp_path) -> None:
    tiering._save_disk_cache("azure", [ENTRY])
    path = tmp_path / "tiering_azure.json"
    assert json.loads(path.read_text()) == [ENTRY]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["tiering_azure.json"]

    def _fail(src: str, dst: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(tiering.os, "replace", _fail)
    tiering._save_disk_cache("azure", [{"id": "new", "tier": 0}])
    # The old file is untouched and no temp file is left behind.
    assert json.loads(path.read_text()) == [ENTRY]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["tiering_azure.json"]


def _write_cache(kind: str, data: list, age: float) -> None:
    tiering._save_disk_cache(kind, data)
    mtime = time.time() - age
    os.utime(tiering._cache_path(kind), (mtime, mtime))


def _cached(kind: str) -> list:
    with open(tiering._cache_path(kind)) as f:
        return json.load(f)


STALE = tiering._CACHE_TTL + 3600
FRESH = 60


@pytest.mark.parametrize(("load", "kind"), LOADERS)
def test_fresh_cache_is_used_without_fetching(monkeypatch, load, kind) -> None:
    _write_cache(kind, [ENTRY], FRESH)
    calls = _counting_fetch(monkeypatch, [{"id": "other", "tier": 2}])
    load()
    assert calls == []
    assert set(_index(kind)) == {"abc"}


@pytest.mark.parametrize(("load", "kind"), LOADERS)
def test_stale_cache_is_used_when_the_fetch_fails(monkeypatch, caplog, load, kind) -> None:
    _write_cache(kind, [ENTRY], STALE)
    calls = _counting_fetch(monkeypatch, None)
    with caplog.at_level(logging.INFO, logger="fomo.tiering"):
        load()
    assert len(calls) == 1
    assert set(_index(kind)) == {"abc"}
    assert any(r.levelno == logging.INFO and "stale" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(("load", "kind"), LOADERS)
def test_stale_cache_is_used_when_the_download_has_no_usable_entries(monkeypatch, load, kind) -> None:
    _write_cache(kind, [ENTRY], STALE)
    _counting_fetch(monkeypatch, [{"id": None, "tier": 1}])
    load()
    assert set(_index(kind)) == {"abc"}
    # The unusable download did not replace the cache.
    assert _cached(kind) == [ENTRY]


@pytest.mark.parametrize(("load", "kind"), LOADERS)
def test_stale_cache_is_refreshed_when_the_fetch_succeeds(monkeypatch, load, kind) -> None:
    _write_cache(kind, [ENTRY], STALE)
    new = {"id": "new", "tier": 2, "assetName": "N"}
    _counting_fetch(monkeypatch, [new])
    load()
    assert set(_index(kind)) == {"new"}
    assert _cached(kind) == [new]


@pytest.mark.parametrize(("load", "kind"), LOADERS)
def test_stale_cache_is_used_without_network(monkeypatch, load, kind) -> None:
    _write_cache(kind, [ENTRY], STALE)
    _no_network(monkeypatch)
    load(allow_network=False)
    assert set(_index(kind)) == {"abc"}
