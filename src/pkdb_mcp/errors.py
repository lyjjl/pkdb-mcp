"""Domain exceptions used by the PK-DB MCP server."""


class PKDBMCPError(RuntimeError):
    """Base class for expected PK-DB MCP errors."""


class OpenAPILoadError(PKDBMCPError):
    """Raised when the OpenAPI document cannot be loaded."""


class OpenAPIParseError(PKDBMCPError):
    """Raised when the OpenAPI document cannot be parsed."""


class OperationNotFoundError(PKDBMCPError):
    """Raised when a requested OpenAPI operation is unknown."""


class PKDBHTTPError(PKDBMCPError):
    """Raised for transport-level PK-DB API failures."""
