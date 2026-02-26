#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Data Online 终端命令执行 - 多账号支持 - 指定账号执行"""

import os, sys, asyncio, httpx
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Tuple, Optional, List
from playwright.async_api import async_playwright

# 配置
BASE_URL = "https://sv66.dataonline.vn:2222"
LOGIN_URL = f"{BASE_URL}/evo/login"
TERMINAL_URL = f"{BASE_URL}/evo/user/terminal"
OUTPUT_DIR = Path("output/screenshots")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CN_TZ = timezone(timedelta(hours=8))

def cn_now() -> datetime:
    return datetime.now(CN_TZ)

def cn_time_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return cn_now().strftime(fmt)

def mask(s: str, show: int = 3) -> str:
    """隐藏敏感信息（仅用于日志）"""
    if not s: return "***"
    s = str(s)
    if len(s) <= show: return s[0] + "***"
    return s[:show] + "*" * min(3, len(s) - show)

def mask_command(cmd: str) -> str:
    """隐藏命令详情 - 只用于工作流日志"""
    if not cmd: return "***"
    first_word = cmd.split()[0] if cmd.split() else "cmd"
    cmd_name = first_word.split('/')[-1]
    return f"{cmd_name} ..."

def shot(idx: int, name: str) -> str:
    """生成截图路径"""
    return str(OUTPUT_DIR / f"acc{idx}-{cn_now().strftime('%H%M%S')}-{name}.png")

def get_username_from_email(email: str) -> str:
    """从邮箱中提取用户名部分（@前面的部分）"""
    if '@' in email:
        return email.split('@')[0]
    return email

def parse_accounts(s: str) -> List[Tuple[str, str, str]]:
    """解析账号配置，返回 [(邮箱, 密码, 命令), ...]"""
    accounts = []
    for line in s.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split('----')
        if len(parts) >= 3:
            email = parts[0].strip()
            password = parts[1].strip()
            command = '----'.join(parts[2:]).strip()
            if email and password and command:
                accounts.append((email, password, command))
    return accounts

def filter_accounts(accounts: List[Tuple[str, str, str]], target: str) -> List[Tuple[str, str, str]]:
    """
    根据账号名过滤账号列表
    支持：
    - 完整邮箱匹配: imgzzcdc@example.com
    - 用户名匹配: imgzzcdc
    """
    if not target:
        return accounts
    
    target = target.strip().lower()
    filtered = []
    
    for email, password, command in accounts:
        email_lower = email.lower()
        username = get_username_from_email(email_lower)
        
        # 精确匹配：完整邮箱 或 用户名部分
        if email_lower == target or username == target:
            filtered.append((email, password, command))
    
    return filtered

# ============ 以下函数保持不变 ============

async def notify(ok: bool, username: str, info: str, img: str = None, command: str = None):
    """发送 Telegram 通知（完整显示，不隐藏）"""
    token = os.environ.get("TG_BOT_TOKEN")
    chat = os.environ.get("TG_CHAT_ID")
    if not token or not chat:
        return
    
    try:
        icon = "✅" if ok else "❌"
        result = "执行成功" if ok else "执行失败"
        cmd_display = command[:50] + "..." if command and len(command) > 50 else (command or "无")
        
        text = f"""{icon} {result}

账号：{username}
命令：<code>{cmd_display}</code>
信息：{info}
时间：{cn_time_str()}

Data Online Auto Restart"""
        
        async with httpx.AsyncClient(timeout=60) as client:
            if img and Path(img).exists():
                with open(img, "rb") as f:
                    await client.post(
                        f"https://api.telegram.org/bot{token}/sendPhoto",
                        data={"chat_id": chat, "caption": text, "parse_mode": "HTML"},
                        files={"photo": f}
                    )
            else:
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat, "text": text, "parse_mode": "HTML"}
                )
        print("[INFO] 通知发送成功")
    except Exception as e:
        print(f"[WARN] 通知发送失败: {e}")

async def wait_for_page_ready(page, timeout: int = 30) -> bool:
    """等待页面完全加载"""
    for i in range(timeout):
        try:
            content = await page.content()
            if 'challenge' in content.lower() or 'checking your browser' in content.lower():
                print(f"[INFO] 等待 Cloudflare 验证... ({i+1}s)")
                await asyncio.sleep(1)
                continue
            inputs = await page.query_selector_all('input')
            if len(inputs) > 0:
                return True
        except:
            pass
        await asyncio.sleep(1)
    return False

