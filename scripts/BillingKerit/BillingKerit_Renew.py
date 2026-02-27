#!/usr/bin/env python3
"""
Kerit Cloud 自动续订脚本 - 纯 IMAP 自动登录版

配置格式：
BILLING_KERIT_MAIL = 邮箱1----IMAP密码1----邮箱2----IMAP密码2----邮箱3----IMAP密码3

说明：
- Gmail 需要使用"应用专用密码"，而非账号密码
- 需要在邮箱设置中开启 IMAP 访问
"""

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
    """发送 Telegram 通知（带截图）"""
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
    """解析账号配置"""
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
    """获取 IMAP 服务器配置"""
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
def check_blocked(sb) -> Tuple[bool, str]:
    """检查是否被阻止，返回 (是否阻止, 原因)"""
    try:
        src = sb.get_page_source()
        
        if "Access Restricted" in src:
            return True, "Access Restricted - VPN/代理被检测"
        
        if "Server error occurred" in src:
            return True, "Server error - 服务器错误"
        
        if "unusual network activity" in src:
            return True, "异常网络活动被检测"
        
        # 检查错误弹窗
        error_modal = sb.execute_script('''
            var errorText = document.body.innerText;
            if (errorText.includes('Server error') || errorText.includes('Error')) {
                var gotItBtn = document.querySelector('button');
                if (gotItBtn && gotItBtn.textContent.includes('Got it')) {
                    return "Server error modal";
                }
            }
            return null;
        ''')
        
        if error_modal:
            return True, error_modal
        
        return False, ""
    except:
        return False, ""

# ============== 邮箱验证码 ==============
def fetch_otp_from_email(email_addr: str, imap_pwd: str, timeout: int = 120) -> Optional[str]:
    """从邮箱获取 OTP 验证码"""
    log("INFO", f"📧 连接邮箱: {mask_email(email_addr)}")
    
    server, port = get_imap_server(email_addr)
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            mail = imaplib.IMAP4_SSL(server, port)
            mail.login(email_addr, imap_pwd)
            mail.select("INBOX")
            
            # 搜索 Kerit 相关邮件
            search_queries = [
                '(FROM "kerit" UNSEEN)',
                '(SUBJECT "OTP" UNSEEN)',
                '(SUBJECT "verification" UNSEEN)',
                '(SUBJECT "code" UNSEEN)',
            ]
            
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
                    
                    # 获取邮件内容
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            if content_type == "text/plain":
                                body = part.get_payload(decode=True).decode(errors="ignore")
                                break
                            elif content_type == "text/html":
                                body = part.get_payload(decode=True).decode(errors="ignore")
                    else:
                        body = msg.get_payload(decode=True).decode(errors="ignore")
                    
                    # 提取 4 位 OTP
                    otp_match = re.search(r'\b(\d{4})\b', body)
                    if otp_match:
                        otp = otp_match.group(1)
                        mail.store(msg_id, '+FLAGS', '\\Seen')
                        mail.logout()
                        log("INFO", f"✅ 获取到验证码: ****")
                        return otp
            
            mail.logout()
            
        except Exception as e:
            log("WARN", f"   邮箱连接失败: {e}")
        
        log("INFO", f"   等待验证码邮件... ({int(time.time() - start_time)}s)")
        time.sleep(5)
    
    log("ERROR", "❌ 获取验证码超时")
    return None

