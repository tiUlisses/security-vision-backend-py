import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_create_and_list_buildings():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # cria um prédio
        payload = {
            "name": "Prédio Principal",
            "code": "HQ",
            "description": "Prédio sede da empresa",
        }
        resp_create = await ac.post("/api/v1/buildings/", json=payload)
        assert resp_create.status_code == 201, resp_create.text
        data = resp_create.json()
        assert data["id"] is not None
        assert data["name"] == payload["name"]
        assert data["code"] == payload["code"]

        # lista prédios
        resp_list = await ac.get("/api/v1/buildings/")
        assert resp_list.status_code == 200, resp_list.text
        items = resp_list.json()
        assert any(b["code"] == "HQ" for b in items)

        # busca por id
        building_id = data["id"]
        resp_get = await ac.get(f"/api/v1/buildings/{building_id}")
        assert resp_get.status_code == 200
        b = resp_get.json()
        assert b["id"] == building_id

        # update
        resp_update = await ac.put(
            f"/api/v1/buildings/{building_id}",
            json={"description": "Atualizada"},
        )
        assert resp_update.status_code == 200
        updated = resp_update.json()
        assert updated["description"] == "Atualizada"

        # delete
        resp_delete = await ac.delete(f"/api/v1/buildings/{building_id}")
        assert resp_delete.status_code == 204

        # depois de deletar, não deve encontrar
        resp_get_404 = await ac.get(f"/api/v1/buildings/{building_id}")
        assert resp_get_404.status_code == 404
