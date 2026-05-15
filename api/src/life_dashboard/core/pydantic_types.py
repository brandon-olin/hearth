"""
Shared Pydantic annotated types for use across domain schemas.
"""
from typing import Annotated

from pydantic import BeforeValidator


def _coerce_list(v: object) -> list:
    """Coerce None (legacy DB rows) to an empty list."""
    return v if v is not None else []


# Use this anywhere a JSON list column may be NULL in the database.
# model_validate(orm_obj) will convert None → [] before Pydantic validates.
CoercedList = Annotated[list[str], BeforeValidator(_coerce_list)]
