"""Protected atomic UTF-8 text publication and a sample-sheet adapter."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from stat import S_ISREG
from typing import Iterable

from .serialization import SheetFormat, serialize_sheet
from .sheet import SampleSheet


def _check_protected(destination: Path, protected: tuple[Path, ...]) -> None:
    for path in protected:
        if destination.resolve() == path.resolve():
            raise ValueError(f"destination overlaps protected path: {path}")
        if destination.exists() and path.exists() and destination.samefile(path):
            raise ValueError(f"destination overlaps protected file: {path}")


def write_sheet_atomic(
    sheet: SampleSheet,
    destination: Path,
    format: SheetFormat,
    *,
    protected_paths: Iterable[Path] = (),
    overwrite: bool = False,
) -> Path:
    """Serialize first, then publish through write_text_atomic and its safety checks.

    See write_text_atomic for the portable no-overwrite race limitation.
    """
    text = serialize_sheet(sheet, format)
    return write_text_atomic(text, destination, protected_paths=protected_paths, overwrite=overwrite)


def write_text_atomic(
    text: str,
    destination: Path,
    *,
    protected_paths: Iterable[Path] = (),
    overwrite: bool = False,
) -> Path:
    """Preflight, validate UTF-8, fsync, then replace using a same-directory temp.

    No-overwrite mode reserves the destination with O_CREAT|O_EXCL after the
    temporary file is complete, rejecting a destination created during the
    write. A brief empty reservation is visible before os.replace. Python's
    portable standard library has no atomic conditional os.replace: an actor
    replacing the reservation in that final interval cannot be fully guarded
    against. Concurrent directory/protected-path changes likewise require
    external coordination. Cleanup removes only our own reservation inode.
    Protected paths are checked before creating the temp and again before
    publication. No input contents are opened or read.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    destination = Path(os.path.abspath(destination))
    protected = tuple(Path(path) for path in protected_paths)
    if not destination.parent.exists():
        raise FileNotFoundError(destination.parent)
    if not destination.parent.is_dir():
        raise NotADirectoryError(destination.parent)
    if destination.is_dir():
        raise IsADirectoryError(destination)
    _check_protected(destination, protected)
    if os.path.lexists(destination):
        if not overwrite:
            raise FileExistsError(destination)
        if not S_ISREG(destination.lstat().st_mode):
            raise ValueError("existing destination must be an ordinary file")
    # Reject invalid UTF-8 text before any temporary file is created, too.
    text.encode("utf-8")

    temporary: Path | None = None
    reservation: tuple[int, int] | None = None
    completed = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=destination.parent,
            prefix=".fastq-sheet-audit-", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        _check_protected(destination, protected)
        if not overwrite:
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                stat = os.fstat(descriptor)
                reservation = (stat.st_dev, stat.st_ino)
            finally:
                os.close(descriptor)
        os.replace(temporary, destination)
        completed = True
        return destination
    finally:
        try:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        finally:
            if not completed and reservation is not None:
                try:
                    stat = destination.lstat()
                except FileNotFoundError:
                    pass
                else:
                    if (stat.st_dev, stat.st_ino) == reservation:
                        destination.unlink()
