import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.free_ai_model_radar.smart_model_catalog import (
    FreeLLMModelCatalog,
    _normalize_group_key,
    _slugify_group_label,
    _strip_provider_suffix,
)


class SmartModelCatalogTests(unittest.TestCase):
    def test_provider_suffix_matches_freellm_grouping(self):
        self.assertEqual(_strip_provider_suffix("Qwen3 Coder 480B (HF)"), "Qwen3 Coder 480B")
        self.assertEqual(_strip_provider_suffix("DeepSeek V4 Flash Free"), "DeepSeek V4 Flash")
        self.assertEqual(_normalize_group_key("Qwen3-Coder_480B (HF)"), "qwen3 coder 480b")
        self.assertEqual(_slugify_group_label("Qwen3 Coder 480B"), "qwen3-coder-480b")

    def test_catalog_unifies_providers_into_canonical_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "freeapi.db"
            con = sqlite3.connect(db)
            con.executescript("""
                CREATE TABLE models (
                    id INTEGER PRIMARY KEY,
                    platform TEXT,
                    model_id TEXT,
                    display_name TEXT,
                    intelligence_rank INTEGER,
                    speed_rank INTEGER,
                    size_label TEXT,
                    context_window INTEGER,
                    supports_vision INTEGER,
                    supports_tools INTEGER,
                    endpoint_scope TEXT,
                    enabled INTEGER
                );
                CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
            """)
            con.executemany(
                "INSERT INTO models VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (1, "huggingface", "Qwen/Qwen3-Coder-480B-A35B-Instruct", "Qwen3 Coder 480B (HF)", 3, 7, "Frontier", 262144, 0, 1, "", 1),
                    (2, "other", "qwen3-coder-480b", "Qwen3-Coder 480B", 4, 5, "Frontier", 131072, 0, 1, "", 1),
                ],
            )
            con.commit()
            con.close()

            rows = FreeLLMModelCatalog(db_path=db).models()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].model_id, "qwen3-coder-480b")
            self.assertEqual(set(rows[0].platforms), {"huggingface", "other"})
            self.assertEqual(rows[0].context_window, 262144)
            self.assertTrue(rows[0].supports_tools)

    def test_unify_merge_override_is_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "freeapi.db"
            con = sqlite3.connect(db)
            con.executescript("""
                CREATE TABLE models (
                    id INTEGER PRIMARY KEY,
                    platform TEXT,
                    model_id TEXT,
                    display_name TEXT,
                    intelligence_rank INTEGER,
                    speed_rank INTEGER,
                    size_label TEXT,
                    context_window INTEGER,
                    supports_vision INTEGER,
                    supports_tools INTEGER,
                    endpoint_scope TEXT,
                    enabled INTEGER
                );
                CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
            """)
            con.executemany(
                "INSERT INTO models VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (1, "p1", "alpha-a", "Alpha A", 2, 5, "Large", 32000, 0, 1, "", 1),
                    (2, "p2", "alpha-b", "Alpha B", 3, 6, "Large", 64000, 0, 1, "", 1),
                ],
            )
            con.execute(
                "INSERT INTO settings VALUES (?,?)",
                ("model_unify_overrides", '{"merges":[{"into":"Alpha","keys":["p1:alpha-a","p2:alpha-b"]}],"splits":[]}'),
            )
            con.commit()
            con.close()

            rows = FreeLLMModelCatalog(db_path=db).models()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].model_id, "alpha-a")
            self.assertEqual(set(rows[0].platforms), {"p1", "p2"})


if __name__ == "__main__":
    unittest.main()
