#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zampto 续期"""

import os, sys, time, platform, requests, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
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
        expiry = dt.replace(tzinfo=timezone.utc) + timedelta(minutes=minutes)
        return expiry.astimezone(CN_TZ).strftime("%Y年%m月%d日 %H时%M分")
    except: return "未知"

def mask(s, show=1):
    if not s: return "***"
    s = str(s)
    return s[:show] + "***" if len(s) > show else s[0] + "***"

def mask_id(sid): return str(sid)[0] + "***" if sid else "****"
def is_linux(): return platform.system().lower() == "linux"
def shot(idx, name): return str(OUTPUT_DIR / f"acc{idx}-{cn_now().strftime('%H%M%S')}-{name}.png")

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

def js_get_element_text(sb, element_id):
    """安全获取元素文本"""
    try:
        el = sb.find_element(f"#{element_id}")
        return el.text.strip() if el else ""
    except:
        return ""

def wait_turnstile_complete(sb, timeout=45):
    print(f"[INFO] 等待验证完成 (最多 {timeout}s)...")
    for i in range(timeout):
        try:
            # 检查弹窗是否还在
            modals = sb.find_elements(".confirmation-modal-content")
            containers = sb.find_elements("#turnstileContainer")
            if not modals and not containers:
                print(f"[INFO] ✅ 验证完成 ({i}s)")
                return "closed"
            
            # 检查 token
            inputs = sb.find_elements("input[name='cf-turnstile-response']")
            for inp in inputs:
                val = inp.get_attribute("value") or ""
                if len(val) > 20:
                    print(f"[INFO] ✅ Token 已获取 ({i}s)")
                    return "token"
        except:
            return "closed"
        
        if i % 10 == 0 and i:
            print(f"[INFO] 等待验证... {i}s")
        time.sleep(1)
    return "timeout"

def click_captcha_with_timeout(sb, timeout=20):
    print(f"[INFO] 尝试点击验证码 (超时: {timeout}s)...")
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(sb.uc_gui_click_captcha)
            future.result(timeout=timeout)
            print("[INFO] ✅ 已点击验证")
            return True
    except FuturesTimeoutError:
        print(f"[WARN] 点击超时")
    except Exception as e:
        print(f"[WARN] 点击失败: {e}")
    return False

def handle_turnstile(sb, idx):
    time.sleep(3)
    
    # 检测类型
    turnstile_type = "none"
    try:
        containers = sb.find_elements("#turnstileContainer")
        cf_inputs = sb.find_elements("input[name='cf-turnstile-response']")
        if containers or cf_inputs:
            iframes = sb.find_elements("iframe")
            for iframe in iframes:
                src = iframe.get_attribute("src") or ""
                if "challenges.cloudflare.com" in src or "turnstile" in src:
                    turnstile_type = "visible"
                    break
            else:
                turnstile_type = "invisible"
    except:
        turnstile_type = "visible"
    
    print(f"[INFO] Turnstile 类型: {turnstile_type}")
    
    if turnstile_type == "none":
        return True
    
    if turnstile_type == "visible":
        click_captcha_with_timeout(sb, 20)
        time.sleep(3)
    
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
            
            last_shot = shot(idx, f"login-{attempt}")
            sb.save_screenshot(last_shot)
            
            for _ in range(10):
                if 'identifier' in sb.get_page_source(): break
                time.sleep(2)
            
            for sel in ['input[name="identifier"]', 'input[type="email"]', 'input[type="text"]']:
                try:
                    sb.wait_for_element(sel, timeout=5)
                    sb.type(sel, user)
                    print(f"[INFO] 输入用户名")
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
                            print("[INFO] 输入密码")
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
            
            last_shot = shot(idx, "result")
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
        print("[INFO] 已退出登录")
    except: pass

def get_servers(sb, idx):
    print("[INFO] 获取服务器列表...")
    servers, seen = [], set()
    
    sb.open(DASHBOARD_URL)
    time.sleep(5)
    screenshot = shot(idx, "dashboard")
    sb.save_screenshot(screenshot)
    
    src = sb.get_page_source()
    if "Access Blocked" in src or "VPN or Proxy" in src:
        return [], "⚠️ 访问被阻止", screenshot
    
    for url in [DASHBOARD_URL, OVERVIEW_URL]:
        if url != DASHBOARD_URL:
            sb.open(url)
            time.sleep(3)
        for sid in re.findall(r'/server\?id=(\d+)', sb.get_page_source()):
            if sid not in seen:
                seen.add(sid)
                servers.append({"id": sid})
    
    if not servers:
        return [], "⚠️ 未找到服务器", screenshot
    
    print(f"[INFO] 找到 {len(servers)} 个服务器")
    return servers, "", screenshot

