from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class GenerateQrRequest(BaseModel):
    account_id: UUID
    amount: Decimal | None = Field(default=None, gt=0)
    merchant_city: str = Field(default="Singapore", max_length=15)
