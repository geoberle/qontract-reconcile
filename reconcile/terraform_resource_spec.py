from dataclasses import dataclass, field
import inspect
import json
from typing import Any, Optional


@dataclass
class TerraformResourceSpec:

    resource: dict[str, Any]
    namespace: dict[str, Any]
    output_resource_name: Optional[str]
    owner_tags: dict[str, str]

    # the output from a previous tf run
    tf_secret: Optional[dict[str, str]] = field(init=False)

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

    @property
    def annotations(self) -> dict[str, Any]:
        return json.loads(self.resource.get('annotations') or '{}')

    def get_tf_secret_field(self, field: str):
        if self.tf_secret:
            return self.tf_secret.get(field, None)
        else:
            return None

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
