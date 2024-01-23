import dataclasses
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import Enum
from json import JSONEncoder
from typing import Any

import boto3
from pydantic import BaseModel, parse_obj_as

from reconcile.external_resources.model import ExternalResourceKey, Reconciliation
from reconcile.utils.state import State

DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class StateNotFoundError(Exception):
    pass


class ReconcileStatus(str, Enum):
    SUCCESS: str = "SUCCESS"
    ERROR: str = "ERROR"
    IN_PROGRESS: str = "IN_PROGRESS"
    NOT_EXISTS: str = "NOT_EXISTS"


class ResourceStatus(str, Enum):
    CREATED: str = "CREATED"
    DELETED: str = "DELETED"
    ABANDONED: str = "ABANDONED"
    NOT_EXISTS: str = "NOT_EXISTS"
    IN_PROGRESS: str = "IN_PROGRESS"
    DELETE_IN_PROGRESS: str = "DELETE_IN_PROGRESS"
    ERROR: str = "ERROR"


class ExternalResourceState(BaseModel):
    key: ExternalResourceKey
    ts: datetime
    resource_status: ResourceStatus
    resource_digest: str = ""
    reconciliation: Reconciliation


class EnhancedJsonEncoder(JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif dataclasses.is_dataclass(obj):
            return dataclasses.asdict(obj)


class ExternalResourcesStateManager:
    def __init__(self, state: State, index_file_key: str):
        self.state = state
        self.index_file_key = index_file_key

        try:
            data = self.state[self.index_file_key]
            states_list = parse_obj_as(list[ExternalResourceState], data)
            self.index: dict[ExternalResourceKey, ExternalResourceState] = {
                item.key: item for item in states_list
            }
        except Exception:
            logging.info("No state file, creating a new one.")
            self.index = {}

    def _write_index_file(
        self,
    ) -> None:
        data = [item.dict() for item in self.index.values()]
        self.state[self.index_file_key] = data

    def get_external_resource_state(
        self, key: ExternalResourceKey
    ) -> ExternalResourceState:
        obj = self.index.get(
            key,
            ExternalResourceState(
                key=key,
                ts=datetime.now(timezone.utc),
                resource_status=ResourceStatus.NOT_EXISTS,
                reconciliation=Reconciliation(key=key),
            ),
        )
        return obj

    def set_external_resource_state(
        self,
        key: ExternalResourceKey,
        state: ExternalResourceState,
    ) -> None:
        self.index[key] = state

    def del_external_resource_state(self, key: ExternalResourceKey) -> None:
        del self.index[key]

    def get_all_resource_keys(self) -> list[ExternalResourceKey]:
        return list[ExternalResourceKey](self.index.keys())

    def save_state(self) -> None:
        self._write_index_file()
        # self._write_external_resource_states()


class DynamoDBStateAdapater:
    KEY_PROVISION_PROVIDER = "key.provision_provider"
    KEY_PROVISIONER_NAME = "key.provisioner_name"
    KEY_PROVIDER = "key.provider"
    KEY_IDENTIFIER = "key.identifier"
    RECONCILIATION_RESOURCE_DIGEST = "reconcilitation.resource_digest"
    RECONCILIATION_IMAGE = "reconciliation.image"
    RECONCILIATION_INPUT = "reconciliation.input"
    RECONCILIATION_ACTION = "reconciliation.action"
    RESOURCE_KEY = "resource_key"
    RESOURCE_STATUS = "resource_status"
    RESOURCE_DIGEST = "resource_digest"
    TIMESTAMP = "ts"

    def _get_value(self, item: Mapping[str, Any], key: str, _type: str = "S") -> Any:
        return item[key][_type]

    def _item_has_reconcilitation(self, item: Mapping[str, Any]) -> bool:
        # Just check if one of the reconcilitation attributes exists
        return DynamoDBStateAdapater.RECONCILIATION_ACTION in item

    def deserialize(self, item: Mapping[str, Any]) -> ExternalResourceState:
        key = ExternalResourceKey(
            provision_provider=self._get_value(item, self.KEY_PROVISION_PROVIDER),
            provisioner_name=self._get_value(item, self.KEY_PROVISION_PROVIDER),
            provider=self._get_value(item, self.KEY_PROVIDER),
            identifier=self._get_value(item, self.KEY_IDENTIFIER),
        )
        if self._item_has_reconcilitation(item):
            r = Reconciliation(
                key=key,
                resource_digest=self._get_value(
                    item, self.RECONCILIATION_RESOURCE_DIGEST
                ),
                image=self._get_value(item, self.RECONCILIATION_IMAGE),
                input=self._get_value(item, self.RECONCILIATION_INPUT),
                action=self._get_value(item, self.RECONCILIATION_ACTION),
            )
        else:
            r = Reconciliation(key=key)
        return ExternalResourceState(
            key=key,
            ts=self._get_value(item, self.TIMESTAMP),
            resource_digest=self._get_value(item, self.RESOURCE_DIGEST),
            resource_status=self._get_value(item, self.RESOURCE_STATUS),
            reconciliation=r,
        )

    def serialize(self, state: ExternalResourceState) -> dict[str, Any]:
        return {
            "resource_key": {"S": state.key.digest()},
            "key.provision_provider": {"S": state.key.provision_provider},
            "key.provisioner_name": {"S": state.key.provisioner_name},
            "key.provider": {"S": state.key.provider},
            "key.identifier": {"S": state.key.identifier},
            "ts": {"S": state.ts.isoformat()},
            "resource_status": {"S": state.resource_status.value},
            "resource_digest": {"S": state.resource_digest},
            "reconciliation.resource_digest": {
                "S": state.reconciliation.resource_digest
            },
            "reconciliation.image": {"S": state.reconciliation.image},
            "reconciliation.input": {"S": state.reconciliation.input},
            "reconciliation.action": {"S": state.reconciliation.action.value},
        }


class ExternalResourcesStateDynamoDB:
    def __init__(self) -> None:
        self.adapter = DynamoDBStateAdapater()
        self.client = boto3.client("dynamodb", region_name="us-east-1")
        self._table = "external-resources-test"
        self._index_name = "resources_index"
        self.partial_resources = self._get_all_resources_by_index()

    def get_external_resource_state(
        self, key: ExternalResourceKey
    ) -> ExternalResourceState:
        data = self.client.get_item(
            TableName=self._table,
            ConsistentRead=True,
            Key={self.adapter.RESOURCE_KEY: {"S": key.digest()}},
        )
        if "Item" in data:
            return self.adapter.deserialize(data["Item"])
        else:
            return ExternalResourceState(
                key=key,
                ts=datetime.now(timezone.utc),
                resource_status=ResourceStatus.NOT_EXISTS,
                reconciliation=Reconciliation(key=key),
            )

    def set_external_resource_state(
        self,
        state: ExternalResourceState,
    ) -> None:
        self.client.put_item(TableName=self._table, Item=self.adapter.serialize(state))

    def del_external_resource_state(self, key: ExternalResourceKey) -> None:
        self.client.delete_item(
            TableName=self._table,
            Key={self.adapter.RESOURCE_KEY: {"S": key.digest()}},
        )

    def _get_all_resources_by_index(
        self,
    ) -> dict[ExternalResourceKey, ExternalResourceState]:
        # TODO: Need to implement pagination if this goes further
        # than 1Mb per response
        logging.info("Getting all Resources from DynamoDb")
        partials = {}
        for item in self.client.scan(
            TableName=self._table, IndexName=self._index_name
        ).get("Items", []):
            s = self.adapter.deserialize(item)
            partials[s.key] = s
        return partials

    def get_all_resource_keys(self) -> list[ExternalResourceKey]:
        return [k for k in self.partial_resources.keys()]

    def update_resource_status(
        self, key: ExternalResourceKey, status: ResourceStatus
    ) -> None:
        self.client.update_item(
            TableName=self._table,
            Key={self.adapter.RESOURCE_KEY: {"S": key.digest()}},
            UpdateExpression="set resource_status=:new_value",
            ExpressionAttributeValues={":new_value": {"S": status.value}},
            ReturnValues="UPDATED_NEW",
        )
