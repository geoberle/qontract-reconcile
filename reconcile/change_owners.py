from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Protocol, Tuple
from functools import reduce
import re

from reconcile.utils import gql
from reconcile.gql_definitions.change_owners.fragments.change_type import (
    ChangeType,
    ChangeTypeChangeDetectorJsonPathProviderV1,
)
from reconcile.gql_definitions.change_owners.queries.self_service_roles import RoleV1
from reconcile.gql_definitions.change_owners.queries import (
    self_service_roles,
    change_types,
)
from reconcile.utils.semver_helper import make_semver

from deepdiff import DeepDiff
from deepdiff.helper import CannotCompare

import jsonpath_ng
import jsonpath_ng.ext
from tabulate import tabulate


QONTRACT_INTEGRATION = "change-owners"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class BundleFileType(Enum):
    DATAFILE = "datafile"
    RESOURCEFILE = "resourcefile"


@dataclass(frozen=True)
class FileRef:
    file_type: BundleFileType
    path: str
    schema: Optional[str]


class DiffType(Enum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


@dataclass
class Diff:
    path: jsonpath_ng.JSONPath
    diff_type: DiffType
    old: Optional[Any]
    new: Optional[Any]
    covered_by: list["ChangeTypeContext"]


@dataclass
class BundleFileChange:
    fileref: FileRef
    old: Optional[dict[str, Any]]
    new: Optional[dict[str, Any]]
    diffs: list[Diff]

    def cover_changes(self, change_type_context: "ChangeTypeContext") -> list[Diff]:
        covered_diffs = {}
        covered_diffs.update(
            self._cover_changes_for_diff_types(
                [DiffType.ADDED, DiffType.CHANGED], self.new, change_type_context
            )
        )
        covered_diffs.update(
            self._cover_changes_for_diff_types(
                [DiffType.REMOVED], self.old, change_type_context
            )
        )
        return list(covered_diffs.values())

    def _cover_changes_for_diff_types(
        self,
        diff_types: list[DiffType],
        file_content: Any,
        change_type_context: "ChangeTypeContext",
    ) -> dict[str, Diff]:
        covered_diffs = {}
        filtered_diffs = self._filter_diffs(diff_types)
        if filtered_diffs:
            for (
                allowed_path
            ) in change_type_context.change_type_processor.allowed_changed_paths(
                self.fileref, file_content
            ):
                for d in filtered_diffs:
                    covered = str(d.path).startswith(allowed_path)
                    if covered:
                        covered_diffs[str(d.path)] = d
                        d.covered_by.append(change_type_context)
        return covered_diffs

    def _filter_diffs(self, diff_types: list[DiffType]) -> list[Diff]:
        return list(filter(lambda d: d.diff_type in diff_types, self.diffs))


def compare_object_ctx_identifier(x: Any, y: Any):
    """
    this function helps the deepdiff library to decide if two objects are
    actually the same in the sense of identity. this helps with finding
    changes in lists where reordering items might occure.
    the __identifier key of an object is maintained by the qontract-validator
    based on the contextUnique flags on properties in jsonschemas of qontract-schema.

    in a list of heterogenous elements (e.g. openshiftResources), not every element
    necessarily has an __identitry property, e.g. vault-secret elements have one,
    but resource-template elements don't (because there is no set of properties
    clearly identifying the resulting resource).

    if two objects with no identity properties are compared, deepdiff will still
    try to figure out if they might be the same object based on a critical number
    of unique properties. this situation is signaled back by raising the CannotCompare
    exception
    """
    x_id = x.get("__identifier")
    y_id = y.get("__identifier")
    if x_id and y_id:
        # if both have an identifier, they are the same if the identifier is the same
        return x_id == y_id
    if x_id or y_id:
        # if only one of them has an identifier, they must be different objects
        return False
    raise CannotCompare() from None


def create_bundle_file_change(
    path: str,
    schema: Optional[str],
    file_type: BundleFileType,
    old_file_content: Any,
    new_file_content: Any,
) -> BundleFileChange:
    fileref = FileRef(path=path, schema=schema, file_type=file_type)
    diffs: list[Diff] = []
    if old_file_content and new_file_content:
        deep_diff = DeepDiff(
            old_file_content,
            new_file_content,
            ignore_order=True,
            iterable_compare_func=compare_object_ctx_identifier,
        )
        # handle changed values
        diffs.extend(
            [
                Diff(
                    path=deep_diff_path_to_jsonpath(path),
                    diff_type=DiffType.CHANGED,
                    old=change.get("old_value"),
                    new=change.get("new_value"),
                    covered_by=[],
                )
                for path, change in deep_diff.get("values_changed", {}).items()
            ]
        )
        # handle property added
        diffs.extend(
            [
                Diff(
                    path=deep_diff_path_to_jsonpath(path),
                    diff_type=DiffType.ADDED,
                    old=None,
                    new=None,  # TODO(goberlec) get access to new
                    covered_by=[],
                )
                for path in deep_diff.get("dictionary_item_added", [])
            ]
        )
        # handle property removed
        diffs.extend(
            [
                Diff(
                    path=deep_diff_path_to_jsonpath(path),
                    diff_type=DiffType.REMOVED,
                    old=None,  # TODO(goberlec) get access to new
                    new=None,
                    covered_by=[],
                )
                for path in deep_diff.get("dictionary_item_removed", [])
            ]
        )
        # handle added items
        diffs.extend(
            [
                Diff(
                    path=deep_diff_path_to_jsonpath(path),
                    diff_type=DiffType.ADDED,
                    old=None,
                    new=change,
                    covered_by=[],
                )
                for path, change in deep_diff.get("iterable_item_added", {}).items()
            ]
        )
        # handle removed items
        diffs.extend(
            [
                Diff(
                    path=deep_diff_path_to_jsonpath(path),
                    diff_type=DiffType.REMOVED,
                    old=change,
                    new=None,
                    covered_by=[],
                )
                for path, change in deep_diff.get("iterable_item_removed", {}).items()
            ]
        )
    return BundleFileChange(
        fileref=fileref, old=old_file_content, new=new_file_content, diffs=diffs
    )


class Approver(Protocol):
    org_username: str


def extract_datafile_context_from_bundle_change(
    bundle_change: BundleFileChange, change_type: ChangeType
) -> list[FileRef]:
    if not change_type.changes:
        return []

    if change_type.context_schema == bundle_change.fileref.schema:
        return [bundle_change.fileref]

    contexts: list[FileRef] = []
    for c in change_type.changes:
        if c.change_schema == bundle_change.fileref.schema and c.context:
            context_selector = jsonpath_ng.ext.parse(c.context.selector)
            old_contexts = {e.value for e in context_selector.find(bundle_change.old)}
            new_contexts = {e.value for e in context_selector.find(bundle_change.new)}
            if c.context.when == "added":
                affected_context_paths = new_contexts - old_contexts
            elif c.context.when == "removed":
                affected_context_paths = old_contexts - new_contexts
            contexts.extend(
                [
                    FileRef(
                        schema=change_type.context_schema,
                        path=path,
                        file_type=BundleFileType.DATAFILE,
                    )
                    for path in affected_context_paths
                ]
            )
    return contexts


DEEP_DIFF_RE = re.compile(r"\['?(.*?)'?\]")


def deep_diff_path_to_jsonpath(deep_diff_path: str) -> str:
    """
    deepdiff's way to describe a path within a data structure differs from jsonpath.
    this function helps to translate deepdiff paths into regular jsonpath expressions.

    deepdiff paths start with "root" followed by a series of square bracket expressions
    fields and indices, e.g. `root['openshiftResources'][1]['version']`. the matching
    jsonpath expression looks like `openshiftResources.[1].version`
    """

    def build_jsonpath_part(element: str) -> jsonpath_ng.JSONPath:
        if element.isdigit():
            return jsonpath_ng.Index(int(element))
        else:
            return jsonpath_ng.Fields(element)

    path_parts = [
        build_jsonpath_part(p) for p in DEEP_DIFF_RE.findall(deep_diff_path[4:])
    ]
    return reduce(lambda a, b: a.child(b), path_parts)


@dataclass
class ChangeTypeProcessor:
    """
    The datasclass ChangeTypeProcessor wraps the generated GQL class ChangeType
    and adds functionality that operates close on the configuration of the
    ChangeType.
    """

    change_type: ChangeType

    def __post_init__(self):
        expressions_by_file_type_schema: dict[
            Tuple[BundleFileType, Optional[str]], list[jsonpath_ng.JSONPath]
        ] = defaultdict(list)
        for c in self.change_type.changes or []:
            if isinstance(c, ChangeTypeChangeDetectorJsonPathProviderV1):
                change_schema = c.change_schema or self.change_type.context_schema
                if change_schema:
                    for jsonpath_expression in c.json_path_selectors or []:
                        file_type = BundleFileType[
                            self.change_type.context_type.upper()
                        ]
                        expressions_by_file_type_schema[
                            (file_type, change_schema)
                        ].append(jsonpath_ng.ext.parse(jsonpath_expression))
            else:
                raise ValueError(
                    f"{c.provider} is not a supported change detection provider within ChangeTypes"
                )
        self.expressions_by_file_type_schema = expressions_by_file_type_schema

    def allowed_changed_paths(self, file_ref: FileRef, file_content: Any) -> list[str]:
        """
        find all paths within the provide file_content, that are covered by this
        ChangeType. the paths are represented as jsonpath expressions pinpointing
        the root element that can be changed
        """
        paths = []
        if (
            file_ref.file_type,
            file_ref.schema,
        ) in self.expressions_by_file_type_schema:
            for change_type_path_expression in self.expressions_by_file_type_schema[
                (file_ref.file_type, file_ref.schema)
            ]:
                paths.extend(
                    [
                        str(p.full_path)
                        for p in change_type_path_expression.find(file_content)
                    ]
                )
        return paths


@dataclass
class ChangeTypeContext:
    """
    A ChangeTypeContext represents a ChangeType in the context of its usage, e.g.
    bound to a RoleV1. The relevant part is not the role though, but the approvers
    defined in that context.

    ChangeTypeContext serves as a way to reason about changes outside within an
    arbitrary context, as long as it has a way to provide approvers.
    """

    change_type_processor: ChangeTypeProcessor
    context: str
    approvers: list[Approver]


def fetch_self_service_roles(gql_api: gql.GqlApi) -> list[RoleV1]:
    roles = self_service_roles.query(gql_api.query).roles or []
    return [r for r in roles if r and (r.self_service or r.owned_saas_files)]


def fetch_change_types(gql_api: gql.GqlApi) -> list[ChangeType]:
    change_type_list = change_types.query(gql_api.query).change_types or []
    return [ct for ct in change_type_list if ct]


def find_bundle_changes(comparison_sha: str) -> list[BundleFileChange]:
    changes = gql.get_diff(comparison_sha)
    return _parse_bundle_changes(changes)


def _parse_bundle_changes(bundle_changes) -> list[BundleFileChange]:
    change_list = [
        create_bundle_file_change(
            path=c.get("datafilepath"),
            schema=c.get("datafileschema"),
            file_type=BundleFileType.DATAFILE,
            old_file_content=c.get("old"),
            new_file_content=c.get("new"),
        )
        for c in bundle_changes["datafiles"].values()
    ]
    change_list.extend(
        [
            create_bundle_file_change(
                path=c.get("resourcepath"),
                schema=None,  # todo(goberlec): schema for res file?
                file_type=BundleFileType.RESOURCEFILE,
                old_file_content=c.get("old"),
                new_file_content=c.get("new"),
            )
            for c in bundle_changes["resources"].values()
        ]
    )
    return change_list


def cover_changes_with_self_service_roles(
    roles: list[RoleV1],
    change_types: list[ChangeType],
    bundle_changes: list[BundleFileChange],
    saas_file_owner_change_type_name: Optional[str] = None,
) -> None:
    # wrap changetypes
    change_type_processors = [ChangeTypeProcessor(ct) for ct in change_types]

    # role lookup enables fast lookup for (filetype, filepath, changetype-name) to a role
    role_lookup: dict[Tuple[BundleFileType, str, str], list[RoleV1]] = defaultdict(list)
    for r in roles:
        # build role lookup for owned_saas_files section of a role
        if saas_file_owner_change_type_name and r.owned_saas_files:
            for saas_file in r.owned_saas_files:
                if saas_file:
                    role_lookup[
                        (
                            BundleFileType.DATAFILE,
                            saas_file.path,
                            saas_file_owner_change_type_name,
                        )
                    ].append(r)

        # build role lookup for self_service section of a role
        if r.self_service:
            for ss in r.self_service:
                if ss and ss.datafiles:
                    for df in ss.datafiles:
                        if df:
                            role_lookup[
                                (BundleFileType.DATAFILE, df.path, ss.change_type.name)
                            ].append(r)
                if ss and ss.resources:
                    for res in ss.resources:
                        if res:
                            role_lookup[
                                (BundleFileType.RESOURCEFILE, res, ss.change_type.name)
                            ].append(r)

    for bc in bundle_changes:
        for ctp in change_type_processors:
            datafile_refs = extract_datafile_context_from_bundle_change(
                bc, ctp.change_type
            )
            for df_ref in datafile_refs:
                # if the context file is bound with the change type in
                # a role, build a changetypecontext
                for role in role_lookup[
                    (df_ref.file_type, df_ref.path, ctp.change_type.name)
                ]:
                    bc.cover_changes(
                        ChangeTypeContext(
                            change_type_processor=ctp,
                            context=f"RoleV1 - {role.name}",
                            approvers=[u for u in role.users or [] if u],
                        )
                    )


def cover_changes(
    changes: list[BundleFileChange],
    change_types: list[ChangeType],
    comparision_gql_api: gql.GqlApi,
    saas_file_owner_change_type_name: Optional[str] = None,
):
    # self service roles coverage
    roles = fetch_self_service_roles(comparision_gql_api)
    cover_changes_with_self_service_roles(
        bundle_changes=changes,
        change_types=change_types,
        roles=roles,
        saas_file_owner_change_type_name=saas_file_owner_change_type_name,
    )


def run(
    dry_run: bool,
    comparison_sha: str,
    saas_file_owner_change_type_name: Optional[str] = None,
):
    comparision_gql_api = gql.get_api_for_sha(
        comparison_sha, QONTRACT_INTEGRATION, validate_schemas=False
    )

    changes = find_bundle_changes(comparison_sha)
    change_types = fetch_change_types(comparision_gql_api)
    cover_changes(
        changes, change_types, comparision_gql_api, saas_file_owner_change_type_name
    )

    results = []
    for c in changes:
        for d in c.diffs:
            item = {
                "file": c.fileref.path,
                "schema": c.fileref.schema,
                "changed path": d.path,
                "old value": d.old,
                "new value": d.new,
            }
            if d.covered_by:
                item.update(
                    {
                        "change type": d.covered_by[
                            0
                        ].change_type_processor.change_type.name,
                        "context": d.covered_by[0].context,
                        "approvers": ", ".join(
                            [a.org_username for a in d.covered_by[0].approvers]
                        )[:20],
                    }
                )
            results.append(item)

    print_table(
        results,
        [
            "file",
            "changed path",
            "old value",
            "new value",
            "change type",
            "context",
            "approvers",
        ],
    )


def print_table(content, columns, table_format="simple"):
    headers = [column.upper() for column in columns]
    table_data = []
    for item in content:
        row_data = []
        for column in columns:
            cell = item
            for token in column.split("."):
                cell = cell.get(token) or {}
            if cell == {}:
                cell = ""
            if isinstance(cell, list):
                cell = "\n".join(cell)
            row_data.append(cell)
        table_data.append(row_data)

    print(tabulate(table_data, headers=headers, tablefmt=table_format))


# todo
# write docs
# write PR comment
# dedup code in create_bundle_file_change
