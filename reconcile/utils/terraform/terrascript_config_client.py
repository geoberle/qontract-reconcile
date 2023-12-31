import tempfile
from typing import Iterable, Optional, Union

from terrascript import Data, Output, Resource, Terrascript

from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
    ExternalResourceSpecInventory,
)
from reconcile.utils.terraform.config_client import TerraformConfigClient


class TerrascriptConfigClient(TerraformConfigClient):
    """
    Build the Terrascript configuration, collect resources, and return Terraform JSON
    configuration.
    """

    def __init__(
        self,
        ts_client: Terrascript,
        tmp_dir_prefix: str,
    ) -> None:
        self._terrascript = ts_client
        self._resource_specs: ExternalResourceSpecInventory = {}
        self.tmp_dir_prefix = tmp_dir_prefix

    def add_spec(self, spec: ExternalResourceSpec) -> None:
        self._resource_specs[spec.id_object()] = spec

    def populate_resources(self) -> None:
        """
        Add the resource spec to Terrascript using the resource-specific classes
        to determine which resources to create.
        """
        raise NotImplementedError()

    def dump(self, existing_dir: Optional[str] = None) -> str:
        """Write the Terraform JSON representation of the resources to disk"""
        if existing_dir is None:
            working_dir = tempfile.mkdtemp(prefix=self.tmp_dir_prefix)
        else:
            working_dir = existing_dir
        with open(
            working_dir + "/config.tf.json", "w", encoding="locale"
        ) as terraform_config_file:
            terraform_config_file.write(self.dumps())

        return working_dir

    def dumps(self) -> str:
        """Return the Terraform JSON representation of the resources"""
        return str(self._terrascript)

    def _add_resources(
        self, tf_resources: Iterable[Union[Resource, Output, Data]]
    ) -> None:
        for resource in tf_resources:
            self._terrascript.add(resource)
