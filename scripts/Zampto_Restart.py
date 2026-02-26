#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, time, platform, requests, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Tuple
from seleniumbase import SB

AUTH_URL = "https://auth.zampto.net/sign-in?app_id=bmhk6c8qdqxphlyscztgl"
DASHBOARD_URL = "https://dash.zampto.net/homepage"
OVERVIEW_URL = "https://dash.zampto.net/overview"
SERVER_URL = "https://dash.zampto.net/server?id={}"
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

def notify(ok: bool, stage: str, msg: str = "", img: str = None):
    token, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not token or not chat: return
    try:
        text = f"🔔 Zampto 重启: {'✅' if ok else '❌'} {stage}\n{msg}\n⏰ {cn_time_str()}"
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text}, timeout=30)
        if img and Path(img).exists():
            with open(img, "rb") as f:
                requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", data={"chat_id": chat}, files={"photo": f}, timeout=60)
    except: pass

def parse_accounts(s: str) -> List[Tuple[str, str]]:
    return [(p[0].strip(), p[1].strip()) for line in s.strip().split('\n') 
            if '----' in line and len(p := line.strip().split('----', 1)) == 2 and p[0].strip() and p[1].strip()]

def login(sb, user: str, pwd: str, idx: int) -> bool:
    user_masked = mask(user)
    print(f"\n{'='*50}\n[INFO] 账号 {idx}: 登录 {user_masked}\n{'='*50}")
    
    for attempt in range(3):
        try:
            print(f"[INFO] 打开登录页 (尝试 {attempt + 1}/3)...")
            sb.uc_open_with_reconnect(AUTH_URL, reconnect_time=10.0)
            time.sleep(5)
            
            current_url = sb.get_current_url()
            if "dash.zampto.net" in current_url:
                print("[INFO] ✅ 已登录")
                return True
            
            sb.save_screenshot(shot(idx, f"01-login-{attempt}"))
            
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
                return False
            
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
                return False
            
            time.sleep(1)
            try:
                sb.click('button[type="submit"]')
            except:
                sb.click('button')
            
            time.sleep(6)
            sb.save_screenshot(shot(idx, "02-result"))
            
            current_url = sb.get_current_url()
            if "dash.zampto.net" in current_url or "sign-in" not in current_url:
                print("[INFO] ✅ 登录成功")
                return True
            
            print(f"[WARN] 尝试 {attempt + 1}: 登录未成功")
            
        except Exception as e:
            print(f"[WARN] 尝试 {attempt + 1} 异常: {e}")
            if attempt < 2:
                time.sleep(5)
                continue
    
    print("[ERROR] 登录失败")
    return False

def logout(sb):
    try:
        sb.delete_all_cookies()
        sb.open("about:blank")
        time.sleep(1)
        print("[INFO] 已退出登录")
    except Exception as e:
        print(f"[WARN] 退出时出错: {e}")

def get_servers(sb, idx: int) -> List[Dict[str, str]]:
    """获取服务器列表，返回 server-console 链接"""
    print("[INFO] 获取服务器列表...")
    servers = []
    seen_ids = set()
    
    sb.open(DASHBOARD_URL)
    time.sleep(5)
    sb.save_screenshot(shot(idx, "03-dashboard"))
    
    src = sb.get_page_source()
    if "Access Blocked" in src or "VPN or Proxy Detected" in src:
        print("[ERROR] ⚠️ 访问被阻止")
        return []
    
    for page_url in [DASHBOARD_URL, OVERVIEW_URL]:
        if page_url != DASHBOARD_URL:
            sb.open(page_url)
            time.sleep(3)
        
        src = sb.get_page_source()
        # 查找 server-console 链接
        matches = re.findall(r'href="[^"]*?/server-console\?id=(\d+)"', src)
        for sid in matches:
            if sid not in seen_ids:
                seen_ids.add(sid)
                servers.append({"id": sid, "name": f"Server {sid}"})
        
        # 也查找 server 链接（备用）
        if not servers:
            matches = re.findall(r'href="[^"]*?/server\?id=(\d+)"', src)
            for sid in matches:
                if sid not in seen_ids:
                    seen_ids.add(sid)
                    servers.append({"id": sid, "name": f"Server {sid}"})
    
    print(f"[INFO] 找到 {len(servers)} 个服务器")
    for s in servers:
        print(f"  - ID: {mask(s['id'])}")
    return servers

