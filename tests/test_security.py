"""Secrets stay out of ``--log``, the Graph token cache is private, token acquisition is serialised."""

from __future__ import annotations

import contextlib
import email.message
import io
import json
import logging
import os
import stat
import subprocess
import urllib.error
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from fomo import azure

SECRET = "SECRET-ARM-TOKEN"
PHONE = "+47 555 01 234"
USER_ID = "00000000-0000-0000-0000-00000000c0de"
PROFILE = {"id": USER_ID, "mail": "user@contoso.com", "mobilePhone": PHONE, "businessPhones": [PHONE]}


def _mode(path: str | Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


@pytest.fixture
def umask_022() -> Iterator[None]:
    old = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(old)


@pytest.fixture
def debug_log(tmp_path: Path) -> Iterator[Path]:
    """Send ``fomo.azure`` DEBUG records to a file, as ``--log`` does."""
    path = tmp_path / "debug.log"
    handler = logging.FileHandler(path)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    logger = logging.getLogger("fomo.azure")
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield path
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        handler.close()


def _fake_az(
    monkeypatch: pytest.MonkeyPatch,
    respond: Callable[[list[str]], tuple[int, Any, str]],
) -> list[list[str]]:
    """Fake ``subprocess.run`` at the ``fomo.azure.subprocess`` boundary; return the recorded argv."""
    calls: list[list[str]] = []

    def _run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        code, out, err = respond(cmd)
        return subprocess.CompletedProcess(cmd, code, stdout=json.dumps(out), stderr=err)

    monkeypatch.setattr(azure.subprocess, "run", _run)
    return calls


def _ignores_query(cmd: list[str]) -> tuple[int, Any, str]:
    """Answer with the full bodies, as if ``--query`` were ignored (worst case)."""
    if cmd[1:3] == ["account", "get-access-token"]:
        return 0, {"accessToken": SECRET, "expiresOn": "2026-11-12 13:00:00.000000", "tokenType": "Bearer"}, ""
    if cmd[1:4] == ["ad", "signed-in-user", "show"]:
        return 0, PROFILE, ""
    raise AssertionError(f"unexpected az call {cmd!r}")


def _honours_query(cmd: list[str]) -> tuple[int, Any, str]:
    """Answer the way ``az`` does: ``--query`` selects one value."""
    code, body, err = _ignores_query(cmd)
    if "--query" in cmd:
        body = body[cmd[cmd.index("--query") + 1]]
    return code, body, err


# ---------------------------------------------------------------------------
# --log contents
# ---------------------------------------------------------------------------


def test_token_and_profile_calls_stay_out_of_the_log(monkeypatch: pytest.MonkeyPatch, debug_log: Path) -> None:
    calls = _fake_az(monkeypatch, _ignores_query)

    azure.check_auth()
    azure.get_current_user()

    text = debug_log.read_text()
    assert "az account get-access-token" in text  # logging is on
    assert SECRET not in text
    assert PHONE not in text
    assert "user@contoso.com" not in text
    assert [cmd[cmd.index("--query") + 1] for cmd in calls] == ["expiresOn", "id"]


def test_get_current_user_returns_the_queried_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_az(monkeypatch, _honours_query)

    assert azure.get_current_user() == USER_ID
    assert calls == [["az", "ad", "signed-in-user", "show", "--query", "id", "--output", "json"]]


def test_check_auth_requests_only_the_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_az(monkeypatch, _honours_query)

    assert azure.check_auth() is None
    assert calls == [["az", "account", "get-access-token", "--query", "expiresOn", "--output", "json"]]


def test_run_az_redacts_logged_stdout_and_stderr(monkeypatch: pytest.MonkeyPatch, debug_log: Path) -> None:
    def _respond(cmd: list[str]) -> tuple[int, Any, str]:
        if "fail" in cmd:
            return 1, None, 'ERROR: bad request {"refresh_token": "SECRET-RT"}'
        return 0, {"value": [{"name": "kept", "access_token": "SECRET-AT"}]}, ""

    _fake_az(monkeypatch, _respond)

    assert azure._run_az("rest", "ok") == {"value": [{"name": "kept", "access_token": "SECRET-AT"}]}
    with pytest.raises(RuntimeError) as excinfo:
        azure._run_az("rest", "fail")

    text = debug_log.read_text()
    assert "kept" in text
    assert "ERROR: bad request" in text
    assert "SECRET" not in text
    assert "SECRET" not in str(excinfo.value)


def test_graph_error_body_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b'<html>proxy error {"id_token": "SECRET-ID", "client_secret": "SECRET-CS"}</html>'

    def _urlopen(req: Any, *args: Any, **kwargs: Any) -> Any:
        raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway", email.message.Message(), io.BytesIO(body))

    monkeypatch.setattr(azure, "_get_graph_token", lambda *a, **k: "tok")
    monkeypatch.setattr(azure.urllib.request, "urlopen", _urlopen)

    with pytest.raises(RuntimeError) as excinfo:
        azure._run_graph("GET", "https://graph.microsoft.com/v1.0/me")
    assert "proxy error" in str(excinfo.value)
    assert "SECRET" not in str(excinfo.value)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"accessToken": "abc", "expiresOn": "x"}', '{"accessToken": "***", "expiresOn": "x"}'),
        ('{"access_token":"a\\"b","refresh_token" : "c"}', '{"access_token":"***","refresh_token" : "***"}'),
        (
            '{"ID_TOKEN": "a", "client_secret": "b", "password": "c"}',
            '{"ID_TOKEN": "***", "client_secret": "***", "password": "***"}',
        ),
        ('{"userPassword": 12345, "tokenType": "Bearer"}', '{"userPassword": "***", "tokenType": "Bearer"}'),
        ('{"refreshToken": "truncated-at-2000-cha', '{"refreshToken": "***"'),
        ("no json here: refresh token expired", "no json here: refresh token expired"),
        ('{"name": "accessToken", "value": "x"}', '{"name": "accessToken", "value": "x"}'),
    ],
)
def test_redact(text: str, expected: str) -> None:
    assert azure._redact(text) == expected


