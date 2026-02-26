# scripts/data-online_renew.py
import os
import re
import asyncio
import httpx
from playwright.async_api import async_playwright

# ==================== 配置 ====================
LOGIN_URL = "https://www.data-online.co.uk/login"
TERMINAL_URL = "https://www.data-online.co.uk/console"
TIMEOUT = 60000
MAX_RETRIES = 3

# ==================== 工具函数 ====================
def mask_string(s: str, show: int = 2) -> str:
    """脱敏字符串，只显示前 show 位"""
    if len(s) <= show:
        return "*" * len(s)
    return s[:show] + "*" * (len(s) - show)

def log(msg: str):
    print(f"[INFO] {msg}")

def parse_accounts() -> list:
    """解析账号配置"""
    raw = os.getenv("DATA_ACCOUNT", "")
    accounts = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("----")
        if len(parts) >= 3:
            accounts.append({
                "username": parts[0].strip(),
                "password": parts[1].strip(),
                "command": parts[2].strip()
            })
    return accounts

async def send_telegram(message: str):
    """发送 Telegram 通知"""
    token = os.getenv("TG_BOT_TOKEN", "")
    chat_id = os.getenv("TG_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
                timeout=30
            )
        log("通知发送成功")
    except Exception as e:
        log(f"通知发送失败: {e}")

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

# ==================== 核心逻辑 ====================
async def execute_account(page, account: dict, index: int, screenshot_dir: str) -> dict:
    """执行单个账号的终端命令"""
    username = account["username"]
    masked_user = mask_string(username)
    result = {"account": masked_user, "success": False, "message": ""}
    
    try:
        # 登录
        log("=" * 50)
        log(f"账号 {index}: 登录 {masked_user}")
        log("=" * 50)
        
        log("打开登录页...")
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                log(f"连接尝试 {attempt}/{MAX_RETRIES}")
                await page.goto(LOGIN_URL, timeout=TIMEOUT, wait_until="domcontentloaded")
                log("✅ 连接成功")
                break
            except Exception as e:
                if attempt == MAX_RETRIES:
                    raise Exception(f"无法访问登录页: {e}")
                await asyncio.sleep(3)
        
        log("等待页面加载...")
        await page.wait_for_load_state("networkidle", timeout=TIMEOUT)
        
        log("查找登录表单...")
        await page.wait_for_selector('input[name="username"], input[name="user_name"], input[type="text"]', timeout=TIMEOUT)
        log("✅ 登录表单已找到")
        
        log("填写登录信息...")
        username_selectors = ['input[name="username"]', 'input[name="user_name"]', 'input[type="text"]']
        for selector in username_selectors:
            elem = page.locator(selector).first
            if await elem.count() > 0:
                await elem.fill(username)
                log("✅ 用户名已填写")
                break
        
        password_selectors = ['input[name="password"]', 'input[type="password"]']
        for selector in password_selectors:
            elem = page.locator(selector).first
            if await elem.count() > 0:
                await elem.fill(account["password"])
                log("✅ 密码已填写")
                break
        
        submit_selectors = ['button[type="submit"]', 'input[type="submit"]', 'button:has-text("Login")', 'button:has-text("登录")']
        for selector in submit_selectors:
            elem = page.locator(selector).first
            if await elem.count() > 0:
                await elem.click()
                log("✅ 点击登录按钮")
                break
        
        log("等待登录响应...")
        await page.wait_for_load_state("networkidle", timeout=TIMEOUT)
        
        current_url = page.url
        if "login" in current_url.lower():
            error_elem = page.locator('.error, .alert-danger, .message-error').first
            if await error_elem.count() > 0:
                error_text = await error_elem.text_content()
                raise Exception(f"登录失败: {error_text}")
            raise Exception("登录失败: 仍在登录页面")
        
        log("✅ 登录成功")
        
        # 执行终端命令
        log("")
        log("访问终端页面...")
        await page.goto(TERMINAL_URL, timeout=TIMEOUT, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=TIMEOUT)
        log("✅ 进入终端页面")
        
        log("执行命令...")
        terminal_selectors = ['textarea', 'input[type="text"]', '.terminal-input', '#command']
        command_sent = False
        for selector in terminal_selectors:
            elem = page.locator(selector).first
            if await elem.count() > 0:
                await elem.fill(account["command"])
                await elem.press("Enter")
                command_sent = True
                log("✅ 命令已发送")
                break
        
        if not command_sent:
            await page.keyboard.type(account["command"])
            await page.keyboard.press("Enter")
            log("✅ 命令已发送 (键盘输入)")
        
        await asyncio.sleep(3)
        await page.screenshot(path=f"{screenshot_dir}/account_{index}_terminal.png", full_page=True)
        
        result["success"] = True
        result["message"] = "命令执行成功"
        
        # 发送通知
        await send_telegram(f"✅ <b>Data Online</b>\n账号: {masked_user}\n状态: 命令执行成功")
        
    except Exception as e:
        error_msg = str(e)
        # 脱敏错误信息中可能包含的敏感内容
        error_msg = re.sub(r'(username|password|command)[=:]\s*\S+', r'\1=***', error_msg, flags=re.I)
        result["message"] = error_msg
        log(f"❌ 执行失败: {error_msg}")
        await page.screenshot(path=f"{screenshot_dir}/account_{index}_error.png", full_page=True)
        await send_telegram(f"❌ <b>Data Online</b>\n账号: {masked_user}\n状态: 执行失败\n错误: {error_msg}")
    
    finally:
        try:
            logout_selectors = ['a:has-text("Logout")', 'a:has-text("退出")', 'button:has-text("Logout")']
            for selector in logout_selectors:
                elem = page.locator(selector).first
                if await elem.count() > 0:
                    await elem.click()
                    log("已退出登录")
                    break
        except:
            pass
    
    return result

async def main():
    accounts = parse_accounts()
    if not accounts:
        log("❌ 未配置账号")
        return
    
    log(f"共 {len(accounts)} 个账号")
    
    screenshot_dir = "output/screenshots"
    ensure_dir(screenshot_dir)
    
    results = []
    
    log("启动浏览器...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()
        
        for i, account in enumerate(accounts, 1):
            result = await execute_account(page, account, i, screenshot_dir)
            results.append(result)
            log("")
        
        await browser.close()
    
    # 汇总
    success_count = sum(1 for r in results if r["success"])
    log("=" * 50)
    log(f"📊 执行汇总: {success_count}/{len(results)} 成功")
    log("-" * 50)
    for r in results:
        status = "✅" if r["success"] else "❌"
        log(f"{status} {r['account']}: {r['message']}")
    log("=" * 50)

if __name__ == "__main__":
    asyncio.run(main())
