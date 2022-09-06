from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Protocol, Tuple
import re
from functools import reduce

from reconcile.utils import gql

from reconcile.gql_definitions.change_owners.fragments.change_type import (
    ChangeType,
)
from reconcile.gql_definitions.change_owners.queries.self_service_roles import RoleV1
from reconcile.gql_definitions.change_owners.queries import (
    self_service_roles,
    change_types,
)

from deepdiff import DeepDiff
from deepdiff.helper import CannotCompare

import jsonpath_ng
import jsonpath_ng.ext


QONTRACT_INTEGRATION = "change-owners"


class BundleFileType(Enum):
    DATAFILE = 1
    RESOURCEFILE = 2


@dataclass(frozen=True)
class FileRef:
    file_type: BundleFileType
    path: str
    schema: Optional[str]


@dataclass
class Diff:
    path: jsonpath_ng.JSONPath
    diff_type: str  # e.g. added, changed
    old: Optional[Any]
    new: Optional[Any]
    covered_by: list["ChangeTypeContext"]


@dataclass
class BundleFileChange:
    fileref: FileRef
    old: Optional[dict[str, Any]]
    new: Optional[dict[str, Any]]
    diffs: list[Diff]


def compare_ctx_identifier(x: Any, y: Any):
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
    old: Optional[dict[str, Any]],
    new: Optional[dict[str, Any]],
) -> BundleFileChange:
    fileref = FileRef(path=path, schema=schema, file_type=file_type)
    diffs: list[Diff] = []
    if old and new:
        deep_diff = DeepDiff(
            old, new, ignore_order=True, iterable_compare_func=compare_ctx_identifier
        )
        # handle changed values
        diffs.extend(
            [
                Diff(
                    path=deep_diff_path_to_jsonpath(path),
                    diff_type="changed",
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
                    diff_type="added",
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
                    diff_type="removed",
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
                    diff_type="added",
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
                    diff_type="removed",
                    old=change,
                    new=None,
                    covered_by=[],
                )
                for path, change in deep_diff.get("iterable_item_removed", {}).items()
            ]
        )
    return BundleFileChange(fileref=fileref, old=old, new=new, diffs=diffs)


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
    change_type: ChangeType

    def __post_init__(self):
        expressions_by_schema: dict[str, list[jsonpath_ng.JSONPath]] = defaultdict(list)
        for c in self.change_type.changes or []:
            change_schema = c.change_schema or self.change_type.context_schema
            for jsonpath_expression in c.json_path_selectors or []:
                expressions_by_schema[change_schema].append(
                    jsonpath_ng.ext.parse(jsonpath_expression)
                )
        self.expressions_by_schema = expressions_by_schema

    def allowed_changed_paths(self, bundle_change: BundleFileChange) -> list[str]:
        paths = []
        if bundle_change.fileref.schema in self.expressions_by_schema:
            for change_type_path_expression in self.expressions_by_schema[
                bundle_change.fileref.schema
            ]:
                # todo(goberlec) only new??
                paths.extend(
                    [
                        str(p.full_path)
                        for p in change_type_path_expression.find(bundle_change.new)
                    ]
                )
        return paths


@dataclass
class ChangeTypeContext:
    change_type_processor: ChangeTypeProcessor
    context_type: str
    context: str
    approvers: list[Approver]

    def cover_changes(self, bundle_change: BundleFileChange):
        for allowed_path in self.change_type_processor.allowed_changed_paths(
            bundle_change
        ):
            for diff in bundle_change.diffs:
                covered = str(diff.path).startswith(allowed_path)
                if covered:
                    diff.covered_by.append(self)


# for the regular context it is easy - we can decide upfront when to create a context object
# because the owned objects are listed next to the change type and we know what changed in the bundle

# for the change types with a context selector, it is harder because we would need to inspect
# changed objects upfront (e.g. a user) and extract the owning objects (e.g. the role) - and then
# we need to keep searching if that changetype is combined with one of those owning objects. and then,
# we can create the context object.
#
# is this bad? not necessarily. most of the time not many files change in an MR
#
# walkthrough - so we see a user file changed. we look through our change types if any has a
# change with a changeSchema == /access/user-1.yml. if we found one we inspect the contextSelector
# and see what it matches on, e.g. it matches on adding a role. this role is now are context. lets
# a look if this role is assigned somehow to this changetype and by which approvers


