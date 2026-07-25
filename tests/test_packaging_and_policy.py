from __future__ import annotations

import re
import struct
import subprocess
from pathlib import Path
from typing import Any

import yaml

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.10 CI job
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
BUILD_WORKFLOW = ROOT / ".github" / "workflows" / "build-windows-executable.yml"
SCREENSHOT = ROOT / "docs" / "images" / "morning-app-launcher.png"


def _machine_path_pattern() -> re.Pattern[str]:
    backslash = chr(92)
    path_separator = "[" + re.escape(backslash + "/") + "]"
    drive_root = r"(?<![A-Za-z0-9])[A-Za-z]:" + path_separator
    drive_path = drive_root + r"[^\s\"']+"
    unc_root = re.escape(backslash) * 2
    unc_segment = "[^" + re.escape(backslash) + r"\s]+"
    unc_path = unc_root + unc_segment + re.escape(backslash) + unc_segment
    return re.compile("|".join((drive_path, unc_path)))


def _load_yaml(path: Path) -> dict[str, Any]:
    document = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    return document


def _workflow_steps(document: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = document["jobs"]
    assert isinstance(jobs, dict)
    steps: list[dict[str, Any]] = []
    for job in jobs.values():
        assert isinstance(job, dict)
        job_steps = job.get("steps", [])
        assert isinstance(job_steps, list)
        steps.extend(step for step in job_steps if isinstance(step, dict))
    return steps


def _png_chunks(path: Path) -> tuple[tuple[int, int, int], list[str]]:
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    width, height, _depth, color_type = struct.unpack(">IIBB", data[16:26])
    chunks: list[str] = []
    position = 8
    while position < len(data):
        length = struct.unpack(">I", data[position : position + 4])[0]
        chunks.append(data[position + 4 : position + 8].decode("ascii"))
        position += length + 12
    return (width, height, color_type), chunks


def test_project_metadata_license_entry_point_and_dependencies() -> None:
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = document["project"]

    assert project["name"] == "morning-app-launcher"
    assert project["requires-python"] == ">=3.10,<3.14"
    assert project["license"] == {"file": "LICENSE"}
    assert project["gui-scripts"] == {"morning-app-launcher": "morning_app_launcher.app:main"}
    assert "dependencies" not in project
    assert any(
        dependency.lower().startswith("pyinstaller>=")
        for dependency in project["optional-dependencies"]["release"]
    )
    assert all(
        "pyinstaller" not in dependency.lower()
        for dependency in project["optional-dependencies"]["dev"]
    )
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert license_text.startswith("MIT License")
    assert "Permission is hereby granted" in license_text


def test_package_resources_and_legacy_artifacts() -> None:
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = document["tool"]["setuptools"]["package-data"]
    resources = set(package_data["morning_app_launcher.resources"])

    assert resources == {"morning-app-launcher.ico", "morning-app-launcher.png"}
    assert not (ROOT / "src" / "morning_app_launcher" / "resources" / "favicon.ico").exists()
    assert not (ROOT / "morning_apps.exe").exists()
    assert not (ROOT / "morning_apps.pyw").exists()


def test_portfolio_screenshot_has_only_image_chunks() -> None:
    dimensions, chunks = _png_chunks(SCREENSHOT)

    assert dimensions == (824, 524, 2)
    assert chunks[0] == "IHDR"
    assert chunks[-1] == "IEND"
    assert set(chunks) <= {"IHDR", "IDAT", "IEND"}


def test_ci_is_least_privilege_and_runs_all_supported_versions() -> None:
    document = _load_yaml(CI_WORKFLOW)
    steps = _workflow_steps(document)
    runs = "\n".join(str(step.get("run", "")) for step in steps)
    matrix = document["jobs"]["test"]["strategy"]["matrix"]

    assert document["permissions"] == {"contents": "read"}
    assert set(matrix["python-version"]) == {"3.10", "3.11", "3.12", "3.13"}
    for command in (
        'pip install -e ".[dev]"',
        "pip check",
        "compileall -q src",
        "ruff check src tests",
        "mypy",
        "pytest",
    ):
        assert command in runs
    assert "morning-app-launcher" not in runs
    assert "python -m morning_app_launcher" not in runs


def test_official_actions_use_flexible_numeric_major_policy() -> None:
    workflows = [_load_yaml(CI_WORKFLOW), _load_yaml(BUILD_WORKFLOW)]
    uses = [
        str(step["uses"])
        for workflow in workflows
        for step in _workflow_steps(workflow)
        if "uses" in step
    ]

    assert uses
    assert all(re.fullmatch(r"actions/[a-z0-9-]+@v[1-9][0-9]*", value) for value in uses)


def test_manual_build_workflow_creates_only_unsigned_portable_artifacts() -> None:
    document = _load_yaml(BUILD_WORKFLOW)
    text = BUILD_WORKFLOW.read_text(encoding="utf-8")
    steps = _workflow_steps(document)
    uploads = [step for step in steps if "upload-artifact" in str(step.get("uses", ""))]

    assert document["permissions"] == {"contents": "read"}
    assert document["on"] == {"workflow_dispatch": ""}
    assert "--onedir" in text
    assert "--onefile" not in text
    assert "--windowed" in text
    assert "--name MorningAppLauncher" in text
    assert "--collect-data morning_app_launcher" in text
    assert "morning-app-launcher.ico" in text
    assert '$directory = "release-output\\MorningAppLauncher"' in text
    assert '"$directory\\MorningAppLauncher.exe"' in text
    assert "Compress-Archive -LiteralPath $directory -DestinationPath $archive" in text
    assert "Get-FileHash" in text
    assert "MorningAppLauncher-portable-windows.zip.sha256" in text
    assert len(uploads) == 1
    assert uploads[0]["with"] == {
        "name": "MorningAppLauncher-portable-windows",
        "path": (
            "release-output/MorningAppLauncher-portable-windows.zip\n"
            "release-output/MorningAppLauncher-portable-windows.zip.sha256\n"
        ),
        "if-no-files-found": "error",
    }
    assert "gh release" not in text.lower()
    assert "softprops/action-gh-release" not in text.lower()
    assert "signtool" not in text.lower()


def test_dependabot_is_weekly_and_bounded() -> None:
    document = _load_yaml(ROOT / ".github" / "dependabot.yml")
    updates = document["updates"]

    assert {update["package-ecosystem"] for update in updates} == {"pip", "github-actions"}
    assert all(update["schedule"]["interval"] == "weekly" for update in updates)
    assert all(0 < int(update["open-pull-requests-limit"]) <= 10 for update in updates)


def test_tracked_tree_excludes_local_private_and_generated_files() -> None:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = result.stdout.splitlines()
    forbidden = re.compile(
        r"(^|/)(save\.txt|config\.json|\.env(?:\..*)?|__pycache__|\.pytest_cache|"
        r"\.mypy_cache|\.ruff_cache|build|dist|release-output|logs?)(/|$)|"
        r"\.(?:pyc|pyo|log|exe|msi|dll|whl|sha256|spec)$",
        re.IGNORECASE,
    )

    assert not [path for path in paths if forbidden.search(path)]


def test_tracked_text_has_no_absolute_machine_or_network_paths() -> None:
    machine_path = _machine_path_pattern()
    backslash = chr(92)
    drive_home = "C:" + backslash + "Users" + backslash + "example-user"
    absolute_windows = "D:" + backslash + "Program Files" + backslash + "Example"
    network_share = backslash + backslash + "server" + backslash + "share"

    assert machine_path.search(drive_home)
    assert machine_path.search(absolute_windows)
    assert machine_path.search(network_share)
    assert machine_path.search("docs/images/example.png") is None
    assert machine_path.search("docs" + backslash + "images" + backslash + "example.png") is None
    assert machine_path.search("https://example.com/downloads/tool") is None

    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    text_suffixes = {".md", ".py", ".toml", ".yml", ".yaml", ".txt"}
    findings: list[str] = []
    for relative in result.stdout.splitlines():
        path = ROOT / relative
        if path.suffix.lower() not in text_suffixes or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if machine_path.search(text):
            findings.append(relative)

    assert findings == []
