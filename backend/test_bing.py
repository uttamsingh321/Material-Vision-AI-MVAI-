import asyncio
import httpx
import json
from bs4 import BeautifulSoup

async def main():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    html = await httpx.AsyncClient().get('https://www.bing.com/images/search?q=ESD+FOAM+product', headers=headers)
    soup = BeautifulSoup(html.text, 'html.parser')
    murls = []
    for a in soup.find_all('a', class_='iusc'):
        try:
            murls.append(json.loads(a.get('m', '{}')).get('murl'))
        except:
            pass
    print(murls[:5])

asyncio.run(main())
