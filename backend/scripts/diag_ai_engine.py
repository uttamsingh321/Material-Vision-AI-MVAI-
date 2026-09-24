"""Ad-hoc diagnostic: prints the raw output of the AI-engine helpers.

Run with ``python -m scripts.diag_ai_engine`` from the backend directory.
Not part of the test suite; kept because these three cases were the ones that
needed manual inspection during development.
"""

from __future__ import annotations

from app.ai_engine import brand_detector, material_classifier


def main() -> None:
    detector = brand_detector()

    print("detect_brand('SKF6205-2RS', 'bearing for conveyor') ->")
    print("   ", detector.detect_brand("SKF6205-2RS", "bearing for conveyor"))
    print("detect_in_text('SKF6205-2RS') ->")
    print("   ", detector.detect_in_text("SKF6205-2RS"))

    for url in (
        "https://www.se.com/in/en/product/LC1D18",
        "https://www.abb.co.in/products",
        "https://example.com/x",
        "https://se.com/x",
        "https://www.rs-online.com/web/p/connectors/1234",
    ):
        print(f"detect_in_url({url!r}) ->", detector.detect_in_url(url))

    print("classify('metal pin') ->", material_classifier().classify("metal pin"))
    print("known categories ->", material_classifier().known_categories())


if __name__ == "__main__":
    main()
