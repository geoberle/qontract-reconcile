from __future__ import annotations
from abc import ABC, abstractmethod

from pydantic.dataclasses import dataclass
from pydantic.fields import FieldInfo
from enum import Enum
from typing import Any, Mapping, Optional, Type

from reconcile.gql_definitions.cna.queries.cna_resources import CNAssetV1


ASSET_ID_FIELD = "id"
ASSET_TYPE_FIELD = "asset_type"
ASSET_NAME_FIELD = "name"
ASSET_HREF_FIELD = "href"
ASSET_STATUS_FIELD = "status"
ASSET_PARAMETERS_FIELD = "parameters"


class AssetError(Exception):
    pass


class UnknownAssetTypeError(Exception):
    pass


class AssetType(str, Enum):
    NULL = "null"
    EXAMPLE_AWS_ASSUMEROLE = "example-aws-assumerole"
    AWS_RDS = "aws-rds"


def asset_type_by_id(asset_type_id: str) -> Optional[AssetType]:
    try:
        return AssetType(asset_type_id)
    except ValueError:
        return None


def asset_type_id_from_raw_asset(raw_asset: Mapping[str, Any]) -> Optional[str]:
    return raw_asset.get(ASSET_TYPE_FIELD)


def asset_type_from_raw_asset(raw_asset: Mapping[str, Any]) -> Optional[AssetType]:
    asset_type_id = asset_type_id_from_raw_asset(raw_asset)
    if asset_type_id:
        return asset_type_by_id(asset_type_id)
    else:
        return None


class AssetTypeVariableType(Enum):
    STRING = "${string}"
    NUMBER = "${number}"
    LIST_STRING = "${list(string)}"
    LIST_NUMBER = "${list(number)}"


@dataclass(frozen=True)
class AssetTypeVariable:
    name: str
    type: AssetTypeVariableType
    optional: bool = False
    default: Optional[str] = None


@dataclass
class AssetTypeMetadata:
    id: AssetType
    bindable: bool
    variables: set[AssetTypeVariable]


class AssetStatus(Enum):
    UNKNOWN = None
    READY = "Ready"
    TERMINATED = "Terminated"
    PENDING = "Pending"
    RUNNING = "Running"


class AssetModelConfig:
    allow_population_by_field_name = True


@dataclass(frozen=True, config=AssetModelConfig)
class Asset(ABC):
    name: str
    id: Optional[str]
    href: Optional[str]
    status: Optional[AssetStatus]

    @staticmethod
    def bindable() -> bool:
        return True

    @classmethod
    def type_metadata(cls) -> AssetTypeMetadata:
        return asset_type_metadata_from_asset_dataclass(cls)

    @staticmethod
    @abstractmethod
    def asset_type() -> AssetType:
        ...

    @staticmethod
    @abstractmethod
    def provider() -> str:
        ...

    @staticmethod
    @abstractmethod
    def from_query_class(asset: CNAssetV1) -> Asset:
        ...

    def asset_metadata(self) -> dict[str, Any]:
        return {
            ASSET_ID_FIELD: self.id,
            ASSET_HREF_FIELD: self.href,
            ASSET_STATUS_FIELD: self.status.value if self.status else None,
            ASSET_NAME_FIELD: self.name,
            ASSET_TYPE_FIELD: self.asset_type().value,
        }

    def api_payload(self) -> dict[str, Any]:
        return {
            ASSET_TYPE_FIELD: self.asset_type().value,
            ASSET_NAME_FIELD: self.name,
            ASSET_PARAMETERS_FIELD: self.raw_asset_parameters(omit_empty=False),
        }

    def raw_asset_parameters(self, omit_empty: bool) -> dict[str, Any]:
        raw_asset_params = {}
        for var in self.type_metadata().variables:
            python_property_name = _property_for_asset_parameter_alias(
                type(self), var.name
            )
            var_value = getattr(self, python_property_name)
            if not var.optional and var_value is None:
                raise AssetError(
                    f"Required variable {var.name} not set for asset {self.name}"
                )
            if var_value is not None or not omit_empty:
                raw_asset_params[var.name] = var_value
        return raw_asset_params

    def update_from(
        self,
        asset: Asset,
    ) -> Asset:
        assert isinstance(asset, type(self))
        return type(asset)(
            id=self.id,
            href=self.href,
            status=self.status,
            name=self.name,
            **asset.asset_properties(),
        )

    def asset_properties(self) -> dict[str, Any]:
        return {p: getattr(self, p) for p in self.__annotations__.keys()}

    @staticmethod
    def from_api_mapping(
        raw_asset: Mapping[str, Any],
        cna_dataclass: Type[Asset],
    ) -> Asset:
        params = {}
        raw_asset_params = raw_asset.get(ASSET_PARAMETERS_FIELD) or {}
        for var in cna_dataclass.type_metadata().variables:
            var_value = raw_asset_params.get(var.name)
            if not var.optional and not var_value:
                raise AssetError(
                    f"Inconsistent asset from CNA API {raw_asset}: required parameter {var.name} is missing in CNA"
                )
            property_name = _property_for_asset_parameter_alias(cna_dataclass, var.name)
            params[property_name] = var_value

        return cna_dataclass(
            id=raw_asset.get(ASSET_ID_FIELD),
            href=raw_asset.get(ASSET_HREF_FIELD),
            status=AssetStatus(raw_asset.get(ASSET_STATUS_FIELD)),
            name=raw_asset.get(ASSET_NAME_FIELD, ""),
            **params,
        )


def asset_type_metadata_from_asset_dataclass(
    asset_dataclass: Type[Asset],
) -> AssetTypeMetadata:
    variables = {
        _asset_type_metadata_variable_from_type_annotation(
            property_name, type_hint, getattr(asset_dataclass, property_name)
        )
        for property_name, type_hint in asset_dataclass.__annotations__.items()
    }
    return AssetTypeMetadata(
        id=asset_dataclass.asset_type(),
        bindable=asset_dataclass.bindable(),
        variables=variables,
    )


def _asset_type_metadata_variable_from_type_annotation(
    property_name: str,
    type_hint: str,
    field_info: FieldInfo,
) -> AssetTypeVariable:
    optional = type_hint.startswith("Optional[")
    if type_hint == "str" or type_hint.endswith("[str]"):
        asset_type = AssetTypeVariableType.STRING
    elif type_hint == "int" or type_hint.endswith("[int]"):
        asset_type = AssetTypeVariableType.NUMBER
    else:
        raise AssetError(f"Unsupported type hint {type_hint} for {property_name}")
        # TODO handle list types
    return AssetTypeVariable(
        name=field_info.alias or property_name,
        optional=optional,
        type=asset_type,
    )


def _property_for_asset_parameter_alias(cna_dataclass: Type[Asset], alias: str) -> str:
    for property_name in cna_dataclass.__annotations__.keys():
        if alias in (getattr(cna_dataclass, property_name).alias, property_name):
            return property_name
    raise AssetError(f"Cannot find property for alias {alias} in {cna_dataclass}")