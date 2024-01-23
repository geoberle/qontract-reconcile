import base64
import json
import logging
import sys
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any, Tuple

from reconcile.external_resources.model import (
    Action,
    AWSExternalResourceFactory,
    ExternalResource,
    ExternalResourceFactory,
    ExternalResourceKey,
    ExternalResourceModule,
    ExternalResourcesSettings,
    ObjectFactory,
    Reconciliation,
)
from reconcile.external_resources.state import (
    ExternalResourcesStateDynamoDB,
    ExternalResourceState,
    ReconcileStatus,
    ResourceStatus,
)
from reconcile.gql_definitions.external_resources.external_resources_namespaces import (
    NamespaceTerraformProviderResourceAWSV1,
    NamespaceTerraformResourceRoleV1,
    NamespaceV1,
)
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
)
from reconcile.utils.oc import OCCli
from reconcile.utils.openshift_resource import OpenshiftResource, ResourceInventory
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "external_resources"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class ExternalResourcesImpl(ABC):
    @abstractmethod
    def get_resource_reconcile_status(
        self,
        key: Reconciliation,
        from_inventory: bool = True,
    ) -> ReconcileStatus:
        pass

    @abstractmethod
    def reconcile_resource(
        self,
        key: Reconciliation,
        dry_run: bool,
    ) -> None:
        pass

    @abstractmethod
    def get_resource_reconcile_logs(self, key: Reconciliation) -> None:
        pass


