#!/usr/bin/env python3
"""Throwaway account + pure-HTTP adfocus concurrency probe (runs in CI).

Stage A  new account: mail.tm mailbox -> accounts.noprofit.space register ->
         login -> SSO into panel.plugged.host -> calagopus_session cookie
Stage B  N batches of BATCH claims over plain HTTPS (no browser):
         earn BATCH URLs, clear them in parallel, redeem each, report what landed.

Never prints the cookie or the password.
"""
import asyncio
import json
import os
import random
import re
import string
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from curl_cffi import requests as cffi

sys.path.insert(0, os.path.dirname(os.path.abspath(os.environ.get(
    "PLUGGED_SRC", "plugged.py"))))
import plugged as P  # noqa: E402  (panel API layer only)

T0 = time.time()
CHROME = os.environ.get("CHROME_BIN", "/usr/bin/google-chrome")
BATCH = int(os.environ.get("BATCH", "5"))
ROUNDS = int(os.environ.get("ROUNDS", "2"))
PROXY = os.environ.get("PROXY_URL", "")
IMPERSONATE = "chrome131"
UA_CH = {"b": "Chromium/131|Google Chrome/131|Not_A Brand/24", "p": "Windows", "m": 0}

S = requests.Session()
S.trust_env = False


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} │ {msg}", flush=True)


def ok(msg):
    log(f"✅ {msg}")


def bad(msg):
    log(f"❌ {msg}")


def step(msg):
    log(f"── {msg} " + "─" * max(0, 34 - len(msg)))


# ───────────────────────── stage A: throwaway account ─────────────────────────
def mailbox():
    r = S.get("https://api.mail.tm/domains", timeout=30).json()
    dom = r["hydra:member"][0]["domain"]
    user = "pl" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    addr = f"{user}@{dom}"
    pw = "Pw" + "".join(random.choices(string.ascii_letters + string.digits, k=12)) + "!9"
    S.post("https://api.mail.tm/accounts", json={"address": addr, "password": pw},
           timeout=30).raise_for_status()
    S.post("https://api.mail.tm/token", json={"address": addr, "password": pw},
           timeout=30).raise_for_status()
    ok(f"临时邮箱 {addr[:3]}***@{dom}")
    return addr, pw


def js_value(raw):
    for path in (("result", "result", "value"), ("result", "value"), ("value",)):
        cur = raw
        try:
            for k in path:
                cur = cur[k]
            return cur
        except Exception:
            continue
    return None


async def turnstile_token(tab):
    for _ in range(20):
        v = js_value(await tab.execute_script(
            "return (document.querySelector('input[name=\"cf-turnstile-response\"]')||{}).value||''"))
        if v and len(v) > 100:
            return v
        await asyncio.sleep(1.5)
    return ""


async def page_text(tab, limit=400):
    raw = js_value(await tab.execute_script(
        "return (document.body && document.body.innerText || '').replace(/\\s+/g,' ')"
        f".slice(0,{limit})"))
    return raw or ""


async def submit_form(tab, fields, token, label):
    payload = json.dumps(fields)
    info = js_value(await tab.execute_script(f"""
        const f = {payload};
        const missing = [];
        for (const [k, v] of Object.entries(f)) {{
            const el = document.querySelector(`[name="${{k}}"]`);
            if (!el) {{ missing.push(k); continue; }}
            if (el.type === 'checkbox') {{ el.checked = true; }}
            else {{ el.value = v; }}
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
        }}
        const t = document.querySelector('[name="cf-turnstile-response"]');
        if (t) {{
            t.value = {json.dumps(token)};
            t.dispatchEvent(new Event('input', {{bubbles: true}}));
            t.dispatchEvent(new Event('change', {{bubbles: true}}));
        }}
        const legal = document.querySelector('[name="legal_acceptance"]');
        if (legal && !legal.checked) {{ legal.checked = true; }}
        const b = document.querySelector('form button[type=submit]')
            || [...document.querySelectorAll('form button')]
                 .find(x => /register|sign ?up|create|log ?in|continue/i.test(x.innerText||''));
        if (b && b.disabled) {{ b.disabled = false; }}
        return JSON.stringify({{missing: missing, button: b ? (b.innerText||b.type||'').trim().slice(0,30) : null,
            token_len: t ? t.value.length : -1}});
    """))
    log(f"{label} 填表 {info}")
    await asyncio.sleep(1)
    before = await tab.current_url()
    clicked = js_value(await tab.execute_script("""
        const b = document.querySelector('form button[type=submit], form button');
        if (b) { b.click(); return true; }
        return false;
    """))
    if not clicked:
        bad(f"{label} 找不到提交按钮")
        return ""
    for _ in range(15):
        await asyncio.sleep(1)
        url = await tab.current_url()
        if url.split("?")[0] != before.split("?")[0]:
            log(f"{label} 跳转到 {url[:70]}")
            return url
    txt = await page_text(tab)
    bad(f"{label} 未跳转（{before[:60]}）页面：{txt[:240]}")
    return ""


