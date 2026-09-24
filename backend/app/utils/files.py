"""Filesystem helpers with a security-first bias.

Two rules are enforced everywhere:

1. **Never trust a name from outside.**  Uploaded file names and URLs both
   reach the disk, so every write path goes through :func:`safe_filename` and
   :func:`ensure_within`.
2. **Never hand an absolute filesystem path to a client.**  Callers store and
   return paths *relative* to a configured root, produced by
   :func:`relative_posix`.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

#: Characters Windows forbids in file names, plus control characters.
_UNSAFE_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
#: Normalisation patterns applied after the unsafe-character substitution.
_WHITESPACE_RUNS_RE = re.compile(r"\s+")
_UNDERSCORE_RUNS_RE = re.compile(r"_{2,}")
_NON_ALNUM_SUFFIX_RE = re.compile(r"[^A-Za-z0-9]")
_ALNUM_RE = re.compile(r"[A-Za-z0-9]")
#: Windows reserved device names - creating these fails or aliases a device.
_RESERVED_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)
_BYTES_UNITS = ("B", "KB", "MB", "GB", "TB")


def safe_filename(name: str, *, fallback: str = "file", max_length: int = 180) -> str:
    """Reduce an arbitrary string to a name that is safe on every platform.

    Strips directory components (defeating ``../../etc/passwd``), removes
    reserved characters, guards against Windows device names, collapses runs of
    separators, and substitutes ``fallback`` when nothing usable remains.
    The extension, if any, is preserved.
    """
    # ``Path(...).name`` also normalises backslashes on Windows, but the
    # replacement makes the behaviour identical on POSIX.
    candidate = Path(name.replace("\\", "/")).name
    candidate = _UNSAFE_CHARS_RE.sub("_", candidate)
    candidate = _WHITESPACE_RUNS_RE.sub("_", candidate)
    candidate = _UNDERSCORE_RUNS_RE.sub("_", candidate)
    candidate = candidate.strip(" ._")

    stem, dot, suffix = candidate.rpartition(".")
    if not dot:
        stem, suffix = candidate, ""
    # An extension is kept only if it is plausibly one.
    suffix = _NON_ALNUM_SUFFIX_RE.sub("", suffix)

    # A stem of only punctuation ("!!!") is not a usable name.
    if not _ALNUM_RE.search(stem):
        stem = fallback
    if stem.lower() in _RESERVED_NAMES:
        stem = f"{stem}_file"

    allowed = max_length - (len(suffix) + 1 if suffix else 0)
    stem = stem[: max(1, allowed)]
    return f"{stem}.{suffix}" if suffix else stem


def ensure_within(base: str | Path, target: str | Path) -> Path:
    """Resolve ``target`` and verify it stays inside ``base``.

    Raises:
        ValueError: when the resolved path escapes the base directory.  This is
            the guard that turns a path-traversal attempt into a clean 400
            instead of a file read outside the sandbox.
    """
    base_path = Path(base).resolve()
    candidate = (base_path / target).resolve() if not Path(target).is_absolute() else Path(target).resolve()
    if candidate != base_path and base_path not in candidate.parents:
        raise ValueError(f"path escapes the storage root: {target!r}")
    return candidate


def relative_posix(path: str | Path, base: str | Path) -> str:
    """Path relative to ``base``, always with forward slashes.

    Stored in the database so a volume can be remounted (or moved from Windows
    to Linux containers) without rewriting every row.
    """
    return Path(path).resolve().relative_to(Path(base).resolve()).as_posix()


def unique_path(directory: str | Path, filename: str) -> Path:
    """Return a non-existing path inside ``directory`` for ``filename``.

    Appends ``-1``, ``-2``, ... before the extension until the name is free.
    """
    target = Path(directory) / filename
    if not target.exists():
        return target

    stem, suffix = target.stem, target.suffix
    for index in range(1, 10_000):
        candidate = target.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not find a free filename in {directory!r}")


def human_bytes(size: int | None) -> str:
    """Format a byte count for display: ``1536`` -> ``"1.5 KB"``."""
    if not size or size < 0:
        return "0 B"
    value = float(size)
    for unit in _BYTES_UNITS:
        if value < 1024 or unit == _BYTES_UNITS[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"  # pragma: no cover - unreachable


def atomic_write_bytes(path: str | Path, payload: bytes) -> Path:
    """Write ``payload`` atomically.

    A crash mid-write must never leave a truncated image or workbook behind, so
    data goes to a temporary file in the same directory (same volume, therefore
    an atomic ``os.replace``) and is then renamed into place.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=".mvai-", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return target


def directory_size(directory: str | Path) -> int:
    """Total size in bytes of every file under ``directory`` (recursive)."""
    root = Path(directory)
    if not root.exists():
        return 0
    return sum(item.stat().st_size for item in root.rglob("*") if item.is_file())


def has_suffix(filename: str, suffixes: tuple[str, ...]) -> bool:
    """Case-insensitive extension check against an allowed list."""
    return Path(filename).suffix.lower() in {suffix.lower() for suffix in suffixes}