async def try_connect(page, url: str, max_retries: int = 3, retry_delay: int = 30) -> Tuple[bool, str]:
    """尝试连接，带重试机制"""
    last_error = ""
    
    for attempt in range(max_retries):
        try:
            print(f"[INFO] 连接尝试 {attempt + 1}/{max_retries}")
            await page.goto(url, timeout=60000, wait_until='domcontentloaded')
            print("[INFO] ✅ 连接成功")
            return True, ""
        except Exception as e:
            last_error = str(e)
            error_type = "未知错误"
            
            if 'ERR_CONNECTION_REFUSED' in last_error:
                error_type = "连接被拒绝"
            elif 'ERR_CONNECTION_TIMED_OUT' in last_error:
                error_type = "连接超时"
            elif 'ERR_NAME_NOT_RESOLVED' in last_error:
                error_type = "域名解析失败"
            elif 'ERR_CONNECTION_RESET' in last_error:
                error_type = "连接被重置"
            
            print(f"[WARN] 尝试 {attempt + 1}: {error_type}")
            
            if attempt < max_retries - 1:
                print(f"[INFO] {retry_delay}秒后重试...")
                await asyncio.sleep(retry_delay)
    
    return False, f"连接失败 (重试{max_retries}次)"

async def check_login_status(page) -> Tuple[str, str]:
    """检查登录状态"""
    current_url = page.url
    
    if 'account-disabled' in current_url:
        return 'disabled', '账户已禁用'
    if 'wrong-password' in current_url or 'invalid' in current_url:
        return 'wrong_password', '密码错误'
    if '/login' not in current_url:
        return 'success', '登录成功'
    
    try:
        page_text = await page.text_content('body')
        if page_text:
            text_lower = page_text.lower()
            if 'disabled' in text_lower:
                return 'disabled', '账户已禁用'
            if 'wrong password' in text_lower or 'invalid' in text_lower:
                return 'wrong_password', '密码错误'
    except:
        pass
    
    return 'pending', '等待中'

