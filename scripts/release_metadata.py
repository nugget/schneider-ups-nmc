"""Read and write the release version shared by manifest.json and pyproject.toml.

Home Assistant reads the integration version from ``manifest.json`` and the
Python tooling reads it from ``pyproject.toml``. The release recipes in the
``justfile`` call this script so both surfaces always move together.

Usage::

    python scripts/release_metadata.py normalize v0.2.0   # prints 0.2.0
    python scripts/release_metadata.py current            # working tree
    python scripts/release_metadata.py current origin/main
    python scripts/release_metadata.py set 0.2.0
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("custom_components/schneider_ups_nmc/manifest.json")
PYPROJECT = Path("pyproject.toml")

_VERSION_PATTERN = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z][0-9A-Za-z.-]*)?$"
)
_PROJECT_SECTION = re.compile(r"(?ms)^\[project\]\n(?P<body>.*?)(?=^\[|\Z)")
_PROJECT_VERSION_LINE = re.compile(
    r"(?m)^(?P<prefix>version\s*=\s*)(?P<quote>['\"])"
    r"(?P<value>[^'\"]*)(?P=quote)(?P<suffix>\s*(?:#.*)?)$"
)


class ReleaseMetadataError(Exception):
    """Raised when a version or release metadata file is not usable."""


def normalize_version(version: str) -> str:
    """Return ``version`` without its leading ``v``, such as ``0.2.0``.

    Accepts ``0.2.0``, ``v0.2.0`` and pre-releases such as ``0.2.0-rc.1``, and
    raises ``ReleaseMetadataError`` for anything else.
    """
    normalized = version.removeprefix("v")
    if not _VERSION_PATTERN.match(normalized):
        msg = (
            f"release version must look like 0.1.0, v0.1.0, 0.1.0-rc.1, or "
            f"v0.1.0-rc.1 (got {version!r})"
        )
        raise ReleaseMetadataError(msg)
    return normalized


def current_version(ref: str | None = None, root: Path = ROOT) -> str:
    """Return the manifest version in the working tree, or at git ``ref``.

    Raises ``ReleaseMetadataError`` when ``ref`` or its manifest cannot be read.
    """
    if ref is None:
        text = root.joinpath(MANIFEST).read_text(encoding="utf-8")
    else:
        result = subprocess.run(
            ["git", "show", f"{ref}:{MANIFEST.as_posix()}"],
            cwd=root,
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            msg = f"could not read {MANIFEST} at {ref}: {result.stderr.strip()}"
            raise ReleaseMetadataError(msg)
        text = result.stdout
    return json.loads(text)["version"]


def set_version(version: str, root: Path = ROOT) -> None:
    """Write ``version`` into ``manifest.json`` and ``pyproject.toml``.

    Both files are validated and rendered before either is written, so a
    malformed ``pyproject.toml`` leaves the manifest untouched too. The
    ``[project]`` version line is edited in place so comments and formatting
    elsewhere survive. Raises ``ReleaseMetadataError`` when there is no single
    editable version line.
    """
    manifest_path = root.joinpath(MANIFEST)
    pyproject_path = root.joinpath(PYPROJECT)
    manifest_text = _render_manifest(manifest_path.read_text(encoding="utf-8"), version)
    pyproject_text = _render_pyproject(
        pyproject_path.read_text(encoding="utf-8"), version
    )
    manifest_path.write_text(manifest_text, encoding="utf-8")
    pyproject_path.write_text(pyproject_text, encoding="utf-8")


def _render_manifest(text: str, version: str) -> str:
    manifest = json.loads(text)
    manifest["version"] = version
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def _render_pyproject(text: str, version: str) -> str:
    try:
        parsed_version = tomllib.loads(text)["project"]["version"]
    except (tomllib.TOMLDecodeError, KeyError) as err:
        msg = f"pyproject.toml has no readable [project] version: {err}"
        raise ReleaseMetadataError(msg) from err
    section = _PROJECT_SECTION.search(text)
    if section is None:
        msg = "pyproject.toml is missing a [project] section"
        raise ReleaseMetadataError(msg)

    body = section.group("body")
    lines = list(_PROJECT_VERSION_LINE.finditer(body))
    if len(lines) != 1:
        msg = "pyproject.toml [project] section must contain exactly one version"
        raise ReleaseMetadataError(msg)
    line = lines[0]
    if line.group("value") != parsed_version:
        msg = "pyproject.toml parsed version does not match the version line"
        raise ReleaseMetadataError(msg)

    quote = line.group("quote")
    updated_body = (
        body[: line.start()]
        + f"{line.group('prefix')}{quote}{version}{quote}{line.group('suffix')}"
        + body[line.end() :]
    )
    return text[: section.start("body")] + updated_body + text[section.end("body") :]


def main(argv: list[str] | None = None) -> int:
    """Run the command line and return the process exit status."""
    parser = argparse.ArgumentParser(description="Read or write the release version.")
    commands = parser.add_subparsers(dest="command", required=True)
    normalize = commands.add_parser("normalize", help="print VERSION without 'v'")
    normalize.add_argument("version")
    current = commands.add_parser("current", help="print the manifest version")
    current.add_argument("ref", nargs="?", help="git ref; default: working tree")
    setter = commands.add_parser("set", help="write VERSION to release metadata")
    setter.add_argument("version")
    args = parser.parse_args(argv)

    try:
        if args.command == "normalize":
            print(normalize_version(args.version))
        elif args.command == "current":
            print(current_version(args.ref))
        else:
            set_version(normalize_version(args.version))
    except ReleaseMetadataError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
