"""Pagination primitives shared by every collection endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Generic, TypeVar

from app.config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PageParams:
    """Validated paging input.  Build it with :meth:`from_query`."""

    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    @classmethod
    def from_query(
        cls,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        *,
        max_page_size: int = MAX_PAGE_SIZE,
    ) -> PageParams:
        """Clamp client input instead of failing - a bad ``page_size`` should
        never turn into a 422 for a dashboard widget."""
        return cls(
            page=max(1, int(page)),
            page_size=min(max(1, int(page_size)), max_page_size),
        )

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    """A slice of results plus the metadata a UI needs to render a pager."""

    items: list[T]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        """:term:`total pages`; ``0`` when there are no items."""
        if self.total <= 0:
            return 0
        return ceil(self.total / self.page_size)

    @property
    def has_next(self) -> bool:
        return self.page < self.pages

    @property
    def has_previous(self) -> bool:
        return self.page > 1


def paginate(items: list[T], total: int, params: PageParams) -> Page[T]:
    """Combine an already-sliced item list with its total count."""
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)
