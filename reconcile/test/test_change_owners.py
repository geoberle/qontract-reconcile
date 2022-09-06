from dataclasses import dataclass
from typing import Any, Optional
from reconcile.change_owners import (
    BundleFileChange,
    BundleFileType,
    ChangeTypeContext,
    ChangeTypeProcessor,
    Diff,
    FileRef,
    create_bundle_file_change,
    build_change_type_contexts_from_self_service_roles,
    deep_diff_path_to_jsonpath,
    extract_datafile_context_from_bundle_change,
)
from reconcile.gql_definitions.change_owners.fragments.change_type import ChangeType
from reconcile.gql_definitions.change_owners.queries.self_service_roles import (
    ChangeTypeV1,
    DatafileObjectV1,
    RoleV1,
    SelfServiceConfigV1,
    UserV1,
)

from .fixtures import Fixtures

import pytest
import copy
import jsonpath_ng
import jsonpath_ng.ext

fxt = Fixtures("change_owners")


@dataclass
class TestDatafile:
    datafilepath: str
    datafileschema: str
    content: dict[str, Any]

    def file_ref(self) -> FileRef:
        return FileRef(
            path=self.datafilepath,
            schema=self.datafileschema,
            file_type=BundleFileType.DATAFILE,
        )

    def create_bundle_change(
        self, jsonpath_patches: Optional[dict[str, Any]] = None
    ) -> BundleFileChange:
        new_content = copy.deepcopy(self.content)
        if jsonpath_patches:
            for jp, v in jsonpath_patches.items():
                e = jsonpath_ng.ext.parse(jp)
                e.update(new_content, v)
        return create_bundle_file_change(
            path=self.datafilepath,
            schema=self.datafileschema,
            file_type=BundleFileType.DATAFILE,
            old=self.content,
            new=new_content,
        )


def load_change_type(path: str) -> ChangeType:
    content = fxt.get_anymarkup(path)
    return ChangeType(**content)


def load_self_service_roles(path: str) -> list[RoleV1]:
    roles = fxt.get_anymarkup(path)["self_service_roles"]
    return [RoleV1(**r) for r in roles]


def build_role(
    name: str,
    change_type_name: str,
    datafiles: Optional[list[DatafileObjectV1]],
    users: Optional[list[str]],
) -> RoleV1:
    return RoleV1(
        name=name,
        path=f"/role/{name}.yaml",
        self_service=[
            SelfServiceConfigV1(
                change_type=ChangeTypeV1(
                    name=change_type_name,
                ),
                datafiles=datafiles,
                resources=None,
            )
        ],
        users=[UserV1(org_username=u) for u in users or []],
    )


@pytest.fixture
def saas_file_changetype() -> ChangeType:
    return load_change_type("changetype_saas_file.yaml")


@pytest.fixture
def role_member_change_type() -> ChangeType:
    return load_change_type("changetype_role_member.yaml")


@pytest.fixture
def secret_promoter_change_type() -> ChangeType:
    return load_change_type("changetype_secret_promoter.yaml")


@pytest.fixture
def change_types() -> list[ChangeType]:
    return [saas_file_changetype(), role_member_change_type()]


@pytest.fixture
def saas_file() -> TestDatafile:
    return TestDatafile(**fxt.get_anymarkup("datafile_saas_file.yaml"))


@pytest.fixture
def user_file() -> TestDatafile:
    return TestDatafile(**fxt.get_anymarkup("datafile_user.yaml"))


@pytest.fixture
def namespace_file() -> TestDatafile:
    return TestDatafile(**fxt.get_anymarkup("datafile_namespace.yaml"))


#
# testcases for context extraction from bundle changes
#


def test_extract_datafile_context_from_bundle_change(
    saas_file_changetype: ChangeType, saas_file: TestDatafile
):
    """
    in this testcase, a changed datafile matches directly the context schema
    of the change type, so the change type is directly relevant for the changed
    datafile
    """
    datafile_context = extract_datafile_context_from_bundle_change(
        saas_file.create_bundle_change(), saas_file_changetype
    )
    assert datafile_context == [saas_file.file_ref()]


