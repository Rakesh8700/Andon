#!/usr/bin/env python3
"""
Andon Support Tool - practical backend.

Pure Python standard library (no pip installs required):
  - http.server  : HTTP server + static file serving
  - sqlite3      : persistent storage (andon.db)
  - json         : API payloads

Data model
----------
queries(id, associate_login, comment, image, status, created_at)
answers(id, query_id, sme_login, response_text, created_at)

status transitions: open -> answered -> resolved

Run:
  python server.py            (defaults to port 8900)
  python server.py 9000       (custom port)

Then open:
  http://localhost:8900/associate.html
  http://localhost:8900/sme.html
  http://localhost:8900/dashboard.html
"""

import http.server
import socketserver
import sqlite3
import json
import os
import sys
import threading
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "andon.db")

# Port: Render (and most PaaS) inject a PORT env var; fall back to CLI arg or 8900.
PORT = int(os.environ.get("PORT") or (sys.argv[1] if len(sys.argv) > 1 else 8900))

# ---------------------------------------------------------------------------
# Database backend selection.
#   - If DATABASE_URL is set (e.g. on Render), use PostgreSQL (persistent).
#   - Otherwise use a local SQLite file (great for local dev).
# The rest of the app uses ? placeholders; for Postgres we translate to %s.
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_PG = DATABASE_URL.startswith("postgres")

_db_lock = threading.Lock()

if USE_PG:
    import psycopg
    from psycopg.rows import dict_row

    # Some providers give "postgres://"; psycopg wants "postgresql://".
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

    def get_db():
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)

    def _adapt(sql):
        # Translate SQLite-style ? placeholders to Postgres %s.
        return sql.replace("?", "%s")
else:
    def get_db():
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _adapt(sql):
        return sql


def init_db():
    with _db_lock:
        conn = get_db()
        cur = conn.cursor()
        if USE_PG:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS queries (
                    id               SERIAL PRIMARY KEY,
                    associate_login  TEXT NOT NULL,
                    comment          TEXT NOT NULL,
                    image            TEXT,
                    status           TEXT NOT NULL DEFAULT 'open',
                    claimed_by       TEXT,
                    claimed_at       TEXT,
                    created_at       TEXT NOT NULL
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS answers (
                    id             SERIAL PRIMARY KEY,
                    query_id       INTEGER NOT NULL REFERENCES queries(id),
                    sme_login      TEXT NOT NULL,
                    response_text  TEXT NOT NULL,
                    created_at     TEXT NOT NULL
                );
                """
            )
        else:
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS queries (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    associate_login  TEXT NOT NULL,
                    comment          TEXT NOT NULL,
                    image            TEXT,
                    status           TEXT NOT NULL DEFAULT 'open',
                    claimed_by       TEXT,
                    claimed_at       TEXT,
                    created_at       TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS answers (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_id       INTEGER NOT NULL,
                    sme_login      TEXT NOT NULL,
                    response_text  TEXT NOT NULL,
                    created_at     TEXT NOT NULL,
                    FOREIGN KEY (query_id) REFERENCES queries(id)
                );
                """
            )
            # Migration for older local DBs that predate the claim columns.
            cols = [r[1] for r in conn.execute("PRAGMA table_info(queries)").fetchall()]
            if "claimed_by" not in cols:
                conn.execute("ALTER TABLE queries ADD COLUMN claimed_by TEXT")
            if "claimed_at" not in cols:
                conn.execute("ALTER TABLE queries ADD COLUMN claimed_at TEXT")
        conn.commit()
        conn.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def q_all(sql, params=()):
    with _db_lock:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(_adapt(sql), params)
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]


def q_one(sql, params=()):
    with _db_lock:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(_adapt(sql), params)
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None


def execute(sql, params=()):
    """Run INSERT/UPDATE. For INSERTs, returns the new row id."""
    with _db_lock:
        conn = get_db()
        cur = conn.cursor()
        is_insert = sql.lstrip().upper().startswith("INSERT")
        if USE_PG and is_insert:
            cur.execute(_adapt(sql) + " RETURNING id", params)
            new_id = cur.fetchone()["id"]
            conn.commit()
            conn.close()
            return new_id
        cur.execute(_adapt(sql), params)
        conn.commit()
        last_id = getattr(cur, "lastrowid", None)
        conn.close()
        return last_id


