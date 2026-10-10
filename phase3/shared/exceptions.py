"""Phase 3 exception hierarchy."""


class PlatformError(Exception):
    """Base exception for the platform layer."""


class DuplicateUserError(PlatformError):
    """Raised when a user email is already registered."""


class InvalidCredentialsError(PlatformError):
    """Raised when credentials do not match."""


class TenantValidationError(PlatformError):
    """Raised when tenant data is invalid."""


class NotAuthorizedError(PlatformError):
    """Raised when the caller lacks the required role."""


class SessionExpiredError(PlatformError):
    """Raised when a session or JWT is no longer valid."""
