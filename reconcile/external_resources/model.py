import base64
import hashlib
import json
from abc import (
    ABC,
    abstractmethod,
)
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
)
from reconcile.utils.external_resources import ResourceValueResolver


class ExternalResourceKey(BaseModel, frozen=True):
    provision_provider: str
    provisioner_name: str
    provider: str
    identifier: str

    @staticmethod
    def from_spec(spec: ExternalResourceSpec) -> "ExternalResourceKey":
        return ExternalResourceKey(
            provision_provider=spec.provision_provider,
            provisioner_name=spec.provisioner_name,
            identifier=spec.identifier,
            provider=spec.provider,
        )

    def digest(self) -> str:
        digest = hashlib.md5(
            json.dumps(self.dict(), sort_keys=True).encode("utf-8")
        ).hexdigest()
        return digest

    @property
    def state_path(self) -> str:
        return f"{self.provision_provider}/{self.provisioner_name}/{self.provider}/{self.identifier}"

    def __str__(self) -> str:
        return f"{self.provision_provider}/{self.provisioner_name}/{self.provider}/{self.identifier}"


class Action(str, Enum):
    DESTROY: str = "Destroy"
    APPLY: str = "Apply"


class Reconciliation(BaseModel, frozen=True):
    key: ExternalResourceKey
    resource_digest: str = ""
    image: str = ""
    input: str = ""
    action: Action = Action.APPLY
    dry_run: bool = False


T = TypeVar("T")


class ObjectFactory(Generic[T]):
    def __init__(self) -> None:
        self._providers: dict[str, T] = {}

    def register_factory(self, id: str, t: T) -> None:
        self._providers[id] = t

    def get_factory(self, id: str) -> T:
        provider = self._providers.get(id)
        if not provider:
            raise ValueError(id)
        return provider


class ExternalResourceModule(BaseModel):
    image: str
    default_version: str
    provision_provider: str
    provider: str


class ExternalResourcesSettings(BaseModel):
    """Class with Settings for all the supported external resources provisioners"""

    # Terraform / CDKTF
    tf_state_bucket: str
    tf_state_region: str
    tf_state_dynamodb_table: str
    # Others ...


class ModuleProvisionData(ABC, BaseModel):
    pass


class TerraformModuleProvisionData(ModuleProvisionData):
    """Specific Provision Options for modules based on Terraform or CDKTF"""

    tf_state_bucket: str
    tf_state_region: str
    tf_state_dynamodb_table: str
    tf_state_key: str


class ModuleProvisionDataFactory(ABC):
    @abstractmethod
    def create_provision_data(self, ers: ExternalResourceSpec) -> ModuleProvisionData:
        pass


class TerraformModuleProvisionDataFactory(ModuleProvisionDataFactory):
    def __init__(self, settings: ExternalResourcesSettings):
        self.settings = settings

    def create_provision_data(
        self, spec: ExternalResourceSpec
    ) -> TerraformModuleProvisionData:
        key = ExternalResourceKey.from_spec(spec)

        return TerraformModuleProvisionData(
            tf_state_bucket=self.settings.tf_state_bucket,
            tf_state_region=self.settings.tf_state_region,
            tf_state_dynamodb_table=self.settings.tf_state_dynamodb_table,
            tf_state_key=key.state_path + "/terraform.tfstate",
        )


class ExternalResourceProvision(BaseModel):
    """External resource app-interface attributes. They are not part of the resource but are needed
    for annotating secrets or other stuff"""

    provision_provider: str  # aws
    provisioner: str  # ter-int-dev
    provider: str  # aws-iam-role
    identifier: str
    target_cluster: str
    target_namespace: str
    target_secret_name: str
    module_provision_data: ModuleProvisionData


class ExternalResource(BaseModel):
    data: dict[str, Any]
    provision: ExternalResourceProvision

    def digest(self) -> str:
        digest = hashlib.md5(
            json.dumps(self.data, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return digest

    def serialize_input(self) -> str:
        return base64.b64encode(json.dumps(self.dict()).encode()).decode()


class ExternalResourceFactory(ABC):
    @abstractmethod
    def create_external_resource(self, ers: ExternalResourceSpec) -> ExternalResource:
        pass


class AWSExternalResourceFactory(ExternalResourceFactory):
    # TODO: This class need the modules configuration
    def __init__(
        self,
        settings: ExternalResourcesSettings,
    ):
        tf_factory = TerraformModuleProvisionDataFactory(settings=settings)
        provision_options_factories = ObjectFactory[ModuleProvisionDataFactory]()
        provision_options_factories.register_factory("terraform", tf_factory)
        provision_options_factories.register_factory("cdktf", tf_factory)
        self.provision_options_factories = provision_options_factories

    def create_external_resource(self, ers: ExternalResourceSpec) -> ExternalResource:
        rvr = ResourceValueResolver(spec=ers, identifier_as_value=True)
        data: dict[str, Any] = rvr.resolve()

        region = data.get("region")
        if region:
            if region not in ers.provisioner["supported_deployment_regions"]:
                raise ValueError(region)
        else:
            region = ers.provisioner["resources_default_region"]
        data["region"] = region

        module = "cdktf"
        options_factory = self.provision_options_factories.get_factory(module)
        module_provision_data = options_factory.create_provision_data(ers)

        provision = ExternalResourceProvision(
            provision_provider=ers.provision_provider,
            provisioner=ers.provisioner_name,
            provider=ers.provider,
            identifier=ers.identifier,
            target_cluster=ers.cluster_name,
            target_namespace=ers.namespace_name,
            target_secret_name=ers.output_resource_name,
            module_provision_data=module_provision_data,
        )

        return ExternalResource(data=data, provision=provision)