def css_text(html):
    txt = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    txt = re.sub(r"<style.*?</style>", " ", txt, flags=re.S)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


async def read_value(tab, selector):
    return js_value(await tab.execute_script(
        f"return (document.querySelector({json.dumps(selector)})||{{}}).value||''")) or ""


async def fill_field(tab, selector, value, checkbox=False):
    prop = "checked" if checkbox else "value"
    val = "true" if checkbox else json.dumps(value)
    await tab.execute_script(f"""
        const el = document.querySelector({json.dumps(selector)});
        if (el) {{
            el.{prop} = {val};
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
        }}
        return !!el;
    """)


async def fill_fields(tab, fields):
    missing = []
    for selector, value in fields:
        got = await fill_field(tab, selector, value)
        if not got:
            missing.append(selector)
    return missing


def post_form(url, data, cookies):
    s = requests.Session()
    s.trust_env = False
    for c in cookies:
        s.cookies.set(c["name"], c["value"], domain=c.get("domain") or None,
                      path=c.get("path") or "/")
    r = s.post(url, data=data, allow_redirects=False, timeout=45,
               headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                                      "Chrome/131.0.0.0 Safari/537.36",
                        "Origin": "https://accounts.noprofit.space",
                        "Referer": url})
    return r, s


async def signup():
    from pydoll.browser import Chrome
    from pydoll.browser.options import ChromiumOptions

    addr, pw = mailbox()
    nick = "pl" + "".join(random.choices(string.ascii_lowercase, k=5))

    opts = ChromiumOptions()
    opts.headless = False
    opts.start_timeout = 60
    for a in ("--no-sandbox", "--disable-dev-shm-usage", "--window-size=1400,1000"):
        opts.add_argument(a)
    if os.path.exists(CHROME):
        opts.binary_location = CHROME

    cookie = ""
    async with Chrome(options=opts) as browser:
        tab = await browser.start()

        step("注册")
        acc = None
        for attempt in (1, 2):
            async with tab.expect_cloudflare_turnstile(time_to_wait_captcha=90):
                await tab.go_to("https://accounts.noprofit.space/register", timeout=120)
            await asyncio.sleep(2)
            missing = await fill_fields(tab, [
                ('input[name="name"]', nick), ('input[name="email"]', addr),
                ('input[name="password"]', pw),
                ('input[name="password_confirmation"]', pw),
                ('input[name="legal_acceptance"]', "", True)])
            await asyncio.sleep(0.5)
            cookies = await tab.get_cookies()
            csrf = await read_value(tab, 'input[name="_token"]')
            token = await read_value(tab, 'input[name="cf-turnstile-response"]')
            log(f"注册[{attempt}] 缺字段 {missing}｜csrf {len(csrf)}｜token {len(token)}")
            if not token:
                continue
            data = {"_token": csrf, "name": nick, "email": addr,
                    "password": pw, "password_confirmation": pw,
                    "legal_acceptance": "1", "cf-turnstile-response": token}
            r, s = post_form("https://accounts.noprofit.space/register", data, cookies)
            log(f"注册[{attempt}] POST {r.status_code} 跳 "
                f"{r.headers.get('location','')[:60]}")
            if r.status_code in (301, 302, 303):
                acc = s
                break
            body = css_text(r.text)
            hit = re.search(r"(The [a-z ]+ (?:field|must)[^.]{0,120}\.|"
                            r"Security check failed[^.]{0,80}\.|already been taken[^.]{0,60}\.)",
                            body, re.I)
            bad(f"注册被拒：{hit.group(1)[:180] if hit else body[:180]}")
        if acc is None:
            bad("注册没成功")
            return ""

        step("登录")
        for attempt in (1, 2):
            async with tab.expect_cloudflare_turnstile(time_to_wait_captcha=90):
                await tab.go_to("https://accounts.noprofit.space/login", timeout=120)
            await asyncio.sleep(2)
            await fill_fields(tab, [
                ('input[name="login"]', addr), ('input[name="password"]', pw),
                ('input[name="legal_acceptance"]', "", True)])
            await asyncio.sleep(0.5)
            csrf = await read_value(tab, 'input[name="_token"]')
            token = await read_value(tab, 'input[name="cf-turnstile-response"]')
            log(f"登录[{attempt}] csrf {len(csrf)}｜token {len(token)}")
            if not token:
                continue
            r, s2 = post_form("https://accounts.noprofit.space/login", {
                "_token": csrf, "login": addr, "password": pw,
                "legal_acceptance": "1", "cf-turnstile-response": token}, cookies)
            log(f"登录[{attempt}] POST {r.status_code} 跳 "
                f"{r.headers.get('location','')[:60]}")
            if r.status_code in (301, 302, 303):
                acc = s2
                break
            body = css_text(r.text)
            hit = re.search(r"(These credentials[^.]{0,80}\.|Security check failed[^.]{0,80}\.)",
                            body, re.I)
            bad(f"登录被拒：{hit.group(1)[:180] if hit else body[:180]}")

        step("SSO 进面板")
        await tab.go_to("https://accounts.noprofit.space/dashboard", timeout=120)
        await asyncio.sleep(3)
        sso = js_value(await tab.execute_script("""
            const a = [...document.querySelectorAll('a')]
                .find(e => /plugged\\.host/i.test(e.innerText || '') && e.href);
            return a ? a.href : '';
        """))
        log(f"SSO 链接 {'有' if sso else '没有'}")
        if sso:
            r = acc.get(sso, allow_redirects=True, timeout=45)
            log(f"SSO 结束 {r.status_code} {r.url[:60]}")
            for c in acc.cookies:
                if c.name == "calagopus_session" and c.value:
                    cookie = c.value
        if not cookie:
            for c in await tab.get_cookies():
                if c.get("name") == "calagopus_session" and c.get("value"):
                    cookie = c["value"]
        log(f"面板页 {str(await tab.current_url())[:70]}")
    return cookie


