#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zampto 续期"""

import os, sys, time, platform, requests, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from seleniumbase import SB
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

AUTH_URL = "https://auth.zampto.net/sign-in?app_id=bmhk6c8qdqxphlyscztgl"
DASHBOARD_URL = "https://dash.zampto.net/homepage"
OVERVIEW_URL = "https://dash.zampto.net/overview"
SERVER_URL = "https://dash.zampto.net/server?id={}"
OUTPUT_DIR = Path("output/screenshots")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CN_TZ = timezone(timedelta(hours=8))

def cn_now(): return datetime.now(CN_TZ)
def cn_time_str(fmt="%Y-%m-%d %H:%M:%S"): return cn_now().strftime(fmt)

def parse_renewal_time(time_str):
    if not time_str: return "未知"
    try:
        dt = datetime.strptime(time_str, "%b %d, %Y %I:%M %p")
        return dt.replace(tzinfo=timezone.utc).astimezone(CN_TZ).strftime("%Y年%m月%d日 %H时%M分")
    except: return time_str

def calc_expiry_time(renewal_time_str, minutes=2880):
    if not renewal_time_str: return "未知"
    try:
        dt = datetime.strptime(renewal_time_str, "%b %d, %Y %I:%M %p")
        dt = dt.replace(tzinfo=timezone.utc)
        expiry = dt + timedelta(minutes=minutes)
        return expiry.astimezone(CN_TZ).strftime("%Y年%m月%d日 %H时%M分")
    except: return "未知"

def mask(s, show=1):
    if not s: return "***"
    s = str(s)
    return s[:show] + "***" if len(s) > show else s[0] + "***"

def mask_id(sid): return sid[0] + "***" if sid else "****"
def is_linux(): return platform.system().lower() == "linux"

def shot(idx, name):
    return str(OUTPUT_DIR / f"acc{idx}-{cn_now().strftime('%H%M%S')}-{name}.png")

def notify(ok, username, info, img=None):
    token, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not token or not chat: return
    try:
        text = f"{'✅' if ok else '❌'} {'续期成功' if ok else '续期失败'}\n\n账号：{username}\n信息：{info}\n时间：{cn_time_str()}"
        if img and Path(img).exists():
            with open(img, "rb") as f:
                requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                    data={"chat_id": chat, "caption": text}, files={"photo": f}, timeout=60)
        else:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text}, timeout=30)
    except Exception as e:
        print(f"[WARN] 通知失败: {e}")

def parse_accounts(s):
    return [(p[0].strip(), p[1].strip()) for line in s.strip().split('\n') 
            if '----' in line and len(p := line.strip().split('----', 1)) == 2 and p[0].strip() and p[1].strip()]

def detect_turnstile_type(sb):
    try:
        result = sb.execute_script('''
            (function() {
                var container = document.getElementById('turnstileContainer');
                var cfInput = document.querySelector("input[name='cf-turnstile-response']");
                if (!container && !cfInput) return "none";
                var iframes = document.querySelectorAll('iframe');
                for (var i = 0; i < iframes.length; i++) {
                    var src = iframes[i].src || "";
                    if (src.includes("challenges.cloudflare.com") || src.includes("turnstile")) {
                        var rect = iframes[i].getBoundingClientRect();
                        if (rect.width > 100 && rect.height > 50) return "visible";
                    }
                }
                var cfDiv = document.querySelector('.cf-turnstile, [data-sitekey]');
                if (cfDiv) {
                    var rect = cfDiv.getBoundingClientRect();
                    if (rect.width > 100 && rect.height > 50) return "visible";
                }
                if (container) {
                    var rect = container.getBoundingClientRect();
                    if (rect.height > 50) return "visible";
                }
                return "invisible";
            })()
        ''')
        return result or "unknown"
    except: return "visible"

