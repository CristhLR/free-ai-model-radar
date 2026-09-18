import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.free_ai_model_radar.catalog_discovery import _merge_candidate, _parse_freellm_readme, _slug
from src.free_ai_model_radar.db import connect


class CatalogDiscoveryTests(unittest.TestCase):
    def test_known_aliases_deduplicate(self):
        self.assertEqual(_slug("Google AI Studio (Gemini)", {}), "google-gemini")
        self.assertEqual(_slug("Zhipu AI (GLM)", {}), "zai-glm")
        self.assertEqual(_slug("Mistral AI", {}), "mistral")

    def test_parse_freellm_quick_reference(self):
        text = '''<!-- BEGIN_QUICK_REF -->
| Provider | Base URL | Get API Key | Credit Card? |
|---|---|---|---|
| Groq | `https://api.groq.com/openai/v1` | <a href="https://console.groq.com/keys">Get Key →</a> | No |
<!-- END_QUICK_REF -->'''
        rows = _parse_freellm_readme(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Groq")
        self.assertEqual(rows[0]["registration_url"], "https://console.groq.com/keys")
        self.assertFalse(rows[0]["card_required"])

    def test_secondary_source_does_not_overwrite_known_value(self):
        with tempfile.TemporaryDirectory() as td:
            con = connect(Path(td) / "radar.db")
            now = datetime.now(timezone.utc).isoformat()
            con.execute(
                """INSERT INTO provider_candidates(slug,name,status,source_url,api_base_url,card_required,first_seen,last_seen)
                VALUES(?,?,?,?,?,?,?,?)""",
                ("demo", "Demo", "discovered", "primary", "https://primary/v1", 1, now, now),
            )
            con.commit()
            _merge_candidate(
                con, "secondary", "https://catalog", {"name":"Demo", "api_base_url":"https://other/v1", "card_required":False}, {"demo":"demo"}, now
            )
            row = con.execute("SELECT api_base_url,card_required,metadata_json FROM provider_candidates WHERE slug='demo'").fetchone()
            self.assertEqual(row[0], "https://primary/v1")
            self.assertEqual(row[1], 1)
            self.assertIn("catalog_conflicts", row[2])
            con.close()


if __name__ == "__main__":
    unittest.main()
