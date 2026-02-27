#!/usr/bin/env python3
"""Kerit Cloud 自动续订脚本 - 修复续订逻辑"""

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

def handle_page_errors(sb, max_retries: int = 3) -> bool:
    for _ in range(max_retries):
        try:
            body_text = sb.execute_script("return document.body.innerText || ''") or ""
            
            if "Access Restricted" in body_text:
                log("ERROR", "⛔ Access Restricted")
                return False
            
            if "Server error" in body_text:
                log("WARN", "   Server error 弹窗，尝试关闭...")
                close_error_modal(sb)
                time.sleep(2)
                continue
            
            return True
        except:
            return True
    return True

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

# ============== 续订辅助函数 ==============
def get_renewal_count(sb) -> int:
    """获取本周续订次数"""
    try:
        count = sb.execute_script("""
            // 方法1：从专用元素获取
            var el = document.getElementById('renewal-count');
            if (el) return parseInt(el.textContent) || 0;
            
            // 方法2：从页面文本提取 "6 / 7" 格式
            var bodyText = document.body.innerText;
            var match = bodyText.match(/(\\d+)\\s*\\/\\s*7/);
            if (match) return parseInt(match[1]);
            
            return 0;
        """)
        return count or 0
    except:
        return 0

def get_days_remaining(sb) -> int:
    """获取剩余天数"""
    try:
        days = sb.execute_script("""
            // 方法1：从专用元素获取
            var el = document.getElementById('expiry-display');
            if (el) return parseInt(el.textContent) || 0;
            
            // 方法2：从页面文本提取 "6 Days" 格式
            var bodyText = document.body.innerText;
            var match = bodyText.match(/(\\d+)\\s*Days?/i);
            if (match) return parseInt(match[1]);
            
            return 0;
        """)
        return days or 0
    except:
        return 0

def handle_turnstile(sb):
    """处理 Turnstile 验证"""
    try:
        for _ in range(10):
            success = sb.execute_script("""
                return document.body.innerText.includes('Success!') ||
                       document.querySelector('[data-turnstile-response]') !== null;
            """)
            if success:
                return True
            time.sleep(1)
    except:
        pass
    return False