def wait_turnstile_complete(sb, timeout=45):
    print(f"[INFO] 等待验证完成 (最多 {timeout}s)...")
    for i in range(timeout):
        try:
            result = sb.execute_script('''
                (function() {
                    var modal = document.querySelector('.confirmation-modal-content');
                    var container = document.getElementById('turnstileContainer');
                    if (!modal && !container) return "closed";
                    var inputs = document.querySelectorAll("input[name='cf-turnstile-response']");
                    for (var j = 0; j < inputs.length; j++) {
                        if (inputs[j].value && inputs[j].value.length > 20) return "token";
                    }
                    return "waiting";
                })()
            ''')
            if result == "closed":
                print(f"[INFO] ✅ 验证完成，页面已刷新 ({i}s)")
                return "closed"
            elif result == "token":
                print(f"[INFO] ✅ Token 已获取 ({i}s)")
                return "token"
        except:
            print(f"[INFO] ✅ 页面刷新中 ({i}s)")
            return "closed"
        if i % 10 == 0 and i:
            print(f"[INFO] 等待验证... {i}s")
        time.sleep(1)
    return "timeout"

def click_captcha_with_timeout(sb, timeout=20):
    """带超时的验证码点击"""
    print(f"[INFO] 尝试 uc_gui_click_captcha (超时: {timeout}s)...")
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(sb.uc_gui_click_captcha)
            future.result(timeout=timeout)
            print("[INFO] ✅ 已点击验证")
            return True
    except FuturesTimeoutError:
        print(f"[WARN] uc_gui_click_captcha 超时")
    except Exception as e:
        print(f"[WARN] uc_gui_click_captcha 失败: {e}")
    return False

def handle_turnstile(sb, idx):
    time.sleep(3)
    turnstile_type = detect_turnstile_type(sb)
    print(f"[INFO] Turnstile 类型: {turnstile_type}")
    
    if turnstile_type == "none":
        print("[INFO] 未检测到 Turnstile")
        return True
    
    if turnstile_type in ("visible", "unknown"):
        click_captcha_with_timeout(sb, 20)
        time.sleep(3)
    else:
        print("[INFO] Invisible Turnstile - 等待自动验证...")
    
    result = wait_turnstile_complete(sb, 45)
    return result in ("token", "closed")

def login(sb, user, pwd, idx):
    print(f"\n{'='*50}\n[INFO] 账号 {idx}: 登录 {mask(user)}\n{'='*50}")
    last_shot = None
    
    for attempt in range(3):
        try:
            print(f"[INFO] 打开登录页 (尝试 {attempt+1}/3)...")
            sb.uc_open_with_reconnect(AUTH_URL, reconnect_time=8)
            time.sleep(4)
            
            if "dash.zampto.net" in sb.get_current_url():
                print("[INFO] ✅ 已登录")
                return True, None
            
            last_shot = shot(idx, f"01-login-{attempt}")
            sb.save_screenshot(last_shot)
            
            for _ in range(10):
                if 'identifier' in sb.get_page_source(): break
                time.sleep(2)
            
            for sel in ['input[name="identifier"]', 'input[type="email"]', 'input[type="text"]']:
                try:
                    sb.wait_for_element(sel, timeout=5)
                    sb.type(sel, user)
                    print(f"[INFO] 找到输入框: {sel}")
                    break
                except: continue
            else:
                if attempt < 2: continue
                return False, last_shot
            
            time.sleep(1)
            try: sb.click('button[type="submit"]')
            except: sb.click('button')
            time.sleep(4)
            
            for _ in range(15):
                for sel in ['input[name="password"]', 'input[type="password"]']:
                    try:
                        if sb.is_element_visible(sel):
                            sb.type(sel, pwd)
                            print("[INFO] 已输入密码")
                            break
                    except: continue
                else:
                    time.sleep(1)
                    continue
                break
            
            time.sleep(1)
            try: sb.click('button[type="submit"]')
            except: sb.click('button')
            time.sleep(6)
            
            last_shot = shot(idx, "02-result")
            sb.save_screenshot(last_shot)
            
            if "dash.zampto.net" in sb.get_current_url() or "sign-in" not in sb.get_current_url():
                print("[INFO] ✅ 登录成功")
                return True, last_shot
                
        except Exception as e:
            print(f"[WARN] 尝试 {attempt+1} 异常: {e}")
            if attempt < 2: time.sleep(5)
    
    return False, last_shot

