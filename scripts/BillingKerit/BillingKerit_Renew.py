#!/usr/bin/env python3
"""Kerit Cloud 自动续订脚本 - 优化版"""

import os, sys, time, platform, requests, re, imaplib, email
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from seleniumbase import SB

# ============== 配置 ==============
BASE_URL = "https://billing.kerit.cloud"
LOGIN_URL = f"{BASE_URL}/"
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
            return d
        except:
            sys.exit(1)
    return None

def shot(idx: int, name: str) -> str:
    return str(OUTPUT_DIR / f"acc{idx}-{cn_now().strftime('%H%M%S')}-{name}.png")

# ============== 通知函数 ==============
def notify(ok: bool, email_full: str, info: str, img: str = None):
    """发送TG通知 - 显示完整邮箱"""
    token = os.environ.get("TG_BOT_TOKEN")
    chat = os.environ.get("TG_CHAT_ID")
    if not token or not chat:
        return
    
    try:
        icon = "✅" if ok else "❌"
        result = "续订成功" if ok else "续订失败"
        
        text = f"""{icon} Kerit Cloud {result}

账号：{email_full}
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
    except:
        pass

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

# ============== 页面处理 ==============
def handle_page_errors(sb) -> bool:
    try:
        body_text = sb.execute_script("return document.body.innerText || ''") or ""
        if "Access Restricted" in body_text:
            return False
        if "Server error" in body_text:
            sb.execute_script('''
                var buttons = document.querySelectorAll('button');
                for (var btn of buttons) {
                    if (['Got it', 'Try Again', 'OK'].includes(btn.textContent.trim())) {
                        btn.click(); break;
                    }
                }
            ''')
            time.sleep(2)
        return True
    except:
        return True

# ============== 邮箱验证码 ==============
def fetch_otp_from_email(email_addr: str, imap_pwd: str, timeout: int = 120) -> Optional[str]:
    server, port = get_imap_server(email_addr)
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            mail = imaplib.IMAP4_SSL(server, port)
            mail.login(email_addr, imap_pwd)
            mail.select("INBOX")
            
            for query in ['(FROM "kerit" UNSEEN)', '(SUBJECT "OTP" UNSEEN)']:
                try:
                    _, messages = mail.search(None, query)
                    if messages[0]:
                        for msg_id in reversed(messages[0].split()[-5:]):
                            _, msg_data = mail.fetch(msg_id, "(RFC822)")
                            msg = email.message_from_bytes(msg_data[0][1])
                            
                            body = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    if part.get_content_type() in ["text/plain", "text/html"]:
                                        body = part.get_payload(decode=True).decode(errors="ignore")
                                        if body: break
                            else:
                                body = msg.get_payload(decode=True).decode(errors="ignore")
                            
                            otp_match = re.search(r'\b(\d{4})\b', body)
                            if otp_match:
                                mail.store(msg_id, '+FLAGS', '\\Seen')
                                mail.logout()
                                return otp_match.group(1)
                except:
                    continue
            
            mail.logout()
        except:
            pass
        
        time.sleep(5)
    
    return None

# ============== 登录流程 ==============
def login(sb, email_addr: str, imap_pwd: str, idx: int) -> Tuple[bool, Optional[str]]:
    email_masked = mask_email(email_addr)
    log("INFO", f"🔐 [{idx}] 登录 {email_masked}")
    
    last_shot = None
    
    for attempt in range(3):
        try:
            sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=10)
            time.sleep(5)
            
            last_shot = shot(idx, "login")
            sb.save_screenshot(last_shot)
            
            if not handle_page_errors(sb):
                continue
            
            current_url = sb.get_current_url()
            if "/session" in current_url or "/free" in current_url:
                log("INFO", f"   ✅ 已登录")
                return True, last_shot
            
            # 等待并输入邮箱
            for _ in range(15):
                if sb.execute_script('return document.querySelector(\'input[type="email"]\') !== null'):
                    break
                time.sleep(1)
            
            sb.execute_script(f'''
                var input = document.querySelector('input[type="email"]');
                if (input) {{
                    input.value = "{email_addr}";
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }}
            ''')
            
            time.sleep(2)
            
            # 处理 Turnstile
            try:
                sb.uc_gui_click_captcha()
            except:
                pass
            
            for _ in range(20):
                if sb.execute_script("return document.body.innerText.includes('Success!')"):
                    break
                time.sleep(1)
            
            # 点击 Continue
            sb.execute_script('''
                var buttons = document.querySelectorAll('button');
                for (var btn of buttons) {
                    if (btn.textContent.includes('Continue with Email')) {
                        btn.click(); return;
                    }
                }
            ''')
            
            time.sleep(5)
            handle_page_errors(sb)
            
            # 检查 OTP 页面
            if not sb.execute_script("return document.body.innerText.includes('Check Your Inbox')"):
                continue
            
            log("INFO", f"   📧 获取验证码...")
            otp = fetch_otp_from_email(email_addr, imap_pwd, timeout=120)
            if not otp:
                log("ERROR", f"   ❌ 验证码超时")
                return False, last_shot
            
            # 输入 OTP
            sb.execute_script(f'''
                (function() {{
                    var otp = "{otp}";
                    var inputs = document.querySelectorAll('input');
                    var otpInputs = [];
                    for (var input of inputs) {{
                        var rect = input.getBoundingClientRect();
                        if (rect.width > 30 && rect.width < 100 && rect.height > 30) {{
                            otpInputs.push(input);
                        }}
                    }}
                    if (otpInputs.length >= 4) {{
                        for (var j = 0; j < 4; j++) {{
                            otpInputs[j].value = otp[j];
                            otpInputs[j].dispatchEvent(new Event('input', {{ bubbles: true }}));
                        }}
                    }}
                }})()
            ''')
            
            time.sleep(2)
            
            # 点击 Verify
            sb.execute_script('''
                var buttons = document.querySelectorAll('button');
                for (var btn of buttons) {
                    if (btn.textContent.includes('Verify')) {
                        btn.click(); return;
                    }
                }
            ''')
            
            time.sleep(5)
            last_shot = shot(idx, "verify")
            sb.save_screenshot(last_shot)
            
            current_url = sb.get_current_url()
            if "/session" in current_url or "/free" in current_url:
                log("INFO", f"   ✅ 登录成功")
                return True, last_shot
            
        except Exception as e:
            log("WARN", f"   尝试 {attempt+1} 失败: {str(e)[:30]}")
            continue
    
    log("ERROR", f"   ❌ 登录失败")
    return False, last_shot

# ============== 续订辅助函数 ==============
def get_renewal_count(sb) -> int:
    try:
        return sb.execute_script("""
            var el = document.getElementById('renewal-count');
            if (el) return parseInt(el.textContent) || 0;
            var bodyText = document.body.innerText;
            var match = bodyText.match(/(\\d+)\\s*\\/\\s*7/);
            if (match) return parseInt(match[1]);
            return 0;
        """) or 0
    except:
        return 0

def get_days_remaining(sb) -> int:
    try:
        return sb.execute_script("""
            var el = document.getElementById('expiry-display');
            if (el) return parseInt(el.textContent) || 0;
            var bodyText = document.body.innerText;
            var match = bodyText.match(/(\\d+)\\s*Days?/i);
            if (match) return parseInt(match[1]);
            return 0;
        """) or 0
    except:
        return 0

def handle_turnstile(sb):
    try:
        for _ in range(10):
            if sb.execute_script("return document.body.innerText.includes('Success!')"):
                return True
            time.sleep(1)
    except:
        pass
    return False

# ============== 续订流程 ==============
def do_renewal(sb, idx: int, email_full: str, email_masked: str) -> Dict[str, Any]:
    result = {
        "success": False,
        "message": "",
        "screenshot": None,
        "renewed": 0
    }
    
    try:
        sb.uc_open_with_reconnect(FREE_PANEL_URL, reconnect_time=8)
        time.sleep(5)
        
        result["screenshot"] = shot(idx, "panel")
        sb.save_screenshot(result["screenshot"])
        
        initial_count = get_renewal_count(sb)
        initial_days = get_days_remaining(sb)
        
        log("INFO", f"   📊 状态: {initial_count}/7, {initial_days}天")
        
        # 检查上限
        if initial_count >= 7 or initial_days >= 7:
            result["success"] = True
            result["message"] = f"🎉 已达上限 | {initial_count}/7 | {initial_days}天"
            log("INFO", f"   {result['message']}")
            return result
        
        # 检查按钮
        btn_disabled = sb.execute_script("""
            var btn = document.getElementById('renewServerBtn');
            return !btn || btn.disabled;
        """)
        
        if btn_disabled:
            result["success"] = True
            result["message"] = f"⏭️ 未到续订时间 | {initial_count}/7 | {initial_days}天"
            log("INFO", f"   {result['message']}")
            return result
        
        # 循环续订
        total_renewed = 0
        
        for round_num in range(1, 8):
            current_count = get_renewal_count(sb)
            current_days = get_days_remaining(sb)
            
            if current_count >= 7 or current_days >= 7:
                break
            
            if sb.execute_script("var btn = document.getElementById('renewServerBtn'); return !btn || btn.disabled"):
                break
            
            # 点击 Renew Server
            sb.execute_script("var btn = document.getElementById('renewServerBtn'); if (btn) btn.click();")
            time.sleep(3)
            
            # 处理 Turnstile
            try:
                sb.uc_gui_click_captcha()
                time.sleep(2)
            except:
                pass
            handle_turnstile(sb)
            
            # 点击广告
            main_window = sb.driver.current_window_handle
            original_windows = set(sb.driver.window_handles)
            
            sb.execute_script("""
                var ad = document.getElementById('adBanner');
                if (ad) {
                    var parent = ad.closest('[onclick]') || ad.parentElement;
                    if (parent) parent.click(); else ad.click();
                }
            """)
            
            time.sleep(3)
            
            # 关闭广告窗口
            new_windows = set(sb.driver.window_handles) - original_windows
            for win in new_windows:
                try:
                    sb.driver.switch_to.window(win)
                    sb.driver.close()
                except:
                    pass
            sb.driver.switch_to.window(main_window)
            
            time.sleep(1)
            
            # 等待并点击 renewBtn
            for _ in range(10):
                if sb.execute_script("var btn = document.getElementById('renewBtn'); return btn && !btn.disabled"):
                    break
                time.sleep(1)
            
            sb.execute_script("var btn = document.getElementById('renewBtn'); if (btn && !btn.disabled) btn.click();")
            time.sleep(3)
            
            result["screenshot"] = shot(idx, f"renew-{round_num}")
            sb.save_screenshot(result["screenshot"])
            
            # 检查限制
            if sb.execute_script("return document.body.innerText.includes('Cannot exceed') || document.body.innerText.includes('limit')"):
                break
            
            total_renewed += 1
            log("INFO", f"   ✅ 第 {round_num} 轮完成")
            
            # 关闭模态框并刷新
            sb.execute_script("""
                var close = document.querySelector('#renewalModal .close, .btn-close');
                if (close) close.click();
                var modal = document.getElementById('renewalModal');
                if (modal) modal.style.display = 'none';
            """)
            
            time.sleep(2)
            sb.refresh()
            time.sleep(3)
        
        # 最终状态
        final_count = get_renewal_count(sb)
        final_days = get_days_remaining(sb)
        
        result["screenshot"] = shot(idx, "final")
        sb.save_screenshot(result["screenshot"])
        result["renewed"] = total_renewed
        
        if total_renewed > 0:
            result["success"] = True
            result["message"] = f"✅ 续订{total_renewed}次 | {final_count}/7 | {final_days}天"
        elif final_count >= 7 or final_days >= 7:
            result["success"] = True
            result["message"] = f"🎉 已达上限 | {final_count}/7 | {final_days}天"
        else:
            result["message"] = f"❌ 未能续订 | {final_count}/7 | {final_days}天"
        
        log("INFO", f"   {result['message']}")
        
    except Exception as e:
        result["message"] = f"异常: {str(e)[:30]}"
        log("ERROR", f"   {result['message']}")
    
    return result

# ============== 主流程 ==============
def process(sb, account: Dict, idx: int) -> Dict[str, Any]:
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
    
    try:
        sb.delete_all_cookies()
    except:
        pass
    
    # 登录
    login_ok, login_shot = login(sb, email_addr, imap_pwd, idx)
    result["screenshot"] = login_shot
    
    if not login_ok:
        result["message"] = "登录失败"
        notify(False, email_addr, "⚠️ 登录失败", login_shot)  # TG用完整邮箱
        return result
    
    # 续订
    renewal = do_renewal(sb, idx, email_addr, email_masked)
    result["success"] = renewal["success"]
    result["message"] = renewal["message"]
    result["screenshot"] = renewal["screenshot"]
    
    # 发送通知 - 使用完整邮箱
    notify(renewal["success"], email_addr, renewal["message"], renewal["screenshot"])
    
    return result

def main():
    log("INFO", "🚀 Kerit Cloud 自动续订")
    
    acc_str = os.environ.get("BILLING_KERIT_MAIL", "")
    if not acc_str:
        log("ERROR", "缺少 BILLING_KERIT_MAIL")
        sys.exit(1)
    
    accounts = parse_accounts(acc_str)
    if not accounts:
        log("ERROR", "无有效账号")
        sys.exit(1)
    
    log("INFO", f"📋 账号: {len(accounts)} 个")
    
    proxy = os.environ.get("PROXY_SOCKS5") or os.environ.get("PROXY_HTTP", "")
    
    display = setup_display()
    results = []
    
    try:
        opts = {"uc": True, "test": True, "locale_code": "en", "headless": False}
        if proxy:
            opts["proxy"] = proxy.replace("socks5://", "socks5h://")
        
        with SB(**opts) as sb:
            for acc in accounts:
                try:
                    r = process(sb, acc, acc["index"])
                    results.append(r)
                    time.sleep(3)
                except Exception as e:
                    log("ERROR", f"[{acc['index']}] {mask_email(acc['email'])}: {str(e)[:30]}")
                    results.append({
                        "email_masked": mask_email(acc["email"]),
                        "success": False,
                        "message": str(e)[:30]
                    })
                    notify(False, acc["email"], f"⚠️ {str(e)[:30]}", None)
    
    except Exception as e:
        log("ERROR", f"脚本异常: {e}")
        sys.exit(1)
    
    finally:
        if display:
            display.stop()
    
    # 汇总
    ok = sum(1 for r in results if r.get("success"))
    log("INFO", f"📊 结果: {ok}/{len(results)} 成功")
    for r in results:
        icon = "✅" if r.get("success") else "❌"
        log("INFO", f"   {icon} {r.get('email_masked')}: {r.get('message')}")
    
    sys.exit(0 if ok > 0 else 1)

if __name__ == "__main__":
    main()