# ============== 续订流程（核心修复）==============
def do_renewal(sb, idx: int, email_masked: str) -> Dict[str, Any]:
    """执行续订 - 基于参考脚本逻辑"""
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
        # ========== 步骤1：进入 Free Panel 页面 ==========
        log("INFO", "📋 进入 Free Panel 页面...")
        sb.uc_open_with_reconnect(FREE_PANEL_URL, reconnect_time=8)
        time.sleep(5)
        
        result["screenshot"] = shot(idx, "10-free-panel")
        sb.save_screenshot(result["screenshot"])
        
        current_url = sb.get_current_url()
        log("INFO", f"   当前 URL: {current_url}")
        
        # ========== 步骤2：获取续订信息 ==========
        log("INFO", "🔍 检查续订状态...")
        
        initial_count = get_renewal_count(sb)
        initial_days = get_days_remaining(sb)
        result["initial_count"] = initial_count
        
        log("INFO", f"   本周已续订: {initial_count}/7")
        log("INFO", f"   剩余天数: {initial_days} 天")
        
        # 获取续订状态文本
        status_text = sb.execute_script("""
            var el = document.getElementById('renewal-status-text');
            return el ? el.textContent.trim() : '未知';
        """) or "未知"
        log("INFO", f"   续订状态: {status_text}")
        
        # ========== 步骤3：检查上限 ==========
        if initial_count >= 7 or initial_days >= 7:
            log("INFO", "🎉 已达上限，无需续订")
            result["success"] = True
            result["final_count"] = initial_count
            result["final_days"] = initial_days
            
            if initial_count >= 7:
                result["message"] = f"🎉 本周已续满 | {initial_count}/7 | {initial_days}天"
            else:
                result["message"] = f"🎉 已达最大有效期 | {initial_count}/7 | {initial_days}天"
            
            notify(True, email_masked, result["message"], result["screenshot"])
            return result
        
        # ========== 步骤4：检查续订按钮 ==========
        renew_btn_disabled = sb.execute_script("""
            var btn = document.getElementById('renewServerBtn');
            if (!btn) return true;
            return btn.disabled || btn.hasAttribute('disabled');
        """)
        
        log("INFO", f"   续订按钮 disabled: {renew_btn_disabled}")
        
        if renew_btn_disabled:
            log("INFO", "⏭️ 续订按钮已禁用，未到续订时间")
            result["success"] = True  # 标记为成功，因为无需操作
            result["final_count"] = initial_count
            result["final_days"] = initial_days
            result["message"] = f"⏭️ 未到续订时间 | {initial_count}/7 | {initial_days}天"
            notify(True, email_masked, result["message"], result["screenshot"])
            return result
        
        # ========== 步骤5：循环续订 ==========
        log("INFO", "✨ 续订按钮可用，开始循环续订...")
        
        total_renewed = 0
        max_renewals = 7
        
        for renewal_round in range(1, max_renewals + 1):
            log("INFO", f"\n{'='*20} 第 {renewal_round} 轮续订 {'='*20}")
            
            current_count = get_renewal_count(sb)
            current_days = get_days_remaining(sb)
            
            log("INFO", f"   当前: {current_count}/7, {current_days}天")
            
            if current_count >= 7:
                log("INFO", "🎉 已达到 7/7，停止续订")
                break
            
            if current_days >= 7:
                log("INFO", "🎉 剩余天数已达 7 天，停止续订")
                break
            
            # 检查按钮状态
            renew_server_btn_disabled = sb.execute_script("""
                var btn = document.getElementById('renewServerBtn');
                if (!btn) return true;
                return btn.disabled || btn.hasAttribute('disabled');
            """)
            
            if renew_server_btn_disabled:
                log("INFO", "   续订按钮已禁用，停止续订")
                break
            
            # 点击 Renew Server 按钮
            sb.execute_script("""
                var btn = document.getElementById('renewServerBtn');
                if (btn && !btn.disabled) btn.click();
            """)
            log("INFO", "   已点击 Renew Server 按钮")
            
            time.sleep(3)
            
            result["screenshot"] = shot(idx, f"11-modal-{renewal_round}")
            sb.save_screenshot(result["screenshot"])
            
            # 等待模态框出现
            modal_visible = sb.execute_script("""
                var modal = document.getElementById('renewalModal');
                if (!modal) return false;
                var style = window.getComputedStyle(modal);
                return style.display !== 'none' && style.visibility !== 'hidden';
            """)
            
            if not modal_visible:
                log("WARN", "   模态框未出现，尝试重新点击...")
                sb.execute_script("""
                    var btn = document.getElementById('renewServerBtn');
                    if (btn) btn.click();
                """)
                time.sleep(3)
            
            # 处理 Turnstile
            log("INFO", "   处理 Turnstile...")
            try:
                sb.uc_gui_click_captcha()
                time.sleep(2)
            except:
                pass
            
            handle_turnstile(sb)
            
            # 点击广告
            log("INFO", "   🖱️ 点击广告横幅...")
            main_window = sb.driver.current_window_handle
            original_windows = set(sb.driver.window_handles)
            
            sb.execute_script("""
                var adBanner = document.getElementById('adBanner');
                if (adBanner) {
                    var parent = adBanner.closest('[onclick]') || adBanner.parentElement;
                    if (parent && parent.onclick) parent.click();
                    else adBanner.click();
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
            
            # 等待最终续订按钮可用
            log("INFO", "   等待 renewBtn 按钮...")
            for _ in range(10):
                btn_ready = sb.execute_script("""
                    var btn = document.getElementById('renewBtn');
                    return btn && !btn.disabled;
                """)
                if btn_ready:
                    break
                time.sleep(1)
            
            # 点击最终续订按钮
            log("INFO", "   🔘 点击 renewBtn...")
            
            renew_btn_ready = sb.execute_script("""
                var btn = document.getElementById('renewBtn');
                if (!btn) return {exists: false};
                return {
                    exists: true,
                    disabled: btn.disabled,
                    visible: btn.offsetParent !== null
                };
            """)
            
            log("INFO", f"   renewBtn 状态: {renew_btn_ready}")
            
            if renew_btn_ready and renew_btn_ready.get("exists") and not renew_btn_ready.get("disabled"):
                sb.execute_script("""
                    var btn = document.getElementById('renewBtn');
                    if (btn && !btn.disabled) btn.click();
                """)
                log("INFO", "   已点击 renewBtn")
            else:
                log("WARN", "   renewBtn 不可用，尝试提交表单...")
                sb.execute_script("""
                    var form = document.querySelector('#renewalModal form');
                    if (form) form.submit();
                """)
            
            # 等待响应
            time.sleep(3)
            
            result["screenshot"] = shot(idx, f"12-result-{renewal_round}")
            sb.save_screenshot(result["screenshot"])
            
            # 检查是否达到限制
            limit_reached = sb.execute_script("""
                var bodyText = document.body.innerText || '';
                return bodyText.includes('Cannot exceed 7 days') ||
                       bodyText.includes('exceed 7 days') ||
                       bodyText.includes('maximum') ||
                       bodyText.includes('limit reached');
            """)
            
            if limit_reached:
                log("INFO", "   ⚠️ 检测到已达续订限制")
                break
            
            total_renewed += 1
            log("INFO", f"   ✅ 第 {renewal_round} 轮续订完成")
            
            # 关闭模态框
            sb.execute_script("""
                var closeBtn = document.querySelector('#renewalModal .close, [data-dismiss="modal"], .btn-close');
                if (closeBtn) closeBtn.click();
                var modal = document.getElementById('renewalModal');
                if (modal) modal.style.display = 'none';
                var backdrop = document.querySelector('.modal-backdrop');
                if (backdrop) backdrop.remove();
                document.body.classList.remove('modal-open');
            """)
            
            time.sleep(2)
            
            # 刷新页面获取最新状态
            sb.refresh()
            time.sleep(3)
            
            # 检查当前状态
            new_count = get_renewal_count(sb)
            new_days = get_days_remaining(sb)
            
            log("INFO", f"   当前状态: {new_count}/7, {new_days}天")
            
            if new_days >= 7:
                log("INFO", "🎉 已达到 7 天有效期上限!")
                break
        
        # ========== 步骤6：获取最终状态 ==========
        time.sleep(2)
        final_count = get_renewal_count(sb)
        final_days = get_days_remaining(sb)
        
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
        if total_renewed > 0:
            result["success"] = True
            result["message"] = f"✅ 续订 {total_renewed} 次 | {final_count}/7 | {final_days}天"
        elif final_count >= 7 or final_days >= 7:
            result["success"] = True
            result["message"] = f"🎉 已达上限 | {final_count}/7 | {final_days}天"
        else:
            result["message"] = f"❌ 未能续订 | {final_count}/7 | {final_days}天"
        
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
