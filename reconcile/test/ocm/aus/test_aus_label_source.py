from typing import Optional

from reconcile.aus.aus_label_source import (
    AUSClusterUpgradePolicyLabelSource,
    AUSOrganizationLabelSource,
)
from reconcile.gql_definitions.advanced_upgrade_service.aus_clusters import (
    ClusterSpecV1,
    ClusterV1,
)
from reconcile.gql_definitions.fragments.aus_organization import AUSOCMOrganization
from reconcile.test.ocm.aus.fixtures import (
    build_organization,
    build_upgrade_policy,
)


def build_cluster(
    name: str,
    org: AUSOCMOrganization,
    soak_days: int = 0,
    workloads: Optional[list[str]] = None,
    schedule: Optional[str] = None,
    sector: Optional[str] = None,
    mutexes: Optional[list[str]] = None,
    blocked_versions: Optional[list[str]] = None,
) -> ClusterV1:
    return ClusterV1(
        name=name,
        ocm=org,
        spec=ClusterSpecV1(
            product="rosa",
            id=f"{name}-id",
            external_id="ocm-external-id",
            version="4.8.0",
        ),
        upgradePolicy=build_upgrade_policy(
            soak_days=soak_days,
            workloads=workloads,
            schedule=schedule,
            sector=sector,
            mutexes=mutexes,
            blocked_versions=blocked_versions,
        ),
        disable=None,
    )


#
# test sourcing labels from cluster upgrade policies
#


def test_cluster_upgrade_policy_label_source() -> None:
    org = build_organization(
        org_id="org-1",
        org_name="org-1",
        env_name="ocm-prod",
    )
    source = AUSClusterUpgradePolicyLabelSource(
        clusters=[
            build_cluster("cluster-1", org, workloads=["workload-1"]),
        ]
    )

    sourced_labels = source.get_labels()
    assert len(sourced_labels) == 1
    label_owner = next(iter(sourced_labels))
    assert sourced_labels[label_owner] == {
        "sre-capabilities.aus.soak-days": "0",
        "sre-capabilities.aus.workloads": "workload-1",
        "sre-capabilities.aus.schedule": "* * * * *",
    }


def test_cluster_upgrade_policy_label_source_sector() -> None:
    org = build_organization(
        org_id="org-1",
        org_name="org-1",
        env_name="ocm-prod",
    )
    source = AUSClusterUpgradePolicyLabelSource(
        clusters=[
            build_cluster(
                "cluster-1", org, workloads=["workload-1"], sector="sector-1"
            ),
        ]
    )

    sourced_labels = source.get_labels()
    assert len(sourced_labels) == 1
    label_owner = next(iter(sourced_labels))
    assert sourced_labels[label_owner] == {
        "sre-capabilities.aus.soak-days": "0",
        "sre-capabilities.aus.workloads": "workload-1",
        "sre-capabilities.aus.schedule": "* * * * *",
        "sre-capabilities.aus.sector": "sector-1",
    }


def test_cluster_upgrade_policy_label_source_mutexes() -> None:
    org = build_organization(
        org_id="org-1",
        org_name="org-1",
        env_name="ocm-prod",
    )
    source = AUSClusterUpgradePolicyLabelSource(
        clusters=[
            build_cluster(
                "cluster-1",
                org,
                workloads=["workload-1"],
                mutexes=["mutex-1", "mutex-2"],
            ),
        ]
    )

    sourced_labels = source.get_labels()
    assert len(sourced_labels) == 1
    label_owner = next(iter(sourced_labels))
    assert sourced_labels[label_owner] == {
        "sre-capabilities.aus.soak-days": "0",
        "sre-capabilities.aus.workloads": "workload-1",
        "sre-capabilities.aus.schedule": "* * * * *",
        "sre-capabilities.aus.mutexes": "mutex-1,mutex-2",
    }


def test_cluster_upgrade_policy_label_source_blocked_versions() -> None:
    org = build_organization(
        org_id="org-1",
        org_name="org-1",
        env_name="ocm-prod",
    )
    source = AUSClusterUpgradePolicyLabelSource(
        clusters=[
            build_cluster(
                "cluster-1",
                org,
                workloads=["workload-1"],
                blocked_versions=["4.12.1", "4.12.2"],
            ),
        ]
    )

    sourced_labels = source.get_labels()
    assert len(sourced_labels) == 1
    label_owner = next(iter(sourced_labels))
    assert sourced_labels[label_owner] == {
        "sre-capabilities.aus.soak-days": "0",
        "sre-capabilities.aus.workloads": "workload-1",
        "sre-capabilities.aus.schedule": "* * * * *",
        "sre-capabilities.aus.blocked-versions": "4.12.1,4.12.2",
    }


#
# test sourcing labels from organizations
#


def test_aus_organization_label_source_blocked_versions() -> None:
    source = AUSOrganizationLabelSource(
        organizations=[
            build_organization(
                org_id="org-1",
                org_name="org-1",
                env_name="ocm-prod",
                blocked_versions=["4.12.1", "4.12.2"],
            )
        ]
    )

    sourced_labels = source.get_labels()
    assert len(sourced_labels) == 1
    label_owner = next(iter(sourced_labels))
    assert sourced_labels[label_owner] == {
        "sre-capabilities.aus.blocked-versions": "4.12.1,4.12.2",
    }


def test_aus_organization_label_source_sector_dependencies() -> None:
    source = AUSOrganizationLabelSource(
        organizations=[
            build_organization(
                org_id="org-1",
                org_name="org-1",
                env_name="ocm-prod",
                sector_dependencies={"prod": ["stage-1", "stage-2"], "stage-1": None},
            )
        ]
    )

    sourced_labels = source.get_labels()
    assert len(sourced_labels) == 1
    label_owner = next(iter(sourced_labels))
    assert sourced_labels[label_owner] == {
        "sre-capabilities.aus.sectors.prod": "stage-1,stage-2",
    }


def test_aus_organization_label_source_inherit() -> None:
    source = AUSOrganizationLabelSource(
        organizations=[
            build_organization(
                org_id="org-1",
                org_name="org-1",
                env_name="ocm-prod",
                inherit_version_data_from_org_ids=[
                    ("ocm-stage", "org-2", True),
                    ("ocm-stage", "org-3", True),
                ],
            )
        ]
    )

    sourced_labels = source.get_labels()
    assert len(sourced_labels) == 1
    label_owner = next(iter(sourced_labels))
    assert sourced_labels[label_owner] == {
        "sre-capabilities.aus.version-data.inherit": "org-2,org-3",
    }


def test_aus_organization_label_source_publish() -> None:
    source = AUSOrganizationLabelSource(
        organizations=[
            build_organization(
                org_id="org-1",
                org_name="org-1",
                env_name="ocm-prod",
                publish_version_data_from_org_ids=["org-2", "org-3"],
            )
        ]
    )

    sourced_labels = source.get_labels()
    assert len(sourced_labels) == 1
    label_owner = next(iter(sourced_labels))
    assert sourced_labels[label_owner] == {
        "sre-capabilities.aus.version-data.publish": "org-2,org-3",
    }
