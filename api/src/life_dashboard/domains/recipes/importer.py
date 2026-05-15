"""
Recipe importer — fetches a URL and extracts a Schema.org Recipe from its
JSON-LD data, returning a populated RecipeCreate ready for the service layer.

Only standard-library + httpx (already a project dependency) are used; no
extra packages required.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from decimal import Decimal, InvalidOperation

import httpx

from life_dashboard.domains.recipes.schemas import IngredientData, RecipeCreate, StepData

# ── ISO 8601 duration ─────────────────────────────────────────────────────────

# Matches the parts we care about from durations like PT15M, PT1H30M, P1DT2H
_ISO_DURATION_RE = re.compile(
    r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:[\d.]+S)?",
    re.IGNORECASE,
)


def _parse_iso_duration_minutes(val: str | None) -> int | None:
    if not val:
        return None
    m = _ISO_DURATION_RE.search(str(val))
    if not m:
        return None
    days = int(m.group(1) or 0)
    hours = int(m.group(2) or 0)
    minutes = int(m.group(3) or 0)
    total = days * 24 * 60 + hours * 60 + minutes
    return total or None


# ── Servings ──────────────────────────────────────────────────────────────────

def _parse_servings(val: str | int | float | list | None) -> int | None:
    if val is None:
        return None
    if isinstance(val, list):
        val = val[0] if val else None
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val) if val > 0 else None
    # e.g. "4 servings", "4-6 people", "Makes 12"
    m = re.search(r"\d+", str(val))
    return int(m.group()) if m else None


# ── HTML → JSON-LD extraction ─────────────────────────────────────────────────

_JSONLD_SCRIPT_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _extract_json_ld_blocks(html: str) -> list[dict]:
    blocks: list[dict] = []
    for m in _JSONLD_SCRIPT_RE.finditer(html):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            blocks.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            blocks.append(data)
    return blocks


def _is_recipe_type(obj: dict) -> bool:
    t = obj.get("@type", "")
    types = t if isinstance(t, list) else [t]
    return any("Recipe" in str(x) for x in types)


def _find_recipe_block(blocks: list[dict]) -> dict | None:
    for block in blocks:
        if _is_recipe_type(block):
            return block
        # Some sites nest under @graph
        for item in block.get("@graph", []):
            if isinstance(item, dict) and _is_recipe_type(item):
                return item
    return None


# ── Ingredient parsing ────────────────────────────────────────────────────────

# Common units — used for optional quantity/unit extraction
_UNITS = (
    "cups?", "tbsp", "tablespoons?", "tsp", "teaspoons?",
    "oz", "ounces?", "lbs?", "pounds?",
    "g", "grams?", "kg", "kilograms?",
    "ml", "milliliters?", "l", "liters?",
    "cloves?", "stalks?", "bunches?", "cans?",
    "packages?", "pkg", "pieces?", "slices?",
    "pinch(?:es)?", "dash(?:es)?", "handfuls?", "sprigs?", "heads?",
)
_UNIT_GROUP = "(?:" + "|".join(_UNITS) + ")"

# Matches: optional leading number (int, decimal, fraction, unicode fraction)
# followed by optional unit, then the rest as name
_UNICODE_FRACTIONS = {"½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4",
                      "¾": "3/4", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8"}

_INGREDIENT_RE = re.compile(
    r"^"
    r"([\d\s./]+|[½⅓⅔¼¾⅛⅜⅝⅞])?"   # group 1: quantity string (optional)
    r"\s*"
    r"(" + _UNIT_GROUP + r")?"       # group 2: unit (optional)
    r"\s+"
    r"(.+)$",                        # group 3: name
    re.IGNORECASE,
)


def _parse_quantity(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    raw = raw.strip()
    for uni, frac in _UNICODE_FRACTIONS.items():
        raw = raw.replace(uni, frac)
    raw = raw.strip()
    # "1 1/2" → 1.5, "3/4" → 0.75, "2" → 2
    parts = raw.split()
    total = Decimal(0)
    for part in parts:
        if "/" in part:
            num, denom = part.split("/", 1)
            try:
                total += Decimal(num.strip()) / Decimal(denom.strip())
            except (InvalidOperation, ZeroDivisionError):
                return None
        else:
            try:
                total += Decimal(part)
            except InvalidOperation:
                return None
    return total if total > 0 else None


def _parse_ingredient(raw_str: str, sort_order: int) -> IngredientData:
    text = _strip_html(raw_str)
    # Replace unicode fractions before matching
    normalized = text
    for uni, frac in _UNICODE_FRACTIONS.items():
        normalized = normalized.replace(uni, frac)

    m = _INGREDIENT_RE.match(normalized)
    if m and m.group(3):
        qty = _parse_quantity(m.group(1))
        unit_raw = m.group(2)
        unit = unit_raw.rstrip("s").lower() if unit_raw else None  # normalise plurals lightly
        name = m.group(3).strip()
        return IngredientData(name=name, quantity=qty, unit=unit, sort_order=sort_order)

    # Fallback: store the whole string as name
    return IngredientData(name=text, sort_order=sort_order)


def _parse_ingredients(raw: list) -> list[IngredientData]:
    result = []
    for i, item in enumerate(raw):
        if isinstance(item, str) and item.strip():
            result.append(_parse_ingredient(item, i))
        elif isinstance(item, dict):
            name = item.get("name") or item.get("text") or ""
            if name.strip():
                result.append(_parse_ingredient(name, i))
    return result


# ── Step parsing ──────────────────────────────────────────────────────────────

def _instruction_text(item) -> str | None:
    if isinstance(item, str):
        return _strip_html(item) or None
    if isinstance(item, dict):
        text = item.get("text") or item.get("name") or ""
        return _strip_html(str(text)) or None
    return None


def _parse_steps(raw) -> list[StepData]:
    if isinstance(raw, str):
        text = raw.strip()
        return [StepData(step_number=1, instruction=text)] if text else []

    if not isinstance(raw, list):
        return []

    # Flatten HowToSection → itemListElement
    flat: list = []
    for item in raw:
        if isinstance(item, dict) and item.get("@type") == "HowToSection":
            for sub in item.get("itemListElement", []):
                flat.append(sub)
        else:
            flat.append(item)

    steps = []
    for i, item in enumerate(flat, start=1):
        text = _instruction_text(item)
        if text:
            steps.append(StepData(step_number=i, instruction=text))
    return steps


# ── HTML entity helpers ───────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    """Remove inline HTML tags and decode HTML entities."""
    text = re.sub(r"<[^>]+>", "", text)
    return html_lib.unescape(text).strip()


# ── Image extraction ─────────────────────────────────────────────────────────

def _extract_image_url(raw) -> str | None:
    """
    Schema.org `image` can be:
    - a string URL
    - an ImageObject dict with "url" or "contentUrl"
    - a list of any of the above (we use the first)
    """
    if not raw:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if not raw:
        return None
    if isinstance(raw, str):
        return raw.strip() or None
    if isinstance(raw, dict):
        url = raw.get("url") or raw.get("contentUrl") or ""
        return str(url).strip() or None
    return None


# ── Public entry point ────────────────────────────────────────────────────────

class RecipeImportError(Exception):
    """Raised when the URL can't be fetched or contains no Recipe schema."""