# ─────────────────────── stage B: pure-HTTP concurrent claims ──────────────────
def claim_http(url, px):
    """Clear one adfoc.us offer over HTTPS. Returns (claim, detail)."""
    s = cffi.Session(impersonate=IMPERSONATE, proxy=px or None, timeout=30)
    try:
        r = s.get(url)
    except Exception as exc:
        return "", f"tls:{type(exc).__name__}"
    if r.status_code != 200 or len(r.content) < 2000:
        return "", f"http{r.status_code}/{len(r.content)}B"

    key = (re.search(r'id="my_key" value="([^"]+)"', r.text) or [None, ""])[1]
    nx = re.search(r'class="nx-go"[^>]*href="([^"]+)"', r.text)
    click_m = re.search(r'var click_url = "([^"]+)"', r.text)
    inline = re.search(
        r'href="(https://panel\.plugged\.host/account/tokens\?claim=[^"]+)"', r.text)
    hdrs = {"Referer": url, "Origin": "https://adfoc.us"}

    def beacon(body, path):
        try:
            s.post("https://adfoc.us" + path, data=json.dumps(body),
                   headers={"Content-Type": "text/plain;charset=UTF-8", **hdrs},
                   allow_redirects=False)
        except Exception:
            pass

    first = {"k": key, "r": 100, "y": "a", "e": 0,
             "n": {"b": 175, "p": 430, "d": 650, "l": 1200},
             "rf": 1520, "t0": 1200, "c": 1600,
             "u": {"k": 1, "s": 1, "y": 0, "w": 728, "h": 90, "c": -1},
             "fl": -1, "ft": 1, "lb": 0, "v": 1, "hm": 0, "hn": 0, "mt": 0,
             "ti": 6, "cn": 9, "jq": 0, "js": -1, "ss": -1, "ac": 0, "pv": 0,
             "sc": [1400, 1000, 1400, 860, 100], "lg": "en-US",
             "tz": "Asia/Shanghai", "ch": UA_CH, "bt": 0, "g": 1, "a": 1, "ct": 0}

    if nx:
        link = nx.group(1).replace("&amp;", "&")
        target = link if link.startswith("http") else "https://adfoc.us" + link
        try:
            s.post("https://adfoc.us/serve/nx/credit", data={"key": key},
                   headers={**hdrs, "Content-Type":
                            "application/x-www-form-urlencoded; charset=UTF-8",
                            "X-Requested-With": "XMLHttpRequest"},
                   allow_redirects=False)
        except Exception:
            pass
        time.sleep(1.5)
        beacon(first, "/serve/nx/state")
        dwell = random.uniform(12, 17)
        time.sleep(dwell)
        ms = int(1200 + dwell * 1000)
        beacon({"k": key, "r": 100, "y": "b", "x": 1, "ss": ms - 800,
                "sk": ms - 300, "lv": ms, "hm": 0, "ac": 0, "cn": -1}, "/serve/nx/state")
        tpl = "nx"
    elif click_m:
        target = click_m.group(1).replace("&amp;", "&")
        if not target.startswith("http"):
            target = "https://adfoc.us" + target
        first["cn"], first["jq"] = 6, 1
        beacon(first, "/serve/state")
        dwell = random.uniform(12, 17)
        time.sleep(dwell)
        ms = int(1200 + dwell * 1000)
        beacon({"k": key, "r": 100, "y": "b", "x": 2, "ss": ms - 800,
                "sk": ms - 300, "lv": ms, "hm": 0, "ac": 0, "cn": -1}, "/serve/state")
        tpl = "click_url"
    elif inline:
        m = re.search(r"claim=([A-Za-z0-9._-]+)", inline.group(1))
        return (m.group(1) if m else ""), "inline"
    else:
        return "", "unknown-template"

    try:
        r3 = s.get(target, allow_redirects=False, headers={
            "Referer": url,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Site": "same-origin", "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"})
    except Exception as exc:
        return "", f"{tpl}/next-tls:{type(exc).__name__}"
    loc = r3.headers.get("location", "") or ""
    m = re.search(r"claim=([A-Za-z0-9._-]+)", loc) or re.search(
        r"claim=([A-Za-z0-9._-]+)", r3.text or "")
    if not m:
        return "", f"{tpl}/next-{r3.status_code}"
    return m.group(1), tpl


MODE = os.environ.get("MODE", "token").strip().lower()


def main():
    if MODE == "signup":
        step("注册新号")
        cookie = asyncio.run(signup())
        if not cookie:
            bad("注册失败")
            return 1
        with open("/tmp/newsession.txt", "w") as f:
            f.write(f"calagopus_session={cookie}")
        os.chmod("/tmp/newsession.txt", 0o600)
        ok(f"新号可用，会话已落盘（{len(cookie)} 字符）")
        return 0

    if not PROXY:
        bad("PROXY_URL 未设置")
        return 1

    if os.environ.get("PLUGGED_COOKIES"):
        ok("使用已注册的账号跑 token")
        cookie = ""
    else:
        step("阶段 A 新号")
        cookie = asyncio.run(signup())
        if not cookie:
            bad("新号没拿到面板会话")
            return 1
        ok(f"面板会话已建立（{len(cookie)} 字符）")
        os.environ["PLUGGED_COOKIES"] = f"calagopus_session={cookie}"
    api = P.Panel(PROXY)
    bal0, earned0, provs = P.parse_tokens(api.tokens())
    for p in provs:
        if p["name"] in ("adfocus", "linkvertise"):
            log(f"{p['name']} {p['granted']}/{p['cap']} 下一枚 {p['next_reward']}")
    ok(f"起始余额 {bal0:.2f}｜今日已赚 {earned0:.2f}")

    total_ok = 0
    for rnd in range(1, ROUNDS + 1):
        step(f"阶段 B 第 {rnd} 批（{BATCH} 枚）")
        urls, t_earn = [], time.monotonic()
        for i in range(BATCH):
            status, url = api.earn("adfocus")
            if status != "ok" or not url:
                bad(f"earn[{i+1}] {status}")
                break
            urls.append(url)
        log(f"拿到 {len(urls)} 条链接（{time.monotonic() - t_earn:.1f}s，去重 "
            f"{len(set(urls))}）")
        if not urls:
            break

        t0 = time.monotonic()
        with ThreadPoolExecutor(max_workers=len(urls)) as pool:
            cleared = list(pool.map(lambda u: claim_http(u, PROXY), urls))
        claims = [(u, c, d) for u, (c, d) in zip(urls, cleared) if c]
        log(f"清链接 {len(claims)}/{len(urls)}（{time.monotonic() - t0:.1f}s）")

        landed = 0
        for url, claim, detail in claims:
            status, data = api.redeem(claim, {})
            verdict = (data or {}).get("status") if isinstance(data, dict) else None
            amount = (data or {}).get("amount") if isinstance(data, dict) else None
            if status == "ok" and verdict == "granted":
                landed += 1
                log(f"  ✅ {detail} 到账 {amount}")
            else:
                log(f"  ⚠️ {detail} 兑换 {status}/{verdict} {amount}")

        total_ok += landed
        bal, earned, _ = P.parse_tokens(api.tokens())
        log(f"本批到账 {landed} 枚｜余额 {bal:.2f}｜今日已赚 {earned:.2f}")

    bal, earned, provs = P.parse_tokens(api.tokens())
    step("汇总")
    log(f"两批共到账 {total_ok} 枚｜余额 {bal:.2f}｜今日已赚 {earned:.2f}")
    for p in provs:
        if p["name"] in ("adfocus", "linkvertise"):
            log(f"{p['name']} {p['granted']}/{p['cap']} 下一枚 {p['next_reward']}")
    log(f"总耗时 {(time.monotonic() - T0) / 60:.1f} 分钟")
    return 0 if total_ok >= BATCH else 1


if __name__ == "__main__":
    sys.exit(main())
