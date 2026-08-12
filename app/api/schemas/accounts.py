from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class CreateAccountRequest(BaseModel):
    account_number: str = Field(min_length=1, max_length=34)
    owner_name: str = Field(min_length=1, max_length=255)
    account_type: str = Field(min_length=1, max_length=20)
    currency: str = Field(min_length=3, max_length=3)


class AccountResponse(BaseModel):
    id: UUID
    account_number: str
    owner_name: str
    account_type: str
    currency: str
    status: str
    version: int


class AccountBalanceResponse(BaseModel):
    account_id: UUID
    currency: str
    balance: Decimal