# ============== 登录流程 ==============
def input_otp_to_boxes(sb, otp: str) -> bool:
    """将 OTP 输入到 4 个单独的输入框"""
    log("INFO", f"📝 输入验证码到 4 个输入框...")
    
    try:
        # 方法1：使用 JavaScript 找到所有输入框并填入
        result = sb.execute_script(f'''
            (function() {{
                var otp = "{otp}";
                
                // 查找所有可能的 OTP 输入框
                var inputs = document.querySelectorAll('input[type="text"], input[type="tel"], input[type="number"]');
                var otpInputs = [];
                
                // 过滤出 OTP 输入框（通常是短的、单字符的输入框）
                for (var i = 0; i < inputs.length; i++) {{
                    var input = inputs[i];
                    var maxLen = input.maxLength;
                    var placeholder = input.placeholder || "";
                    
                    // OTP 输入框通常 maxLength=1 或者是数字输入
                    if (maxLen === 1 || maxLen === -1) {{
                        var rect = input.getBoundingClientRect();
                        if (rect.width > 0 && rect.width < 100) {{
                            otpInputs.push(input);
                        }}
                    }}
                }}
                
                // 如果找到 4 个输入框，填入 OTP
                if (otpInputs.length >= 4) {{
                    for (var j = 0; j < 4 && j < otp.length; j++) {{
                        otpInputs[j].value = otp[j];
                        otpInputs[j].dispatchEvent(new Event('input', {{ bubbles: true }}));
                        otpInputs[j].dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }}
                    return "success";
                }}
                
                // 备用方法：查找特定的 OTP 容器
                var otpContainer = document.querySelector('[class*="otp"], [class*="code"], [class*="verify"]');
                if (otpContainer) {{
                    var containerInputs = otpContainer.querySelectorAll('input');
                    if (containerInputs.length >= 4) {{
                        for (var k = 0; k < 4 && k < otp.length; k++) {{
                            containerInputs[k].value = otp[k];
                            containerInputs[k].dispatchEvent(new Event('input', {{ bubbles: true }}));
                            containerInputs[k].dispatchEvent(new Event('change', {{ bubbles: true }}));
                        }}
                        return "success";
                    }}
                }}
                
                return "not_found";
            }})()
        ''')
        
        if result == "success":
            log("INFO", "   ✅ OTP 已填入输入框")
            return True
        
        # 方法2：逐个定位输入框
        log("INFO", "   尝试备用方法...")
        for i, digit in enumerate(otp[:4]):
            try:
                # 尝试多种选择器
                selectors = [
                    f'input:nth-of-type({i+1})',
                    f'input[data-index="{i}"]',
                    f'input[aria-label*="{i+1}"]',
                ]
                
                for sel in selectors:
                    try:
                        if sb.is_element_present(sel):
                            sb.type(sel, digit)
                            break
                    except:
                        continue
            except:
                continue
        
        return True
        
    except Exception as e:
        log("ERROR", f"   OTP 输入失败: {e}")
        return False

