#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import requests
from datetime import datetime, timezone, timedelta

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"

# ====================== 配置 ======================
FREEMCHOST = os.getenv("FREEMCHOST", "")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")
FREEMCHOST_SERVERS_ID = os.getenv("FREEMCHOST_SERVERS_ID", "")
FREEMCHOST_PROXY_NODE = os.getenv("FREEMCHOST_PROXY_NODE", "")

if "-----" not in FREEMCHOST:
    raise ValueError("FREEMCHOST 格式错误，应为 email-----password")
FREEMCHOST_EMAIL, FREEMCHOST_PWD = FREEMCHOST.split("-----", 1)

SUPABASE_URL = "https://laehfeigoiycigkfknfn.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxhZWhmZWlnb2l5Y2lna2ZrbmZuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODAyNzk1NTgsImV4cCI6MjA5NTg1NTU1OH0.r-CQTnTFWYj5Vawvn1Ky91QnPJMcp1feIRFWJrhq7T8"
BASE_URLS = ["https://freemchost.com", "https://new.freemchost.com"]
SERVER_INFO_FN = "c3a45c08362f2f613bbb6d511a3733a9e85e561709d48bec9280e82a4aa4f47d"
DWELL_FN = "8a85876cf1da47edc9a524dcba6145449f36592433445062fd5cb967b0bc9453"   # 取续期确认码（dwell）
RENEW_FN = "798181797bd95a02dee916a26c18d3539a58152db8660e097ca48d7cdd8ee50c"   # 带确认码确认续期
RENEW_AHEAD_HOURS = 46     # 到期前 46 小时（站点免费续期开窗时间，window_hours）触发续期，同时是下次 cron 的安排点
RENEW_MIN_GAP_HOURS = 12   # 续期成功后与下次检查的最小间隔（续期一次 +60h，正常不会触发，纯保险）


# ====================== 工具函数 ======================
def now_str():
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    print(msg, flush=True)


def send_tg(msg):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        log("⚠️ 未配置 TG 信息，跳过通知")
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                      json={"chat_id": TG_CHAT_ID, "text": msg}, timeout=10)
        log("📤 TG 通知已发送")
    except Exception as e:
        log(f"⚠️ TG 发送失败: {e}")


def tss_find(obj, key):
    if not isinstance(obj, dict) or "p" not in obj:
        return None
    k_list = obj["p"].get("k", [])
    v_list = obj["p"].get("v", [])
    if key in k_list:
        idx = k_list.index(key)
        if idx < len(v_list):
            v = v_list[idx]
            return v["s"] if isinstance(v, dict) and "s" in v else v
    for v in v_list:
        if isinstance(v, dict):
            r = tss_find(v, key)
            if r is not None:
                return r
    return None


def tss_body(fields):
    """按 TSS 编码构造 serverFn 请求体。fields: [(key, value), ...]"""
    keys = "[" + ",".join('"%s"' % k for k, _ in fields) + "]"
    vals = []
    for _, v in fields:
        if isinstance(v, bool):
            vals.append('{"t":2,"s":%d}' % (3 if v else 2))
        elif isinstance(v, (int, float)):
            vals.append('{"t":0,"s":%s}' % v)
        else:
            vals.append('{"t":1,"s":"%s"}' % v)
    values = "[" + ",".join(vals) + "]"
    return ('{"t":{"t":10,"i":0,"p":{"k":["data"],"v":['
            '{"t":10,"i":1,"p":{"k":%s,"v":%s},"o":0}'
            ']},"o":0},"f":63,"m":[]}' % (keys, values))


def tss_node(obj, key):
    """取原始 TSS 节点（保留 t 类型），用于判断布尔字段。"""
    if not isinstance(obj, dict) or "p" not in obj:
        return None
    k_list = obj["p"].get("k", [])
    v_list = obj["p"].get("v", [])
    if key in k_list:
        idx = k_list.index(key)
        if idx < len(v_list):
            return v_list[idx]
    for v in v_list:
        if isinstance(v, dict):
            r = tss_node(v, key)
            if r is not None:
                return r
    return None


