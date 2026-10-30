#!/usr/bin/env python3
"""VoteSafe - online voting system. Pure Python 3.8+, no installs needed."""
import json, sqlite3, os, hashlib, secrets, time, re, csv, io, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("VOTE_DB", os.path.join(BASE, "data", "voting.db"))
PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "0.0.0.0")
os.makedirs(os.path.dirname(DB), exist_ok=True)
LOCK = threading.Lock()
SESS, FAILS = {}, {}

def db():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c
def now(): return time.strftime("%Y-%m-%d %H:%M:%S")
def hp(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100000).hex()
def chk(pw, h): return secrets.compare_digest(hp(pw, h.split("$")[0]), h)
def last9(s): return re.sub(r"\D", "", s or "")[-9:]
def nname(s): return re.sub(r"\s+", " ", (s or "").strip()).lower()
def log(c, a, d=""): c.execute("insert into audit(ts,action,detail) values(?,?,?)", (now(), a, d))
def get(c, k): r = c.execute("select v from settings where k=?", (k,)).fetchone(); return r[0] if r else None
def put(c, k, v): c.execute("insert or replace into settings(k,v) values(?,?)", (k, v))

def init():
    c = db()
    c.executescript("""
create table if not exists settings(k text primary key, v text);
create table if not exists positions(id integer primary key autoincrement, name text not null, sort integer default 0);
create table if not exists candidates(id integer primary key autoincrement, position_id integer not null, name text not null, bio text default '');
create table if not exists voters(id integer primary key autoincrement, name text not null, email text unique not null, phone text not null, has_voted integer default 0, voted_at text);
create table if not exists ballots(code text primary key, cast_at text);
create table if not exists votes(id integer primary key autoincrement, ballot_code text, position_id integer, candidate_id integer);
create table if not exists audit(id integer primary key autoincrement, ts text, action text, detail text);""")
    if get(c, "title") is None:
        put(c, "title", "Annual General Elections"); put(c, "status", "draft"); put(c, "admin_hash", hp("Admin@123"))
        sample = {"President": ["Amina Kato", "Joseph Mwesigwa", "Ruth Nankya"], "Vice President": ["Samuel Opio", "Grace Achieng"],
                  "Deputy": ["Patrick Byaruhanga", "Martha Auma"], "Speaker": ["Isaac Lubega", "Esther Namatovu"],
                  "Secretary": ["Doreen Atim", "Brian Mukasa"], "Treasurer": ["Henry Ssebunya", "Lydia Nakato"],
                  "Publicity Secretary": ["Kevin Tumusiime", "Sarah Birungi"]}
        for i, (p, cs) in enumerate(sample.items()):
            cur = c.execute("insert into positions(name,sort) values(?,?)", (p, i))
            for n in cs: c.execute("insert into candidates(position_id,name,bio) values(?,?,?)", (cur.lastrowid, n, "Sample candidate - replace with real details."))
        for n, e, p in [("Alice Namukasa", "alice@example.com", "0772000001"), ("Bob Ochieng", "bob@example.com", "0772000002"),
                        ("Carol Nambi", "carol@example.com", "0772000003"), ("David Mugisha", "david@example.com", "0772000004"),
                        ("Esther Nakato", "esther@example.com", "0772000005")]:
            c.execute("insert into voters(name,email,phone) values(?,?,?)", (n, e, p))
        log(c, "setup", "Database created with sample data")
    c.commit(); c.close()

def results(c):
    out = []
    for p in c.execute("select * from positions order by sort,id").fetchall():
        cs = [dict(id=r["id"], name=r["name"], votes=r["n"]) for r in c.execute(
            "select c.id,c.name,(select count(*) from votes v where v.candidate_id=c.id) n from candidates c where position_id=? order by c.id", (p["id"],))]
        ab = c.execute("select count(*) from votes where position_id=? and candidate_id is null", (p["id"],)).fetchone()[0]
        out.append(dict(id=p["id"], name=p["name"], candidates=cs, abstain=ab))
    return out

class Err(Exception):
    def __init__(s, m, code=400): s.m, s.code = m, code

def locked_out(ip):
    f = FAILS.get(ip)
    return f and f[0] >= 8 and f[1] > time.time()
