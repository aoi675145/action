#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zampto 重启"""

import os, sys, time, platform, requests, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from seleniumbase import SB

AUTH_URL = "https://auth.zampto.net/sign-in?app_id=bmhk6c8qdqxphlyscztgl"
DASHBOARD_URL = "https://dash.zampto.net/homepage"
OVERVIEW_URL = "https://dash.zampto.net/overview"
CONSOLE_URL = "https://dash.zampto.net/server-console?id={}"
OUTPUT_DIR = Path("output/screenshots")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CN_TZ = timezone(timedelta(hours=8))

def cn_now() -> datetime:
    return datetime.now(CN_TZ)

def cn_time_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return cn_now().strftime(fmt)

def mask(s: str, show: int = 1) -> str:
    if not s: return "***"
    s = str(s)
    if len(s) <= show: return s[0] + "***"
    return s[:show] + "*" * min(3, len(s) - show)

def mask_id(sid: str) -> str:
    if not sid: return "****"
    return sid[0] + "***"

def is_linux(): return platform.system().lower() == "linux"

def setup_display():
    if is_linux() and not os.environ.get("DISPLAY"):
        try:
            from pyvirtualdisplay import Display
            d = Display(visible=False, size=(1920, 1080))
            d.start()
            os.environ["DISPLAY"] = d.new_display_var
            print("[INFO] 虚拟显示已启动")
            return d
        except Exception as e:
            print(f"[ERROR] 虚拟显示失败: {e}"); sys.exit(1)
    return None

def shot(idx: int, name: str) -> str:
    return str(OUTPUT_DIR / f"acc{idx}-{cn_now().strftime('%H%M%S')}-{name}.png")

def notify(ok: bool, username: str, info: str, img: str = None):
    """发送通知 - 带截图"""
    token, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not token or not chat: 
        return
    
    try:
        icon = "✅" if ok else "❌"
        result = "重启成功" if ok else "重启失败"
        
        text = f"""{icon} {result}

账号：{username}
信息：{info}
时间：{cn_time_str()}

Zampto Auto Restart"""
        
        if img and Path(img).exists():
            with open(img, "rb") as f:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    data={"chat_id": chat, "caption": text},
                    files={"photo": f},
                    timeout=60
                )
        else:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text},
                timeout=30
            )
    except Exception as e:
        print(f"[WARN] 通知发送失败: {e}")

def parse_accounts(s: str) -> List[Tuple[str, str]]:
    return [(p[0].strip(), p[1].strip()) for line in s.strip().split('\n') 
            if '----' in line and len(p := line.strip().split('----', 1)) == 2 and p[0].strip() and p[1].strip()]

