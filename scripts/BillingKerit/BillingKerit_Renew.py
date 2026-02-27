#!/usr/bin/env python3
"""Kerit Cloud 自动续订脚本 - 修复页面检测和续订逻辑"""

import os, sys, time, platform, requests, re, imaplib, email
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from seleniumbase import SB

# ============== 配置 ==============
BASE_URL = "https://billing.kerit.cloud"
LOGIN_URL = f"{BASE_URL}/"
SESSION_URL = f"{BASE_URL}/session"
FREE_PANEL_URL = f"{BASE_URL}/free_panel"

OUTPUT_DIR = Path("output/screenshots")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CN_TZ = timezone(timedelta(hours=8))

# ============== 工具函数 ==============
def cn_now() -> datetime:
    return datetime.now(CN_TZ)

def cn_time_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return cn_now().strftime(fmt)

def log(level: str, msg: str):
    print(f"[{cn_time_str()}] [{level}] {msg}")

def mask(s: str, show: int = 3) -> str:
    if not s: return "***"
    s = str(s)
    if len(s) <= show: return s[0] + "***"
    return s[:show] + "***"

def mask_email(email_addr: str) -> str:
    if not email_addr or "@" not in email_addr:
        return "***@***"
    local, domain = email_addr.split("@", 1)
    return f"{mask(local, 2)}@{domain}"

def is_linux(): 
    return platform.system().lower() == "linux"

def setup_display():
    if is_linux() and not os.environ.get("DISPLAY"):
        try:
            from pyvirtualdisplay import Display
            d = Display(visible=False, size=(1920, 1080))
            d.start()
            os.environ["DISPLAY"] = d.new_display_var
            log("INFO", "🖥️ 虚拟显示已启动")
            return d
        except Exception as e:
            log("ERROR", f"虚拟显示失败: {e}")
            sys.exit(1)
    return None

def shot(idx: int, name: str) -> str:
    return str(OUTPUT_DIR / f"acc{idx}-{cn_now().strftime('%H%M%S')}-{name}.png")

# ============== 通知函数 ==============
def notify(ok: bool, account: str, info: str, img: str = None):
    token = os.environ.get("TG_BOT_TOKEN")
    chat = os.environ.get("TG_CHAT_ID")
    if not token or not chat:
        return
    
    try:
        icon = "✅" if ok else "❌"
        result = "续订成功" if ok else "续订失败"
        
        text = f"""{icon} Kerit Cloud {result}

账号：{account}
信息：{info}
时间：{cn_time_str()}"""
        
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
        log("WARN", f"通知发送失败: {e}")

# ============== 账号解析 ==============
def parse_accounts(s: str) -> List[Dict[str, str]]:
    accounts = []
    parts = [p.strip() for p in s.replace('\n', '----').split('----') if p.strip()]
    
    for i in range(0, len(parts) - 1, 2):
        email_addr = parts[i]
        imap_pwd = parts[i + 1]
        if "@" in email_addr:
            accounts.append({
                "index": len(accounts) + 1,
                "email": email_addr,
                "imap_password": imap_pwd
            })
    
    return accounts

def get_imap_server(email_addr: str) -> Tuple[str, int]:
    domain = email_addr.split("@")[1].lower()
    servers = {
        "gmail.com": ("imap.gmail.com", 993),
        "outlook.com": ("outlook.office365.com", 993),
        "hotmail.com": ("outlook.office365.com", 993),
        "yahoo.com": ("imap.mail.yahoo.com", 993),
        "163.com": ("imap.163.com", 993),
        "qq.com": ("imap.qq.com", 993),
    }
    return servers.get(domain, (f"imap.{domain}", 993))

# ============== 页面检测 ==============
def close_error_modal(sb) -> bool:
    try:
        return sb.execute_script('''
            var buttons = document.querySelectorAll('button');
            for (var btn of buttons) {
                var text = btn.textContent.trim();
                if (text === 'Got it' || text === 'Try Again' || text === 'OK') {
                    btn.click();
                    return true;
                }
            }
            return false;
        ''') or False
    except:
        return False

