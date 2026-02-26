# scripts/data-online_renew.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Data Online 终端命令执行"""

import os, sys, asyncio, httpx
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Tuple, Optional
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

def shot(name: str) -> str:
    """生成截图路径"""
    return str(OUTPUT_DIR / f"{cn_now().strftime('%H%M%S')}-{name}.png")

async def notify(ok: bool, username: str, info: str, img: str = None, command: str = None):
    """发送 Telegram 通知"""
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
    
    return False, f"连接失败 (重试{max_retries}次): {last_error[:100]}"

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

async def login(page, username: str, password: str) -> Tuple[bool, str, Optional[str]]:
    """登录，返回 (成功, 状态, 截图路径)"""
    print(f"\n{'='*50}")
    print(f"[INFO] 登录账号: {mask(username)}")
    print(f"{'='*50}")
    
    last_shot = None
    
    print(f"[INFO] 打开登录页...")
    ok, err = await try_connect(page, LOGIN_URL)
    if not ok:
        last_shot = shot("connect-error")
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
    
    last_shot = shot("01-login")
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
        last_shot = shot("no-form")
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
        last_shot = shot("username-error")
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
        last_shot = shot("password-error")
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
            last_shot = shot("disabled")
            await page.screenshot(path=last_shot)
            return False, "disabled", last_shot
        elif status == 'wrong_password':
            print("[ERROR] 🔑 密码错误")
            last_shot = shot("wrong-password")
            await page.screenshot(path=last_shot)
            return False, "wrong_password", last_shot
        elif status == 'success':
            print("[INFO] ✅ 登录成功")
            last_shot = shot("02-loggedin")
            await page.screenshot(path=last_shot)
            return True, "success", last_shot
    
    last_shot = shot("timeout")
    await page.screenshot(path=last_shot)
    return False, "timeout", last_shot

async def execute_command(page, command: str) -> Tuple[bool, str, Optional[str]]:
    """执行终端命令，返回 (成功, 消息, 截图路径)"""
    print(f"\n[INFO] 访问终端页面...")
    
    try:
        await page.goto(TERMINAL_URL, timeout=60000)
        await page.wait_for_load_state('networkidle')
    except Exception as e:
        print(f"[ERROR] 终端页面加载失败: {e}")
        last_shot = shot("terminal-error")
        await page.screenshot(path=last_shot)
        return False, f"终端加载失败", last_shot
    
    await asyncio.sleep(2)
    
    if '/login' in page.url:
        print("[ERROR] 会话已失效")
        last_shot = shot("session-expired")
        await page.screenshot(path=last_shot)
        return False, "会话失效", last_shot
    
    print("[INFO] ✅ 进入终端页面")
    await asyncio.sleep(5)
    
    last_shot = shot("03-terminal")
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
    last_shot = shot("04-result")
    await page.screenshot(path=last_shot)
    
    return True, "命令执行成功", last_shot

async def main():
    username = os.environ.get('DATA_USERNAME')
    password = os.environ.get('DATA_PASSWORD')
    command = os.environ.get('DATA_COMMAND', '')
    
    if not username:
        print("[ERROR] 缺少 DATA_USERNAME"); sys.exit(1)
    if not password:
        print("[ERROR] 缺少 DATA_PASSWORD"); sys.exit(1)
    if not command:
        print("[ERROR] 缺少 DATA_COMMAND"); sys.exit(1)
    
    print(f"[INFO] 账号: {mask(username)}")
    print(f"[INFO] 命令: {command[:50]}...")
    
    final_status = "failed"
    error_message = ""
    screenshot_file = None
    
    async with async_playwright() as p:
        print("[INFO] 启动浏览器...")
        browser = await p.chromium.launch(
            headless=True,
            args=['--ignore-certificate-errors', '--no-sandbox', '--disable-blink-features=AutomationControlled']
        )
        
        context = await browser.new_context(
            ignore_https_errors=True,
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = await context.new_page()
        
        try:
            login_ok, status, login_shot = await login(page, username, password)
            screenshot_file = login_shot
            
            if not login_ok:
                final_status = status
                error_message = {
                    "disabled": "账户已禁用",
                    "wrong_password": "密码错误", 
                    "network_error": "网络连接失败",
                    "form_error": "登录表单未加载",
                    "username_error": "用户名填写失败",
                    "password_error": "密码填写失败",
                    "timeout": "登录超时"
                }.get(status, f"登录失败: {status}")
            else:
                exec_ok, exec_msg, exec_shot = await execute_command(page, command)
                screenshot_file = exec_shot
                
                if exec_ok:
                    final_status = "success"
                    error_message = exec_msg
                else:
                    final_status = "failed"
                    error_message = exec_msg
            
        except Exception as e:
            print(f"[ERROR] 异常: {e}")
            error_message = str(e)[:100]
            try:
                screenshot_file = shot("error")
                await page.screenshot(path=screenshot_file)
            except:
                pass
        finally:
            await browser.close()
    
    # 输出结果
    print(f"\n{'='*50}")
    print(f"[INFO] 执行结果: {'✅ 成功' if final_status == 'success' else '❌ 失败'}")
    print(f"[INFO] 信息: {error_message}")
    print(f"{'='*50}")
    
    # 发送通知 - 账号不隐藏
    await notify(
        ok=(final_status == "success"),
        username=username,
        info=error_message,
        img=screenshot_file,
        command=command
    )
    
    if final_status in ['disabled', 'wrong_password', 'network_error']:
        sys.exit(0)
    elif final_status != 'success':
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == '__main__':
    asyncio.run(main())