def login(sb, user: str, pwd: str, idx: int) -> Tuple[bool, Optional[str]]:
    """登录，返回 (成功, 截图路径)"""
    user_masked = mask(user)
    print(f"\n{'='*50}\n[INFO] 账号 {idx}: 登录 {user_masked}\n{'='*50}")
    
    last_shot = None
    
    for attempt in range(3):
        try:
            print(f"[INFO] 打开登录页 (尝试 {attempt + 1}/3)...")
            sb.uc_open_with_reconnect(AUTH_URL, reconnect_time=10.0)
            time.sleep(5)
            
            current_url = sb.get_current_url()
            if "dash.zampto.net" in current_url:
                print("[INFO] ✅ 已登录")
                return True, None
            
            last_shot = shot(idx, f"01-login-{attempt}")
            sb.save_screenshot(last_shot)
            
            for _ in range(10):
                src = sb.get_page_source()
                if 'identifier' in src or 'email' in src:
                    break
                time.sleep(2)
            
            selectors = ['input[name="identifier"]', 'input[type="email"]', 'input[type="text"]']
            
            input_found = False
            for sel in selectors:
                try:
                    sb.wait_for_element(sel, timeout=5)
                    print(f"[INFO] 找到输入框: {sel}")
                    sb.type(sel, user)
                    input_found = True
                    break
                except:
                    continue
            
            if not input_found:
                print(f"[WARN] 尝试 {attempt + 1}: 未找到输入框")
                if attempt < 2:
                    time.sleep(5)
                    continue
                return False, last_shot
            
            time.sleep(1)
            try:
                sb.click('button[type="submit"]')
            except:
                sb.click('button')
            
            time.sleep(4)
            
            pwd_found = False
            for _ in range(15):
                for sel in ['input[name="password"]', 'input[type="password"]']:
                    try:
                        if sb.is_element_visible(sel):
                            sb.type(sel, pwd)
                            pwd_found = True
                            print("[INFO] 已输入密码")
                            break
                    except:
                        continue
                if pwd_found:
                    break
                time.sleep(1)
            
            if not pwd_found:
                print("[WARN] 密码页面未加载")
                if attempt < 2:
                    continue
                return False, last_shot
            
            time.sleep(1)
            try:
                sb.click('button[type="submit"]')
            except:
                sb.click('button')
            
            time.sleep(6)
            last_shot = shot(idx, "02-result")
            sb.save_screenshot(last_shot)
            
            current_url = sb.get_current_url()
            if "dash.zampto.net" in current_url or "sign-in" not in current_url:
                print("[INFO] ✅ 登录成功")
                return True, last_shot
            
            print(f"[WARN] 尝试 {attempt + 1}: 登录未成功")
            
        except Exception as e:
            print(f"[WARN] 尝试 {attempt + 1} 异常: {e}")
            if attempt < 2:
                time.sleep(5)
                continue
    
    print("[ERROR] 登录失败")
    return False, last_shot

def logout(sb):
    try:
        sb.delete_all_cookies()
        sb.open("about:blank")
        time.sleep(1)
        print("[INFO] 已退出登录")
    except Exception as e:
        print(f"[WARN] 退出时出错: {e}")

def get_servers(sb, idx: int) -> Tuple[List[Dict[str, str]], str, Optional[str]]:
    """获取服务器列表，返回 (服务器列表, 错误信息, 截图路径)"""
    print("[INFO] 获取服务器列表...")
    servers = []
    seen_ids = set()
    
    sb.open(DASHBOARD_URL)
    time.sleep(5)
    
    # 保存截图
    screenshot = shot(idx, "03-dashboard")
    sb.save_screenshot(screenshot)
    
    src = sb.get_page_source()
    if "Access Blocked" in src or "VPN or Proxy Detected" in src:
        print("[ERROR] ⚠️ 访问被阻止")
        return [], "⚠️ 访问被阻止", screenshot
    
    for page_url in [DASHBOARD_URL, OVERVIEW_URL]:
        if page_url != DASHBOARD_URL:
            sb.open(page_url)
            time.sleep(3)
        
        src = sb.get_page_source()
        matches = re.findall(r'href="[^"]*?/server-console\?id=(\d+)"', src)
        for sid in matches:
            if sid not in seen_ids:
                seen_ids.add(sid)
                servers.append({"id": sid, "name": f"Server {sid}"})
        
        if not servers:
            matches = re.findall(r'href="[^"]*?/server\?id=(\d+)"', src)
            for sid in matches:
                if sid not in seen_ids:
                    seen_ids.add(sid)
                    servers.append({"id": sid, "name": f"Server {sid}"})
    
    if not servers:
        print("[WARN] 未找到服务器")
        return [], "⚠️ 未找到服务器", screenshot
    
    print(f"[INFO] 找到 {len(servers)} 个服务器")
    for s in servers:
        print(f"  - ID: {mask_id(s['id'])}")
    return servers, "", screenshot

def wait_for_status(sb, timeout: int = 10) -> str:
    for i in range(timeout):
        try:
            status = sb.execute_script('''
                (function() {
                    var cards = document.querySelector('.info-cards');
                    if (!cards) return "";
                    
                    var statusEl = document.getElementById('serverStatus');
                    if (statusEl && statusEl.textContent) {
                        return statusEl.textContent.trim();
                    }
                    
                    var statusRunning = document.querySelector('.status-running');
                    if (statusRunning) return statusRunning.textContent.trim();
                    
                    var statusStopped = document.querySelector('.status-stopped');
                    if (statusStopped) return statusStopped.textContent.trim();
                    
                    return "";
                })()
            ''')
            
            if status:
                return status
        except:
            pass
        time.sleep(1)
    return ""

