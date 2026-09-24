"""MVAI AI engine.

Deterministic, dependency-free modules that turn a raw material description into
the structured signals the pipeline needs:

``brand_detector``       brand resolution from text, codes and domains
``description_parser``   free text -> brand / model / category / search query
``material_classifier``  rule-based placement in the image-library taxonomy
``confidence_engine``    weighted evidence -> overall / band / decision
``duplicate_detector``   sha256 + perceptual + source-URL deduplication

Import these through ``backend.app.ai_engine`` (``ai_engine.load(...)``) rather
than by filesystem path - this directory is named ``ai-engine`` to match the
project specification, and hyphenated names cannot appear in an ``import``
statement.  See ADR-008.
"""

from __future__ import annotations

__all__ = [
    "brand_detector",
    "confidence_engine",
    "description_parser",
    "duplicate_detector",
    "material_classifier",
]
