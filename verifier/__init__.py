"""Verification engine: decides which candidate image is the real product.

Layered evidence, cheapest first:

1. ``candidate_ranker``  - provider/position/URL heuristics, no downloads
2. ``text_similarity``   - title/snippet vs description
3. ``brand_compare``     - brand agreement
4. ``ocr_compare``       - text rendered in the image itself
5. ``confidence_score``  - weighted combination and accept/review/reject call
6. ``human_review``      - escalation for the uncertain middle

Import through ``backend.app.ai_engine.verifier("candidate_ranker")``.  See
ADR-008 for why this directory is not on the normal import path.
"""

from __future__ import annotations

__all__ = ["candidate_ranker"]
