import unittest
from src.free_ai_model_radar.watcher import _fingerprint

class WatcherTests(unittest.TestCase):
    def test_html_ignores_script_noise(self):
        a = b"<html><body><h1>Free tier</h1><script>nonce=111</script></body></html>"
        b = b"<html><body><h1>Free tier</h1><script>nonce=999</script></body></html>"
        self.assertEqual(_fingerprint(a, "text/html"), _fingerprint(b, "text/html"))

    def test_visible_text_changes_hash(self):
        a = b"<html><body>Free tier: 100</body></html>"
        b = b"<html><body>Free tier: 200</body></html>"
        self.assertNotEqual(_fingerprint(a, "text/html"), _fingerprint(b, "text/html"))

if __name__ == "__main__":
    unittest.main()
