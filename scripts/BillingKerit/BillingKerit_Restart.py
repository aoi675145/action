#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, time, requests, re, asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Tuple
from urllib.parse import unquote

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("[ERROR] 请安装 playwright: pip install playwright && playwright install chromium")
    sys.exit(1)

BASE_URL = "https://panel.kerit.cloud"
API_RESOURCES_URL = f"{BASE_URL}/api/client/servers/{{}}/resources"
API_POWER_URL = f"{BASE_URL}/api/client/servers/{{}}/power"

OUTPUT_DIR = Path("output/screenshots")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CN_TZ = timezone(timedelta(hours=8))

def cn_now() -> datetime:
    return datetime.now(CN_TZ)

def cn_time_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return cn_now().strftime(fmt)

def mask_str(s: str, show: int = 2) -> str:
    """通用字符串遮蔽"""
    if not s: return "***"
    s = str(s)
    if len(s) <= show: return s[0] + "***"
    return s[:show] + "*" * min(4, len(s) - show)

def mask_email(email: str) -> str:
    """遮蔽邮箱"""
    if not email or '@' not in email:
        return mask_str(email)
    local, domain = email.split('@', 1)
    return mask_str(local, 2) + "@" + mask_str(domain, 2)

def mask_id(sid: str) -> str:
    """遮蔽服务器ID"""
    if not sid: return "****"
    return sid[:2] + "****" if len(sid) > 2 else "****"

def mask_username(name: str) -> str:
    """遮蔽用户名"""
    if not name: return "***"
    if len(name) <= 2: return name[0] + "**"
    return name[0] + "*" * (len(name) - 1)

def shot_path(name: str) -> str:
    """生成截图路径（使用时间戳避免泄露）"""
    ts = cn_now().strftime('%H%M%S%f')[:9]
    return str(OUTPUT_DIR / f"{ts}.png")

def notify(ok: bool, title: str, details: str = "", image_path: str = None):
    """发送 Telegram 通知（私人通知，不脱敏）"""
    token, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not token or not chat:
        return
    
    try:
        icon = "✅" if ok else "❌"
        text = f"""{icon} {result}

{details}
时间：{cn_time_str()}

Billing Kerit Auto Restart"""
        
        if image_path and Path(image_path).exists():
            with open(image_path, 'rb') as f:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    data={"chat_id": chat, "caption": text[:1024]},
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
        print(f"[WARN] 通知发送失败")

def parse_cookies(cookie_str: str) -> List[Dict[str, Any]]:
    """解析 Cookie 字符串为 Playwright 格式"""
    cookies = []
    if not cookie_str:
        return cookies
    
    for item in cookie_str.split(';'):
        item = item.strip()
        if '=' in item:
            key, value = item.split('=', 1)
            key = key.strip()
            value = value.strip()
            if key and value:
                cookies.append({
                    "name": key,
                    "value": value,
                    "domain": "panel.kerit.cloud",
                    "path": "/"
                })
    
    return cookies

