from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import (
    Any,
    Optional,
    Protocol,
    Tuple,
)

from reconcile.utils.gql import get_diff


class BundleFileType(Enum):
    DATAFILE = "datafile"
    RESOURCEFILE = "resourcefile"


@dataclass(frozen=True)
class FileRef:
    file_type: BundleFileType
    path: str
    schema: Optional[str]

    def __str__(self) -> str:
        return f"{self.file_type.value}:{self.path}"


class FileDiffResolver(Protocol):
    @abstractmethod
    def lookup_file_diff(
        self, file_ref: FileRef
    ) -> Tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
        ...


@dataclass
class QontractServerFileDiffResolver:
    comparison_sha: str

    def lookup_file_diff(
        self, file_ref: FileRef
    ) -> Tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
        data = get_diff(
            old_sha=self.comparison_sha,
            file_type=file_ref.file_type.value,
            file_path=file_ref.path,
        )
        return data["old"], data["new"]


class NoOpFileDiffResolver:
    def lookup_file_diff(
        self, file_ref: FileRef
    ) -> Tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
        raise Exception(
            "NoOpFileDiffResolver is not supposed to be used in "
            "runtime contexts where lookups are needed"
        )
