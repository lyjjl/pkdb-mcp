"""FastMCP server factory."""

from __future__ import annotations

from typing import Any

from pkdb_mcp.client import PKDBClient
from pkdb_mcp.openapi import OpenAPICatalog, load_spec, parse_catalog
from pkdb_mcp.registry import register_helper_tools, register_operation_tools
from pkdb_mcp.settings import Settings, get_settings


def load_catalog(settings: Settings | None = None) -> OpenAPICatalog:
    """Load and parse the PK-DB Swagger/OpenAPI catalog."""

    effective_settings = settings or get_settings()
    return parse_catalog(load_spec(effective_settings))


def create_mcp_server(settings: Settings | None = None) -> Any:
    """Create a FastMCP server and register all PK-DB tools."""

    from mcp.server.fastmcp import FastMCP

    effective_settings = settings or get_settings()
    catalog = load_catalog(effective_settings)
    client = PKDBClient(effective_settings, catalog=catalog)
    mcp = FastMCP(effective_settings.mcp_server_name)

    register_helper_tools(mcp, client, catalog)
    register_operation_tools(mcp, client, catalog)
    return mcp


def run(settings: Settings | None = None) -> None:
    """Run the MCP server with configured transport."""

    effective_settings = settings or get_settings()
    mcp = create_mcp_server(effective_settings)
    if effective_settings.mcp_transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport=effective_settings.mcp_transport)
