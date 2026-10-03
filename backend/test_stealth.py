import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
import json

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await Stealth().apply_stealth_async(page)
        await page.goto("https://www.bing.com/images/search?q=ESD+FOAM+industrial")
        await page.wait_for_timeout(3000)
        imgs = await page.evaluate("() => Array.from(document.querySelectorAll('a.iusc')).map(a => {try {return JSON.parse(a.getAttribute('m')).murl} catch(e) {return null}}).filter(Boolean)")
        print(imgs[:3])
        await browser.close()

asyncio.run(main())
