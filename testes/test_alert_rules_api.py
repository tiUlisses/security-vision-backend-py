import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_alert_rule_crud_with_filters():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # building
        b = {"name": "Predio Alertas", "code": "P_ALERT", "description": "Predio alertas"}
        rb = await ac.post("/api/v1/buildings/", json=b)
        assert rb.status_code == 201
        building_id = rb.json()["id"]

        # floor
        f = {
            "building_id": building_id,
            "name": "Andar 1",
            "level": 1,
            "description": "Andar 1",
        }
        rf = await ac.post("/api/v1/floors/", json=f)
        assert rf.status_code == 201
        floor_id = rf.json()["id"]

        # floor_plan
        fp = {
            "floor_id": floor_id,
            "name": "Planta A1",
            "image_url": "https://example.com/a1.png",
            "width": 1000.0,
            "height": 800.0,
            "description": "Mapa A1",
        }
        rfp = await ac.post("/api/v1/floor-plans/", json=fp)
        assert rfp.status_code == 201
        floor_plan_id = rfp.json()["id"]

        # device (gateway)
        d = {
            "floor_plan_id": floor_plan_id,
            "name": "GW Cofre",
            "code": "GW_COFRE",
            "type": "BLE_GATEWAY",
            "mac_address": "10:20:30:40:50:60",
            "description": "Gateway do cofre",
            "pos_x": 100.0,
            "pos_y": 200.0,
        }
        rd = await ac.post("/api/v1/devices/", json=d)
        assert rd.status_code == 201
        device_id = rd.json()["id"]

        # person group
        g = {"name": "Visitantes Restritos", "description": "Nao podem entrar no cofre"}
        rg = await ac.post("/api/v1/person-groups/", json=g)
        assert rg.status_code == 201
        group_id = rg.json()["id"]

        # alert rule
        rule_payload = {
            "name": "Visitantes nao podem cofre",
            "description": "Regra cofre",
            "rule_type": "FORBIDDEN_SECTOR",
            "group_id": group_id,
            "device_id": device_id,
            "max_dwell_seconds": None,
            "is_active": True,
        }
        rr = await ac.post("/api/v1/alert-rules/", json=rule_payload)
        assert rr.status_code == 201, rr.text
        rule = rr.json()
        rule_id = rule["id"]

        # list
        rlist = await ac.get("/api/v1/alert-rules/")
        assert rlist.status_code == 200
        rules = rlist.json()
        assert any(r["id"] == rule_id for r in rules)

        # filter by type
        rlist2 = await ac.get("/api/v1/alert-rules/?rule_type=FORBIDDEN_SECTOR")
        assert rlist2.status_code == 200
        rules2 = rlist2.json()
        assert any(r["id"] == rule_id for r in rules2)

        # get
        rget = await ac.get(f"/api/v1/alert-rules/{rule_id}")
        assert rget.status_code == 200

        # update
        upd = {"is_active": False}
        rupd = await ac.put(f"/api/v1/alert-rules/{rule_id}", json=upd)
        assert rupd.status_code == 200
        assert rupd.json()["is_active"] is False

        # delete
        rdel = await ac.delete(f"/api/v1/alert-rules/{rule_id}")
        assert rdel.status_code == 204
