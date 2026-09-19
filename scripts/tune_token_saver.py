import json
import sqlite3
from pathlib import Path

p = Path.home() / 'freellmapi' / 'server' / 'data' / 'freeapi.db'
con = sqlite3.connect(p)
row = con.execute("SELECT value FROM settings WHERE key='compression'").fetchone()
cfg = json.loads(row[0])
cfg['autoTriggerEstTokens'] = 6000
cfg['targetTokens'] = 4000
con.execute("UPDATE settings SET value=? WHERE key='compression'", (json.dumps(cfg, separators=(',', ':')),))
con.commit()
print('trigger=6000 target=4000')
