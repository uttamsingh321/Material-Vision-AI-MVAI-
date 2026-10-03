"""Image library service: promote accepted images into the categorised library.

``image-cache/`` is where bytes land while they are still *candidates*.
``image-library/`` is the operator-facing taxonomy - one subfolder per material
category (``Electrical``, ``Bearings``, ...), pre-created by
``Settings.ensure_directories``.  Promotion copies an accepted image into its
category folder and records an :class:`app.models.image_library.ImageLibraryItem`
row so the library page and the exporters can answer "what do we already
have?" without touching disk.

Deduplication rules:

* **Files** are named ``<sha12>.<ext>`` - identical bytes promoted twice land
  on one file within a category, so re-accepting the same picture wastes no
  disk.  The category is part of the path, so the same picture legitimately
  appears once per category folder it was accepted into.
* **Rows** are appended per promotion: the *provenance* differs (different
  material, different batch) even when the bytes do not, which is exactly what
  the model docstring promises.

Reads never leak absolute paths: :meth:`ImageLibraryService.read_item`
resolves relative to ``image-library/`` through
:func:`app.utils.files.ensure_within`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.config.logging import get_logger
from app.models.image import MaterialImage
from app.models.image_library import ImageLibraryItem
from app.models.material import Material
from app.utils.files import atomic_write_bytes, ensure_within, relative_posix
from app.utils.hashing import sha256_bytes

logger = get_logger(__name__)


class ImageLibraryService:
    """Promotion, lookup and reads for the local image library."""

    def __init__(self, root: str | Path | None = None) -> None:
        settings = get_settings()
        self.root = Path(root) if root is not None else settings.image_library_dir
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Promotion
    # ------------------------------------------------------------------
    async def promote(
        self,
        session: AsyncSession,
        image: MaterialImage,
        material: Material,
        *,
        category: str | None = None,
        payload: bytes | None = None,
    ) -> ImageLibraryItem:
        """Copy an accepted image into its category folder and index it.

        Args:
            payload: raw bytes; when ``None`` the bytes are read from the
                cache path already recorded on ``image.storage_path``.
            category: overrides ``material.category`` (rarely needed).
        """
        cat = category or material.category or "Uncategorised"
        category_dir = self.root / cat
        category_dir.mkdir(parents=True, exist_ok=True)

        if payload is None:
            cache_root = get_settings().image_cache_dir
            payload = ensure_within(cache_root, image.storage_path).read_bytes()

        digest = image.sha256 or sha256_bytes(payload)
        extension = image.extension or ".png"
        filename = f"{digest[:12]}{extension}"
        target = category_dir / filename
        if not target.exists():
            atomic_write_bytes(target, payload)

        library_path = relative_posix(target, self.root)
        item = ImageLibraryItem(
            material_id=material.id,
            image_id=image.id,
            category=cat,
            library_path=library_path,
            filename=filename,
            sha256=digest,
            byte_size=len(payload),
            mime_type=image.mime_type,
            material_code=material.material_code,
            description=(material.description or "")[:1000],
            source_url=None,
            source_domain=image.source_domain,
        )
        # ``source_url`` wants the full URL; the image row keeps only hashes of
        # it, so fall back to the search result when one is linked.
        if image.search_result_id is not None:
            from app.models.search_result import SearchResult

            result = await session.get(SearchResult, image.search_result_id)
            if result is not None:
                item.source_url = result.image_url

        image.library_path = library_path
        session.add(item)
        await session.flush()
        logger.info(
            "image_library.promoted",
            image_id=image.id,
            category=cat,
            library_path=library_path,
        )
        return item

    # ------------------------------------------------------------------
    # Lookup / reads
    # ------------------------------------------------------------------
    async def get_item(self, session: AsyncSession, item_id: int) -> ImageLibraryItem | None:
        return await session.get(ImageLibraryItem, item_id)

    async def list_items(
        self,
        session: AsyncSession,
        *,
        category: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ImageLibraryItem], int]:
        """Paged library listing with optional category/code/description filter."""
        query = select(ImageLibraryItem)
        if category:
            query = query.where(ImageLibraryItem.category == category)
        if search:
            pattern = f"%{search}%"
            query = query.where(
                ImageLibraryItem.description.like(pattern)
                | ImageLibraryItem.material_code.like(pattern)
            )
        total = (
            await session.execute(select(func.count()).select_from(query.subquery()))
        ).scalar_one()
        rows = (
            await session.execute(
                query.order_by(
                    ImageLibraryItem.created_at.desc(), ImageLibraryItem.id.desc()
                )
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), int(total)

    def resolve_item(self, item: ImageLibraryItem) -> Path:
        """Absolute path of a library row's file (traversal-guarded)."""
        return ensure_within(self.root, item.library_path)

    def read_item(self, item: ImageLibraryItem) -> bytes:
        return self.resolve_item(item).read_bytes()

    def categories(self) -> list[str]:
        """Category folders that actually exist on disk."""
        return sorted(entry.name for entry in self.root.iterdir() if entry.is_dir())


def image_library_service() -> ImageLibraryService:
    """The library service rooted at the configured ``image-library/``."""
    return ImageLibraryService()


__all__ = ["ImageLibraryService", "image_library_service"]

