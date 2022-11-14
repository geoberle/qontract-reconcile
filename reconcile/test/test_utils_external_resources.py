import json
from typing import Optional, Union

import pytest
from pydantic import BaseModel

from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
    TypedExternalResourceSpec,
)
import reconcile.utils.external_resources as uer
from reconcile.gql_definitions.fragments.resource_file import ResourceFile


@pytest.fixture
def namespace_info():
    return {
        "managedExternalResources": True,
        "externalResources": [
            {
                "provider": uer.PROVIDER_AWS,
                "provisioner": {
                    "name": "acc1",
                },
                "resources": [
                    {
                        "provider": "rds",
                    }
                ],
            },
            {
                "provider": uer.PROVIDER_AWS,
                "provisioner": {
                    "name": "acc2",
                },
                "resources": [
                    {
                        "provider": "rds",
                    }
                ],
            },
            {
                "provider": "other",
                "provisioner": {
                    "name": "acc3",
                },
                "resources": [
                    {
                        "provider": "other",
                    }
                ],
            },
        ],
    }


@pytest.fixture
def expected(namespace_info):
    return [
        ExternalResourceSpec(
            provision_provider=uer.PROVIDER_AWS,
            resource={"provider": "rds"},
            provisioner={"name": "acc1"},
            namespace=namespace_info,
        ),
        ExternalResourceSpec(
            provision_provider=uer.PROVIDER_AWS,
            resource={"provider": "rds"},
            provisioner={"name": "acc2"},
            namespace=namespace_info,
        ),
    ]


def test_get_external_resource_specs(namespace_info, expected):
    results = uer.get_external_resource_specs(
        namespace_info, provision_provider=uer.PROVIDER_AWS
    )
    assert results == expected


@pytest.fixture
def expected_other(namespace_info):
    return [
        ExternalResourceSpec(
            provision_provider="other",
            resource={"provider": "other"},
            provisioner={"name": "acc3"},
            namespace=namespace_info,
        ),
    ]


def test_get_external_resource_specs_no_filter(
    namespace_info, expected, expected_other
):
    results = uer.get_external_resource_specs(namespace_info)
    assert results == expected + expected_other


def test_get_external_resource_specs_filter_other(namespace_info, expected_other):
    results = uer.get_external_resource_specs(
        namespace_info, provision_provider="other"
    )
    assert results == expected_other


def test_get_provision_providers(namespace_info):
    results = uer.get_provision_providers(namespace_info)
    assert results == {uer.PROVIDER_AWS, "other"}


def test_get_provision_providers_none():
    namespace_info = {"managedExternalResources": False}
    results = uer.get_provision_providers(namespace_info)
    assert not results


def test_managed_external_resources():
    namespace_info = {"managedExternalResources": True}
    assert uer.managed_external_resources(namespace_info) is True


def test_managed_external_resources_none():
    namespace_info = {"managedExternalResources": False}
    assert uer.managed_external_resources(namespace_info) is False


def test_resource_value_resolver_no_defaults_or_overrides():
    """Values are resolved properly when defaults and overrides are omitted."""
    spec = ExternalResourceSpec(
        provision_provider="other",
        provisioner={"name": "some_account"},
        resource={
            "provider": "other",
            "identifier": "some-id",
            "field_1": "data1",
            "field_2": "data2",
            "field_3": "data3",
        },
        namespace={},
    )

    resolver = uer.ResourceValueResolver(spec)
    values = resolver.resolve()

    assert values == {"field_1": "data1", "field_2": "data2", "field_3": "data3"}


def test_resource_value_resolver_identifier_as_value():
    """
    `identifier` is added to the resolved values if `identifier_as_value` is set. This
    is for compatibility when both our schemas and a Terraform provider both expect
    `identifier` to be present (so it must be in the resolved values).
    """
    spec = ExternalResourceSpec(
        provision_provider="other",
        provisioner={"name": "some_account"},
        resource={
            "provider": "other",
            "identifier": "some-id",
            "field_1": "data1",
            "field_2": "data2",
            "field_3": "data3",
        },
        namespace={},
    )

    resolver = uer.ResourceValueResolver(spec, identifier_as_value=True)
    values = resolver.resolve()

    assert values == {
        "identifier": "some-id",
        "field_1": "data1",
        "field_2": "data2",
        "field_3": "data3",
    }


def test_resource_value_resolver_tags():
    """`tags` is added to the resolved values if `integration_tag` is set."""
    spec = ExternalResourceSpec(
        provision_provider="other",
        provisioner={"name": "some_account"},
        resource={
            "provider": "other",
            "identifier": "some-id",
            "field_1": "data1",
            "field_2": "data2",
            "field_3": "data3",
        },
        namespace={
            "name": "some-namespace",
            "cluster": {"name": "some-cluster"},
            "environment": {"name": "some-name"},
            "app": {"name": "some-app"},
        },
    )

    resolver = uer.ResourceValueResolver(spec, integration_tag="some-integration")
    values = resolver.resolve()

    assert values == {
        "field_1": "data1",
        "field_2": "data2",
        "field_3": "data3",
        "tags": {
            "app": "some-app",
            "cluster": "some-cluster",
            "environment": "some-name",
            "managed_by_integration": "some-integration",
            "namespace": "some-namespace",
        },
    }


