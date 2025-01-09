from __future__ import annotations

import os

try:
    import fcntl
except ImportError:
    class WrapLock():
        def __init__(self, subdir_root: str):
            pass
        def __enter__(self, *args, **kwargs) -> None:
            pass
        def __exit__(self, *args, **kwargs) -> None:
            pass
else:
    class WrapLock():
        def __init__(self, subdir_root: str):
            self.lock_file = os.path.join(subdir_root, ".wraplock")

        """Uses the :func:`fcntl.flock` to hard lock the lock file on unix systems."""
        def __enter__(self, *args, **kwargs) -> None:
            try:
                self.fd = os.open(self.lock_file,
                             os.O_RDWR | os.O_TRUNC | os.O_CREAT,
                             0o644);
            except FileNotFoundError:
                self.fd = -1
                return
            fcntl.flock(self.fd, fcntl.LOCK_EX)

        def __exit__(self, *args, **kwargs) -> None:
            if self.fd == -1:
                return;
            # Do not remove the lockfile:
            #   https://github.com/tox-dev/py-filelock/issues/31
            #   https://stackoverflow.com/questions/17708885/flock-removing-locked-file-without-race-condition
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = -1

__all__ = [
    "WrapLock",
]
