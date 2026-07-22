import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from life_dashboard.core.pydantic_types import CoercedList

MealSlot = Literal["breakfast", "lunch", "dinner", "snack"]

#: Display order for the grid rows. The DB CHECK constraint holds the same four
#: values — keep them in step.
MEAL_SLOTS: tuple[str, ...] = ("breakfast", "lunch", "dinner", "snack")

Visibility = Literal["household", "personal", "members"]


class MealPlanEntryCreate(BaseModel):
    recipe_id: uuid.UUID
    entry_date: date
    meal_slot: MealSlot
    servings: int | None = Field(default=None, ge=1, le=100)
    notes: str | None = None
    sort_order: int = 0


class MealPlanEntryUpdate(BaseModel):
    """Moving an entry between cells — the drag-to-another-day case."""
    entry_date: date | None = None
    meal_slot: MealSlot | None = None
    servings: int | None = Field(default=None, ge=1, le=100)
    notes: str | None = None
    sort_order: int | None = None


class MealPlanEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    plan_id: uuid.UUID
    recipe_id: uuid.UUID
    entry_date: date
    meal_slot: MealSlot
    servings: int | None
    notes: str | None
    sort_order: int
    created_at: datetime
    updated_at: datetime
    #: Denormalised for the grid, which renders names and never re-fetches each
    #: recipe. Filled in by the service; not a column.
    recipe_name: str | None = None
    recipe_cover_image_url: str | None = None


class MealPlanCreate(BaseModel):
    #: Any day inside the desired week; normalised to that week's Monday.
    week_start: date
    notes: str | None = None
    visibility: Visibility = "household"
    shared_with_user_ids: CoercedList | None = None


class MealPlanUpdate(BaseModel):
    notes: str | None = None
    visibility: Visibility | None = None
    shared_with_user_ids: CoercedList | None = None


class MealPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    week_start: date
    notes: str | None
    visibility: Visibility
    shared_with_user_ids: CoercedList = []
    created_at: datetime
    updated_at: datetime
    entries: list[MealPlanEntryResponse] = []


class MealPlanListResponse(BaseModel):
    items: list[MealPlanResponse]
    total: int


class GenerateGroceryListRequest(BaseModel):
    """Turn a planned week into groceries.

    Either append to an existing list (``list_id``) or create a new one
    (``name``). Sending neither creates a list named after the week.
    """
    list_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=500)
    store: str | None = Field(default=None, max_length=200)


class AggregatedIngredient(BaseModel):
    """One merged line of the generated list, for the confirmation UI."""
    name: str
    quantity: Decimal | None = None
    unit: str | None = None
    #: How many planned recipes contributed to this line. >1 means it was
    #: combined rather than duplicated.
    from_recipes: int = 1


class GenerateGroceryListResponse(BaseModel):
    list_id: uuid.UUID
    list_name: str
    created_list: bool
    recipes_planned: int
    #: Lines written to the list this call.
    added: int
    #: Lines already present (an earlier generate, or a manual entry) and left
    #: alone — this endpoint is safe to call twice.
    skipped: int
    items: list[AggregatedIngredient] = []
