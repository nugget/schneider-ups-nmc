"""Home Assistant Marketplace metadata checks for APC UPS NMC."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "custom_components" / "schneider_ups_nmc" / "manifest.json"

# The only hacs.json keys the 2026.11 Marketplace reads; anything else is
# silently ignored, so a key outside this set is dead configuration.
MARKETPLACE_HACS_JSON_KEYS = {
    "content_in_root",
    "filename",
    "hacs",
    "hide_default_branch",
    "homeassistant",
    "name",
    "persistent_directory",
    "zip_release",
}


class MarketplaceMetadataTest(unittest.TestCase):
    """Keep the repository metadata the Marketplace reads accurate."""

    def test_hacs_json_has_only_keys_the_marketplace_reads(self) -> None:
        """Every hacs.json key is one the Marketplace honors."""
        hacs = json.loads(ROOT.joinpath("hacs.json").read_text(encoding="utf-8"))
        self.assertLessEqual(set(hacs), MARKETPLACE_HACS_JSON_KEYS)

    def test_manifest_declares_categories_and_connectivity(self) -> None:
        """The 2026.11 categories (primary first) and connectivity are declared."""
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertTrue(1 <= len(manifest["categories"]) <= 3)
        self.assertEqual(manifest["categories"][0], "energy.backup_power")
        self.assertEqual(manifest["connectivity"], ["network"])


if __name__ == "__main__":
    unittest.main()
