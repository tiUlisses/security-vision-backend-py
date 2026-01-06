from app.crud.base import CRUDBase
from app.models.webhook_subscription import WebhookSubscription
from app.schemas.webhook import WebhookSubscriptionCreate, WebhookSubscriptionUpdate


class CRUDWebhookSubscription(
    CRUDBase[WebhookSubscription, WebhookSubscriptionCreate, WebhookSubscriptionUpdate]
):
    async def create(self, db, obj_in):  # type: ignore[override]
        if isinstance(obj_in, dict):
            obj_in_data = obj_in
        elif hasattr(obj_in, "model_dump"):
            obj_in_data = obj_in.model_dump(exclude_unset=True)
        else:
            obj_in_data = obj_in.dict(exclude_unset=True)

        if "url" in obj_in_data and obj_in_data["url"] is not None:
            obj_in_data["url"] = str(obj_in_data["url"])

        return await super().create(db, obj_in_data)

    async def update(self, db, db_obj, obj_in):  # type: ignore[override]
        if isinstance(obj_in, dict):
            update_data = obj_in
        elif hasattr(obj_in, "model_dump"):
            update_data = obj_in.model_dump(exclude_unset=True)
        else:
            update_data = obj_in.dict(exclude_unset=True)

        if "url" in update_data and update_data["url"] is not None:
            update_data["url"] = str(update_data["url"])

        return await super().update(db, db_obj, update_data)


webhook_subscription = CRUDWebhookSubscription(WebhookSubscription)