def test_extract_datafile_context_from_bundle_change_schema_mismatch(
    saas_file_changetype: ChangeType, saas_file: TestDatafile
):
    """
    in this testcase, the schema of the bundle change and the schema of the
    change types do not match and hence to context is extracted.
    """
    saas_file.datafileschema = "/some/other/schema.yml"
    datafile_context = extract_datafile_context_from_bundle_change(
        saas_file.create_bundle_change(), saas_file_changetype
    )
    assert not datafile_context


def test_extract_added_selector_datafile_context_from_bundle_change(
    role_member_change_type: ChangeType,
):
    """
    in this testcase, a changed datafile does not directly belong to the change
    type, because the context schema does not match (change type reacts to roles,
    while the changed datafile is a user). but the change type defines a context
    extraction section that feels responsible for user files and extracts the
    relevant context, the role, from the users role section, looking out for added
    roles.
    """
    new_role = "/role/new.yml"
    user_change = create_bundle_file_change(
        path="/somepath.yml",
        schema="/access/user-1.yml",
        file_type=BundleFileType.DATAFILE,
        old={
            "roles": [{"$ref": "/role/existing.yml"}],
        },
        new={
            "roles": [{"$ref": "/role/existing.yml"}, {"$ref": new_role}],
        },
    )
    datafile_context = extract_datafile_context_from_bundle_change(
        user_change, role_member_change_type
    )
    assert datafile_context == [
        FileRef(
            file_type=BundleFileType.DATAFILE,
            schema="/access/roles-1.yml",
            path=new_role,
        )
    ]


def test_extract_removed_selector_datafile_context_from_bundle_change(
    role_member_change_type: ChangeType,
):
    """
    this testcase is similar to previous one, but detects removed contexts (e.g
    roles in this example) as the relevant context to extract.
    """
    role_member_change_type.changes[0].context.when = "removed"  # type: ignore
    existing_role = "/role/existing.yml"
    new_role = "/role/new.yml"
    user_change = create_bundle_file_change(
        path="/somepath.yml",
        schema="/access/user-1.yml",
        file_type=BundleFileType.DATAFILE,
        old={
            "roles": [{"$ref": existing_role}],
        },
        new={
            "roles": [{"$ref": new_role}],
        },
    )
    datafile_context = extract_datafile_context_from_bundle_change(
        user_change, role_member_change_type
    )
    assert datafile_context == [
        FileRef(
            file_type=BundleFileType.DATAFILE,
            schema="/access/roles-1.yml",
            path=existing_role,
        )
    ]


def test_extract_selector_datafile_context_from_bundle_change_schema_mismatch(
    role_member_change_type: ChangeType,
):
    """
    in this testcase, the changeSchema section of the change types changes does
    not match the bundle change.
    """
    datafile_change = create_bundle_file_change(
        path="/somepath.yml",
        schema="/some/other/schema.yml",
        file_type=BundleFileType.DATAFILE,
        old=None,
        new=None,
    )
    datafile_context = extract_datafile_context_from_bundle_change(
        datafile_change, role_member_change_type
    )
    assert not datafile_context


def test_with_a_context_selector_where_the_datafile_has_no_matching_section():
    pass


#
# testcases for ChangeTypeContext construction
#


def test_build_change_type_contexts_from_self_service_roles(
    saas_file_changetype: ChangeType, saas_file: TestDatafile
):
    approver = "approver"
    role = build_role(
        "role-1",
        saas_file_changetype.name,
        [
            DatafileObjectV1(
                datafileSchema=saas_file.datafileschema, path=saas_file.datafilepath
            )
        ],
        users=[approver],
    )
    saas_file_change = saas_file.create_bundle_change()
    contexts = build_change_type_contexts_from_self_service_roles(
        roles=[role],
        change_types=[saas_file_changetype],
        bundle_changes=[saas_file_change],
    )

    assert saas_file_change.fileref in contexts
    change_type_contexts = contexts[saas_file_change.fileref]
    assert len(change_type_contexts) == 1
    assert change_type_contexts[0].approvers == [UserV1(org_username=approver)]
    assert (
        change_type_contexts[0].change_type_processor.change_type
        == saas_file_changetype
    )


