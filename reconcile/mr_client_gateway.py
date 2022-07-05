from typing import Any
from reconcile import queries

from reconcile.utils.sqs_gateway import SQSGateway
from reconcile.utils.gitlab_api import GitLabApi


class MRClientGatewayError(Exception):
    """
    Used when an error happens in the MR Client Gateway initialization.
    """


def init(gitlab_project_id=None, sqs_or_gitlab=None, settings=None):
    """
    Creates the Merge Request client to of a given type.

    :param gitlab_project_id: used when the client type is 'gitlab'
    :param sqs_or_gitlab: 'gitlab' or 'sqs'
    :return: an instance of the selected MR client.
    """
    if not settings:
        settings = queries.get_app_interface_settings()

    if sqs_or_gitlab is None:
        client_type = settings.get("mergeRequestGateway", "gitlab")
    else:
        client_type = sqs_or_gitlab

    if client_type == "gitlab":
        if gitlab_project_id is None:
            raise MRClientGatewayError('Missing "gitlab_project_id".')

        instance = queries.get_gitlab_instance()

        return GitLabApi(
            instance,
            project_id=gitlab_project_id,
            settings=settings,
        )

    elif client_type == "sqs":
        accounts = queries.get_queue_aws_accounts()

        return SQSGateway(accounts, settings=settings)

    else:
        raise MRClientGatewayError(f"Invalid client type: {client_type}")
