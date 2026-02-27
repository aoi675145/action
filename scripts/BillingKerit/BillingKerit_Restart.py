#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, re, asyncio, logging
from base64 import b64encode
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
from urllib.parse import unquote

try:
    import aiohttp
    from playwright.async_api import async_playwright
except ImportError:
    print("[ERROR] pip install playwright aiohttp pynacl && playwright install chromium")
    sys.exit(1)

# ==================== 配置 ====================

BASE_URL = "https://panel.kerit.cloud"
OUTPUT_DIR = Path("output/screenshots")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CN_TZ = timezone(timedelta(hours=8))

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ==================== 工具函数 ====================

def cn_now() -> datetime:
    return datetime.now(CN_TZ)

def cn_time_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return cn_now().strftime(fmt)

def mask(s: str, show: int = 2) -> str:
    if not s: return "***"
    return s[:show] + "****" if len(s) > show else s[0] + "***"

def mask_email(email: str) -> str:
    if '@' not in str(email): return mask(email)
    local, domain = email.split('@', 1)
    return f"{mask(local)}@{mask(domain)}"

def shot_path() -> str:
    return str(OUTPUT_DIR / f"{cn_now().strftime('%H%M%S%f')[:9]}.png")

# ==================== GitHub Manager ====================

class GitHubManager:
    def __init__(self, token: Optional[str], repo: Optional[str]):
        self.token, self.repo = token, repo
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        } if token else {}

    async def update_secret(self, name: str, value: str) -> bool:
        if not self.token or not self.repo:
            return False
        try:
            from nacl import encoding, public
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"https://api.github.com/repos/{self.repo}/actions/secrets/public-key",
                    headers=self.headers
                ) as r:
                    if r.status != 200:
                        return False
                    kd = await r.json()
                pk = public.PublicKey(kd["key"].encode(), encoding.Base64Encoder())
                enc = b64encode(public.SealedBox(pk).encrypt(value.encode())).decode()
                async with s.put(
                    f"https://api.github.com/repos/{self.repo}/actions/secrets/{name}",
                    headers=self.headers,
                    json={"encrypted_value": enc, "key_id": kd["key_id"]}
                ) as r:
                    if r.status in [201, 204]:
                        logger.info(f"✅ Secret {name} 已更新")
                        return True
        except Exception as e:
            logger.error(f"❌ GitHub异常")
        return False

# ==================== Telegram 通知 ====================

class TelegramNotifier:
    def __init__(self, token: Optional[str], chat_id: Optional[str]):
        self.token, self.chat_id = token, chat_id
        self.api = f"https://api.telegram.org/bot{token}" if token else None

    async def send(self, ok: bool, title: str, details: str = "", image_path: str = None):
        if not self.api or not self.chat_id:
            return
        
        icon = "✅" if ok else "❌"
        text = f"{icon} {title}\n\n{details}\n时间：{cn_time_str()}\n\nBilling Kerit Auto Restart"
        
        try:
            async with aiohttp.ClientSession() as s:
                if image_path and Path(image_path).exists():
                    data = aiohttp.FormData()
                    data.add_field("chat_id", self.chat_id)
                    data.add_field("caption", text[:1024])
                    data.add_field("photo", open(image_path, "rb"), filename="screenshot.png")
                    async with s.post(f"{self.api}/sendPhoto", data=data) as r:
                        pass
                else:
                    async with s.post(f"{self.api}/sendMessage", json={"chat_id": self.chat_id, "text": text}) as r:
                        pass
        except Exception as e:
            logger.warning("通知发送失败")

# ==================== Kerit API ====================

class KeritAPI:
    def __init__(self, cookie_str: str):
        self.cookie_str = cookie_str
        self.cookies = self._parse_cookies(cookie_str)
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": BASE_URL,
            "Origin": BASE_URL,
        }
        # 设置 XSRF Token
        for c in self.cookies:
            if c["name"] == "XSRF-TOKEN":
                self.headers["X-XSRF-TOKEN"] = unquote(c["value"])
                break

    def _parse_cookies(self, s: str) -> List[Dict[str, Any]]:
        cookies = []
        for item in s.split(';'):
            if '=' in item:
                k, v = item.strip().split('=', 1)
                if k and v:
                    cookies.append({"name": k, "value": v, "domain": "panel.kerit.cloud", "path": "/"})
        return cookies

    def _cookie_header(self) -> str:
        return "; ".join([f"{c['name']}={c['value']}" for c in self.cookies])

    async def get_status(self, server_id: str) -> Dict[str, Any]:
        result = {"state": "unknown", "is_suspended": False}
        try:
            async with aiohttp.ClientSession() as s:
                headers = {**self.headers, "Cookie": self._cookie_header()}
                async with s.get(f"{BASE_URL}/api/client/servers/{server_id}/resources", headers=headers) as r:
                    if r.status == 200:
                        data = await r.json()
                        attrs = data.get("attributes", {})
                        result["state"] = attrs.get("current_state", "unknown")
                        result["is_suspended"] = attrs.get("is_suspended", False)
        except:
            pass
        return result

    async def power_action(self, server_id: str, action: str) -> bool:
        try:
            async with aiohttp.ClientSession() as s:
                headers = {**self.headers, "Cookie": self._cookie_header(), "Content-Type": "application/json"}
                async with s.post(
                    f"{BASE_URL}/api/client/servers/{server_id}/power",
                    headers=headers,
                    json={"signal": action}
                ) as r:
                    return r.status in [200, 204]
        except:
            return False

