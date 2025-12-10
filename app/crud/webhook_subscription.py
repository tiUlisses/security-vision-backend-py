from app.crud.base import CRUDBase
from app.models.webhook_subscription import WebhookSubscription
from app.schemas.webhook import WebhookSubscriptionCreate, WebhookSubscriptionUpdate


class CRUDWebhookSubscription(
    CRUDBase[WebhookSubscription, WebhookSubscriptionCreate, WebhookSubscriptionUpdate]
):
    pass


webhook_subscription = CRUDWebhookSubscription(WebhookSubscription)
