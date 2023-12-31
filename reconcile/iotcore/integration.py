import logging
import sys
from collections.abc import Callable, Iterable
from typing import Optional, Tuple

import reconcile.gql_definitions.itocore.external_resources as terraform_iot_core_resources
from reconcile.gql_definitions.common import terraform_aws_accounts
from reconcile.gql_definitions.fragments.aws_account_terraform import (
    AWSAccountTerraform,
)
from reconcile.gql_definitions.itocore.external_resources import (
    NamespaceTerraformProviderResourceAWSV1,
    NamespaceV1,
)
from reconcile.iotcore.terrascript import TMP_DIR_PREFIX, TerrascriptIotCoreClient
from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.external_resources import get_external_resource_specs
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.terraform.config import TerraformS3BackendConfig
from reconcile.utils.terraform.config_client import (
    TerraformConfigClientCollection,
)
from reconcile.utils.terraform_client import TerraformClient
from reconcile.utils.terrascript_aws_client import (
    AWSAccountCredentials,
    create_aws_terrascript,
)

QONTRACT_INTEGRATION = "terraform-iot-core"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class TerraformIOTCoreIntegrationParams(PydanticRunParams):
    enable_deletion: bool
    internal: bool
    light: bool
    use_jump_host: bool
    vault_output_path: str
    thread_pool_size: int = 10
    print_to_file: Optional[str] = None
    account_name: Optional[str] = None


class TerraformIOTCoreIntegration(
    QontractReconcileIntegration[TerraformIOTCoreIntegrationParams]
):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def run(self, dry_run: bool) -> None:
        self._run_with_defer(dry_run)

    @defer
    def _run_with_defer(self, dry_run: bool, defer: Callable) -> None:
        accounts, iotcore_namespaces = _get_desired_state(self.params.account_name)

        if not accounts:
            logging.info("No AWS accounts were detected, nothing to do.")
            sys.exit(ExitCodes.SUCCESS)

        # build terraform clients
        tf_clients = self.build_clients(accounts)

        # register IOT resources
        specs = [
            spec
            for namespace in iotcore_namespaces
            for spec in get_external_resource_specs(namespace.dict(by_alias=True))
        ]
        tf_clients.add_specs(specs)
        tf_clients.populate_resources()

        # todo oc stuff

        working_dirs = tf_clients.dump(print_to_file="/tmp/maestro.tf")
        if self.params.print_to_file:
            sys.exit(ExitCodes.SUCCESS)

        tf = TerraformClient(
            QONTRACT_INTEGRATION,
            QONTRACT_INTEGRATION_VERSION,
            "qrtfiotcore",
            [a.dict(by_alias=True) for a in accounts or []],
            working_dirs,
            self.params.thread_pool_size,
        )
        defer(tf.cleanup)

        disabled_deletions_detected, err = tf.plan(self.params.enable_deletion)
        if err:
            sys.exit(ExitCodes.ERROR)
        if disabled_deletions_detected:
            logging.error("Deletions detected but they are disabled")
            sys.exit(ExitCodes.ERROR)

        if dry_run:
            sys.exit(ExitCodes.SUCCESS)

        err = tf.apply()
        if err:
            sys.exit(ExitCodes.ERROR)

    def build_clients(
        self,
        accounts: list[AWSAccountTerraform],
    ) -> TerraformConfigClientCollection:
        clients = TerraformConfigClientCollection()
        for aws_account in accounts or []:
            creds = self.get_aws_account_creds(aws_account)
            s3_backend_config = create_backend_config(aws_account, creds)
            ts_client = create_aws_terrascript(
                provider_version=aws_account.provider_version,
                resources_default_region=aws_account.resources_default_region,
                supported_deployment_regions=aws_account.supported_deployment_regions
                or [],
                aws_account_creds=creds,
                backend_config=s3_backend_config,
            )
            clients.register_client(
                aws_account.name,
                TerrascriptIotCoreClient(
                    ts_client=ts_client,
                    tmp_dir_prefix=TMP_DIR_PREFIX,
                ),
            )
        return clients

    def get_aws_account_creds(
        self, account: AWSAccountTerraform
    ) -> AWSAccountCredentials:
        aws_acct_creds = self.secret_reader.read_all_secret(account.automation_token)
        return AWSAccountCredentials(
            aws_access_key_id=aws_acct_creds["aws_access_key_id"],
            aws_secret_access_key=aws_acct_creds["aws_secret_access_key"],
        )


def create_backend_config(
    account: AWSAccountTerraform, creds: AWSAccountCredentials
) -> TerraformS3BackendConfig:
    # default from AWS account file
    tf_state = account.terraform_state
    if tf_state is None:
        raise ValueError(
            f"AWS account {account.name} cannot be used for AWS IOT Core "
            f"because it does not define a terraform state "
        )

    for i in tf_state.integrations or []:
        integration_name = i.integration
        if integration_name == QONTRACT_INTEGRATION:
            return TerraformS3BackendConfig(
                creds.aws_access_key_id,
                creds.aws_secret_access_key,
                tf_state.bucket,
                i.key,
                tf_state.region,
            )

    raise ValueError(f"No state bucket config found for account {account.name}")


def _get_desired_state(
    account_name: Optional[str] = None,
) -> Tuple[
    list[AWSAccountTerraform],
    list[NamespaceV1],
]:
    gql_api = gql.get_api()
    accounts = terraform_aws_accounts.query(
        query_func=gql_api.query,
        variables={"filter": {"name": {"in": [account_name]}}}
        if account_name
        else None,
    ).accounts
    query_resources = terraform_iot_core_resources.query(query_func=gql_api.query)
    iotcore_namespaces = _filter_iotcore_namespaces(
        query_resources.namespaces or [], {acct.name for acct in accounts or []}
    )
    return accounts or [], iotcore_namespaces


def _filter_iotcore_namespaces(
    namespaces: Iterable[NamespaceV1], account_names: set[str]
) -> list[NamespaceV1]:
    """
    Get only the namespaces that have AWS iot-core resources and that match account_names.
    """
    supported_providers = {"iot-thing"}
    iotcore_namespaces: list[NamespaceV1] = []
    for ns in namespaces:
        iot_provisioners: list[NamespaceTerraformProviderResourceAWSV1] = []
        for provisioner in ns.external_resources or []:
            if isinstance(provisioner, NamespaceTerraformProviderResourceAWSV1):
                if provisioner.provisioner.name not in account_names:
                    continue
                provisioner.resources = [
                    resource
                    for resource in provisioner.resources
                    if resource.provider in supported_providers
                ]
                if provisioner.resources:
                    iot_provisioners.append(provisioner)
        ns.external_resources = iot_provisioners  # type: ignore
        if ns.external_resources:
            iotcore_namespaces.append(ns)
    return iotcore_namespaces
