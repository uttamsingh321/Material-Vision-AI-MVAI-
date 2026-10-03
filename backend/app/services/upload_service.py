"""Upload service: validate, name and persist incoming workbook files.

Storage layout - one folder per batch::

    uploads/<batch_id>/<sanitised original name>.xlsx

``batch_id`` is a UUID minted here (or supplied by the caller); it becomes the
``materials.batch_id`` grouping key and the handle every later stage (jobs,
export, review) refers to.  Keeping the original file on disk means the export
service can append result columns to the *source* workbook later without
having to re-upload it.

Writes go through :func:`app.utils.files.atomic_write_bytes` - a crash halfway
through a multi-megabyte upload must never leave a truncated workbook that a
later parse would misread.  The returned ``relative_path`` is POSIX-style and
relative to ``uploads/`` so it is safe to expose over the API.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.config.logging import get_logger
from app.utils.files import atomic_write_bytes, relative_posix, safe_filename
from app.utils.hashing import sha256_bytes
from app.services.validation_service import ValidationService, validation_service

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class StoredUpload:
    """Where an uploaded workbook landed and what it was."""

    batch_id: str
    original_filename: str
    #: Absolute path on this host (server-side only - never sent to a client).
    path: Path
    #: POSIX path relative to ``uploads_dir`` - safe to serialise.
    relative_path: str
    byte_size: int
    sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "original_filename": self.original_filename,
            "relative_path": self.relative_path,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
        }


class UploadService:
    """Validated, batch-scoped storage for uploaded workbooks."""

    def __init__(self, validator: ValidationService | None = None) -> None:
        self.settings = get_settings()
        self.validator = validator or validation_service()

    @property
    def uploads_dir(self) -> Path:
        directory = self.settings.uploads_dir
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def new_batch_id(self) -> str:
        """A fresh UUID4 for one upload/batch."""
        return str(uuid.uuid4())

    def store(
        self,
        payload: bytes,
        filename: str,
        *,
        batch_id: str | None = None,
        validate: bool = True,
    ) -> StoredUpload:
        """Validate ``payload`` and write it under ``uploads/<batch_id>/``.

        Raises:
            app.services.validation_service.UploadRejectedError: when
                ``validate`` is true and the container checks fail.
        """
        if validate:
            self.validator.ensure_uploadable(filename, payload)

        batch = batch_id or self.new_batch_id()
        clean_name = safe_filename(filename, fallback="workbook.xlsx")
        directory = self.uploads_dir / batch
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / clean_name
        atomic_write_bytes(path, payload)

        stored = StoredUpload(
            batch_id=batch,
            original_filename=filename,
            path=path,
            relative_path=relative_posix(path, self.uploads_dir),
            byte_size=len(payload),
            sha256=sha256_bytes(payload),
        )
        logger.info(
            "upload.stored",
            batch_id=stored.batch_id,
            filename=clean_name,
            bytes=stored.byte_size,
        )
        return stored

    def source_workbook(self, batch_id: str) -> Path | None:
        """The stored workbook for ``batch_id``, if it still exists.

        The folder holds exactly one file by construction; a glob is used so a
        renamed or re-uploaded file is still found without a manifest table.
        """
        directory = self.uploads_dir / batch_id
        if not directory.is_dir():
            return None
        candidates = sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and not path.name.startswith(".")
        )
        return candidates[0] if candidates else None

    def read_source(self, batch_id: str) -> bytes | None:
        """Raw bytes of the stored workbook, or ``None`` when purged."""
        path = self.source_workbook(batch_id)
        if path is None:
            return None
        return path.read_bytes()

    def delete_batch(self, batch_id: str) -> bool:
        """Remove the stored workbook folder for a batch; ``True`` if removed."""
        import shutil

        directory = self.uploads_dir / batch_id
        if not directory.is_dir():
            return False
        shutil.rmtree(directory, ignore_errors=True)
        return True


def upload_service() -> UploadService:
    """An upload service configured from the current settings."""
    return UploadService()


__all__ = ["StoredUpload", "UploadService", "upload_service"]
