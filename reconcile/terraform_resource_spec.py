from abc import abstractmethod
from dataclasses import dataclass, field
import json
from typing import Any, Optional, cast
import yaml
import copy
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
            # the jinja2 rendering has the capabilitiy to change the passed
            # vars dict - make a copy to protect against it
            rendered_data = orb.process_jinja2_template(self.data, dict(vars))
            return yaml.safe_load(rendered_data)
        else:
            return dict(vars)


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
    secret: Optional[dict[str, str]] = field(init=False)

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
    def annotations(self) -> dict[str, str]:
        annotation_str = self.resource.get("annotations")
        if annotation_str:
            return json.loads(annotation_str)
        else:
            return {}

    def get_secret_field(self, field: str) -> Any:
        if self.secret:
            return self.secret.get(field, None)
        else:
            return None

    def _output_format(self) -> OutputFormat:
        if self.resource.get("output_format") is not None:
            return OutputFormat(
                **cast(dict[str, Any], self.resource.get("output_format"))
            )
        else:
            return OutputFormat(provider="generic-secret")

    def render_output_secret(self) -> dict[str, str]:
        if self.secret:
            return self._output_format().render(self.secret)
        else:
            raise ValueError(f"resourcespec {self.output_prefix} does not have output data attached to be rendered")


@dataclass(frozen=True)
class TerraformResourceIdentifier:

    identifier: str
    provider: str
    account: str

    @property
    def output_prefix(self) -> str:
        return f"{self.identifier}-{self.provider}"

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
    def from_output_prefix(
        output_prefix: str, account: str
    ) -> "TerraformResourceIdentifier":
        identifier, provider = output_prefix.rsplit("-", 1)
        return TerraformResourceIdentifier(
            identifier=identifier,
            provider=provider,
            account=account,
        )


TerraformResourceSpecDict = dict[TerraformResourceIdentifier, TerraformResourceSpec]
