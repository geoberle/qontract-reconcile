from typing import Optional, Set
from pydantic import BaseModel, Extra, Field

from pydantic.dataclasses import dataclass


class ShardingSpec(BaseModel, extra=Extra.ignore):

    shards: Optional[int]
    sharding_strategy: Optional[str] = Field(default=None, alias="shardingStrategy")


@dataclass
class ResourceRequirements:

    cpu: str
    memory: str


@dataclass
class Resources:

    requests: Optional[ResourceRequirements]
    limits: Optional[ResourceRequirements]


@dataclass
class IntegrationSpec:

    name: str
    description: str
    schemas: Set[str]

    @dataclass
    class PRCheck:

        cmd: str
        state: Optional[bool]
        sqs: Optional[bool]
        disabled: Optional[bool]
        always_run: Optional[bool]
        no_validate_schemas: Optional[bool]
        run_for_valid_saas_file_changes: Optional[bool]
        sharding: Optional[ShardingSpec]
        resources: Optional[ResourceRequirements]

    pr_check: Optional[PRCheck]
