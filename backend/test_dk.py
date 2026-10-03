import asyncio
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
import httpx

client_id = os.getenv("DIGIKEY_CLIENT_ID")
client_secret = os.getenv("DIGIKEY_CLIENT_SECRET")
print("Client ID present:", bool(client_id))

async def test():
    # Step 1: Get token
    async with httpx.AsyncClient(timeout=10) as client:
        token_resp = await client.post(
            "https://api.digikey.com/v1/oauth2/token",
            data={"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"}
        )
        print("Token status:", token_resp.status_code)
        if token_resp.status_code != 200:
            print("Token error:", token_resp.text)
            return
        token = token_resp.json()["access_token"]
        print("Got token:", token[:12] + "...")

    # Step 2: Search
    async with httpx.AsyncClient(timeout=10) as client:
        search_resp = await client.post(
            "https://api.digikey.com/Search/v3/Products/Keyword",
            headers={
                "Authorization": f"Bearer {token}",
                "X-DIGIKEY-Client-Id": client_id,
                "Content-Type": "application/json"
            },
            json={"Keywords": "ELECTROMAGNETIC RELAY", "RecordCount": 1}
        )
        print("Search status:", search_resp.status_code)
        print("Response:", search_resp.text[:500])

asyncio.run(test())