def fail(ip):
    n = FAILS.get(ip, (0, 0))[0] + 1
    FAILS[ip] = (n, time.time() + 300)
    raise Err("We could not match those details. Please check and try again.", 401)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def out(self, code, obj, ctype="application/json", extra=None):
        b = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        for k, v in {"Content-Type": ctype, "Content-Length": str(len(b)), "Cache-Control": "no-store",
                     "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", **(extra or {})}.items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(b)
    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try: return json.loads(self.rfile.read(min(n, 2000000)) or b"{}")
        except Exception: return {}
    def who(self, role):
        s = SESS.get((self.headers.get("Authorization") or "").replace("Bearer ", ""))
        if s and s[0] == role and s[2] > time.time(): return s
        raise Err("Please log in again.", 401)
    def do_GET(self): self.go("GET")
    def do_POST(self): self.go("POST")
    def go(self, m):
        path = self.path.split("?")[0]
        try:
            if not path.startswith("/api/"):
                if path != "/": return self.out(404, b"Not found", "text/plain")
                return self.out(200, open(os.path.join(BASE, "static", "index.html"), "rb").read(), "text/html; charset=utf-8")
            r = self.api(m, path[5:], self.body() if m == "POST" else {})
            if isinstance(r, tuple): return self.out(200, r[1], r[0], {"Content-Disposition": "attachment; filename=results.csv"})
            self.out(200, r)
        except Err as e: self.out(e.code, {"error": e.m})
        except Exception as e: self.out(500, {"error": "Something went wrong on the server."})

    def api(self, m, p, d):
        ip = self.client_address[0]
        with LOCK:
            c = db()
            try:
                r = self.dispatch(c, m, p, d, ip); c.commit(); return r
            except Exception: c.rollback(); raise
            finally: c.close()

    def dispatch(self, c, m, p, d, ip):
        status = get(c, "status")
        if p == "status": return dict(title=get(c, "title"), status=status)
        if p == "results":
            if status != "closed": raise Err("Results are published when voting closes.", 403)
            return dict(title=get(c, "title"), results=results(c))
        if p == "login":
            if locked_out(ip): raise Err("Too many attempts. Please wait 5 minutes.", 429)
            e = (d.get("email") or "").strip().lower()
            v = c.execute("select * from voters where email=?", (e,)).fetchone()
            if not v or nname(d.get("name")) != nname(v["name"]) or len(last9(d.get("phone"))) < 7 or last9(d.get("phone")) != last9(v["phone"]): fail(ip)
            FAILS.pop(ip, None)
            t = secrets.token_urlsafe(24); SESS[t] = ("voter", v["id"], time.time() + 1800)
            return dict(token=t, name=v["name"])
        if p == "ballot":
            s = self.who("voter"); v = c.execute("select * from voters where id=?", (s[1],)).fetchone()
            pos = [dict(id=x["id"], name=x["name"], candidates=[dict(id=k["id"], name=k["name"], bio=k["bio"]) for k in c.execute(
                "select * from candidates where position_id=? order by id", (x["id"],))]) for x in c.execute("select * from positions order by sort,id")]
            return dict(status=status, title=get(c, "title"), name=v["name"], has_voted=bool(v["has_voted"]), voted_at=v["voted_at"], positions=pos)
        if p == "vote":
            s = self.who("voter")
            if status != "open": raise Err("Voting is not open right now.", 403)
            v = c.execute("select * from voters where id=?", (s[1],)).fetchone()
            if v["has_voted"]: raise Err("You have already voted. A vote cannot be cast twice.", 409)
            ch = d.get("choices") or {}; rows = []
            for x in c.execute("select id from positions").fetchall():
                sel = ch.get(str(x["id"]))
                if sel is None: raise Err("Please make a choice (or abstain) for every position.")
                if sel == "abstain": rows.append((x["id"], None))
                elif c.execute("select 1 from candidates where id=? and position_id=?", (sel, x["id"])).fetchone(): rows.append((x["id"], int(sel)))
                else: raise Err("Invalid choice.")
            code = "VS-" + secrets.token_hex(4).upper()
            if c.execute("update voters set has_voted=1,voted_at=? where id=? and has_voted=0", (now(), v["id"])).rowcount != 1: raise Err("Already voted.", 409)
            c.execute("insert into ballots values(?,?)", (code, now()))
            for pid, cid in rows: c.execute("insert into votes(ballot_code,position_id,candidate_id) values(?,?,?)", (code, pid, cid))
            log(c, "vote", "A ballot was cast (voter identity not recorded with choices)")
            return dict(ok=True, receipt=code)
        # ---------- admin ----------
        if p == "admin/login":
            if locked_out(ip): raise Err("Too many attempts. Please wait 5 minutes.", 429)
            if not chk(d.get("password") or "", get(c, "admin_hash")): fail(ip)
            FAILS.pop(ip, None); t = secrets.token_urlsafe(24); SESS[t] = ("admin", 0, time.time() + 3600)
            return dict(token=t)
        self.who("admin")
        nb = c.execute("select count(*) from ballots").fetchone()[0]
        if p == "admin/dashboard":
            tot = c.execute("select count(*) from voters").fetchone()[0]
            pos = [dict(id=x["id"], name=x["name"], candidates=[dict(id=k["id"], name=k["name"], bio=k["bio"]) for k in c.execute(
                "select * from candidates where position_id=? order by id", (x["id"],))]) for x in c.execute("select * from positions order by sort,id")]
            return dict(title=get(c, "title"), status=status, registered=tot, voted=nb, results=results(c), positions=pos,
                        voters=[dict(r) for r in c.execute("select id,name,email,phone,has_voted,voted_at from voters order by name")],
                        audit=[dict(r) for r in c.execute("select ts,action,detail from audit order by id desc limit 30")])
        if p == "admin/status":
            s = d.get("status")
            if s not in ("draft", "open", "closed"): raise Err("Invalid status.")
            if s == "open" and (c.execute("select count(*) from positions").fetchone()[0] == 0 or c.execute("select count(*) from voters").fetchone()[0] == 0):
                raise Err("Add at least one position and one voter before opening.")
            if s == "draft" and nb: raise Err("Votes already exist, so this election cannot go back to draft.")
            put(c, "status", s); log(c, "status", s); return dict(ok=True)
        if p == "admin/title":
            t = (d.get("title") or "").strip()
            if not t: raise Err("Title cannot be empty.")
            put(c, "title", t[:120]); log(c, "title", t); return dict(ok=True)
        if p == "admin/password":
            n = d.get("new") or ""
            if not chk(d.get("old") or "", get(c, "admin_hash")): raise Err("Current password is wrong.")
            if len(n) < 8: raise Err("New password must be at least 8 characters.")
            put(c, "admin_hash", hp(n)); log(c, "password", "Admin password changed"); return dict(ok=True)
        if p in ("admin/position", "admin/candidate", "admin/delete") and nb: raise Err("Votes have been cast, so positions and candidates are locked.", 409)
        if p == "admin/position":
            n = (d.get("name") or "").strip()
            if not n: raise Err("Enter a position name.")
            c.execute("insert into positions(name,sort) values(?,(select coalesce(max(sort),0)+1 from positions))", (n[:80],)); log(c, "position+", n); return dict(ok=True)
        if p == "admin/candidate":
            n = (d.get("name") or "").strip()
            if not n or not c.execute("select 1 from positions where id=?", (d.get("position_id"),)).fetchone(): raise Err("Enter a candidate name.")
            c.execute("insert into candidates(position_id,name,bio) values(?,?,?)", (d["position_id"], n[:80], (d.get("bio") or "")[:300])); log(c, "candidate+", n); return dict(ok=True)
        if p == "admin/voter":
            n, e, ph = (d.get("name") or "").strip(), (d.get("email") or "").strip().lower(), (d.get("phone") or "").strip()
            if not n or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", e) or len(last9(ph)) < 7: raise Err("Enter a valid name, email and phone number.")
            if c.execute("select 1 from voters where email=?", (e,)).fetchone(): raise Err("That email is already registered.")
            c.execute("insert into voters(name,email,phone) values(?,?,?)", (n[:80], e, ph)); log(c, "voter+", e); return dict(ok=True)
        if p == "admin/import":
            add = skip = 0
            for row in csv.reader(io.StringIO(d.get("csv") or "")):
                if len(row) < 3 or "@" not in row[1]: skip += 1; continue
                e = row[1].strip().lower()
                if c.execute("select 1 from voters where email=?", (e,)).fetchone() or len(last9(row[2])) < 7: skip += 1; continue
                c.execute("insert into voters(name,email,phone) values(?,?,?)", (row[0].strip()[:80], e, row[2].strip())); add += 1
            log(c, "import", f"{add} added, {skip} skipped"); return dict(added=add, skipped=skip)
        if p == "admin/delete":
            t, i = d.get("type"), d.get("id")
            if t == "candidate": c.execute("delete from candidates where id=?", (i,))
            elif t == "position": c.execute("delete from candidates where position_id=?", (i,)); c.execute("delete from positions where id=?", (i,))
            elif t == "voter": c.execute("delete from voters where id=? and has_voted=0", (i,))
            else: raise Err("Invalid request.")
            log(c, "delete", f"{t} {i}"); return dict(ok=True)
        if p == "admin/wipe":
            if status == "open": raise Err("Close voting before clearing data.", 409)
            for t in ("votes", "ballots", "candidates", "positions", "voters"): c.execute(f"delete from {t}")
            put(c, "status", "draft"); log(c, "wipe", "All election data cleared"); return dict(ok=True)
        if p == "admin/export":
            o = io.StringIO(); w = csv.writer(o); w.writerow(["Position", "Candidate", "Votes"])
            for r in results(c):
                for k in r["candidates"]: w.writerow([r["name"], k["name"], k["votes"]])
                w.writerow([r["name"], "(Abstained)", r["abstain"]])
            return ("text/csv", o.getvalue().encode())
        raise Err("Not found.", 404)

if __name__ == "__main__":
    init()
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--reset-admin":
        c = db(); put(c, "admin_hash", hp(sys.argv[2])); c.commit(); print("Admin password reset."); sys.exit()
    print(f"VoteSafe running at http://localhost:{PORT}  (admin password on first run: Admin@123)")
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