def renew(sb, sid, idx, username):
    """续期服务器"""
    result = {"server_id": sid, "success": False, "message": "", "screenshot": None, "expiry_cn": ""}
    
    print(f"\n[INFO] 续期服务器 {mask_id(sid)}...")
    
    sb.open(SERVER_URL.format(sid))
    time.sleep(4)
    
    # 滚动页面
    sb.scroll_to_bottom()
    time.sleep(1)
    sb.scroll_to_top()
    time.sleep(1)
    
    console_shot = shot(idx, "console")
    sb.save_screenshot(console_shot)
    result["screenshot"] = console_shot
    
    src = sb.get_page_source()
    if "Access Blocked" in src:
        result["message"] = "⚠️ 访问被阻止"
        notify(False, username, result["message"], console_shot)
        return result
    
    # 获取续期前时间
    old_renewal = js_get_element_text(sb, "lastRenewalTime")
    print(f"[INFO] 续期前: {old_renewal or '(空)'}")
    
    # 滚动到中间位置
    sb.scroll_to_y(600)
    time.sleep(1)
    sb.save_screenshot(shot(idx, "scroll"))
    
    # 查找并点击续期按钮
    clicked = False
    
    # 方法1: 通过 onclick 属性查找
    try:
        links = sb.find_elements(f'a[onclick*="handleServerRenewal"]')
        for link in links:
            onclick = link.get_attribute("onclick") or ""
            if sid in onclick:
                link.click()
                clicked = True
                print("[INFO] 通过 onclick 找到按钮")
                break
    except Exception as e:
        print(f"[DEBUG] 方法1失败: {e}")
    
    # 方法2: 通过文本查找
    if not clicked:
        try:
            elements = sb.find_elements("a, button")
            for el in elements:
                text = (el.text or "").lower()
                if "renew" in text and len(text) < 30:
                    el.click()
                    clicked = True
                    print(f"[INFO] 通过文本找到按钮: {text}")
                    break
        except Exception as e:
            print(f"[DEBUG] 方法2失败: {e}")
    
    # 方法3: 通过 CSS 选择器
    if not clicked:
        try:
            for sel in ['a.action-button', 'button.btn-renew', '.renew-btn', '[class*="renew"]']:
                try:
                    btns = sb.find_elements(sel)
                    for btn in btns:
                        if "renew" in (btn.text or "").lower():
                            btn.click()
                            clicked = True
                            print(f"[INFO] 通过选择器 {sel} 找到按钮")
                            break
                except: continue
                if clicked: break
        except Exception as e:
            print(f"[DEBUG] 方法3失败: {e}")
    
    if not clicked:
        # 打印页面上所有按钮和链接的信息
        try:
            elements = sb.find_elements("a, button")
            print(f"[DEBUG] 页面上找到 {len(elements)} 个链接/按钮:")
            for i, el in enumerate(elements[:20]):
                text = (el.text or "").strip()[:30]
                onclick = (el.get_attribute("onclick") or "")[:50]
                href = (el.get_attribute("href") or "")[:50]
                if text or onclick:
                    print(f"  [{i}] text='{text}' onclick='{onclick}' href='{href}'")
        except: pass
        
        result["message"] = "⚠️ 未找到续期按钮"
        notify(False, username, f"{mask_id(sid)}: {result['message']}", console_shot)
        return result
    
    print("[INFO] 已点击续期按钮")
    time.sleep(2)
    sb.save_screenshot(shot(idx, "modal"))
    
    # 处理 Turnstile
    handle_turnstile(sb, idx)
    time.sleep(3)
    
    # 刷新获取新时间
    sb.open(SERVER_URL.format(sid))
    time.sleep(4)
    
    new_renewal = js_get_element_text(sb, "lastRenewalTime")
    remain = js_get_element_text(sb, "nextRenewalTime")
    
    result["expiry_cn"] = calc_expiry_time(new_renewal)
    print(f"[INFO] 续期后: {new_renewal or '(空)'}, 剩余: {remain or '(空)'}")
    
    # 判断成功
    today = datetime.now().strftime('%b %d, %Y')
    if new_renewal and new_renewal != old_renewal:
        result["success"] = True
        result["message"] = f"到期: {result['expiry_cn']}"
    elif today in str(new_renewal):
        result["success"] = True
        result["message"] = f"今日已续期，到期: {result['expiry_cn']}"
    elif remain and ("day" in remain or "hour" in remain):
        result["success"] = True
        result["message"] = f"到期: {result['expiry_cn']}"
    else:
        result["message"] = f"⚠️ 状态未知"
    
    final_shot = shot(idx, "result")
    sb.save_screenshot(final_shot)
    result["screenshot"] = final_shot
    
    notify(result["success"], username, f"{mask_id(sid)}: {result['message']}", final_shot)
    print(f"[INFO] {'✅' if result['success'] else '⚠️'} {result['message']}")
    return result

def process(sb, user, pwd, idx):
    result = {"username": user, "success": False, "message": "", "servers": []}
    
    login_ok, login_shot = login(sb, user, pwd, idx)
    if not login_ok:
        result["message"] = "登录失败"
        notify(False, user, "⚠️ 登录失败", login_shot)
        return result
    
    servers, error, dash_shot = get_servers(sb, idx)
    if error:
        result["message"] = error
        notify(False, user, error, dash_shot)
        logout(sb)
        return result
    
    for srv in servers:
        try:
            r = renew(sb, srv["id"], idx, user)
            result["servers"].append(r)
            time.sleep(3)
        except Exception as e:
            print(f"[ERROR] 服务器 {mask_id(srv['id'])} 异常: {e}")
            result["servers"].append({"server_id": srv["id"], "success": False, "message": str(e)})
    
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
    sb_args = {"uc": True, "locale": "en"}
    
    if is_linux():
        sb_args["xvfb"] = True
        sb_args["headed"] = False
        print("[INFO] Linux: xvfb + headless")
    
    if proxy:
        sb_args["proxy"] = proxy
        print("[INFO] 使用代理")
    
    try:
        with SB(**sb_args) as sb:
            for i, (u, p) in enumerate(accounts, 1):
                try:
                    r = process(sb, u, p, i)
                    results.append(r)
                except Exception as e:
                    print(f"[ERROR] 账号 {mask(u)} 异常: {e}")
                    results.append({"username": u, "success": False, "message": str(e), "servers": []})
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
    print(f"{'='*50}")
    
    sys.exit(0 if ok_srv > 0 else 1)

if __name__ == "__main__":
    main()
