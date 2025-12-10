from datetime import datetime
from typing import Optional, Dict, Any

from pydantic import AnyHttpUrl, BaseModel, Field


class WebhookSubscriptionBase(BaseModel):
    name: str = Field(..., max_length=255)
    url: AnyHttpUrl
    secret_token: Optional[str] = Field(None, max_length=255)
    # Regra de filtro: se None -> recebe todos os eventos
    # se tiver valor -> recebe apenas aquele event_type
    event_type_filter: Optional[str] = Field(None, max_length=64)
    is_active: bool = True


class WebhookSubscriptionCreate(WebhookSubscriptionBase):
    pass


class WebhookSubscriptionUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    url: Optional[AnyHttpUrl] = None
    secret_token: Optional[str] = Field(None, max_length=255)
    event_type_filter: Optional[str] = Field(None, max_length=64)
    is_active: Optional[bool] = None


class WebhookSubscriptionRead(WebhookSubscriptionBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# NOVO: metadados de tipos de evento, para a tela de configuração
class WebhookEventTypeMeta(BaseModel):
    event_type: str
    label: str
    description: str
    sample_payload: Dict[str, Any]