# ==================== 账号解析 ====================

def parse_accounts() -> List[Dict[str, Any]]:
    accounts = []
    for key, value in os.environ.items():
        if key.startswith("BILLING_KERIT_COOKIES_") and "----" in value:
            parts = value.strip().split("----", 1)
            if len(parts) == 2 and parts[0] and parts[1]:
                try:
                    idx = int(key.split("_")[-1])
                except:
                    idx = 999
                accounts.append({"name": parts[0].strip(), "cookie": parts[1].strip(), "env_key": key, "index": idx})
    return sorted(accounts, key=lambda x: x["index"])

# ==================== 服务器处理 ====================

async def process_server(page, api: KeritAPI, server: Dict[str, str], idx: int) -> Dict[str, Any]:
    sid, name = server["id"], server["name"]
    result = {"id": sid, "name": name, "success": False, "message": "", "action": "none"}
    
    logger.info(f"服务器 #{idx + 1}: {mask(sid)}")
    
    status = await api.get_status(sid)
    state = status["state"]
    logger.info(f"状态: {state}")
    
    if status["is_suspended"]:
        result["message"] = "⚠️ 已暂停"
        return result
    
    if state != "offline":
        result["success"] = True
        result["message"] = f"正常 ({state})"
        result["action"] = "skip"
        logger.info("✅ 无需操作")
        return result
    
    logger.info("服务器离线，启动中...")
    result["action"] = "start"
    
    try:
        await page.goto(f"{BASE_URL}/server/{sid}", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
        
        # 尝试点击启动按钮
        clicked = False
        for selector in ["#power-start", "button:has-text('Start')", "[data-action='start']"]:
            try:
                btn = await page.query_selector(selector)
                if btn:
                    await btn.click()
                    clicked = True
                    logger.info("✅ 点击 Start 按钮成功")
                    break
            except:
                continue
        
        # JS 备用
        if not clicked:
            clicked = await page.evaluate('''() => {
                const btn = document.getElementById('power-start') || 
                           [...document.querySelectorAll('button')].find(b => b.textContent.toLowerCase().includes('start'));
                if (btn) { btn.click(); return true; }
                return false;
            }''')
            if clicked:
                logger.info("✅ JS 点击成功")
        
        # API 备用
        if not clicked:
            if await api.power_action(sid, "start"):
                clicked = True
                logger.info("✅ API 启动命令已发送")
        
        if clicked:
            for i in range(6):
                await asyncio.sleep(5)
                new_state = (await api.get_status(sid))["state"]
                logger.info(f"({(i+1)*5}s) 状态: {new_state}")
                if new_state == "running":
                    result["success"], result["message"] = True, "✅ 启动成功"
                    return result
                if new_state == "starting":
                    result["success"], result["message"] = True, "启动中..."
                    return result
            result["message"] = f"启动超时 ({new_state})"
        else:
            result["message"] = "⚠️ 未找到启动按钮"
    except Exception as e:
        result["message"] = "⚠️ 操作异常"
    
    return result

# ==================== 账号处理 ====================

async def process_account(account: Dict[str, Any], idx: int, github: GitHubManager) -> Dict[str, Any]:
    name, cookie_str, env_key = account["name"], account["cookie"], account["env_key"]
    masked = mask_email(name) if "@" in name else mask(name)
    
    result = {
        "account": name, "masked": masked, "env_key": env_key,
        "success": False, "message": "", "servers": [], "screenshot": None
    }
    
    logger.info(f"\n{'='*50}")
    logger.info(f"账号 #{idx + 1}: {masked}")
    logger.info(f"{'='*50}")
    
    api = KeritAPI(cookie_str)
    if not api.cookies:
        result["message"] = "Cookie 解析失败"
        return result
    
    logger.info(f"解析到 {len(api.cookies)} 个 Cookie")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
        )
        await context.add_cookies(api.cookies)
        page = await context.new_page()
        
        try:
            logger.info("访问面板首页...")
            await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)
            
            result["screenshot"] = shot_path()
            await page.screenshot(path=result["screenshot"], full_page=True)
            logger.info("截图已保存")
            
            if "/auth/login" in page.url:
                result["message"] = "Cookie 已过期"
                logger.error(result["message"])
                return result
            
            # 检查 Cookie 更新
            new_cookies = await context.cookies()
            new_str = "; ".join([f"{c['name']}={c['value']}" for c in new_cookies 
                                 if "kerit.cloud" in c.get("domain", "")])
            if new_str and new_str != cookie_str:
                if await github.update_secret(env_key, f"{name}----{new_str}"):
                    logger.info("Cookie 已自动更新")
            
            content = await page.content()
            
            # 用户名
            if m := re.search(r'"username":"([^"]+)"', content):
                logger.info(f"✅ 登录成功 (用户: {mask(m.group(1))})")
            else:
                logger.info("✅ 登录成功")
            
            # 查找服务器
            servers = []
            for sid in set(re.findall(r'href="/server/([a-zA-Z0-9]+)"', content)):
                servers.append({"id": sid, "name": f"Server-{sid[:6]}"})
            
            logger.info(f"找到 {len(servers)} 个服务器")
            for s in servers:
                logger.info(f"  - {mask(s['id'])}")
            
            if not servers:
                result["message"] = "未找到服务器"
                logger.warning(result["message"])
                return result
            
            # 处理服务器
            for i, srv in enumerate(servers):
                srv_result = await process_server(page, api, srv, i)
                result["servers"].append(srv_result)
                await asyncio.sleep(1)
            
            result["screenshot"] = shot_path()
            await page.screenshot(path=result["screenshot"], full_page=True)
            
            ok = sum(1 for s in result["servers"] if s["success"])
            result["success"] = ok > 0 or all(s["action"] == "skip" for s in result["servers"])
            result["message"] = f"{ok}/{len(result['servers'])} 正常"
            
        except Exception as e:
            logger.error("处理异常")
            result["message"] = "处理异常"
        finally:
            await browser.close()
    
    return result

