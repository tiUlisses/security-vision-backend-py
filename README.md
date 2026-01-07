# SecurityVision Backend (RTLS + CAM-BUS + Face Engine)

Backend assíncrono em **Python/FastAPI** para o ecossistema *SecurityVision* com ingestão de RTLS via MQTT, eventos de câmeras (CAM-BUS/face engine) e integração com Chatwoot.

Este README foi refatorado para ser **clone-and-run** em ambiente de desenvolvimento, com exemplos de `.env` alinhados ao seu dataset.

---

## ✅ Quickstart (Docker Compose – recomendado)

> Ideal para desenvolvimento local com Postgres, MQTT e Redis já provisionados.

```bash
git clone <URL_DO_REPO>
cd security-vision-backend-py

# Suba a stack
docker compose up --build
```

Serviços:

- API: `http://localhost:8000`
- Postgres: `localhost:5432`
- MQTT: `localhost:1883`
- Redis: `localhost:6379`

> Caso queira Adminer: `docker compose --profile tools up --build`

---

## ✅ Quickstart (Local – sem Docker)

### 1) Requisitos

- Python **3.11**
- PostgreSQL **16**
- Broker MQTT (Mosquitto/EMQX)

### 2) Ambiente Python

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

### 3) Variáveis de ambiente

Crie um arquivo `.env` na raiz (pode usar o exemplo abaixo):

```env
DATABASE_URL=postgresql://rtls:rtls123@localhost:5432/rtls_db
RTLS_DB_HOST=localhost
RTLS_DB_PORT=5432
RTLS_DB_USER=rtls
RTLS_DB_PASSWORD=rtls123
RTLS_DB_NAME=rtls_db
RUN_MIGRATIONS=0

RTLS_MQTT_ENABLED=true
RTLS_MQTT_HOST=localhost
RTLS_MQTT_PORT=1883
RTLS_MQTT_USERNAME=
RTLS_MQTT_PASSWORD=
RTLS_MQTT_TOPIC=rtls/gateways/#

CAMBUS_MQTT_ENABLED=true
CAMBUS_MQTT_BASE_TOPIC=rtls/cameras
CAMBUS_UPLINK_BASE_TOPIC=security-vision/cameras
CAMBUS_TENANT=howbe
CAMBUS_DEFAULT_SHARD=shard-1
CAMBUS_UPLINK_SRT_PORT=8890
CAMBUS_UPLINK_TTL_SECONDS=300

CHATWOOT_ENABLED=true
CHATWOOT_BASE_URL=https://chat.urtechsolucoes.com
CHATWOOT_API_ACCESS_TOKEN=NyEu794ta4nAbM6krRa2Rari
CHATWOOT_DEFAULT_ACCOUNT_ID=2
CHATWOOT_DEFAULT_INBOX_IDENTIFIER=teste
CHATWOOT_DEFAULT_CONTACT_IDENTIFIER=security-vision-system
CHATWOOT_INCIDENT_BASE_URL=http://localhost:5173/incidents
MEDIA_BASE_URL=http://localhost:8000/media

PUBLIC_BASE_URL=http://localhost:8000
SUPERADMIN_EMAIL=ulisses.rocha@howbe.com.br
SUPERADMIN_PASSWORD=h0wb3@123
SUPERADMIN_NAME=System Admin
```

### 4) Subir a API

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5) Subir a API (sem dev mode / sem reload)

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## ✅ Variáveis essenciais (dev)

### Banco

- `DATABASE_URL` *(prioritário)*
- `RTLS_DB_HOST`, `RTLS_DB_PORT`, `RTLS_DB_USER`, `RTLS_DB_PASSWORD`, `RTLS_DB_NAME`

### Sessões de presença

- `PRESENCE_SESSION_GAP_SECONDS` *(opcional, default: 15s)*: define o intervalo máximo entre
  `collection_logs` consecutivos para que continuem na mesma sessão.
- `PRESENCE_LOG_RETENTION_DAYS` *(opcional, default: 30)*: dias de retenção de logs brutos
  (`collection_logs`) antes do rollup/purge.

A view `presence_sessions` agrega os registros de `collection_logs` por `(tag_id, device_id)`
em sessões contínuas usando esse gap, expondo início, fim, duração e quantidade de amostras.

#### Retenção e rollups de presença

Estratégia recomendada:

- Manter `collection_logs` apenas na janela recente (ex.: 30 dias).
- Consolidar histórico em `presence_daily_usage` (rollup diário).

Job sugerido (cron/async), que agrega e faz purge dos logs fora da retenção:

```bash
python scripts/rollup_presence_logs.py --retention-days 30
```

Plano de queries para relatórios:

- Janela recente: consultar `presence_sessions` diretamente.
- Histórico: consultar `presence_daily_usage` e combinar com a janela recente quando necessário.

