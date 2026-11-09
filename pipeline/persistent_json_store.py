"""Small, process-safe helpers for JSON files shared with the live service."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path


@contextmanager
def exclusive_file_lock(path):
    """Lock a stable sibling file while a shared JSON file is updated."""
    path = Path(path)
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def read_json_object(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json_atomically(path, payload, *, indent=2):
    """Write and replace one JSON file; callers lock before read/merge/write."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(
                payload,
                output,
                ensure_ascii=False,
                indent=indent,
                separators=None if indent is not None else (",", ":"),
            )
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
