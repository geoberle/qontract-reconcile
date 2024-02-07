import sys
from abc import ABC, abstractmethod
from typing import Any, Iterable

from kubernetes.client import (
    V1Container,
    V1EmptyDirVolumeSource,
    V1EnvVar,
    V1EnvVarSource,
    V1JobSpec,
    V1LocalObjectReference,
    V1ObjectFieldSelector,
    V1ObjectMeta,
    V1PodSpec,
    V1PodTemplateSpec,
    V1SecretVolumeSource,
    V1Volume,
    V1VolumeMount,
)
from pydantic import BaseModel

from reconcile.external_resources.model import Reconciliation
from reconcile.external_resources.state import ReconcileStatus
from reconcile.utils.jobcontroller.controller import K8sJobController
from reconcile.utils.jobcontroller.models import JobConcurrencyPolicy, K8sJob


class ExternalResourcesReconciler(ABC):
    @abstractmethod
    def get_resource_reconcile_status(self, key: Reconciliation) -> ReconcileStatus: ...

    @abstractmethod
    def reconcile_resource(
        self,
        key: Reconciliation,
    ) -> bool: ...

    @abstractmethod
    def wait_for_reconcile_list_completion(
        self,
        reconcile_list: Iterable[Reconciliation],
        check_interval_seconds: int,
        timeout_seconds: int,
    ) -> dict[Reconciliation, ReconcileStatus]: ...

    @abstractmethod
    def write_job_logs_to_stdout(self, key: Reconciliation) -> None: ...


class ReconciliationK8sJob(K8sJob, BaseModel):
    """
    Wraps a reconciliation request into a Kubernetes Job
    """

    reconciliation: Reconciliation

    def description(self) -> str:
        return f"Action: {self.reconciliation.action}, Key: {self.reconciliation.key} "

    def name(self) -> str:
        n = f"er-{self.job_identity_digest()}"
        if self.reconciliation.dry_run:
            n += "-dry-run"
        return n

    def job_identity_data(self) -> Any:
        return {
            "rec": self.reconciliation,
            "dry_run": self.reconciliation.dry_run,
        }

    def annotations(self) -> dict[str, Any]:
        return {
            "er.provision_provider": self.reconciliation.key.provision_provider,
            "er.provisioner": self.reconciliation.key.provisioner_name,
            "er.provider": self.reconciliation.key.provision_provider,
            "er.identifier": self.reconciliation.key.identifier,
            "er.dry_run": str(self.reconciliation.dry_run),
        }

    def job_spec(self) -> V1JobSpec:
        return V1JobSpec(
            backoff_limit=1,
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(
                    annotations=self.annotations(), labels=self.labels()
                ),
                spec=V1PodSpec(
                    init_containers=[
                        V1Container(
                            name="job",
                            image=self.reconciliation.image,
                            image_pull_policy="Always",
                            env=[
                                V1EnvVar(
                                    name="DRY_RUN",
                                    value=str(self.reconciliation.dry_run),
                                ),
                                V1EnvVar(
                                    name="INPUT",
                                    value=self.reconciliation.input,
                                ),
                                V1EnvVar(
                                    name="ACTION",
                                    value=self.reconciliation.action.value,
                                ),
                                V1EnvVar(
                                    name="CDKTF_LOG_LEVEL",
                                    value="debug",
                                ),
                            ],
                            volume_mounts=[
                                V1VolumeMount(
                                    name="credentials",
                                    mount_path="/credentials",
                                    sub_path="credentials",
                                ),
                                V1VolumeMount(
                                    name="workdir",
                                    mount_path="/work",
                                ),
                            ],
                        )
                    ],
                    containers=[
                        V1Container(
                            name="outputs",
                            image="quay.io/app-sre/external-resources-tests:outputs",
                            command=["/bin/bash", "/app/entrypoint.sh"],
                            image_pull_policy="Always",
                            env=[
                                V1EnvVar(
                                    name="NAMESPACE",
                                    value_from=V1EnvVarSource(
                                        field_ref=V1ObjectFieldSelector(
                                            field_path="metadata.namespace"
                                        )
                                    ),
                                ),
                                V1EnvVar(
                                    name="INPUT",
                                    value=self.reconciliation.input,
                                ),
                                V1EnvVar(
                                    name="ACTION",
                                    value=self.reconciliation.action,
                                ),
                                V1EnvVar(
                                    name="DRY_RUN",
                                    value=str(self.reconciliation.dry_run),
                                ),
                            ],
                            volume_mounts=[
                                V1VolumeMount(
                                    name="workdir",
                                    mount_path="/work",
                                ),
                            ],
                        )
                    ],
                    image_pull_secrets=[V1LocalObjectReference(name="quay-io")],
                    volumes=[
                        V1Volume(
                            name="credentials",
                            secret=V1SecretVolumeSource(
                                secret_name=f"credentials-{self.reconciliation.key.provisioner_name}",
                            ),
                        ),
                        V1Volume(
                            name="workdir",
                            empty_dir=V1EmptyDirVolumeSource(size_limit="10Mi"),
                        ),
                    ],
                    restart_policy="Never",
                    service_account_name="external-resources-sa",
                ),
            ),
        )


JOB_CONCURRENCY_POLICY = (
    JobConcurrencyPolicy.REPLACE_IN_PROGRESS
    | JobConcurrencyPolicy.REPLACE_FAILED
    | JobConcurrencyPolicy.REPLACE_FINISHED
)


class K8sExternalResourcesReconciler(ExternalResourcesReconciler):
    def __init__(self, controller: K8sJobController) -> None:
        self.controller = controller

    def get_resource_reconcile_status(
        self,
        key: Reconciliation,
    ) -> ReconcileStatus:
        return ReconcileStatus(
            self.controller.get_job_status(
                ReconciliationK8sJob(reconciliation=key).name()
            ).value
        )

    def reconcile_resource(
        self,
        key: Reconciliation,
    ) -> bool:
        return self.controller.enqueue_job(
            job=ReconciliationK8sJob(reconciliation=key),
            concurrency_policy=JOB_CONCURRENCY_POLICY,
        )

    def wait_for_reconcile_list_completion(
        self,
        reconcile_list: Iterable[Reconciliation],
        check_interval_seconds: int,
        timeout_seconds: int,
    ) -> dict[Reconciliation, ReconcileStatus]:
        jobs = {ReconciliationK8sJob(reconciliation=r) for r in reconcile_list}
        job_status = self.controller.wait_for_job_list_completion(
            jobs=jobs,
            check_interval_seconds=check_interval_seconds,
            timeout_seconds=timeout_seconds,
        )
        return {
            job.reconciliation: ReconcileStatus(status.value)
            for job, status in job_status
        }

    def write_job_logs_to_stdout(self, key: Reconciliation) -> None:
        self.controller.get_job_logs(
            ReconciliationK8sJob(reconciliation=key), sys.stdout
        )
