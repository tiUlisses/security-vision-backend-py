# tests/test_floorplan_devices.py
import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_list_devices_for_floor_plan():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # cria building
        b_payload = {
            "name": "Predio Teste",
            "code": "PREDIO_TESTE",
            "description": "Predio de teste",
        }
        resp_b = await ac.post("/api/v1/buildings/", json=b_payload)
        assert resp_b.status_code == 201, resp_b.text
        building = resp_b.json()

        # cria floor
        f_payload = {
            "building_id": building["id"],
            "name": "Andar 1",
            "level": 1,
            "description": "Primeiro andar",
        }
        resp_f = await ac.post("/api/v1/floors/", json=f_payload)
        assert resp_f.status_code == 201, resp_f.text
        floor = resp_f.json()

        # cria floor_plan
        fp_payload = {
            "floor_id": floor["id"],
            "name": "Planta Andar 1",
            "image_url": "https://example.com/andar1.png",
            "width": 1000.0,
            "height": 800.0,
            "description": "Mapa do primeiro andar",
        }
        resp_fp = await ac.post("/api/v1/floor-plans/", json=fp_payload)
        assert resp_fp.status_code == 201, resp_fp.text
        floor_plan = resp_fp.json()

        # cria dois devices (gateways) nessa planta
        d1_payload = {
            "floor_plan_id": floor_plan["id"],
            "name": "Gateway 1",
            "code": "GW1",
            "type": "BLE_GATEWAY",
            "mac_address": "11:22:33:44:55:66",
            "description": "Setor A",
            "pos_x": 100.0,
            "pos_y": 200.0,
        }
        d2_payload = {
            "floor_plan_id": floor_plan["id"],
            "name": "Gateway 2",
            "code": "GW2",
            "type": "BLE_GATEWAY",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "description": "Setor B",
            "pos_x": 300.0,
            "pos_y": 400.0,
        }

        resp_d1 = await ac.post("/api/v1/devices/", json=d1_payload)
        resp_d2 = await ac.post("/api/v1/devices/", json=d2_payload)
        assert resp_d1.status_code == 201, resp_d1.text
        assert resp_d2.status_code == 201, resp_d2.text

        # chama o endpoint novo
        resp_list = await ac.get(f"/api/v1/floor-plans/{floor_plan['id']}/devices")
        assert resp_list.status_code == 200, resp_list.text
        devices = resp_list.json()
        macs = {d["mac_address"] for d in devices}
        assert "11:22:33:44:55:66" in macs
        assert "AA:BB:CC:DD:EE:FF" in macs