def execute_rowcount(sql, params=()):
    """Run an UPDATE and return how many rows changed (for race-safe claims)."""
    with _db_lock:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(_adapt(sql), params)
        rc = cur.rowcount
        conn.commit()
        conn.close()
        return rc


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    # ---- helpers -------------------------------------------------
    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def log_message(self, fmt, *args):
        # Keep the console readable.
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---- routing -------------------------------------------------
    def do_GET(self):
        if self.path.startswith("/api/"):
            return self.handle_api_get()
        # default: serve static files (associate.html, sme.html, dashboard.html, ...)
        if self.path == "/" or self.path == "":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self.handle_api_post()
        self.send_error(404, "Not found")

    # ---- API: GET ------------------------------------------------
    def handle_api_get(self):
        path = self.path.split("?")[0]
        params = {}
        if "?" in self.path:
            for kv in self.path.split("?", 1)[1].split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    params[k] = v

        if path == "/api/queries":
            # Optional filter: ?status=open
            status = params.get("status")
            if status:
                rows = q_all(
                    "SELECT * FROM queries WHERE status = ? ORDER BY id DESC",
                    (status,),
                )
            else:
                rows = q_all("SELECT * FROM queries ORDER BY id DESC")
            # attach answers to each
            for r in rows:
                r["answers"] = q_all(
                    "SELECT * FROM answers WHERE query_id = ? ORDER BY id ASC",
                    (r["id"],),
                )
            return self._send_json({"queries": rows})

        if path == "/api/image":
            # Serve a query's stored image inline so it opens in a browser.
            qid = params.get("id")
            row = q_one("SELECT image FROM queries WHERE id = ?", (qid,))
            if not row or not row.get("image"):
                self.send_error(404, "No image for this query")
                return
            data_url = row["image"]
            # Expected form: data:image/png;base64,XXXX
            try:
                header, b64 = data_url.split(",", 1)
                mime = "image/png"
                if header.startswith("data:") and ";" in header:
                    mime = header[len("data:"):].split(";", 1)[0] or "image/png"
                import base64
                raw = base64.b64decode(b64)
            except Exception:
                self.send_error(500, "Stored image is not decodable")
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Content-Disposition", 'inline; filename="andon_query_%s.png"' % qid)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)
            return

        if path == "/api/query":
            qid = params.get("id")
            row = q_one("SELECT * FROM queries WHERE id = ?", (qid,))
            if not row:
                return self._send_json({"error": "not found"}, 404)
            row["answers"] = q_all(
                "SELECT * FROM answers WHERE query_id = ? ORDER BY id ASC", (qid,)
            )
            return self._send_json(row)

        if path == "/api/stats":
            # Aggregate tracking data.
            per_sme = q_all(
                """
                SELECT sme_login, COUNT(*) AS answered
                FROM answers
                GROUP BY sme_login
                ORDER BY answered DESC
                """
            )
            per_associate = q_all(
                """
                SELECT associate_login, COUNT(*) AS posted
                FROM queries
                GROUP BY associate_login
                ORDER BY posted DESC
                """
            )
            totals = {
                "total_queries": (q_one("SELECT COUNT(*) c FROM queries") or {}).get("c", 0),
                "total_answered": (q_one("SELECT COUNT(DISTINCT query_id) c FROM answers") or {}).get("c", 0),
                "open": (q_one("SELECT COUNT(*) c FROM queries WHERE status='open'") or {}).get("c", 0),
            }
            return self._send_json(
                {"per_sme": per_sme, "per_associate": per_associate, "totals": totals}
            )

        return self._send_json({"error": "unknown endpoint"}, 404)

    # ---- API: POST -----------------------------------------------
    def handle_api_post(self):
        path = self.path.split("?")[0]
        data = self._read_json()

        if path == "/api/queries":
            login = (data.get("associate_login") or "").strip()
            comment = (data.get("comment") or "").strip()
            image = data.get("image")  # optional base64 data URL
            if not login or not comment:
                return self._send_json(
                    {"error": "associate_login and comment are required"}, 400
                )
            qid = execute(
                "INSERT INTO queries (associate_login, comment, image, status, created_at) "
                "VALUES (?, ?, ?, 'open', ?)",
                (login, comment, image, now_iso()),
            )
            return self._send_json({"ok": True, "id": qid})

        if path == "/api/claim":
            qid = data.get("query_id")
            sme = (data.get("sme_login") or "").strip()
            if not qid or not sme:
                return self._send_json({"error": "query_id and sme_login required"}, 400)
            row = q_one("SELECT claimed_by, status FROM queries WHERE id = ?", (qid,))
            if not row:
                return self._send_json({"error": "query not found"}, 404)
            # Race-safe: only claim if currently unclaimed (claimed_by IS NULL).
            changed = execute_rowcount(
                "UPDATE queries SET claimed_by = ?, claimed_at = ?, status = 'claimed' "
                "WHERE id = ? AND claimed_by IS NULL",
                (sme, now_iso(), qid),
            )
            if changed == 0:
                # Someone already holds it (or it moved past open/claimed).
                current = q_one("SELECT claimed_by FROM queries WHERE id = ?", (qid,))
                return self._send_json(
                    {"error": "already_claimed", "claimed_by": (current or {}).get("claimed_by")},
                    409,
                )
            return self._send_json({"ok": True, "claimed_by": sme})

        if path == "/api/release":
            qid = data.get("query_id")
            sme = (data.get("sme_login") or "").strip()
            if not qid or not sme:
                return self._send_json({"error": "query_id and sme_login required"}, 400)
            # Only the current claimer can release, back to 'open'.
            changed = execute_rowcount(
                "UPDATE queries SET claimed_by = NULL, claimed_at = NULL, status = 'open' "
                "WHERE id = ? AND claimed_by = ?",
                (qid, sme),
            )
            if changed == 0:
                return self._send_json({"error": "not_claim_owner"}, 403)
            return self._send_json({"ok": True})

        if path == "/api/answers":
            qid = data.get("query_id")
            sme = (data.get("sme_login") or "").strip()
            text = (data.get("response_text") or "").strip()
            if not qid or not sme or not text:
                return self._send_json(
                    {"error": "query_id, sme_login and response_text are required"}, 400
                )
            existing = q_one("SELECT claimed_by, status FROM queries WHERE id = ?", (qid,))
            if not existing:
                return self._send_json({"error": "query not found"}, 404)
            # Enforce claim: only the SME who claimed it may respond.
            claimer = existing.get("claimed_by")
            if not claimer:
                return self._send_json({"error": "must_claim_first"}, 409)
            if claimer != sme:
                return self._send_json(
                    {"error": "claimed_by_other", "claimed_by": claimer}, 403
                )
            aid = execute(
                "INSERT INTO answers (query_id, sme_login, response_text, created_at) "
                "VALUES (?, ?, ?, ?)",
                (qid, sme, text, now_iso()),
            )
            execute("UPDATE queries SET status = 'answered' WHERE id = ?", (qid,))
            return self._send_json({"ok": True, "id": aid})

        if path == "/api/resolve":
            qid = data.get("query_id")
            if not qid:
                return self._send_json({"error": "query_id required"}, 400)
            execute("UPDATE queries SET status = 'resolved' WHERE id = ?", (qid,))
            return self._send_json({"ok": True})

        return self._send_json({"error": "unknown endpoint"}, 404)


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    backend = "PostgreSQL (DATABASE_URL)" if USE_PG else f"SQLite ({DB_PATH})"
    print(f"Andon server running on port {PORT}")
    print(f"  Associate window ->  http://localhost:{PORT}/associate.html")
    print(f"  SME console      ->  http://localhost:{PORT}/sme.html")
    print(f"  Dashboard        ->  http://localhost:{PORT}/dashboard.html")
    print(f"  Storage backend  ->  {backend}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