def check_page_status(sb) -> Tuple[str, str]:
    """检查页面状态"""
    try:
        result = sb.execute_script('''
            var bodyText = document.body.innerText || '';
            
            // 被阻止
            if (bodyText.includes('Access Restricted')) {
                return {status: "blocked", detail: "Access Restricted"};
            }
            
            // 错误弹窗
            if (bodyText.includes('Server error occurred')) {
                return {status: "error_modal", detail: "Server error"};
            }
            
            // Free Server 页面 (续订页面)
            if (bodyText.includes('Free Server') || 
                bodyText.includes('Extend Lifecycle') ||
                bodyText.includes('Renewals This Week') ||
                bodyText.includes('TIME REMAINING')) {
                return {status: "ok", detail: "Free Server 页面"};
            }
            
            // 登录页面
            if (bodyText.includes('Welcome Back') || 
                bodyText.includes('Enter your Kerit Cloud')) {
                return {status: "ok", detail: "登录页面"};
            }
            
            // OTP 页面
            if (bodyText.includes('Check Your Inbox')) {
                return {status: "ok", detail: "OTP 页面"};
            }
            
            // Session/Dashboard 页面
            if (bodyText.includes('Dashboard') || 
                bodyText.includes('Manage') ||
                bodyText.includes('OPERATIONAL')) {
                return {status: "ok", detail: "Dashboard 页面"};
            }
            
            return {status: "ok", detail: "其他页面"};
        ''')
        
        return result.get('status', 'ok'), result.get('detail', '')
    except:
        return "ok", "检测异常"

def handle_page_errors(sb, max_retries: int = 3) -> bool:
    for retry in range(max_retries):
        status, detail = check_page_status(sb)
        
        if status == "ok":
            return True
        
        if status == "blocked":
            log("ERROR", f"⛔ {detail}")
            return False
        
        if status == "error_modal":
            log("WARN", f"   错误弹窗: {detail}, 尝试关闭...")
            close_error_modal(sb)
            time.sleep(2)
            sb.refresh()
            time.sleep(5)
    
    return True  # 默认返回 True，避免误判

# ============== 邮箱验证码 ==============
def fetch_otp_from_email(email_addr: str, imap_pwd: str, timeout: int = 120) -> Optional[str]:
    log("INFO", f"📧 连接邮箱: {mask_email(email_addr)}")
    
    server, port = get_imap_server(email_addr)
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            mail = imaplib.IMAP4_SSL(server, port)
            mail.login(email_addr, imap_pwd)
            mail.select("INBOX")
            
            search_queries = [
                '(FROM "kerit" UNSEEN)',
                '(SUBJECT "OTP" UNSEEN)',
                '(SUBJECT "verification" UNSEEN)',
            ]
            
            messages = (None, [b''])
            for query in search_queries:
                try:
                    _, messages = mail.search(None, query)
                    if messages[0]:
                        break
                except:
                    continue
            
            if messages[0]:
                msg_ids = messages[0].split()
                for msg_id in reversed(msg_ids[-5:]):
                    _, msg_data = mail.fetch(msg_id, "(RFC822)")
                    msg = email.message_from_bytes(msg_data[0][1])
                    
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() in ["text/plain", "text/html"]:
                                body = part.get_payload(decode=True).decode(errors="ignore")
                                if body:
                                    break
                    else:
                        body = msg.get_payload(decode=True).decode(errors="ignore")
                    
                    otp_match = re.search(r'\b(\d{4})\b', body)
                    if otp_match:
                        otp = otp_match.group(1)
                        mail.store(msg_id, '+FLAGS', '\\Seen')
                        mail.logout()
                        log("INFO", f"✅ 获取到验证码: ****")
                        return otp
            
            mail.logout()
            
        except Exception as e:
            log("WARN", f"   邮箱错误: {e}")
        
        elapsed = int(time.time() - start_time)
        log("INFO", f"   等待邮件... ({elapsed}s)")
        time.sleep(5)
    
    log("ERROR", "❌ 获取验证码超时")
    return None

