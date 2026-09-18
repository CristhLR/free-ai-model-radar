import tempfile, unittest
from pathlib import Path
from src.free_ai_model_radar.db import connect, sync_provider
from src.free_ai_model_radar.domain import CandidateModel

class DbTests(unittest.TestCase):
    def test_diff_new_then_removed(self):
        with tempfile.TemporaryDirectory() as td:
            con = connect(Path(td) / "radar.db")
            model = CandidateModel("x","m","https://x/v1","https://x/models")
            self.assertEqual(sync_provider(con,"x",[model])["NEW"], ["m"])
            self.assertEqual(sync_provider(con,"x",[])["REMOVED"], ["m"])
            con.close()

if __name__ == "__main__":
    unittest.main()
