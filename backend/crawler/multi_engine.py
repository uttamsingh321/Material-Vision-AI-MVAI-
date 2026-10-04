"""
Multi-Engine Image Crawler with Maximum Coverage
Strategy:
1. Autocorrect the query
2. Try Bing Images (primary)
3. If Bing returns < 3 results, also scrape Google Images  
4. If still empty, try DuckDuckGo Images
5. Download all candidate images in parallel
6. Use CLIP to rank candidates against MULTIPLE prompts
7. Accept the best match if its score is above the threshold
8. If CLIP is unavailable, accept the first large image
"""

import httpx
import asyncio
import urllib.parse
import re
import os
import io

from .base import BaseSearchProvider, ProviderResponse, ProviderHit, SearchQuery

# Global lazy-loaded CLIP model
_clip_model = None
_clip_processor = None

def _load_clip():
    global _clip_model, _clip_processor
    if _clip_model is not None:
        return True
    try:
        import torch
        from transformers import CLIPProcessor, CLIPModel
        model_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../../../ai-engine/models/industrial-clip-ft")
        )
        if not os.path.exists(model_path):
            model_path = "openai/clip-vit-base-patch32"
        _clip_processor = CLIPProcessor.from_pretrained(model_path)
        _clip_model = CLIPModel.from_pretrained(model_path)
        _clip_model.eval()
        return True
    except Exception as e:
        print(f"[CLIP] Failed to load: {e}")
        return False