# ============== OTP 输入 ==============
def input_otp_to_boxes(sb, otp: str) -> bool:
    log("INFO", f"📝 输入验证码...")
    
    try:
        result = sb.execute_script(f'''
            (function() {{
                var otp = "{otp}";
                var inputs = document.querySelectorAll('input');
                var otpInputs = [];
                
                for (var input of inputs) {{
                    var rect = input.getBoundingClientRect();
                    if (rect.width > 30 && rect.width < 100 && rect.height > 30 && rect.height < 100) {{
                        otpInputs.push(input);
                    }}
                }}
                
                if (otpInputs.length >= 4) {{
                    for (var j = 0; j < 4; j++) {{
                        otpInputs[j].value = otp[j];
                        otpInputs[j].dispatchEvent(new Event('input', {{ bubbles: true }}));
                    }}
                    return "success";
                }}
                return "not_found:" + otpInputs.length;
            }})()
        ''')
        
        log("INFO", f"   结果: {result}")
        return result and "success" in str(result)
    except Exception as e:
        log("ERROR", f"   OTP 输入失败: {e}")
        return False

# ============== 登录流程 ==============
def login(sb, email_addr: str, imap_pwd: str, idx: int) -> Tuple[bool, Optional[str]]:
    email_masked = mask_email(email_addr)
    log("INFO", f"\n{'='*50}")
    log("INFO", f"🔐 账号 {idx}: 登录 {email_masked}")
    log("INFO", f"{'='*50}")
    
    last_shot = None
    
    for attempt in range(3):
        try:
            log("INFO", f"尝试 {attempt + 1}/3: 打开登录页...")
            sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=10)
            time.sleep(5)
            
            last_shot = shot(idx, f"01-login-{attempt}")
            sb.save_screenshot(last_shot)
            
            handle_page_errors(sb)
            
            # 检查是否已登录
            current_url = sb.get_current_url()
            if "/session" in current_url or "/free" in current_url:
                log("INFO", "✅ 已登录")
                return True, last_shot
            
            # 等待登录表单
            log("INFO", "   等待登录表单...")
            for _ in range(15):
                has_input = sb.execute_script('''
                    return document.querySelector('input[type="email"]') !== null;
                ''')
                if has_input:
                    break
                time.sleep(1)
            
            # 输入邮箱
            log("INFO", "   输入邮箱...")
            sb.execute_script(f'''
                var input = document.querySelector('input[type="email"], input[placeholder*="email"]');
                if (input) {{
                    input.value = "{email_addr}";
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }}
            ''')
            
            time.sleep(2)
            last_shot = shot(idx, f"02-email-{attempt}")
            sb.save_screenshot(last_shot)
            
            # 处理 Turnstile
            log("INFO", "   处理 Turnstile...")
            try:
                sb.uc_gui_click_captcha()
            except:
                pass
            
            # 等待 Turnstile
            for _ in range(20):
                if sb.execute_script("return document.body.innerText.includes('Success!')"):
                    log("INFO", "   ✅ Turnstile 通过")
                    break
                time.sleep(1)
            
            # 点击 Continue
            log("INFO", "   点击 Continue with Email...")
            sb.execute_script('''
                var buttons = document.querySelectorAll('button');
                for (var btn of buttons) {
                    if (btn.textContent.includes('Continue with Email')) {
                        btn.click();
                        return;
                    }
                }
            ''')
            
            time.sleep(5)
            last_shot = shot(idx, f"03-after-continue-{attempt}")
            sb.save_screenshot(last_shot)
            
            handle_page_errors(sb)
            
            # 检查 OTP 页面
            otp_page = sb.execute_script('''
                return document.body.innerText.includes('Check Your Inbox');
            ''')
            
            if not otp_page:
                log("WARN", "   未进入 OTP 页面")
                continue
            
            log("INFO", "✅ 进入 OTP 验证页面")
            
            # 获取验证码
            otp = fetch_otp_from_email(email_addr, imap_pwd, timeout=120)
            if not otp:
                return False, last_shot
            
            # 输入 OTP
            input_otp_to_boxes(sb, otp)
            time.sleep(2)
            
            last_shot = shot(idx, "04-otp-input")
            sb.save_screenshot(last_shot)
            
            # 点击 Verify
            log("INFO", "   点击 Verify Code...")
            sb.execute_script('''
                var buttons = document.querySelectorAll('button');
                for (var btn of buttons) {
                    if (btn.textContent.includes('Verify')) {
                        btn.click();
                        return;
                    }
                }
            ''')
            
            time.sleep(5)
            last_shot = shot(idx, "05-verify-result")
            sb.save_screenshot(last_shot)
            
            handle_page_errors(sb)
            
            current_url = sb.get_current_url()
            log("INFO", f"   当前 URL: {current_url}")
            
            if "/session" in current_url or "/free" in current_url:
                log("INFO", "✅ 登录成功!")
                return True, last_shot
            
            time.sleep(3)
            current_url = sb.get_current_url()
            if "/session" in current_url:
                log("INFO", "✅ 登录成功!")
                return True, last_shot
            
        except Exception as e:
            log("ERROR", f"   异常: {e}")
            continue
    
    log("ERROR", "❌ 登录失败")
    return False, last_shot

