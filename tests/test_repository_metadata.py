"""Repository metadata checks for APC UPS NMC."""

from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path
from typing import Any

import homeassistant
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "schneider_ups_nmc"
PACKAGE_NAME = "schneider-ups-nmc"


class RepositoryMetadataTest(unittest.TestCase):
    """Test release and HACS metadata consistency."""

    def test_hacs_repository_contains_one_integration(self) -> None:
        """Keep the repository layout valid for HACS integration installs."""
        integrations = [
            path
            for path in ROOT.joinpath("custom_components").iterdir()
            if path.is_dir() and path.joinpath("manifest.json").is_file()
        ]

        self.assertEqual([path.name for path in integrations], [DOMAIN])
        self.assertTrue(ROOT.joinpath("hacs.json").is_file())
        self.assertTrue(ROOT.joinpath("README.md").is_file())

    def test_release_versions_match(self) -> None:
        """Keep Home Assistant and Python package metadata in lockstep."""
        manifest = _manifest()
        pyproject = _pyproject()
        lock_package = _lock_package()

        self.assertEqual(manifest["version"], pyproject["project"]["version"])
        self.assertEqual(manifest["version"], lock_package["version"])

    def test_manifest_matches_project_metadata(self) -> None:
        """Keep manifest metadata aligned with repository packaging."""
        manifest = _manifest()
        pyproject = _pyproject()
        hacs = _hacs()

        self.assertEqual(manifest["domain"], DOMAIN)
        self.assertEqual(manifest["name"], hacs["name"])
        self.assertEqual(pyproject["project"]["name"], PACKAGE_NAME)
        self.assertEqual(
            set(manifest["requirements"]),
            set(pyproject["project"]["dependencies"]),
        )
        self.assertEqual(
            manifest["documentation"],
            "https://github.com/nugget/schneider-ups-nmc",
        )
        self.assertEqual(
            manifest["issue_tracker"],
            "https://github.com/nugget/schneider-ups-nmc/issues",
        )

    def test_manifest_requirements_fit_home_assistant_constraints(self) -> None:
        """Reject requirements that conflict with Home Assistant's own pins.

        Home Assistant refuses to set up an integration whose requirements
        cannot be installed alongside the versions it pins in
        ``package_constraints.txt``, so a stale upper bound becomes a
        production setup failure on the next core upgrade.
        """
        constraints = _home_assistant_pins()

        for requirement_text in _manifest()["requirements"]:
            requirement = Requirement(requirement_text)
            pinned = constraints.get(canonicalize_name(requirement.name))
            if pinned is None:
                continue
            with self.subTest(requirement_text):
                self.assertTrue(
                    requirement.specifier.contains(pinned, prereleases=True),
                    f"Home Assistant pins {requirement.name}=={pinned}",
                )


def _manifest() -> dict[str, Any]:
    """Return the integration manifest."""
    return json.loads(
        ROOT.joinpath("custom_components", DOMAIN, "manifest.json").read_text(
            encoding="utf-8"
        )
    )


def _pyproject() -> dict[str, Any]:
    """Return the Python project metadata."""
    return tomllib.loads(ROOT.joinpath("pyproject.toml").read_text(encoding="utf-8"))


def _hacs() -> dict[str, Any]:
    """Return HACS repository metadata."""
    return json.loads(ROOT.joinpath("hacs.json").read_text(encoding="utf-8"))


def _lock_package() -> dict[str, Any]:
    """Return the local package entry from uv.lock."""
    lock = tomllib.loads(ROOT.joinpath("uv.lock").read_text(encoding="utf-8"))
    for package in lock["package"]:
        if package["name"] == PACKAGE_NAME:
            return package

    raise AssertionError(f"{PACKAGE_NAME} is missing from uv.lock")


if __name__ == "__main__":
    unittest.main()


def _home_assistant_pins() -> dict[str, str]:
    constraints_path = Path(homeassistant.__file__).with_name("package_constraints.txt")
    pins: dict[str, str] = {}
    for line in constraints_path.read_text(encoding="utf-8").splitlines():
        text = line.split("#", 1)[0].strip()
        if not text:
            continue
        requirement = Requirement(text)
        specifiers = list(requirement.specifier)
        if len(specifiers) == 1 and specifiers[0].operator == "==":
            pins[canonicalize_name(requirement.name)] = specifiers[0].version
    return pins