def login(sb, email_addr: str, imap_pwd: str, idx: int) -> Tuple[bool, Optional[str]]:
    """登录流程"""
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
            
            # 检查是否被阻止
            blocked, reason = check_blocked(sb)
            if blocked:
                log("ERROR", f"⚠️ {reason}")
                if attempt < 2:
                    log("INFO", "   等待后重试...")
                    time.sleep(10)
                    continue
                return False, last_shot
            
            # 检查是否已登录
            current_url = sb.get_current_url()
            if "/session" in current_url:
                log("INFO", "✅ 已登录")
                return True, last_shot
            
            # 等待邮箱输入框
            log("INFO", "   等待登录表单...")
            for _ in range(10):
                if sb.is_element_present('input[type="email"]') or sb.is_element_present('input[placeholder*="email"]'):
                    break
                time.sleep(1)
            
            # 输入邮箱
            log("INFO", "   输入邮箱...")
            email_input = sb.execute_script('''
                var inputs = document.querySelectorAll('input');
                for (var i = 0; i < inputs.length; i++) {
                    var input = inputs[i];
                    if (input.type === 'email' || 
                        input.placeholder.toLowerCase().includes('email') ||
                        input.name === 'email') {
                        return input;
                    }
                }
                return null;
            ''')
            
            if email_input:
                sb.execute_script(f'''
                    var input = arguments[0];
                    input.value = "{email_addr}";
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                ''', email_input)
            else:
                sb.type('input[type="email"], input[placeholder*="email"]', email_addr)
            
            time.sleep(2)
            
            last_shot = shot(idx, f"02-email-{attempt}")
            sb.save_screenshot(last_shot)
            
            # 处理 Turnstile
            log("INFO", "   处理 Turnstile...")
            try:
                sb.uc_gui_click_captcha()
            except:
                pass
            time.sleep(3)
            
            # 等待 Turnstile 完成
            for _ in range(15):
                turnstile_ok = sb.execute_script('''
                    var successText = document.body.innerText;
                    return successText.includes('Success!') || 
                           document.querySelector('[data-turnstile-response]') !== null;
                ''')
                if turnstile_ok:
                    log("INFO", "   ✅ Turnstile 验证通过")
                    break
                time.sleep(1)
            
            # 点击 Continue with Email
            log("INFO", "   点击 Continue with Email...")
            sb.execute_script('''
                var buttons = document.querySelectorAll('button');
                for (var btn of buttons) {
                    if (btn.textContent.includes('Continue with Email') || 
                        btn.textContent.includes('Continue')) {
                        btn.click();
                        return true;
                    }
                }
                var submitBtn = document.querySelector('button[type="submit"]');
                if (submitBtn) submitBtn.click();
            ''')
            
            time.sleep(5)
            
            last_shot = shot(idx, f"03-after-continue-{attempt}")
            sb.save_screenshot(last_shot)
            
            # 检查是否出错
            blocked, reason = check_blocked(sb)
            if blocked:
                log("ERROR", f"⚠️ {reason}")
                # 点击 Got it 关闭错误弹窗
                sb.execute_script('''
                    var buttons = document.querySelectorAll('button');
                    for (var btn of buttons) {
                        if (btn.textContent.includes('Got it') || btn.textContent.includes('Try Again')) {
                            btn.click();
                            break;
                        }
                    }
                ''')
                time.sleep(2)
                if attempt < 2:
                    log("INFO", "   等待后重试...")
                    time.sleep(10)
                    continue
                return False, last_shot
            
            # 检查是否到达 OTP 页面
            otp_page = sb.execute_script('''
                return document.body.innerText.includes('Check Your Inbox') ||
                       document.body.innerText.includes('verification code');
            ''')
            
            if not otp_page:
                log("WARN", "   未进入 OTP 页面")
                if attempt < 2:
                    continue
                return False, last_shot
            
            log("INFO", "✅ 进入 OTP 验证页面")
            
            # 获取邮箱验证码
            log("INFO", "📧 获取邮箱验证码...")
            otp = fetch_otp_from_email(email_addr, imap_pwd, timeout=120)
            
            if not otp:
                log("ERROR", "❌ 获取验证码失败")
                last_shot = shot(idx, "04-otp-failed")
                sb.save_screenshot(last_shot)
                return False, last_shot
            
            # 输入 OTP 到 4 个输入框
            input_otp_to_boxes(sb, otp)
            
            time.sleep(2)
            last_shot = shot(idx, "05-otp-input")
            sb.save_screenshot(last_shot)
            
            # 点击 Verify Code
            log("INFO", "   点击 Verify Code...")
            sb.execute_script('''
                var buttons = document.querySelectorAll('button');
                for (var btn of buttons) {
                    if (btn.textContent.includes('Verify') || btn.textContent.includes('Submit')) {
                        btn.click();
                        return;
                    }
                }
            ''')
            
            time.sleep(5)
            
            last_shot = shot(idx, "06-verify-result")
            sb.save_screenshot(last_shot)
            
            # 检查是否出错
            blocked, reason = check_blocked(sb)
            if blocked:
                log("ERROR", f"⚠️ 验证后出错: {reason}")
                if attempt < 2:
                    # 点击关闭错误弹窗
                    sb.execute_script('''
                        var buttons = document.querySelectorAll('button');
                        for (var btn of buttons) {
                            if (btn.textContent.includes('Got it')) {
                                btn.click();
                                break;
                            }
                        }
                    ''')
                    time.sleep(5)
                    continue
                return False, last_shot
            
            # 验证登录结果
            current_url = sb.get_current_url()
            log("INFO", f"   当前 URL: {current_url}")
            
            if "/session" in current_url or ("/billing.kerit" in current_url and "?" not in current_url):
                log("INFO", "✅ 登录成功!")
                return True, last_shot
            
            # 再等待一下
            time.sleep(3)
            current_url = sb.get_current_url()
            if "/session" in current_url:
                log("INFO", "✅ 登录成功!")
                return True, last_shot
            
            log("WARN", f"   登录未成功，URL: {current_url}")
            
        except Exception as e:
            log("ERROR", f"   尝试 {attempt + 1} 异常: {e}")
            if attempt < 2:
                time.sleep(5)
                continue
    
    log("ERROR", "❌ 登录失败")
    return False, last_shot