async def login(page, username: str, password: str, idx: int) -> Tuple[bool, str, Optional[str]]:
    """登录，返回 (成功, 状态, 截图路径)"""
    print(f"\n{'='*50}")
    print(f"[INFO] 账号 {idx}: 登录 {mask(username)}")
    print(f"{'='*50}")
    
    last_shot = None
    
    print(f"[INFO] 打开登录页...")
    ok, err = await try_connect(page, LOGIN_URL)
    if not ok:
        last_shot = shot(idx, "connect-error")
        await page.set_content(f'''
            <html><body style="background:#1a1a2e;color:#fff;font-family:monospace;padding:50px;">
            <h1>🌐 网络连接失败</h1>
            <p>目标: {LOGIN_URL}</p>
            <p style="color:#ff6b6b;">{err}</p>
            </body></html>
        ''')
        await page.screenshot(path=last_shot)
        return False, "network_error", last_shot
    
    print("[INFO] 等待页面加载...")
    await wait_for_page_ready(page, timeout=30)
    
    last_shot = shot(idx, "01-login")
    await page.screenshot(path=last_shot)
    
    print("[INFO] 查找登录表单...")
    input_found = False
    for attempt in range(3):
        try:
            await page.wait_for_selector('input', timeout=10000)
            input_found = True
            print("[INFO] ✅ 登录表单已找到")
            break
        except:
            print(f"[WARN] 尝试 {attempt + 1}/3: 表单未加载")
            await asyncio.sleep(3)
    
    if not input_found:
        last_shot = shot(idx, "no-form")
        await page.screenshot(path=last_shot)
        return False, "form_error", last_shot
    
    print("[INFO] 填写登录信息...")
    username_selectors = [
        '#username input', 'input[placeholder*="username" i]',
        'input[name="username"]', 'input[type="text"]:first-of-type',
        '.Input__Text', 'div.Input input'
    ]
    
    username_filled = False
    for selector in username_selectors:
        try:
            element = page.locator(selector).first
            if await element.is_visible(timeout=2000):
                await element.click()
                await asyncio.sleep(0.3)
                await element.fill('')
                await element.type(username, delay=50)
                value = await element.input_value()
                if value == username:
                    print("[INFO] ✅ 用户名已填写")
                    username_filled = True
                    break
        except:
            continue
    
    if not username_filled:
        last_shot = shot(idx, "username-error")
        await page.screenshot(path=last_shot)
        return False, "username_error", last_shot
    
    password_selectors = [
        '#password input', 'input[type="password"]',
        'input[placeholder*="password" i]', '.InputPassword__Input'
    ]
    
    password_filled = False
    for selector in password_selectors:
        try:
            element = page.locator(selector).first
            if await element.is_visible(timeout=2000):
                await element.click()
                await asyncio.sleep(0.3)
                await element.fill('')
                await element.type(password, delay=50)
                value = await element.input_value()
                if len(value) > 0:
                    print("[INFO] ✅ 密码已填写")
                    password_filled = True
                    break
        except:
            continue
    
    if not password_filled:
        last_shot = shot(idx, "password-error")
        await page.screenshot(path=last_shot)
        return False, "password_error", last_shot
    
    submit_selectors = [
        'button[type="submit"]', 'button:has-text("Sign in")',
        'button:has-text("Login")', '.Button[type="submit"]'
    ]
    
    for selector in submit_selectors:
        try:
            element = page.locator(selector).first
            if await element.is_visible(timeout=2000):
                await element.click()
                print("[INFO] ✅ 点击登录按钮")
                break
        except:
            continue
    
    print("[INFO] 等待登录响应...")
    await asyncio.sleep(3)
    
    for i in range(10):
        await asyncio.sleep(1)
        status, message = await check_login_status(page)
        
        if status == 'disabled':
            print("[ERROR] 🚫 账户已禁用")
            last_shot = shot(idx, "disabled")
            await page.screenshot(path=last_shot)
            return False, "disabled", last_shot
        elif status == 'wrong_password':
            print("[ERROR] 🔑 密码错误")
            last_shot = shot(idx, "wrong-password")
            await page.screenshot(path=last_shot)
            return False, "wrong_password", last_shot
        elif status == 'success':
            print("[INFO] ✅ 登录成功")
            last_shot = shot(idx, "02-loggedin")
            await page.screenshot(path=last_shot)
            return True, "success", last_shot
    
    last_shot = shot(idx, "timeout")
    await page.screenshot(path=last_shot)
    return False, "timeout", last_shot

async def execute_command(page, command: str, idx: int) -> Tuple[bool, str, Optional[str]]:
    """执行终端命令，返回 (成功, 消息, 截图路径)"""
    print(f"\n[INFO] 访问终端页面...")
    
    try:
        await page.goto(TERMINAL_URL, timeout=60000)
        await page.wait_for_load_state('networkidle')
    except Exception as e:
        print(f"[ERROR] 终端页面加载失败: {e}")
        last_shot = shot(idx, "terminal-error")
        await page.screenshot(path=last_shot)
        return False, "终端加载失败", last_shot
    
    await asyncio.sleep(2)
    
    if '/login' in page.url:
        print("[ERROR] 会话已失效")
        last_shot = shot(idx, "session-expired")
        await page.screenshot(path=last_shot)
        return False, "会话失效", last_shot
    
    print("[INFO] ✅ 进入终端页面")
    await asyncio.sleep(5)
    
    last_shot = shot(idx, "03-terminal")
    await page.screenshot(path=last_shot)
    
    print("[INFO] 执行命令...")
    for selector in ['.xterm', '.xterm-screen', '.terminal', 'canvas']:
        try:
            element = page.locator(selector).first
            if await element.is_visible(timeout=3000):
                await element.click()
                break
        except:
            continue
    else:
        await page.mouse.click(640, 400)
    
    await asyncio.sleep(1)
    await page.keyboard.type(command, delay=30)
    await asyncio.sleep(0.5)
    await page.keyboard.press('Enter')
    print("[INFO] ✅ 命令已发送")
    
    await asyncio.sleep(5)
    last_shot = shot(idx, "04-result")
    await page.screenshot(path=last_shot)
    
    return True, "命令执行成功", last_shot

