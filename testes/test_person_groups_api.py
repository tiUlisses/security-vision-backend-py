import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_person_group_crud():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # create
        payload = {"name": "Visitantes", "description": "Grupo de visitantes"}
        resp = await ac.post("/api/v1/person-groups/", json=payload)
        assert resp.status_code == 201, resp.text
        group = resp.json()
        group_id = group["id"]

        # list
        resp_list = await ac.get("/api/v1/person-groups/")
        assert resp_list.status_code == 200
        groups = resp_list.json()
        assert any(g["id"] == group_id for g in groups)

        # get
        resp_get = await ac.get(f"/api/v1/person-groups/{group_id}")
        assert resp_get.status_code == 200
        assert resp_get.json()["name"] == "Visitantes"

        # update
        upd = {"description": "Visitantes externos"}
        resp_upd = await ac.put(f"/api/v1/person-groups/{group_id}", json=upd)
        assert resp_upd.status_code == 200
        assert resp_upd.json()["description"] == "Visitantes externos"

        # delete
        resp_del = await ac.delete(f"/api/v1/person-groups/{group_id}")
        assert resp_del.status_code == 204

        # get after delete
        resp_get2 = await ac.get(f"/api/v1/person-groups/{group_id}")
        assert resp_get2.status_code == 404
