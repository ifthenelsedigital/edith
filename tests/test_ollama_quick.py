import httpx, asyncio

async def test():
    c = httpx.AsyncClient(base_url="http://localhost:11434", timeout=180)
    print("Sending request to phi3:mini (may take a minute on first load)...")
    r = await c.post("/api/chat", json={
        "model": "phi3:mini",
        "messages": [{"role": "user", "content": "Say hello in exactly 5 words"}],
        "stream": False,
        "options": {"num_predict": 30},
    })
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text[:500]}")
    await c.aclose()

asyncio.run(test())
