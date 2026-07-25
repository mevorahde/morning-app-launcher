"""Safe application-level errors that do not disclose configured paths."""


class ApplicationError(Exception):
    """Base class for errors safe to present to a user."""


class ConfigurationError(ApplicationError):
    """Configuration could not be read or written safely."""


class ConfigurationReadError(ConfigurationError):
    """Configuration could not be loaded."""


class ConfigurationWriteError(ConfigurationError):
    """Configuration could not be stored."""


class UnsupportedConfigurationError(ConfigurationReadError):
    """Configuration uses a schema version this application cannot read."""


class MigrationError(ConfigurationError):
    """Legacy configuration could not be migrated."""


class InvalidApplicationPath(ApplicationError):
    """A selected application path is invalid or unavailable."""


class InvalidDisplayName(ApplicationError):
    """An application display name is invalid."""


class DuplicateApplication(ApplicationError):
    """An application is already present in the collection."""


class InvalidSelection(ApplicationError):
    """A requested list selection does not exist."""


class LaunchError(ApplicationError):
    """The operating system could not open an application."""
