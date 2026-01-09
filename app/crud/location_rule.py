from app.crud.base import CRUDBase
from app.models.location import LocationRule
from app.schemas.location import LocationRuleCreate, LocationRuleUpdate


class CRUDLocationRule(CRUDBase[LocationRule, LocationRuleCreate, LocationRuleUpdate]):
    pass


location_rule = CRUDLocationRule(LocationRule)
