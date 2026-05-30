from pathlib import Path

from pkdb_mcp.openapi import (
    load_spec_file,
    parse_catalog,
    substitute_path_parameters,
    to_identifier,
)

FIXTURE = Path(__file__).parent / "fixtures" / "pkdb_minimal_openapi.json"


def test_to_identifier_normalizes_api_names() -> None:
    assert to_identifier("studies__name") == "studies__name"
    assert to_identifier("api/v1/info-nodes/{sid}") == "api_v1_info_nodes_sid"
    assert to_identifier("1bad-name") == "value_1bad_name"
    assert to_identifier("class") == "class_"


def test_parse_swagger2_catalog() -> None:
    catalog = parse_catalog(load_spec_file(FIXTURE))

    assert catalog.title == "PK-DB REST API"
    assert catalog.version == "v1"
    assert len(catalog.operations) == 3
    assert "pkdb_statistics_list" in catalog.by_tool_name

    operation = catalog.get("pkdb_info_nodes_read")
    assert operation.method == "get"
    assert operation.path == "/info_nodes/{sid}/"
    assert operation.parameters[0].name == "sid"
    assert operation.parameters[0].py_name == "sid"
    assert operation.parameters[0].required is True


def test_substitute_path_parameters() -> None:
    catalog = parse_catalog(load_spec_file(FIXTURE))
    operation = catalog.get("pkdb_info_nodes_read")

    assert (
        substitute_path_parameters(operation.path, {"sid": "caf"}, operation) == "/info_nodes/caf/"
    )
