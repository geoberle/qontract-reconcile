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
from reconcile.gql_definitions.fragments.resource_file import ResourceFile


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

fragment ResourceFile on Resource_v1 {
  resourceFileSchema: schema
  content
}

query CNAssets {
  namespaces: namespaces_v1 {
    name
    managedExternalResources
    externalResources {
      provider
      provisioner {
        name
      }
      ... on NamespaceCNAsset_v1 {
        resources {
          provider
          identifier
          ... on CNANullAsset_v1 {
            overrides {
              addr_block
            }
          }
          ... on CNARDSInstance_v1 {
            vpc {
              vpc_id
              region
              account {
                ... CNAAWSAccountRoleARNs
              }
            }
            defaults {
              ... ResourceFile
            }
            overrides {
              name
              engine
              engine_version
              username
              instance_class
              allocated_storage
              max_allocated_storage
              backup_retention_period
              db_subnet_group_name
            }
          }
          ... on CNAAssumeRoleAsset_v1{
            account {
              ... CNAAWSAccountRoleARNs
            }
            overrides {
              slug
            }
            defaults {
              ... ResourceFile
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
    identifier: str = Field(..., alias="identifier")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CNANullAssetOverridesV1(BaseModel):
    addr_block: Optional[str] = Field(..., alias="addr_block")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CNANullAssetV1(CNAssetV1):
    overrides: Optional[CNANullAssetOverridesV1] = Field(..., alias="overrides")

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


class CNARDSInstanceOverridesV1(BaseModel):
    name: Optional[str] = Field(..., alias="name")
    engine: Optional[str] = Field(..., alias="engine")
    engine_version: Optional[str] = Field(..., alias="engine_version")
    username: Optional[str] = Field(..., alias="username")
    instance_class: Optional[str] = Field(..., alias="instance_class")
    allocated_storage: Optional[int] = Field(..., alias="allocated_storage")
    max_allocated_storage: Optional[int] = Field(..., alias="max_allocated_storage")
    backup_retention_period: Optional[int] = Field(..., alias="backup_retention_period")
    db_subnet_group_name: Optional[str] = Field(..., alias="db_subnet_group_name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CNARDSInstanceV1(CNAssetV1):
    vpc: AWSVPCV1 = Field(..., alias="vpc")
    defaults: Optional[ResourceFile] = Field(..., alias="defaults")
    overrides: Optional[CNARDSInstanceOverridesV1] = Field(..., alias="overrides")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CNAAssumeRoleAssetOverridesV1(BaseModel):
    slug: Optional[str] = Field(..., alias="slug")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CNAAssumeRoleAssetV1(CNAssetV1):
    account: CNAAWSAccountRoleARNs = Field(..., alias="account")
    overrides: Optional[CNAAssumeRoleAssetOverridesV1] = Field(..., alias="overrides")
    defaults: Optional[ResourceFile] = Field(..., alias="defaults")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceCNAssetV1(NamespaceExternalResourceV1):
    resources: list[
        Union[CNARDSInstanceV1, CNAAssumeRoleAssetV1, CNANullAssetV1, CNAssetV1]
    ] = Field(..., alias="resources")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceV1(BaseModel):
    name: str = Field(..., alias="name")
    managed_external_resources: Optional[bool] = Field(
        ..., alias="managedExternalResources"
    )
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