def fetch_self_service_roles(gql_api: gql.GqlApi) -> list[RoleV1]:
    roles = self_service_roles.query(gql_api.query).roles or []
    return [r for r in roles if r and r.self_service]


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
            old=c.get("old"),
            new=c.get("new"),
        )
        for c in bundle_changes["datafiles"].values()
    ]
    change_list.extend(
        [
            create_bundle_file_change(
                path=c.get("resourcepath"),
                schema=None,  # todo(goberlec): schema for res file?
                file_type=BundleFileType.RESOURCEFILE,
                old=c.get("old"),
                new=c.get("new"),
            )
            for c in bundle_changes["resources"].values()
        ]
    )
    return change_list


def build_change_type_contexts_from_self_service_roles(
    roles: list[RoleV1],
    change_types: list[ChangeType],
    bundle_changes: list[BundleFileChange],
) -> dict[FileRef, list[ChangeTypeContext]]:
    # wrap changetypes
    change_type_processors = [ChangeTypeProcessor(ct) for ct in change_types]

    # role lookup enables fast lookup for (filetype, filepath, changetype-name)
    role_lookup: dict[Tuple[BundleFileType, str, str], list[RoleV1]] = defaultdict(list)
    for r in roles:
        if not r.self_service:
            continue
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

    change_type_contexts: dict[FileRef, list[ChangeTypeContext]] = defaultdict(list)
    for bc in bundle_changes:
        for ctp in change_type_processors:
            context_files = extract_datafile_context_from_bundle_change(
                bc, ctp.change_type
            )
            for cf in context_files:
                # if the context file is bound with the change type in
                # a role, build a changetypecontext
                for role in role_lookup[(cf.file_type, cf.path, ctp.change_type.name)]:
                    change_type_contexts[bc.fileref].append(
                        ChangeTypeContext(
                            change_type_processor=ctp,
                            context_type="RoleV1",
                            context=role.name,
                            approvers=[u for u in role.users or [] if u],
                        )
                    )

    return change_type_contexts


def build_change_type_contexts(
    changes: list[BundleFileChange],
    change_types: list[ChangeType],
    comparision_gql_api: gql.GqlApi,
):
    contexts = build_change_type_contexts_from_self_service_roles(
        bundle_changes=changes,
        change_types=change_types,
        roles=fetch_self_service_roles(comparision_gql_api),
    )
    # add more contexts from other places, e.g.
    # - build_change_type_contexts_for_user_file_self_service()
    #  ...
    return contexts


def cover_changes(
    changes: list[BundleFileChange],
    change_types: list[ChangeType],
    comparision_gql_api: gql.GqlApi,
):
    contexts = build_change_type_contexts(changes, change_types, comparision_gql_api)
    for c in changes:
        if c.fileref in contexts:
            for ctx in contexts[c.fileref]:
                ctx.cover_changes(c)


def run(dry_run: bool, comparison_sha: str):
    comparision_gql_api = gql.get_api_for_sha(
        comparison_sha, QONTRACT_INTEGRATION, validate_schemas=False
    )

    changes = find_bundle_changes(comparison_sha)
    change_types = fetch_change_types(comparision_gql_api)
    cover_changes(changes, change_types, comparision_gql_api)

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
                        "covered": "yes" if d.covered_by else "no",
                        "change type": d.covered_by[
                            0
                        ].change_type_processor.change_type.name,
                        "context": f"{d.covered_by[0].context_type} - {d.covered_by[0].context}",
                        "approvers": ", ".join(
                            [a.org_username for a in d.covered_by[0].approvers]
                        )[:20],
                    }
                )
            else:
                item["covered"] = "no"
            results.append(item)

    from tools.qontract_cli import print_table

    print_table(
        results,
        [
            "file",
            "changed path",
            "old value",
            "new value",
            "covered",
            "change type",
            "context",
            "approvers",
        ],
    )
    # process the contexts to eliminate document parts that are covered by
    # the change type

    # then do another diff on all changes, if no diffs remain, the PR can be self
    # serviced by the approvers in the contexts
