import asyncio
import httpx
from bs4 import BeautifulSoup

async def main():
    headers = {'User-Agent': 'Mozilla/5.0'}
    html = await httpx.AsyncClient().get('https://www.findchips.com/search/ESD+FOAM', headers=headers)
    soup = BeautifulSoup(html.text, 'html.parser')
    imgs = soup.find_all('img')
    print([img.get('src') for img in imgs][:10])

asyncio.run(main())