# ============== 续订流程（核心修复）==============
def get_renewal_info(sb) -> Dict[str, Any]:
    """获取续订信息 - 基于实际页面结构"""
    try:
        info = sb.execute_script('''
            var result = {count: 0, total: 7, days: 0, canRenew: false, btnText: ""};
            var bodyText = document.body.innerText;
            
            // 提取 "6 / 7" 格式的续订次数
            var renewMatch = bodyText.match(/(\\d+)\\s*\\/\\s*(\\d+)/);
            if (renewMatch) {
                result.count = parseInt(renewMatch[1]);
                result.total = parseInt(renewMatch[2]);
            }
            
            // 提取剩余天数 "6 Days"
            var daysMatch = bodyText.match(/(\\d+)\\s*Days?/i);
            if (daysMatch) {
                result.days = parseInt(daysMatch[1]);
            }
            
            // 检查是否可以续订
            result.canRenew = bodyText.includes('Ready to renew') || 
                             bodyText.includes('You can renew');
            
            // 检查续订按钮
            var renewBtn = Array.from(document.querySelectorAll('button, a')).find(
                el => el.textContent.includes('Renew Server')
            );
            if (renewBtn) {
                result.btnText = renewBtn.textContent.trim();
                result.btnDisabled = renewBtn.disabled || false;
            }
            
            return result;
        ''')
        
        return info or {"count": 0, "total": 7, "days": 0, "canRenew": False}
    except:
        return {"count": 0, "total": 7, "days": 0, "canRenew": False}

def click_renew_button(sb) -> bool:
    """点击 Renew Server 按钮"""
    try:
        clicked = sb.execute_script('''
            // 查找 Renew Server 按钮
            var buttons = document.querySelectorAll('button, a');
            for (var btn of buttons) {
                if (btn.textContent.includes('Renew Server')) {
                    btn.click();
                    return true;
                }
            }
            return false;
        ''')
        return clicked or False
    except:
        return False