def logout(sb):
    try:
        sb.delete_all_cookies()
        sb.open("about:blank")
        time.sleep(1)
        print("[INFO] 已退出登录")
    except: pass

def get_servers(sb, idx):
    print("[INFO] 获取服务器列表...")
    servers, seen = [], set()
    
    sb.open(DASHBOARD_URL)
    time.sleep(5)
    screenshot = shot(idx, "03-dashboard")
    sb.save_screenshot(screenshot)
    
    src = sb.get_page_source()
    if "Access Blocked" in src or "VPN or Proxy Detected" in src:
        return [], "⚠️ 访问被阻止", screenshot
    
    for url in [DASHBOARD_URL, OVERVIEW_URL]:
        if url != DASHBOARD_URL:
            sb.open(url)
            time.sleep(3)
        for sid in re.findall(r'href="[^"]*?/server\?id=(\d+)"', sb.get_page_source()):
            if sid not in seen:
                seen.add(sid)
                servers.append({"id": sid, "name": f"Server {sid}"})
    
    if not servers:
        return [], "⚠️ 未找到服务器", screenshot
    
    print(f"[INFO] 找到 {len(servers)} 个服务器")
    for s in servers:
        print(f"  - ID: {mask_id(s['id'])}")
    return servers, "", screenshot

