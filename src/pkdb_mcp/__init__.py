"""MCP server for the PK-DB REST API."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pkdb-mcp")
except PackageNotFoundError:  # pragma: no cover - editable source tree without install metadata.
    __version__ = "0.0.0"

__all__ = ["__version__"]
