#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kerit Cloud 重启脚本 (Pterodactyl 面板) - 支持多账号"""

import os, sys, time, requests, re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Tuple
from urllib.parse import unquote

BASE_URL = "https://panel.kerit.cloud"
API_RESOURCES_URL = f"{BASE_URL}/api/client/servers/{{}}/resources"
API_POWER_URL = f"{BASE_URL}/api/client/servers/{{}}/power"

CN_TZ = timezone(timedelta(hours=8))

def cn_now() -> datetime:
    return datetime.now(CN_TZ)

def cn_time_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return cn_now().strftime(fmt)

def mask(s: str, show: int = 3) -> str:
    if not s: return "***"
    s = str(s)
    if len(s) <= show: return s[0] + "***"
    return s[:show] + "*" * min(5, len(s) - show)

def mask_id(sid: str) -> str:
    if not sid: return "****"
    return sid[:4] + "****" if len(sid) > 4 else sid

def notify(ok: bool, title: str, details: str = ""):
    """发送 Telegram 通知"""
    token, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not token or not chat:
        return
    
    try:
        icon = "✅" if ok else "❌"
        text = f"""{icon} Kerit Cloud {title}

{details}
时间：{cn_time_str()}"""
        
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "HTML"},
            timeout=30
        )
    except Exception as e:
        print(f"[WARN] 通知发送失败: {e}")

def parse_cookies(cookie_str: str) -> Dict[str, str]:
    """解析 Cookie 字符串"""
    cookies = {}
    if not cookie_str:
        return cookies
    for item in cookie_str.split(';'):
        item = item.strip()
        if '=' in item:
            key, value = item.split('=', 1)
            cookies[key.strip()] = value.strip()
    return cookies

def parse_accounts(account_str: str) -> List[Dict[str, str]]:
    """
    解析多账号配置
    格式: 账号名----Cookie字符串
    多个账号用换行分隔
    """
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

def create_session(cookies: Dict[str, str]) -> requests.Session:
    """创建带 Cookie 的 Session"""
    session = requests.Session()
    
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
    
    # XSRF Token
    xsrf = cookies.get('XSRF-TOKEN', '')
    if xsrf:
        session.headers['X-XSRF-TOKEN'] = unquote(xsrf)
    
    return session

def check_login(session: requests.Session) -> Tuple[bool, str]:
    """检查登录状态并返回用户名"""
    try:
        resp = session.get(BASE_URL, timeout=30)
        
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        
        if '/auth/login' in resp.url:
            return False, "Cookie 已过期"
        
        if 'PterodactylUser' in resp.text:
            match = re.search(r'"username":"([^"]+)"', resp.text)
            if match:
                return True, match.group(1)
            return True, "unknown"
        
        return False, "未找到用户信息"
    except Exception as e:
        return False, str(e)

def get_servers(session: requests.Session) -> List[Dict[str, str]]:
    """获取服务器列表"""
    servers = []
    try:
        resp = session.get(BASE_URL, timeout=30)
        if resp.status_code != 200:
            return servers
        
        # 匹配服务器链接和名称
        pattern = r'href="/server/([a-zA-Z0-9]+)"[^>]*>.*?<p[^>]*class="[^"]*ServerRow[^"]*"[^>]*>([^<]+)</p>'
        matches = re.findall(pattern, resp.text, re.DOTALL)
        
        seen = set()
        for sid, name in matches:
            if sid not in seen:
                seen.add(sid)
                servers.append({"id": sid, "name": name.strip()})
        
        # 备用匹配
        if not servers:
            ids = re.findall(r'href="/server/([a-zA-Z0-9]+)"', resp.text)
            seen = set()
            for sid in ids:
                if sid not in seen:
                    seen.add(sid)
                    servers.append({"id": sid, "name": f"Server-{sid[:6]}"})
                    
    except Exception as e:
        print(f"[ERROR] 获取服务器列表: {e}")
    
    return servers

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
        print(f"[ERROR] 获取状态: {e}")
    return result

def send_power_action(session: requests.Session, server_id: str, action: str) -> bool:
    """发送电源操作: start, stop, restart, kill"""
    try:
        resp = session.post(
            API_POWER_URL.format(server_id),
            json={"signal": action},
            timeout=30
        )
        return resp.status_code in [200, 204]
    except Exception as e:
        print(f"[ERROR] 电源操作: {e}")
        return False

