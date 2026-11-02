import os, json, base64, time, hashlib, requests

auth = os.environ["TRANGER_AUTH"].strip()
parts = auth.split("-----")
bot_id = parts[0].strip()
api_key = parts[1].strip() if len(parts) > 1 else ""
rt = os.environ["TRANGER_REFRESH_TOKEN"].strip()
proxy = os.environ.get("PROXY_SERVER", "").strip()
proxies = {"http": proxy, "https": proxy} if os.environ.get("IS_PROXY") == "true" and proxy else None

print("bot_id:", bot_id[:4] + "***" + bot_id[-2:], "| key_sha:", hashlib.sha256(api_key.encode()).hexdigest()[:16])

s = requests.Session()
if proxies:
    s.proxies.update(proxies)

r = s.post("https://securetoken.googleapis.com/v1/token?key=" + api_key,
           data={"grant_type": "refresh_token", "refresh_token": rt}, timeout=30)
print("refresh:", r.status_code, (r.text[:200] if r.status_code != 200 else "ok"))
tok = r.json().get("id_token", "") if r.status_code == 200 else ""
if tok:
    p = tok.split(".")[1]; p += "=" * (-len(p) % 4)
    info = json.loads(base64.urlsafe_b64decode(p))
    uid = str(info.get("user_id") or info.get("sub"))
    print("aud:", info.get("aud"), "| uid:", uid[:6] + "***" + uid[-4:], "| exp_in:", info.get("exp", 0) - int(time.time()))
    print("provider:", (info.get("firebase") or {}).get("sign_in_provider"), "| email_verified:", info.get("email_verified"))
    h = {"Authorization": "Bearer " + tok, "Origin": "https://cloud.tranger.xyz"}
    for path in [f"/v1/status/{bot_id}", "/v1/projects", "/v1/bots", f"/v1/start-bot/{bot_id}"]:
        try:
            method = "POST" if "start-bot" in path else "GET"
            rr = s.request(method, "https://cloud-api.tranger.xyz" + path, headers=h, timeout=30)
            print(method, path, "->", rr.status_code, rr.text[:220].replace("\n", " "))
        except Exception as e:
            print(method, path, "-> ERR", type(e).__name__, str(e)[:90])
