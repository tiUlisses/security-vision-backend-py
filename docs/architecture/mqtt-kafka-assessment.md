# Avaliação técnica: MQTT atual vs. adoção de Kafka (com conectores)

## 1) Estado atual da aplicação

### 1.1 Ingestão RTLS via MQTT
- A aplicação inicia um `MqttIngestor` no startup do FastAPI e mantém um loop assíncrono com reconexão automática ao broker MQTT. Esse loop assina um tópico configurável (`settings.MQTT_TOPIC`) e processa cada mensagem.  
- O parser aceita dois formatos de tópico para gateways:
  - **Novo**: `rtls/gateways/<tenant>/<building>/<floor>/gateway/<gateway_id>/<kind>`
  - **Legado**: `rtls/gateways/<gateway_id>/<kind>`
- O ingestor faz **auto-provisioning** de gateways por MAC, atualiza `last_seen_at`, resolve `building/floor` quando possível e grava `CollectionLog` apenas para tags cadastradas.
- Existe monitor de offline/online para gateways, com geração de eventos e fechamento de sessões RTLS obsoletas.

**Conclusão:** o núcleo de coleta RTLS já está resiliente e orientado a mensagens, com lógica de negócio centrada no processamento de eventos.

### 1.2 Ingestão CAM-BUS (câmeras) via MQTT
- Em paralelo ao ingestor RTLS, existe um coletor dedicado para câmeras (`run_cambus_event_collector`) também conectado no MQTT.
- Ele interpreta padrões de tópicos de câmera (`info/status/events`), faz upsert em `device_topics`, atualiza `last_seen_at` e persiste eventos em `device_events`.

**Conclusão:** já há um padrão de “adapter por domínio” (gateways e câmeras) que pode ser expandido para Kafka sem reescrever toda a aplicação.

### 1.3 Dependências e empacotamento
- O stack local usa `docker-compose` com API + Postgres + Redis + Mosquitto + MinIO.
- O `Dockerfile` é multi-stage (`builder`, `prod`, `dev`) e suporta cenário de desenvolvimento e produção.

**Conclusão:** a base para CI/CD em contêineres já existe; e agora também temos um CI principal desacoplado de Docker para evolução da nova abordagem.

---

## 2) É possível manter MQTT e adicionar Kafka como consumidor?

**Sim, é tecnicamente viável e recomendado em fases.**

### Estratégia sugerida
1. **Não remover MQTT de dispositivos** inicialmente. Gateways/câmeras continuam publicando no MQTT.
2. Introduzir Kafka como backbone analítico/integração usando uma das opções:
   - **Ponte em aplicação (Python):** novo worker que consome MQTT e publica em Kafka com envelope padronizado.
   - **Kafka Connect MQTT Source:** broker MQTT → tópicos Kafka (menor código de app, maior dependência operacional em Connect).
3. Manter o backend atual consumindo MQTT durante transição (dual path).
4. Migrar consumidores internos gradualmente para Kafka, preservando as regras de negócio existentes.

---

## 3) Lógica de conectores para controle de dispositivos MQTT via Kafka

Para comando/controle (downlink), use fluxo bidirecional:

- **Comando de negócio** entra em tópico Kafka (ex.: `rtls.device.commands`).
- **Connector/bridge Kafka→MQTT** transforma e publica no tópico MQTT correto do dispositivo.
- **Confirmação/telemetria** retorna por MQTT e é republicada em Kafka (ex.: `rtls.device.acks`, `rtls.device.telemetry`).

### Envelope canônico recomendado
```json
{
  "event_id": "uuid",
  "source": "mqtt|api|connector",
  "tenant": "default",
  "domain": "rtls|camera",
  "device_id": "AA:BB:CC:DD:EE:FF",
  "topic": "rtls/gateways/...",
  "kind": "status|beacon|command|ack",
  "occurred_at": "2026-01-01T12:00:00Z",
  "payload": {"...": "..."}
}
```