def do_renewal(sb, idx: int, email_masked: str) -> Dict[str, Any]:
    """执行续订"""
    result = {
        "success": False,
        "message": "",
        "screenshot": None,
        "initial_count": 0,
        "final_count": 0,
        "final_days": 0,
        "renewed": 0
    }
    
    try:
        # ========== 步骤1：进入 Free Server 页面 ==========
        log("INFO", "📋 进入 Free Server 页面...")
        
        # 先尝试点击侧边栏
        sb.execute_script('''
            var items = document.querySelectorAll('a, button, [onclick]');
            for (var item of items) {
                if (item.textContent.includes('Free Server') || 
                    item.textContent.includes('Free Plans')) {
                    item.click();
                    return true;
                }
            }
        ''')
        
        time.sleep(3)
        
        # 如果没跳转，直接访问
        current_url = sb.get_current_url()
        if "/free" not in current_url:
            log("INFO", "   直接访问 /free_panel...")
            sb.uc_open_with_reconnect(FREE_PANEL_URL, reconnect_time=8)
            time.sleep(5)
        
        result["screenshot"] = shot(idx, "10-free-server")
        sb.save_screenshot(result["screenshot"])
        
        current_url = sb.get_current_url()
        log("INFO", f"   当前 URL: {current_url}")
        
        # ========== 步骤2：获取初始状态 ==========
        info = get_renewal_info(sb)
        initial_count = info.get("count", 0)
        initial_days = info.get("days", 0)
        can_renew = info.get("canRenew", False)
        
        result["initial_count"] = initial_count
        
        log("INFO", f"📊 当前状态:")
        log("INFO", f"   本周续订: {initial_count}/{info.get('total', 7)}")
        log("INFO", f"   剩余天数: {initial_days} 天")
        log("INFO", f"   可以续订: {'是' if can_renew else '否'}")
        
        # 检查是否已达上限
        if initial_count >= 7:
            log("INFO", "🎉 本周已达续订上限 (7/7)")
            result["success"] = True
            result["final_count"] = initial_count
            result["final_days"] = initial_days
            result["message"] = f"已达上限 | {initial_count}/7 | {initial_days}天"
            notify(True, email_masked, result["message"], result["screenshot"])
            return result
        
        if initial_days >= 7:
            log("INFO", "🎉 已有 7 天时长，无需续订")
            result["success"] = True
            result["final_count"] = initial_count
            result["final_days"] = initial_days
            result["message"] = f"已满 7 天 | {initial_count}/7 | {initial_days}天"
            notify(True, email_masked, result["message"], result["screenshot"])
            return result
        
        # ========== 步骤3：循环续订 ==========
        total_renewed = 0
        max_rounds = 7 - initial_count  # 最多续订次数
        
        for round_num in range(1, max_rounds + 1):
            log("INFO", f"\n{'='*15} 第 {round_num} 轮 {'='*15}")
            
            # 获取当前状态
            info = get_renewal_info(sb)
            current_count = info.get("count", 0)
            current_days = info.get("days", 0)
            
            log("INFO", f"   状态: {current_count}/7, {current_days}天")
            
            if current_count >= 7 or current_days >= 7:
                log("INFO", "🎉 已达上限")
                break
            
            # 点击 Renew Server 按钮
            log("INFO", "   🔘 点击 Renew Server...")
            if not click_renew_button(sb):
                log("WARN", "   未找到 Renew Server 按钮")
                break
            
            time.sleep(3)
            result["screenshot"] = shot(idx, f"11-modal-{round_num}")
            sb.save_screenshot(result["screenshot"])
            
            # 处理 Turnstile
            log("INFO", "   处理 Turnstile...")
            try:
                sb.uc_gui_click_captcha()
            except:
                pass
            time.sleep(3)
            
            # 点击广告链接
            log("INFO", "   🖱️ 点击广告...")
            main_window = sb.driver.current_window_handle
            original_windows = set(sb.driver.window_handles)
            
            sb.execute_script('''
                // 查找广告链接/按钮
                var adElements = document.querySelectorAll('[onclick*="openAd"], [onclick*="adLink"], #adBanner, .ad-banner, a[target="_blank"]');
                for (var el of adElements) {
                    el.click();
                    return;
                }
                // 备用：查找任何外部链接
                var links = document.querySelectorAll('a[href*="http"]');
                for (var link of links) {
                    if (link.target === '_blank') {
                        link.click();
                        return;
                    }
                }
            ''')
            
            time.sleep(4)
            
            # 关闭广告窗口
            new_windows = set(sb.driver.window_handles) - original_windows
            if new_windows:
                log("INFO", f"   关闭 {len(new_windows)} 个广告窗口")
                for win in new_windows:
                    try:
                        sb.driver.switch_to.window(win)
                        time.sleep(1)
                        sb.driver.close()
                    except:
                        pass
                sb.driver.switch_to.window(main_window)
            
            time.sleep(2)
            
            # 等待完成按钮可用
            log("INFO", "   等待完成按钮...")
            for _ in range(15):
                btn_ready = sb.execute_script('''
                    var btns = document.querySelectorAll('button');
                    for (var btn of btns) {
                        var text = btn.textContent.toLowerCase();
                        if ((text.includes('complete') || text.includes('renew') || text.includes('confirm')) 
                            && !btn.disabled) {
                            return true;
                        }
                    }
                    return false;
                ''')
                if btn_ready:
                    break
                time.sleep(1)
            
            # 点击完成续订按钮
            log("INFO", "   🔘 点击完成续订...")
            sb.execute_script('''
                var btns = document.querySelectorAll('button');
                for (var btn of btns) {
                    var text = btn.textContent.toLowerCase();
                    if ((text.includes('complete') || text.includes('confirm renewal')) && !btn.disabled) {
                        btn.click();
                        return;
                    }
                }
            ''')
            
            time.sleep(4)
            result["screenshot"] = shot(idx, f"12-result-{round_num}")
            sb.save_screenshot(result["screenshot"])
            
            # 检查是否成功
            new_info = get_renewal_info(sb)
            new_count = new_info.get("count", 0)
            
            if new_count > current_count:
                total_renewed += 1
                log("INFO", f"   ✅ 第 {round_num} 轮成功! ({new_count}/7)")
            else:
                log("WARN", f"   ⚠️ 第 {round_num} 轮可能未成功")
            
            # 关闭模态框
            sb.execute_script('''
                var closeBtn = document.querySelector('[class*="close"], .modal-close, button[aria-label="Close"]');
                if (closeBtn) closeBtn.click();
            ''')
            
            time.sleep(2)
            
            # 刷新页面
            sb.refresh()
            time.sleep(4)
            
            # 检查是否还能续订
            info = get_renewal_info(sb)
            if info.get("count", 0) >= 7 or info.get("days", 0) >= 7:
                log("INFO", "🎉 已达上限，停止续订")
                break
        
        # ========== 步骤4：获取最终状态 ==========
        time.sleep(2)
        final_info = get_renewal_info(sb)
        final_count = final_info.get("count", 0)
        final_days = final_info.get("days", 0)
        
        result["final_count"] = final_count
        result["final_days"] = final_days
        result["renewed"] = total_renewed
        
        result["screenshot"] = shot(idx, "13-final")
        sb.save_screenshot(result["screenshot"])
        
        log("INFO", f"\n📊 最终状态:")
        log("INFO", f"   本周续订: {final_count}/7")
        log("INFO", f"   剩余天数: {final_days} 天")
        log("INFO", f"   本次续订: {total_renewed} 次")
        
        # 判断结果
        if total_renewed > 0 or final_count >= 7 or final_days >= 7:
            result["success"] = True
            result["message"] = f"续订 {total_renewed} 次 | {final_count}/7 | {final_days}天"
        else:
            result["message"] = f"未能续订 | {final_count}/7 | {final_days}天"
        
    except Exception as e:
        log("ERROR", f"续订异常: {e}")
        result["message"] = f"异常: {str(e)[:50]}"
        if not result["screenshot"]:
            result["screenshot"] = shot(idx, "error")
            try:
                sb.save_screenshot(result["screenshot"])
            except:
                pass
    
    return result

