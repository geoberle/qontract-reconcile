from dataclasses import dataclass, field
import inspect
from typing import Any, Optional


@dataclass
class TerraformResourceSpec:

    resource: dict[str, Any]
    namespace: dict[str, Any]
    output_resource_name: Optional[str]
    owner_tags: dict[str, str]

    @property
    def provider(self):
        return self.resource.get("provider")

    @property
    def identifier(self):
        return self.resource.get("identifier")

    @property
    def account(self):
        return self.resource.get("account")

    @property
    def namespace_name(self) -> str:
        return self.namespace["name"]

    @property
    def cluster_name(self) -> str:
        return self.namespace["cluster"]["name"]

    @property
    def output_prefix(self):
        return f"{self.identifier}-{self.provider}"

    def get_output_resource_name(self):
        return self.output_resource_name or self.output_prefix

    @property
    def owning_namespace(self):
        return self.owner_tags.get("namespace")

    @property
    def owning_cluster(self):
        return self.owner_tags.get("cluster")

    @staticmethod
    def build_namespaced_owner_tags(namespace_name: str, cluster_name: str, integration_name: str):
        return {
            "namespace": namespace_name,
            "cluster": cluster_name,
            "managed_by_integration": integration_name
        }


@dataclass(frozen=True)
class TerraformResourceIdentifier:

    identifier: str
    provider: str
    account: str

    @classmethod
    def from_dict(cls, data):
        return cls(**{
            k: v for k, v in data.items()
            if k in inspect.signature(cls).parameters
        })

    @staticmethod
    def from_output_prefix_account(output_prefix, account):
        identifier, provider = output_prefix.rsplit("-", 1)
        return TerraformResourceIdentifier(
            identifier=identifier,
            provider=provider,
            account=account
        )
