import uuid

from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.recipes.models import Recipe, RecipeIngredient, RecipeStep
from life_dashboard.domains.recipes.schemas import (
    IngredientData,
    IngredientResponse,
    RecipeCreate,
    RecipeListResponse,
    RecipeResponse,
    RecipeUpdate,
    StepData,
    StepResponse,
)
from life_dashboard.domains.tags.models import Tag, Tagging
from life_dashboard.domains.tags.schemas import TagSummary

_ENTITY_TYPE = "recipe"


# ── Tag loaders ───────────────────────────────────────────────────────────────

async def _load_tags(
    db: AsyncSession, recipe_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[TagSummary]]:
    if not recipe_ids:
        return {}
    rows = (await db.execute(
        select(Tag, Tagging.entity_id)
        .join(Tagging, Tag.id == Tagging.tag_id)
        .where(Tagging.entity_type == _ENTITY_TYPE, Tagging.entity_id.in_(recipe_ids))
        .order_by(Tag.name)
    )).all()
    tag_map: dict[uuid.UUID, list[TagSummary]] = {}
    for tag, entity_id in rows:
        tag_map.setdefault(entity_id, []).append(TagSummary.model_validate(tag))
    return tag_map


# ── Child loaders ─────────────────────────────────────────────────────────────

async def _load_children(
    db: AsyncSession, recipe_ids: list[uuid.UUID]
) -> tuple[
    dict[uuid.UUID, list[RecipeIngredient]],
    dict[uuid.UUID, list[RecipeStep]],
]:
    if not recipe_ids:
        return {}, {}

    ing_rows = (await db.execute(
        select(RecipeIngredient)
        .where(RecipeIngredient.recipe_id.in_(recipe_ids))
        .order_by(RecipeIngredient.sort_order)
    )).scalars().all()

    step_rows = (await db.execute(
        select(RecipeStep)
        .where(RecipeStep.recipe_id.in_(recipe_ids))
        .order_by(RecipeStep.step_number)
    )).scalars().all()

    ing_map: dict[uuid.UUID, list[RecipeIngredient]] = {}
    for i in ing_rows:
        ing_map.setdefault(i.recipe_id, []).append(i)

    step_map: dict[uuid.UUID, list[RecipeStep]] = {}
    for s in step_rows:
        step_map.setdefault(s.recipe_id, []).append(s)

    return ing_map, step_map


def _build_response(
    recipe: Recipe,
    ingredients: list[RecipeIngredient],
    steps: list[RecipeStep],
    tags: list[TagSummary],
) -> RecipeResponse:
    return RecipeResponse.model_validate(recipe).model_copy(update={
        "ingredients": [IngredientResponse.model_validate(i) for i in ingredients],
        "steps": [StepResponse.model_validate(s) for s in steps],
        "tags": tags,
    })


# ── Child writers ─────────────────────────────────────────────────────────────

async def _replace_ingredients(
    db: AsyncSession, recipe_id: uuid.UUID, items: list[IngredientData]
) -> None:
    await db.execute(
        sa_delete(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe_id)
    )
    for item in items:
        db.add(RecipeIngredient(recipe_id=recipe_id, **item.model_dump()))


async def _replace_steps(
    db: AsyncSession, recipe_id: uuid.UUID, items: list[StepData]
) -> None:
    await db.execute(sa_delete(RecipeStep).where(RecipeStep.recipe_id == recipe_id))
    for item in items:
        db.add(RecipeStep(recipe_id=recipe_id, **item.model_dump()))


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def create_recipe(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: RecipeCreate,
) -> RecipeResponse:
    recipe = Recipe(
        household_id=household_id,
        created_by_user_id=user_id,
        goal_id=data.goal_id,
        name=data.name,
        description=data.description,
        source_url=data.source_url,
        prep_time_minutes=data.prep_time_minutes,
        cook_time_minutes=data.cook_time_minutes,
        servings=data.servings,
        notes=data.notes,
    )
    db.add(recipe)
    await db.flush()

    await _replace_ingredients(db, recipe.id, data.ingredients)
    await _replace_steps(db, recipe.id, data.steps)

    await db.commit()
    await db.refresh(recipe)

    ing_map, step_map = await _load_children(db, [recipe.id])
    tag_map = await _load_tags(db, [recipe.id])
    return _build_response(
        recipe, ing_map.get(recipe.id, []), step_map.get(recipe.id, []),
        tag_map.get(recipe.id, []),
    )


