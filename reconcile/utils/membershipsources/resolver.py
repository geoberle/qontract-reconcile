from collections.abc import (
    Iterable,
    Sequence,
)
from dataclasses import dataclass

from sretoolbox.utils import threaded

from reconcile.gql_definitions.fragments.membership_source import (
    AppInterfaceMembershipProviderSourceV1,
    MembershipProviderSourceV1,
    MembershipProviderV1,
)
from reconcile.utils.membershipsources.app_interface_resolver import (
    resolve_app_interface_membership_source,
)
from reconcile.utils.membershipsources.models import (
    ProviderResolver,
    RoleBot,
    RoleMember,
    RoleUser,
    RoleWithMemberships,
)


@dataclass
class GroupResolverJob:
    provider: MembershipProviderV1
    groups: set[str]


def build_resolver_jobs(
    roles: Sequence[RoleWithMemberships],
) -> Iterable[GroupResolverJob]:
    """
    Bundles groups to resolve by provider so that they can be resolved
    in batches.
    """
    resolver_jobs: dict[str, GroupResolverJob] = {}
    for r in roles:
        for ms in r.member_sources or []:
            job = resolver_jobs.get(ms.provider.name)
            if not job:
                job = GroupResolverJob(provider=ms.provider, groups=set())
                resolver_jobs[ms.provider.name] = job
            job.groups.add(ms.group)
    return resolver_jobs.values()


ProviderGroup = tuple[str, str]


def get_resolver_for_provider_source(
    source: MembershipProviderSourceV1,
) -> ProviderResolver:
    match source:
        case AppInterfaceMembershipProviderSourceV1():
            return resolve_app_interface_membership_source
        case _:
            raise ValueError(
                "No resolver available for membership provider source",
                type(source),
            )


def resolve_groups(job: GroupResolverJob) -> dict[ProviderGroup, list[RoleMember]]:
    """
    Resolves groups and returns a dict with group name as key and a list
    of members as value.
    """
    resolver = get_resolver_for_provider_source(job.provider.source)
    return resolver(job.provider.name, job.provider.source, job.groups)


def resolve_role_members(
    roles: Sequence[RoleWithMemberships], thread_pool: int = 5
) -> dict[str, list[RoleMember]]:
    """
    Resolves members of roles, combining local members and the ones from
    membership sources.
    """
    resolver_jobs = build_resolver_jobs(roles)
    processed_jobs: Iterable[dict[ProviderGroup, list[RoleMember]]] = threaded.run(
        func=resolve_groups,
        iterable=resolver_jobs,
        thread_pool_size=thread_pool,
    )
    resolved_groups = {}
    for d in processed_jobs:
        resolved_groups.update(d)

    members_by_group = {}
    for r in roles:
        members: list[RoleMember] = []

        # bring in the local users and bots ...
        members.extend([RoleUser(**u.dict()) for u in r.users or []])
        members.extend([RoleBot(**b.dict()) for b in r.bots or [] if b.org_username])

        # ... and enhance with the ones from member sources
        for ms in r.member_sources or []:
            members.extend(resolved_groups.get((ms.provider.name, ms.group), []))

        members_by_group[r.name] = members

    return members_by_group
