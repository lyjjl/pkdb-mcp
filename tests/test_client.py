from pathlib import Path

import httpx
import pytest

from pkdb_mcp.client import PKDBClient
from pkdb_mcp.openapi import load_spec_file, parse_catalog
from pkdb_mcp.settings import Settings

FIXTURE = Path(__file__).parent / "fixtures" / "pkdb_minimal_openapi.json"


@pytest.mark.asyncio
async def test_call_operation_builds_path_and_query(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = parse_catalog(load_spec_file(FIXTURE))
    settings = Settings(
        api_base_url="https://example.test/api/v1",
        openapi_url="https://example.test/api/v1/swagger.json",
        api_token="secret",
    )
    client = PKDBClient(settings, catalog=catalog)
    operation = catalog.get("pkdb_info_nodes_read")
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"sid": "caf"}, request=request)

    original_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: original_async_client(
            *args, transport=httpx.MockTransport(handler), **kwargs
        ),
    )

    result = await client.call_operation(operation, {"sid": "caf", "format": "json"})

    assert result["ok"] is True
    assert result["data"] == {"sid": "caf"}
    assert captured["url"] == "https://example.test/api/v1/info_nodes/caf/?format=json"
    assert captured["authorization"] == "Token secret"


@pytest.mark.asyncio
async def test_raw_request_serializes_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        api_base_url="https://example.test/api/v1",
        openapi_url="https://example.test/api/v1/swagger.json",
    )
    client = PKDBClient(settings)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"PK\x03\x04zip-content",
            headers={"content-type": "application/zip"},
            request=request,
        )

    original_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: original_async_client(
            *args, transport=httpx.MockTransport(handler), **kwargs
        ),
    )

    result = await client.raw_request(method="GET", path="/filter/", query={"download": True})

    assert result["encoding"] == "base64"
    assert result["size_bytes"] == len(b"PK\x03\x04zip-content")
    assert result["data_base64"]