def tss_is_true(node):
    """TSS 布尔：{"t":2,"s":3}=true，{"t":2,"s":2}=false（其余按真值判断）。"""
    if isinstance(node, dict) and node.get("t") == 2:
        return node.get("s") == 3
    return bool(node)


def safe_error_text(value, session=None):
    text = str(value)
    secrets = [FREEMCHOST, FREEMCHOST_EMAIL, FREEMCHOST_PWD,
               FREEMCHOST_SERVERS_ID, FREEMCHOST_PROXY_NODE,
               TG_BOT_TOKEN, TG_CHAT_ID, SUPABASE_ANON_KEY]
    if session is not None:
        authorization = session.headers.get("Authorization", "")
        secrets.extend([authorization, authorization.removeprefix("Bearer ")])
        secrets.extend(cookie.value for cookie in session.cookies)
    for secret in sorted(filter(None, secrets), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"https?://\S+|socks5?h?://\S+", "[URL]", text)
    text = re.sub(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+", "[TOKEN]", text)
    text = re.sub(r"(?i)\b(bearer\s+)\S+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)\b(password|token|cookie|secret|apikey|api_key)\b\s*[:=]\s*[^\s,;]+",
                  r"\1=[REDACTED]", text)
    return " ".join(text.split())[:500]


def tss_error_details(data, session):
    errors = []
    fields = ("message", "code", "status", "statusCode")

    def collect(node):
        details = []
        if isinstance(node, dict):
            for key in fields:
                value = node.get(key)
                if isinstance(value, dict):
                    value = value.get("s")
                if isinstance(value, (str, int, float)):
                    details.append(f"{key}={safe_error_text(value, session)}")
            props = node.get("p")
            if isinstance(props, dict):
                keys, values = props.get("k", []), props.get("v", [])
                if isinstance(keys, list) and isinstance(values, list):
                    for key, value in zip(keys, values):
                        if key in fields:
                            if isinstance(value, dict):
                                value = value.get("s")
                            if isinstance(value, (str, int, float)):
                                details.append(f"{key}={safe_error_text(value, session)}")
            for value in node.values():
                details.extend(collect(value))
        elif isinstance(node, list):
            for value in node:
                details.extend(collect(value))
        return details

    def walk(node):
        if isinstance(node, dict):
            if node.get("c") == "$TSR/Error":
                details = list(dict.fromkeys(collect(node)))
                errors.append("; ".join(details) if details else "未能解析 TSS 错误字段（不代表服务端未提供原因）")
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return errors


def call_server_fn(session, fn_id, body):
    errors = []
    for base in BASE_URLS:
        try:
            r = session.post(
                f"{base}/_serverFn/{fn_id}",
                headers={
                    "x-tsr-serverfn": "true",
                    "Content-Type": "application/json",
                    "Origin": base,
                    "Referer": f"{base}/",
                },
                data=body,
                timeout=20,
            )
            if r.status_code == 200:
                data = r.json()
                details = tss_error_details(data, session)
                if details:
                    errors.append(f"{base}: HTTP {r.status_code}, TSS error: "
                                  + " | ".join(details)[:1000])
                    continue
                return data
            errors.append(f"{base}: HTTP {r.status_code}")
        except Exception as e:
            errors.append(f"{base}: {safe_error_text(e, session)}")
    raise Exception("接口调用失败: " + " | ".join(errors))


def call_renew(session, api_body):
    """两步续期（字段与站点前端 app.servers._serverId 一致）：
    ① dwell 接口取 token（renewable=false 说明还没到开窗时间，直接跳过）
    ② 等待 min_dwell_ms ③ 带 token + dwell_ms + 蜜罐 hp（留空）确认续期。"""
    start_raw = call_server_fn(session, DWELL_FN, api_body)
    if not tss_is_true(tss_node(start_raw, "renewable")):
        raise Exception("当前不在免费续期开放窗口（renewable=false）")
    token = tss_find(start_raw, "token")
    if not token:
        raise Exception(f"未取到续期确认码: {start_raw}")
    try:
        wait_s = float(tss_find(start_raw, "min_dwell_ms") or 600) / 1000 + 1.0
    except (TypeError, ValueError):
        wait_s = 1.6
    wait_s = max(1.0, wait_s)
    t0 = time.monotonic()
    log(f"⏱ 已取到确认码，等待 {wait_s:.1f}s 后确认...")
    time.sleep(wait_s)
    dwell_ms = int((time.monotonic() - t0) * 1000)
    body = tss_body([("id", FREEMCHOST_SERVERS_ID), ("token", token),
                     ("hp", ""), ("dwell_ms", dwell_ms)])
    return call_server_fn(session, RENEW_FN, body)


# ====================== 自动改 cron ======================
def plan_next_run(expires_at, renew_failed):
    """正常：下次运行 = 最新到期时间前 RENEW_AHEAD_HOURS 小时，且与本次至少间隔
    RENEW_MIN_GAP_HOURS；续期未开放/失败：2 小时后重试（不超过到期前 30 分钟）。"""
    now = datetime.now(timezone.utc)
    if renew_failed:
        target = min(now + timedelta(hours=2), expires_at - timedelta(minutes=30))
        if target <= now + timedelta(minutes=10):
            target = now + timedelta(minutes=15)
        return target
    return max(expires_at - timedelta(hours=RENEW_AHEAD_HOURS),
               now + timedelta(hours=RENEW_MIN_GAP_HOURS))


def write_next_run(target_utc):
    """把下次运行时间写成一次性 cron（M H D M *），供工作流"修改 cron"步骤回写 yml。"""
    cron = f"{target_utc.minute} {target_utc.hour} {target_utc.day} {target_utc.month} *"
    try:
        with open("next_run.txt", "w", encoding="utf-8") as fh:
            fh.write(cron)
        bj = (target_utc + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
        log(f"📅 下次运行: {bj} (北京时间) → cron: {cron}")
    except Exception as e:
        log(f"⚠️ 写入 next_run.txt 失败: {safe_error_text(e)}")
    return cron


# ====================== 主逻辑 ======================
def main():
    log("")
    log("#" * 25)
    log("   Freemchost 自动续期 (API 直连)")
    log("#" * 25)
    log("")
    log(f"🕐 运行时间: {now_str()} (北京时间)")

    try:
        if not FREEMCHOST_PROXY_NODE:
            raise ValueError("FREEMCHOST_PROXY_NODE 未设置，代理是必须的")
        PROXY = {"http": FREEMCHOST_PROXY_NODE, "https": FREEMCHOST_PROXY_NODE}
        log("⚙️ 代理已启用")

        # ---------- 1. 创建浏览器风格 Session 并验证出口 IP ----------
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": UA,
            "Accept": "application/x-tss-framed, application/x-ndjson, application/json, text/html, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        sess.proxies.update(PROXY)

        log("🌐 验证出口 IP...")
        try:
            ip = (sess.get("https://api.ipify.org/?format=json", timeout=10).json().get("ip") or "").strip()
            m = re.match(r"(\d+\.\d+)\.\d+\.\d+$", ip)
            if m:
                ip_masked = m.group(1) + ".**.**"
            elif ":" in ip:  # IPv6 同样只显示前两段
                seg = ip.split(":")
                ip_masked = f"{seg[0]}:{seg[1] if len(seg) > 1 else ''}:****"
            else:
                ip_masked = "***"
            log(f"📍 出口 IP 确认：{ip_masked}")
        except Exception as e:
            log(f"⚠️ IP 验证失败: {safe_error_text(e)}")

        # ---------- 2. Supabase 登录 ----------
        log("🔐 Supabase 登录中...")
        r = sess.post(
            f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
            headers={"apikey": SUPABASE_ANON_KEY},
            json={"email": FREEMCHOST_EMAIL, "password": FREEMCHOST_PWD},
            timeout=30,
        )
        if r.status_code != 200:
            raise Exception(f"登录失败 ({r.status_code}): {r.text[:200]}")
        token = r.json().get("access_token")
        if not token:
            raise Exception("登录响应中未找到 access_token")
        log("✅ 登录成功，Token 已获取")

        # ---------- 3. 访问站点获取会话 Cookie ----------
        log("🍪 获取站点会话...")
        sess.headers["Authorization"] = f"Bearer {token}"
        session_ok = False
        for base in BASE_URLS:
            try:
                r = sess.get(base, timeout=15)
                if r.status_code in (200, 301, 302):
                    session_ok = True
                    log(f"✅ 会话已获取 ({base})")
                    break
            except Exception:
                continue
        if not session_ok:
            log("⚠️ 未能获取站点会话，继续尝试 API...")

        api_body = tss_body([("id", FREEMCHOST_SERVERS_ID)])

        # ---------- 4. 查服务器信息 ----------
        log("🔍 查询服务器信息...")
        raw = call_server_fn(sess, SERVER_INFO_FN, api_body)
        expires_str = tss_find(raw, "expires_at")
        if not expires_str:
            raise Exception(f"无法解析 expires_at: {raw}")
        expires_at = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
        now_utc = datetime.now(timezone.utc)
        remain = expires_at - now_utc
        old_label = f"{remain.days}d {remain.seconds // 3600}h {(remain.seconds % 3600) // 60}m"
        log(f"📅 到期: {expires_str}，剩余: {old_label}")

        # ---------- 5. 续期（剩余 ≤ 46 小时、站点开窗就触发） ----------
        threshold = timedelta(hours=RENEW_AHEAD_HOURS)
        renew_failed = False
        new_label = old_label
        result_status = "无需续期"
        if remain <= threshold:
            log(f"🔄 剩余 {old_label}，调用续期 API...")
            try:
                renew_raw = call_renew(sess, api_body)
                new_expires_str = tss_find(renew_raw, "expires_at")
            except Exception as e:
                log(f"⚠️ 续期接口未开放或调用失败: {safe_error_text(e, sess)}")
                result_status = "续期未开放"
                renew_failed = True
            else:
                if new_expires_str:
                    new_expires = datetime.fromisoformat(new_expires_str.replace("Z", "+00:00"))
                    new_remain = new_expires - now_utc
                    new_label = f"{new_remain.days}d {new_remain.seconds // 3600}h {(new_remain.seconds % 3600) // 60}m"
                    if new_remain.total_seconds() > remain.total_seconds():
                        log(f"✅ 续期成功: {old_label} → {new_label}")
                        result_status = "续期成功"
                        expires_at = new_expires
                    else:
                        log("⚠️ 续期 API 返回了 expires_at 但时间未增加")
                        result_status = "续期失败"
                        renew_failed = True
                else:
                    log(f"⚠️ 续期 API 返回异常: {renew_raw}")
                    result_status = "续期失败"
                    renew_failed = True
        else:
            log(f"⏳ 剩余 {old_label}，未到 {RENEW_AHEAD_HOURS} 小时阈值，无需续期")

        # ---------- 6. 自动改 cron：下次运行 = 最新到期时间前 46 小时 ----------
        next_run = plan_next_run(expires_at, renew_failed)
        next_cron = write_next_run(next_run)

        # ---------- 7. TG 通知 ----------
        result_icon = {"续期成功": "✅续期成功", "续期失败": "⚠️续期失败", "续期未开放": "⚠️续期未开放"}
        lines = [
            "🎮 Freemchost 续期通知",
            f"⏰ 通知时间：{now_str()}",
            f"👤 账号：{FREEMCHOST_EMAIL}",
            f"📅 利用期限：{new_label}",
        ]
        lines.append(f"📊 执行结果：{result_icon.get(result_status, result_status)}")
        send_tg("\n".join(lines))

    except Exception as e:
        # 出错也要安排下次运行（2 小时后重试），否则 cron 停在上一次时间
        write_next_run(datetime.now(timezone.utc) + timedelta(hours=2))
        log(f"❌ {e}")
        send_tg(f"🎮 Freemchost 续期通知\n⏰ 通知时间：{now_str()}\n👤 账号：{FREEMCHOST_EMAIL}\n📅 利用期限：{locals().get('new_label', locals().get('old_label', 'N/A'))}\n📊 执行结果：❌{e}")
        raise


if __name__ == "__main__":
    main()
