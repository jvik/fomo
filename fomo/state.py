"""fomo's private files on disk.

:func:`write_private_json` writes a file that only the user may read, such as
the cached Graph refresh token.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import uuid


def write_private_json(path: str, payload: object) -> None:
    """Write *payload* as JSON to *path*, privately and atomically.

    The file's directory (fomo's own) is made 0700, and tightened to 0700 if
    it already exists with wider permissions; its parents are left alone.
    The JSON goes to a new temp file that is created 0600, never through an
    existing file or symlink, and is then renamed over *path*, so it is never
    readable by others, a symlink at *path* is replaced rather than followed,
    and a failed write leaves the old file as it was.  Errors are raised.
    """
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    if stat.S_IMODE(os.stat(directory).st_mode) & 0o077:
        os.chmod(directory, 0o700)
    tmp = f"{path}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
