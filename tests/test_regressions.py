from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "kg-media-to-text"))


def load_module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, REPO / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class VaultConfigTests(unittest.TestCase):
    def test_canonical_registry_is_read_and_preserves_other_domains(self):
        vault = load_module("vault_under_test", "kg-media-to-text/media_to_text/vault.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            one = root / "one"
            (one / "wiki").mkdir(parents=True)
            (one / "AGENTS.md").write_text("ok", encoding="utf-8")
            vault.CONFIG_PATH = root / "config.json"
            vault.CONFIG_PATH.write_text(json.dumps({
                "version": 1,
                "vault": {"default": "one", "paths": {"one": str(one)}},
                "report": {"at": "09:30"},
            }), encoding="utf-8")

            self.assertEqual(vault._from_config(), one.resolve())
            vault.save_vault_registry({"one": str(one)}, "one")
            saved = json.loads(vault.CONFIG_PATH.read_text(encoding="utf-8"))
            self.assertEqual(saved["report"], {"at": "09:30"})
            self.assertEqual(saved["vault"]["paths"], {"one": str(one)})
            self.assertNotIn("vaults", saved)

    def test_legacy_registry_is_migrated_only_when_written(self):
        vault = load_module("vault_legacy_test", "kg-media-to-text/media_to_text/vault.py")
        with tempfile.TemporaryDirectory() as td:
            vault.CONFIG_PATH = Path(td) / "config.json"
            vault.CONFIG_PATH.write_text(json.dumps({
                "default": "personal",
                "vaults": {"personal": "/tmp/personal"},
                "collect": {"mail": {}},
            }), encoding="utf-8")
            self.assertEqual(
                vault.load_vault_registry(), ({"personal": "/tmp/personal"}, "personal"))
            vault.save_vault_registry({"personal": "/tmp/personal"}, "personal")
            saved = json.loads(vault.CONFIG_PATH.read_text(encoding="utf-8"))
            self.assertEqual(saved["collect"], {"mail": {}})
            self.assertEqual(saved["vault"]["default"], "personal")
            self.assertNotIn("default", saved)

    def test_invalid_shared_config_is_not_silently_overwritten(self):
        vault = load_module("vault_invalid_test", "kg-media-to-text/media_to_text/vault.py")
        with tempfile.TemporaryDirectory() as td:
            vault.CONFIG_PATH = Path(td) / "config.json"
            vault.CONFIG_PATH.write_text("{broken", encoding="utf-8")
            with self.assertRaises(vault.VaultNotFoundError):
                vault.save_vault_registry({"one": "/tmp/one"}, "one")
            self.assertEqual(vault.CONFIG_PATH.read_text(encoding="utf-8"), "{broken")


class ToolRegressionTests(unittest.TestCase):
    def test_shell_image_target_never_reuses_an_existing_name(self):
        helper = REPO / "kg-init/templates/scripts/lib-imgcompress.sh"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "photo.png"
            src.touch()
            (root / "photo.webp").touch()
            cmd = 'source "$1"; unique_webp_path "$2"'
            first = subprocess.run(
                ["bash", "-c", cmd, "_", str(helper), str(src)],
                check=True, capture_output=True, text=True).stdout.strip()
            self.assertNotEqual(first, str(root / "photo.webp"))
            Path(first).touch()
            second = subprocess.run(
                ["bash", "-c", cmd, "_", str(helper), str(src)],
                check=True, capture_output=True, text=True).stdout.strip()
            self.assertNotEqual(second, first)

    def test_doc_output_uses_source_path_hash(self):
        doc = load_module("ingest_doc_test", "kg-doc/scripts/ingest_doc.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            doc.RAW_DIR = root / "raw"
            doc.RAW_DIR.mkdir()
            a = root / "a" / "report.pdf"
            b = root / "b" / "report.docx"
            a.parent.mkdir(); b.parent.mkdir()
            a.touch(); b.touch()
            self.assertNotEqual(doc.out_path_for(a), doc.out_path_for(b))

    def test_web_output_uses_url_hash(self):
        doc = load_module("ingest_web_test", "kg-doc/scripts/ingest_doc.py")
        with tempfile.TemporaryDirectory() as td:
            doc.RAW_DIR = Path(td)
            self.assertNotEqual(
                doc.web_out_path("https://a.example/post", "Same title"),
                doc.web_out_path("https://b.example/post", "Same title"),
            )

    def test_lint_reports_dead_ref_without_any_images(self):
        lint = load_module("lint_no_images_test", "kg-lint/scripts/lint_vault.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "wiki").mkdir()
            (root / "wiki" / "note.md").write_text(
                "![missing](missing.png)", encoding="utf-8")
            lint.VAULT = root
            findings = lint.check_image()
            self.assertEqual([x["kind"] for x in findings], ["dead_image"])

    def test_lint_does_not_collapse_duplicate_basenames(self):
        lint = load_module("lint_duplicate_images_test", "kg-lint/scripts/lint_vault.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "wiki").mkdir()
            (root / "assets" / "a").mkdir(parents=True)
            (root / "assets" / "b").mkdir(parents=True)
            (root / "assets" / "a" / "same.png").write_bytes(b"a")
            (root / "assets" / "b" / "same.png").write_bytes(b"b")
            (root / "wiki" / "note.md").write_text(
                "![exact](../assets/a/same.png)", encoding="utf-8")
            lint.VAULT = root
            findings = lint.check_image()
            orphans = [x["image"] for x in findings if x["kind"] == "orphan_image"]
            self.assertEqual(orphans, ["assets/b/same.png"])

    def test_search_index_rebuilds_after_deletion(self):
        search = load_module("search_delete_test", "kg-ask/scripts/search_vault.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "wiki").mkdir()
            page = root / "wiki" / "gone.md"
            page.write_text("temporary", encoding="utf-8")
            search.VAULT = root
            search.INDEX_FILE = root / "cache" / "index.json"
            self.assertEqual(len(search.build_index()["docs"]), 1)
            page.unlink()
            self.assertEqual(search.load_index()["docs"], [])

    def test_review_state_is_scoped_by_vault(self):
        review = load_module("review_state_test", "kg-review/scripts/pick_review.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            one = root / "one"; two = root / "two"
            one.mkdir(); two.mkdir()
            with mock.patch.dict(os.environ, {"KG_AGENT_CONFIG_DIR": str(root / "cfg")}):
                self.assertNotEqual(review.review_log_path(one), review.review_log_path(two))
                self.assertEqual(review.review_log_path(one).parent, root / "cfg" / "state")


if __name__ == "__main__":
    unittest.main()
