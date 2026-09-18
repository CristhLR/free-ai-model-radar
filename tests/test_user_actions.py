import tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path

from src.free_ai_model_radar.db import connect
from src.free_ai_model_radar.user_actions import build_registration_actions, complete_action, list_pending_actions

class UserActionTests(unittest.TestCase):
    def test_registration_queue(self):
        with tempfile.TemporaryDirectory() as td:
            con = connect(Path(td) / "radar.db")
            now = datetime.now(timezone.utc).isoformat()
            con.execute(
                """INSERT INTO provider_candidates(
                slug,name,status,source_url,docs_url,env_key,phone_required,card_required,
                first_seen,last_seen)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                ("demo","Demo AI","discovered","https://source","https://demo.example/signup",
                 "DEMO_API_KEY",1,0,now,now),
            )
            con.commit()

            result = build_registration_actions(con)
            self.assertEqual(result["created_actions"], 3)
            actions = list_pending_actions(con, "demo")
            self.assertEqual([a["action"] for a in actions],
                             ["register_account","phone_verification","create_api_key"])

            complete_action(con, actions[0]["id"])
            remaining = list_pending_actions(con, "demo")
            self.assertEqual(len(remaining), 2)
            con.close()

if __name__ == "__main__":
    unittest.main()
