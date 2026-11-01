import json, os, urllib.request

raw = os.environ.get("Ori_cookies", "").strip()
account = ""
if "-----" in raw:
    account, raw = (p.strip() for p in raw.split("-----", 1))
print("account =", account or "(none)", "| cookie_len =", len(raw))

BASE = "https://panel.orihost.com"
HDR = {
    "Cookie": raw,
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}


def call(path):
    req = urllib.request.Request(BASE + path, headers=HDR)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        code = getattr(e, "code", 0)
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        return code, body or f"{type(e).__name__}"


st, body = call("/api/client")
print("GET /api/client ->", st)
try:
    d = json.loads(body)
    data = d.get("data") or []
    print("  servers:", len(data))
    for s in data:
        a = s.get("attributes") or {}
        print("   -", a.get("identifier"), "|", a.get("name"), "| suspended:", a.get("is_suspended"))
except Exception:
    print("  body:", body[:200])

st2, body2 = call("/api/client/servers/c8e5fc4b")
print("GET /api/client/servers/c8e5fc4b ->", st2)
try:
    d2 = json.loads(body2)
    a2 = d2.get("attributes") or {}
    print("  attribute keys:", sorted(a2.keys())[:30])
    print("  renewal =", a2.get("renewal"), "| suspended =", a2.get("is_suspended"))
except Exception:
    print("  body:", body2[:300])
