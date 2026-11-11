"""The data folder: the rotated tokens, and nothing else (spec C-8, A-4, A-5)."""

import contextlib
import hashlib
import os
import secrets
from pathlib import Path


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, name: str) -> Path:
        return self.root / name

    def read(self, name: str) -> str | None:
        try:
            return self.path(name).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def write(self, name: str, text: str) -> None:
        """Write a file whole or not at all, readable only by the app's user.

        A kill at any instant leaves the old file or the new one, never half of
        either (spec A-5, O-3a): the text goes to a temporary file that is
        flushed to disk and then renamed over the target.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path(f".{name}.{secrets.token_hex(8)}.tmp")
        try:
            with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            tmp.replace(self.path(name))
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise
        # The rename itself is only durable once the folder is flushed too.
        folder = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(folder)
        finally:
            os.close(folder)

    def remove(self, name: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.path(name).unlink()

    def seeded_by(self, name: str, env_value: str) -> bool:
        """Whether the stored copy of `name` started from this environment value.

        The environment value only seeds the store; the app then keeps the
        rotated copy. A different value means the user signed in again, and it
        replaces the stored copy (spec A-4). Only a hash of the value is kept.
        """
        return self.read(f"{name}.seed") == _digest(env_value)

    def mark_seed(self, name: str, env_value: str) -> None:
        self.write(f"{name}.seed", _digest(env_value))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
