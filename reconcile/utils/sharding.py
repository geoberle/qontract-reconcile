from abc import ABC, abstractmethod
from pydantic.dataclasses import dataclass
import hashlib
import logging
import os
from typing import Any, Optional

from reconcile.utils.integration_spec import ShardingSpec
from reconcile.utils.runtime.meta import IntegrationMeta


LOG = logging.getLogger(__name__)

SHARDS = int(os.environ.get("SHARDS", 1))
SHARD_ID = int(os.environ.get("SHARD_ID", 0))


def is_in_shard(value):
    if SHARDS == 1:
        return True

    h = hashlib.new("md5", usedforsecurity=False)
    h.update(value.encode())
    value_hex = h.hexdigest()
    value_int = int(value_hex, base=16)

    in_shard = value_int % SHARDS == SHARD_ID

    if in_shard:
        LOG.debug("IN_SHARD TRUE: %s", value)
    else:
        LOG.debug("IN_SHARD FALSE: %s", value)

    return in_shard


def is_in_shard_round_robin(value, index):
    if SHARDS == 1:
        return True

    in_shard = index % SHARDS == SHARD_ID

    if in_shard:
        LOG.debug("IN_SHARD TRUE: %s", value)
    else:
        LOG.debug("IN_SHARD FALSE: %s", value)

    return in_shard


@dataclass
class Shard:

    shard_id: Optional[int]
    shards: Optional[int]
    shard_key: Optional[str]
    shard_name_suffix: str
    sharding_args: Optional[str]


class ShardingStrategy(ABC):
    @abstractmethod
    def build_integration_shards(
        self, integration_meta: IntegrationMeta, sharding_spec: ShardingSpec
    ) -> list[Shard]:
        pass


class IntegrationShardManager:
    def __init__(self, strategies: dict[str, ShardingStrategy]):
        self.strategies = strategies

    def build_integration_shards(
        self, integration_meta: IntegrationMeta, sharding_spec: ShardingSpec
    ) -> list[Shard]:
        sharding_strategy = sharding_spec.sharding_strategy or "static"
        if sharding_strategy in self.strategies:
            return self.strategies[sharding_strategy].build_integration_shards(
                integration_meta, sharding_spec
            )
        else:
            raise ValueError(f"unsupported sharding strategy '{sharding_strategy}'")


class StaticShardingStrategy(ShardingStrategy):
    def build_integration_shards(
        self, _: IntegrationMeta, sharding_spec: ShardingSpec
    ) -> list[Shard]:
        shards = sharding_spec.shards or 1
        return [
            Shard(
                shard_id=s,
                shards=shards,
                shard_key=None,
                shard_name_suffix=f"-{s}" if shards > 1 else "",
                sharding_args=None,
            )
            for s in range(0, shards)
        ]


class AWSAccountShardManager(ShardingStrategy):
    def __init__(self, aws_accounts: list[dict[str, Any]]):
        self.aws_accounts = aws_accounts

    def build_integration_shards(
        self, integration_meta: IntegrationMeta, _: ShardingSpec
    ) -> list[Shard]:
        if "--account-name" in integration_meta.args:
            filtered_accounts = self._aws_accounts_for_integration(
                integration_meta.name
            )
            return [
                Shard(
                    shard_id=None,
                    shards=None,
                    shard_key=account["name"],
                    shard_name_suffix=f"-{account['name']}"
                    if len(filtered_accounts) > 1
                    else "",
                    sharding_args=f"--account-name {account['name']}",
                )
                for account in filtered_accounts
            ]
        else:
            raise ValueError(
                f"integration {integration_meta.name} does not support arg --account-name required by the per-aws-account sharding strategy"
            )

    def _aws_accounts_for_integration(
        self, integration: str, filter_disabled: bool = True
    ) -> list[dict[str, Any]]:
        return [
            a
            for a in self.aws_accounts
            if not filter_disabled
            or a["disable"] is None
            or "integrations" not in a["disable"]
            or integration not in (a["disable"]["integrations"] or [])
        ]
