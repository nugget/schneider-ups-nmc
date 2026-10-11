"""Tests for the Home Assistant drift report."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from typing import Any
from unittest.mock import patch

from scripts import ha_drift

NEWEST_CORE = "2026.11.0"
CONSTRAINTS = """# Pinned by Home Assistant core
cryptography==50.0.1
aiohttp==3.13.0
typing-extensions>=4.16.0,<5.0
pycryptodome>=3.6.6
pycryptodome!=3.20.0
"""
RELEASES = {
    "typing-extensions": ["3.10.0", "4.15.0", "4.16.0", "4.17.1", "5.0.0"],
    "pycryptodome": ["3.5.0", "3.19.0", "3.20.0", "3.21.0"],
}


class RequirementStatusTest(unittest.TestCase):
    """Test how one manifest requirement compares with core."""

    def test_reports_each_requirement(self) -> None:
        """Flag conflicts with core pins and ranges, and drift from core's SNMP."""
        constraints = ha_drift._core_constraints(CONSTRAINTS)
        core_snmp = {"pysnmp": "pysnmp==7.1.27"}
        cases = (
            (
                "cryptography>=42.0.0,<49.0.0",
                "CONFLICT: core pins 50.0.1",
                True,
            ),
            ("cryptography>=42.0.0", "ok: core pins 50.0.1", False),
            (
                "typing-extensions<4",
                "CONFLICT: no release satisfies core's <5.0,>=4.16.0",
                True,
            ),
            (
                "typing-extensions>=4.17,<4.18",
                "ok: core requires <5.0,>=4.16.0",
                False,
            ),
            (
                "pycryptodome==3.20.0",
                "CONFLICT: no release satisfies core's !=3.20.0,>=3.6.6",
                True,
            ),
            ("pycryptodome>=3.19", "ok: core requires !=3.20.0,>=3.6.6", False),
            ("pysnmp==7.1.27", "matches core snmp integration", False),
            (
                "pysnmp==7.1.26",
                "differs from core snmp integration (pysnmp==7.1.27)",
                False,
            ),
            ("somepackage==1.0", "not constrained by core", False),
        )
        for requirement, expected_status, expected_conflict in cases:
            with self.subTest(requirement):
                self.assertEqual(
                    ha_drift.requirement_status(
                        requirement, constraints, core_snmp, RELEASES.__getitem__
                    ),
                    (expected_status, expected_conflict),
                )

    def test_core_constraints_keep_ranges_and_merge_lines(self) -> None:
        """Keep every core specifier and combine repeated packages."""
        self.assertEqual(
            {
                name: str(specifier)
                for name, specifier in ha_drift._core_constraints(CONSTRAINTS).items()
            },
            {
                "cryptography": "==50.0.1",
                "aiohttp": "==3.13.0",
                "typing-extensions": "<5.0,>=4.16.0",
                "pycryptodome": "!=3.20.0,>=3.6.6",
            },
        )


class MainTest(unittest.TestCase):
    """Test the report's exit status and harness advice, fully offline."""

    def test_exit_status_and_harness_advice(self) -> None:
        """Fail on conflicts; advise an upgrade only when the harness is behind.

        The installed Home Assistant matches the newest harness's in every case,
        so "harness behind" proves the check compares harness releases.
        """
        cases = (
            ("conflict", "pysnmp==9.9.9", "0.13.400", 1, "fail to load"),
            ("current", "pysnmp==7.1.27", "0.13.400", 0, None),
            ("harness behind", "pysnmp==7.1.27", "0.13.371", 0, "is behind"),
        )
        for name, core_pin, installed_harness, expected_exit, expected_advice in cases:
            with self.subTest(name):
                output = io.StringIO()
                with (
                    patch.object(ha_drift, "_pypi", _fake_pypi),
                    patch.object(
                        ha_drift,
                        "_core_file",
                        lambda _tag, path, pin=core_pin: _fake_core_file(path, pin),
                    ),
                    patch.object(
                        ha_drift,
                        "_installed",
                        lambda package, harness=installed_harness: (
                            harness if package == ha_drift.HARNESS else NEWEST_CORE
                        ),
                    ),
                    redirect_stdout(output),
                ):
                    exit_status = ha_drift.main()

                self.assertEqual(exit_status, expected_exit)
                for advice in ("fail to load", "is behind"):
                    if advice == expected_advice:
                        self.assertIn(advice, output.getvalue())
                    else:
                        self.assertNotIn(advice, output.getvalue())


def _fake_pypi(package: str, release: str | None = None) -> dict[str, Any]:
    if package == "homeassistant":
        return {"info": {"version": NEWEST_CORE, "requires_python": ">=3.14.2"}}
    if release is None:
        return {"info": {"version": "0.13.400"}}
    return {"info": {"requires_dist": [f"homeassistant=={NEWEST_CORE}"]}}


def _fake_core_file(path: str, pysnmp_pin: str) -> str:
    if path.endswith("package_constraints.txt"):
        return f"{CONSTRAINTS}{pysnmp_pin}\n"
    return json.dumps({"requirements": ["pysnmp==7.1.27"]})


if __name__ == "__main__":
    unittest.main()
