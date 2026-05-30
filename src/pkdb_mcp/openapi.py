"""OpenAPI/Swagger loading and normalization.

The public PK-DB schema is produced by drf-yasg, which usually emits Swagger 2.0.
This module also accepts OpenAPI 3.x so the MCP layer remains stable if PK-DB upgrades
its schema generator later.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from pkdb_mcp.errors import OpenAPILoadError, OpenAPIParseError, OperationNotFoundError
from pkdb_mcp.settings import Settings
from pkdb_mcp.types import JsonDict

_HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}
_IDENTIFIER_RE = re.compile(r"[^0-9a-zA-Z_]+")
_PATH_PARAM_RE = re.compile(r"{([^{}]+)}")


@dataclass(frozen=True, slots=True)
class OperationParameter:
    """Normalized OpenAPI parameter metadata."""

    name: str
    location: str
    required: bool = False
    description: str = ""
    schema: JsonDict = field(default_factory=dict)
    py_name: str = ""

    def __post_init__(self) -> None:
        if not self.py_name:
            object.__setattr__(self, "py_name", to_identifier(self.name))

    def compact(self) -> JsonDict:
        """Return a compact agent-readable representation."""

        return {
            "name": self.name,
            "argument": self.py_name,
            "in": self.location,
            "required": self.required,
            "description": self.description,
            "schema": self.schema,
        }


@dataclass(frozen=True, slots=True)
class Operation:
    """Normalized OpenAPI operation."""

    operation_id: str
    tool_name: str
    method: str
    path: str
    summary: str = ""
    description: str = ""
    tags: tuple[str, ...] = ()
    parameters: tuple[OperationParameter, ...] = ()
    request_body: JsonDict | None = None
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    @property
    def brief(self) -> str:
        """Return the shortest useful human-readable description."""

        return self.summary or self.description or f"{self.method.upper()} {self.path}"

    def compact(self) -> JsonDict:
        """Return a compact representation for MCP helper tools."""

        return {
            "operation_id": self.operation_id,
            "tool_name": self.tool_name,
            "method": self.method.upper(),
            "path": self.path,
            "summary": self.summary,
            "tags": list(self.tags),
            "parameters": [parameter.compact() for parameter in self.parameters],
            "has_request_body": self.request_body is not None,
        }


@dataclass(slots=True)
class OpenAPICatalog:
    """Normalized operation catalog."""

    title: str
    version: str
    raw: JsonDict
    operations: tuple[Operation, ...]

    @property
    def by_operation_id(self) -> dict[str, Operation]:
        return {operation.operation_id: operation for operation in self.operations}

    @property
    def by_tool_name(self) -> dict[str, Operation]:
        return {operation.tool_name: operation for operation in self.operations}

    def get(self, name_or_id: str) -> Operation:
        """Find an operation by operation ID or MCP tool name."""

        if name_or_id in self.by_operation_id:
            return self.by_operation_id[name_or_id]
        if name_or_id in self.by_tool_name:
            return self.by_tool_name[name_or_id]
        msg = f"Unknown PK-DB operation {name_or_id!r}."
        raise OperationNotFoundError(msg)

    def compact(self) -> JsonDict:
        """Return compact catalog metadata for agents."""

        return {
            "title": self.title,
            "version": self.version,
            "operation_count": len(self.operations),
            "operations": [operation.compact() for operation in self.operations],
        }


def to_identifier(value: str) -> str:
    """Normalize an API name into a valid Python/MCP snake_case identifier."""

    cleaned = _IDENTIFIER_RE.sub("_", value.replace("-", "_").replace(".", "_")).strip("_")
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", cleaned).lower()
    if not snake:
        snake = "value"
    if snake[0].isdigit():
        snake = f"value_{snake}"
    if snake in {"from", "class", "pass", "global", "lambda", "async", "await", "in"}:
        snake = f"{snake}_"
    return snake


def tool_name_for(operation_id: str) -> str:
    """Return the MCP tool name for an operation ID."""

    normalized = to_identifier(operation_id)
    return normalized if normalized.startswith("pkdb_") else f"pkdb_{normalized}"


def load_spec(settings: Settings) -> JsonDict:
    """Load a Swagger/OpenAPI document from PK-DB, optionally falling back to a bundle."""

    try:
        with httpx.Client(
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"Accept": "application/json", "User-Agent": settings.user_agent},
        ) as client:
            response = client.get(settings.openapi_url_str)
            response.raise_for_status()
            return _decode_spec_bytes(response.content, response.headers.get("content-type", ""))
    except Exception as exc:
        if not settings.use_fallback_spec:
            msg = f"Could not load live PK-DB OpenAPI schema from {settings.openapi_url_str}."
            raise OpenAPILoadError(msg) from exc
        return load_spec_file(settings.fallback_spec_path)


def load_spec_file(path: Path) -> JsonDict:
    """Load an OpenAPI document from a local JSON or YAML file."""

    try:
        raw = path.read_bytes()
    except OSError as exc:
        msg = f"Could not read OpenAPI fallback spec at {path}."
        raise OpenAPILoadError(msg) from exc
    return _decode_spec_bytes(raw, path.suffix)


def _decode_spec_bytes(raw: bytes, hint: str) -> JsonDict:
    text = raw.decode("utf-8")
    try:
        if "yaml" in hint or hint.endswith(('.yaml', '.yml')):
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
    except Exception as exc:
        msg = "OpenAPI document is not valid JSON/YAML."
        raise OpenAPIParseError(msg) from exc
    if not isinstance(data, dict):
        msg = "OpenAPI document root must be an object."
        raise OpenAPIParseError(msg)
    return data


def parse_catalog(spec: JsonDict) -> OpenAPICatalog:
    """Parse a Swagger 2.0 or OpenAPI 3.x document into a normalized catalog."""

    info = spec.get("info", {})
    if not isinstance(info, dict):
        info = {}

    raw_paths = spec.get("paths")
    if not isinstance(raw_paths, dict):
        msg = "OpenAPI document has no paths object."
        raise OpenAPIParseError(msg)

    operations: list[Operation] = []
    seen_tool_names: set[str] = set()
    for path, path_item in sorted(raw_paths.items()):
        if not isinstance(path_item, dict):
            continue
        inherited_parameters = _parse_parameters(path_item.get("parameters", []))
        for method, operation_doc in sorted(path_item.items()):
            if method.lower() not in _HTTP_METHODS or not isinstance(operation_doc, dict):
                continue
            operation = _parse_operation(
                spec=spec,
                path=path,
                method=method.lower(),
                operation_doc=operation_doc,
                inherited_parameters=inherited_parameters,
                seen_tool_names=seen_tool_names,
            )
            operations.append(operation)

    return OpenAPICatalog(
        title=str(info.get("title") or "PK-DB REST API"),
        version=str(info.get("version") or info.get("default_version") or "unknown"),
        raw=spec,
        operations=tuple(operations),
    )


def _parse_operation(
    *,
    spec: JsonDict,
    path: str,
    method: str,
    operation_doc: JsonDict,
    inherited_parameters: tuple[OperationParameter, ...],
    seen_tool_names: set[str],
) -> Operation:
    raw_operation_id = str(operation_doc.get("operationId") or _derive_operation_id(method, path))
    operation_id = to_identifier(raw_operation_id)
    tool_name = _dedupe_name(tool_name_for(operation_id), seen_tool_names)
    parameters = [*inherited_parameters, *_parse_parameters(operation_doc.get("parameters", []))]
    request_body = _parse_request_body(operation_doc)

    # Swagger 2.0 sometimes models body/formData only as parameters.
    if request_body is None:
        body_params = [parameter for parameter in parameters if parameter.location in {"body", "formData"}]
        if body_params:
            request_body = {
                "content": {
                    "application/json": {
                        "schema": body_params[0].schema if len(body_params) == 1 else {"type": "object"}
                    }
                }
            }

    return Operation(
        operation_id=operation_id,
        tool_name=tool_name,
        method=method,
        path=path,
        summary=str(operation_doc.get("summary") or ""),
        description=str(operation_doc.get("description") or ""),
        tags=tuple(str(tag) for tag in operation_doc.get("tags", []) if tag),
        parameters=tuple(parameters),
        request_body=request_body,
        consumes=tuple(_as_string_list(operation_doc.get("consumes") or spec.get("consumes") or [])),
        produces=tuple(_as_string_list(operation_doc.get("produces") or spec.get("produces") or [])),
    )


def _parse_parameters(raw_parameters: Any) -> tuple[OperationParameter, ...]:
    if not isinstance(raw_parameters, list):
        return ()
    parameters: list[OperationParameter] = []
    used_py_names: set[str] = set()
    for item in raw_parameters:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "value")
        py_name = _dedupe_name(to_identifier(name), used_py_names)
        schema = item.get("schema")
        if not isinstance(schema, dict):
            schema = {key: item[key] for key in ("type", "format", "enum", "items") if key in item}
        parameters.append(
            OperationParameter(
                name=name,
                py_name=py_name,
                location=str(item.get("in") or "query"),
                required=bool(item.get("required", False)),
                description=str(item.get("description") or ""),
                schema=schema,
            )
        )
    return tuple(parameters)


def _parse_request_body(operation_doc: JsonDict) -> JsonDict | None:
    request_body = operation_doc.get("requestBody")
    return request_body if isinstance(request_body, dict) else None


def _derive_operation_id(method: str, path: str) -> str:
    path_bits = [bit for bit in path.strip("/").split("/") if bit]
    normalized_bits = [bit.strip("{}").replace("-", "_") for bit in path_bits]
    return "_".join([method, *normalized_bits])


def _dedupe_name(name: str, seen: set[str]) -> str:
    candidate = name
    index = 2
    while candidate in seen:
        candidate = f"{name}_{index}"
        index += 1
    seen.add(candidate)
    return candidate


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    return []


def substitute_path_parameters(path: str, arguments: dict[str, Any], operation: Operation) -> str:
    """Substitute OpenAPI path placeholders using normalized argument names."""

    path_parameters = {parameter.name: parameter for parameter in operation.parameters if parameter.location == "path"}

    def replace(match: re.Match[str]) -> str:
        api_name = match.group(1)
        parameter = path_parameters.get(api_name)
        argument_name = parameter.py_name if parameter else to_identifier(api_name)
        if argument_name not in arguments:
            msg = f"Missing required path parameter {api_name!r} as argument {argument_name!r}."
            raise ValueError(msg)
        return str(arguments[argument_name])

    return _PATH_PARAM_RE.sub(replace, path)
