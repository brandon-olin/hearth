import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from life_dashboard.core.pydantic_types import CoercedList

GroceryListStatus = Literal["active", "completed", "archived"]


class GroceryItemData(BaseModel):
    name: str = Field(min_length=1)
    quantity: Decimal | None = None
    unit: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=200)
    is_checked: bool = False
    notes: str | None = None
    recipe_id: uuid.UUID | None = None
    recipe_ingredient_id: uuid.UUID | None = None


class GroceryItemResponse(GroceryItemData):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    list_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class GroceryItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    quantity: Decimal | None = None
    unit: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=200)
    is_checked: bool | None = None
    notes: str | None = None


class GroceryListCreate(BaseModel):
    todo_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=500)
    store: str | None = Field(default=None, max_length=200)
    status: GroceryListStatus = "active"
    items: list[GroceryItemData] = []
    visibility: str = "household"
    shared_with_user_ids: list[str] = []


class GroceryListUpdate(BaseModel):
    todo_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=500)
    store: str | None = Field(default=None, max_length=200)
    status: GroceryListStatus | None = None
    items: list[GroceryItemData] | None = None
    visibility: str | None = None
    shared_with_user_ids: list[str] | None = None


class GroceryListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    todo_id: uuid.UUID | None
    name: str
    store: str | None
    status: str
    visibility: str
    shared_with_user_ids: CoercedList
    created_at: datetime
    updated_at: datetime
    items: list[GroceryItemResponse] = []


class GroceryListListResponse(BaseModel):
    items: list[GroceryListResponse]
    total: int
    limit: int
    offset: int