def parse_accounts(account_str: str) -> List[Dict[str, str]]:
    """解析多账号配置"""
    accounts = []
    if not account_str:
        return accounts
    
    for line in account_str.strip().split('\n'):
        line = line.strip()
        if not line or '----' not in line:
            continue
        
        parts = line.split('----', 1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            accounts.append({
                'name': parts[0].strip(),
                'cookie': parts[1].strip()
            })
    
    return accounts

def create_api_session(cookie_str: str) -> requests.Session:
    """创建 API 请求 Session"""
    session = requests.Session()
    
    cookies = {}
    for item in cookie_str.split(';'):
        item = item.strip()
        if '=' in item:
            key, value = item.split('=', 1)
            cookies[key.strip()] = value.strip()
    
    for name, value in cookies.items():
        session.cookies.set(name, value, domain='panel.kerit.cloud')
    
    session.headers.update({
        'Accept': 'application/json',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': BASE_URL,
        'Origin': BASE_URL,
    })
    
    xsrf = cookies.get('XSRF-TOKEN', '')
    if xsrf:
        session.headers['X-XSRF-TOKEN'] = unquote(xsrf)
    
    return session

def get_server_status(session: requests.Session, server_id: str) -> Dict[str, Any]:
    """获取服务器状态"""
    result = {"state": "unknown", "is_suspended": False}
    try:
        resp = session.get(API_RESOURCES_URL.format(server_id), timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            attrs = data.get('attributes', {})
            result['state'] = attrs.get('current_state', 'unknown')
            result['is_suspended'] = attrs.get('is_suspended', False)
    except Exception as e:
        print(f"[ERROR] 获取状态失败")
    return result

def send_power_action(session: requests.Session, server_id: str, action: str) -> bool:
    """发送电源操作"""
    try:
        resp = session.post(
            API_POWER_URL.format(server_id),
            json={"signal": action},
            timeout=30
        )
        return resp.status_code in [200, 204]
    except Exception as e:
        print(f"[ERROR] 电源操作失败")
        return False

async def process_account(account: Dict[str, str], index: int) -> Dict[str, Any]:
    """处理单个账号"""
    name = account['name']
    cookie_str = account['cookie']
    
    # 日志用遮蔽名称
    masked_name = mask_email(name) if '@' in name else mask_str(name)
    
    result = {
        "account": name,  # 原始名称用于TG通知
        "account_masked": masked_name,  # 遮蔽名称用于日志
        "success": False,
        "message": "",
        "servers": [],
        "screenshot": None
    }
    
    print(f"\n{'='*50}")
    print(f"[INFO] 账号 #{index + 1}: {masked_name}")
    print(f"{'='*50}")
    
    cookies = parse_cookies(cookie_str)
    if not cookies:
        result['message'] = "Cookie 解析失败"
        return result
    
    print(f"[INFO] 解析到 {len(cookies)} 个 Cookie")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        await context.add_cookies(cookies)
        page = await context.new_page()
        
        try:
            print("[INFO] 访问面板首页...")
            await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)
            
            screenshot_path = shot_path("dashboard")
            await page.screenshot(path=screenshot_path, full_page=True)
            result['screenshot'] = screenshot_path
            print(f"[INFO] 截图已保存")
            
            current_url = page.url
            
            if '/auth/login' in current_url:
                result['message'] = "Cookie 已过期"
                print(f"[ERROR] {result['message']}")
                notify(False, "登录失败", f"账号: {name}\n{result['message']}", screenshot_path)
                return result
            
            content = await page.content()
            
            user_match = re.search(r'"username":"([^"]+)"', content)
            if user_match:
                username = user_match.group(1)
                print(f"[INFO] ✅ 登录成功 (用户: {mask_username(username)})")
            else:
                print("[INFO] ✅ 登录成功")
            
            # 查找服务器
            servers = []
            seen_ids = set()
            
            href_matches = re.findall(r'href="/server/([a-zA-Z0-9]+)"', content)
            for sid in href_matches:
                if sid not in seen_ids:
                    seen_ids.add(sid)
                    servers.append({"id": sid, "name": f"Server-{sid[:4]}"})
            
            if not servers:
                server_links = await page.query_selector_all('a[href^="/server/"]')
                for link in server_links:
                    href = await link.get_attribute('href')
                    if href:
                        match = re.search(r'/server/([a-zA-Z0-9]+)', href)
                        if match:
                            sid = match.group(1)
                            if sid not in seen_ids:
                                seen_ids.add(sid)
                                servers.append({"id": sid, "name": f"Server-{sid[:4]}"})
            
            print(f"[INFO] 找到 {len(servers)} 个服务器")
            
            for srv in servers:
                print(f"  - {mask_id(srv['id'])}")
            
            if not servers:
                result['message'] = "未找到服务器"
                print(f"[WARN] {result['message']}")
                notify(False, "未找到服务器", f"账号: {name}", screenshot_path)
                return result
            
            api_session = create_api_session(cookie_str)
            
            for i, server in enumerate(servers):
                srv_result = await process_server(page, api_session, server, i)
                result['servers'].append(srv_result)
                await page.wait_for_timeout(1000)
            
            final_shot = shot_path("final")
            await page.screenshot(path=final_shot, full_page=True)
            result['screenshot'] = final_shot
            
            ok_count = sum(1 for s in result['servers'] if s['success'])
            result['success'] = ok_count > 0 or all(s.get('action') == 'skip' for s in result['servers'])
            result['message'] = f"{ok_count}/{len(result['servers'])} 正常"
            
        except Exception as e:
            print(f"[ERROR] 处理异常")
            result['message'] = "处理异常"
            try:
                err_shot = shot_path("error")
                await page.screenshot(path=err_shot)
                result['screenshot'] = err_shot
            except:
                pass
        
        finally:
            await browser.close()
    
    return result

async def process_server(page, api_session: requests.Session, server: Dict[str, str], index: int) -> Dict[str, Any]:
    """处理单个服务器"""
    sid, srv_name = server['id'], server['name']
    result = {
        "id": sid,
        "name": srv_name,
        "success": False,
        "message": "",
        "action": "none"
    }
    
    print(f"\n[INFO] 服务器 #{index + 1}: {mask_id(sid)}")
    
    status = get_server_status(api_session, sid)
    state = status['state']
    print(f"[INFO] 状态: {state}")
    
    if status['is_suspended']:
        result['message'] = "⚠️ 已暂停"
        return result
    
    if state != 'offline':
        result['success'] = True
        result['message'] = f"正常 ({state})"
        result['action'] = "skip"
        print(f"[INFO] ✅ 无需操作")
        return result
    
    print(f"[INFO] 服务器离线，进入控制台启动...")
    result['action'] = "start"
    
    try:
        server_url = f"{BASE_URL}/server/{sid}"
        await page.goto(server_url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        srv_shot = shot_path("server")
        await page.screenshot(path=srv_shot)
        print(f"[INFO] 服务器页面截图已保存")
        
        clicked = False
        
        start_btn = await page.query_selector('#power-start')
        if start_btn:
            await start_btn.click()
            clicked = True
            print("[INFO] ✅ 点击 Start 按钮成功")
        
        if not clicked:
            buttons = await page.query_selector_all('button')
            for btn in buttons:
                text = await btn.inner_text()
                if 'start' in text.lower():
                    await btn.click()
                    clicked = True
                    print("[INFO] ✅ 点击 Start 按钮成功")
                    break
        
        if not clicked:
            js_clicked = await page.evaluate('''
                () => {
                    const startBtn = document.getElementById('power-start');
                    if (startBtn) { startBtn.click(); return true; }
                    const buttons = document.querySelectorAll('button');
                    for (const btn of buttons) {
                        if (btn.textContent.toLowerCase().includes('start')) {
                            btn.click(); return true;
                        }
                    }
                    return false;
                }
            ''')
            if js_clicked:
                clicked = True
                print("[INFO] ✅ 点击 Start 按钮成功")
        
        if not clicked:
            if send_power_action(api_session, sid, "start"):
                clicked = True
                print("[INFO] ✅ API 启动命令已发送")
        
        if clicked:
            await page.wait_for_timeout(3000)
            
            for i in range(6):
                await page.wait_for_timeout(5000)
                new_status = get_server_status(api_session, sid)
                new_state = new_status['state']
                print(f"[INFO] ({(i+1)*5}s) 状态: {new_state}")
                
                if new_state == 'running':
                    result['success'] = True
                    result['message'] = "✅ 启动成功"
                    return result
                elif new_state == 'starting':
                    result['success'] = True
                    result['message'] = "启动中..."
                    return result
            
            result['message'] = f"启动超时 ({new_state})"
        else:
            result['message'] = "⚠️ 未找到启动按钮"
            
    except Exception as e:
        result['message'] = "⚠️ 操作异常"
        print(f"[ERROR] 操作异常")
    
    return result

async def main():
    print(f"\n{'='*60}")
    print(f"  Billing Kerit 自动重启")
    print(f"  {cn_time_str()}")
    print(f"{'='*60}")
    
    account_str = os.environ.get("KERIT_ACCOUNT", "")
    if not account_str:
        print("[ERROR] 缺少 KERIT_ACCOUNT")
        sys.exit(1)
    
    accounts = parse_accounts(account_str)
    if not accounts:
        print("[ERROR] 无有效账号")
        sys.exit(1)
    
    target_name = os.environ.get("ACCOUNT_NAME", "").strip()
    if target_name:
        accounts = [a for a in accounts if a['name'] == target_name]
        if not accounts:
            print(f"[ERROR] 未找到指定账号")
            sys.exit(1)
    
    print(f"[INFO] 处理 {len(accounts)} 个账号")
    
    results = []
    for i, account in enumerate(accounts):
        try:
            result = await process_account(account, i)
            results.append(result)
            await asyncio.sleep(2)
        except Exception as e:
            results.append({
                "account": account['name'],
                "account_masked": mask_email(account['name']) if '@' in account['name'] else mask_str(account['name']),
                "success": False,
                "message": "处理异常",
                "servers": [],
                "screenshot": None
            })
    
    # 汇总输出（日志脱敏）
    print(f"\n{'='*60}")
    print(f"  执行汇总")
    print(f"{'='*60}")
    
    # TG 通知用（不脱敏）
    tg_lines = []
    # 日志用（脱敏）
    log_lines = []
    
    total_ok = 0
    total_servers = 0
    last_screenshot = None
    
    for r in results:
        icon = "✅" if r['success'] else "❌"
        
        # 日志输出（脱敏）
        masked_name = r.get('account_masked', mask_str(r['account']))
        log_line = f"{icon} 账号: {r['message']}"
        print(log_line)
        log_lines.append(log_line)
        
        # TG 通知（不脱敏）
        tg_line = f"{icon} {r['account']}: {r['message']}"
        tg_lines.append(tg_line)
        
        if r.get('screenshot'):
            last_screenshot = r['screenshot']
        
        for s in r.get('servers', []):
            srv_icon = "✓" if s['success'] else "✗"
            
            # 日志（脱敏）
            log_srv = f"  {srv_icon} 服务器: {s['message']}"
            print(log_srv)
            
            # TG（不脱敏）
            tg_srv = f"  {srv_icon} {s['name']}: {s['message']}"
            tg_lines.append(tg_srv)
            
            total_servers += 1
            if s['success']:
                total_ok += 1
    
    # 发送 TG 通知（使用不脱敏的内容）
    all_ok = all(r['success'] for r in results)
    notify(
        all_ok,
        "执行完成" if all_ok else "部分失败",
        "\n".join(tg_lines),
        last_screenshot
    )
    
    print(f"\n📊 服务器: {total_ok}/{total_servers} 正常")
    sys.exit(0 if all_ok else 1)

if __name__ == "__main__":
    asyncio.run(main())
