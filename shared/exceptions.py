"""Shared application exceptions used at module boundaries."""


class ConfigurationError(ValueError):
    """Raised when a required or invalid configuration value is supplied."""


class ContractViolation(ValueError):
    """Raised when an inter-module payload violates the shared contract."""


__all__ = ["ConfigurationError", "ContractViolation"]