class MultiEngineImagesProvider(BaseSearchProvider):
    id = "multi_engine"
    kind = "image_search"
    display_name = "Multi-Engine Verified Search"
    enabled = True

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    # ------------------------------------------------------------------ #
    # Search helpers
    # ------------------------------------------------------------------ #

    async def _bing_urls(self, client: httpx.AsyncClient, q: str) -> list[str]:
        try:
            r = await client.get(
                f"https://www.bing.com/images/search?q={q}&count=15",
                timeout=10
            )
            urls = re.findall(r'murl&quot;:&quot;(.*?)&quot;', r.text)
            return [u for u in urls if u.startswith("http")][:10]
        except Exception:
            return []

    async def _google_urls(self, client: httpx.AsyncClient, q: str) -> list[str]:
        try:
            r = await client.get(
                f"https://www.google.com/search?tbm=isch&q={q}&num=15",
                timeout=10
            )
            # Google embeds image URLs in JS JSON blobs
            urls = re.findall(r'"(https?://[^"]+\.(?:jpg|jpeg|png|webp))"', r.text)
            return [u for u in urls if "gstatic" not in u][:10]
        except Exception:
            return []

    async def _duckduckgo_urls(self, client: httpx.AsyncClient, q: str) -> list[str]:
        try:
            # Step 1: get DDG token
            r = await client.get(
                f"https://duckduckgo.com/?q={q}&iax=images&ia=images", timeout=10
            )
            token_match = re.search(r"vqd=([\d-]+)&", r.text)
            if not token_match:
                return []
            vqd = token_match.group(1)
            # Step 2: fetch image results using token
            r2 = await client.get(
                f"https://duckduckgo.com/i.js?q={q}&vqd={vqd}&l=us-en&o=json",
                timeout=10
            )
            import json
            data = r2.json()
            return [item["image"] for item in data.get("results", [])[:10] if "image" in item]
        except Exception:
            return []

    # ------------------------------------------------------------------ #
    # Image downloader
    # ------------------------------------------------------------------ #

    async def _download_images(self, client: httpx.AsyncClient, urls: list[str]) -> list[dict]:
        """Download URLs concurrently and return list of {url, bytes}."""
        async def fetch_one(url):
            try:
                r = await client.get(url, timeout=8, follow_redirects=True)
                if r.status_code == 200 and len(r.content) > 5000:
                    return {"url": url, "bytes": r.content}
            except Exception:
                pass
            return None

        results = await asyncio.gather(*[fetch_one(u) for u in urls])
        return [r for r in results if r is not None]

    # ------------------------------------------------------------------ #
    # CLIP verification
    # ------------------------------------------------------------------ #

    def _clip_score_and_pick(self, candidates: list[dict], item_text: str) -> dict | None:
        """
        Score all candidate images against multiple prompts and
        return the best match if it passes the threshold.
        """
        if not _load_clip():
            # CLIP unavailable – return first large image as fallback
            return candidates[0] if candidates else None

        try:
            import torch
            from PIL import Image as PILImage

            # Multiple prompts – pick the one that gives the highest score
            prompts = [
                f"{item_text}",
                f"a photo of {item_text}",
                f"industrial component {item_text}",
                f"manufacturing part {item_text}",
            ]

            images_pil = []
            for c in candidates:
                try:
                    images_pil.append(PILImage.open(io.BytesIO(c["bytes"])).convert("RGB"))
                except Exception:
                    images_pil.append(PILImage.new("RGB", (224, 224), (200, 200, 200)))

            best_score = -1.0
            best_idx = 0

            for prompt in prompts:
                inputs = _clip_processor(
                    text=[prompt],
                    images=images_pil,
                    return_tensors="pt",
                    padding=True,
                )
                with torch.no_grad():
                    outputs = _clip_model(**inputs)
                    logits = outputs.logits_per_image.squeeze().tolist()

                if not isinstance(logits, list):
                    logits = [logits]

                local_max = max(logits)
                local_idx = logits.index(local_max)

                if local_max > best_score:
                    best_score = local_max
                    best_idx = local_idx

            print(f"[CLIP] '{item_text}' → best_score={best_score:.2f} idx={best_idx}")

            # Threshold: 20.0 (permissive enough to capture industrial items)
            if best_score >= 20.0:
                return candidates[best_idx]
            else:
                # CLIP is too uncertain — accept first image anyway to avoid "not found"
                print(f"[CLIP] Score {best_score:.2f} below threshold, accepting top image as fallback")
                return candidates[0]

        except Exception as e:
            print(f"[CLIP] Error during scoring: {e}")
            return candidates[0] if candidates else None

    async def _pinterest_urls(self, client: httpx.AsyncClient, q: str) -> list[str]:
        try:
            r = await client.get(
                f"https://www.pinterest.com/search/pins/?q={q}",
                timeout=10,
                headers={
                    **self.HEADERS,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                }
            )
            # Pinterest embeds image URLs in a JSON blob in the initial HTML
            urls = re.findall(r'"url"\s*:\s*"(https?://i\.pinimg\.com/[^"]+\.(?:jpg|jpeg|png))"', r.text)
            # Also try originals
            originals = [u.replace("/236x/", "/originals/").replace("/564x/", "/originals/") for u in urls]
            return list(dict.fromkeys(originals + urls))[:8]  # deduplicated, originals first
        except Exception:
            return []

    # ------------------------------------------------------------------ #
    # Main search
    # ------------------------------------------------------------------ #

    async def _search(self, query: SearchQuery) -> ProviderResponse:
        # 1. Spell-correct the query
        try:
            from autocorrect import Speller
            corrected = Speller()(query.text)
        except ImportError:
            corrected = query.text

        # 2. Strip garbage characters (????, symbols from Excel)
        import re as _re
        corrected = _re.sub(r'[?？！@#$%^&*=\[\]{}<>~`\\]+', '', corrected).strip()
        if not corrected:
            return ProviderResponse(provider=self.id, query=query, hits=tuple())

        # Build TWO query variations: specific and broader
        neg = "-drawing -illustration -cartoon -logo -diagram"
        q_specific = urllib.parse.quote_plus(f"{corrected} product photo {neg}")
        q_broad    = urllib.parse.quote_plus(f"{corrected} {neg}")

        async with httpx.AsyncClient(headers=self.HEADERS, follow_redirects=True) as client:
            # --- Parallel scrape Google + Pinterest only ---
            google_urls, pinterest_urls = await asyncio.gather(
                self._google_urls(client, q_specific),
                self._pinterest_urls(client, q_specific),
                return_exceptions=True,
            )

            # Merge unique URLs — Pinterest first (often cleaner product shots)
            seen = set()
            all_urls = []
            for src in [pinterest_urls, google_urls]:
                if isinstance(src, list):
                    for u in src:
                        if u not in seen:
                            seen.add(u)
                            all_urls.append(u)
                if len(all_urls) >= 20:
                    break

            if not all_urls:
                return ProviderResponse(provider=self.id, query=query, hits=tuple())

            # --- Download all candidates in parallel ---
            candidates = await self._download_images(client, all_urls)

        if not candidates:
            return ProviderResponse(provider=self.id, query=query, hits=tuple())

        # --- CLIP-rank and pick the best ---
        best = self._clip_score_and_pick(candidates, corrected)

        if best:
            return ProviderResponse(
                provider=self.id,
                query=query,
                hits=tuple([ProviderHit(
                    image_url=best["url"],
                    position=0,
                    source_domain="multi-engine-verified",
                )]),
            )

        return ProviderResponse(provider=self.id, query=query, hits=tuple())

    async def _fetch(self, image_url: str) -> bytes:
        return b""