def test_resource_value_resolver_overrides_and_defaults(mocker):
    """Values are resolved properly when overrides and defaults exist."""
    # The need to patch here will go away once we start using the resolveResource
    # schema option.
    patch_get_values = mocker.patch.object(uer.ResourceValueResolver, "_get_values")
    patch_get_values.return_value = {
        "default_1": "default_data1",
        "default_2": "default_data2",
        "default_3": "default_data3",
    }

    spec = ExternalResourceSpec(
        provision_provider="other",
        provisioner={"name": "some_account"},
        resource={
            "provider": "other",
            "identifier": "some-id",
            "field_1": "field_data1",
            "field_2": "field_data2",
            "field_3": "field_data3",
            "overrides": json.dumps({"default_2": "override_data2"}),
            "defaults": "/some/path",
        },
        namespace={},
    )

    resolver = uer.ResourceValueResolver(spec)
    values = resolver.resolve()

    assert values == {
        "field_1": "field_data1",
        "field_2": "field_data2",
        "field_3": "field_data3",
        "default_1": "default_data1",
        "default_2": "override_data2",
        "default_3": "default_data3",
    }


class TestProvisionier(BaseModel):
    name: str


class MyResource(BaseModel):
    provider: str
    identifier: str


class ResourceOverrides(BaseModel):
    field_1: Optional[str]
    field_2: Optional[str]


class OverrideableResource(BaseModel):
    provider: str
    identifier: str
    overrides: Optional[ResourceOverrides]
    defaults: Optional[ResourceFile]


class TestNamespaceExternalResource(BaseModel):
    provider: str
    provisioner: TestProvisionier
    resources: list[Union[MyResource, OverrideableResource]]


class TestNamespace(BaseModel):
    name: str
    managed_external_resources: bool
    external_resources: Optional[list[TestNamespaceExternalResource]]


@pytest.fixture
def namespace() -> TestNamespace:
    return TestNamespace(
        name="ns",
        managed_external_resources=True,
        external_resources=[
            TestNamespaceExternalResource(
                provider="pp",
                provisioner=TestProvisionier(name="pn"),
                resources=[
                    MyResource(provider="rp", identifier="ri"),
                ],
            )
        ],
    )


def test_get_external_resource_specs_for_namespace(
    namespace: TestNamespace,
):
    external_resources = uer.get_external_resource_specs_for_namespace(
        namespace, MyResource, None
    )
    assert len(external_resources) == 1

    assert external_resources[0].provision_provider == "pp"
    assert external_resources[0].provisioner_name == "pn"
    assert external_resources[0].namespace_name == "ns"
    assert external_resources[0].provider == "rp"
    assert external_resources[0].identifier == "ri"


def test_get_external_resource_specs_for_namespace_provisioning_provider_filter(
    namespace: TestNamespace,
):
    external_resources = uer.get_external_resource_specs_for_namespace(
        namespace, MyResource, "another-provisioning-provider"
    )
    assert len(external_resources) == 0


def test_get_external_resource_specs_for_namespace_wrong_type(namespace: TestNamespace):
    with pytest.raises(ValueError):
        uer.get_external_resource_specs_for_namespace(
            namespace, OverrideableResource, None
        )


def test_typed_external_resource_resolve_no_defaults(namespace: TestNamespace):
    """
    In this scenario, the resource has no defaults, so overrides remain untouched.
    """
    assert namespace.external_resources is not None
    spec = TypedExternalResourceSpec[OverrideableResource](
        namespace_spec=namespace,
        namespace_external_resource=namespace.external_resources[0],
        spec=OverrideableResource(
            provider="p",
            identifier="i",
            overrides=ResourceOverrides(field_1="f1", field_2="f2"),
            defaults=None,
        ),
    )
    resolved_spec = spec.resolve()
    assert resolved_spec.spec.overrides == spec.spec.overrides


def test_typed_external_resource_resolve_defaults_overrides(
    namespace: TestNamespace,
):
    """
    This scenario tests defaults overwriting undefined overrides.
    """
    overwrite_f2 = "f2_override"
    default_f1 = "f1_default"
    default_f2 = "f2_default"
    assert namespace.external_resources is not None
    spec = TypedExternalResourceSpec[OverrideableResource](
        namespace_spec=namespace,
        namespace_external_resource=namespace.external_resources[0],
        spec=OverrideableResource(
            provider="p",
            identifier="i",
            overrides=ResourceOverrides(field_1=None, field_2=overwrite_f2),
            defaults=ResourceFile(
                resourceFileSchema=None,
                content=f"field_1: {default_f1}\nfield_2: {default_f2}",
            ),
        ),
    )
    resolved_spec = spec.resolve()
    assert resolved_spec.spec.overrides is not None
    assert resolved_spec.spec.overrides.field_1 == default_f1
    assert resolved_spec.spec.overrides.field_2 == overwrite_f2


def test_typed_external_resource_resolve_override_none(
    namespace: TestNamespace,
):
    """
    This scenario tests that a missing override is created from defaults.
    """
    default_f1 = "f1_default"
    default_f2 = "f2_default"
    assert namespace.external_resources is not None
    spec = TypedExternalResourceSpec[OverrideableResource](
        namespace_spec=namespace,
        namespace_external_resource=namespace.external_resources[0],
        spec=OverrideableResource(
            provider="p",
            identifier="i",
            overrides=None,
            defaults=ResourceFile(
                resourceFileSchema=None,
                content=f"field_1: {default_f1}\nfield_2: {default_f2}",
            ),
        ),
    )
    resolved_spec = spec.resolve()
    assert resolved_spec.spec.overrides is not None
    assert resolved_spec.spec.overrides.field_1 == default_f1
    assert resolved_spec.spec.overrides.field_2 == default_f2