# ---------------------------------------------------------------------------
# --log file mode
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _bare_root_logger() -> Iterator[None]:
    """Let ``logging.basicConfig`` configure the root logger as it does outside pytest.

    pytest's capture handlers sit on the root logger during the test call,
    which would make ``basicConfig`` a no-op; park them for the duration.
    """
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    for handler in saved_handlers:
        root.removeHandler(handler)
    try:
        yield
    finally:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_level)


def test_log_file_is_created_private(run_cli: Callable[[list[str]], Any], tmp_path: Path, umask_022: None) -> None:
    path = tmp_path / "f.log"

    with _bare_root_logger():
        code, _, err = run_cli(["--log", str(path), "--mg", "corp"])

    assert code == 2  # usage error, after logging was configured
    assert err[-1] == "fomo: error: --mg requires -r/--reason for non-interactive activation"
    assert path.is_file()
    assert _mode(path) == 0o600


def test_existing_log_file_keeps_its_mode(run_cli: Callable[[list[str]], Any], tmp_path: Path, umask_022: None) -> None:
    path = tmp_path / "f.log"
    path.write_text("earlier run\n")
    path.chmod(0o644)

    with _bare_root_logger():
        code, _, _ = run_cli(["--log", str(path), "--mg", "corp"])

    assert code == 2
    assert _mode(path) == 0o644
    assert path.read_text().startswith("earlier run\n")


# ---------------------------------------------------------------------------
# Graph token cache
# ---------------------------------------------------------------------------

TOKENS = {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600, "id_token": "not cached"}


@pytest.fixture
def cache_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "home" / ".cache" / "fomo" / "graph_token.json"
    monkeypatch.setattr(azure, "_TOKEN_CACHE_PATH", str(path))
    return path


@pytest.fixture
def dump_modes(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Record the mode of the file ``json.dump`` writes the tokens into, at the time of writing."""
    modes: list[int] = []
    real_dump = json.dump

    def _spy(obj: Any, fp: Any, *args: Any, **kwargs: Any) -> None:
        modes.append(stat.S_IMODE(os.fstat(fp.fileno()).st_mode))
        real_dump(obj, fp, *args, **kwargs)

    monkeypatch.setattr(azure.json, "dump", _spy)
    return modes


def test_token_cache_is_private_from_the_start(cache_path: Path, dump_modes: list[int], umask_022: None) -> None:
    azure._save_token_cache(TOKENS, "tenant-1")

    assert dump_modes == [0o600]
    assert _mode(cache_path) == 0o600
    assert _mode(cache_path.parent) == 0o700
    cached = azure._load_token_cache()
    assert cached is not None
    assert {k: cached[k] for k in ("access_token", "refresh_token", "expires_in", "tenant_id")} == {
        "access_token": "AT",
        "refresh_token": "RT",
        "expires_in": 3600,
        "tenant_id": "tenant-1",
    }
    assert "id_token" not in cached
    assert os.listdir(cache_path.parent) == ["graph_token.json"]


def test_token_cache_tightens_a_shared_cache_directory(cache_path: Path, umask_022: None) -> None:
    # tiering.py may have created ~/.cache/fomo first, with the default mode.
    cache_path.parent.mkdir(parents=True, mode=0o755)
    assert _mode(cache_path.parent) == 0o755

    azure._save_token_cache(TOKENS, "tenant-1")

    assert _mode(cache_path.parent) == 0o700
    assert _mode(cache_path.parent.parent) == 0o755  # only fomo's own directory


def test_token_cache_replaces_an_existing_file(cache_path: Path, dump_modes: list[int], umask_022: None) -> None:
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text('{"refresh_token": "old"}')
    cache_path.chmod(0o644)

    azure._save_token_cache(TOKENS, "tenant-1")

    assert dump_modes == [0o600]
    assert _mode(cache_path) == 0o600
    assert json.loads(cache_path.read_text())["refresh_token"] == "RT"


def test_token_cache_does_not_follow_a_symlink(cache_path: Path, tmp_path: Path, umask_022: None) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    victim.chmod(0o644)
    cache_path.parent.mkdir(parents=True)
    cache_path.symlink_to(victim)

    azure._save_token_cache(TOKENS, "tenant-1")

    assert victim.read_text() == "keep me"
    assert _mode(victim) == 0o644
    assert not cache_path.is_symlink()
    assert _mode(cache_path) == 0o600
    assert json.loads(cache_path.read_text())["refresh_token"] == "RT"


def test_token_cache_write_failure_keeps_the_old_cache(
    cache_path: Path, monkeypatch: pytest.MonkeyPatch, umask_022: None
) -> None:
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text('{"refresh_token": "old"}')

    def _fail(obj: Any, fp: Any, *args: Any, **kwargs: Any) -> None:
        fp.write('{"refresh_token": "half')
        raise OSError("No space left on device")

    monkeypatch.setattr(azure.json, "dump", _fail)

    with pytest.raises(OSError, match="No space left"):
        azure._save_token_cache(TOKENS, "tenant-1")

    assert cache_path.read_text() == '{"refresh_token": "old"}'
    assert os.listdir(cache_path.parent) == ["graph_token.json"]  # temp file removed
