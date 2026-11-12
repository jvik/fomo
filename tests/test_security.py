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
import threading
import time
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


def test_reused_log_file_is_made_private_but_not_a_fifo(
    run_cli: Callable[[list[str]], Any], tmp_path: Path, umask_022: None
) -> None:
    # Older versions created the log 0644 and wrote tokens into it.
    path = tmp_path / "f.log"
    path.write_text("earlier run\n")
    path.chmod(0o644)

    with _bare_root_logger():
        code, out, err = run_cli(["--log", str(path), "--mg", "corp"])

    assert code == 2
    assert out == []
    assert err[-1] == "fomo: error: --mg requires -r/--reason for non-interactive activation"
    assert _mode(path) == 0o600
    assert path.read_text().startswith("earlier run\n")  # appended to, not truncated

    fifo = tmp_path / "f.fifo"
    os.mkfifo(fifo, 0o644)
    reader = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)  # so that opening it to write doesn't block
    try:
        with _bare_root_logger():
            code, _, _ = run_cli(["--log", str(fifo), "--mg", "corp"])
    finally:
        os.close(reader)

    assert code == 2
    assert _mode(fifo) == 0o644


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


# ---------------------------------------------------------------------------
# Token cache left by an older version
# ---------------------------------------------------------------------------


@pytest.fixture
def old_cache(cache_path: Path, umask_022: None) -> Path:
    """A token cache as older versions left it: 0644, in a 0755 directory."""
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text('{"refresh_token": "old"}')
    cache_path.chmod(0o644)
    return cache_path


@pytest.mark.parametrize(
    ("argv", "expected_out"),
    [
        (["--demo"], []),
        (
            ["--entra", "Global Reader", "-r", "x", "--dry-run"],
            ["Fetching Entra eligible roles…", "Activating 1 Entra role(s)…", "  • Global Reader… ✓ DryRun"],
        ),
    ],
)
def test_startup_makes_an_old_token_cache_private(
    run_cli: Callable[[list[str]], Any],
    fake_azure: Any,
    monkeypatch: pytest.MonkeyPatch,
    old_cache: Path,
    argv: list[str],
    expected_out: list[str],
) -> None:
    from fomo.app import PimApp

    monkeypatch.setattr(PimApp, "run", lambda self, *args, **kwargs: None)  # the TUI

    code, out, err = run_cli(argv)

    assert (code, out, err) == (0, expected_out, [])  # nothing new printed
    assert _mode(old_cache) == 0o600
    assert _mode(old_cache.parent) == 0o700
    assert _mode(old_cache.parent.parent) == 0o755  # only fomo's own directory
    assert old_cache.read_text() == '{"refresh_token": "old"}'


def test_making_the_token_cache_private_leaves_symlinks_alone(
    cache_path: Path, tmp_path: Path, umask_022: None
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    victim = elsewhere / "victim.json"
    victim.write_text("keep me")
    victim.chmod(0o644)
    (elsewhere / "graph_token.json").symlink_to(victim)
    cache_path.parent.parent.mkdir(parents=True)
    cache_path.parent.symlink_to(elsewhere)

    azure.make_token_cache_private()

    assert cache_path.parent.is_symlink()
    assert cache_path.is_symlink()
    assert _mode(elsewhere) == 0o755
    assert _mode(victim) == 0o644
    assert victim.read_text() == "keep me"


def test_making_the_token_cache_private_skips_files_of_other_users(
    old_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: uid + 1)

    azure.make_token_cache_private()

    assert _mode(old_cache) == 0o644
    assert _mode(old_cache.parent) == 0o755


def test_making_the_token_cache_private_swallows_errors(
    old_cache: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _fchmod(fd: int, mode: int) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "fchmod", _fchmod)

    with caplog.at_level(logging.DEBUG, logger="fomo.state"):
        azure.make_token_cache_private()

    assert _mode(old_cache) == 0o644
    assert [record.levelno for record in caplog.records] == [logging.DEBUG, logging.DEBUG]
    assert "Operation not permitted" in caplog.text


# ---------------------------------------------------------------------------
# Graph token lock
# ---------------------------------------------------------------------------


@pytest.fixture
def device_code_flows(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fake a slow device-code flow; return the tenants it was started for."""
    flows: list[str] = []

    def _flow(tenant_id: str, on_device_code: Any = None, stop_event: Any = None) -> dict:
        flows.append(tenant_id)
        time.sleep(0.2)
        return {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}

    monkeypatch.setattr(azure, "_device_code_flow", _flow)
    monkeypatch.setattr(azure, "_get_tenant_id", lambda: "tenant-1")
    return flows


def _call_in_thread(results: list[Any], **kwargs: Any) -> threading.Thread:
    def _target() -> None:
        try:
            results.append(azure._get_graph_token(**kwargs))
        except Exception as exc:
            results.append(exc)

    thread = threading.Thread(target=_target)
    thread.start()
    return thread


def test_concurrent_callers_share_one_device_code_flow(device_code_flows: list[str]) -> None:
    results: list[Any] = []

    threads = [_call_in_thread(results), _call_in_thread(results)]
    for thread in threads:
        thread.join(timeout=5)

    assert device_code_flows == ["tenant-1"]
    assert results == ["AT", "AT"]


def test_waiting_caller_gives_up_when_its_screen_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    flows: list[str] = []
    started, release = threading.Event(), threading.Event()

    def _flow(tenant_id: str, on_device_code: Any = None, stop_event: Any = None) -> dict:
        flows.append(tenant_id)
        started.set()
        release.wait(5)  # the user hasn't signed in yet
        return {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}

    monkeypatch.setattr(azure, "_device_code_flow", _flow)
    monkeypatch.setattr(azure, "_get_tenant_id", lambda: "tenant-1")
    first: list[Any] = []
    second: list[Any] = []
    stop = threading.Event()

    first_thread = _call_in_thread(first)
    try:
        assert started.wait(5)  # the first caller holds the lock
        second_thread = _call_in_thread(second, stop_event=stop)
        stop.set()
        second_thread.join(timeout=2)

        assert not second_thread.is_alive()
        assert [str(exc) for exc in second] == ["Authentication cancelled."]
    finally:
        release.set()
        first_thread.join(timeout=5)
    assert first == ["AT"]
    assert flows == ["tenant-1"]


def test_cancelled_caller_does_not_start_a_device_code_flow(device_code_flows: list[str]) -> None:
    stop = threading.Event()
    stop.set()

    with pytest.raises(RuntimeError, match="^Authentication cancelled.$"):
        azure._get_graph_token(stop_event=stop)

    assert device_code_flows == []