async def fetch_recipe_preview(url: str) -> RecipeCreate:
    """
    Fetch *url*, find a Schema.org Recipe in the JSON-LD, and return a
    ``RecipeCreate`` populated with whatever the page provides.

    Raises ``RecipeImportError`` on network/parse failure.
    Does **not** write to the database — callers decide whether to save.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            html = response.text
    except httpx.HTTPStatusError as exc:
        raise RecipeImportError(
            f"The page returned HTTP {exc.response.status_code}."
        ) from exc
    except httpx.TimeoutException:
        raise RecipeImportError("The request timed out — the site may be slow or unreachable.")
    except httpx.RequestError as exc:
        raise RecipeImportError(f"Could not reach that URL: {exc}") from exc

    blocks = _extract_json_ld_blocks(html)
    recipe = _find_recipe_block(blocks)

    if recipe is None:
        raise RecipeImportError(
            "No Schema.org Recipe found on this page. "
            "The site may not publish structured recipe data."
        )

    # ── Name ──────────────────────────────────────────────────────────────────
    name = recipe.get("name") or ""
    if isinstance(name, list):
        name = name[0] if name else ""
    name = _strip_html(str(name)).strip()
    if not name:
        raise RecipeImportError("The recipe schema has no name.")

    # ── Description ───────────────────────────────────────────────────────────
    description = recipe.get("description") or None
    if description:
        description = _strip_html(str(description)).strip() or None

    # ── Times ─────────────────────────────────────────────────────────────────
    prep_time = _parse_iso_duration_minutes(recipe.get("prepTime"))
    cook_time = _parse_iso_duration_minutes(recipe.get("cookTime"))
    # Some sites use totalTime only
    if prep_time is None and cook_time is None:
        total = _parse_iso_duration_minutes(recipe.get("totalTime"))
        if total:
            cook_time = total

    # ── Servings ──────────────────────────────────────────────────────────────
    servings = _parse_servings(recipe.get("recipeYield"))

    # ── Ingredients ───────────────────────────────────────────────────────────
    raw_ingredients = recipe.get("recipeIngredient") or []
    ingredients = _parse_ingredients(raw_ingredients)

    # ── Steps ─────────────────────────────────────────────────────────────────
    raw_steps = recipe.get("recipeInstructions") or []
    steps = _parse_steps(raw_steps)

    cover_image_url = _extract_image_url(recipe.get("image"))

    return RecipeCreate(
        name=name,
        description=description,
        cover_image_url=cover_image_url,
        source_url=url,
        prep_time_minutes=prep_time,
        cook_time_minutes=cook_time,
        servings=servings,
        ingredients=ingredients,
        steps=steps,
    )
