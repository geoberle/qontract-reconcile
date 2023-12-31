from collections.abc import Collection, Iterable, Mapping
from typing import Any

from reconcile import queries


def get_aws_accounts(
    include_accounts: Collection[str], exclude_accounts: Collection[str]
) -> list[Mapping[str, Any]]:
    accounts = queries.get_aws_accounts(terraform_state=True)
    if not include_accounts and exclude_accounts:
        excluding = filter_accounts_by_name(accounts, exclude_accounts)
        validate_account_names(excluding, exclude_accounts)
        accounts = exclude_accounts_by_name(accounts, exclude_accounts)
        if len(accounts) == 0:
            raise ValueError("You have excluded all aws accounts, verify your input")
    elif include_accounts:
        accounts = filter_accounts_by_name(accounts, include_accounts)
        validate_account_names(accounts, include_accounts)
    return accounts


def filter_accounts_by_name(
    accounts: Iterable[Mapping[str, Any]], filter: Iterable[str]
) -> Collection[Mapping[str, Any]]:
    return [ac for ac in accounts if ac["name"] in filter]


def exclude_accounts_by_name(
    accounts: Iterable[Mapping[str, Any]], filter: Iterable[str]
) -> Collection[Mapping[str, Any]]:
    return [ac for ac in accounts if ac["name"] not in filter]


def validate_account_names(
    accounts: Collection[Mapping[str, Any]], names: Collection[str]
) -> None:
    if len(accounts) != len(names):
        missing_names = set(names) - {a["name"] for a in accounts}
        raise ValueError(
            f"Accounts {missing_names} were provided as arguments, but not found in app-interface. Check your input for typos or for missing AWS account definitions."
        )
