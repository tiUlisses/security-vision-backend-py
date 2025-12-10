import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_positions_current_basic_flow():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # 1) building
        b = {"name": "Predio Mapa", "code": "P_MAPA", "description": "Predio para mapa"}
        rb = await ac.post("/api/v1/buildings/", json=b)
        assert rb.status_code == 201, rb.text
        building = rb.json()

        # 2) floor
        f = {
            "building_id": building["id"],
            "name": "Andar 1",
            "level": 1,
            "description": "Andar 1",
        }
        rf = await ac.post("/api/v1/floors/", json=f)
        assert rf.status_code == 201, rf.text
        floor = rf.json()

        # 3) floor_plan
        fp = {
            "floor_id": floor["id"],
            "name": "Planta A1",
            "image_url": "https://example.com/a1.png",
            "width": 1000.0,
            "height": 800.0,
            "description": "Mapa A1",
        }
        rfp = await ac.post("/api/v1/floor-plans/", json=fp)
        assert rfp.status_code == 201, rfp.text
        floor_plan = rfp.json()

        # 4) device (gateway) posicionado
        d = {
            "floor_plan_id": floor_plan["id"],
            "name": "GW Setor A",
            "code": "GW_SETOR_A",
            "type": "BLE_GATEWAY",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "description": "Gateway setor A",
            "pos_x": 100.0,
            "pos_y": 200.0,
        }
        rd = await ac.post("/api/v1/devices/", json=d)
        assert rd.status_code == 201, rd.text
        device = rd.json()

        # 5) person
        p = {
            "full_name": "Joao Mapa",
            "document_id": "12345678900",
            "email": "joao@example.com",
            "active": True,
            "notes": "Teste mapa",
        }
        rp = await ac.post("/api/v1/people/", json=p)
        assert rp.status_code == 201, rp.text
        person = rp.json()

        # 6) tag da pessoa
        t = {
            "mac_address": "11:22:33:44:55:66",
            "label": "Tag Joao",
            "person_id": person["id"],
            "active": True,
            "notes": None,
        }
        rt = await ac.post("/api/v1/tags/", json=t)
        assert rt.status_code == 201, rt.text
        tag = rt.json()

        # 7) collection_log simulando detecção
        cl = {
            "device_id": device["id"],
            "tag_id": tag["id"],
            "rssi": -65,
            "raw_payload": '{"demo": true}',
        }
        rcl = await ac.post("/api/v1/collection-logs/", json=cl)
        assert rcl.status_code == 201, rcl.text

        # 8) chama positions/current filtrando pela planta
        rpos = await ac.get(
            f"/api/v1/positions/current?floor_plan_id={floor_plan['id']}"
        )
        assert rpos.status_code == 200, rpos.text
        positions = rpos.json()
        assert len(positions) == 1

        loc = positions[0]
        assert loc["person_id"] == person["id"]
        assert loc["device_id"] == device["id"]
        assert loc["floor_plan_id"] == floor_plan["id"]
        assert loc["floor_plan_image_url"] == floor_plan["image_url"]
        assert loc["device_pos_x"] == d["pos_x"]
        assert loc["device_pos_y"] == d["pos_y"]
