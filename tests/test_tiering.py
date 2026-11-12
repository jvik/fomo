"""tiering.ensure_*_loaded(): load once, thread-safe."""

from __future__ import annotations

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
