import httpx
import asyncio
import urllib.parse
import re
import base64
import os
from .base import BaseSearchProvider, ProviderResponse, ProviderHit, SearchQuery

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

class MultiEngineImagesProvider(BaseSearchProvider):
    id = "multi_engine"
    kind = "image_search"
    display_name = "Gemini Vision Verified Search"
    enabled = True

    async def _search(self, query: SearchQuery) -> ProviderResponse:
        negative_keywords = "-person -people -human -worker -man -woman -face -stock -landscape -beach -scenery -nature -sketch -drawing -illustration -cartoon -logo"
        q = urllib.parse.quote_plus(f"{query.text} industrial component {negative_keywords}")
        
        async def fetch_bing(client):
            try:
                r = await client.get(f"https://www.bing.com/images/search?q={q}", timeout=8)
                urls = re.findall(r'murl&quot;:&quot;(.*?)&quot;', r.text)
                return urls[:3]
            except: return []
            
        async def fetch_google(client):
            try:
                r = await client.get(f"https://www.google.com/search?q={q}&tbm=isch", timeout=8)
                urls = re.findall(r'\["(http[s]?://[^"]+?\.(?:jpg|png|jpeg))"', r.text)
                return urls[:3]
            except: return []

        async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}) as client:
            b_urls, g_urls = await asyncio.gather(fetch_bing(client), fetch_google(client))
            
            # Combine and deduplicate
            all_urls = []
            for u in b_urls + g_urls:
                if u not in all_urls: all_urls.append(u)
            
            all_urls = all_urls[:4] # Take top 4 max
            if not all_urls:
                return ProviderResponse(provider=self.id, query=query, hits=tuple())

            # Download images for Gemini
            valid_images = []
            for url in all_urls:
                try:
                    img_r = await client.get(url, timeout=5)
                    if img_r.status_code == 200:
                        b64 = base64.b64encode(img_r.content).decode('utf-8')
                        mime = img_r.headers.get("content-type", "image/jpeg")
                        valid_images.append({"url": url, "b64": b64, "mime": mime})
                except: pass

            if not valid_images:
                return ProviderResponse(provider=self.id, query=query, hits=tuple())
                
            # Ask Gemini
            parts = [{"text": f"You are an industrial QA AI. Look at the following {len(valid_images)} images. Which image perfectly shows the industrial manufacturing component: '{query.text}'? Reject any images that are humans, animals, sketches, landscapes, or logos. Reply ONLY with the number of the image (e.g., 1, 2, 3). If NONE of them are valid industrial components, reply with 0."}]
            
            for idx, img in enumerate(valid_images):
                parts.append({"text": f"Image {idx + 1}:"})
                parts.append({
                    "inline_data": {
                        "mime_type": img["mime"],
                        "data": img["b64"]
                    }
                })
            
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.0}}
            
            # Retry logic for Gemini API (Free tier has limits)
            for attempt in range(3):
                try:
                    resp = await client.post(gemini_url, json=payload, timeout=15)
                    if resp.status_code == 429:
                        await asyncio.sleep(5)
                        continue
                        
                    resp_data = resp.json()
                    text_resp = resp_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    
                    match = re.search(r'\d+', text_resp)
                    if match:
                        chosen_idx = int(match.group(0)) - 1
                        if 0 <= chosen_idx < len(valid_images):
                            chosen_url = valid_images[chosen_idx]["url"]
                            return ProviderResponse(provider=self.id, query=query, hits=tuple([ProviderHit(image_url=chosen_url, position=0, source_domain="gemini-verified")]))
                    break # valid response but no match or 0
                except Exception as e:
                    await asyncio.sleep(2)
                    
            # If Gemini fails or picks 0, fallback to None
            return ProviderResponse(provider=self.id, query=query, hits=tuple())

    async def _fetch(self, image_url: str) -> bytes:
        return b""