def test_build_change_type_contexts_from_self_service_roles_not_owned(
    saas_file_changetype: ChangeType, saas_file: TestDatafile
):
    approver = "approver"
    role = build_role(
        "role-1",
        saas_file_changetype.name,
        [
            DatafileObjectV1(
                datafileSchema=saas_file.datafileschema,
                path="/some/other/saas-file.yaml",
            )
        ],
        users=[approver],
    )
    saas_file_change = saas_file.create_bundle_change()
    contexts = build_change_type_contexts_from_self_service_roles(
        roles=[role],
        change_types=[saas_file_changetype],
        bundle_changes=[saas_file_change],
    )

    assert not contexts


def test_build_change_type_contexts_from_self_service_roles_context_selector(
    role_member_change_type: ChangeType,
):
    new_role = "/role/new.yml"
    user_change = create_bundle_file_change(
        path="/somepath.yml",
        schema="/access/user-1.yml",
        file_type=BundleFileType.DATAFILE,
        old={
            "roles": [{"$ref": "/role/existing.yml"}],
        },
        new={
            "roles": [{"$ref": "/role/existing.yml"}, {"$ref": new_role}],
        },
    )

    approver = "approver"
    role = build_role(
        "role-1",
        role_member_change_type.name,
        [DatafileObjectV1(datafileSchema="/access/role-1.yml", path=new_role)],
        users=[approver],
    )
    contexts = build_change_type_contexts_from_self_service_roles(
        roles=[role],
        change_types=[role_member_change_type],
        bundle_changes=[user_change],
    )

    assert user_change.fileref in contexts
    change_type_contexts = contexts[user_change.fileref]
    assert len(change_type_contexts) == 1
    assert change_type_contexts[0].approvers == [UserV1(org_username=approver)]
    assert (
        change_type_contexts[0].change_type_processor.change_type
        == role_member_change_type
    )


def test_build_change_type_contexts_from_self_service_roles_context_selector_not_owned(
    role_member_change_type: ChangeType,
):
    new_role = "/role/new.yml"
    user_change = create_bundle_file_change(
        path="/somepath.yml",
        schema="/access/user-1.yml",
        file_type=BundleFileType.DATAFILE,
        old={
            "roles": [{"$ref": "/role/existing.yml"}],
        },
        new={
            "roles": [{"$ref": "/role/existing.yml"}, {"$ref": new_role}],
        },
    )

    approver = "approver"
    role = build_role(
        "role-1",
        role_member_change_type.name,
        [
            DatafileObjectV1(
                datafileSchema="/access/role-1.yml", path="/some/other/role.yml"
            )
        ],
        users=[approver],
    )
    contexts = build_change_type_contexts_from_self_service_roles(
        roles=[role],
        change_types=[role_member_change_type],
        bundle_changes=[user_change],
    )

    assert not contexts


#
# deep diff path translation
#


@pytest.mark.parametrize(
    "deep_diff_path,expected_json_path",
    [
        ("root['one']['two']['three']", "one.two.three"),
        (
            "root['resourceTemplates'][0]['targets'][0]['ref']",
            "resourceTemplates.[0].targets.[0].ref",
        ),
    ],
)
def test_deep_diff_path_to_jsonpath(deep_diff_path, expected_json_path):
    assert str(deep_diff_path_to_jsonpath(deep_diff_path)) == expected_json_path


#
# change type processor find allowed changed paths
#


def test_change_type_processor_allowed_paths_simple(
    role_member_change_type: ChangeType, user_file: TestDatafile
):
    changed_user_file = user_file.create_bundle_change()
    processor = ChangeTypeProcessor(change_type=role_member_change_type)
    paths = processor.allowed_changed_paths(changed_user_file)

    assert paths == ["roles"]


