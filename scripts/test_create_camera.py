#!/usr/bin/env python
"""
Script de teste para criar:
- Building
- Floor
- Camera (type=CAMERA)

e acionar o backend para publicar o tópico MQTT /info para o cam-bus.

Exemplo (replicando o seu mosquitto_pub):

python -m scripts.test_create_camera \
  --building PredioA \
  --building-code PredioA \
  --floor Andar1 \
  --code fixa02 \
  --name "Dahua fixa 02" \
  --ip 192.168.91.111 \
  --port 80 \
  --username admin \
  --password h0wb3@123 \
  --manufacturer Dahua \
  --model any
"""

import argparse
import asyncio
import sys

import httpx
from dotenv import load_dotenv

from app.core.config import settings

load_dotenv()  # garante que o .env seja lido antes do settings


async def create_building(
    client: httpx.AsyncClient,
    name: str,
    code: str,
    description: str | None = None,
) -> dict:
    """
    Tenta primeiro localizar o prédio pelo code (GET /buildings/by-code/{code}).
    Se não existir, cria (POST /buildings/).
    """

    # 1) tenta achar pelo code (idempotente)
    print(f"[INFO] Procurando building com code={code} ...")
    resp = await client.get(f"/buildings/by-code/{code}")
    if resp.status_code == 200:
        building = resp.json()
        print(
            f"[OK] Building já existe id={building['id']} "
            f"name={building['name']} code={building['code']}"
        )
        return building
    elif resp.status_code not in (404,):
        print("[ERRO] Falha na consulta de building por code:")
        print("Status:", resp.status_code)
        print("Body:", resp.text)
        resp.raise_for_status()

    # 2) não existe -> cria
    payload = {
        "name": name,
        "code": code,
        "description": description,
    }

    print(f"[INFO] Criando building com payload: {payload}")
    resp = await client.post("/buildings/", json=payload)
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError:
        print("[ERRO] Falha ao criar building:")
        print("Status:", resp.status_code)
        print("Body:", resp.text)
        raise

    building = resp.json()
    print(f"[OK] Building criado id={building['id']} name={building['name']} code={building['code']}")
    return building



async def create_floor(
    client: httpx.AsyncClient,
    name: str,
    building_id: int,
    level: int | None = None,
    description: str | None = None,
) -> dict:
    """
    Cria um andar usando FloorCreate:
    {
      "building_id": int,
      "name": str,
      "level": int | null,
      "description": str | null
    }
    """
    payload = {
        "building_id": building_id,
        "name": name,
        "level": level,
        "description": description,
    }

    print(f"[INFO] Criando floor com payload: {payload}")
    resp = await client.post("/floors/", json=payload)
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError:
        print("[ERRO] Falha ao criar floor:")
        print("Status:", resp.status_code)
        print("Body:", resp.text)
        raise

    return resp.json()


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cria building, floor e câmera via API e publica /info no MQTT pelo backend."
    )

    parser.add_argument(
        "--api-base",
        default="http://localhost:8000/api/v1",
        help="Base URL da API FastAPI (default: http://localhost:8000/api/v1)",
    )

    # Building
    parser.add_argument("--building", default="PredioA", help="Nome do prédio (default: PredioA)")
    parser.add_argument(
        "--building-code",
        default="PredioA",
        help="Code do prédio (default: PredioA)",
    )

    # Floor
    parser.add_argument("--floor", default="Andar1", help="Nome do andar (default: Andar1)")
    parser.add_argument(
        "--floor-level",
        type=int,
        default=None,
        help="Nível do andar (opcional, ex: 1 para 1º andar)",
    )

    # Camera
    parser.add_argument("--code", default="fixa02", help="Code da câmera (default: fixa02)")
    parser.add_argument("--name", default="Dahua fixa 02", help="Nome da câmera")
    parser.add_argument("--ip", required=True, help="IP da câmera (ex: 192.168.91.111)")
    parser.add_argument("--port", type=int, default=80, help="Porta da câmera (default: 80)")
    parser.add_argument("--username", default="admin", help="Usuário da câmera (default: admin)")
    parser.add_argument("--password", required=True, help="Senha da câmera")

    parser.add_argument("--manufacturer", default="Dahua", help="Fabricante (default: Dahua)")
    parser.add_argument("--model", default="any", help="Modelo (default: any)")

    args = parser.parse_args(argv)

    base_url = args.api_base.rstrip("/")
    print(f"[INFO] Usando API base: {base_url}")

    async with httpx.AsyncClient(base_url=base_url, timeout=15.0) as client:
        # 1) Building
        building = await create_building(
            client,
            name=args.building,
            code=args.building_code,
        )
        building_id = building["id"]
        print(f"[OK] Building criado id={building_id} name={building['name']} code={building['code']}")

        # 2) Floor
        floor = await create_floor(
            client,
            name=args.floor,
            building_id=building_id,
            level=args.floor_level,
        )
        floor_id = floor["id"]
        print(
            f"[OK] Floor criado id={floor_id} name={floor['name']} building_id={floor['building_id']}"
        )

        # 3) Camera via /devices/cameras
        camera_payload = {
            "name": args.name,
            "code": args.code,
            "building_id": building_id,
            "floor_id": floor_id,
            "ip_address": args.ip,
            "port": args.port,
            "username": args.username,
            "password": args.password,
            "manufacturer": args.manufacturer,
            "model": args.model,
            # floor_plan_id / pos_x / pos_y podem ser adicionados aqui no futuro
        }

        print(f"[INFO] Criando câmera com payload: {camera_payload}")

        resp = await client.post("/devices/cameras/", json=camera_payload)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            print("[ERRO] Falha ao criar câmera:")
            print("Status:", resp.status_code)
            print("Body:", resp.text)
            raise

        camera = resp.json()
        print(f"[OK] Camera criada id={camera['id']} name={camera['name']} type={camera['type']}")

    # Monta o tópico esperado (informativo)
    tenant = settings.CAMBUS_TENANT
    base_topic = settings.CAMBUS_MQTT_BASE_TOPIC.rstrip("/")
    building_segment = args.building
    floor_segment = args.floor
    dev_type_segment = "camera"
    dev_id_segment = camera.get("code") or f"cam{camera['id']}"

    topic = (
        f"{base_topic}/{tenant}/"
        f"{building_segment}/{floor_segment}/"
        f"{dev_type_segment}/{dev_id_segment}/info"
    )

    print("\n[INFO] Se tudo deu certo, o backend publicou algo como:")
    print(f"  Tópico MQTT: {topic}")
    print("  Payload JSON: { manufacturer, model, name, ip, username, password, port, "
          "use_tls, enabled, shard, analytics }")

    print("\n[INFO] Para debugar, você pode rodar:")
    print(f"  mosquitto_sub -h {settings.RTLS_MQTT_HOST} -p {settings.RTLS_MQTT_PORT} -t '{base_topic}/#' -v")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
