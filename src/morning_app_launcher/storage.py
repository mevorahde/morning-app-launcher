"""Versioned JSON persistence and legacy configuration migration."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from enum import Enum
from pathlib import Path
from typing import Protocol

from .errors import (
    ConfigurationError,
    ConfigurationReadError,
    ConfigurationWriteError,
    InvalidApplicationPath,
    InvalidDisplayName,
    MigrationError,
    UnsupportedConfigurationError,
)
from .models import Application, deduplicate

CONFIGURATION_VERSION = 2
LEGACY_JSON_CONFIGURATION_VERSION = 1
APPLICATION_DIRECTORY = "MorningAppLauncher"
CONFIGURATION_FILENAME = "config.json"


class ApplicationStore(Protocol):
    def exists(self) -> bool:
        """Return whether stored configuration exists."""

    def load(self) -> list[Application]:
        """Load applications or raise a safe configuration error."""

    def save(self, applications: list[Application]) -> None:
        """Persist applications atomically or raise a safe configuration error."""


def user_configuration_path(
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the stable per-user Windows configuration path."""

    environment = os.environ if environ is None else environ
    base_value = environment.get("LOCALAPPDATA") or environment.get("APPDATA")
    if base_value:
        base = Path(base_value)
    else:
        user_home = Path.home() if home is None else home
        base = user_home / "AppData" / "Local"
    return base / APPLICATION_DIRECTORY / CONFIGURATION_FILENAME


class JsonApplicationStore:
    """Store application paths in a small, versioned JSON document."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> list[Application]:
        if not self.path.exists():
            return []
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                document = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigurationReadError("The saved configuration could not be read.") from exc

        if not isinstance(document, dict):
            raise ConfigurationReadError("The saved configuration has an invalid format.")
        version = document.get("version")
        if version not in (LEGACY_JSON_CONFIGURATION_VERSION, CONFIGURATION_VERSION):
            raise UnsupportedConfigurationError(
                "The saved configuration version is not supported."
            )
        values = document.get("applications")
        if not isinstance(values, list):
            raise ConfigurationReadError("The saved configuration has an invalid format.")
        try:
            if version == LEGACY_JSON_CONFIGURATION_VERSION:
                if not all(isinstance(value, str) for value in values):
                    raise ConfigurationReadError(
                        "The saved configuration has an invalid format."
                    )
                applications = deduplicate(Application.from_text(value) for value in values)
                self.save(applications)
                return applications
            if not all(
                isinstance(value, dict)
                and set(value) == {"path", "name"}
                and isinstance(value["path"], str)
                and isinstance(value["name"], str)
                for value in values
            ):
                raise ConfigurationReadError("The saved configuration has an invalid format.")
            return deduplicate(
                Application.from_text(value["path"], value["name"]) for value in values
            )
        except (InvalidApplicationPath, InvalidDisplayName) as exc:
            raise ConfigurationReadError("The saved configuration has an invalid format.") from exc

    def save(self, applications: list[Application]) -> None:
        document = {
            "version": CONFIGURATION_VERSION,
            "applications": [
                {"path": str(application.path), "name": application.name}
                for application in applications
            ],
        }
        temporary_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                json.dump(document, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
        except (OSError, TypeError, ValueError) as exc:
            raise ConfigurationWriteError("The configuration could not be saved.") from exc
        finally:
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink(missing_ok=True)


class MigrationStatus(Enum):
    NOT_NEEDED = "not_needed"
    MIGRATED = "migrated"


class LegacyConfigurationMigrator:
    """Copy the ignored legacy text configuration into the JSON store."""

    def __init__(self, legacy_path: Path, destination: ApplicationStore) -> None:
        self.legacy_path = legacy_path
        self.destination = destination

    def migrate(self) -> MigrationStatus:
        if self.destination.exists() or not self.legacy_path.exists():
            return MigrationStatus.NOT_NEEDED
        try:
            text = self.legacy_path.read_text(encoding="utf-8")
            applications = deduplicate(
                Application.from_text(line) for line in text.splitlines() if line.strip()
            )
            self.destination.save(applications)
        except (
            OSError,
            UnicodeError,
            InvalidApplicationPath,
            InvalidDisplayName,
            ConfigurationError,
        ) as exc:
            raise MigrationError(
                "The legacy configuration could not be migrated and was left unchanged."
            ) from exc
        return MigrationStatus.MIGRATED
