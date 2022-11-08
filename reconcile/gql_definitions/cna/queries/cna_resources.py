"""
Generated by qenerate plugin=pydantic_v1. DO NOT MODIFY MANUALLY!
"""
from enum import Enum  # noqa: F401 # pylint: disable=W0611
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

from reconcile.gql_definitions.cna.queries.aws_account_fragment import (
    CNAAWSAccountRoleARNs,
)


DEFINITION = """
fragment CNAAWSAccountRoleARNs on AWSAccount_v1 {
  name
  cna {
    defaultRoleARN
    moduleRoleARNS {
      module
      arn
    }
  }
}

query CNAssets {
  namespaces: namespaces_v1 {
    name
    externalResources {
      provider
      provisioner {
        name
      }
      ... on NamespaceCNAsset_v1 {
        resources {
          provider
          ... on CNANullAsset_v1 {
            name: identifier
            addr_block
          }
          ... on CNAAssumeRoleAsset_v1{
            name: identifier
            aws_assume_role {
              slug
              account {
                ... CNAAWSAccountRoleARNs
              }
            }
          }
          ... on CNARDSInstance_v1 {
            name: identifier
            aws_rds {
              vpc {
                vpc_id
                region
                account {
                  ... CNAAWSAccountRoleARNs
                }
              }
              db_subnet_group_name
              engine
              engine_version
              instance_class
              allocated_storage
              max_allocated_storage
              backup_retention_period
              backup_window
              maintenance_window
            }
          }
        }
      }
    }
  }
}
"""


class ExternalResourcesProvisionerV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceExternalResourceV1(BaseModel):
    provider: str = Field(..., alias="provider")
    provisioner: ExternalResourcesProvisionerV1 = Field(..., alias="provisioner")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CNAssetV1(BaseModel):
    provider: str = Field(..., alias="provider")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CNANullAssetV1(CNAssetV1):
    name: str = Field(..., alias="name")
    addr_block: Optional[str] = Field(..., alias="addr_block")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CNAAssumeRoleAssetConfigV1(BaseModel):
    slug: str = Field(..., alias="slug")
    account: CNAAWSAccountRoleARNs = Field(..., alias="account")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CNAAssumeRoleAssetV1(CNAssetV1):
    name: str = Field(..., alias="name")
    aws_assume_role: CNAAssumeRoleAssetConfigV1 = Field(..., alias="aws_assume_role")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AWSVPCV1(BaseModel):
    vpc_id: str = Field(..., alias="vpc_id")
    region: str = Field(..., alias="region")
    account: CNAAWSAccountRoleARNs = Field(..., alias="account")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CNARDSInstanceConfigV1(BaseModel):
    vpc: AWSVPCV1 = Field(..., alias="vpc")
    db_subnet_group_name: str = Field(..., alias="db_subnet_group_name")
    engine: str = Field(..., alias="engine")
    engine_version: str = Field(..., alias="engine_version")
    instance_class: str = Field(..., alias="instance_class")
    allocated_storage: int = Field(..., alias="allocated_storage")
    max_allocated_storage: int = Field(..., alias="max_allocated_storage")
    backup_retention_period: int = Field(..., alias="backup_retention_period")
    backup_window: str = Field(..., alias="backup_window")
    maintenance_window: str = Field(..., alias="maintenance_window")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CNARDSInstanceV1(CNAssetV1):
    name: str = Field(..., alias="name")
    aws_rds: CNARDSInstanceConfigV1 = Field(..., alias="aws_rds")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceCNAssetV1(NamespaceExternalResourceV1):
    resources: list[
        Union[CNANullAssetV1, CNAAssumeRoleAssetV1, CNARDSInstanceV1, CNAssetV1]
    ] = Field(..., alias="resources")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceV1(BaseModel):
    name: str = Field(..., alias="name")
    external_resources: Optional[
        list[Union[NamespaceCNAssetV1, NamespaceExternalResourceV1]]
    ] = Field(..., alias="externalResources")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CNAssetsQueryData(BaseModel):
    namespaces: Optional[list[NamespaceV1]] = Field(..., alias="namespaces")

    class Config:
        smart_union = True
        extra = Extra.forbid


def query(query_func: Callable, **kwargs) -> CNAssetsQueryData:
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
        CNAssetsQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return CNAssetsQueryData(**raw_data)