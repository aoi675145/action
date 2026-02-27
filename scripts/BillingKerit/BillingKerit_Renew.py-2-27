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
    return s[:show] + "***" if len(s) > show else s[0] + "***"

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
        except Exception as e:
            log("ERROR", f"虚拟显示失败: {e}")
            sys.exit(1)
    return None

def shot(idx: int, name: str) -> str:
    return str(OUTPUT_DIR / f"acc{idx}-{cn_now().strftime('%H%M%S')}-{name}.png")

# ============== 通知函数（优化）==============
def notify(ok: bool, email_full: str, info: str, img: str = None):
    """发送TG通知 - 完整显示邮箱"""
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
时间：{cn_time_str()}

Billing Kerit Auto Renewal"""
        
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

# ============== 邮箱验证码 ==============
def fetch_otp(email_addr: str, imap_pwd: str, timeout: int = 120) -> Optional[str]:
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
        except Exception as e:
            pass
        
        elapsed = int(time.time() - start_time)
        log("INFO", f"   等待验证码... ({elapsed}s)")
        time.sleep(5)
    
    return None

# ============== 登录流程（修复首次失败）==============
def login(sb, email_addr: str, imap_pwd: str, idx: int) -> Tuple[bool, Optional[str]]:
    log("INFO", f"🔐 登录账号: {email_addr}")
    
    last_shot = None
    
    for attempt in range(3):
        try:
            log("INFO", f"   尝试 {attempt + 1}/3")
            sb.uc_open_with_reconnect(LOGIN_URL, reconnect_time=10)
            time.sleep(5)
            
            # 检查是否已登录
            if "/session" in sb.get_current_url() or "/free" in sb.get_current_url():
                log("INFO", "   ✅ 已登录")
                return True, shot(idx, "logged")
            
            # 等待登录表单（增加等待时间）
            for _ in range(20):
                if sb.execute_script('return document.querySelector(\'input[type="email"]\') !== null'):
                    break
                time.sleep(1)
            
            # 输入邮箱
            sb.execute_script(f'''
                var input = document.querySelector('input[type="email"], input[placeholder*="email"]');
                if (input) {{
                    input.value = "{email_addr}";
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }}
            ''')
            time.sleep(2)
            
            # 处理 Turnstile（增加等待时间）
            log("INFO", "   处理 Turnstile...")
            try:
                sb.uc_gui_click_captcha()
            except:
                pass
            
            # 等待 Turnstile 完成（增加到30秒）
            turnstile_ok = False
            for _ in range(30):
                if sb.execute_script("return document.body.innerText.includes('Success!')"):
                    turnstile_ok = True
                    log("INFO", "   ✅ Turnstile 通过")
                    break
                time.sleep(1)
            
            if not turnstile_ok:
                log("WARN", "   Turnstile 未通过，重试...")
                continue
            
            # 点击 Continue（确保按钮可点击）
            time.sleep(2)
            sb.execute_script('''
                var buttons = document.querySelectorAll('button');
                for (var btn of buttons) {
                    if (btn.textContent.includes('Continue with Email') && !btn.disabled) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            ''')
            
            # 等待页面响应（增加到10秒）
            time.sleep(10)
            
            last_shot = shot(idx, f"after-continue-{attempt}")
            sb.save_screenshot(last_shot)
            
            # 多次检查 OTP 页面
            otp_page = False
            for _ in range(5):
                if sb.execute_script("return document.body.innerText.includes('Check Your Inbox')"):
                    otp_page = True
                    break
                # 也检查是否直接登录成功
                if "/session" in sb.get_current_url():
                    log("INFO", "   ✅ 直接登录成功")
                    return True, last_shot
                time.sleep(2)
            
            if not otp_page:
                log("WARN", "   未进入 OTP 页面，重试...")
                continue
            
            log("INFO", "   📧 获取验证码...")
            otp = fetch_otp(email_addr, imap_pwd, timeout=120)
            if not otp:
                log("ERROR", "   ❌ 获取验证码超时")
                return False, last_shot
            
            log("INFO", f"   ✅ 获取到验证码")
            
            # 输入 OTP
            sb.execute_script(f'''
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
            ''')
            time.sleep(2)
            
            # 点击 Verify
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
            
            # 检查登录结果
            if "/session" in sb.get_current_url() or "/free" in sb.get_current_url():
                log("INFO", "   ✅ 登录成功")
                last_shot = shot(idx, "login-ok")
                sb.save_screenshot(last_shot)
                return True, last_shot
            
            # 再等待一下
            time.sleep(3)
            if "/session" in sb.get_current_url():
                log("INFO", "   ✅ 登录成功")
                return True, last_shot
            
        except Exception as e:
            log("ERROR", f"   异常: {e}")
            continue
    
    log("ERROR", "   ❌ 登录失败")
    return False, last_shot

# ============== 续订辅助函数 ==============
def get_renewal_count(sb) -> int:
    try:
        return sb.execute_script("""
            var el = document.getElementById('renewal-count');
            if (el) return parseInt(el.textContent) || 0;
            var match = document.body.innerText.match(/(\\d+)\\s*\\/\\s*7/);
            return match ? parseInt(match[1]) : 0;
        """) or 0
    except:
        return 0

def get_days_remaining(sb) -> int:
    try:
        return sb.execute_script("""
            var el = document.getElementById('expiry-display');
            if (el) return parseInt(el.textContent) || 0;
            var match = document.body.innerText.match(/(\\d+)\\s*Days?/i);
            return match ? parseInt(match[1]) : 0;
        """) or 0
    except:
        return 0

# ============== 续订流程 ==============
def do_renewal(sb, idx: int, email_full: str) -> Dict[str, Any]:
    result = {
        "success": False,
        "message": "",
        "screenshot": None,
        "renewed": 0
    }
    
    try:
        # 进入 Free Panel
        log("INFO", "📋 进入续订页面...")
        sb.uc_open_with_reconnect(FREE_PANEL_URL, reconnect_time=8)
        time.sleep(5)
        
        result["screenshot"] = shot(idx, "panel")
        sb.save_screenshot(result["screenshot"])
        
        # 获取状态
        count = get_renewal_count(sb)
        days = get_days_remaining(sb)
        
        log("INFO", f"   状态: {count}/7, {days}天")
        
        # 检查上限
        if count >= 7 or days >= 7:
            result["success"] = True
            result["message"] = f"🎉 已达上限 | {count}/7 | {days}天"
            log("INFO", f"   {result['message']}")
            return result
        
        # 检查按钮
        btn_disabled = sb.execute_script("""
            var btn = document.getElementById('renewServerBtn');
            return !btn || btn.disabled;
        """)
        
        if btn_disabled:
            result["success"] = True
            result["message"] = f"⏭️ 未到续订时间 | {count}/7 | {days}天"
            log("INFO", f"   {result['message']}")
            return result
        
        # 循环续订
        log("INFO", "✨ 开始续订...")
        total_renewed = 0
        
        for round_num in range(1, 8):
            current_count = get_renewal_count(sb)
            current_days = get_days_remaining(sb)
            
            if current_count >= 7 or current_days >= 7:
                log("INFO", f"   🎉 达到上限: {current_count}/7, {current_days}天")
                break
            
            # 检查按钮
            if sb.execute_script("var b=document.getElementById('renewServerBtn');return !b||b.disabled"):
                break
            
            # 点击 Renew Server
            sb.execute_script("var b=document.getElementById('renewServerBtn');if(b&&!b.disabled)b.click()")
            time.sleep(3)
            
            # 处理 Turnstile
            try:
                sb.uc_gui_click_captcha()
                time.sleep(2)
            except:
                pass
            
            for _ in range(15):
                if sb.execute_script("return document.body.innerText.includes('Success!')"):
                    break
                time.sleep(1)
            
            # 点击广告
            main_window = sb.driver.current_window_handle
            original_windows = set(sb.driver.window_handles)
            
            sb.execute_script("""
                var ad = document.getElementById('adBanner');
                if (ad) {
                    var p = ad.closest('[onclick]') || ad.parentElement;
                    if (p) p.click(); else ad.click();
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
                if sb.execute_script("var b=document.getElementById('renewBtn');return b&&!b.disabled"):
                    break
                time.sleep(1)
            
            sb.execute_script("var b=document.getElementById('renewBtn');if(b&&!b.disabled)b.click()")
            time.sleep(3)
            
            result["screenshot"] = shot(idx, f"round-{round_num}")
            sb.save_screenshot(result["screenshot"])
            
            # 检查限制
            if sb.execute_script("return document.body.innerText.includes('Cannot exceed')"):
                log("INFO", f"   达到续订限制")
                break
            
            total_renewed += 1
            log("INFO", f"   ✅ 第 {round_num} 轮完成")
            
            # 关闭模态框
            sb.execute_script("""
                var c=document.querySelector('#renewalModal .close,[data-dismiss="modal"]');
                if(c)c.click();
                var m=document.getElementById('renewalModal');if(m)m.style.display='none';
                var b=document.querySelector('.modal-backdrop');if(b)b.remove();
                document.body.classList.remove('modal-open');
            """)
            time.sleep(2)
            
            sb.refresh()
            time.sleep(3)
        
        # 最终状态
        final_count = get_renewal_count(sb)
        final_days = get_days_remaining(sb)
        result["renewed"] = total_renewed
        
        result["screenshot"] = shot(idx, "final")
        sb.save_screenshot(result["screenshot"])
        
        log("INFO", f"📊 结果: {total_renewed}次续订 | {final_count}/7 | {final_days}天")
        
        if total_renewed > 0:
            result["success"] = True
            result["message"] = f"✅ 续订{total_renewed}次 | {final_count}/7 | {final_days}天"
        elif final_count >= 7 or final_days >= 7:
            result["success"] = True
            result["message"] = f"🎉 已达上限 | {final_count}/7 | {final_days}天"
        else:
            result["message"] = f"❌ 未能续订 | {final_count}/7 | {final_days}天"
        
    except Exception as e:
        log("ERROR", f"续订异常: {e}")
        result["message"] = f"异常: {str(e)[:50]}"
    
    return result

# ============== 主流程 ==============
def process(sb, account: Dict, idx: int) -> Dict[str, Any]:
    email_addr = account["email"]
    imap_pwd = account["imap_password"]
    
    result = {
        "email": email_addr,
        "success": False,
        "message": "",
        "screenshot": None
    }
    
    try:
        sb.delete_all_cookies()
    except:
        pass
    
    login_ok, login_shot = login(sb, email_addr, imap_pwd, idx)
    result["screenshot"] = login_shot
    
    if not login_ok:
        result["message"] = "登录失败"
        notify(False, email_addr, "⚠️ 登录失败", login_shot)
        return result
    
    renewal = do_renewal(sb, idx, email_addr)
    result["success"] = renewal["success"]
    result["message"] = renewal["message"]
    result["screenshot"] = renewal["screenshot"]
    
    notify(renewal["success"], email_addr, renewal["message"], renewal["screenshot"])
    
    return result

def main():
    log("INFO", "🚀 Kerit Cloud 自动续订")
    
    acc_str = os.environ.get("BILLING_KERIT_MAIL", "")
    if not acc_str:
        log("ERROR", "缺少 BILLING_KERIT_MAIL")
        notify(False, "系统", "⚠️ 缺少账号配置", None)
        sys.exit(1)
    
    accounts = parse_accounts(acc_str)
    if not accounts:
        log("ERROR", "无有效账号")
        sys.exit(1)
    
    log("INFO", f"📋 {len(accounts)} 个账号")
    
    proxy = os.environ.get("PROXY_SOCKS5") or os.environ.get("PROXY_HTTP", "")
    if proxy:
        log("INFO", f"🌐 代理: {mask(proxy, 10)}")
    
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
                    time.sleep(5)
                except Exception as e:
                    log("ERROR", f"账号异常: {e}")
                    results.append({"email": acc["email"], "success": False, "message": str(e)})
                    notify(False, acc["email"], f"⚠️ {e}", None)
    
    except Exception as e:
        log("ERROR", f"脚本异常: {e}")
        sys.exit(1)
    
    finally:
        if display:
            display.stop()
    
    # 汇总
    ok = sum(1 for r in results if r.get("success"))
    log("INFO", f"📊 汇总: {ok}/{len(results)} 成功")
    for r in results:
        icon = "✅" if r.get("success") else "❌"
        log("INFO", f"   {icon} {r.get('email')}: {r.get('message')}")
    
    sys.exit(0 if ok > 0 else 1)

if __name__ == "__main__":
    main()
