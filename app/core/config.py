# app/core/config.py
from typing import Optional
import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AnyHttpUrl


def _load_secret_file(env_var: str, file_var: str) -> None:
    file_path = os.getenv(file_var)
    if not file_path or os.getenv(env_var):
        return

    path = Path(file_path)
    if not path.is_file():
        return

    os.environ[env_var] = path.read_text().strip()


_load_secret_file("RTLS_DB_PASSWORD", "RTLS_DB_PASSWORD_FILE")
_load_secret_file("CHATWOOT_API_ACCESS_TOKEN", "CHATWOOT_API_ACCESS_TOKEN_FILE")
_load_secret_file("SUPERADMIN_PASSWORD", "SUPERADMIN_PASSWORD_FILE")


class Settings(BaseSettings):
    """
    Configurações globais da aplicação.

    Compatível com as variáveis que você já tinha no .env:
    - redis_host, redis_port
    - mqtt_broker_url
    - rtls_db_host, rtls_db_port, rtls_db_user, rtls_db_password, rtls_db_name
    - RTLS_MQTT_ENABLED, RTLS_MQTT_HOST, RTLS_MQTT_PORT, RTLS_MQTT_USERNAME,
      RTLS_MQTT_PASSWORD, RTLS_MQTT_TOPIC

    E expõe propriedades amigáveis que usamos no código:
    - settings.database_url
    - settings.MQTT_ENABLED / MQTT_HOST / MQTT_PORT / MQTT_TOPIC / MQTT_GATEWAY_TOPIC_PREFIX
    - settings.CAMBUS_MQTT_* para o cam-bus
    """
    FRONTEND_BASE_URL: Optional[AnyHttpUrl] = None
    PUBLIC_BASE_URL: Optional[AnyHttpUrl] = None
    MEDIA_BASE_URL: Optional[AnyHttpUrl] = None
    CHATWOOT_ENABLED: bool = False
    CHATWOOT_BASE_URL: AnyHttpUrl | None = None
    CHATWOOT_API_ACCESS_TOKEN: str | None = None
    CHATWOOT_DEFAULT_ACCOUNT_ID: str | None = None
    CHATWOOT_DEFAULT_INBOX_IDENTIFIER: str | None = None
    CHATWOOT_DEFAULT_CONTACT_IDENTIFIER: str = "security-vision-system"
    CHATWOOT_WEBHOOK_TOKEN: str | None = os.getenv("CHATWOOT_WEBHOOK_TOKEN")
    CHATWOOT_INCIDENT_BASE_URL: AnyHttpUrl | None = None
    POSITION_STALE_THRESHOLD_SECONDS: int = 15
    PRESENCE_SESSION_GAP_SECONDS: int = Field(
        default=15,
        description=(
            "Janela máxima (em segundos) entre logs consecutivos para manter a mesma "
            "sessão de presença."
        ),
    )
    PRESENCE_LOG_RETENTION_DAYS: int = Field(
        default=30,
        description=(
            "Quantidade de dias para manter collection_logs brutos antes do rollup/purge."
        ),
    )
    PRESENCE_ROLLUP_ENABLED: bool = Field(
        default=False,
        description="Se True, executa rollup/purge automaticamente em background.",
    )
    PRESENCE_ROLLUP_INTERVAL_MINUTES: int = Field(
        default=60,
        description="Intervalo (em minutos) entre execuções do rollup/purge automático.",
    )
    # ==================================================================

    # Config Pydantic v2
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignora qualquer variável extra que não tenhamos declarado
    )

    APP_NAME: str = "SecurityVision"

    # ------------------------------------------------------------------
    # Autenticação / JWT
    # ------------------------------------------------------------------
    JWT_SECRET_KEY: str = Field(
        default="change-me-in-production",
        alias="SVPOS_SECRET_KEY",
        description="Chave secreta usada para assinar JWTs. Sempre sobrescreva em produção.",
    )
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=1440,
        alias="SVPOS_ACCESS_TOKEN_EXPIRE_MINUTES",
        description="Tempo de expiração (minutos) do access token.",
    )
    JWT_ISSUER: str = Field(
        default="security-vision",
        description="Identificador do emissor dos tokens.",
    )
    JWT_AUDIENCE: str = Field(
        default="security-vision-clients",
        description="Audiência padrão dos tokens.",
    )
    JWT_ISSUER: str = Field(
        default="security-vision",
        description="Identificador do emissor dos tokens.",
    )
    ALLOW_ANONYMOUS_DEV_MODE: bool = Field(
        default=True,
        description=(
            "Se True, permite que rotas protegidas aceitem um usuário dev fictício "
            "quando não há token. Use apenas em desenvolvimento/testes."
        ),
    )
    TESTING: bool = Field(
        default=False,
        description="Indica execução de testes (mantido apenas para compatibilidade).",
    )

    # Bootstrap do primeiro superadmin (opcional)
    SUPERADMIN_EMAIL: Optional[str] = None
    SUPERADMIN_PASSWORD: Optional[str] = None
    SUPERADMIN_NAME: str = "System Admin"

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------
    redis_host: str = "localhost"
    redis_port: int = 6379

    # URL antiga de broker (se quiser usar em outra parte depois)
    mqtt_broker_url: Optional[str] = None

    # ------------------------------------------------------------------
    # Banco RTLS
    # ------------------------------------------------------------------
    rtls_db_host: str = "localhost"
    rtls_db_port: int = 5432
    rtls_db_user: str = "rtls"
    rtls_db_password: str = "rtls123"
    rtls_db_name: str = "rtls_db"

    media_root: str = Field(default="media", alias="MEDIA_ROOT")
    public_base_url: str = Field(
        default="http://localhost:8000",
        alias="PUBLIC_BASE_URL",
    )

    # Opcional: se você quiser setar DATABASE_URL direto no .env
    DATABASE_URL: Optional[str] = Field(
        default=None,
        alias="DATABASE_URL",
    )

    # ------------------------------------------------------------------
    # CAM-BUS (câmeras em GO) – usa o mesmo broker MQTT do RTLS
    # ------------------------------------------------------------------
    CAMBUS_MQTT_ENABLED: bool = True
    CAMBUS_MQTT_BASE_TOPIC: str = "rtls/cameras"
    CAMBUS_UPLINK_BASE_TOPIC: str = Field(
        default="security-vision/cameras",
        description="Base do tópico para comandos uplink (start/stop) enviados ao cam-bus.",
    )
    CAMBUS_TENANT: str = "default"
    CAMBUS_DEFAULT_SHARD: str = "shard-1"
    CAMBUS_UPLINK_SRT_PORT: int = Field(
        default=8890,
        description="Porta SRT padrão usada ao iniciar uplink de câmeras.",
    )
    CAMBUS_UPLINK_TTL_SECONDS: int = Field(
        default=300,
        description="TTL (em segundos) padrão para mensagens de uplink de câmeras.",
    )

    # ------------------------------------------------------------------
    # Access-Control / Vision-Controller (projeção de ambientes)
    # ------------------------------------------------------------------
    ACCESS_CONTROL_MQTT_ENABLED: bool = True
    ACCESS_CONTROL_MQTT_TOPIC: str = "security-vision/access-control/locations"

    # ------------------------------------------------------------------
    # MQTT do RTLS (gateways BLE, etc.)
    # (lê variáveis do tipo RTLS_MQTT_* do .env automaticamente)
    # ------------------------------------------------------------------
    rtls_mqtt_enabled: bool = True
    rtls_mqtt_host: str = "localhost"
    rtls_mqtt_port: int = 1883
    rtls_mqtt_topic: str = "rtls/gateways/#"
    rtls_mqtt_username: Optional[str] = None
    rtls_mqtt_password: Optional[str] = None

    # ------------------------------------------------------------------
    # Outros ajustes
    # ------------------------------------------------------------------
    DEVICE_OFFLINE_THRESHOLD_SECONDS: int = 60

    # ==================================================================
    # Propriedades derivadas
    # ==================================================================

    @property
    def database_url(self) -> str:
        """
        URL async do banco para o SQLAlchemy.

        Prioridade:
        1) se DATABASE_URL estiver setada no .env, usa ela
        2) senão, monta a partir de rtls_db_* e garante +asyncpg
        """
        url = self.DATABASE_URL

        if not url:
            url = (
                f"postgresql+asyncpg://"
                f"{self.rtls_db_user}:{self.rtls_db_password}"
                f"@{self.rtls_db_host}:{self.rtls_db_port}/{self.rtls_db_name}"
            )

        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

        return url

    # ---------------- MQTT "genérico" usado hoje no código ----------------

    @property
    def MQTT_ENABLED(self) -> bool:
        return self.rtls_mqtt_enabled

    @property
    def MQTT_HOST(self) -> str:
        return self.rtls_mqtt_host

    @property
    def MQTT_PORT(self) -> int:
        return self.rtls_mqtt_port

    @property
    def MQTT_TOPIC(self) -> str:
        return self.rtls_mqtt_topic

    @property
    def MQTT_USERNAME(self) -> Optional[str]:
        return self.rtls_mqtt_username

    @property
    def MQTT_PASSWORD(self) -> Optional[str]:
        return self.rtls_mqtt_password

    @property
    def MQTT_GATEWAY_TOPIC_PREFIX(self) -> str:
        """
        Deduz o prefixo a partir do tópico de MQTT, por exemplo:

        rtls/gateways/#  -> rtls/gateways
        rtls/gw/#        -> rtls/gw
        """
        topic = self.rtls_mqtt_topic
        if topic.endswith("/#"):
            return topic[:-2]
        return topic

    # ---------------- Espelhos em MAIÚSCULO p/ uso direto (RTLS_MQTT_*) ----------------

    @property
    def RTLS_MQTT_ENABLED(self) -> bool:
        return self.rtls_mqtt_enabled

    @property
    def RTLS_MQTT_HOST(self) -> str:
        return self.rtls_mqtt_host

    @property
    def RTLS_MQTT_PORT(self) -> int:
        return self.rtls_mqtt_port

    @property
    def RTLS_MQTT_TOPIC(self) -> str:
        return self.rtls_mqtt_topic

    @property
    def RTLS_MQTT_USERNAME(self) -> Optional[str]:
        return self.rtls_mqtt_username

    @property
    def RTLS_MQTT_PASSWORD(self) -> Optional[str]:
        return self.rtls_mqtt_password


settings = Settings()
