# Phase 03c: fix(security), keep secrets out of logs, private token cache, Graph token lock

**Group:** 3
**Findings:** F03, F04, F14
**Contract:** none. Only `--log` file contents, file permissions and internal locking change.

## Problem (verified with fakes)

- `_run_az` logs `result.stdout[:2000]` for every call. The TUI's startup `check_auth()` runs `az account get-access-token`, so the **ARM access token** lands in the `--log` file. `get_current_user()` runs `az ad signed-in-user show`, which puts the user's profile (phone, mail) there too. `logging.basicConfig(filename=...)` creates the log as 0644.
- `_save_token_cache` writes the refresh token with the default umask (0644) before `chmod 0600`. The directory is 0755, and the write follows symlinks.
- `_get_graph_token` has no lock. The Entra tab and the Assignments screen can run two device-code flows at once.

## Steps

### 1. `fomo/azure.py`

- `check_auth()`: `_run_az("account", "get-access-token", "--query", "expiresOn")`. It validates the session without returning the token.
- `get_current_user()`: `_run_az("ad", "signed-in-user", "show", "--query", "id")`, which returns a JSON string. Adjust the return. **The CLI contract tests use fakes at the function level, so they're unaffected.**
- Add `_redact(text)`, which masks JSON values for keys matching `(?i)(access_?token|refresh_?token|id_?token|client_secret|password)`. Apply it to every logged stdout and stderr in `_run_az` and to Graph error bodies. Add a `log_body: bool = True` parameter to `_run_az` and pass `False` for token and profile calls.
- `_save_token_cache`:
  - create the directory with `os.makedirs(dir, mode=0o700, exist_ok=True)`, then `os.chmod(dir, 0o700)` if it's broader. `~/.cache/fomo` is fomo's own directory.
  - write via `fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)`, `json.dump`, `fsync`, then `os.replace(tmp, path)`. Clean up `tmp` on error.
- Add a module-level `_graph_token_lock = threading.RLock()`. Hold it for the whole body of `_get_graph_token`, so the second caller waits and then reuses the in-process token.

### 2. `fomo/__main__.py` (the `--log` branch only)

Create the log file 0600 before configuring logging: `os.open(args.log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)` and close it, then `logging.basicConfig(...)` exactly as today. Keep the same format, level and datefmt. `import os` is stdlib, so the top-level import rule holds. Existing files keep their mode; don't chmod user files.

## Tests (`tests/test_security.py`)

- Fake `subprocess.run` at the `fomo.azure.subprocess` boundary, returning `{"accessToken": "SECRET"}` for get-access-token and a profile with a phone number. With logging configured to a tmp file at DEBUG, call `check_auth()` and `get_current_user()`. Assert that the log contains neither `SECRET` nor the phone number, and that the `az` args include `--query`.
- `_redact` unit test.
- `main(["--log", tmp/"f.log", ...])`, via an invocation that exits early with a usage error after logging is configured: the file mode is 0600 under umask 022.
- Token cache under umask 022: spy on `json.dump` to record `os.stat(fd or path)` mode during the write. The file is always 0600, the directory is 0700, and an existing symlink at the path is not followed (`O_EXCL` on the temp file, and `replace` swaps the link itself).
- Lock: two threads call `_get_graph_token` with a fake `_device_code_flow` that sleeps 0.2 s and counts calls. The count is 1.

## Verify

- `.venv/bin/python -m pytest -q` passes, contract tests included and unchanged.
- Lint and the type checker are clean.

## Commits

- `fix(security): keep tokens and profile data out of --log and create it 0600`
- `fix(security): write the Graph token cache privately and atomically`
- `fix(entra): serialize Graph token acquisition`

Tick `03c`.
