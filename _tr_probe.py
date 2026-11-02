import os, json, base64, urllib.parse, requests

auth = os.environ["TRANGER_AUTH"].strip()
parts = auth.split("-----")
bot_id = parts[0].strip()
api_key = parts[1].strip() if len(parts) > 1 else ""
rt = os.environ["TRANGER_REFRESH_TOKEN"].strip()
print("bot_id:", bot_id[:4] + "***" + bot_id[-2:], "| api_key_len:", len(api_key))

r = requests.post("https://securetoken.googleapis.com/v1/token?key=" + api_key,
                  data=urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": rt}),
                  timeout=30)
print("token status:", r.status_code)
d = r.json() if r.status_code == 200 else {}
tok = d.get("id_token", "")
print("expires_in:", d.get("expires_in"), "| project:", d.get("project_id"), "| token_len:", len(tok))
if tok:
    payload = tok.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    info = json.loads(base64.urlsafe_b64decode(payload))
    print("JWT aud:", str(info.get("aud"))[:40], "| iss:", info.get("iss"), "| exp-now:", info.get("exp", 0) - int(__import__("time").time()))
    print("uid:", str(info.get("user_id") or info.get("sub"))[:6] + "***")
    for path in [f"/v1/bots/{bot_id}", f"/v1/status/{bot_id}", f"/v1/bot-status/{bot_id}"]:
        try:
            h = {"authorization": "Bearer " + tok, "content-type": "application/json", "origin": "https://cloud.tranger.xyz", "user-agent": "Mozilla/5.0"}
            rr = requests.get("https://cloud-api.tranger.xyz" + path, headers=h, timeout=30)
            print("GET", path, "->", rr.status_code, rr.text[:160].replace("\n", " "))
        except Exception as e:
            print("GET", path, "-> ERR", type(e).__name__, str(e)[:80])
