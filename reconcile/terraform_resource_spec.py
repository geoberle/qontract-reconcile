from abc import abstractmethod
from pydantic.dataclasses import dataclass
from typing import Any, Optional, cast
import yaml
from reconcile import openshift_resources_base as orb


class OutputFormatProcessor:
    @abstractmethod
    def render(self, vars: dict[str, str]) -> dict[str, str]:
        return {}


@dataclass
class GenericSecretOutputFormatConfig(OutputFormatProcessor):

    data: Optional[str] = None

    def render(self, vars: dict[str, str]) -> dict[str, str]:
        if self.data:
            rendered_data = orb.process_jinja2_template(self.data, vars)
            return yaml.safe_load(rendered_data)
        else:
            return vars


@dataclass
class OutputFormat:

    provider: str
    data: Optional[str] = None

    def _formatter(self) -> OutputFormatProcessor:
        if self.provider == "generic-secret":
            return GenericSecretOutputFormatConfig(data=self.data)
        else:
            # default to generic-secret as provider for backwards compatibility
            return GenericSecretOutputFormatConfig()

    def render(self, vars: dict[str, str]) -> dict[str, str]:
        return self._formatter().render(vars)


@dataclass
class TerraformResourceSpec:

    resource: dict[str, Any]
    namespace: dict[str, Any]

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

    @property
    def output_resource_name(self):
        return self.resource.get("output_resource_name") or self.output_prefix

    @property
    def output_format(self) -> OutputFormat:
        if self.resource.get("output_format") is not None:
            return OutputFormat(
                **cast(dict[str, Any], self.resource.get("output_format"))
            )
        else:
            return OutputFormat(provider="generic-secret")


@dataclass(frozen=True)
class TerraformResourceIdentifier:

    identifier: str
    provider: str
    account: str

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "TerraformResourceIdentifier":
        if "identifier" not in data or "provider" not in data:
            raise ValueError(
                "dict does not include required both keys 'identifier' and 'provider'"
            )
        return TerraformResourceIdentifier(
            identifier=cast(str, data["identifier"]),
            provider=cast(str, data["provider"]),
            account=cast(str, data["account"]),
        )

    @staticmethod
    def from_output_prefix(output_prefix: str, account: str) -> "TerraformResourceIdentifier":
        identifier, provider = output_prefix.rsplit("-", 1)
        return TerraformResourceIdentifier(
            identifier=identifier,
            provider=provider,
            account=account,
        )


TerraformResourceSpecDict = dict[TerraformResourceIdentifier, TerraformResourceSpec]
