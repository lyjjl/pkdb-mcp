"""MCP tool registration helpers."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from pkdb_mcp.client import PKDBClient
from pkdb_mcp.openapi import OpenAPICatalog, Operation, OperationParameter
from pkdb_mcp.types import JsonDict

ToolHandler = Callable[..., Awaitable[JsonDict]]


def make_operation_handler(client: PKDBClient, operation: Operation) -> ToolHandler:
    """Create a callable with an operation-specific signature for FastMCP."""

    async def handler(**kwargs: Any) -> JsonDict:
        return await client.call_operation(operation, kwargs)

    h: Any = handler
    h.__name__ = operation.tool_name
    h.__qualname__ = operation.tool_name
    h.__doc__ = operation_description(operation)
    h.__signature__ = operation_signature(operation)
    return handler


def operation_signature(operation: Operation) -> inspect.Signature:
    """Build a keyword-only Python signature from OpenAPI parameters."""

    parameters: list[inspect.Parameter] = []
    seen_names: set[str] = set()

    for item in operation.parameters:
        if item.location in {"header", "cookie"}:
            continue
        name = _unique_parameter_name(item.py_name, seen_names)
        default = inspect.Parameter.empty if item.required else None
        parameters.append(
            inspect.Parameter(
                name=name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=_annotation_for(item),
            )
        )

    if (
        operation.request_body is not None
        and "body" not in seen_names
        and "json_body" not in seen_names
    ):
        parameters.append(
            inspect.Parameter(
                name="json_body",
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=None,
                annotation=dict[str, Any] | list[Any] | str | int | float | bool | None,
            )
        )

    return inspect.Signature(parameters=parameters, return_annotation=dict[str, Any])


def operation_description(operation: Operation) -> str:
    """Build compact but useful MCP tool description text."""

    lines = [operation.brief, f"PK-DB REST operation: {operation.method.upper()} {operation.path}."]
    if operation.parameters:
        lines.append("Arguments:")
        for parameter in operation.parameters:
            required = "required" if parameter.required else "optional"
            location = parameter.location
            description = f" - {parameter.py_name}: {parameter.name} in {location}, {required}"
            if parameter.description:
                description = f"{description}. {parameter.description}"
            lines.append(description)
    if operation.request_body is not None:
        lines.append(
            "Request body: pass JSON as json_body"
            " unless the generated schema exposes a body argument."
        )
    return "\n".join(line for line in lines if line)


def register_operation_tools(mcp: Any, client: PKDBClient, catalog: OpenAPICatalog) -> None:
    """Register one MCP tool per parsed OpenAPI operation."""

    for operation in catalog.operations:
        handler = make_operation_handler(client, operation)
        mcp.tool(name=operation.tool_name, description=operation_description(operation))(handler)


def register_helper_tools(mcp: Any, client: PKDBClient, catalog: OpenAPICatalog) -> None:
    """Register stable helper tools that make the generated API easier for agents."""

    @mcp.tool(
        name="pkdb_list_operations",
        description="List all PK-DB operations loaded from the Swagger/OpenAPI document.",
    )
    async def list_operations(tag: str | None = None, search: str | None = None) -> JsonDict:
        operations = catalog.operations
        if tag:
            operations = tuple(operation for operation in operations if tag in operation.tags)
        if search:
            query = search.lower()
            operations = tuple(
                operation
                for operation in operations
                if query in operation.tool_name.lower()
                or query in operation.operation_id.lower()
                or query in operation.path.lower()
                or query in operation.brief.lower()
            )
        return {
            "title": catalog.title,
            "version": catalog.version,
            "operation_count": len(operations),
            "operations": [operation.compact() for operation in operations],
        }

    @mcp.tool(
        name="pkdb_describe_operation",
        description="Describe one PK-DB operation by MCP tool name or OpenAPI operation ID.",
    )
    async def describe_operation(name: str) -> JsonDict:
        operation = catalog.get(name)
        data = operation.compact()
        data["description"] = operation_description(operation)
        data["request_body"] = operation.request_body
        data["consumes"] = list(operation.consumes)
        data["produces"] = list(operation.produces)
        return data

    @mcp.tool(
        name="pkdb_raw_request",
        description=(
            "Perform a direct PK-DB REST request relative to PKDB_API_BASE_URL. "
            "Use this for newly added endpoints before the MCP process is restarted."
        ),
    )
    async def raw_request(
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        json_body: dict[str, Any] | list[Any] | str | int | float | bool | None = None,
    ) -> JsonDict:
        return await client.raw_request(method=method, path=path, query=query, json_body=json_body)


def _unique_parameter_name(name: str, seen_names: set[str]) -> str:
    candidate = name
    index = 2
    while candidate in seen_names:
        candidate = f"{name}_{index}"
        index += 1
    seen_names.add(candidate)
    return candidate


def _annotation_for(parameter: OperationParameter) -> object:
    schema_type = parameter.schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), None)
    match schema_type:
        case "integer":
            return int
        case "number":
            return float
        case "boolean":
            return bool
        case "array":
            return list[Any]
        case "object":
            return dict[str, Any]
        case _:
            return str | int | float | bool | list[Any] | dict[str, Any] | None
