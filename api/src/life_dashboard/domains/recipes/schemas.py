import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from life_dashboard.domains.tags.schemas import TagSummary


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
    source_url: str | None = None
    prep_time_minutes: int | None = Field(default=None, ge=0)
    cook_time_minutes: int | None = Field(default=None, ge=0)
    servings: int | None = Field(default=None, ge=1)
    notes: str | None = None
    ingredients: list[IngredientData] = []
    steps: list[StepData] = []


class RecipeUpdate(BaseModel):
    goal_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    source_url: str | None = None
    prep_time_minutes: int | None = Field(default=None, ge=0)
    cook_time_minutes: int | None = Field(default=None, ge=0)
    servings: int | None = Field(default=None, ge=1)
    notes: str | None = None
    ingredients: list[IngredientData] | None = None
    steps: list[StepData] | None = None


class RecipeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    goal_id: uuid.UUID | None
    name: str
    description: str | None
    source_url: str | None
    prep_time_minutes: int | None
    cook_time_minutes: int | None
    servings: int | None
    notes: str | None
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
