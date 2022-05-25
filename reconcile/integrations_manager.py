from dataclasses import dataclass
import os
import sys
import json
import logging

from github import Github
from typing import Any, Iterable, Mapping, Optional

import reconcile.openshift_base as ob

from reconcile.utils import helm
from reconcile import queries
from reconcile.status import ExitCodes
from reconcile.utils.oc import oc_process
from reconcile.utils.runtime.meta import IntegrationMeta
from reconcile.utils.semver_helper import make_semver
from reconcile.github_org import GH_BASE_URL, get_default_config
from reconcile.utils.openshift_resource import OpenshiftResource, ResourceInventory
from reconcile.utils.defer import defer


QONTRACT_INTEGRATION = "integrations-manager"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


@dataclass
class IntegrationShardManager:

    aws_accounts: list[dict[str, Any]]
    integration_runtime_meta: dict[str, IntegrationMeta]

    def build_integration_shards(
        self, integration: str, spec: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        extra_args = spec["extraArgs"] or ""
        sharding_strategy = spec.get("shardingStrategy") or "static"
        if sharding_strategy == "per-aws-account":
            if self._integration_supports_arg(integration, "--account-name"):
                filtered_accounts = self._aws_accounts_for_integration(integration)
                return [
                    {
                        "shard_id": shard_id,
                        "shards": len(filtered_accounts),
                        "shard_name_suffix": f"-{account['name']}"
                        if len(filtered_accounts) > 1
                        else "",
                        "extra_args": " ".join(
                            a
                            for a in [extra_args, "--account-name", account["name"]]
                            if a
                        ),
                    }
                    for shard_id, account in enumerate(filtered_accounts)
                ]
            else:
                raise ValueError(
                    f"integration {integration} does not support arg --account-name required by the per-aws-account sharding strategy"
                )
        elif sharding_strategy == "static":
            shards = spec.get("shards") or 1
            return [
                {
                    "shard_id": s,
                    "shards": shards,
                    "shard_name_suffix": f"-{s}" if shards > 1 else "",
                    "extra_args": extra_args,
                }
                for s in range(0, shards)
            ]
        else:
            raise ValueError(f"unsupported sharding strategy {sharding_strategy}")

    def _aws_accounts_for_integration(self, integration: str) -> list[dict[str, Any]]:
        return [
            a
            for a in self.aws_accounts
            if a["disable"] is None
            or "integrations" not in a["disable"]
            or integration not in (a["disable"]["integrations"] or [])
        ]

    def _integration_supports_arg(self, integration, arg):
        return arg in self.integration_runtime_meta[integration].args


def construct_values_file(
    integration_specs: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "integrations": [],
        "cronjobs": [],
    }
    for spec in integration_specs:
        key = "cronjobs" if spec.get("cron") else "integrations"
        values[key].append(spec)
    return values


def get_image_tag_from_ref(ref: str) -> str:
    settings = queries.get_app_interface_settings()
    gh_token = get_default_config()["token"]
    github = Github(gh_token, base_url=GH_BASE_URL)
    commit_sha = github.get_repo("app-sre/qontract-reconcile").get_commit(sha=ref).sha
    return commit_sha[: settings["hashLength"]]


def collect_parameters(
    template: Mapping[str, Any],
    environment: Mapping[str, Any],
    image_tag_from_ref: Optional[Mapping[str, str]],
) -> dict[str, Any]:
    parameters: dict[str, Any] = {}
    environment_parameters = environment.get("parameters")
    if environment_parameters:
        parameters.update(json.loads(environment_parameters))
    template_parameters = template.get("parameters")
    if template_parameters:
        tp_env_vars = {
            p["name"]: os.environ[p["name"]]
            for p in template_parameters
            if p["name"] in os.environ
        }
        parameters.update(tp_env_vars)
    if image_tag_from_ref:
        for e, r in image_tag_from_ref.items():
            if environment["name"] == e:
                parameters["IMAGE_TAG"] = get_image_tag_from_ref(r)

    return parameters


def construct_oc_resources(
    namespace_info: Mapping[str, Any],
    image_tag_from_ref: Optional[Mapping[str, str]],
) -> list[OpenshiftResource]:
    template = helm.template(construct_values_file(namespace_info["integration_specs"]))

    parameters = collect_parameters(
        template, namespace_info["environment"], image_tag_from_ref
    )
    resources = oc_process(template, parameters)
    return [
        OpenshiftResource(
            r,
            QONTRACT_INTEGRATION,
            QONTRACT_INTEGRATION_VERSION,
            error_details=r.get("metadata", {}).get("name"),
        )
        for r in resources
    ]


def initialize_shard_specs(
    namespaces: Iterable[Mapping[str, Any]], shard_manager: IntegrationShardManager
) -> None:
    for namespace_info in namespaces:
        for spec in namespace_info["integration_specs"]:
            spec["shard_specs"] = shard_manager.build_integration_shards(
                spec["name"], spec
            )


def fetch_desired_state(
    namespaces: Iterable[Mapping[str, Any]],
    ri: ResourceInventory,
    image_tag_from_ref: Optional[Mapping[str, str]],
) -> None:
    for namespace_info in namespaces:
        namespace = namespace_info["name"]
        cluster = namespace_info["cluster"]["name"]
        oc_resources = construct_oc_resources(namespace_info, image_tag_from_ref)
        for r in oc_resources:
            ri.add_desired(cluster, namespace, r.kind, r.name, r)


def collect_namespaces(
    integrations: Iterable[Mapping[str, Any]], environment_name: str
) -> list[dict[str, Any]]:
    unique_namespaces: dict[str, dict[str, Any]] = {}
    for i in integrations:
        managed = i.get("managed") or []
        for m in managed:
            ns = m["namespace"]
            if environment_name and ns["environment"]["name"] != environment_name:
                continue
            ns = unique_namespaces.setdefault(ns["path"], ns)
            spec = m["spec"]
            spec["name"] = i["name"]
            # create a backref from namespace to integration spec
            ns.setdefault("integration_specs", []).append(spec)

    return list(unique_namespaces.values())


@defer
def run(
    dry_run,
    environment_name,
    integration_runtime_meta: dict[str, IntegrationMeta],
    thread_pool_size=10,
    internal=None,
    use_jump_host=True,
    image_tag_from_ref=None,
    defer=None,
):
    namespaces = collect_namespaces(
        queries.get_integrations(managed=True), environment_name
    )
    if not namespaces:
        logging.debug("Nothing to do, exiting.")
        sys.exit(ExitCodes.SUCCESS)

    ri, oc_map = ob.fetch_current_state(
        namespaces=namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        override_managed_types=["Deployment", "StatefulSet", "CronJob", "Service"],
        internal=internal,
        use_jump_host=use_jump_host,
    )
    defer(oc_map.cleanup)
    shard_manager = IntegrationShardManager(
        aws_accounts=queries.get_aws_accounts(),
        integration_runtime_meta=integration_runtime_meta,
    )
    initialize_shard_specs(namespaces, shard_manager)
    fetch_desired_state(namespaces, ri, image_tag_from_ref)
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)

    if ri.has_error_registered():
        sys.exit(ExitCodes.ERROR)
