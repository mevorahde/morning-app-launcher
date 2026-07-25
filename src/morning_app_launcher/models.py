"""Domain models and path identity helpers."""

from __future__ import annotations

import os
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .errors import InvalidApplicationPath, InvalidDisplayName

MAX_DISPLAY_NAME_LENGTH = 120


def default_display_name(path: Path) -> str:
    """Derive the historical filename-based label for a path."""

    return path.stem or path.name or "Application"


def validate_display_name(value: str) -> str:
    """Normalize and validate a user-visible application name."""

    if not isinstance(value, str):
        raise InvalidDisplayName("The application name is invalid.")
    name = value.strip()
    if not name:
        raise InvalidDisplayName("Enter an application name.")
    if len(name) > MAX_DISPLAY_NAME_LENGTH:
        raise InvalidDisplayName(
            f"Application names must be {MAX_DISPLAY_NAME_LENGTH} characters or fewer."
        )
    if any(char in "\r\n" or unicodedata.category(char) == "Cc" for char in name):
        raise InvalidDisplayName(
            "Application names cannot contain line breaks or control characters."
        )
    return name


@dataclass(frozen=True, slots=True, init=False)
class Application:
    """A configured application with path identity and a user-visible name."""

    path: Path
    name: str

    def __init__(self, path: Path, name: str | None = None) -> None:
        object.__setattr__(self, "path", path)
        object.__setattr__(
            self,
            "name",
            validate_display_name(default_display_name(path) if name is None else name),
        )

    @classmethod
    def from_text(cls, value: str, name: str | None = None) -> Application:
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise InvalidApplicationPath("The application path is invalid.")
        path = Path(value.strip())
        return cls(path, default_display_name(path) if name is None else name)

    @property
    def identity(self) -> str:
        return os.path.normcase(str(self.path.resolve(strict=False)))

    def renamed(self, name: str) -> Application:
        """Return a copy with the same launch path and a validated display name."""

        return Application(self.path, name)


def deduplicate(applications: Iterable[Application]) -> list[Application]:
    """Preserve order while removing path-equivalent entries."""

    result: list[Application] = []
    identities: set[str] = set()
    for application in applications:
        if application.identity not in identities:
            identities.add(application.identity)
            result.append(application)
    return result
