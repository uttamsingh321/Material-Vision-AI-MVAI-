"""Bridge that exposes the top-level ``ai-engine/`` directory as ``mvai_ai``.

Why this exists
---------------
The mandated repository layout uses hyphenated folder names (``ai-engine/``,
``crawler/``, ``verifier/``) to match the specification.  Python identifiers
cannot contain a hyphen, so ``import ai-engine`` is a syntax error and ``import
ai_engine`` would resolve to a *different* directory.

Rather than duplicate the code or silently rename the folder, :func:`load`
registers the directory in ``sys.modules`` under the alias ``mvai_ai`` using a
file-location spec with explicit ``submodule_search_locations``.  After that,
ordinary imports work::

    from app.ai_engine import ai_engine
    brand_detector = ai_engine.load("brand_detector")
    brand_detector.detect_brand("Schneider LC1D18")

Registration is idempotent, so the cost is paid once per process.  Importing
through this module is the *only* supported way to reach those packages - see
ADR-008.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

#: ``<repo>/backend/app/ai_engine.py`` -> ``<repo>``
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
BACKEND_ROOT: Path = REPO_ROOT / "backend"

#: Directory name -> import alias.  Applied identically to all three.
PACKAGE_ALIASES: dict[str, str] = {
    "ai-engine": "mvai_ai",
    "crawler": "mvai_crawler",
    "verifier": "mvai_verifier",
}


class SiblingPackageError(ImportError):
    """A sibling package directory is missing or malformed."""


def _register(directory_name: str) -> str:
    """Register ``<repo>/<directory_name>`` under its import alias."""
    alias = PACKAGE_ALIASES[directory_name]
    if alias in sys.modules:
        return alias

    package_dir = REPO_ROOT / directory_name
    initialiser = package_dir / "__init__.py"
    if not initialiser.is_file():
        raise SiblingPackageError(
            f"cannot register {directory_name!r}: {initialiser} is missing"
        )

    spec = importlib.util.spec_from_file_location(
        alias,
        initialiser,
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise SiblingPackageError(f"cannot build an import spec for {package_dir}")

    module = importlib.util.module_from_spec(spec)
    # Register before executing so circular imports inside the package resolve.
    sys.modules[alias] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(alias, None)
        raise
    return alias


def load(module_name: str, *, package: str = "ai-engine") -> ModuleType:
    """Import ``<package>/<module_name>.py`` and return the module object.

    Args:
        module_name: file stem inside the package, e.g. ``"brand_detector"``.
        package: one of the keys of :data:`PACKAGE_ALIASES`.

    Raises:
        SiblingPackageError: for an unknown package, or a missing module.
    """
    if package not in PACKAGE_ALIASES:
        raise SiblingPackageError(
            f"unknown package {package!r}; expected one of {sorted(PACKAGE_ALIASES)}"
        )

    alias = _register(package)
    try:
        return importlib.import_module(f"{alias}.{module_name}")
    except ModuleNotFoundError as exc:
        raise SiblingPackageError(
            f"module {module_name!r} not found in {package!r} ({exc})"
        ) from exc


def available_modules(*, package: str = "ai-engine") -> tuple[str, ...]:
    """File stems of the importable modules inside ``package``."""
    if package not in PACKAGE_ALIASES:
        raise SiblingPackageError(f"unknown package {package!r}")
    package_dir = REPO_ROOT / package
    if not package_dir.is_dir():
        return ()
    return tuple(
        sorted(
            path.stem
            for path in package_dir.glob("*.py")
            if path.stem != "__init__" and not path.stem.startswith("_")
        )
    )


# --- typed convenience accessors -------------------------------------------


def brand_detector() -> ModuleType:
    """``ai-engine/brand_detector.py``."""
    return load("brand_detector")


def description_parser() -> ModuleType:
    """``ai-engine/description_parser.py``."""
    return load("description_parser")


def material_classifier() -> ModuleType:
    """``ai-engine/material_classifier.py``."""
    return load("material_classifier")


def duplicate_detector() -> ModuleType:
    """``ai-engine/duplicate_detector.py``."""
    return load("duplicate_detector")


def confidence_engine() -> ModuleType:
    """``ai-engine/confidence_engine.py``."""
    return load("confidence_engine")


def ocr_reader() -> ModuleType:
    """``ai-engine/ocr_reader.py`` (interface only in Phase 1)."""
    return load("ocr_reader")


def image_similarity() -> ModuleType:
    """``ai-engine/image_similarity.py`` (interface only in Phase 1)."""
    return load("image_similarity")


def vision_validator() -> ModuleType:
    """``ai-engine/vision_validator.py`` (interface only in Phase 1)."""
    return load("vision_validator")


def background_remover() -> ModuleType:
    """``ai-engine/background_remover.py`` (interface only in Phase 1)."""
    return load("background_remover")


def crawler(module_name: str) -> ModuleType:
    """Any module inside ``crawler/``, e.g. ``crawler("google_search")``."""
    return load(module_name, package="crawler")


def verifier(module_name: str) -> ModuleType:
    """Any module inside ``verifier/``, e.g. ``verifier("candidate_ranker")``."""
    return load(module_name, package="verifier")


__all__ = [
    "BACKEND_ROOT",
    "PACKAGE_ALIASES",
    "REPO_ROOT",
    "SiblingPackageError",
    "available_modules",
    "background_remover",
    "brand_detector",
    "confidence_engine",
    "crawler",
    "description_parser",
    "duplicate_detector",
    "image_similarity",
    "load",
    "material_classifier",
    "ocr_reader",
    "verifier",
    "vision_validator",
]
