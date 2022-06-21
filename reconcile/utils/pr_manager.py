from typing import Any, Optional

from pydantic import BaseModel

from reconcile import queries
from reconcile.utils import gql
from reconcile.utils.integration_spec import IntegrationSpec
from reconcile.utils.runtime.meta import IntegrationMeta
from reconcile.utils.sharding import (
    AWSAccountShardManager,
    IntegrationShardManager,
    StaticShardingStrategy,
)


class Diff(BaseModel):

    resourcepath: Optional[str]
    datafilepath: str
    datafileschema: str
    action: str
    jsonpath: str
    old: dict[str, Any]
    new: dict[str, Any]


class IntegrationPRSpec:
    def __init__(self, spec: IntegrationSpec, integration_meta: IntegrationMeta):
        self.spec = spec
        if integration_meta:
            self.integration_meta = integration_meta
        else:
            # workaround until we can get metadata for non cli.py based integrations
            self.integration_meta = IntegrationMeta(
                name=self.spec.name, args=[], short_help=None
            )

    def should_run_on_change(self, change: Diff) -> bool:
        # todo - look deeper if the change is relevant
        return change.datafileschema in self.spec.schemas

    def should_integration_run(self, changes: list[Diff], valid_saas_file_changes_only: bool) -> bool:
        if self.disabled():
            return False
        if self.should_always_run():
            return True
        if valid_saas_file_changes_only and not self.run_during_saas_file_changes():
            return False
        for c in changes:
            if self.should_run_on_change(c):
                return True
        return False

    def should_always_run(self) -> bool:
        if self.spec.pr_check:
            return self.spec.pr_check.always_run or False
        else:
            return False

    def disabled(self) -> bool:
        if self.spec.pr_check:
            return self.spec.pr_check.disabled or False
        else:
            return False

    def run_during_saas_file_changes(self) -> bool:
        if self.spec.pr_check:
            if self.spec.pr_check.run_for_valid_saas_file_changes is None:
                return True
            else:
                return self.spec.pr_check.run_for_valid_saas_file_changes
        else:
            return True

    def _memory_limit(self) -> Optional[str]:
        if self.spec.pr_check and self.spec.pr_check.resources and self.spec.pr_check.resources.limits:
            memory = self.spec.pr_check.resources.limits.memory
            return memory.replace("Mi", "m").replace("Gi", "g")
        else:
            return None

    def _build_base_run_cmd(self) -> Optional[str]:
        if self.spec.pr_check:
            cmd = []
            # ENV
            if self.spec.pr_check.state:
                cmd.append("STATE=true")
            if self.spec.pr_check.sqs:
                cmd.append("SQS_GATEWAY=true")
            if self.spec.pr_check.no_validate_schemas:
                cmd.append("NO_VALIDATE=true")
            if self._memory_limit():
                cmd.append(f"MEMORY_LIMIT={self._memory_limit()}")

            # main cmd
            # todo - get rid of special handling for non q-r integrations
            if self.spec.name == "vault-manager":
                cmd.append("run_vault_reconcile_integration")
            elif self.spec.name == "user-validator":
                cmd.append("run_user_validator")
            else:
                cmd.append(f"run_int {self.spec.pr_check.cmd}")

            return " ".join(cmd)
        else:
            return None

    def build_integration_cmds(self, shard_manager: IntegrationShardManager) -> list[str]:
        base_cmd = self._build_base_run_cmd()
        if base_cmd:
            # apply sharding
            if self.spec.pr_check.sharding:
                shards = shard_manager.build_integration_shards(
                    self.integration_meta,
                    self.spec.pr_check.sharding
                )
                return [
                    f"ALIAS={self.integration_meta.name}{s.shard_name_suffix} {base_cmd} {s.sharding_args}"
                    for s in shards
                ]
            else:
                return [base_cmd]
        else:
            return None


QUERY = """
{
  integrations: integrations_v1 {
    name
    description
    schemas
    pr_check {
      resources {
        limits {
          cpu
          memory
        }
      }
      sharding {
        shards
        shardingStrategy
      }
      cmd
      state
      sqs
      disabled
      always_run
      no_validate_schemas
      run_for_valid_saas_file_changes
    }
  }
}
"""


def get_integrations(integration_runtime_meta: dict[str, IntegrationMeta]):
    gqlapi = gql.get_api()
    return [
        IntegrationPRSpec(
            spec=IntegrationSpec(**i),
            integration_meta=integration_runtime_meta.get(i["name"])
        )
        for i in gqlapi.query(QUERY)["integrations"]
    ]


def select_integrations(
    base_bundle_sha: str,
    bundle_sha: str,
    valid_saas_file_changes_only: bool,
    integration_runtime_meta: dict[str, IntegrationMeta],
):
    shard_manager = IntegrationShardManager(
        strategies={
            "per-aws-account": AWSAccountShardManager(queries.get_aws_accounts()),
        }
    )

    resource_diffs = [Diff(**d) for d in gql.get_diff(base_bundle_sha, bundle_sha)]
    integration_run_commands = []
    for integration in get_integrations(integration_runtime_meta):
        run = integration.should_integration_run(resource_diffs, valid_saas_file_changes_only)
        if run:
            cmds = integration.build_integration_cmds(shard_manager)
            if cmds:
                integration_run_commands.extend(cmds)
    return integration_run_commands