async def get_recipe(
    db: AsyncSession,
    recipe_id: uuid.UUID,
    household_id: uuid.UUID,
) -> RecipeResponse | None:
    result = await db.execute(
        select(Recipe).where(Recipe.id == recipe_id, Recipe.household_id == household_id)
    )
    recipe = result.scalar_one_or_none()
    if recipe is None:
        return None
    ing_map, step_map = await _load_children(db, [recipe.id])
    tag_map = await _load_tags(db, [recipe.id])
    return _build_response(
        recipe, ing_map.get(recipe.id, []), step_map.get(recipe.id, []),
        tag_map.get(recipe.id, []),
    )


async def list_recipes(
    db: AsyncSession,
    household_id: uuid.UUID,
    *,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> RecipeListResponse:
    query = select(Recipe).where(Recipe.household_id == household_id)
    if search:
        query = query.where(Recipe.name.ilike(f"%{search}%"))

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    recipes = list(
        (await db.execute(
            query.order_by(Recipe.name.asc()).limit(limit).offset(offset)
        )).scalars().all()
    )

    ids = [r.id for r in recipes]
    ing_map, step_map = await _load_children(db, ids)
    tag_map = await _load_tags(db, ids)
    return RecipeListResponse(
        items=[
            _build_response(r, ing_map.get(r.id, []), step_map.get(r.id, []), tag_map.get(r.id, []))
            for r in recipes
        ],
        total=total, limit=limit, offset=offset,
    )


async def update_recipe(
    db: AsyncSession,
    recipe_id: uuid.UUID,
    household_id: uuid.UUID,
    data: RecipeUpdate,
) -> RecipeResponse | None:
    result = await db.execute(
        select(Recipe).where(Recipe.id == recipe_id, Recipe.household_id == household_id)
    )
    recipe = result.scalar_one_or_none()
    if recipe is None:
        return None

    sent = data.model_fields_set
    for field in ("goal_id", "name", "description", "source_url",
                  "prep_time_minutes", "cook_time_minutes", "servings", "notes"):
        if field in sent:
            setattr(recipe, field, getattr(data, field))

    if "ingredients" in sent and data.ingredients is not None:
        await _replace_ingredients(db, recipe.id, data.ingredients)
    if "steps" in sent and data.steps is not None:
        await _replace_steps(db, recipe.id, data.steps)

    await db.commit()
    await db.refresh(recipe)

    ing_map, step_map = await _load_children(db, [recipe.id])
    tag_map = await _load_tags(db, [recipe.id])
    return _build_response(
        recipe, ing_map.get(recipe.id, []), step_map.get(recipe.id, []),
        tag_map.get(recipe.id, []),
    )


async def delete_recipe(
    db: AsyncSession,
    recipe_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(Recipe).where(Recipe.id == recipe_id, Recipe.household_id == household_id)
    )
    recipe = result.scalar_one_or_none()
    if recipe is None:
        return False
    await db.delete(recipe)
    await db.commit()
    return True


# ── Tag mutations ─────────────────────────────────────────────────────────────

async def add_tag(
    db: AsyncSession,
    recipe_id: uuid.UUID,
    tag_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    """Returns False if the recipe or tag doesn't belong to this household."""
    recipe_exists = (await db.execute(
        select(Recipe.id).where(Recipe.id == recipe_id, Recipe.household_id == household_id)
    )).scalar_one_or_none()
    if recipe_exists is None:
        return False

    tag_exists = (await db.execute(
        select(Tag.id).where(Tag.id == tag_id, Tag.household_id == household_id)
    )).scalar_one_or_none()
    if tag_exists is None:
        return False

    already = (await db.execute(
        select(Tagging.id).where(
            Tagging.tag_id == tag_id,
            Tagging.entity_type == _ENTITY_TYPE,
            Tagging.entity_id == recipe_id,
        )
    )).scalar_one_or_none()
    if already is None:
        db.add(Tagging(tag_id=tag_id, entity_type=_ENTITY_TYPE, entity_id=recipe_id))
        await db.commit()
    return True


async def remove_tag(
    db: AsyncSession,
    recipe_id: uuid.UUID,
    tag_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    recipe_exists = (await db.execute(
        select(Recipe.id).where(Recipe.id == recipe_id, Recipe.household_id == household_id)
    )).scalar_one_or_none()
    if recipe_exists is None:
        return False

    await db.execute(
        sa_delete(Tagging).where(
            Tagging.tag_id == tag_id,
            Tagging.entity_type == _ENTITY_TYPE,
            Tagging.entity_id == recipe_id,
        )
    )
    await db.commit()
    return True
