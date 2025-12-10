import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_webhook_crud():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        payload = {
            "name": "Webhook Teste",
            "url": "https://webhook.site/00000000-0000-0000-0000-000000000000",
            "secret_token": "segredo",
            "event_type_filter": "FORBIDDEN_SECTOR",
            "is_active": True,
        }
        r = await ac.post("/api/v1/webhooks/", json=payload)
        assert r.status_code == 201, r.text
        webhook = r.json()
        wid = webhook["id"]

        rlist = await ac.get("/api/v1/webhooks/")
        assert rlist.status_code == 200
        assert any(w["id"] == wid for w in rlist.json())

        rget = await ac.get(f"/api/v1/webhooks/{wid}")
        assert rget.status_code == 200

        rupd = await ac.put(f"/api/v1/webhooks/{wid}", json={"is_active": False})
        assert rupd.status_code == 200
        assert rupd.json()["is_active"] is False

        rdel = await ac.delete(f"/api/v1/webhooks/{wid}")
        assert rdel.status_code == 204
