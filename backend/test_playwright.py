import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        await page.goto("https://www.google.com/search?tbm=isch&q=ESD+FOAM")
        await page.wait_for_timeout(2000)
        imgs = await page.evaluate("() => Array.from(document.querySelectorAll('img')).map(img => img.src).filter(src => src.startsWith('http') || src.startsWith('data:image'))")
        print(imgs[:3])
        await browser.close()

asyncio.run(main())
