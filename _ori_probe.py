import json, os, urllib.request

raw = os.environ.get("Ori_cookies", "").strip()
if "-----" in raw:
    _, raw = (p.strip() for p in raw.split("-----", 1))
BASE = "https://panel.orihost.com"
HDR = {"Cookie": raw, "Accept": "application/json", "X-Requested-With": "XMLHttpRequest",
       "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"}

def call(p):
    try:
        with urllib.request.urlopen(urllib.request.Request(BASE + p, headers=HDR), timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        body = ""
        try: body = e.read().decode("utf-8", "replace")
        except Exception: pass
        return getattr(e, "code", 0), body or type(e).__name__

for path in ["/api/client", "/api/client/", "/api/client/servers"]:
    st, body = call(path)
    print(f"GET {path} -> {st}")
    if st == 200:
        try:
            d = json.loads(body); data = d.get("data") or []
            print("   count:", len(data), "| ids:", [((x.get("attributes") or {}).get("identifier")) for x in data])
        except Exception as ex:
            print("   parse fail", ex)

st, body = call("/api/client/servers/cf61b300")
print("GET /api/client/servers/cf61b300 ->", st)
try:
    a = (json.loads(body).get("attributes") or {})
    print("   keys:", sorted(a.keys())[:28])
    print("   renewal =", a.get("renewal"), "| suspended =", a.get("is_suspended"), "| identifier =", a.get("identifier"))
except Exception:
    print("   body:", body[:200])
