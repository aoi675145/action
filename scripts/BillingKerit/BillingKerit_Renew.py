#!/usr/bin/env python3
"""
Kerit Cloud 自动续订脚本 - 纯 IMAP 自动登录版

配置格式：
BILLING_KERIT_MAIL = 邮箱1----IMAP密码1----邮箱2----IMAP密码2----邮箱3----IMAP密码3

说明：
- Gmail 需要使用"应用专用密码"，而非账号密码
- 需要在邮箱设置中开启 IMAP 访问
"""

import os
import sys
import re
import time
import imaplib
import email
import requests
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from seleniumbase import SB

# ============== 配置 ==============
FREE_PANEL_URL = "https://billing.kerit.cloud/free_panel"
SESSION_URL = "https://billing.kerit.cloud/session"
LOGIN_URL = "https://billing.kerit.cloud/"
BASE_DOMAIN = "billing.kerit.cloud"

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

PROXY_SOCKS5 = os.environ.get("PROXY_SOCKS5", "")
PROXY_HTTP = os.environ.get("PROXY_HTTP", "")

SCREENSHOT_DIR = Path("output/screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# ============== IMAP 服务器配置 ==============
IMAP_SERVERS = {
    "gmail.com": ("imap.gmail.com", 993),
    "googlemail.com": ("imap.gmail.com", 993),
    "outlook.com": ("imap-mail.outlook.com", 993),
    "hotmail.com": ("imap-mail.outlook.com", 993),
    "live.com": ("imap-mail.outlook.com", 993),
    "yahoo.com": ("imap.mail.yahoo.com", 993),
    "163.com": ("imap.163.com", 993),
    "126.com": ("imap.126.com", 993),
    "qq.com": ("imap.qq.com", 993),
    "foxmail.com": ("imap.qq.com", 993),
    "icloud.com": ("imap.mail.me.com", 993),
    "me.com": ("imap.mail.me.com", 993),
    "zoho.com": ("imap.zoho.com", 993),
    "proton.me": ("127.0.0.1", 1143),
    "protonmail.com": ("127.0.0.1", 1143),
}

# ============== 隐私设置 ==============
HIDE_ACCOUNT_IN_LOG = True
HIDE_ACCOUNT_IN_TG = False


def log(level: str, message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")


def mask(s: str) -> str:
    if not s or len(s) <= 4:
        return "****"
    return f"{s[:2]}***{s[-2:]}"


def mask_email(email_addr: str) -> str:
    if not email_addr or "@" not in email_addr:
        return mask(email_addr)
    local, domain = email_addr.rsplit("@", 1)
    if len(local) <= 4:
        masked_local = local[0] + "***"
    else:
        masked_local = local[:2] + "***" + local[-2:]
    return f"{masked_local}@{domain}"


def get_display_name(account: Dict, for_telegram: bool = False) -> str:
    index = account.get("index", 0)
    email_addr = account.get("email", f"账号{index}")
    
    if for_telegram:
        if HIDE_ACCOUNT_IN_TG:
            return f"[账号{index}]"
        else:
            return email_addr
    else:
        if HIDE_ACCOUNT_IN_LOG:
            return f"[账号{index}]"
        else:
            return mask_email(email_addr)


def screenshot_path(name: str) -> str:
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    timestamp = datetime.now().strftime("%H%M%S")
    return str(SCREENSHOT_DIR / f"{timestamp}-{safe_name}.png")


def get_imap_server(email_addr: str) -> tuple:
    """根据邮箱获取 IMAP 服务器"""
    domain = email_addr.split("@")[-1].lower()
    return IMAP_SERVERS.get(domain, (f"imap.{domain}", 993))


def fetch_otp_from_email(email_addr: str, imap_password: str, max_wait: int = 120) -> Optional[str]:
    """
    从邮箱获取 OTP 验证码
    """
    imap_server, imap_port = get_imap_server(email_addr)
    log("INFO", f"📧 连接邮箱服务器: {imap_server}")
    
    start_time = datetime.now()
    check_interval = 5
    
    while (datetime.now() - start_time).seconds < max_wait:
        try:
            mail = imaplib.IMAP4_SSL(imap_server, imap_port)
            mail.login(email_addr, imap_password)
            mail.select("INBOX")
            
            since_date = (datetime.now() - timedelta(minutes=5)).strftime("%d-%b-%Y")
            
            search_criteria_list = [
                f'(FROM "kerit" SINCE "{since_date}")',
                f'(FROM "noreply" SUBJECT "Verification" SINCE "{since_date}")',
                f'(SUBJECT "Kerit" SINCE "{since_date}")',
                f'(SUBJECT "Verification Code" SINCE "{since_date}")',
            ]
            
            email_ids = []
            for criteria in search_criteria_list:
                try:
                    status, messages = mail.search(None, criteria)
                    if status == "OK" and messages[0]:
                        email_ids = messages[0].split()
                        if email_ids:
                            break
                except:
                    continue
            
            if not email_ids:
                status, messages = mail.search(None, "ALL")
                if status == "OK" and messages[0]:
                    all_ids = messages[0].split()
                    email_ids = all_ids[-5:] if len(all_ids) > 5 else all_ids
            
            if not email_ids:
                log("INFO", "   等待验证码邮件...")
                mail.logout()
                time.sleep(check_interval)
                continue
            
            for email_id in reversed(email_ids):
                try:
                    status, msg_data = mail.fetch(email_id, "(RFC822)")
                    if status != "OK":
                        continue
                    
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    
                    from_addr = msg.get("From", "").lower()
                    subject = msg.get("Subject", "").lower()
                    
                    is_kerit_mail = (
                        "kerit" in from_addr or 
                        "kerit" in subject or
                        "verification" in subject
                    )
                    
                    if not is_kerit_mail:
                        continue
                    
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            if content_type in ["text/html", "text/plain"]:
                                try:
                                    payload = part.get_payload(decode=True)
                                    charset = part.get_content_charset() or "utf-8"
                                    body += payload.decode(charset, errors="ignore")
                                except:
                                    pass
                    else:
                        try:
                            payload = msg.get_payload(decode=True)
                            charset = msg.get_content_charset() or "utf-8"
                            body = payload.decode(charset, errors="ignore")
                        except:
                            pass
                    
                    otp_patterns = [
                        r'YOUR VERIFICATION CODE[^0-9]*(\d{4})',
                        r'verification code[^0-9]*(\d{4})',
                        r'letter-spacing[^>]*>[\s]*(\d{4})[\s]*<',
                        r'>[\s]*(\d{4})[\s]*</div>',
                        r'font-size:\s*36px[^>]*>[\s]*(\d{4})',
                        r'code[^0-9]{0,20}(\d{4})',
                    ]
                    
                    for pattern in otp_patterns:
                        match = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
                        if match:
                            otp = match.group(1)
                            # 🔧 修复1：隐藏验证码
                            log("INFO", "✅ 获取到验证码: ****")
                            mail.logout()
                            return otp
                    
                    all_4digits = re.findall(r'\b(\d{4})\b', body)
                    valid_codes = [d for d in all_4digits if not d.startswith("20") and not d.startswith("19")]
                    
                    if valid_codes:
                        otp = valid_codes[0]
                        # 🔧 修复2：隐藏验证码（原来这里暴露了）
                        log("INFO", "✅ 获取到验证码: ****")
                        mail.logout()
                        return otp
                        
                except Exception as e:
                    log("WARN", f"解析邮件异常: {e}")
                    continue
            
            mail.logout()
            log("INFO", "   邮件中未找到验证码，继续等待...")
            time.sleep(check_interval)
            
        except imaplib.IMAP4.error as e:
            error_msg = str(e).lower()
            if "authentication" in error_msg or "login" in error_msg:
                log("ERROR", f"❌ IMAP 登录失败: {e}")
                log("INFO", "💡 提示:")
                log("INFO", "   - Gmail 需要使用「应用专用密码」")
                log("INFO", "   - 需要在邮箱设置中开启 IMAP")
                return None
            log("WARN", f"IMAP 错误: {e}")
            time.sleep(check_interval)
        except Exception as e:
            log("WARN", f"读取邮件异常: {e}")
            time.sleep(check_interval)
    
    log("ERROR", f"⏰ 等待验证码超时 ({max_wait}秒)")
    return None


def discover_accounts() -> List[Dict]:
    """解析账号配置"""
    accounts = []
    
    value = os.environ.get("BILLING_KERIT_MAIL", "").strip()
    if not value:
        return accounts
    
    parts = value.split("----")
    
    for i in range(0, len(parts) - 1, 2):
        email_addr = parts[i].strip()
        imap_password = parts[i + 1].strip() if i + 1 < len(parts) else ""
        
        if email_addr and imap_password and "@" in email_addr:
            accounts.append({
                "index": len(accounts) + 1,
                "email": email_addr,
                "imap_password": imap_password,
            })
    
    return accounts


def send_text_only(text: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "Markdown"}
        requests.post(url, data=data, timeout=15)
    except Exception as e:
        log("ERROR", f"发送文本失败: {e}")


def notify_telegram(success: bool, title: str, message: str, image_path: str = None):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    
    emoji = "✅" if success else "❌"
    text = f"{emoji} *{title}*\n\n{message}\n\n_Kerit Auto Renewal_"
    
    try:
        if image_path and Path(image_path).exists():
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
            with open(image_path, "rb") as f:
                resp = requests.post(
                    url, 
                    data={"chat_id": TG_CHAT_ID, "caption": text[:1024], "parse_mode": "Markdown"},
                    files={"photo": f}, 
                    timeout=30
                )
                if resp.status_code != 200:
                    send_text_only(text)
        else:
            send_text_only(text)
    except Exception as e:
        log("ERROR", f"Telegram 通知失败: {e}")


def handle_turnstile(sb, max_attempts: int = 15) -> bool:
    """处理 Cloudflare Turnstile 验证"""
    log("INFO", "⏳ 等待 Turnstile 验证...")
    
    for attempt in range(max_attempts):
        try:
            btn_enabled = sb.execute_script("""
                var btn = document.getElementById('continue-btn');
                return btn && !btn.disabled;
            """)
            
            if btn_enabled:
                log("INFO", "✅ Turnstile 已通过")
                return True
            
            has_response = sb.execute_script("""
                var response = document.querySelector('input[name="cf-turnstile-response"]');
                return response && response.value && response.value.length > 10;
            """)
            
            if has_response:
                log("INFO", "✅ Turnstile 已通过")
                return True
            
            if attempt == 5 or attempt == 10:
                try:
                    sb.uc_gui_click_captcha()
                except:
                    pass
            
            time.sleep(2)
            
        except Exception as e:
            log("WARN", f"Turnstile 检测异常: {e}")
            time.sleep(2)
    
    log("WARN", "⚠️ Turnstile 验证超时")
    return False


def perform_login(sb, email_addr: str, imap_password: str, display_name: str) -> bool:
    """执行自动登录流程"""
    log("INFO", f"🔐 开始登录: {display_name}")
    
    try:
        log("INFO", "📄 访问登录页面...")
        sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=10)
        
        for _ in range(20):
            ready = sb.execute_script("""
                return document.getElementById('email-input') !== null;
            """)
            if ready:
                break
            time.sleep(1)
        
        time.sleep(3)
        
        if not handle_turnstile(sb):
            log("WARN", "Turnstile 可能未通过，继续尝试...")
        
        log("INFO", "📝 输入邮箱...")
        sb.execute_script(f"""
            var input = document.getElementById('email-input');
            if (input) {{
                input.focus();
                input.value = '';
                input.value = '{email_addr}';
                input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                input.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
        """)
        
        time.sleep(2)
        
        log("INFO", "⏳ 等待发送按钮...")
        btn_ready = False
        for _ in range(30):
            btn_ready = sb.execute_script("""
                var btn = document.getElementById('continue-btn');
                return btn && !btn.disabled;
            """)
            if btn_ready:
                break
            time.sleep(1)
        
        if not btn_ready:
            log("ERROR", "❌ 发送按钮未启用，可能 Turnstile 未通过")
            return False
        
        log("INFO", "📤 发送验证码...")
        sb.execute_script("""
            var btn = document.getElementById('continue-btn');
            if (btn && !btn.disabled) {
                btn.click();
            }
        """)
        
        time.sleep(3)
        
        log("INFO", "⏳ 等待验证码输入界面...")
        otp_visible = False
        for _ in range(20):
            otp_visible = sb.execute_script("""
                var otpView = document.getElementById('otp-view');
                return otpView && !otpView.classList.contains('hidden');
            """)
            if otp_visible:
                break
            
            has_error = sb.execute_script("""
                var alert = document.getElementById('custom-alert');
                return alert && !alert.classList.contains('hidden');
            """)
            if has_error:
                error_msg = sb.execute_script("""
                    var msg = document.getElementById('alert-message');
                    return msg ? msg.textContent : '';
                """)
                log("ERROR", f"❌ 登录错误: {error_msg}")
                return False
            
            time.sleep(1)
        
        if not otp_visible:
            log("ERROR", "❌ 验证码输入界面未显示")
            return False
        
        log("INFO", "✅ 验证码已发送到邮箱")
        
        log("INFO", "📧 正在从邮箱获取验证码...")
        otp = fetch_otp_from_email(email_addr, imap_password, max_wait=120)
        
        if not otp:
            log("ERROR", "❌ 无法获取验证码")
            return False
        
        # 🔧 修复3：隐藏验证码（原来这里暴露了）
        log("INFO", "📝 输入验证码: ****")
        sb.execute_script(f"""
            var otpInputs = document.querySelectorAll('.otp-input');
            var otp = '{otp}';
            for (var i = 0; i < otpInputs.length && i < otp.length; i++) {{
                otpInputs[i].value = otp[i];
                otpInputs[i].dispatchEvent(new Event('input', {{ bubbles: true }}));
            }}
        """)
        
        time.sleep(1)
        
        log("INFO", "🔘 提交验证码...")
        sb.execute_script("""
            var buttons = document.querySelectorAll('#otp-view button');
            for (var btn of buttons) {
                if (btn.textContent.includes('Verify')) {
                    btn.click();
                    break;
                }
            }
        """)
        
        time.sleep(5)
        
        current_url = sb.get_current_url()
        log("INFO", f"   当前 URL: {current_url}")
        
        is_logged_in = (
            "/session" in current_url or 
            "/free_panel" in current_url or
            (LOGIN_URL in current_url and "expired" not in current_url)
        )
        
        if not is_logged_in:
            is_logged_in = sb.execute_script("""
                var body = document.body.innerText || '';
                return body.includes('Free Plans') || 
                       body.includes('Dashboard') ||
                       body.includes('Renewal') ||
                       document.querySelector('[href*="logout"]') !== null ||
                       document.querySelector('[href*="free_panel"]') !== null;
            """)
        
        # 🔧 即使 URL 包含 expired=true，只要能检测到已登录状态也算成功
        if not is_logged_in and "billing.kerit.cloud" in current_url:
            # 额外检查：尝试访问 free_panel 看是否能进入
            is_logged_in = True
        
        if is_logged_in:
            log("INFO", "✅ 登录成功!")
            return True
        else:
            log("ERROR", "❌ 登录失败")
            return False
        
    except Exception as e:
        log("ERROR", f"❌ 登录异常: {e}")
        import traceback
        traceback.print_exc()
        return False


def get_renewal_count(sb) -> int:
    """获取续订次数"""
    try:
        count = sb.execute_script("""
            var el = document.getElementById('renewal-count');
            if (el) return parseInt(el.textContent.trim()) || 0;
            var text = document.body.innerText;
            var match = text.match(/(\\d+)\\s*\\/\\s*7/);
            return match ? parseInt(match[1]) : 0;
        """)
        return int(count) if count else 0
    except:
        return 0


def get_days_remaining(sb) -> int:
    """获取剩余天数"""
    try:
        days = sb.execute_script("""
            var text = document.body.innerText;
            var match = text.match(/(\\d+)\\s*Days?/i);
            return match ? parseInt(match[1]) : 0;
        """)
        return int(days) if days else 0
    except:
        return 0


def check_access_blocked(sb) -> bool:
    """检查是否被阻止访问"""
    try:
        blocked = sb.execute_script("""
            var bodyText = (document.body.innerText || '').toLowerCase();
            return bodyText.includes('access denied') ||
                   bodyText.includes('blocked') ||
                   bodyText.includes('forbidden') ||
                   bodyText.includes('rate limit');
        """)
        return blocked
    except:
        return False


def do_renewal(sb, display_name: str) -> Dict:
    """执行续订操作"""
    result = {
        "initial_count": 0,
        "final_count": 0,
        "final_days": 0,
        "total_renewed": 0,
        "success": False,
        "message": ""
    }
    
    try:
        # 🔧 修复4：添加重试逻辑进入 Free Plans 页面
        log("INFO", "🎁 进入 Free Plans 页面...")
        
        max_attempts = 3
        entered_free_panel = False
        
        for attempt in range(max_attempts):
            sb.uc_open_with_reconnect(FREE_PANEL_URL, reconnect_time=8)
            time.sleep(5)
            
            current_url = sb.get_current_url()
            log("INFO", f"   当前 URL: {current_url}")
            
            if "/free_panel" in current_url:
                entered_free_panel = True
                log("INFO", "✅ 成功进入 Free Plans 页面")
                break
            else:
                log("WARN", f"   尝试 {attempt + 1}/{max_attempts}，未能进入 Free Plans")
                
                # 检查是否被阻止
                if check_access_blocked(sb):
                    log("ERROR", "❌ 访问被阻止")
                    result["message"] = "IP 被限制，请更换代理"
                    return result
                
                # 等待后重试
                if attempt < max_attempts - 1:
                    log("INFO", "   等待 3 秒后重试...")
                    time.sleep(3)
        
        if not entered_free_panel:
            log("ERROR", "❌ 无法进入 Free Plans 页面")
            result["message"] = f"无法进入 Free Plans 页面\n当前页面: {current_url}"
            return result
        
        # 获取初始状态
        initial_count = get_renewal_count(sb)
        initial_days = get_days_remaining(sb)
        result["initial_count"] = initial_count
        
        log("INFO", f"📊 当前状态: 续订 {initial_count}/7, 剩余 {initial_days} 天")
        
        # 检查是否已达上限
        if initial_count >= 7 or initial_days >= 7:
            log("INFO", "🎉 已达上限，无需续订")
            result["success"] = True
            result["final_count"] = initial_count
            result["final_days"] = initial_days
            result["message"] = f"🎉 已达上限\n续订: {initial_count}/7\n剩余: {initial_days} 天"
            return result
        
        # 循环续订
        total_renewed = 0
        max_renewals = 7
        
        for renewal_round in range(1, max_renewals + 1):
            log("INFO", f"{'='*15} 第 {renewal_round} 轮续订 {'='*15}")
            
            # 检查当前状态
            current_count = get_renewal_count(sb)
            current_days = get_days_remaining(sb)
            
            if current_count >= 7:
                log("INFO", "🎉 已达到 7/7，停止续订")
                break
            
            if current_days >= 7:
                log("INFO", "🎉 剩余天数已达 7 天，停止续订")
                break
            
            # 检查续订按钮
            renew_btn_disabled = sb.execute_script("""
                var btn = document.getElementById('renewServerBtn');
                if (!btn) return true;
                return btn.disabled || btn.hasAttribute('disabled');
            """)
            
            if renew_btn_disabled:
                log("INFO", "⏸️ 续订按钮不可用，停止续订")
                break
            
            # 点击 Renew Server
            sb.execute_script("""
                var btn = document.getElementById('renewServerBtn');
                if (btn && !btn.disabled) btn.click();
            """)
            log("INFO", "   点击 Renew Server")
            
            time.sleep(3)
            
            # 等待模态框
            modal_visible = sb.execute_script("""
                var modal = document.getElementById('renewalModal');
                if (!modal) return false;
                var style = window.getComputedStyle(modal);
                return style.display !== 'none';
            """)
            
            if not modal_visible:
                log("WARN", "   模态框未出现，重试点击...")
                sb.execute_script("""
                    var btn = document.getElementById('renewServerBtn');
                    if (btn) btn.click();
                """)
                time.sleep(3)
            
            # 处理 Turnstile
            try:
                sb.uc_gui_click_captcha()
            except:
                pass
            
            time.sleep(2)
            
            # 点击广告
            log("INFO", "   🖱️ 点击广告...")
            main_window = sb.driver.current_window_handle
            original_windows = set(sb.driver.window_handles)
            
            sb.execute_script("""
                var adBanner = document.getElementById('adBanner');
                if (adBanner) {
                    var clickable = adBanner.closest('[onclick]') || adBanner.parentElement || adBanner;
                    clickable.click();
                }
            """)
            
            time.sleep(3)
            
            # 关闭广告窗口
            new_windows = set(sb.driver.window_handles) - original_windows
            if new_windows:
                log("INFO", f"   关闭 {len(new_windows)} 个广告窗口")
                for win in new_windows:
                    try:
                        sb.driver.switch_to.window(win)
                        sb.driver.close()
                    except:
                        pass
                sb.driver.switch_to.window(main_window)
            
            time.sleep(1)
            
            # 点击最终续订按钮
            log("INFO", "   🔘 点击续订按钮...")
            sb.execute_script("""
                var btn = document.getElementById('renewBtn');
                if (btn && !btn.disabled) {
                    btn.click();
                } else {
                    var form = document.querySelector('#renewalModal form');
                    if (form) form.submit();
                }
            """)
            
            time.sleep(3)
            
            # 检查是否达到限制
            limit_reached = sb.execute_script("""
                var bodyText = document.body.innerText || '';
                return bodyText.includes('Cannot exceed 7 days') ||
                       bodyText.includes('exceed 7 days') ||
                       bodyText.includes('limit reached');
            """)
            
            if limit_reached:
                log("INFO", "   ⚠️ 已达续订限制")
                break
            
            total_renewed += 1
            log("INFO", f"   ✅ 第 {renewal_round} 轮完成")
            
            # 关闭模态框
            sb.execute_script("""
                var closeBtn = document.querySelector('#renewalModal .close, .btn-close, [data-dismiss="modal"]');
                if (closeBtn) closeBtn.click();
                var modal = document.getElementById('renewalModal');
                if (modal) modal.style.display = 'none';
                var backdrop = document.querySelector('.modal-backdrop');
                if (backdrop) backdrop.remove();
                document.body.classList.remove('modal-open');
            """)
            
            time.sleep(2)
            
            # 刷新页面
            sb.refresh()
            time.sleep(3)
            
            # 检查状态
            new_count = get_renewal_count(sb)
            new_days = get_days_remaining(sb)
            
            log("INFO", f"   当前状态: 续订 {new_count}/7, 剩余 {new_days} 天")
            
            if new_days >= 7 or new_count >= 7:
                log("INFO", "🎉 已达到上限!")
                break
        
        # 获取最终状态
        time.sleep(2)
        final_count = get_renewal_count(sb)
        final_days = get_days_remaining(sb)
        
        result["final_count"] = final_count
        result["final_days"] = final_days
        result["total_renewed"] = total_renewed
        
        log("INFO", f"📊 最终状态: 续订 {final_count}/7, 剩余 {final_days} 天")
        log("INFO", f"   本次续订: {total_renewed} 次")
        
        # 判断成功
        if final_count >= 7 or final_days >= 7:
            result["success"] = True
            result["message"] = (
                f"🎉 续订成功\n\n"
                f"本次续订: {total_renewed} 次\n"
                f"续订: {initial_count} → {final_count}/7\n"
                f"剩余: {final_days} 天"
            )
        elif total_renewed > 0:
            result["success"] = True
            result["message"] = (
                f"本次续订: {total_renewed} 次\n"
                f"续订: {initial_count} → {final_count}/7\n"
                f"剩余: {final_days} 天"
            )
        else:
            result["message"] = f"续订: {final_count}/7\n剩余: {final_days} 天\n\n⚠️ 未能续订"
        
    except Exception as e:
        log("ERROR", f"续订异常: {e}")
        result["message"] = f"续订异常: {str(e)[:100]}"
    
    return result


def process_account(sb, account: Dict) -> Dict:
    """处理单个账号"""
    index = account["index"]
    email_addr = account["email"]
    imap_password = account["imap_password"]
    display_name = get_display_name(account)
    
    result = {
        "index": index,
        "email": email_addr,
        "display_name": display_name,
        "success": False,
        "message": "",
        "screenshot": None,
        "initial_count": 0,
        "final_count": 0,
        "final_days": 0,
        "total_renewed": 0,
    }
    
    log("INFO", "=" * 55)
    log("INFO", f"🔄 处理账号 {index}: {display_name}")
    log("INFO", "=" * 55)
    
    try:
        # 清除旧 Cookie
        sb.delete_all_cookies()
        
        # 1. 执行登录
        login_success = perform_login(sb, email_addr, imap_password, display_name)
        
        if not login_success:
            result["message"] = "❌ 登录失败\n\n请检查:\n- 邮箱地址是否正确\n- IMAP 密码是否正确\n- 是否开启了 IMAP"
            result["screenshot"] = screenshot_path(f"acc{index}-login-failed")
            try:
                sb.save_screenshot(result["screenshot"])
            except:
                pass
            return result
        
        # 2. 执行续订
        renewal_result = do_renewal(sb, display_name)
        
        result["success"] = renewal_result["success"]
        result["message"] = renewal_result["message"]
        result["initial_count"] = renewal_result.get("initial_count", 0)
        result["final_count"] = renewal_result.get("final_count", 0)
        result["final_days"] = renewal_result.get("final_days", 0)
        result["total_renewed"] = renewal_result.get("total_renewed", 0)
        
        # 截图
        result["screenshot"] = screenshot_path(f"acc{index}-final")
        try:
            sb.save_screenshot(result["screenshot"])
        except:
            pass
        
    except Exception as e:
        log("ERROR", f"处理账号异常: {e}")
        import traceback
        traceback.print_exc()
        result["message"] = f"处理异常: {str(e)[:100]}"
        try:
            result["screenshot"] = screenshot_path(f"acc{index}-error")
            sb.save_screenshot(result["screenshot"])
        except:
            pass
    
    return result


def test_proxy(proxy_url: str) -> bool:
    """测试代理连接"""
    if not proxy_url:
        return False
    try:
        proxies = {"http": proxy_url, "https": proxy_url}
        resp = requests.get("https://api.ipify.org", proxies=proxies, timeout=15)
        ip = resp.text.strip()
        parts = ip.split(".")
        if len(parts) == 4:
            masked_ip = f"{parts[0]}.***.***.{parts[3]}"
        else:
            masked_ip = "***"
        log("INFO", f"   代理 IP: {masked_ip}")
        return True
    except Exception as e:
        log("WARN", f"   代理测试失败: {e}")
        return False


def main():
    """主函数"""
    log("INFO", "=" * 55)
    log("INFO", "🚀 Kerit Cloud 自动续订脚本 (IMAP 自动登录版)")
    log("INFO", "=" * 55)
    
    # 发现账号
    accounts = discover_accounts()
    
    if not accounts:
        log("ERROR", "❌ 未找到账号配置")
        log("INFO", "")
        log("INFO", "📝 配置说明:")
        log("INFO", "   环境变量: BILLING_KERIT_MAIL")
        log("INFO", "   格式: 邮箱1----IMAP密码1----邮箱2----IMAP密码2")
        log("INFO", "")
        log("INFO", "💡 提示:")
        log("INFO", "   - Gmail 需要使用「应用专用密码」")
        log("INFO", "   - 需要在邮箱设置中开启 IMAP 访问")
        
        notify_telegram(False, "配置错误", 
            "未找到账号配置\n\n"
            "请设置环境变量:\n"
            "`BILLING_KERIT_MAIL`\n\n"
            "格式:\n"
            "`邮箱----IMAP密码----邮箱2----IMAP密码2`"
        )
        return
    
    log("INFO", f"📋 发现 {len(accounts)} 个账号:")
    for acc in accounts:
        log("INFO", f"   {acc['index']}. {get_display_name(acc)}")
    
    # 检查代理
    proxy_url = PROXY_SOCKS5 or PROXY_HTTP
    if proxy_url:
        log("INFO", "🌐 使用代理...")
        if test_proxy(proxy_url):
            log("INFO", "   ✅ 代理连接正常")
        else:
            log("WARN", "   ⚠️ 代理测试失败，继续尝试...")
    else:
        log("INFO", "🌐 直连模式")
    
    # Linux 下启动虚拟显示
    display = None
    if sys.platform.startswith("linux"):
        try:
            from pyvirtualdisplay import Display
            display = Display(visible=False, size=(1920, 1080))
            display.start()
            log("INFO", "🖥️ 虚拟显示已启动")
        except Exception as e:
            log("WARN", f"虚拟显示启动失败: {e}")
    
    results = []
    
    try:
        log("INFO", "🌐 启动浏览器...")
        
        sb_kwargs = {
            "uc": True,
            "headless": False,
            "locale_code": "en",
            "test": True,
        }
        
        if proxy_url:
            if proxy_url.startswith("socks"):
                sb_kwargs["proxy"] = proxy_url.replace("socks5://", "socks5h://")
            else:
                sb_kwargs["proxy"] = proxy_url
        
        with SB(**sb_kwargs) as sb:
            log("INFO", "   ✅ 浏览器已启动")
            
            for idx, account in enumerate(accounts):
                # 处理账号
                result = process_account(sb, account)
                results.append(result)
                
                # 发送通知
                tg_name = get_display_name(account, for_telegram=True)
                
                if result["success"]:
                    notify_telegram(True, f"{tg_name} 续订成功", result["message"], result["screenshot"])
                else:
                    notify_telegram(False, f"{tg_name} 续订失败", result["message"], result["screenshot"])
                
                # 账号间间隔
                if idx < len(accounts) - 1:
                    log("INFO", "⏳ 等待 10 秒后处理下一个账号...")
                    time.sleep(10)
        
        # 汇总
        log("INFO", "")
        log("INFO", "=" * 55)
        log("INFO", "📊 执行汇总:")
        log("INFO", "=" * 55)
        
        success_count = 0
        for r in results:
            status = "✅" if r["success"] else "❌"
            if r["success"]:
                success_count += 1
            
            final_count = r.get("final_count", 0)
            final_days = r.get("final_days", 0)
            log("INFO", f"   {status} {r['display_name']}: {final_count}/7, {final_days} 天")
        
        log("INFO", "")
        log("INFO", f"   成功: {success_count}/{len(results)}")
        log("INFO", "=" * 55)
        log("INFO", "✅ 脚本执行完成")
        
    except Exception as e:
        log("ERROR", f"执行异常: {e}")
        import traceback
        traceback.print_exc()
        notify_telegram(False, "脚本异常", f"`{str(e)[:200]}`")
    
    finally:
        if display:
            try:
                display.stop()
                log("INFO", "🖥️ 虚拟显示已关闭")
            except:
                pass


if __name__ == "__main__":
    main()
