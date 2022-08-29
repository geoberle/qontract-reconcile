"""
Generated by qenerate plugin=pydantic_v1. DO NOT MODIFY MANUALLY!
"""
from typing import (  # noqa: F401 # pylint: disable=W0611
    Any,
    Callable,
    Optional,
    Union,
)

from pydantic import (  # noqa: F401 # pylint: disable=W0611
    BaseModel,
    Extra,
    Field,
    Json,
)


class ChangeTypeChangeDetectorContextSelectorV1(BaseModel):
    selector: str = Field(..., alias="selector")
    when: str = Field(..., alias="when")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ChangeTypeChangeDetectorV1(BaseModel):
    provider: str = Field(..., alias="provider")
    change_schema: Optional[str] = Field(..., alias="changeSchema")
    context: Optional[ChangeTypeChangeDetectorContextSelectorV1] = Field(
        ..., alias="context"
    )

    class Config:
        smart_union = True
        extra = Extra.forbid


class ChangeTypeChangeDetectorJsonPathProviderV1(ChangeTypeChangeDetectorV1):
    json_path_selectors: Optional[list[str]] = Field(..., alias="jsonPathSelectors")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ChangeType(BaseModel):
    name: str = Field(..., alias="name")
    context_type: str = Field(..., alias="contextType")
    context_schema: Optional[str] = Field(..., alias="contextSchema")
    changes: Optional[
        list[
            Union[
                ChangeTypeChangeDetectorJsonPathProviderV1, ChangeTypeChangeDetectorV1
            ]
        ]
    ] = Field(..., alias="changes")

    class Config:
        smart_union = True
        extra = Extra.forbid
