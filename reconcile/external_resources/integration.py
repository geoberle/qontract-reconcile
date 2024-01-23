from reconcile.external_resources.manager import (
    ExternalResourcesJobImpl,
    ExternalResourcesManager,
)
from reconcile.external_resources.model import (
    ExternalResourceModule,
    ExternalResourcesSettings,
)
from reconcile.external_resources.state import (
    ExternalResourcesStateDynamoDB,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.clusters_minimal import get_clusters_minimal

# from reconcile.typed_queries.terraform_namespaces import get_namespaces
from reconcile.typed_queries.external_resources_namespaces import get_namespaces
from reconcile.utils.oc import (
    OCCli,
)
from reconcile.utils.oc_map import init_oc_map_from_clusters
from reconcile.utils.openshift_resource import OpenshiftResource, ResourceInventory
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "external_resources"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def fetch_current_state(
    ri: ResourceInventory, oc: OCCli, cluster: str, namespace: str
) -> None:
    for item in oc.get_items("Job", namespace=namespace):
        r = OpenshiftResource(item, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION)
        ri.add_current(cluster, namespace, "Job", r.name, r)


def run(dry_run: bool, cluster: str, namespace: str) -> None:
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    clusters = get_clusters_minimal(name=cluster)
    oc_map = init_oc_map_from_clusters(
        clusters=clusters,
        secret_reader=secret_reader,
        integration=QONTRACT_INTEGRATION,
        thread_pool_size=1,
        init_api_resources=False,
    )

    oc = oc_map.get_cluster(cluster=cluster)
    ri = ResourceInventory()
    # The inventory is only used in normal runs
    ri.initialize_resource_type(
        cluster=cluster, namespace=namespace, resource_type="Job"
    )
    fetch_current_state(ri, oc, cluster, namespace)

    impl = ExternalResourcesJobImpl(
        ri=ri, oc=oc, cluster=cluster, namespace=namespace, dry_run=dry_run
    )

    # state = init_state(
    #     integration=QONTRACT_INTEGRATION,
    #     secret_reader=secret_reader,
    #     encoder=EnhancedJsonEncoder,
    # )
    # state_mgr = ExternalResourcesStateManager(
    #     state=state, index_file_key="external_resources_index.json"
    # )
    state_mgr = ExternalResourcesStateDynamoDB()
    # this will come from app-interface settings
    settings = ExternalResourcesSettings(
        tf_state_bucket="test-external-resources-state",
        tf_state_dynamodb_table="test-external-resources-lock",
        tf_state_region="us-east-1",
    )

    modules = {
        "aws-aws-iam-role": ExternalResourceModule(
            provision_provider="aws",
            provider="aws-iam-role",
            image="quay.io/app-sre/external-resources-tests",
            default_version="0.0.1",
        )
    }

    er_mgr = ExternalResourcesManager(
        oc=oc,
        cluster=cluster,
        namespace=namespace,
        state_manager=state_mgr,
        settings=settings,
        modules=modules,
        impl=impl,
        dry_run=dry_run,
    )
    namespaces = [ns for ns in get_namespaces() if ns.external_resources]
    external_resources = er_mgr.get_external_resources(namespaces)
    # Handle new and Modified Resources
    # Those are in the external_resources list
    # er_mgr.handle_desired_resources(specs=external_resources)
    # er_mgr.handle_desired_resources_dry_run(specs=external_resources)
    if dry_run:
        er_mgr.handle_dry_run_resources(specs=external_resources)
    else:
        er_mgr.handle_resources(specs=external_resources)
        # er_mgr.handle_desired_resources(specs=external_resources)
        # er_mgr.handle_deleted_resources(specs=external_resources)

    # Handle deleted resources
    # Those are in the state, but not in the external_resources
    # er_mgr.handle_deleted_resources(specs=external_resources)

    # er_mgr.reconcile(external_resources, ri)
    # if not dry_run:
    #     state_mgr.save_state()