class ExternalResourcesJobImpl(ExternalResourcesImpl):
    def __init__(
        self,
        ri: ResourceInventory,
        oc: OCCli,
        cluster: str,
        namespace: str,
        dry_run: bool = False,
    ) -> None:
        self.ri = ri
        self.cluster = cluster
        self.namespace = namespace
        self.oc = oc
        self.dry_run = dry_run

    def _get_job_name(self, reconciliation: Reconciliation) -> str:
        name = f"er-{reconciliation.digest()}"
        if self.dry_run:
            name = name + "-dry-run"

        return name

    def _build_job_spec(
        self,
        reconciliation: Reconciliation,
    ) -> dict[str, Any]:
        job = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": self._get_job_name(reconciliation),
                "annotations": {
                    "provision_provider": reconciliation.key.provision_provider,
                    "provisioner": reconciliation.key.provisioner_name,
                    "provider": reconciliation.key.provision_provider,
                    "identifier": reconciliation.key.identifier,
                },
            },
            "spec": {
                "template": {
                    "spec": {
                        "initContainers": [
                            {
                                "name": "job",
                                "image": reconciliation.image,
                                "imagePullPolicy": "Always",
                                "env": [
                                    {
                                        "name": "DRY_RUN",
                                        "value": str(self.dry_run),
                                    },
                                    {
                                        "name": "INPUT",
                                        "value": reconciliation.input,
                                    },
                                    {
                                        "name": "ACTION",
                                        "value": reconciliation.action.value,
                                    },
                                    {
                                        "name": "CDKTF_LOG_LEVEL",
                                        "value": "debug",
                                    },
                                ],
                                "volumeMounts": [
                                    {
                                        "name": "credentials",
                                        "mountPath": "/credentials",
                                        "subPath": "credentials",
                                    },
                                    {
                                        "name": "workdir",
                                        "mountPath": "/work",
                                    },
                                ],
                            }
                        ],
                        "containers": [
                            {
                                "name": "outputs",
                                "image": "quay.io/app-sre/external-resources-tests:outputs",
                                "command": ["/bin/bash", "/app/entrypoint.sh"],
                                "imagePullPolicy": "Always",
                                "env": [
                                    {
                                        "name": "NAMESPACE",
                                        "valueFrom": {
                                            "fieldRef": {
                                                "fieldPath": "metadata.namespace"
                                            }
                                        },
                                    },
                                    {
                                        "name": "INPUT",
                                        "value": reconciliation.input,
                                    },
                                    {
                                        "name": "ACTION",
                                        "value": reconciliation.action,
                                    },
                                    {
                                        "name": "DRY_RUN",
                                        "value": str(self.dry_run),
                                    },
                                ],
                                "volumeMounts": [
                                    {
                                        "name": "workdir",
                                        "mountPath": "/work",
                                    },
                                ],
                            }
                        ],
                        "imagePullSecrets": [{"name": "quay.io"}],
                        "volumes": [
                            {
                                "name": "credentials",
                                "secret": {
                                    "secretName": "credentials-"
                                    + reconciliation.key.provisioner_name
                                },
                            },
                            {"name": "workdir", "emptyDir": {"sizeLimit": "10Mi"}},
                        ],
                        "restartPolicy": "Never",
                        "serviceAccountName": "external-resources-sa",
                    }
                },
                "backoffLimit": 1,
            },
        }
        return job

    def get_resource_reconcile_status(
        self,
        reconciliation: Reconciliation,
        from_inventory: bool = True,
    ) -> ReconcileStatus:
        job_name = self._get_job_name(reconciliation)
        obj: OpenshiftResource | None = None

        if from_inventory:
            obj = self.ri.get_current(
                cluster=self.cluster,
                namespace=self.namespace,
                resource_type="Job",
                name=job_name,
            )
        else:
            _obj = self.oc.get(
                namespace=self.namespace,
                kind="Job",
                name=job_name,
                allow_not_found=True,
            )
            if _obj:
                obj = OpenshiftResource(
                    _obj, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION
                )

        if obj is None:
            return ReconcileStatus.NOT_EXISTS

        status = obj.body["status"]
        backofflimit = obj.body["spec"].get("backoffLimit", 6)
        if status.get("succeeded", 0) > 0:
            return ReconcileStatus.SUCCESS
        elif status.get("failed", 0) >= backofflimit:
            return ReconcileStatus.ERROR
        else:
            return ReconcileStatus.IN_PROGRESS

    def reconcile_resource(
        self,
        r: Reconciliation,
        dry_run: bool,
    ) -> None:
        job_name = self._get_job_name(r)
        current_job = self.ri.get_current(self.cluster, self.namespace, "Job", job_name)

        if current_job:
            logging.info(
                "Removing previous Job. Name: %s, Action: %s, Key: %s",
                job_name,
                r.action,
                r.key,
            )
            self.oc.delete(self.namespace, "Job", job_name)

        logging.info(
            "Spawning Reconciliation Job. Name: %s, Action: %s, IsDryRun: %s, Key: %s",
            job_name,
            r.action,
            dry_run,
            r.key,
        )
        job_spec = self._build_job_spec(r)
        job = OpenshiftResource(
            job_spec, "QONTRACT_INTEGRATION", "QONTRACT_INTEGRATION_VERSION"
        )
        dj = job.annotate()
        self.oc.apply(self.namespace, dj)

    def get_resource_reconcile_logs(self, reconciliation: Reconciliation) -> None:
        name = self._get_job_name(reconciliation)
        self.oc.job_logs(
            namespace=self.namespace, follow=False, name=name, output=sys.stdout
        )