# ============== 续订流程 ==============
def get_renewal_info(sb) -> Tuple[int, int]:
    """获取续订信息"""
    try:
        info = sb.execute_script('''
            var count = 0, days = 0;
            
            var countEl = document.getElementById('renewal-count');
            if (countEl) count = parseInt(countEl.textContent) || 0;
            
            var daysEl = document.getElementById('expiry-display');
            if (daysEl) days = parseInt(daysEl.textContent) || 0;
            
            // 备用方法
            if (!count) {
                var text = document.body.innerText;
                var match = text.match(/(\\d+)\\s*\\/\\s*7/);
                if (match) count = parseInt(match[1]);
            }
            
            return {count: count, days: days};
        ''')
        
        return info.get('count', 0), info.get('days', 0)
    except:
        return 0, 0

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
        # ========== 步骤1：访问 Session ==========
        log("INFO", "📋 访问 Session 页面...")
        sb.uc_open_with_reconnect(SESSION_URL, reconnect_time=8)
        time.sleep(5)
        
        result["screenshot"] = shot(idx, "10-session")
        sb.save_screenshot(result["screenshot"])
        
        current_url = sb.get_current_url()
        log("INFO", f"   当前 URL: {current_url}")
        
        # 检查是否被阻止
        blocked, reason = check_blocked(sb)
        if blocked:
            log("ERROR", f"⚠️ {reason}")
            result["message"] = reason
            notify(False, email_masked, reason, result["screenshot"])
            return result
        
        # ========== 步骤2：进入 Free Plans ==========
        log("INFO", "🎁 点击侧边栏 Free Plans...")
        
        sb.execute_script('''
            if (typeof showFreeServers === 'function') {
                showFreeServers();
            } else {
                var items = document.querySelectorAll('.sidebar-item');
                for (var item of items) {
                    if (item.textContent.includes('Free Plans')) {
                        item.click();
                        break;
                    }
                }
            }
        ''')
        
        time.sleep(5)
        current_url = sb.get_current_url()
        log("INFO", f"   当前 URL: {current_url}")
        
        # 如果没跳转，直接访问
        if "/free_panel" not in current_url:
            log("INFO", "   直接访问 /free_panel...")
            sb.uc_open_with_reconnect(FREE_PANEL_URL, reconnect_time=8)
            time.sleep(5)
            current_url = sb.get_current_url()
        
        result["screenshot"] = shot(idx, "11-free-panel")
        sb.save_screenshot(result["screenshot"])
        
        # 检查是否被阻止
        blocked, reason = check_blocked(sb)
        if blocked:
            log("ERROR", f"⚠️ {reason}")
            result["message"] = reason
            notify(False, email_masked, reason, result["screenshot"])
            return result
        
        if "/free_panel" not in current_url:
            log("ERROR", "❌ 无法进入 Free Plans")
            result["message"] = f"无法进入 Free Plans"
            notify(False, email_masked, result["message"], result["screenshot"])
            return result
        
        log("INFO", "✅ 成功进入 Free Plans")
        
        # ========== 步骤3：获取初始状态 ==========
        initial_count, initial_days = get_renewal_info(sb)
        result["initial_count"] = initial_count
        
        log("INFO", f"📊 当前状态: 续订 {initial_count}/7, 剩余 {initial_days} 天")
        
        if initial_count >= 7 or initial_days >= 7:
            log("INFO", "🎉 已达上限，无需续订")
            result["success"] = True
            result["final_count"] = initial_count
            result["final_days"] = initial_days
            result["message"] = f"已达上限 | {initial_count}/7 | {initial_days}天"
            notify(True, email_masked, result["message"], result["screenshot"])
            return result
        
        # ========== 步骤4：循环续订 ==========
        total_renewed = 0
        
        for round_num in range(1, 8):
            log("INFO", f"{'='*15} 第 {round_num} 轮 {'='*15}")
            
            current_count, current_days = get_renewal_info(sb)
            if current_count >= 7 or current_days >= 7:
                log("INFO", "🎉 已达上限")
                break
            
            # 检查按钮是否可用
            btn_disabled = sb.execute_script('''
                var btn = document.getElementById('renewServerBtn');
                return !btn || btn.disabled;
            ''')
            
            if btn_disabled:
                log("INFO", "⏸️ 续订按钮不可用")
                break
            
            # 点击 Renew Server
            log("INFO", "   点击 Renew Server...")
            sb.execute_script('''
                var btn = document.getElementById('renewServerBtn');
                if (btn && !btn.disabled) btn.click();
            ''')
            time.sleep(3)
            
            result["screenshot"] = shot(idx, f"12-modal-{round_num}")
            sb.save_screenshot(result["screenshot"])
            
            # 检查模态框
            modal_visible = sb.execute_script('''
                var modal = document.getElementById('renewalModal');
                return modal && !modal.classList.contains('hidden');
            ''')
            
            if not modal_visible:
                log("WARN", "   模态框未出现，重试...")
                sb.execute_script('''
                    var btn = document.getElementById('renewServerBtn');
                    if (btn) btn.click();
                ''')
                time.sleep(3)
            
            # 处理 Turnstile
            log("INFO", "   处理 Turnstile...")
            try:
                sb.uc_gui_click_captcha()
            except:
                pass
            time.sleep(3)
            
            # 点击广告
            log("INFO", "   🖱️ 点击广告...")
            main_window = sb.driver.current_window_handle
            original_windows = set(sb.driver.window_handles)
            
            sb.execute_script('''
                if (typeof openAdLink === 'function') {
                    openAdLink();
                } else {
                    var ad = document.getElementById('adBanner');
                    if (ad) ad.click();
                }
            ''')
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
            
            time.sleep(2)
            
            # 等待按钮可用
            for _ in range(10):
                btn_ok = sb.execute_script('''
                    var btn = document.getElementById('renewBtn');
                    return btn && !btn.disabled;
                ''')
                if btn_ok:
                    break
                time.sleep(1)
            
            # 点击 Complete Renewal
            log("INFO", "   🔘 点击 Complete Renewal...")
            sb.execute_script('''
                var btn = document.getElementById('renewBtn');
                if (btn && !btn.disabled) btn.click();
            ''')
            time.sleep(4)
            
            result["screenshot"] = shot(idx, f"13-result-{round_num}")
            sb.save_screenshot(result["screenshot"])
            
            # 检查限制
            limit_hit = sb.execute_script('''
                return document.body.innerText.includes('limit') ||
                       document.body.innerText.includes('exceed');
            ''')
            
            if limit_hit:
                log("INFO", "   ⚠️ 达到限制")
                break
            
            total_renewed += 1
            log("INFO", f"   ✅ 第 {round_num} 轮完成")
            
            # 关闭模态框并刷新
            sb.execute_script('''
                if (typeof closeRenewalModal === 'function') closeRenewalModal();
            ''')
            time.sleep(2)
            sb.refresh()
            time.sleep(4)
            
            new_count, new_days = get_renewal_info(sb)
            log("INFO", f"   状态: {new_count}/7, {new_days}天")
            
            if new_days >= 7 or new_count >= 7:
                break
        
        # ========== 步骤5：获取最终状态 ==========
        time.sleep(2)
        final_count, final_days = get_renewal_info(sb)
        result["final_count"] = final_count
        result["final_days"] = final_days
        result["renewed"] = total_renewed
        
        result["screenshot"] = shot(idx, "14-final")
        sb.save_screenshot(result["screenshot"])
        
        log("INFO", f"📊 最终: {final_count}/7, {final_days}天, 本次续订 {total_renewed} 次")
        
        if final_count >= 7 or final_days >= 7 or total_renewed > 0:
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
