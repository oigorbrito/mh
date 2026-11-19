"""Stamp each pair with the connection its session ran on (the session's last_connection, read
from GET /v1/sessions/{id}), so the provider column says what actually served the run.
Usage: BASE=https://your-instance HR_API_KEY=... python3 fill-connection.py results-A.json results-B.json"""
import json, os, ssl, sys, urllib.request
BASE = os.environ["BASE"].rstrip("/"); KEY = os.environ["HR_API_KEY"]
CTX = ssl._create_unverified_context() if os.environ.get("IGNORE_TLS") == "1" else None
def session(sid):
    req = urllib.request.Request(f"{BASE}/api/harness/v1/sessions/{sid}", headers={"authorization": f"Bearer {KEY}"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60, context=CTX).read().decode())
    except Exception as e:  # noqa: BLE001
        print(sid, "not read:", str(e)[:80]); return {}
failed = []
for path in sys.argv[1:]:
    # A file that cannot be read is named and skipped, never silently: the run's matrix is then incomplete,
    # and the exit status says so.
    try:
        with open(path) as f: res = json.load(f)
    except (OSError, ValueError) as e:
        print(path, "not read, skipped:", str(e)[:120], file=sys.stderr); failed.append(path); continue
    n = 0
    for k, r in res.items():
        sid = r.get("sid")
        if not sid or r.get("connection"): continue
        v = session(sid).get("last_connection") or ""
        if v: r["connection"] = v; n += 1
    # Written beside the file and moved over it, so an interrupted or failed write leaves the original as it was.
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f: json.dump(res, f, indent=1)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp): os.remove(tmp)
        raise
    print(path, "stamped", n)
sys.exit(1 if failed else 0)