class ExternalResourcesManager:
    def __init__(
        self,
        oc: OCCli,
        cluster: str,
        namespace: str,
        state_manager: ExternalResourcesStateDynamoDB,
        settings: ExternalResourcesSettings,
        modules: Mapping[str, ExternalResourceModule],
        impl: ExternalResourcesImpl,
        dry_run: bool = False,
    ) -> None:
        self.state_mgr = state_manager
        self.oc = oc
        self.cluster = cluster
        self.namespace = namespace
        self.settings = settings
        self.modules = modules
        self.impl = impl
        self.dry_run = dry_run
        self.providers = ObjectFactory[ExternalResourceFactory]()
        self.providers.register_factory("aws", AWSExternalResourceFactory(settings))

    def get_external_resources(
        self, namespaces: list[NamespaceV1]
    ) -> list[ExternalResourceSpec]:
        resources: list[ExternalResourceSpec] = []

        # PoC Filter
        for ns in namespaces:
            if ns.name != "external-resources-poc":
                continue
            if ns.external_resources:
                for erp in ns.external_resources:
                    if (
                        type(erp) is NamespaceTerraformProviderResourceAWSV1
                        and erp.resources
                    ):
                        for er in erp.resources:
                            if type(er) is NamespaceTerraformResourceRoleV1:
                                # Using this class is far from ideal as it uses
                                # generic dicts. This might need improved logic.
                                ers = ExternalResourceSpec(
                                    provision_provider=erp.provider,
                                    provisioner=erp.provisioner.dict(),
                                    resource=er.dict(),
                                    namespace=ns.dict(),
                                )
                                resources.append(ers)

                break

        return resources

    def resource_needs_reconciliation(
        self,
        r: Reconciliation,
        state: ExternalResourceState,
    ) -> bool:
        reconcile: bool = False
        if r.action == Action.APPLY:
            match state.resource_status:
                case ResourceStatus.NOT_EXISTS:
                    reconcile = True
                case ResourceStatus.ERROR:
                    reconcile = True
                case ResourceStatus.CREATED:
                    if r.resource_digest != state.resource_digest:
                        reconcile = True
                    elif (datetime.now(state.ts.tzinfo) - state.ts).days > 0:
                        reconcile = True
        elif r.action == Action.DESTROY:
            match state.resource_status:
                case ResourceStatus.CREATED:
                    reconcile = True
                case ResourceStatus.ERROR:
                    reconcile = True
        if reconcile:
            logging.info(
                "Reconciling: Status: %s, Action: %s, key:%s",
                state.resource_status.value,
                r.action.value,
                r.key,
            )
        return reconcile

    def _get_desired_objects_reconciliations(
        self, specs: Iterable[ExternalResourceSpec]
    ) -> set[Reconciliation]:
        r: set[Reconciliation] = set()
        for spec in specs:
            key = ExternalResourceKey.from_spec(spec)
            resource = self.build_external_resource(spec)
            reconciliation = Reconciliation(
                key=key,
                resource_digest=resource.digest(),
                image=self.get_provider_image(spec),
                input=self.serialize_resource_input(resource),
                action=Action.APPLY,
            )
            r.add(reconciliation)
        return r

    def _get_deleted_objects_reconciliations(
        self, specs: Iterable[ExternalResourceSpec]
    ) -> set[Reconciliation]:
        desired_keys = set([ExternalResourceKey.from_spec(spec) for spec in specs])
        state_resource_keys = set(self.state_mgr.get_all_resource_keys())
        deleted_keys = state_resource_keys - desired_keys
        r: set[Reconciliation] = set()
        for key in deleted_keys:
            state = self.state_mgr.get_external_resource_state(key)
            reconciliation = Reconciliation(
                key=key,
                resource_digest=state.resource_digest,
                image=state.reconciliation.image,
                input=state.reconciliation.input,
                action=Action.DESTROY,
            )
            r.add(reconciliation)
        return r

    def _update_in_progress_state(
        self, r: Reconciliation, state: ExternalResourceState
    ) -> None:
        if state.resource_status not in set([
            ResourceStatus.DELETE_IN_PROGRESS,
            ResourceStatus.IN_PROGRESS,
        ]):
            logging.info(
                "Reconciliation In progress. Action: %s, Key:%s",
                state.reconciliation.action,
                state.reconciliation.key,
            )
            return

        # Need to check the reconciliation set in the state, not the desired one
        # as the reconciliation object might be from a previous desired state
        match self.impl.get_resource_reconcile_status(state.reconciliation):
            case ReconcileStatus.ERROR:
                logging.info(
                    "Reconciliation ended with ERROR: Action:%s, Key:%s",
                    r.action.value,
                    r.key,
                )
                state.resource_status = ResourceStatus.ERROR
                self.state_mgr.update_resource_status(r.key, ResourceStatus.ERROR)

            case ReconcileStatus.NOT_EXISTS:
                logging.info(
                    "Reconciliation should exist but it doesn't. Marking as ERROR to retrigger: Action:%s, Key:%s",
                    r.action.value,
                    r.key,
                )
                state.resource_status = ResourceStatus.ERROR
                self.state_mgr.update_resource_status(r.key, ResourceStatus.ERROR)

            case ReconcileStatus.SUCCESS:
                logging.info(
                    "Reconciliation ended SUCCESSFULLY. Action: %s, key:%s",
                    r.action.value,
                    r.key,
                )
                if r.action == Action.APPLY:
                    state.resource_status = ResourceStatus.CREATED
                    self.state_mgr.update_resource_status(r.key, ResourceStatus.CREATED)
                elif r.action == Action.DESTROY:
                    state.resource_status = ResourceStatus.DELETED
                    self.state_mgr.del_external_resource_state(r.key)

    def _update_state(self, r: Reconciliation, state: ExternalResourceState) -> None:
        state.ts = datetime.now(timezone.utc)
        if r.action == Action.APPLY:
            state.resource_status = ResourceStatus.IN_PROGRESS
        elif r.action == Action.DESTROY:
            state.resource_status = ResourceStatus.DELETE_IN_PROGRESS
        state.resource_digest = r.resource_digest
        state.reconciliation = r
        self.state_mgr.set_external_resource_state(state)

    def handle_resources(self, specs: Iterable[ExternalResourceSpec]) -> None:
        desired_r = self._get_desired_objects_reconciliations(specs)
        deleted_r = self._get_deleted_objects_reconciliations(specs)
        for r in desired_r.union(deleted_r):
            state = self.state_mgr.get_external_resource_state(r.key)
            self._update_in_progress_state(r, state)
            if self.resource_needs_reconciliation(r, state):
                self.impl.reconcile_resource(r, self.dry_run)
                self._update_state(r, state)

    def _wait_for_running_jobs(
        self,
        jobs: Iterable[Reconciliation],
        wait_before_start: bool = True,
    ) -> Tuple[set[Reconciliation], set[Reconciliation]]:
        running_jobs = set(jobs)
        success_jobs: set[Reconciliation] = set()
        error_jobs: set[Reconciliation] = set()

        if wait_before_start and len(running_jobs) > 0:
            logging.info("Waiting for jobs population")
            time.sleep(5)

            while running_jobs:
                logging.info(running_jobs)
                for reconciliation in list(running_jobs):
                    status = self.impl.get_resource_reconcile_status(
                        reconciliation, from_inventory=False
                    )
                    logging.info(status)
                    match status:
                        case ReconcileStatus.SUCCESS:
                            success_jobs.add(reconciliation)
                            running_jobs.remove(reconciliation)
                        case ReconcileStatus.ERROR:
                            error_jobs.add(reconciliation)
                            running_jobs.remove(reconciliation)
                if running_jobs:
                    logging.info("Waiting for jobs to complete.")
                    time.sleep(30)
        return (success_jobs, error_jobs)

    def handle_dry_run_resources(self, specs: Iterable[ExternalResourceSpec]) -> None:
        desired_r = self._get_desired_objects_reconciliations(specs)
        deleted_r = self._get_deleted_objects_reconciliations(specs)
        running_jobs = set[Reconciliation]()
        for r in desired_r.union(deleted_r):
            self.impl.reconcile_resource(
                r,
                self.dry_run,
            )
            running_jobs.add(r)

        success_jobs, error_jobs = self._wait_for_running_jobs(running_jobs)

        for reconciliation in success_jobs.union(error_jobs):
            self.impl.get_resource_reconcile_logs(reconciliation)

        if len(error_jobs) > 0:
            raise Exception("Some Resources have reconciliation errors.")

    def get_provider_image(self, ers: ExternalResourceSpec) -> str:
        key = f"{ers.provision_provider}-{ers.provider}"
        module = self.modules.get(key)
        if not module:
            raise ValueError(key)
        # TODO:Logic to override the image:version
        return f"{module.image}:{module.default_version}"

    def build_external_resource(self, ers: ExternalResourceSpec) -> ExternalResource:
        resource = self.providers.get_factory(
            ers.provision_provider
        ).create_external_resource(ers)
        return resource

    def serialize_resource_input(self, resource: ExternalResource) -> str:
        return base64.b64encode(json.dumps(resource.dict()).encode()).decode()
