"""
Generated by qenerate plugin=pydantic_v1. DO NOT MODIFY MANUALLY!
"""
from collections.abc import Callable  # noqa: F401 # pylint: disable=W0611
from enum import Enum  # noqa: F401 # pylint: disable=W0611
from typing import (  # noqa: F401 # pylint: disable=W0611
    Any,
    Optional,
    Union,
)

from pydantic import (  # noqa: F401 # pylint: disable=W0611
    BaseModel,
    Extra,
    Field,
    Json,
)

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret


DEFINITION = """
fragment VaultSecret on VaultSecret_v1 {
    path
    field
    version
    format
}

query StatusPages {
  status_pages: status_page_v1 {
    name
    pageId
    apiUrl
    provider
    credentials {
      ...VaultSecret
    }
    components {
      name
      displayName
      description
      path
      groupName
      app {
        name
      }
      status_config: status {
        provider
        ... on ManualStatusProvider_v1 {
          manual {
            componentStatus
            from
            until
          }
        }
      }
    }
  }
}
"""


class AppV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class StatusProviderV1(BaseModel):
    provider: str = Field(..., alias="provider")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ManualStatusProviderConfigV1(BaseModel):
    component_status: str = Field(..., alias="componentStatus")
    q_from: Optional[str] = Field(..., alias="from")
    until: Optional[str] = Field(..., alias="until")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ManualStatusProviderV1(StatusProviderV1):
    manual: ManualStatusProviderConfigV1 = Field(..., alias="manual")

    class Config:
        smart_union = True
        extra = Extra.forbid


class StatusPageComponentV1(BaseModel):
    name: str = Field(..., alias="name")
    display_name: str = Field(..., alias="displayName")
    description: Optional[str] = Field(..., alias="description")
    path: str = Field(..., alias="path")
    group_name: Optional[str] = Field(..., alias="groupName")
    app: AppV1 = Field(..., alias="app")
    status_config: Optional[
        list[Union[ManualStatusProviderV1, StatusProviderV1]]
    ] = Field(..., alias="status_config")

    class Config:
        smart_union = True
        extra = Extra.forbid


class StatusPageV1(BaseModel):
    name: str = Field(..., alias="name")
    page_id: str = Field(..., alias="pageId")
    api_url: str = Field(..., alias="apiUrl")
    provider: str = Field(..., alias="provider")
    credentials: VaultSecret = Field(..., alias="credentials")
    components: Optional[list[StatusPageComponentV1]] = Field(..., alias="components")

    class Config:
        smart_union = True
        extra = Extra.forbid


class StatusPagesQueryData(BaseModel):
    status_pages: Optional[list[StatusPageV1]] = Field(..., alias="status_pages")

    class Config:
        smart_union = True
        extra = Extra.forbid


def query(query_func: Callable, **kwargs: Any) -> StatusPagesQueryData:
    """
    This is a convenience function which queries and parses the data into
    concrete types. It should be compatible with most GQL clients.
    You do not have to use it to consume the generated data classes.
    Alternatively, you can also mime and alternate the behavior
    of this function in the caller.

    Parameters:
        query_func (Callable): Function which queries your GQL Server
        kwargs: optional arguments that will be passed to the query function

    Returns:
        StatusPagesQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return StatusPagesQueryData(**raw_data)
