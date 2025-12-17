# tests/test_person_current_location.py
import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_person_current_location():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # 1) building
        b_payload = {
            "name": "Predio Central",
            "code": "PREDIO_CENTRAL",
            "description": "Predio central",
        }
        resp_b = await ac.post("/api/v1/buildings/", json=b_payload)
        assert resp_b.status_code == 201, resp_b.text
        building = resp_b.json()

        # 2) floor
        f_payload = {
            "building_id": building["id"],
            "name": "Térreo",
            "level": 0,
            "description": "Térreo",
        }
        resp_f = await ac.post("/api/v1/floors/", json=f_payload)
        assert resp_f.status_code == 201, resp_f.text
        floor = resp_f.json()

        # 3) floor_plan
        fp_payload = {
            "floor_id": floor["id"],
            "name": "Planta Térreo",
            "image_url": "https://example.com/terreo.png",
            "width": 800.0,
            "height": 600.0,
            "description": "Mapa térreo",
        }
        resp_fp = await ac.post("/api/v1/floor-plans/", json=fp_payload)
        assert resp_fp.status_code == 201, resp_fp.text
        floor_plan = resp_fp.json()

        # 4) device (gateway)
        d_payload = {
            "floor_plan_id": floor_plan["id"],
            "name": "Gateway Hall de Entrada",
            "code": "GW_HALL",
            "type": "BLE_GATEWAY",
            "mac_address": "00:11:22:33:44:55",
            "description": "Hall de entrada",
            "pos_x": 150.0,
            "pos_y": 250.0,
        }
        resp_d = await ac.post("/api/v1/devices/", json=d_payload)
        assert resp_d.status_code == 201, resp_d.text
        device = resp_d.json()

        # 5) person
        p_payload = {
            "full_name": "Maria Teste",
            "document_id": "99999999999",
            "email": "maria@example.com",
            "active": True,
            "notes": "Colaboradora teste",
        }
        resp_p = await ac.post("/api/v1/people/", json=p_payload)
        assert resp_p.status_code == 201, resp_p.text
        person = resp_p.json()

        # 6) tag vinculada à pessoa
        t_payload = {
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "label": "Tag Maria",
            "person_id": person["id"],
            "active": True,
            "notes": "Tag principal",
        }
        resp_t = await ac.post("/api/v1/tags/", json=t_payload)
        assert resp_t.status_code == 201, resp_t.text
        tag = resp_t.json()

        # 7) collection_log com essa tag e esse device
        cl_payload = {
            "device_id": device["id"],
            "tag_id": tag["id"],
            "rssi": -65,
            "raw_payload": '{"demo": true}',
        }
        resp_cl = await ac.post("/api/v1/collection-logs/", json=cl_payload)
        assert resp_cl.status_code == 201, resp_cl.text

        # 8) chama o endpoint de localização atual
        resp_loc = await ac.get(f"/api/v1/people/{person['id']}/current-location")
        assert resp_loc.status_code == 200, resp_loc.text
        loc = resp_loc.json()

        assert loc["person_id"] == person["id"]
        assert loc["person_full_name"] == "Maria Teste"
        assert loc["device_id"] == device["id"]
        assert loc["device_name"] == "Gateway Hall de Entrada"
        assert loc["floor_plan_id"] == floor_plan["id"]
        assert loc["floor_id"] == floor["id"]
        assert loc["building_id"] == building["id"]
        assert loc["tag_id"] == tag["id"]
        assert loc["tag_mac_address"] == "AA:BB:CC:DD:EE:FF"