# ==================== 主函数 ====================

async def main():
    logger.info(f"\n{'='*60}")
    logger.info(f"  Billing Kerit 自动重启")
    logger.info(f"  {cn_time_str()}")
    logger.info(f"{'='*60}")
    
    accounts = parse_accounts()
    if not accounts:
        logger.error("无有效账号 (需要 BILLING_KERIT_COOKIES_* 环境变量)")
        sys.exit(1)
    
    # 筛选指定账号
    if target := os.environ.get("ACCOUNT_NAME", "").strip():
        accounts = [a for a in accounts if a["name"] == target]
        if not accounts:
            logger.error("未找到指定账号")
            sys.exit(1)
    
    logger.info(f"处理 {len(accounts)} 个账号")
    
    github = GitHubManager(os.environ.get("REPO_TOKEN"), os.environ.get("GITHUB_REPOSITORY"))
    tg = TelegramNotifier(os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID"))
    
    results = []
    for i, acc in enumerate(accounts):
        try:
            results.append(await process_account(acc, i, github))
        except Exception as e:
            results.append({"account": acc["name"], "masked": mask_email(acc["name"]), 
                          "success": False, "message": "处理异常", "servers": []})
        await asyncio.sleep(2)
    
    # 汇总
    logger.info(f"\n{'='*60}")
    logger.info("  执行汇总")
    logger.info(f"{'='*60}")
    
    tg_lines, total_ok, total_srv, last_shot = [], 0, 0, None
    
    for r in results:
        icon = "✅" if r["success"] else "❌"
        logger.info(f"{icon} 账号: {r['message']}")
        tg_lines.append(f"{icon} {r['account']}: {r['message']}")
        
        if r.get("screenshot"):
            last_shot = r["screenshot"]
        
        for s in r.get("servers", []):
            srv_icon = "✓" if s["success"] else "✗"
            logger.info(f"  {srv_icon} 服务器: {s['message']}")
            tg_lines.append(f"  {srv_icon} {s['name']}: {s['message']}")
            total_srv += 1
            total_ok += s["success"]
    
    all_ok = all(r["success"] for r in results)
    await tg.send(all_ok, "执行完成" if all_ok else "部分失败", "\n".join(tg_lines), last_shot)
    
    logger.info(f"\n📊 服务器: {total_ok}/{total_srv} 正常")
    sys.exit(0 if all_ok else 1)

if __name__ == "__main__":
    asyncio.run(main())