def restart_server(sb, sid: str, idx: int) -> Dict[str, Any]:
    """重启服务器"""
    sid_masked = mask(sid)
    result = {
        "server_id": sid, 
        "success": False, 
        "message": "", 
        "screenshot": None,
        "status": ""
    }
    
    print(f"\n[INFO] 重启服务器 {sid_masked}...")
    
    # 进入服务器控制台页面
    console_url = CONSOLE_URL.format(sid)
    print(f"[INFO] 服务器页面 URL: {console_url}")
    
    sb.open(console_url)
    time.sleep(5)
    
    sb.save_screenshot(shot(idx, f"srv-{sid}-console"))
    
    src = sb.get_page_source()
    if "Access Blocked" in src:
        result["message"] = "访问被阻止"
        return result
    
    # 查找 Restart 按钮
    print("[INFO] 查找 Restart 按钮...")
    
    try:
        # 尝试多种方式查找和点击 Restart 按钮
        clicked = sb.execute_script('''
            (function() {
                // 方式1: 通过 ID 查找
                var restartBtn = document.getElementById('restartBtn');
                if (restartBtn) {
                    restartBtn.click();
                    return "id";
                }
                
                // 方式2: 通过按钮文本查找
                var buttons = document.querySelectorAll('button');
                for (var i = 0; i < buttons.length; i++) {
                    var text = buttons[i].textContent.toLowerCase();
                    if (text.includes('restart')) {
                        buttons[i].click();
                        return "text";
                    }
                }
                
                // 方式3: 通过 class 查找
                var btnSecondary = document.querySelectorAll('.btn-secondary, .btn');
                for (var i = 0; i < btnSecondary.length; i++) {
                    var text = btnSecondary[i].textContent.toLowerCase();
                    if (text.includes('restart')) {
                        btnSecondary[i].click();
                        return "class";
                    }
                }
                
                // 方式4: 通过图标查找
                var icons = document.querySelectorAll('i.fa-sync-alt, i.fas.fa-sync-alt');
                for (var i = 0; i < icons.length; i++) {
                    var parent = icons[i].closest('button');
                    if (parent && parent.textContent.toLowerCase().includes('restart')) {
                        parent.click();
                        return "icon";
                    }
                }
                
                return null;
            })()
        ''')
        
        if clicked:
            print(f"[INFO] ✅ 已点击 Restart 按钮 (方式: {clicked})")
        else:
            # 备用方案: 使用 Selenium 直接点击
            try:
                sb.click('#restartBtn')
                print("[INFO] ✅ 已点击 Restart 按钮 (selenium)")
                clicked = True
            except:
                try:
                    sb.click('button:contains("Restart")')
                    print("[INFO] ✅ 已点击 Restart 按钮 (contains)")
                    clicked = True
                except:
                    result["message"] = "未找到 Restart 按钮"
                    sb.save_screenshot(shot(idx, f"srv-{sid}-nobtn"))
                    return result
        
    except Exception as e:
        result["message"] = f"点击失败: {e}"
        sb.save_screenshot(shot(idx, f"srv-{sid}-error"))
        return result
    
    # 等待重启响应
    print("[INFO] 等待重启响应...")
    time.sleep(3)
    
    sb.save_screenshot(shot(idx, f"srv-{sid}-afterclick"))
    
    # 等待并验证重启成功
    print("[INFO] 验证重启状态...")
    time.sleep(5)
    
    # 刷新页面检查状态
    sb.refresh()
    time.sleep(5)
    
    # 检查服务器状态
    status = ""
    for attempt in range(6):  # 最多等待 30 秒
        try:
            status = sb.execute_script('''
                (function() {
                    var statusEl = document.getElementById('serverStatus');
                    if (statusEl) {
                        return statusEl.textContent.trim();
                    }
                    
                    // 备用查找
                    var statusDiv = document.querySelector('.status-running, .info-card-value');
                    if (statusDiv) {
                        return statusDiv.textContent.trim();
                    }
                    
                    return "";
                })()
            ''') or ""
            
            print(f"[INFO] 当前状态: {status}")
            
            if "Running" in status or "Starting" in status:
                result["success"] = True
                result["status"] = status
                result["message"] = f"重启成功！状态: {status}"
                break
            elif "Offline" in status or "Stopped" in status:
                # 服务器正在重启中，继续等待
                print(f"[INFO] 服务器重启中... ({attempt + 1}/6)")
                time.sleep(5)
                sb.refresh()
                time.sleep(3)
            else:
                time.sleep(5)
                sb.refresh()
                time.sleep(3)
                
        except Exception as e:
            print(f"[WARN] 检查状态出错: {e}")
            time.sleep(5)
    
    if not result["success"]:
        # 即使无法确认状态，如果点击成功了也算部分成功
        result["message"] = f"已发送重启命令，当前状态: {status or '未知'}"
        result["status"] = status
    
    # 保存最终截图
    sp = shot(idx, f"srv-{sid}-result")
    sb.save_screenshot(sp)
    result["screenshot"] = sp
    
    print(f"[INFO] {'✅' if result['success'] else '⚠️'} {result['message']}")
    return result