def renew(sb, sid, idx, username):
    """续期服务器"""
    result = {"server_id": sid, "success": False, "message": "", "screenshot": None,
              "old_time": "", "new_time": "", "expiry_cn": ""}
    
    print(f"\n[INFO] 续期服务器 {mask_id(sid)}...")
    
    sb.open(SERVER_URL.format(sid))
    time.sleep(4)
    
    # 滚动到页面底部，确保加载所有元素
    sb.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(2)
    sb.execute_script("window.scrollTo(0, 0);")
    time.sleep(1)
    
    console_shot = shot(idx, "srv-console")
    sb.save_screenshot(console_shot)
    result["screenshot"] = console_shot
    
    src = sb.get_page_source()
    if "Access Blocked" in src:
        result["message"] = "⚠️ 访问被阻止"
        notify(False, username, "⚠️ 访问被阻止", console_shot)
        return result
    
    # 调试：打印页面关键元素
    debug_info = sb.execute_script('''
        return {
            hasRenewalTime: !!document.getElementById("lastRenewalTime"),
            hasNextRenewal: !!document.getElementById("nextRenewalTime"),
            renewButtons: document.querySelectorAll('a[onclick*="handleServerRenewal"]').length,
            allButtons: Array.from(document.querySelectorAll('a.action-button, button')).map(b => b.textContent.trim().substring(0,20))
        };
    ''')
    print(f"[DEBUG] 页面元素: {debug_info}")
    
    # 获取续期前时间
    old_renewal = ""
    try:
        old_renewal = sb.execute_script('''
            var el = document.getElementById("lastRenewalTime");
            return el ? el.textContent.trim() : "";
        ''') or ""
    except: pass
    
    result["old_time"] = old_renewal
    print(f"[INFO] 续期前时间: {old_renewal or '(空)'}")
    
    # 滚动查找续期按钮
    sb.execute_script("window.scrollTo(0, 500);")
    time.sleep(1)
    
    # 保存滚动后截图
    sb.save_screenshot(shot(idx, "srv-scroll"))
    
    # 点击续期按钮
    try:
        clicked = sb.execute_script(f'''
            (function() {{
                // 方法1: 通过 onclick 属性
                var links = document.querySelectorAll('a[onclick*="handleServerRenewal"]');
                for (var i = 0; i < links.length; i++) {{
                    if (links[i].getAttribute('onclick').includes('{sid}')) {{
                        links[i].click();
                        return "onclick";
                    }}
                }}
                // 方法2: 通过文本内容
                var allElements = document.querySelectorAll('a, button');
                for (var i = 0; i < allElements.length; i++) {{
                    var text = allElements[i].textContent.toLowerCase();
                    if (text.includes('renew') && !text.includes('renewal')) {{
                        allElements[i].click();
                        return "text";
                    }}
                }}
                // 方法3: 通过 class
                var actionBtns = document.querySelectorAll('.action-button, .btn-renew, [class*="renew"]');
                for (var i = 0; i < actionBtns.length; i++) {{
                    if (actionBtns[i].textContent.toLowerCase().includes('renew')) {{
                        actionBtns[i].click();
                        return "class";
                    }}
                }}
                return false;
            }})()
        ''')
        
        print(f"[INFO] 点击结果: {clicked}")
        
        if not clicked:
            # 再次滚动尝试
            sb.execute_script("window.scrollTo(0, 1000);")
            time.sleep(2)
            sb.save_screenshot(shot(idx, "srv-scroll2"))
            
            result["message"] = "⚠️ 未找到续期按钮"
            notify(False, username, f"服务器: {mask_id(sid)} | ⚠️ 未找到按钮", console_shot)
            return result
            
    except Exception as e:
        result["message"] = f"⚠️ 点击失败: {e}"
        notify(False, username, f"服务器: {mask_id(sid)} | ⚠️ 点击失败", console_shot)
        return result
    
    print("[INFO] 已点击续期按钮，等待验证...")
    time.sleep(2)
    sb.save_screenshot(shot(idx, "srv-modal"))
    
    # 处理 Turnstile
    handle_turnstile(sb, idx)
    
    time.sleep(3)
    
    # 刷新页面获取新时间
    sb.open(SERVER_URL.format(sid))
    time.sleep(4)
    
    new_renewal = ""
    remain = ""
    try:
        new_renewal = sb.execute_script('''
            var el = document.getElementById("lastRenewalTime");
            return el ? el.textContent.trim() : "";
        ''') or ""
        remain = sb.execute_script('''
            var el = document.getElementById("nextRenewalTime");
            return el ? el.textContent.trim() : "";
        ''') or ""
    except: pass
    
    result["new_time"] = new_renewal
    result["expiry_cn"] = calc_expiry_time(new_renewal)
    
    print(f"[INFO] 续期后时间: {new_renewal or '(空)'}, 剩余: {remain or '(空)'}")
    
    # 判断是否成功
    today = datetime.now().strftime('%b %d, %Y')
    if new_renewal and new_renewal != old_renewal:
        result["success"] = True
        result["message"] = f"续期成功！到期: {result['expiry_cn']}"
    elif today in str(new_renewal):
        result["success"] = True
        result["message"] = f"今日已续期，到期: {result['expiry_cn']}"
    elif remain and ("1 day" in remain or "2 day" in remain or "hour" in remain):
        result["success"] = True
        result["message"] = f"续期成功！到期: {result['expiry_cn']}"
    else:
        result["message"] = f"⚠️ 状态未知 | {parse_renewal_time(new_renewal)}"
    
    time.sleep(2)
    final_shot = shot(idx, "srv-result")
    sb.save_screenshot(final_shot)
    result["screenshot"] = final_shot
    
    if result["success"]:
        notify(True, username, f"服务器: {mask_id(sid)} | 到期: {result['expiry_cn']}", final_shot)
    else:
        notify(False, username, f"服务器: {mask_id(sid)} | {result['message']}", final_shot)
    
    print(f"[INFO] {'✅' if result['success'] else '⚠️'} {result['message']}")
    return result