def test_change_type_processor_allowed_paths_conditions(
    secret_promoter_change_type: ChangeType, namespace_file: TestDatafile
):
    changed_namespace_file = namespace_file.create_bundle_change()
    processor = ChangeTypeProcessor(change_type=secret_promoter_change_type)
    paths = processor.allowed_changed_paths(changed_namespace_file)

    assert paths == ["openshiftResources.[1].version"]


#
# bundle changes diff detection
#


def test_bundle_change_diff_value_changed():
    bundle_change = create_bundle_file_change(
        path="path",
        schema="schema",
        file_type=BundleFileType.DATAFILE,
        old={"field": "old_value"},
        new={"field": "new_value"},
    )

    assert len(bundle_change.diffs) == 1
    assert str(bundle_change.diffs[0].path) == "field"
    assert bundle_change.diffs[0].diff_type == "changed"
    assert bundle_change.diffs[0].old == "old_value"
    assert bundle_change.diffs[0].new == "new_value"


def test_bundle_change_diff_value_changed_deep():
    bundle_change = create_bundle_file_change(
        path="path",
        schema="schema",
        file_type=BundleFileType.DATAFILE,
        old={"parent": {"children": [{"age": 1}]}},
        new={"parent": {"children": [{"age": 2}]}},
    )

    assert len(bundle_change.diffs) == 1
    assert str(bundle_change.diffs[0].path) == "parent.children.[0].age"
    assert bundle_change.diffs[0].diff_type == "changed"
    assert bundle_change.diffs[0].old == 1
    assert bundle_change.diffs[0].new == 2


def test_bundle_change_diff_value_changed_multiple_in_iterable():
    """
    this testscenario searches shows how changes can be detected in a list,
    when objects with identifiers and objects without are mixed and shuffled
    """
    bundle_change = create_bundle_file_change(
        path="path",
        schema="/openshift/namespace-1.yml",
        file_type=BundleFileType.DATAFILE,
        old={
            "$schema": "/openshift/namespace-1.yml",
            "openshiftResources": [
                {
                    "provider": "vault-secret",
                    "path": "path-1",
                    "version": 1,
                    "__identifier": "secret-1",
                },
                {
                    "provider": "vault-secret",
                    "path": "path-2",
                    "version": 2,
                    "__identifier": "secret-2",
                },
                {
                    "provider": "resource-template",
                    "path": "res-1",
                    "variables": {"var1": "val1", "var2": "val2"},
                },
                {
                    "provider": "resource-template",
                    "path": "res-1",
                    "variables": {"var1": "val3", "var2": "val4"},
                },
            ],
        },
        new={
            "$schema": "/openshift/namespace-1.yml",
            "openshiftResources": [
                {
                    "provider": "vault-secret",
                    "path": "path-2",
                    "version": 1,
                    "__identifier": "secret-2",
                },
                {
                    "provider": "resource-template",
                    "path": "res-1",
                    "variables": {"var1": "val1", "var2": "new_val"},
                },
                {
                    "provider": "vault-secret",
                    "name": "secret-1",
                    "version": 2,
                    "__identifier": "secret-1",
                },
                {
                    "provider": "resource-template",
                    "path": "res-1",
                    "variables": {"var1": "val3", "var2": "val4"},
                },
            ],
        },
    )

    expected = [
        Diff(
            path=jsonpath_ng.parse("openshiftResources.[1].version"),
            diff_type="changed",
            old=2,
            new=1,
            covered_by=[],
        ),
        Diff(
            path=jsonpath_ng.parse("openshiftResources.[2].variables.var2"),
            diff_type="changed",
            old="val2",
            new="new_val",
            covered_by=[],
        ),
        Diff(
            path=jsonpath_ng.parse("openshiftResources.[0].version"),
            diff_type="changed",
            old=1,
            new=2,
            covered_by=[],
        ),
    ]
    assert bundle_change.diffs == expected


def test_bundle_change_diff_item_added():
    pass


def test_bundle_change_diff_item_removed():
    pass


