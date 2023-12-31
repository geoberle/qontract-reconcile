from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import Iterable
from typing import Union

from terrascript import (
    Data,
    Output,
    Resource,
)

from reconcile.utils.external_resource_spec import ExternalResourceSpec


class TerrascriptResource(ABC):
    """
    Base class for creating Terrascript resources. New resources are added by
    subclassing this class and implementing the logic to return the required Terrascript
    resource objects.

    Note: each populate_tf_resource_<resource_name> methods in the TerrascriptAwsClient
    is a separate class using this pattern. This means that each class that implements
    TerrascriptResource can result in N resources being created if it makes sense to
    implicitly created certain resources.
    """

    def __init__(self, spec: ExternalResourceSpec) -> None:
        self._spec = spec

    @staticmethod
    def _get_dependencies(tf_resources: Iterable[Resource]) -> list[str]:
        """
        Formats the dependency name properly for use with depends_on configuration.
        """
        return [
            f"{tf_resource.__class__.__name__}.{tf_resource._name}"
            for tf_resource in tf_resources
        ]

    @abstractmethod
    def populate(self) -> list[Union[Resource, Output, Data]]:
        """Calling this method should return the Terrascript resources to be created."""


class TerrascriptAWSResource(TerrascriptResource):
    @property
    def region(self) -> str:
        region = self._spec.resource.get("region") or self._spec.provisioner.get(
            "resourcesDefaultRegion"
        )
        if region is None:
            raise ValueError(
                f"region for resource {self._spec.identifier} is required but not available"
            )
        return region

    @property
    def provider(self) -> str:
        region = self.region
        return f"aws.{region}" if region else "aws"

    @staticmethod
    def _get_arn_ref(tf_resource: Resource) -> str:
        """
        Returns the ARN of the given resource.
        """
        return TerrascriptAWSResource._get_field_ref(tf_resource, "arn")

    @staticmethod
    def _get_field_ref(tf_resource: Resource, field: str) -> str:
        """
        Returns a field ref of the given resource.
        """
        return f"${{{tf_resource.__class__.__name__}.{tf_resource._name}.{field}}}"
