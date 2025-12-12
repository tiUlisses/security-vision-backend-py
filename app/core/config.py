# app/core/config.py
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AnyHttpUrl


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
    CHATWOOT_ENABLED: bool = False
    CHATWOOT_BASE_URL: AnyHttpUrl | None = None
    CHATWOOT_API_ACCESS_TOKEN: str | None = None
    CHATWOOT_DEFAULT_ACCOUNT_ID: str | None = None
    CHATWOOT_DEFAULT_INBOX_IDENTIFIER: str | None = None
    CHATWOOT_DEFAULT_CONTACT_IDENTIFIER: str = "security-vision-system"

    # Config Pydantic v2
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignora qualquer variável extra que não tenhamos declarado
    )

    APP_NAME: str = "SecurityVision Position"

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

    media_root: str = "media"
    public_base_url: str = "http://localhost:8000"

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
    CAMBUS_TENANT: str = "default"
    CAMBUS_DEFAULT_SHARD: str = "shard-1"

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