def restart_server(sb, sid: str, idx: int, username: str) -> Dict[str, Any]:
    """重启服务器"""
    sid_masked = mask_id(sid)
    result = {
        "server_id": sid, 
        "success": False, 
        "message": "", 
        "screenshot": None,
        "status": ""
    }
    
    print(f"\n[INFO] 重启服务器 {sid_masked}...")
    print(f"[INFO] 服务器页面 URL: https://dash.zampto.net/server-console?id=****")
    
    console_url = CONSOLE_URL.format(sid)
    sb.open(console_url)
    time.sleep(3)
    
    print("[INFO] 等待页面加载...")
    for _ in range(10):
        src = sb.get_page_source()
        if 'serverStatus' in src or 'restartBtn' in src:
            break
        time.sleep(1)
    
    time.sleep(2)
    
    # 保存控制台截图
    console_shot = shot(idx, f"srv-console")
    sb.save_screenshot(console_shot)
    result["screenshot"] = console_shot
    
    src = sb.get_page_source()
    if "Access Blocked" in src:
        result["message"] = "⚠️ 访问被阻止"
        notify(False, username, "⚠️ 访问被阻止", console_shot)
        return result
    
    old_status = wait_for_status(sb, 5)
    print(f"[INFO] 重启前状态: {old_status or '加载中...'}")
    
    print("[INFO] 查找 Restart 按钮...")
    
    try:
        clicked = sb.execute_script('''
            (function() {
                var restartBtn = document.getElementById('restartBtn');
                if (restartBtn) {
                    restartBtn.click();
                    return "id";
                }
                
                var buttons = document.querySelectorAll('button');
                for (var i = 0; i < buttons.length; i++) {
                    var text = buttons[i].textContent.toLowerCase();
                    if (text.includes('restart')) {
                        buttons[i].click();
                        return "text";
                    }
                }
                
                return null;
            })()
        ''')
        
        if clicked:
            print(f"[INFO] ✅ 已点击 Restart 按钮 (方式: {clicked})")
        else:
            try:
                sb.click('#restartBtn')
                print("[INFO] ✅ 已点击 Restart 按钮 (selenium)")
                clicked = True
            except:
                result["message"] = "⚠️ 未找到 Restart 按钮"
                notify(False, username, f"服务器: {sid} | ⚠️ 未找到按钮", console_shot)
                return result
        
    except Exception as e:
        result["message"] = f"⚠️ 点击失败: {e}"
        notify(False, username, f"服务器: {sid} | ⚠️ 点击失败", console_shot)
        return result
    
    print("[INFO] 等待重启响应...")
    time.sleep(3)
    
    print("[INFO] 验证重启状态...")
    
    max_wait = 60
    check_interval = 5
    final_status = ""
    
    for attempt in range(max_wait // check_interval):
        sb.refresh()
        time.sleep(3)
        
        status = wait_for_status(sb, 8)
        print(f"[INFO] 状态检查 ({(attempt + 1) * check_interval}s): {status or '加载中...'}")
        
        if status:
            final_status = status
            
            if "Running" in status:
                result["success"] = True
                result["status"] = status
                result["message"] = f"重启成功！状态: {status}"
                print(f"[INFO] ✅ 服务器已运行: {status}")
                break
            elif "Starting" in status:
                print(f"[INFO] 服务器启动中...")
            elif "Offline" in status or "Stopped" in status:
                print(f"[INFO] 服务器重启中...")
        
        time.sleep(check_interval - 3)
    
    if not result["success"]:
        if final_status:
            result["message"] = f"重启命令已发送，当前状态: {final_status}"
            result["status"] = final_status
            if "Running" in final_status or "Starting" in final_status:
                result["success"] = True
        else:
            result["message"] = "⚠️ 无法获取服务器状态"
    
    # 保存最终截图
    time.sleep(2)
    final_shot = shot(idx, f"srv-result")
    sb.save_screenshot(final_shot)
    result["screenshot"] = final_shot
    
    # 发送通知
    if result["success"]:
        notify(True, username, f"服务器: {sid}", final_shot)
    else:
        notify(False, username, f"服务器: {sid} | {result['message']}", final_shot)
    
    print(f"[INFO] {'✅' if result['success'] else '⚠️'} {result['message']}")
    return result

def process(sb, user: str, pwd: str, idx: int) -> Dict[str, Any]:
    """处理单个账号"""
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
            r = restart_server(sb, srv["id"], idx, user)
            r["name"] = srv.get("name", srv["id"])
            result["servers"].append(r)
            time.sleep(3)
        except Exception as e:
            err_shot = shot(idx, "error")
            sb.save_screenshot(err_shot)
            print(f"[ERROR] 服务器 {mask_id(srv['id'])} 重启异常: {e}")
            result["servers"].append({
                "server_id": srv["id"], 
                "success": False, 
                "message": str(e)
            })
            notify(False, user, f"服务器: {srv['id']} | ⚠️ {e}", err_shot)
    
    ok = sum(1 for s in result["servers"] if s.get("success"))
    result["success"] = ok > 0
    result["message"] = f"{ok}/{len(result['servers'])} 成功"
    
    logout(sb)
    return result

def main():
    acc_str = os.environ.get("ZAMPTO_ACCOUNT", "")
    if not acc_str:
        print("[ERROR] 缺少 ZAMPTO_ACCOUNT")
        sys.exit(1)
    
    accounts = parse_accounts(acc_str)
    if not accounts:
        print("[ERROR] 无有效账号")
        sys.exit(1)
    
    print(f"[INFO] {len(accounts)} 个账号")
    
    proxy = os.environ.get("PROXY_SOCKS5", "")
    if proxy:
        try:
            requests.get("https://api.ipify.org", proxies={"http": proxy, "https": proxy}, timeout=10)
            print("[INFO] 代理连接正常")
        except Exception as e:
            print(f"[WARN] 代理测试失败: {e}")
    
    display = setup_display()
    results = []
    
    try:
        opts = {"uc": True, "test": True, "locale": "en", "headed": not is_linux()}
        if proxy:
            opts["proxy"] = proxy
            print("[INFO] 使用代理模式")
        
        with SB(**opts) as sb:
            for i, (u, p) in enumerate(accounts, 1):
                try:
                    r = process(sb, u, p, i)
                    results.append(r)
                    time.sleep(3)
                except Exception as e:
                    err_shot = shot(i, "fatal")
                    try:
                        sb.save_screenshot(err_shot)
                    except:
                        err_shot = None
                    print(f"[ERROR] 账号 {mask(u)} 异常: {e}")
                    results.append({
                        "username": u, 
                        "success": False, 
                        "message": str(e), 
                        "servers": []
                    })
                    notify(False, u, f"⚠️ {e}", err_shot)
            
    except Exception as e:
        print(f"[ERROR] 脚本异常: {e}")
        sys.exit(1)
    finally:
        if display:
            display.stop()
    
    ok_acc = sum(1 for r in results if r.get("success"))
    total_srv = sum(len(r.get("servers", [])) for r in results)
    ok_srv = sum(sum(1 for s in r.get("servers", []) if s.get("success")) for r in results)
    
    log_summary = f"📊 账号: {ok_acc}/{len(results)} | 服务器: {ok_srv}/{total_srv}\n{'─'*30}\n"
    for r in results:
        log_summary += f"{'✅' if r.get('success') else '❌'} {mask(r['username'])}: {r.get('message','')}\n"
        for s in r.get("servers", []):
            status = s.get('status', '')
            log_summary += f"  {'✓' if s.get('success') else '✗'} Server {mask_id(s['server_id'])}: {s.get('message','')} [{status}]\n"
    
    print(f"\n{'='*50}\n{log_summary}{'='*50}")
    
    sys.exit(0 if ok_srv > 0 else 1)

if __name__ == "__main__":
    main()