### Garantias mínimas
- Idempotência por `event_id`/chave composta (`device_id`, `occurred_at`, hash payload).
- Dead-letter topics para payload inválido.
- Retry com backoff na ponte Kafka↔MQTT.
- Observabilidade (lag, taxa de erro, throughput).

---

## 4) Nova abordagem em branch separada (desacoplada do sub-docker)

### Objetivo
Evoluir Kafka/MQTT em uma **branch dedicada** sem depender do fluxo de Docker em cada alteração de aplicação.

### Branch sugerida
- `feature/kafka-connectors-bridge`

### Diretrizes
1. O fluxo principal de validação passa a ser o `app-ci` (Python), independente de build de containers.
2. O fluxo `container-ci` permanece para mudanças de container/infra e pode ser disparado manualmente (`workflow_dispatch`) ou por alteração em arquivos Docker.
3. A implementação da bridge deve nascer em módulos isolados (ex.: `app/services/event_bridge/`) para não acoplar ao runtime legado imediatamente.
4. O rollout deve ser por feature flag (`KAFKA_ENABLED`, `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_TOPIC_*`) mantendo o comportamento MQTT atual como default.

### Benefício prático
- Time consegue iterar regra de negócio e conectores rapidamente, sem custo operacional de build de imagem em todo PR funcional.

---

## 5) Riscos e ajustes necessários antes da migração

1. **Consolidar ingestores MQTT:** hoje há caminhos parcialmente sobrepostos (`mqtt_worker`, `mqtt_ingestor`, `mqtt_gateways`). Recomenda-se manter um único pipeline por domínio para evitar lógica duplicada.
2. **Corrigir/atualizar testes legados de MQTT:** há testes chamando `process_message`, enquanto a implementação principal expõe `handle_message`.
3. **Definir contrato de tópicos/eventos versionado** (`v1`, `v2`) antes de publicar em Kafka.
4. **Planejar operação Kafka:** partições, retenção, schema evolution (Avro/JSON Schema/Protobuf), DLQ e custo operacional.

---

## 6) Benefícios: migrar para Kafka vs manter somente MQTT

## Manter como está (somente MQTT)
**Prós**
- Simplicidade operacional menor.
- Menor custo inicial.
- Bom para telemetria em tempo real de baixa/média complexidade.

**Contras**
- Menor capacidade de replay e histórico robusto para analytics.
- Integrações multi-consumidor mais frágeis (acoplamento por tópico sem governança forte).
- Escalabilidade analítica limitada em comparação a Kafka.

## Modelo híbrido (MQTT + Kafka)
**Prós**
- Preserva parque legado de dispositivos MQTT.
- Adiciona backbone robusto para integração, replay e analytics.
- Permite migração incremental sem downtime alto.

**Contras**
- Aumenta complexidade operacional (broker MQTT + Kafka + conectores).
- Exige governança de esquema e observabilidade mais madura.

## Migração completa para Kafka no edge
**Prós**
- Uniformidade de plataforma de eventos.

**Contras**
- Alto esforço e risco (dispositivos/gateways tipicamente falam MQTT nativamente).
- Em geral não é a melhor troca para edge IoT em curto prazo.

**Recomendação:** **modelo híbrido em fases**.

---

## 7) Workflows de GitHub Actions

### `app-ci` (principal, desacoplado de Docker)
- Instala dependências Python.
- Executa `compileall`.
- Executa `pytest --collect-only`.

### `container-ci` (infra/containers)
- Valida `docker-compose`.
- Build de imagem `prod` e `dev`.
- Smoke test por `import app.main`.
- Só roda automaticamente quando há mudanças relacionadas a Docker/Compose/workflow, ou manualmente.

---

## Parecer final
Com o código atual, **é viável** manter toda a comunicação existente via MQTT e incorporar Kafka como camada de consumo/orquestração sem perda funcional. A melhor forma de execução é em branch dedicada, com CI principal desacoplado do sub-docker e pipeline de containers separado para mudanças de infra.