def process(sb, user, pwd, idx):
    result = {"username": user, "success": False, "message": "", "servers": []}
    
    login_ok, login_shot = login(sb, user, pwd, idx)
    if not login_ok:
        result["message"] = "登录失败"
        notify(False, user, "⚠️ 登录失败", login_shot)
        return result
    
    servers, error, dashboard_shot = get_servers(sb, idx)
    if error:
        result["message"] = error
        notify(False, user, error, dashboard_shot)
        logout(sb)
        return result
    
    for srv in servers:
        try:
            r = renew(sb, srv["id"], idx, user)
            r["name"] = srv.get("name", srv["id"])
            result["servers"].append(r)
            time.sleep(3)
        except Exception as e:
            err_shot = shot(idx, "error")
            sb.save_screenshot(err_shot)
            print(f"[ERROR] 服务器 {mask_id(srv['id'])} 异常: {e}")
            result["servers"].append({"server_id": srv["id"], "success": False, "message": str(e)})
            notify(False, user, f"服务器: {srv['id']} | ⚠️ {e}", err_shot)
    
    ok = sum(1 for s in result["servers"] if s.get("success"))
    result["success"] = ok > 0
    result["message"] = f"{ok}/{len(result['servers'])} 成功"
    
    logout(sb)
    return result

def main():
    acc_str = os.environ.get("ZAMPTO_ACCOUNT", "")
    if not acc_str:
        print("[ERROR] 缺少 ZAMPTO_ACCOUNT"); sys.exit(1)
    
    accounts = parse_accounts(acc_str)
    if not accounts:
        print("[ERROR] 无有效账号"); sys.exit(1)
    
    print(f"[INFO] {len(accounts)} 个账号")
    
    proxy = os.environ.get("PROXY_SOCKS5", "")
    if proxy:
        try:
            requests.get("https://api.ipify.org", proxies={"http": proxy, "https": proxy}, timeout=10)
            print("[INFO] 代理连接正常")
        except Exception as e:
            print(f"[WARN] 代理测试失败: {e}")
    
    results = []
    
    # SB 参数
    sb_args = {"uc": True, "locale": "en"}
    if is_linux():
        sb_args["xvfb"] = True
        sb_args["headed"] = False
        print("[INFO] Linux 模式: xvfb + headless")
    if proxy:
        sb_args["proxy"] = proxy
        print("[INFO] 使用代理")
    
    try:
        with SB(**sb_args) as sb:
            for i, (u, p) in enumerate(accounts, 1):
                try:
                    r = process(sb, u, p, i)
                    results.append(r)
                    time.sleep(3)
                except Exception as e:
                    err_shot = shot(i, "fatal")
                    try: sb.save_screenshot(err_shot)
                    except: err_shot = None
                    print(f"[ERROR] 账号 {mask(u)} 异常: {e}")
                    results.append({"username": u, "success": False, "message": str(e), "servers": []})
                    notify(False, u, f"⚠️ {e}", err_shot)
    except Exception as e:
        print(f"[ERROR] 脚本异常: {e}")
        sys.exit(1)
    
    ok_acc = sum(1 for r in results if r.get("success"))
    total_srv = sum(len(r.get("servers", [])) for r in results)
    ok_srv = sum(sum(1 for s in r.get("servers", []) if s.get("success")) for r in results)
    
    print(f"\n{'='*50}")
    print(f"📊 账号: {ok_acc}/{len(results)} | 服务器: {ok_srv}/{total_srv}")
    for r in results:
        print(f"{'✅' if r.get('success') else '❌'} {mask(r['username'])}: {r.get('message','')}")
        for s in r.get("servers", []):
            print(f"  {'✓' if s.get('success') else '✗'} {mask_id(s['server_id'])}: {s.get('message','')}")
    print(f"{'='*50}")
    
    sys.exit(0 if ok_srv > 0 else 1)

if __name__ == "__main__":
    main()
