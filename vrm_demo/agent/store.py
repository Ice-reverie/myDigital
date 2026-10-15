"""Durable demo sessions, request deduplication, immutable proposals and leases.

A session bearer secret is hashed at rest. Approval tokens stay in the local
state DB so a refresh can redisplay an outstanding proposal. Never publish it.
"""
from contextlib import contextmanager
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import time
import uuid

class AgentError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status

def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)

def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

class Store:
    def __init__(self, path: Path, session_ttl=86400, approval_ttl=600):
        self.path, self.session_ttl, self.approval_ttl = Path(path), session_ttl, approval_ttl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS agent_sessions (
                id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL, expires REAL NOT NULL,
                state TEXT NOT NULL, lock_owner TEXT, lock_until REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS agent_requests (
                session_id TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                response TEXT NOT NULL, created REAL NOT NULL,
                PRIMARY KEY(session_id,request_id)
            );
            CREATE TABLE IF NOT EXISTS agent_proposals (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, request_id TEXT NOT NULL,
                token TEXT NOT NULL, status TEXT NOT NULL, expires REAL NOT NULL,
                payload TEXT NOT NULL, result TEXT,
                UNIQUE(session_id,request_id)
            );
            CREATE INDEX IF NOT EXISTS agent_proposal_session ON agent_proposals(session_id,status);
            """)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=3)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_session(self):
        sid, secret = uuid.uuid4().hex, secrets.token_urlsafe(32)
        state = {"history": [], "eligible_slots": {}, "preferences": {}, "last_response": None}
        with self.connect() as conn:
            # Expired session state and its bearer-accessible content are removed.
            expired = [r[0] for r in conn.execute("SELECT id FROM agent_sessions WHERE expires<? AND lock_until<?",
                                                 (time.time(), time.time()))]
            for old in expired:
                conn.execute("DELETE FROM agent_requests WHERE session_id=?", (old,))
                conn.execute("DELETE FROM agent_proposals WHERE session_id=?", (old,))
                conn.execute("DELETE FROM agent_sessions WHERE id=?", (old,))
            count = conn.execute("SELECT COUNT(*) FROM agent_sessions").fetchone()[0]
            if count >= 1000:
                raise AgentError("session_limit", "演示会话已达上限，请清理过期会话。", 429)
            conn.execute("INSERT INTO agent_sessions(id,secret_hash,expires,state) VALUES(?,?,?,?)",
                         (sid, digest(secret), time.time() + self.session_ttl, encode(state)))
        return {"session_id": sid, "access_token": secret, "expires_in": self.session_ttl}

    def authenticate(self, sid, token):
        with self.connect() as conn:
            row = conn.execute("SELECT secret_hash,expires FROM agent_sessions WHERE id=?", (sid,)).fetchone()
        if not row or row["expires"] < time.time() or not hmac.compare_digest(row["secret_hash"], digest(token or "")):
            raise AgentError("unauthorized", "会话不存在或已过期，请新建演示会话。", 401)

    @contextmanager
    def lease(self, sid):
        owner = uuid.uuid4().hex
        with self.connect() as conn:
            changed = conn.execute("UPDATE agent_sessions SET lock_owner=?,lock_until=? WHERE id=? AND lock_until<?",
                                   (owner, time.time()+120, sid, time.time())).rowcount
            if changed != 1:
                raise AgentError("session_busy", "该会话正在处理另一条请求，请重试同一请求。", 409)
        try:
            yield
        finally:
            with self.connect() as conn:
                conn.execute("UPDATE agent_sessions SET lock_owner=NULL,lock_until=0 WHERE id=? AND lock_owner=?",
                             (sid, owner))

    def load(self, sid):
        with self.connect() as conn:
            row = conn.execute("SELECT state FROM agent_sessions WHERE id=?", (sid,)).fetchone()
        if not row:
            raise AgentError("unauthorized", "会话不存在。", 401)
        return json.loads(row[0])

    def save(self, sid, state):
        with self.connect() as conn:
            conn.execute("UPDATE agent_sessions SET state=? WHERE id=?", (encode(state), sid))

    def cached(self, sid, rid, fingerprint):
        with self.connect() as conn:
            row = conn.execute("SELECT fingerprint,response FROM agent_requests WHERE session_id=? AND request_id=?",
                               (sid, rid)).fetchone()
        if row:
            if not hmac.compare_digest(row["fingerprint"], fingerprint):
                raise AgentError("request_id_conflict", "相同 request_id 不能用于不同的操作或参数。", 409)
            return json.loads(row["response"])
        return None

    def complete(self, sid, rid, fingerprint, response, state):
        state["last_response"] = response
        with self.connect() as conn:
            conn.execute("UPDATE agent_sessions SET state=? WHERE id=?", (encode(state), sid))
            conn.execute("INSERT INTO agent_requests VALUES(?,?,?,?,?)",
                         (sid, rid, fingerprint, encode(response), time.time()))
            # Bounded cache. Booking safety also uses a separate durable proposal token.
            conn.execute("DELETE FROM agent_requests WHERE session_id=? AND request_id NOT IN "
                         "(SELECT request_id FROM agent_requests WHERE session_id=? ORDER BY created DESC LIMIT 200)",
                         (sid, sid))

    def pending(self, sid):
        with self.connect() as conn:
            conn.execute("UPDATE agent_proposals SET status='expired' WHERE session_id=? AND status='pending' AND expires<?",
                         (sid, time.time()))
            row = conn.execute("SELECT * FROM agent_proposals WHERE session_id=? AND status IN ('pending','committing') "
                               "ORDER BY expires DESC LIMIT 1", (sid,)).fetchone()
        return self._proposal(row) if row else None

    @staticmethod
    def _proposal(row):
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        result["result"] = json.loads(result["result"]) if result["result"] else None
        return result

    def create_proposal(self, sid, rid, payload):
        with self.connect() as conn:
            old = conn.execute("SELECT * FROM agent_proposals WHERE session_id=? AND request_id=?", (sid, rid)).fetchone()
            if old:
                proposal = self._proposal(old)
                if proposal["payload"]["schedule_id"] != payload["schedule_id"]:
                    raise AgentError("proposal_conflict", "请求重试不能更换原有预约时段。", 409)
                return proposal
            active = conn.execute("SELECT id FROM agent_proposals WHERE session_id=? AND status IN ('pending','committing')",
                                  (sid,)).fetchone()
            if active:
                raise AgentError("approval_pending", "请先确认或取消当前待处理预约。", 409)
            pid, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
            expires = time.time()+self.approval_ttl
            conn.execute("INSERT INTO agent_proposals VALUES(?,?,?,?,?,?,?,NULL)",
                         (pid,sid,rid,token,"pending",expires,encode(payload)))
        return self.proposal(sid, pid)

    def proposal(self, sid, pid):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM agent_proposals WHERE id=? AND session_id=?", (pid, sid)).fetchone()
        if not row:
            raise AgentError("proposal_not_found", "当前会话没有这条待确认预约。", 404)
        return self._proposal(row)

    def set_proposal_status(self, pid, status, result=None):
        with self.connect() as conn:
            conn.execute("UPDATE agent_proposals SET status=?,result=? WHERE id=?",
                         (status, encode(result) if result is not None else None, pid))