### MQTT (RTLS Gateways)

```
RTLS_MQTT_TOPIC=rtls/gateways/#
```

Tópicos esperados:

- `rtls/gateways/<gateway_mac>/status`
- `rtls/gateways/<gateway_mac>/beacon`

Payload exemplo:

```json
{
  "readings": [
    { "tag_mac": "AA:BB:CC:DD:EE:FF", "rssi": -62 }
  ]
}
```

### CAM-BUS + Face Engine

```
CAMBUS_MQTT_BASE_TOPIC=rtls/cameras
CAMBUS_UPLINK_BASE_TOPIC=security-vision/cameras
CAMBUS_TENANT=howbe
CAMBUS_DEFAULT_SHARD=shard-1
CAMBUS_UPLINK_SRT_PORT=8890
CAMBUS_UPLINK_TTL_SECONDS=300
```

Tópicos esperados:

- `rtls/cameras/<tenant>/<building>/<floor>/camera/<code>/faceCapture/events`
- `rtls/cameras/<tenant>/<building>/<floor>/camera/<code>/status`
- `rtls/cameras/<tenant>/<building>/collector/status`

> O backend detecta eventos do tipo `faceCapture` e cria incidentes com mídias vinculadas.

---

## ✅ Chatwoot (pronto para uso)

Habilite via `.env`:

```
CHATWOOT_ENABLED=true
CHATWOOT_BASE_URL=https://chat.urtechsolucoes.com
CHATWOOT_API_ACCESS_TOKEN=<TOKEN>
CHATWOOT_DEFAULT_ACCOUNT_ID=2
CHATWOOT_DEFAULT_INBOX_IDENTIFIER=teste
```

Webhook de entrada:

```
POST /api/v1/integrations/chatwoot/webhook
```

---

## ✅ Superadmin (auto bootstrap)

Se as variáveis abaixo estiverem definidas, o sistema cria o primeiro usuário admin na inicialização:

```
SUPERADMIN_EMAIL=ulisses.rocha@howbe.com.br
SUPERADMIN_PASSWORD=h0wb3@123
SUPERADMIN_NAME=System Admin
```

---

## ✅ Docker (com e sem dev mode)

### Desenvolvimento (com hot reload)

Usa o `docker-compose.yml` + `env/.env.dev` e roda o Uvicorn com `--reload`.

```bash
docker compose up --build
```

### Produção (sem dev mode)

Usa o `docker-compose.prod.yml` + `env/.env.prod` com target `prod` (sem hot reload).

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

> Por padrão, o `docker-compose.prod.yml` expõe `8001:8000`.

### Usando um banco externo

Se quiser usar outro Postgres (fora do compose), ajuste `.env`/`env/.env.dev`:

```
DATABASE_URL=postgresql://rtls:rtls123@localhost:5432/rtls_db
RTLS_DB_HOST=localhost
```

---

## ✅ Health & Docs

- `GET /health`
- `GET /docs`
- `GET /openapi.json`

---

## ✅ Migrations

Este projeto usa `Base.metadata.create_all` no startup para desenvolvimento rápido.

Se quiser migrations reais:

```bash
alembic revision --autogenerate -m "initial"
alembic upgrade head
```

---

## ✅ Estrutura do projeto

```
security-vision-backend-py/
├── alembic/
│   ├── versions/
│   ├── env.py
│   └── script.py.mako
├── app/
│   ├── api/
│   ├── core/
│   ├── crud/
│   ├── db/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   ├── utils/
│   └── main.py
├── docker/
│   ├── entrypoint.sh
│   ├── mosquitto.conf
│   └── wait_for_db.py
├── env/
│   ├── .env.dev
│   └── .env.prod
├── media/
├── scripts/
├── testes/
├── .env
├── docker-compose.yml
├── docker-compose.dev.yml
├── docker-compose.prod.yml
├── Dockerfile
├── alembic.ini
├── pyproject.toml
└── requirements.txt
```

---

## ✅ Troubleshooting

### API sobe mas não conecta no banco

- Confirme `DATABASE_URL` e/ou `RTLS_DB_*`
- No Docker, o host do Postgres é `db`

### Migrations falhando no startup

- Deixe `RUN_MIGRATIONS=0` em dev
- Ou crie a primeira migration com Alembic

### MQTT não recebe mensagens

- Verifique `RTLS_MQTT_*`
- Confirme se o broker está acessível

---

## ✅ Comandos úteis

```bash
# Rodar testes
pytest -q
```

---

## ✅ Sobre

Este backend integra RTLS, CAM-BUS (face engine) e Chatwoot de forma unificada.

Se precisar de ajustes específicos no pipeline de câmeras, basta adaptar `app/services/cambus_event_collector.py`.
