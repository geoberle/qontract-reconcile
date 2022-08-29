from dataclasses import dataclass
from typing import Any, Optional
from reconcile.change_owners import (
    BundleFileChange,
    BundleFileType,
    FileRef,
    build_change_type_contexts_from_self_service_roles,
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
                e = jsonpath_ng.parse(jp)
                e.update(new_content, v)
        return BundleFileChange(
            fileref=self.file_ref(),
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
def change_types() -> list[ChangeType]:
    return [saas_file_changetype(), role_member_change_type()]


@pytest.fixture
def saas_file() -> TestDatafile:
    return TestDatafile(**fxt.get_anymarkup("datafile_saas_file.yaml"))


@pytest.fixture
def user_file() -> TestDatafile:
    return TestDatafile(**fxt.get_anymarkup("datafile_user.yaml"))


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
    user_change = BundleFileChange(
        fileref=FileRef(
            path="/somepath.yml",
            schema="/access/user-1.yml",
            file_type=BundleFileType.DATAFILE,
        ),
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
    user_change = BundleFileChange(
        fileref=FileRef(
            path="/somepath.yml",
            schema="/access/user-1.yml",
            file_type=BundleFileType.DATAFILE,
        ),
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
    datafile_change = BundleFileChange(
        fileref=FileRef(
            path="/somepath.yml",
            schema="/some/other/schema.yml",
            file_type=BundleFileType.DATAFILE,
        ),
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
        change_types={saas_file_changetype.name: saas_file_changetype},
        bundle_changes=[saas_file_change],
    )

    assert len(contexts) == 1
    assert contexts[0].approvers == [UserV1(org_username=approver)]
    assert contexts[0].bundle_change == saas_file_change
    assert contexts[0].change_type == saas_file_changetype


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
        change_types={saas_file_changetype.name: saas_file_changetype},
        bundle_changes=[saas_file_change],
    )

    assert not contexts


def test_build_change_type_contexts_from_self_service_roles_context_selector(
    role_member_change_type: ChangeType,
):
    new_role = "/role/new.yml"
    user_change = BundleFileChange(
        fileref=FileRef(
            path="/somepath.yml",
            schema="/access/user-1.yml",
            file_type=BundleFileType.DATAFILE,
        ),
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
        change_types={role_member_change_type.name: role_member_change_type},
        bundle_changes=[user_change],
    )

    assert len(contexts) == 1
    assert contexts[0].approvers == [UserV1(org_username=approver)]
    assert contexts[0].bundle_change == user_change
    assert contexts[0].change_type == role_member_change_type


def test_build_change_type_contexts_from_self_service_roles_context_selector_not_owned(
    role_member_change_type: ChangeType,
):
    new_role = "/role/new.yml"
    user_change = BundleFileChange(
        fileref=FileRef(
            path="/somepath.yml",
            schema="/access/user-1.yml",
            file_type=BundleFileType.DATAFILE,
        ),
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
        change_types={role_member_change_type.name: role_member_change_type},
        bundle_changes=[user_change],
    )

    assert not contexts


#
#
#
