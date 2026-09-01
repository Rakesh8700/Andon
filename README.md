# Andon Support Tool

A practical, self-contained Andon support tool where **associates** post live queries
(image + comment) and **SMEs / experts** answer them, with a **tracking dashboard** that
records which associate posted each query and which SME answered it.

Built with the Python standard library only (no installs) + SQLite for storage.

---

## 1. Running it

From this folder (`Andon/`):

```powershell
py server.py            # runs on port 8900
py server.py 9000       # or pick another port
```

Then open in a browser:

| Page | URL | Who uses it |
|------|-----|-------------|
| Associate window | http://localhost:8900/associate.html | Associates raising queries |
| SME console | http://localhost:8900/sme.html | Experts answering queries |
| Tracking dashboard | http://localhost:8900/dashboard.html | You / managers |

Stop the server with `Ctrl+C` in its terminal.

> Same machine or same network: anyone who can reach `http://<your-ip>:8900` can use it.
> All data is stored in `andon.db` (a single SQLite file in this folder).

---

## 2. The flow

1. **Associate** opens `associate.html`, types their login, presses Enter.
2. Pastes/uploads an image, writes a short comment, presses Enter to submit.
3. They see a "Waiting for SME response" state (auto-refreshes every 2s).
4. **SME** opens `sme.html`, signs in, sees the incoming query, **claims it**, and responds.
5. The associate sees the response and can mark it resolved.

### Claiming (multiple SMEs)

When several SMEs are online, a query must be **claimed** before it can be answered,
so two experts don't work the same one:

- An open query shows a **Claim query** button.
- Once claimed, other SMEs see it locked as **"Claimed by <name>"** and cannot respond.
- Only the SME who claimed it can send a response.
- The claimer can **Release** it back to the queue if they can't help.
- The dashboard and CSV record **who claimed** each query (`claimed_by`), in addition to who answered it.

Query status flow: `open → claimed → answered → resolved`.

---

## 3. How to get the data (who posted / who answered)

There are **three ways**, from easiest to most powerful.

### Option A — The Dashboard (no technical steps)

Open **http://localhost:8900/dashboard.html**. It shows:

- **Answers by SME / Expert** — each SME login and how many queries they answered.
- **Queries by Associate** — each associate login and how many queries they posted.
- **Query History** — every query: who posted it, the comment, status, and **who answered it**.
- **Export CSV** button — downloads `andon_queries.csv` with columns:
  `query_id, associate_login, comment, status, answered_by, answer_texts, image_url, posted_at`.
  The `image_url` column is a clickable link (e.g. `http://localhost:8900/api/image?id=5`) that
  opens the associate's posted (and marked-up) image in a browser. The link works while the
  server is running.

This is the recommended way for day-to-day reporting.

### Option B — The API (for scripts / integrations)

The server exposes JSON endpoints. Example with a browser or `curl`:

- Summary stats:
  ```
  GET http://localhost:8900/api/stats
  ```
  Returns `per_sme` (answers per SME), `per_associate` (posts per associate), and `totals`.

- Full list of queries (each includes its answers):
  ```
  GET http://localhost:8900/api/queries
  ```

### Option C — Query the database directly (most powerful)

The data lives in **`andon.db`**. Two tables:

- `queries(id, associate_login, comment, image, status, claimed_by, claimed_at, created_at)`
- `answers(id, query_id, sme_login, response_text, created_at)`

Open it with Python (already installed), no extra tools needed:

```powershell
py -c "import sqlite3; c=sqlite3.connect('andon.db'); [print(r) for r in c.execute('SELECT sme_login, COUNT(*) FROM answers GROUP BY sme_login ORDER BY 2 DESC')]"
```

Useful ready-made queries:

**1) How many queries each SME answered:**
```sql
SELECT sme_login, COUNT(*) AS queries_answered
FROM answers
GROUP BY sme_login
ORDER BY queries_answered DESC;
```

**2) How many queries each associate posted:**
```sql
SELECT associate_login, COUNT(*) AS queries_posted
FROM queries
GROUP BY associate_login
ORDER BY queries_posted DESC;
```

**3) Full picture — each query, the associate who posted it, and the SME who answered:**
```sql
SELECT q.id,
       q.associate_login,
       q.comment,
       q.status,
       a.sme_login    AS answered_by,
       a.response_text,
       q.created_at   AS posted_at,
       a.created_at   AS answered_at
FROM queries q
LEFT JOIN answers a ON a.query_id = q.id
ORDER BY q.id DESC;
```

To run any of these interactively:

```powershell
py
>>> import sqlite3
>>> c = sqlite3.connect('andon.db')
>>> for row in c.execute("PASTE ONE OF THE SQL QUERIES ABOVE"):
...     print(row)
```

Or install the free **DB Browser for SQLite** app, open `andon.db`, and run the SQL
in a visual editor / export to Excel.

---

## 4. Files

| File | Purpose |
|------|---------|
| `server.py` | Backend: HTTP + SQLite + JSON API |
| `associate.html` | Associate window (login → post query → wait) |
| `sme.html` | SME console (see queries → respond) |
| `dashboard.html` | Tracking + CSV export |
| `andon.db` | SQLite database (created on first run) |

---

## 5. Notes / next steps

- **Login** is a simple typed alias for now (fast, attributes every query/answer). It's
  structured so a real login/SSO can replace `doLogin()` later.
- **Real-time** uses lightweight polling (every ~2s). Fine for this scale.
- To reset all data, stop the server and delete `andon.db` (it will be recreated empty).
- This runs locally / on your network. Deploying to shared Amazon infrastructure with
  SSO would be follow-on work; the code is kept deployment-friendly.
