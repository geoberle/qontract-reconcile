import base64
import json
import logging
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone

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
from reconcile.external_resources.reconciler import ExternalResourcesReconciler
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
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "external_resources"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class ExternalResourcesManager:
    def __init__(
        self,
        oc: OCCli,
        cluster: str,
        namespace: str,
        state_manager: ExternalResourcesStateDynamoDB,
        settings: ExternalResourcesSettings,
        modules: Mapping[str, ExternalResourceModule],
        impl: ExternalResourcesReconciler,
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
                dry_run=self.dry_run,
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
                dry_run=self.dry_run,
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
                self.impl.reconcile_resource(r)
                self._update_state(r, state)

    def handle_dry_run_resources(self, specs: Iterable[ExternalResourceSpec]) -> None:
        desired_r = self._get_desired_objects_reconciliations(specs)
        deleted_r = self._get_deleted_objects_reconciliations(specs)
        running_jobs = set[Reconciliation]()
        for r in desired_r.union(deleted_r):
            self.impl.reconcile_resource(r)
            running_jobs.add(r)

        reconcile_results = self.impl.wait_for_reconcile_list_completion(
            reconcile_list=running_jobs, check_interval_seconds=30, timeout=-1
        )

        failed_reconciles = []
        for reconciliation, reconcile_status in reconcile_results.items():
            self.impl.write_job_logs_to_stdout(reconciliation)
            if reconcile_status == ReconcileStatus.ERROR:
                failed_reconciles.append(str(reconciliation.key))

        if len(failed_reconciles) > 0:
            raise Exception(
                f"Resources have reconciliation errors: {failed_reconciles}"
            )

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
