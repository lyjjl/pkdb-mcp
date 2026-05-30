"""PK-DB HTTP client and OpenAPI operation executor."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any
from urllib.parse import urljoin

import httpx

from pkdb_mcp.errors import OperationNotFoundError, PKDBHTTPError
from pkdb_mcp.openapi import OpenAPICatalog, Operation, substitute_path_parameters
from pkdb_mcp.settings import Settings
from pkdb_mcp.types import JsonDict

_BINARY_CONTENT_TYPES = {
    "application/zip",
    "application/octet-stream",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class PKDBClient:
    """Small HTTP client for executing PK-DB API calls."""

    def __init__(self, settings: Settings, catalog: OpenAPICatalog | None = None) -> None:
        self.settings = settings
        self.catalog = catalog

    async def execute_operation(
        self, name_or_id: str, arguments: Mapping[str, Any] | None = None
    ) -> JsonDict:
        """Execute a loaded OpenAPI operation by tool name or operation ID."""

        if self.catalog is None:
            msg = "No OpenAPI catalog is attached to this client."
            raise OperationNotFoundError(msg)
        operation = self.catalog.get(name_or_id)
        return await self.call_operation(operation, dict(arguments or {}))

    async def call_operation(self, operation: Operation, arguments: dict[str, Any]) -> JsonDict:
        """Execute a normalized OpenAPI operation."""

        path = substitute_path_parameters(operation.path, arguments, operation)
        query: dict[str, Any] = {}
        body: Any = None

        for parameter in operation.parameters:
            if parameter.py_name not in arguments or arguments[parameter.py_name] is None:
                continue
            value = arguments[parameter.py_name]
            match parameter.location:
                case "query":
                    query[parameter.name] = value
                case "formData":
                    query[parameter.name] = value
                case "body":
                    body = value
                case "path":
                    pass
                case _:
                    query[parameter.name] = value

        if body is None:
            body = arguments.get("body", arguments.get("json_body"))

        return await self.raw_request(
            method=operation.method,
            path=path,
            query=query,
            json_body=body,
        )

    async def raw_request(
        self,
        *,
        method: str,
        path: str,
        query: Mapping[str, Any] | None = None,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> JsonDict:
        """Perform a direct request relative to the configured PK-DB API base URL."""

        request_headers = self._headers()
        if headers:
            request_headers.update(headers)

        url = self._url_for(path)
        try:
            client_kwargs: dict[str, Any] = {
                "timeout": self.settings.http_timeout_seconds,
                "follow_redirects": True,
                "headers": request_headers,
            }
            if self.settings.proxy:
                client_kwargs["proxies"] = self.settings.proxy
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.request(
                    method=method.upper(),
                    url=url,
                    params=_drop_none(query or {}),
                    json=json_body,
                )
        except httpx.HTTPError as exc:
            msg = f"PK-DB request failed: {exc}."
            raise PKDBHTTPError(msg) from exc

        return self._serialize_response(response)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, application/octet-stream, */*",
            "User-Agent": self.settings.user_agent,
        }
        if self.settings.api_token:
            headers["Authorization"] = f"Token {self.settings.api_token}"
        return headers

    def _url_for(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        base = f"{self.settings.api_base_url_str}/"
        normalized_path = path.lstrip("/")
        if normalized_path.startswith("api/v1/"):
            normalized_path = normalized_path.removeprefix("api/v1/")
        return urljoin(base, normalized_path)

    @staticmethod
    def _serialize_response(response: httpx.Response) -> JsonDict:
        content_type = (
            response.headers.get("content-type", "").split(";", maxsplit=1)[0].strip().lower()
        )
        payload: JsonDict = {
            "status_code": response.status_code,
            "ok": 200 <= response.status_code < 300,
            "content_type": content_type or None,
            "url": str(response.url),
        }

        if content_type == "application/json" or response.text.startswith(("{", "[")):
            try:
                payload["data"] = response.json()
                return payload
            except ValueError:
                pass

        if content_type in _BINARY_CONTENT_TYPES or _looks_binary(response.content):
            payload["data_base64"] = base64.b64encode(response.content).decode("ascii")
            payload["encoding"] = "base64"
            payload["size_bytes"] = len(response.content)
            return payload

        payload["text"] = response.text
        return payload


def _drop_none(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _looks_binary(content: bytes) -> bool:
    if not content:
        return False
    sample = content[:1024]
    return b"\x00" in sample
