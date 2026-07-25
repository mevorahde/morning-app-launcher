from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from morning_app_launcher.errors import (
    ConfigurationReadError,
    ConfigurationWriteError,
    MigrationError,
    UnsupportedConfigurationError,
)
from morning_app_launcher.models import Application
from morning_app_launcher.storage import (
    JsonApplicationStore,
    LegacyConfigurationMigrator,
    MigrationStatus,
    user_configuration_path,
)

from .fakes import FakeStore


def test_missing_configuration_loads_empty(tmp_path: Path) -> None:
    assert JsonApplicationStore(tmp_path / "config.json").load() == []


def test_json_round_trip_and_version(tmp_path: Path) -> None:
    path = tmp_path / "data" / "config.json"
    store = JsonApplicationStore(path)
    applications = [
        Application(tmp_path / "one.exe", "First app"),
        Application(tmp_path / "two.exe", "第二个应用"),
    ]

    store.save(applications)

    assert store.load() == applications
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document == {
        "version": 2,
        "applications": [
            {"path": str(tmp_path / "one.exe"), "name": "First app"},
            {"path": str(tmp_path / "two.exe"), "name": "第二个应用"},
        ],
    }


def test_version_one_configuration_migrates_atomically_without_path_or_order_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.json"
    first = tmp_path / "First Tool.exe"
    second = tmp_path / "Second Tool.exe"
    path.write_text(
        json.dumps({"version": 1, "applications": [str(first), str(second)]}),
        encoding="utf-8",
    )
    original_replace = os.replace
    replacements: list[tuple[Path, Path]] = []

    def recording_replace(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        replacements.append((Path(source), Path(destination)))
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", recording_replace)

    applications = JsonApplicationStore(path).load()

    assert applications == [
        Application(first, "First Tool"),
        Application(second, "Second Tool"),
    ]
    assert [application.path for application in applications] == [first, second]
    assert len(replacements) == 1
    assert replacements[0][1] == path
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 2


def test_failed_version_one_migration_preserves_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.json"
    original = json.dumps(
        {"version": 1, "applications": [str(tmp_path / "Private Tool.exe")]}
    )
    path.write_text(original, encoding="utf-8")

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("simulated")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(ConfigurationWriteError, match="could not be saved"):
        JsonApplicationStore(path).load()

    assert path.read_text(encoding="utf-8") == original


def test_save_uses_atomic_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "config.json"
    original_replace = os.replace
    replacements: list[tuple[Path, Path]] = []

    def recording_replace(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        replacements.append((Path(source), Path(destination)))
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", recording_replace)
    JsonApplicationStore(path).save([Application(tmp_path / "one.exe")])

    assert len(replacements) == 1
    assert replacements[0][1] == path
    assert not list(tmp_path.glob("*.tmp"))


def test_failed_atomic_replace_preserves_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.json"
    original = '{"version": 1, "applications": []}\n'
    path.write_text(original, encoding="utf-8")

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("simulated failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(ConfigurationWriteError, match="could not be saved"):
        JsonApplicationStore(path).save([Application(tmp_path / "one.exe")])

    assert path.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize(
    "document,error",
    [
        ("not json", ConfigurationReadError),
        ('{"version": 99, "applications": []}', UnsupportedConfigurationError),
        ('{"version": 1, "applications": "wrong"}', ConfigurationReadError),
        ('{"version": 1, "applications": [""]}', ConfigurationReadError),
        ('{"version": 2, "applications": [{"path": "x.exe"}]}', ConfigurationReadError),
        (
            '{"version": 2, "applications": [{"path": "x.exe", "name": ""}]}',
            ConfigurationReadError,
        ),
    ],
)
def test_malformed_or_unsupported_configuration(
    tmp_path: Path, document: str, error: type[Exception]
) -> None:
    path = tmp_path / "config.json"
    path.write_text(document, encoding="utf-8")

    with pytest.raises(error):
        JsonApplicationStore(path).load()

    assert path.read_text(encoding="utf-8") == document


def test_legacy_migration_is_atomic_deduplicated_and_preserves_source(tmp_path: Path) -> None:
    legacy = tmp_path / "save.txt"
    first = tmp_path / "one.exe"
    second = tmp_path / "two.exe"
    contents = f"{first}\n{first}\n\n{second}\n"
    legacy.write_text(contents, encoding="utf-8")
    store = JsonApplicationStore(tmp_path / "data" / "config.json")

    status = LegacyConfigurationMigrator(legacy, store).migrate()

    assert status is MigrationStatus.MIGRATED
    assert store.load() == [Application(first), Application(second)]
    assert legacy.read_text(encoding="utf-8") == contents


def test_migration_failure_preserves_legacy_file(tmp_path: Path) -> None:
    legacy = tmp_path / "save.txt"
    contents = "one.exe\n"
    legacy.write_text(contents, encoding="utf-8")

    class FailingStore(FakeStore):
        def save(self, applications: list[Application]) -> None:
            raise ConfigurationWriteError("simulated")

    with pytest.raises(MigrationError, match="left unchanged"):
        LegacyConfigurationMigrator(legacy, FailingStore()).migrate()

    assert legacy.read_text(encoding="utf-8") == contents


def test_migration_does_not_overwrite_existing_configuration(tmp_path: Path) -> None:
    legacy = tmp_path / "save.txt"
    legacy.write_text("legacy.exe\n", encoding="utf-8")
    existing = Application(tmp_path / "existing.exe")
    store = FakeStore([existing], configuration_exists=True)

    status = LegacyConfigurationMigrator(legacy, store).migrate()

    assert status is MigrationStatus.NOT_NEEDED
    assert store.save_calls == []


def test_user_configuration_path_prefers_local_app_data(tmp_path: Path) -> None:
    result = user_configuration_path({"LOCALAPPDATA": str(tmp_path)}, home=tmp_path / "home")

    assert result == tmp_path / "MorningAppLauncher" / "config.json"