def process(sb, user: str, pwd: str, idx: int) -> Dict[str, Any]:
    """处理单个账号"""
    result = {"username": user, "success": False, "message": "", "servers": []}
    
    if not login(sb, user, pwd, idx):
        result["message"] = "登录失败"
        return result
    
    servers = get_servers(sb, idx)
    if not servers:
        result["message"] = "无服务器或访问被阻止"
        logout(sb)
        return result
    
    for srv in servers:
        try:
            r = restart_server(sb, srv["id"], idx)
            r["name"] = srv.get("name", srv["id"])
            result["servers"].append(r)
            time.sleep(3)
        except Exception as e:
            print(f"[ERROR] 服务器 {mask(srv['id'])} 重启异常: {e}")
            result["servers"].append({
                "server_id": srv["id"], 
                "success": False, 
                "message": str(e)
            })
    
    ok = sum(1 for s in result["servers"] if s.get("success"))
    result["success"] = ok > 0
    result["message"] = f"{ok}/{len(result['servers'])} 成功"
    
    sb.open(DASHBOARD_URL)
    time.sleep(2)
    final_shot = shot(idx, "05-final")
    sb.save_screenshot(final_shot)
    result["final_screenshot"] = final_shot
    
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
    results, last_shot = [], None
    
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
                    if r.get("final_screenshot"):
                        last_shot = r["final_screenshot"]
                    time.sleep(3)
                except Exception as e:
                    print(f"[ERROR] 账号 {mask(u)} 异常: {e}")
                    results.append({
                        "username": u, 
                        "success": False, 
                        "message": str(e), 
                        "servers": []
                    })
            
    except Exception as e:
        print(f"[ERROR] 脚本异常: {e}")
        notify(False, "错误", str(e))
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
            log_summary += f"  {'✓' if s.get('success') else '✗'} Server {mask(s['server_id'])}: {s.get('message','')} [{status}]\n"
    
    print(f"\n{'='*50}\n{log_summary}{'='*50}")
    
    notify_summary = f"📊 账号: {ok_acc}/{len(results)} | 服务器: {ok_srv}/{total_srv}\n{'─'*30}\n"
    for r in results:
        notify_summary += f"{'✅' if r.get('success') else '❌'} {r['username']}: {r.get('message','')}\n"
        for s in r.get("servers", []):
            status = '✓' if s.get('success') else '✗'
            notify_summary += f"  {status} Server {s['server_id']}: {s.get('message','')}\n"
    
    notify(ok_acc == len(results) and ok_srv == total_srv, "重启完成", notify_summary, last_shot)
    sys.exit(0 if ok_srv > 0 else 1)

if __name__ == "__main__":
    main()
