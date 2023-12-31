import json
import random
import string
import time
from typing import Union

from terrascript import (
    Output,
    Resource,
)
from terrascript.resource.aws import (
    aws_iot_certificate,
    aws_iot_policy,
    aws_iot_policy_attachment,
    aws_iot_thing,
    aws_iot_thing_principal_attachment,
)

from reconcile.utils.terraform.terrascript_config_client import TerrascriptConfigClient
from reconcile.utils.terrascript.resources import TerrascriptAWSResource

TMP_DIR_PREFIX = "terrascript-iot-core-"


class TerrascriptIotCoreClient(TerrascriptConfigClient):
    def populate_resources(self) -> None:
        """
        Add the resource spec to Terrascript using the resource-specific classes
        to determine which resources to create.
        """
        for spec in self._resource_specs.values():
            match spec.provider:
                case "iot-thing":
                    self._add_resources(IOTThingResource(spec).populate())
                case _:
                    raise ValueError(f"Unsupported resource type: {spec.provider}")


class IOTThingResource(TerrascriptAWSResource):
    def certificate_validity_period_hours(self) -> int:
        # generation keys are used to define the current and the previous certificate
        # for a thing. keeping the previous and the current certificate alive and valid
        # allows for seamless rotation of certificates
        return self._spec.resource["certificate_validity_period_hours"]

    def populate(self) -> list[Union[Resource, Output]]:
        thing = aws_iot_thing(
            self._spec.identifier, name=self._spec.identifier, provider=self.provider
        )

        resources = [thing]
        resources.extend(self._create_certificate_for_thing(0))
        resources.extend(self._create_certificate_for_thing(-1))
        return resources

    def _create_certificate_for_thing(
        self, generation_offset: int
    ) -> list[Union[Resource, Output]]:
        certificate_identifier = f"{self._spec.identifier}-{generation_key(self.certificate_validity_period_hours(), generation_offset)}"
        certificate = aws_iot_certificate(
            certificate_identifier,
            active=True,
            provider=self.provider,
        )
        principal_attachement = aws_iot_thing_principal_attachment(
            certificate_identifier,
            principal=IOTThingResource._get_arn_ref(certificate),
            thing=self._spec.identifier,
            provider=self.provider,
        )
        policy = aws_iot_policy(
            certificate_identifier,
            name=certificate_identifier,
            policy=json.dumps(self._spec.resource["policy"], sort_keys=True),
            provider=self.provider,
        )
        policy_attachement = aws_iot_policy_attachment(
            certificate_identifier,
            policy=IOTThingResource._get_field_ref(policy, "name"),
            target=IOTThingResource._get_arn_ref(certificate),
            provider=self.provider,
        )

        return [
            certificate,
            principal_attachement,
            policy,
            policy_attachement,
        ]


def generation_key(generation_lifespan_hours: int, generation_offset: int = 0) -> str:
    current_time = time.time()
    interval_seconds = generation_lifespan_hours * 60 * 60
    seed = int(
        (current_time + interval_seconds * generation_offset) // interval_seconds
    )
    rng = random.Random(seed)
    return "".join(rng.choices(string.ascii_letters + string.digits, k=5))
