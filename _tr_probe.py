import os, json, base64, time, hashlib, urllib.parse, requests

auth = os.environ["TRANGER_AUTH"].strip()
parts = auth.split("-----")
bot_id = parts[0].strip()
api_key = parts[1].strip() if len(parts) > 1 else ""
rt = os.environ["TRANGER_REFRESH_TOKEN"].strip()
proxy = os.environ.get("PROXY_SERVER", "").strip()
proxies = {"http": proxy, "https": proxy} if os.environ.get("IS_PROXY") == "true" and proxy else None

print("bot_id:", bot_id[:4] + "***" + bot_id[-2:])
print("api_key sha:", hashlib.sha256(api_key.encode()).hexdigest()[:16], "| len:", len(api_key))
print("proxy:", "on" if proxies else "off")

s = requests.Session()
if proxies:
    s.proxies.update(proxies)
if proxies:
    try:
        print("egress:", s.get("https://api.ipify.org", timeout=20).text)
    except Exception as e:
        print("egress err:", type(e).__name__)

r = s.post("https://securetoken.googleapis.com/v1/token?key=" + api_key,
           data=urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": rt}), timeout=30)
print("refresh:", r.status_code, r.text[:200] if r.status_code != 200 else "ok")
tok = r.json().get("id_token", "") if r.status_code == 200 else ""
if tok:
    p = tok.split(".")[1]; p += "=" * (-len(p) % 4)
    info = json.loads(base64.urlsafe_b64decode(p))
    print("aud:", info.get("aud"), "| iss:", info.get("iss"))
    print("uid:", str(info.get("user_id") or info.get("sub"))[:6] + "***", "| exp_in:", info.get("exp", 0) - int(time.time()))
    print("email_verified:", info.get("email_verified"), "| sign_in_provider:", (info.get("firebase") or {}).get("sign_in_provider"))
    for path in [f"/v1/status/{bot_id}", f"/v1/bots/{bot_id}"]:
        try:
            h = {"Authorization": "Bearer " + tok, "Origin": "https://cloud.tranger.xyz"}
            rr = s.get("https://cloud-api.tranger.xyz" + path, headers=h, timeout=30)
            print("GET", path, "->", rr.status_code, rr.text[:200].replace("\n", " "))
        except Exception as e:
            print("GET", path, "-> ERR", type(e).__name__, str(e)[:100])
