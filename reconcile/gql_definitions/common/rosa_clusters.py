"""
Generated by qenerate plugin=pydantic_v1. DO NOT MODIFY MANUALLY!
"""
from collections.abc import Callable  # noqa: F401 # pylint: disable=W0611
from datetime import datetime  # noqa: F401 # pylint: disable=W0611
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

query RosaClusters($filter: JSON) {
  clusters: clusters_v1(filter: $filter) {
    name
    spec {
      id
      product
      channel
      ... on ClusterSpecROSA_v1 {
        region
        account {
          name
          uid
          automationToken {
            ... VaultSecret
          }
        }
      }
    }
    ocm {
      environment {
        url
        accessTokenClientId
        accessTokenUrl
        accessTokenClientSecret {
          ... VaultSecret
        }
      }
      orgId
      accessTokenClientId
      accessTokenUrl
      accessTokenClientSecret {
        ... VaultSecret
      }
    }
  }
}
"""


class ConfiguredBaseModel(BaseModel):
    class Config:
        smart_union=True
        extra=Extra.forbid


class ClusterSpecV1(ConfiguredBaseModel):
    q_id: Optional[str] = Field(..., alias="id")
    product: str = Field(..., alias="product")
    channel: str = Field(..., alias="channel")


class AWSAccountV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    uid: str = Field(..., alias="uid")
    automation_token: VaultSecret = Field(..., alias="automationToken")


class ClusterSpecROSAV1(ClusterSpecV1):
    region: str = Field(..., alias="region")
    account: Optional[AWSAccountV1] = Field(..., alias="account")


class OpenShiftClusterManagerEnvironmentV1(ConfiguredBaseModel):
    url: str = Field(..., alias="url")
    access_token_client_id: str = Field(..., alias="accessTokenClientId")
    access_token_url: str = Field(..., alias="accessTokenUrl")
    access_token_client_secret: VaultSecret = Field(..., alias="accessTokenClientSecret")


class OpenShiftClusterManagerV1(ConfiguredBaseModel):
    environment: OpenShiftClusterManagerEnvironmentV1 = Field(..., alias="environment")
    org_id: str = Field(..., alias="orgId")
    access_token_client_id: Optional[str] = Field(..., alias="accessTokenClientId")
    access_token_url: Optional[str] = Field(..., alias="accessTokenUrl")
    access_token_client_secret: Optional[VaultSecret] = Field(..., alias="accessTokenClientSecret")


class ClusterV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    spec: Optional[Union[ClusterSpecROSAV1, ClusterSpecV1]] = Field(..., alias="spec")
    ocm: Optional[OpenShiftClusterManagerV1] = Field(..., alias="ocm")


class RosaClustersQueryData(ConfiguredBaseModel):
    clusters: Optional[list[ClusterV1]] = Field(..., alias="clusters")


def query(query_func: Callable, **kwargs: Any) -> RosaClustersQueryData:
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
        RosaClustersQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return RosaClustersQueryData(**raw_data)