def process_server(session: requests.Session, server: Dict[str, str]) -> Dict[str, Any]:
    """处理单个服务器"""
    sid, name = server['id'], server['name']
    result = {"id": sid, "name": name, "success": False, "message": "", "action": "none"}
    
    print(f"\n[INFO] 服务器: {name} ({mask_id(sid)})")
    
    # 获取状态
    status = get_server_status(session, sid)
    state = status['state']
    print(f"[INFO] 状态: {state}")
    
    if status['is_suspended']:
        result['message'] = "⚠️ 服务器已暂停"
        return result
    
    # 非 offline 跳过
    if state != 'offline':
        result['success'] = True
        result['message'] = f"正常 ({state})"
        result['action'] = "skip"
        print(f"[INFO] ✅ 无需操作")
        return result
    
    # offline 需要启动
    print(f"[INFO] 发送启动命令...")
    result['action'] = "start"
    
    if send_power_action(session, sid, "start"):
        # 等待启动
        for i in range(6):  # 最多等30秒
            time.sleep(5)
            new_status = get_server_status(session, sid)
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
        result['message'] = "⚠️ 启动命令失败"
    
    return result

def process_account(account: Dict[str, str]) -> Dict[str, Any]:
    """处理单个账号"""
    name = account['name']
    cookie_str = account['cookie']
    
    result = {
        "account": name,
        "success": False,
        "message": "",
        "servers": []
    }
    
    print(f"\n{'='*50}")
    print(f"[INFO] 账号: {name}")
    print(f"{'='*50}")
    
    # 解析 Cookie
    cookies = parse_cookies(cookie_str)
    if not cookies:
        result['message'] = "Cookie 解析失败"
        return result
    
    # 创建会话
    session = create_session(cookies)
    
    # 检查登录
    login_ok, username = check_login(session)
    if not login_ok:
        result['message'] = f"登录失败: {username}"
        print(f"[ERROR] {result['message']}")
        return result
    
    print(f"[INFO] ✅ 登录成功 ({username})")
    
    # 获取服务器
    servers = get_servers(session)
    if not servers:
        result['message'] = "未找到服务器"
        print(f"[WARN] {result['message']}")
        return result
    
    print(f"[INFO] 找到 {len(servers)} 个服务器")
    
    # 处理每个服务器
    for server in servers:
        try:
            srv_result = process_server(session, server)
            result['servers'].append(srv_result)
            time.sleep(1)
        except Exception as e:
            result['servers'].append({
                "id": server['id'],
                "name": server['name'],
                "success": False,
                "message": str(e)
            })
    
    # 汇总
    ok_count = sum(1 for s in result['servers'] if s['success'])
    result['success'] = ok_count > 0 or all(s.get('action') == 'skip' for s in result['servers'])
    result['message'] = f"{ok_count}/{len(result['servers'])} 正常"
    
    return result

def main():
    print(f"\n{'='*60}")
    print(f"  Kerit Cloud 自动重启")
    print(f"  {cn_time_str()}")
    print(f"{'='*60}")
    
    # 获取账号配置
    account_str = os.environ.get("KERIT_ACCOUNT", "")
    if not account_str:
        print("[ERROR] 缺少 KERIT_ACCOUNT")
        sys.exit(1)
    
    accounts = parse_accounts(account_str)
    if not accounts:
        print("[ERROR] 无有效账号")
        sys.exit(1)
    
    # 筛选指定账号
    target_name = os.environ.get("ACCOUNT_NAME", "").strip()
    if target_name:
        accounts = [a for a in accounts if a['name'] == target_name]
        if not accounts:
            print(f"[ERROR] 未找到账号: {target_name}")
            sys.exit(1)
    
    print(f"[INFO] 处理 {len(accounts)} 个账号")
    
    # 处理每个账号
    results = []
    for account in accounts:
        try:
            result = process_account(account)
            results.append(result)
            time.sleep(2)
        except Exception as e:
            results.append({
                "account": account['name'],
                "success": False,
                "message": str(e),
                "servers": []
            })
    
    # 汇总输出
    print(f"\n{'='*60}")
    print(f"  执行汇总")
    print(f"{'='*60}")
    
    summary_lines = []
    total_ok = 0
    total_servers = 0
    
    for r in results:
        icon = "✅" if r['success'] else "❌"
        line = f"{icon} {r['account']}: {r['message']}"
        print(line)
        summary_lines.append(line)
        
        for s in r.get('servers', []):
            srv_icon = "✓" if s['success'] else "✗"
            srv_line = f"  {srv_icon} {s['name']}: {s['message']}"
            print(srv_line)
            summary_lines.append(srv_line)
            total_servers += 1
            if s['success']:
                total_ok += 1
    
    # 通知
    all_ok = all(r['success'] for r in results)
    notify(
        all_ok,
        "执行完成" if all_ok else "部分失败",
        "\n".join(summary_lines)
    )
    
    print(f"\n📊 服务器: {total_ok}/{total_servers} 正常")
    sys.exit(0 if all_ok else 1)

if __name__ == "__main__":
    main()