async def logout(context):
    """退出登录"""
    try:
        await context.clear_cookies()
        print("[INFO] 已退出登录")
    except Exception as e:
        print(f"[WARN] 退出时出错: {e}")

async def process_account(browser, username: str, password: str, command: str, idx: int) -> dict:
    """处理单个账号"""
    result = {
        "username": mask(username),
        "success": False,
        "message": "",
        "screenshot": None
    }
    
    context = await browser.new_context(
        ignore_https_errors=True,
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    )
    page = await context.new_page()
    
    try:
        # 登录
        login_ok, status, login_shot = await login(page, username, password, idx)
        result["screenshot"] = login_shot
        
        if not login_ok:
            result["message"] = {
                "disabled": "账户已禁用",
                "wrong_password": "密码错误",
                "network_error": "网络连接失败",
                "form_error": "登录表单未加载",
                "username_error": "用户名填写失败",
                "password_error": "密码填写失败",
                "timeout": "登录超时"
            }.get(status, f"登录失败: {status}")
            
            await notify(False, username, result["message"], login_shot, command)
            return result
        
        # 执行命令
        exec_ok, exec_msg, exec_shot = await execute_command(page, command, idx)
        result["screenshot"] = exec_shot
        result["success"] = exec_ok
        result["message"] = exec_msg
        
        await notify(exec_ok, username, exec_msg, exec_shot, command)
        
    except Exception as e:
        print(f"[ERROR] 异常: {e}")
        result["message"] = str(e)[:100]
        try:
            result["screenshot"] = shot(idx, "error")
            await page.screenshot(path=result["screenshot"])
        except:
            pass
        await notify(False, username, result["message"], result["screenshot"], command)
    finally:
        await logout(context)
        await context.close()
    
    return result

async def main():
    # 获取账号配置
    account_str = os.environ.get('DATA_ACCOUNT', '')
    if not account_str:
        print("[ERROR] 缺少 DATA_ACCOUNT")
        sys.exit(1)
    
    accounts = parse_accounts(account_str)
    if not accounts:
        print("[ERROR] 无有效账号配置")
        print("[INFO] 格式: 邮箱----密码----命令")
        sys.exit(1)
    
    target_account = os.environ.get('ACCOUNT_NAME', '').strip()
    
    if target_account:
        print(f"\n[INFO] 🎯 指定账号模式: {mask(target_account)}")
        original_count = len(accounts)
        accounts = filter_accounts(accounts, target_account)
        
        if not accounts:
            print(f"[ERROR] ❌ 未找到匹配的账号: {mask(target_account)}")
            print(f"[INFO] 可用账号列表:")
            all_accounts = parse_accounts(account_str)
            for email, _, _ in all_accounts:
                username = get_username_from_email(email)
                print(f"  - {mask(username)}")
            sys.exit(1)
        
        print(f"[INFO] ✅ 已匹配 {len(accounts)}/{original_count} 个账号")
    else:
        print(f"\n[INFO] 📋 全量模式: 运行所有 {len(accounts)} 个账号")
    
    print(f"\n[INFO] 待处理账号:")
    for i, (email, _, cmd) in enumerate(accounts, 1):
        print(f"  {i}. {mask(email)} | 命令: {mask_command(cmd)}")
    
    results = []
    
    async with async_playwright() as p:
        print("\n[INFO] 启动浏览器...")
        browser = await p.chromium.launch(
            headless=True,
            args=['--ignore-certificate-errors', '--no-sandbox', '--disable-blink-features=AutomationControlled']
        )
        
        try:
            for i, (email, password, command) in enumerate(accounts, 1):
                result = await process_account(browser, email, password, command, i)
                results.append(result)
                
                if i < len(accounts):
                    print(f"\n[INFO] 等待 3 秒处理下一个账号...")
                    await asyncio.sleep(3)
        finally:
            await browser.close()
    
    ok_count = sum(1 for r in results if r["success"])
    
    print(f"\n{'='*50}")
    print(f"📊 执行汇总: {ok_count}/{len(results)} 成功")
    print(f"{'─'*50}")
    for r in results:
        icon = "✅" if r["success"] else "❌"
        print(f"{icon} {r['username']}: {r['message']}")
    print(f"{'='*50}")
    
    sys.exit(0 if ok_count > 0 else 1)

if __name__ == '__main__':
    asyncio.run(main())
