import hashlib, sqlite3, uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass(frozen=True)
class HoldReceipt:
    hold_id:str; content_hash:str; size:int; created_at:str; created_by:str

class SharedHold:
    def __init__(self, db_path):
        self.db_path=str(db_path); self._init()
    def _con(self):
        c=sqlite3.connect(self.db_path, timeout=5)
        c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA busy_timeout=5000")
        return c
    def _init(self):
        with closing(self._con()) as c:
            c.execute("""CREATE TABLE IF NOT EXISTS holds(
              hold_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, created_by TEXT NOT NULL,
              content_hash TEXT NOT NULL, size INTEGER NOT NULL, payload BLOB NOT NULL)""")
    def hold(self,payload,*,created_by):
        if not isinstance(payload,bytes): raise TypeError("payload must be bytes")
        if not isinstance(created_by,str) or not created_by.strip(): raise ValueError("created_by required")
        h=hashlib.sha256(payload).hexdigest(); i=uuid.uuid4().hex
        t=datetime.now(timezone.utc).isoformat()
        with closing(self._con()) as c:
            with c:
                c.execute("INSERT INTO holds VALUES(?,?,?,?,?,?)",(i,t,created_by,h,len(payload),payload))
        return HoldReceipt(i,h,len(payload),t,created_by)
    def get(self,hold_id):
        with closing(self._con()) as c:
            r=c.execute("SELECT content_hash,size,payload FROM holds WHERE hold_id=?",(hold_id,)).fetchone()
        if r is None: raise KeyError(hold_id)
        h,n,p=r; p=bytes(p)
        if len(p)!=n or hashlib.sha256(p).hexdigest()!=h: raise RuntimeError("integrity failure")
        return p
    def discover(self):
        with closing(self._con()) as c:
            return c.execute("SELECT hold_id,created_at,created_by,content_hash,size FROM holds ORDER BY created_at,hold_id").fetchall()
