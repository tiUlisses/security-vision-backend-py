# SecurityVision Backend (RTLS + CAM-BUS)

Backend assíncrono em **Python/FastAPI** para o ecossistema *SecurityVision* (RTLS via MQTT + eventos de câmeras via CAM-BUS), com persistência em **PostgreSQL**, suporte a **webhooks**, integração com **Chatwoot** e execução pronta para **Docker/Docker Compose**.

> Gerado automaticamente em 2025-12-17 com base na estrutura e código do repositório.

---

## Sumário

- [Visão geral](#visão-geral)
- [Stack e componentes](#stack-e-componentes)
- [Arquitetura (alto nível)](#arquitetura-alto-nível)
- [Estrutura do repositório](#estrutura-do-repositório)
- [Como rodar local (sem Docker)](#como-rodar-local-sem-docker)
- [Como rodar com Docker Compose](#como-rodar-com-docker-compose)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Migrations (Alembic)](#migrations-alembic)
- [Endpoints principais](#endpoints-principais)
- [Testes](#testes)
- [Troubleshooting](#troubleshooting)

---

## Visão geral

Este serviço expõe uma API REST em **`/api/v1`** e roda alguns *workers* em background no startup:

- **RTLS MQTT Ingestor**: assina o tópico de gateways (ex.: `rtls/gateways/#`), cria/atualiza *devices* e grava *collection logs* com RSSI por tag.
- **CAM-BUS Event Collector**: assina eventos de câmeras (ex.: `rtls/cameras/#`) e normaliza eventos/estado para o banco.
- **Alertas e Incidentes**:
  - CRUD de **alert_rules** e **alert_events**
  - CRUD de **incidents** (com mensagens e anexos)
  - **webhook subscriptions** (dispatch de eventos para integrações externas)
  - Integração **Chatwoot** (webhook de entrada e serviços para sincronização/atendimento)

Além disso, o backend serve arquivos em **`/media`** (upload de anexos e outras mídias).

---

## Stack e componentes

- **API**: FastAPI + Uvicorn
- **Banco**: PostgreSQL (SQLAlchemy 2.x **async** + `asyncpg`)
- **Migrations**: Alembic (configurado para usar `settings.database_url`)
- **Mensageria**: MQTT (compatível com Mosquitto; uso de `asyncio-mqtt`/`paho-mqtt`)
- **Auth**: OAuth2 Password Flow + JWT (HS256)
- **Infra (Docker)**:
  - `api` (FastAPI)
  - `db` (Postgres 16)
  - `mqtt` (Eclipse Mosquitto)
  - `redis` (Redis 7) *(preparado no stack; uso no código é mínimo/planejado)*
  - `adminer` (opcional, via profile)

---

## Estrutura do repositório

```text
security-vision-backend-py-main/
├── alembic/
│   ├── versions/
│   ├── env.py
│   └── script.py.mako
├── app/
│   ├── api/
│   │   ├── routes/
│   │   ├── v1/
│   │   ├── __init__.py
│   │   └── deps.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── security.py
│   ├── crud/
│   │   ├── __init__.py
│   │   ├── alert_event.py
│   │   ├── alert_rule.py
│   │   ├── base.py
│   │   ├── building.py
│   │   ├── camera_group.py
│   │   ├── collection_log.py
│   │   ├── device.py
│   │   ├── device_event.py
│   │   ├── device_topic.py
│   │   ├── floor.py
│   │   ├── floor_plan.py
│   │   ├── incident.py
│   │   ├── incident_message.py
│   │   ├── incident_rule.py
│   │   ├── person.py
│   │   ├── person_group.py
│   │   ├── presence_session.py
│   │   ├── support_group.py
│   │   ├── tag.py
│   │   ├── user.py
│   │   └── webhook_subscription.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── base_class.py
│   │   └── session.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── alert_event.py
│   │   ├── alert_rule.py
│   │   ├── building.py
│   │   ├── camera_group.py
│   │   ├── collection_log.py
│   │   ├── device.py
│   │   ├── device_event.py
│   │   ├── device_topic.py
│   │   ├── floor.py
│   │   ├── floor_plan.py
│   │   ├── incident.py
│   │   ├── incident_assignee.py
│   │   ├── incident_attachment.py
│   │   ├── incident_message.py
│   │   ├── incident_rule.py
│   │   ├── person.py
│   │   ├── person_group.py
│   │   ├── presence_session.py
│   │   ├── support_group.py
│   │   ├── tag.py
│   │   ├── user.py
│   │   └── webhook_subscription.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── alert_event.py
│   │   ├── alert_rule.py
│   │   ├── building.py
│   │   ├── camera_group.py
│   │   ├── collection_log.py
│   │   ├── dashboard.py
│   │   ├── device.py
│   │   ├── device_event.py
│   │   ├── device_topic.py
│   │   ├── floor.py
│   │   ├── floor_plan.py
│   │   ├── gateway_report.py
│   │   ├── incident.py
│   │   ├── incident_message.py
│   │   ├── incident_rule.py
│   │   ├── location.py
│   │   ├── person.py
│   │   ├── person_group.py
│   │   ├── person_report.py
│   │   ├── presence_session.py
│   │   ├── support_group.py
│   │   ├── tag.py
│   │   ├── user.py
│   │   └── webhook.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── alert_engine.py
│   │   ├── cambus_event_collector.py
│   │   ├── cambus_publisher.py
│   │   ├── chatwoot_client.py
│   │   ├── chatwoot_sync.py
│   │   ├── incident_auto_rules.py
│   │   ├── incident_files.py
│   │   ├── incidents.py
│   │   ├── mqtt_gateways.py
│   │   ├── mqtt_ingestor.py
│   │   ├── mqtt_worker.py
│   │   └── webhook_dispatcher.py
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── mac.py
│   │   └── tag.py
│   ├── .env
│   ├── __init__.py
│   └── main.py
├── docker/
│   ├── entrypoint.sh
│   ├── mosquitto.conf
│   └── wait_for_db.py
├── env/
│   ├── .env.dev
│   └── .env.prod
├── media/
│   ├── floor_plans/
│   └── incidents/
├── scripts/
│   ├── simulate_gateways.py
│   └── test_create_camera.py
├── testes/
│   ├── __init__.py
│   ├── test_alert_events_api.py
│   ├── test_alert_rules_api.py
│   ├── test_buildings.py
│   ├── test_floors_floorplans.py
│   ├── test_mqtt_gateway_autoregister.py
│   ├── test_mqtt_ingestor_logic.py
│   ├── test_people_tags.py
│   ├── test_person_current_location.py
│   ├── test_person_groups_api.py
│   ├── test_position_by_device.py
│   ├── test_positions_current_api.py
│   └── test_webhooks_api.py
├── .dockerignore
├── .env
├── .gitignore
├── alembic.ini
├── docker-compose.dev.yml
├── docker-compose.prod.yml
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── requirements.txt
```

Pontos importantes:

- `app/main.py`: inicializa o FastAPI, CORS, `/media`, e cria tarefas de background no startup.
- `app/api/v1/api.py`: registra todas as rotas em `/api/v1`.
- `app/models`, `app/schemas`, `app/crud`: camada de dados (ORM + Pydantic + repositórios).
- `app/services`: lógica de domínio (MQTT, CAM-BUS, alertas, chatwoot, webhooks, incidentes).
- `docker/entrypoint.sh`: espera o Postgres e (opcionalmente) roda migrations antes de iniciar o Uvicorn.

---

## Como rodar local (sem Docker)

### Pré-requisitos

- Python **3.11**
- PostgreSQL (e.g. `localhost:5432`)
- Broker MQTT (e.g. Mosquitto em `localhost:1883`)
- (Opcional) Redis em `localhost:6379`

### 1) Criar ambiente e instalar dependências

Usando `pip`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

Ou usando Poetry (há `pyproject.toml`):

```bash
poetry install
poetry shell
```

### 2) Configurar variáveis de ambiente

- Ajuste o arquivo `.env` na raiz **ou** exporte variáveis no shell.
- Para referência, veja `env/.env.dev` e `env/.env.prod`.

Exemplo mínimo (local):

```env
DATABASE_URL=postgresql://rtls:rtls123@localhost:5432/rtls_db

RTLS_MQTT_ENABLED=true
RTLS_MQTT_HOST=localhost
RTLS_MQTT_PORT=1883
RTLS_MQTT_TOPIC=rtls/gateways/#

CAMBUS_MQTT_ENABLED=true
CAMBUS_MQTT_BASE_TOPIC=rtls/cameras

PUBLIC_BASE_URL=http://localhost:8000
MEDIA_BASE_URL=http://localhost:8000/media
```

### 3) Subir a API

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Acessos:

- Healthcheck: `GET http://localhost:8000/health`
- Swagger/OpenAPI: `GET http://localhost:8000/docs`
- OpenAPI JSON: `GET http://localhost:8000/openapi.json`

---

## Como rodar com Docker Compose

### Desenvolvimento (hot reload)

O `docker-compose.yml` usa o **target `dev`** do Dockerfile (com `--reload`) e carrega variáveis de `env/.env.dev`.

```bash
docker compose up --build
```

Serviços (por padrão):

- API: `http://localhost:8000`
- Postgres: `localhost:5432`
- Mosquitto: `localhost:1883`
- Redis: `localhost:6379`

#### Adminer (opcional)

O Adminer está configurado com `profiles: ["tools"]`. Para subir junto:

```bash
docker compose --profile tools up --build
```

Acesso: `http://localhost:8080`

---

### Produção (compose dedicado)

O `docker-compose.prod.yml` usa o **target `prod`** (sem hot reload) e por padrão expõe:

- Host `8001` → container `8000`

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

> Recomendações de produção:
> - Definir `SVPOS_SECRET_KEY` e ajustar CORS (em `app/main.py`, hoje está `origins=["*"]`).
> - Remover tokens do repositório e usar secrets/variáveis no ambiente.
> - Revisar `mosquitto.conf` (está com `allow_anonymous true`).

---

## Variáveis de ambiente

As configurações são carregadas via `app/core/config.py` (Pydantic Settings). Em Docker, use os arquivos:

- `env/.env.dev`
- `env/.env.prod`

### Banco (Postgres)

- `DATABASE_URL` (ex.: `postgresql://user:pass@host:5432/dbname`)
- Alternativamente (quando `DATABASE_URL` não é usado):
  - `RTLS_DB_HOST`, `RTLS_DB_PORT`, `RTLS_DB_USER`, `RTLS_DB_PASSWORD`, `RTLS_DB_NAME`

### MQTT (RTLS gateways)

- `RTLS_MQTT_ENABLED` (`true|false`)
- `RTLS_MQTT_HOST`
- `RTLS_MQTT_PORT`
- `RTLS_MQTT_USERNAME` (opcional)
- `RTLS_MQTT_PASSWORD` (opcional)
- `RTLS_MQTT_TOPIC` (ex.: `rtls/gateways/#`)

**Formato de tópico esperado (RTLS):**

- `rtls/gateways/<gateway_mac>/status`
- `rtls/gateways/<gateway_mac>/beacon`

**Exemplo de payload `beacon`:**

```json
{
  "readings": [
    { "tag_mac": "AA:BB:CC:DD:EE:FF", "rssi": -62 }
  ]
}
```

### CAM-BUS (câmeras)

- `CAMBUS_MQTT_ENABLED` (`true|false`)
- `CAMBUS_MQTT_BASE_TOPIC` (ex.: `rtls/cameras`)
- `CAMBUS_TENANT` (identificação do tenant)
- `CAMBUS_DEFAULT_SHARD` (fallback)

**Exemplos de tópicos CAM-BUS reconhecidos (a partir do parser do projeto):**

- `rtls/cameras/<tenant>/<building>/<floor>/camera/<code>/info`
- `rtls/cameras/<tenant>/<building>/<floor>/camera/<code>/status`
- `rtls/cameras/<tenant>/<building>/<floor>/camera/<code>/<analytic>/events`
- `rtls/cameras/<tenant>/<building>/collector/status`

### URLs / mídia

- `PUBLIC_BASE_URL` (base pública da API, ex.: `http://localhost:8000`)
- `MEDIA_BASE_URL` (ex.: `http://localhost:8000/media`)
- `MEDIA_ROOT`/`media_root` (padrão: `media`)

### Chatwoot (integração)

- `CHATWOOT_ENABLED` (`true|false`)
- `CHATWOOT_BASE_URL` (ex.: `https://chat.example.com`)
- `CHATWOOT_API_ACCESS_TOKEN`
- `CHATWOOT_DEFAULT_ACCOUNT_ID`
- `CHATWOOT_DEFAULT_INBOX_IDENTIFIER`
- `CHATWOOT_DEFAULT_CONTACT_IDENTIFIER` (padrão: `security-vision-system`)
- `CHATWOOT_INCIDENT_BASE_URL` (URL do frontend para linkar incidentes)
- `CHATWOOT_WEBHOOK_TOKEN` *(valida `x-chatwoot-signature` no endpoint webhook, quando definido)*

Webhook de entrada (Chatwoot):

- `POST /api/v1/integrations/chatwoot/webhook`

### Auth (JWT)

- `SVPOS_SECRET_KEY` *(obrigatório em produção)*
- `SVPOS_ACCESS_TOKEN_EXPIRE_MINUTES` (default: 1440)

### Flags do entrypoint (Docker)

- `DB_WAIT` (`1|0`): aguarda Postgres antes de iniciar
- `RUN_MIGRATIONS` (`1|0`): roda `alembic upgrade head`

---

## Migrations (Alembic)

O projeto já vem com Alembic configurado (`alembic/env.py` usa `settings.database_url`), porém **a pasta `alembic/versions/` está vazia** no estado atual do repositório.

### Opção A — usar `create_all` (dev/local)

No startup, o backend executa `Base.metadata.create_all(...)` (veja `app/db/session.py:init_db()`), o que resolve para desenvolvimento rápido.

### Opção B — criar a primeira migration (recomendado)

1) Gere uma revisão inicial:

```bash
alembic revision --autogenerate -m "initial"
```

2) Aplique:

```bash
alembic upgrade head
```

> Se você estiver rodando com Docker e ainda não tiver migrations, pode temporariamente setar `RUN_MIGRATIONS=0` para evitar erro no entrypoint.

---

## Endpoints principais

Base: **`/api/v1`**

- **Auth**: `/auth/login`, `/auth/signup`, `/auth/me`
- **Users**: `/users/*`
- **Cadastros**:
  - `/buildings/*`
  - `/floors/*`
  - `/floor-plans/*`
  - `/people/*` (inclui `/people/{person_id}/current-location`)
  - `/tags/*`
  - `/person-groups/*`
- **Devices**:
  - `/devices/*`
  - `/devices/gateways/*`
  - `/devices/cameras/*` (inclui `/devices/cameras/{camera_id}/events`)
  - `/devices/camera-groups/*`
- **Posições**:
  - `/positions/current`
  - `/positions/by-device`
- **Alertas**:
  - `/alert-rules/*`
  - `/alert-events/*`
- **Incidentes**:
  - `/incidents/*` (inclui mensagens e anexos)
  - `/incident-rules/*`
- **Webhooks (outgoing)**:
  - `/webhooks/event-types`
  - `/webhooks/*`
- **Dashboard/Reports**:
  - `/dashboard/summary`
  - `/reports/*` (vários relatórios de presença/uso/alertas)

Docs completos e modelos: `GET /docs`.

---

## Testes

Há uma suíte em `testes/` (pytest). Muitos testes são de integração (dependem de Postgres e/ou da API).

Execução (com dependências já disponíveis):

```bash
pytest -q
```

Sugestão prática: subir o stack de dev e rodar testes no host:

```bash
docker compose up -d --build
pytest -q
```

---

## Troubleshooting

### API sobe mas não conecta no Postgres

- Verifique `DATABASE_URL` e/ou `RTLS_DB_*`
- Em Docker, o hostname do Postgres normalmente é `db` (como no compose).
- O entrypoint suporta `DB_WAIT=1` para aguardar readiness.

### Erro de migrations no startup

- Se `alembic/versions` estiver vazio, `alembic upgrade head` pode falhar.
  - Solução: criar a primeira migration **ou** setar `RUN_MIGRATIONS=0` e confiar no `create_all` em dev.

### MQTT não recebe mensagens

- Confirme `RTLS_MQTT_*` e se o broker está acessível.
- Verifique se os tópicos publicados batem com `RTLS_MQTT_TOPIC` (default: `rtls/gateways/#`).

### Uploads / anexos não aparecem

- Arquivos são gravados em `media/` e servidos em `/media`.
- Em Docker, o compose monta volume para `/app/media`.

---
