"""Compare this repository with the newest Home Assistant release.

Run it through ``just ha-drift`` when Home Assistant ships a new release or
when an install breaks after a core upgrade. It answers three questions:

* Is the test harness running the Home Assistant users have?
* Do our manifest requirements fit the newest core's pinned packages?
* Does our ``pysnmp`` pin match core's own SNMP integration, which shares
  the same Python environment?

The script only reads from PyPI and GitHub; it never edits files. It exits
non-zero when a requirement would stop the integration from loading on the
newest Home Assistant.
"""

from __future__ import annotations

import json
import sys
import tomllib
import urllib.request
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
HARNESS = "pytest-homeassistant-custom-component"
CORE_RAW = "https://raw.githubusercontent.com/home-assistant/core/{tag}/{path}"
TIMEOUT_SECONDS = 15


def _fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8")


def _pypi(package: str, release: str | None = None) -> dict[str, Any]:
    path = f"{package}/{release}/json" if release else f"{package}/json"
    return json.loads(_fetch(f"https://pypi.org/pypi/{path}"))


def _core_file(tag: str, path: str) -> str:
    return _fetch(CORE_RAW.format(tag=tag, path=path))


def _exact_pins(constraints: str) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in constraints.splitlines():
        text = line.split("#", 1)[0].strip()
        if not text:
            continue
        requirement = Requirement(text)
        specifiers = list(requirement.specifier)
        if len(specifiers) == 1 and specifiers[0].operator == "==":
            pins[canonicalize_name(requirement.name)] = specifiers[0].version
    return pins


def _harness_home_assistant(harness_release: str) -> str:
    for requirement in _pypi(HARNESS, harness_release)["info"]["requires_dist"]:
        parsed = Requirement(requirement)
        if parsed.name == "homeassistant":
            return str(parsed.specifier).removeprefix("==")
    return "unknown"


def _installed(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "not installed (run `just setup`)"


def requirement_status(
    text: str, core_pins: dict[str, str], core_snmp: dict[str, str]
) -> tuple[str, bool]:
    """Describe one manifest requirement against the newest core.

    ``core_pins`` maps canonical package names to the exact versions in core's
    ``package_constraints.txt``; ``core_snmp`` maps them to the requirement
    strings in core's SNMP integration manifest. Returns the report text and
    whether the requirement would stop the integration from loading.
    """
    requirement = Requirement(text)
    name = canonicalize_name(requirement.name)
    notes: list[str] = []
    conflict = False
    pinned = core_pins.get(name)
    if pinned and not requirement.specifier.contains(pinned, prereleases=True):
        notes.append(f"CONFLICT: core pins {pinned}")
        conflict = True
    elif pinned:
        notes.append(f"ok, core pins {pinned}")
    core_text = core_snmp.get(name)
    if core_text and SpecifierSet(str(Requirement(core_text).specifier)) != (
        requirement.specifier
    ):
        notes.append(f"differs from core snmp integration ({core_text})")
    elif core_text:
        notes.append("matches core snmp integration")
    return "; ".join(notes) or "not pinned by core", conflict


def main() -> int:
    """Print the drift report; return 1 if a requirement blocks setup."""
    manifest = json.loads(
        ROOT.joinpath("custom_components/schneider_ups_nmc/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    hacs = json.loads(ROOT.joinpath("hacs.json").read_text(encoding="utf-8"))
    pyproject = tomllib.loads(ROOT.joinpath("pyproject.toml").read_text("utf-8"))

    core = _pypi("homeassistant")["info"]
    latest_core = core["version"]
    latest_harness = _pypi(HARNESS)["info"]["version"]
    latest_harness_core = _harness_home_assistant(latest_harness)
    installed_harness = _installed(HARNESS)
    pins = _exact_pins(_core_file(latest_core, "homeassistant/package_constraints.txt"))
    snmp_manifest = json.loads(
        _core_file(latest_core, "homeassistant/components/snmp/manifest.json")
    )
    core_snmp: dict[str, str] = {
        canonicalize_name(Requirement(text).name): text
        for text in snmp_manifest["requirements"]
    }

    print("Home Assistant")
    rows = [
        ("newest release", latest_core),
        (
            f"installed {HARNESS}",
            f"{installed_harness} (HA {_installed('homeassistant')})",
        ),
        (f"newest {HARNESS}", f"{latest_harness} (HA {latest_harness_core})"),
        ("hacs.json minimum", hacs.get("homeassistant", "not set")),
        ("newest core needs Python", core["requires_python"]),
        ("we declare Python", pyproject["project"]["requires-python"]),
    ]
    for label, value in rows:
        print(f"  {label:<48} {value}")

    conflicts = 0
    print("\nManifest requirements vs newest core")
    for text in manifest["requirements"]:
        status, conflict = requirement_status(text, pins, core_snmp)
        conflicts += conflict
        print(f"  {text:<48} {status}")

    if conflicts:
        print(
            "\nThe integration will fail to load on the newest Home Assistant. "
            "Fix the requirement, then `just ha-upgrade` and `just ci`."
        )
        return 1
    if installed_harness != latest_harness:
        print(
            f"\nThe installed harness ({installed_harness}) is behind the newest "
            f"release ({latest_harness}). Run `just ha-upgrade` to test against it."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
