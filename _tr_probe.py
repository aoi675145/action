import os, json, base64, time, hashlib, requests

auth = os.environ["TRANGER_AUTH"].strip()
parts = auth.split("-----")
bot_id, api_key = parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")
rt = os.environ["TRANGER_REFRESH_TOKEN"].strip()
proxy = os.environ.get("PROXY_SERVER", "").strip()
proxies = {"http": proxy, "https": proxy} if os.environ.get("IS_PROXY") == "true" and proxy else None
s = requests.Session()
if proxies: s.proxies.update(proxies)

r = s.post("https://securetoken.googleapis.com/v1/token?key=" + api_key,
           data={"grant_type": "refresh_token", "refresh_token": rt}, timeout=30)
tok = r.json().get("id_token", "") if r.status_code == 200 else ""
print("refresh:", r.status_code, "| token_len:", len(tok))
if not tok: raise SystemExit(1)

# 1) 用户记录
lk = s.post("https://identitytoolkit.googleapis.com/v1/accounts:lookup?key=" + api_key,
            json={"idToken": tok}, timeout=30)
print("lookup:", lk.status_code, lk.text[:400].replace("\n", " "))

h = {"Authorization": "Bearer " + tok, "Origin": "https://cloud.tranger.xyz",
     "Accept": "application/json, text/plain, */*",
     "Referer": "https://cloud.tranger.xyz/",
     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"}
for path in [f"/v1/status/{bot_id}", "/v1/status/00000000", "/v1/status/ffffffff"]:
    rr = s.get("https://cloud-api.tranger.xyz" + path, headers=h, timeout=30)
    print("GET", path, "->", rr.status_code, rr.text[:150].replace("\n", " "))
