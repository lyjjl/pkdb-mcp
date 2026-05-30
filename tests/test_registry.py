import inspect
from pathlib import Path

from pkdb_mcp.client import PKDBClient
from pkdb_mcp.openapi import load_spec_file, parse_catalog
from pkdb_mcp.registry import make_operation_handler, operation_description
from pkdb_mcp.settings import Settings

FIXTURE = Path(__file__).parent / "fixtures" / "pkdb_minimal_openapi.json"


def test_make_operation_handler_has_operation_signature() -> None:
    catalog = parse_catalog(load_spec_file(FIXTURE))
    operation = catalog.get("pkdb_info_nodes_read")
    client = PKDBClient(
        Settings(
            api_base_url="https://example.test/api/v1",
            openapi_url="https://example.test/api/v1/swagger.json",
        ),
        catalog=catalog,
    )

    handler = make_operation_handler(client, operation)
    signature = inspect.signature(handler)

    assert handler.__name__ == "pkdb_info_nodes_read"
    assert "sid" in signature.parameters
    assert signature.parameters["sid"].default is inspect.Parameter.empty
    assert "format" in signature.parameters
    assert signature.parameters["format"].default is None
    assert "GET /info_nodes/{sid}/" in operation_description(operation)
