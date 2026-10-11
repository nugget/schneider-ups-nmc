"""Tests for the release metadata script used by the release recipes."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import release_metadata

ROOT = Path(__file__).resolve().parents[1]
VALID_PYPROJECT = """[project]
name = "schneider-ups-nmc"
version = "0.2.0"  # release version
dependencies = []

[tool.ruff]
target-version = "py314"
"""


class NormalizeVersionTest(unittest.TestCase):
    """Test release version normalization."""

    def test_accepts_release_versions(self) -> None:
        """Strip a leading v from semver releases and pre-releases."""
        cases = (
            ("0.2.0", "0.2.0"),
            ("v0.2.0", "0.2.0"),
            ("0.2.0-rc.1", "0.2.0-rc.1"),
            ("v1.10.3-beta.2", "1.10.3-beta.2"),
        )
        for given, expected in cases:
            with self.subTest(given):
                self.assertEqual(release_metadata.normalize_version(given), expected)

    def test_rejects_non_release_versions(self) -> None:
        """Reject anything that would produce a malformed tag."""
        for given in ("", "1.2", "x", "vv0.2.0", "0.2.0 ", "0.2.0-", "release"):
            with (
                self.subTest(given),
                self.assertRaises(release_metadata.ReleaseMetadataError),
            ):
                release_metadata.normalize_version(given)


class SetVersionTest(unittest.TestCase):
    """Test writing the version to both release surfaces."""

    def setUp(self) -> None:
        """Copy the real manifest beside a known pyproject into a temp root."""
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        manifest = self.root / release_metadata.MANIFEST
        manifest.parent.mkdir(parents=True)
        shutil.copy(ROOT / release_metadata.MANIFEST, manifest)
        self.manifest = manifest
        self.pyproject = self.root / release_metadata.PYPROJECT

    def test_updates_both_surfaces_and_preserves_the_rest(self) -> None:
        """Change only the version in manifest.json and pyproject.toml."""
        self.pyproject.write_text(VALID_PYPROJECT, encoding="utf-8")
        before = json.loads(self.manifest.read_text(encoding="utf-8"))

        release_metadata.set_version("0.3.0", root=self.root)

        after = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(after, before | {"version": "0.3.0"})
        self.assertEqual(
            self.pyproject.read_text(encoding="utf-8"),
            VALID_PYPROJECT.replace(
                'version = "0.2.0"  # release version',
                'version = "0.3.0"  # release version',
            ),
        )
        self.assertEqual(release_metadata.current_version(root=self.root), "0.3.0")

    def test_malformed_pyproject_leaves_both_files_untouched(self) -> None:
        """Validate everything before writing anything."""
        cases = (
            ("invalid TOML", "[project\nversion = 1\n"),
            ("no project section", '[tool.ruff]\nversion = "0.2.0"\n'),
            ("no project version", '[project]\nname = "x"\n'),
            (
                "version not a single-line string",
                "[project]\nname = 'x'\nversion = '''0.2.0'''\n",
            ),
        )
        for name, pyproject_text in cases:
            with self.subTest(name):
                self.pyproject.write_text(pyproject_text, encoding="utf-8")
                manifest_before = self.manifest.read_bytes()

                with self.assertRaises(release_metadata.ReleaseMetadataError):
                    release_metadata.set_version("9.9.9", root=self.root)

                self.assertEqual(self.manifest.read_bytes(), manifest_before)
                self.assertEqual(
                    self.pyproject.read_text(encoding="utf-8"), pyproject_text
                )


class CurrentVersionTest(unittest.TestCase):
    """Test reading the manifest version from the tree and from git refs."""

    def setUp(self) -> None:
        """Create a throwaway git repository with one committed manifest."""
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.manifest = self.root / release_metadata.MANIFEST
        self.manifest.parent.mkdir(parents=True)
        self._write_manifest("1.0.0")
        self._git("init", "--quiet")
        self._git("add", ".")
        self._git("commit", "--quiet", "-m", "release 1.0.0")
        self._write_manifest("2.0.0")

    def test_reads_working_tree_and_refs(self) -> None:
        """Read uncommitted and committed versions independently."""
        cases = ((None, "2.0.0"), ("HEAD", "1.0.0"))
        for ref, expected in cases:
            with self.subTest(ref):
                self.assertEqual(
                    release_metadata.current_version(ref, root=self.root), expected
                )

    def test_malformed_manifest_raises_release_error(self) -> None:
        """Report a broken manifest cleanly instead of with a traceback."""
        cases = (
            ("invalid JSON", "{"),
            ("no version", '{"domain": "schneider_ups_nmc"}'),
            ("non-string version", '{"version": 2}'),
            ("not an object", '["0.2.0"]'),
        )
        for name, manifest_text in cases:
            with self.subTest(name):
                self.manifest.write_text(manifest_text, encoding="utf-8")
                with self.assertRaises(release_metadata.ReleaseMetadataError):
                    release_metadata.current_version(root=self.root)
                with self.assertRaises(release_metadata.ReleaseMetadataError):
                    release_metadata.set_version("9.9.9", root=self.root)

    def test_unknown_ref_raises(self) -> None:
        """Report a ref that does not exist instead of crashing."""
        with self.assertRaises(release_metadata.ReleaseMetadataError):
            release_metadata.current_version("origin/nope", root=self.root)

    def _write_manifest(self, version: str) -> None:
        self.manifest.write_text(json.dumps({"version": version}), encoding="utf-8")

    def _git(self, *args: str) -> None:
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Release Test",
                "-c",
                "user.email=release-test@example.invalid",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            cwd=self.root,
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