# ============== 主流程 ==============
def process(sb, account: Dict, idx: int) -> Dict[str, Any]:
    """处理单个账号"""
    email_addr = account["email"]
    imap_pwd = account["imap_password"]
    email_masked = mask_email(email_addr)
    
    result = {
        "email": email_addr,
        "email_masked": email_masked,
        "success": False,
        "message": "",
        "screenshot": None
    }
    
    # 清除 Cookie
    try:
        sb.delete_all_cookies()
    except:
        pass
    
    # 登录
    login_ok, login_shot = login(sb, email_addr, imap_pwd, idx)
    result["screenshot"] = login_shot
    
    if not login_ok:
        result["message"] = "登录失败"
        notify(False, email_masked, "⚠️ 登录失败", login_shot)
        return result
    
    # 续订
    renewal = do_renewal(sb, idx, email_masked)
    result["success"] = renewal["success"]
    result["message"] = renewal["message"]
    result["screenshot"] = renewal["screenshot"]
    
    # 发送通知
    if renewal["success"]:
        notify(True, email_masked, renewal["message"], renewal["screenshot"])
    else:
        notify(False, email_masked, renewal["message"], renewal["screenshot"])
    
    return result

def main():
    log("INFO", "=" * 55)
    log("INFO", "🚀 Kerit Cloud 自动续订脚本")
    log("INFO", "=" * 55)
    
    # 解析账号
    acc_str = os.environ.get("BILLING_KERIT_MAIL", "")
    if not acc_str:
        log("ERROR", "缺少 BILLING_KERIT_MAIL 环境变量")
        notify(False, "系统", "⚠️ 缺少账号配置", None)
        sys.exit(1)
    
    accounts = parse_accounts(acc_str)
    if not accounts:
        log("ERROR", "无有效账号")
        notify(False, "系统", "⚠️ 无有效账号", None)
        sys.exit(1)
    
    log("INFO", f"📋 发现 {len(accounts)} 个账号")
    for acc in accounts:
        log("INFO", f"   {acc['index']}. {mask_email(acc['email'])}")
    
    # 代理
    proxy = os.environ.get("PROXY_SOCKS5") or os.environ.get("PROXY_HTTP", "")
    if proxy:
        log("INFO", f"🌐 使用代理: {mask(proxy, 10)}")
        try:
            requests.get("https://api.ipify.org", proxies={"http": proxy, "https": proxy}, timeout=10)
            log("INFO", "   ✅ 代理正常")
        except Exception as e:
            log("WARN", f"   代理测试失败: {e}")
    
    # 虚拟显示
    display = setup_display()
    results = []
    
    try:
        opts = {
            "uc": True,
            "test": True,
            "locale_code": "en",
            "headless": False
        }
        if proxy:
            opts["proxy"] = proxy.replace("socks5://", "socks5h://")
        
        with SB(**opts) as sb:
            log("INFO", "🌐 浏览器已启动")
            
            for acc in accounts:
                try:
                    r = process(sb, acc, acc["index"])
                    results.append(r)
                    time.sleep(5)
                except Exception as e:
                    err_shot = shot(acc["index"], "fatal")
                    try:
                        sb.save_screenshot(err_shot)
                    except:
                        err_shot = None
                    log("ERROR", f"账号 {mask_email(acc['email'])} 异常: {e}")
                    results.append({
                        "email_masked": mask_email(acc["email"]),
                        "success": False,
                        "message": str(e)
                    })
                    notify(False, mask_email(acc["email"]), f"⚠️ {e}", err_shot)
    
    except Exception as e:
        log("ERROR", f"脚本异常: {e}")
        notify(False, "系统", f"⚠️ 脚本异常: {e}", None)
        sys.exit(1)
    
    finally:
        if display:
            display.stop()
    
    # 汇总
    ok_count = sum(1 for r in results if r.get("success"))
    
    log("INFO", "")
    log("INFO", "=" * 55)
    log("INFO", f"📊 汇总: {ok_count}/{len(results)} 成功")
    log("INFO", "-" * 55)
    for r in results:
        icon = "✅" if r.get("success") else "❌"
        log("INFO", f"   {icon} {r.get('email_masked', '***')}: {r.get('message', '')}")
    log("INFO", "=" * 55)
    
    sys.exit(0 if ok_count > 0 else 1)

if __name__ == "__main__":
    main()
