import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from life_dashboard.domains.tags.schemas import TagSummary
from life_dashboard.core.pydantic_types import CoercedList


class IngredientData(BaseModel):
    name: str = Field(min_length=1)
    quantity: Decimal | None = None
    unit: str | None = Field(default=None, max_length=100)
    notes: str | None = None
    sort_order: int = 0


class IngredientResponse(IngredientData):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    recipe_id: uuid.UUID


class StepData(BaseModel):
    step_number: int = Field(ge=1)
    instruction: str = Field(min_length=1)
    notes: str | None = None


class StepResponse(StepData):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    recipe_id: uuid.UUID


class RecipeCreate(BaseModel):
    goal_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=500)
    description: str | None = None
    cover_image_url: str | None = None
    source_url: str | None = None
    prep_time_minutes: int | None = Field(default=None, ge=0)
    cook_time_minutes: int | None = Field(default=None, ge=0)
    servings: int | None = Field(default=None, ge=1)
    notes: str | None = None
    ingredients: list[IngredientData] = []
    steps: list[StepData] = []
    body: dict | None = None
    visibility: str = "household"
    shared_with_user_ids: list[str] = []


class RecipeUpdate(BaseModel):
    goal_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    cover_image_url: str | None = None
    source_url: str | None = None
    prep_time_minutes: int | None = Field(default=None, ge=0)
    cook_time_minutes: int | None = Field(default=None, ge=0)
    servings: int | None = Field(default=None, ge=1)
    notes: str | None = None
    ingredients: list[IngredientData] | None = None
    steps: list[StepData] | None = None
    body: dict | None = None
    visibility: str | None = None
    shared_with_user_ids: list[str] | None = None


class RecipeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    goal_id: uuid.UUID | None
    name: str
    description: str | None
    cover_image_url: str | None
    source_url: str | None
    prep_time_minutes: int | None
    cook_time_minutes: int | None
    servings: int | None
    notes: str | None
    body: dict | None
    visibility: str
    shared_with_user_ids: CoercedList
    created_at: datetime
    updated_at: datetime
    ingredients: list[IngredientResponse] = []
    steps: list[StepResponse] = []
    tags: list[TagSummary] = []


class RecipeListResponse(BaseModel):
    items: list[RecipeResponse]
    total: int
    limit: int
    offset: int


# ── Grocery list integration ───────────────────────────────────────────────────

class AddToGroceryListRequest(BaseModel):
    """POST /recipes/{recipe_id}/add-to-grocery-list"""
    list_id: uuid.UUID
    servings_scale: float = Field(default=1.0, gt=0)


class AddToGroceryListResponse(BaseModel):
    list_id: uuid.UUID
    added: int    # items appended
    skipped: int  # already-present ingredient IDs skipped