#
# processing change coverage on a change type context
#


def test_cover_changes_one_file(
    saas_file_changetype: ChangeType, saas_file: TestDatafile
):
    saas_file_change = saas_file.create_bundle_change(
        {"resourceTemplates[0].targets[0].ref": "new-ref"}
    )
    ctx = ChangeTypeContext(
        change_type_processor=ChangeTypeProcessor(saas_file_changetype),
        approvers=[UserV1(org_username="user")],
    )
    ctx.cover_changes(saas_file_change)

    for diff in saas_file_change.diffs:
        assert diff.covered_by == [ctx]


def test_uncover_change_one_file(
    saas_file_changetype: ChangeType, saas_file: TestDatafile
):
    saas_file_change = saas_file.create_bundle_change({"name": "new-name"})
    ctx = ChangeTypeContext(
        change_type_processor=ChangeTypeProcessor(saas_file_changetype),
        approvers=[UserV1(org_username="user")],
    )
    ctx.cover_changes(saas_file_change)

    for diff in saas_file_change.diffs:
        assert diff.covered_by == []


def test_partially_covered_change_one_file(
    saas_file_changetype: ChangeType, saas_file: TestDatafile
):
    saas_file_change = saas_file.create_bundle_change(
        {"resourceTemplates[0].targets[0].ref": "new-ref", "name": "new-name"}
    )
    ctx = ChangeTypeContext(
        change_type_processor=ChangeTypeProcessor(saas_file_changetype),
        approvers=[UserV1(org_username="user")],
    )
    ctx.cover_changes(saas_file_change)

    for diff in saas_file_change.diffs:
        if str(diff.path) == "name":
            assert diff.covered_by == []
        elif str(diff.path) == "resourceTemplates.[0].targets.[0].ref":
            assert diff.covered_by == [ctx]
        else:
            pytest.fail(f"unexpected change path {str(diff.path)}")


#
# e2e change coverage
#


def test_change_coverage(
    secret_promoter_change_type: ChangeType,
    namespace_file: TestDatafile,
    role_member_change_type: ChangeType,
    user_file: TestDatafile,
):
    role_approver_user = "the-one-that-approves-roles"
    team_role_path = "/team-role.yml"
    role_approval_role = build_role(
        name="team-role",
        change_type_name=role_member_change_type.name,
        datafiles=[
            DatafileObjectV1(datafileSchema="/access/role-1.yml", path=team_role_path)
        ],
        users=[role_approver_user],
    )

    secret_approver_user = "the-one-that-approves-secret-promotions"
    secret_promoter_role = build_role(
        name="secret-promoter-role",
        change_type_name=secret_promoter_change_type.name,
        datafiles=[
            DatafileObjectV1(
                datafileSchema=namespace_file.datafileschema,
                path=namespace_file.datafilepath,
            )
        ],
        users=[secret_approver_user],
    )

    bundle_changes = [
        # create a datafile change by patching the role
        user_file.create_bundle_change({"roles[0]": {"$ref": team_role_path}}),
        # create a datafile change by bumping a secret version
        namespace_file.create_bundle_change({"openshiftResources[1].version": 2}),
    ]

    contexts = build_change_type_contexts_from_self_service_roles(
        roles=[role_approval_role, secret_promoter_role],
        change_types=[role_member_change_type, secret_promoter_change_type],
        bundle_changes=bundle_changes,
    )

    for bc in bundle_changes:
        if bc.fileref in contexts:
            for ctx in contexts[bc.fileref]:
                ctx.cover_changes(bc)
        for d in bc.diffs:
            if str(d.path) == "roles.[0].$ref":
                expected_approver = role_approver_user
            elif str(d.path) == "openshiftResources.[1].version":
                expected_approver = secret_approver_user
            else:
                pytest.fail(f"unexpected change path {str(d.path)}")
            assert len(d.covered_by) == 1
            assert len(d.covered_by[0].approvers) == 1
            assert d.covered_by[0].approvers[0].org_username == expected_approver
