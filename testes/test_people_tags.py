import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_create_person_and_tag_association():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # cria person
        person_payload = {
            "full_name": "João da Silva",
            "document_id": "12345678900",
            "email": "joao@example.com",
            "active": True,
            "notes": "Funcionário teste",
        }
        resp_p = await ac.post("/api/v1/people/", json=person_payload)
        assert resp_p.status_code == 201, resp_p.text
        person = resp_p.json()
        person_id = person["id"]

        # cria tag vinculada
        tag_payload = {
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "label": "Tag de teste",
            "person_id": person_id,
            "active": True,
            "notes": "Tag principal",
        }
        resp_t = await ac.post("/api/v1/tags/", json=tag_payload)
        assert resp_t.status_code == 201, resp_t.text
        tag = resp_t.json()
        tag_id = tag["id"]
        assert tag["person_id"] == person_id

        # busca tag por MAC
        resp_by_mac = await ac.get("/api/v1/tags/by-mac/AA:BB:CC:DD:EE:FF")
        assert resp_by_mac.status_code == 200
        tag_mac = resp_by_mac.json()
        assert tag_mac["id"] == tag_id

        # lista tags filtrando por person_id
        resp_list = await ac.get(f"/api/v1/tags/?person_id={person_id}")
        assert resp_list.status_code == 200
        items = resp_list.json()
        assert any(t["id"] == tag_id for t in items)
