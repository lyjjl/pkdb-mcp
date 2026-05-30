"""Shared JSON typing aliases."""

from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | Mapping[str, Any] | Sequence[Any]
type JsonDict = dict[str, Any]
type MutableJsonMapping = MutableMapping[str, Any]
