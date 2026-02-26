# scripts/PellaFree/PellaFree_Renew.py
#!/usr/bin/env python3
"""
Pella 自动续期脚本（带截图通知版）

配置变量:
- PELLA_ACCOUNTS: 格式 邮箱1:密码1,邮箱2:密码2,邮箱3:密码3
- TG_BOT_TOKEN: Telegram 机器人 Token（可选）
- TG_CHAT_ID: Telegram 聊天 ID（可选）
- ACCOUNT_NAME: 指定账号执行（可选）
"""

import os
import sys
import time
import logging
import re
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, WebDriverException

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 截图目录
OUTPUT_DIR = Path("output/screenshots")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 时区
CN_TZ = timezone(timedelta(hours=8))


def cn_now():
    return datetime.now(CN_TZ)


def cn_time_str(fmt="%Y-%m-%d %H:%M:%S"):
    return cn_now().strftime(fmt)


def mask_email(email):
    """隐藏邮箱地址"""
    if not email or '@' not in email:
        return '***'
    name, domain = email.split('@', 1)
    if len(name) <= 2:
        masked = '*' * len(name)
    else:
        masked = name[0] + '*' * (len(name) - 2) + name[-1]
    return f"{masked}@{domain}"


def get_username_from_email(email):
    """从邮箱提取用户名"""
    if '@' in email:
        return email.split('@')[0]
    return email


def shot_path(idx, name):
    """生成截图路径"""
    return str(OUTPUT_DIR / f"acc{idx}-{cn_now().strftime('%H%M%S')}-{name}.png")


class PellaAutoRenew:
    LOGIN_URL = "https://www.pella.app/login"
    HOME_URL = "https://www.pella.app/home"
    RENEW_WAIT_TIME = 8
    WAIT_TIME_AFTER_LOGIN = 20
    RESTART_WAIT_TIME = 60

    def __init__(self, email, password, idx=1):
        self.email = email
        self.password = password
        self.idx = idx
        self.initial_expiry_details = "N/A"
        self.initial_expiry_value = -1.0
        self.server_url = None
        self.server_status = "unknown"
        self.last_screenshot = None
        
        if not self.email or not self.password:
            raise ValueError("邮箱和密码不能为空")
        
        self.driver = None
        self.setup_driver()
    
    def setup_driver(self):
        chrome_options = Options()
        
        if os.getenv('GITHUB_ACTIONS'):
            chrome_options.add_argument('--headless=new')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
        
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        except WebDriverException as e:
            logger.error(f"❌ 驱动初始化失败: {e}")
            raise

    def take_screenshot(self, name):
        """截图并返回路径"""
        try:
            path = shot_path(self.idx, name)
            self.driver.save_screenshot(path)
            self.last_screenshot = path
            return path
        except Exception as e:
            logger.warning(f"截图失败: {e}")
            return None

    def wait_for_element_clickable(self, by, value, timeout=10):
        return WebDriverWait(self.driver, timeout).until(
            EC.element_to_be_clickable((by, value))
        )
    
    def wait_for_element_present(self, by, value, timeout=10):
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )

    def extract_expiry_days(self, page_source):
        match = re.search(r"Your server expires in\s*(\d+)D\s*(\d+)H\s*(\d+)M", page_source)
        if match:
            d, h, m = int(match.group(1)), int(match.group(2)), int(match.group(3))
            return f"{d}天{h}时{m}分", d + h/24 + m/1440
            
        match = re.search(r"Your server expires in\s*(\d+)D", page_source)
        if match:
            d = int(match.group(1))
            return f"{d}天", float(d)
            
        return "无法提取", -1.0

    def find_and_click_button(self):
        selectors = [
            "button.cl-formButtonPrimary",
            "button[data-localization-key='formButtonPrimary']",
            "//button[.//span[contains(text(), 'Continue')]]",
            "//button[contains(@class, 'cl-formButtonPrimary')]",
            "button[type='submit']",
            "form button"
        ]
        
        for selector in selectors:
            try:
                if selector.startswith("//"):
                    btn = WebDriverWait(self.driver, 3).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                else:
                    btn = WebDriverWait(self.driver, 3).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                
                self.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                time.sleep(0.3)
                self.driver.execute_script("arguments[0].click();", btn)
                return True
            except:
                continue
        return False

    def wait_for_password_field(self, timeout=15):
        selectors = [
            "input[type='password']",
            "input[name='password']",
            "input.cl-formFieldInput[type='password']",
            "#password",
        ]
        
        start = time.time()
        while time.time() - start < timeout:
            for sel in selectors:
                try:
                    elem = self.driver.find_element(By.CSS_SELECTOR, sel)
                    if elem.is_displayed():
                        return elem
                except:
                    pass
            time.sleep(0.5)
        return None

    def check_for_error(self):
        selectors = [
            ".cl-formFieldErrorText",
            "[data-localization-key*='error']",
            ".error-message",
        ]
        for sel in selectors:
            try:
                err = self.driver.find_element(By.CSS_SELECTOR, sel)
                if err.is_displayed():
                    return err.text
            except:
                pass
        return None

    def login(self):
        logger.info(f"开始登录: {mask_email(self.email)}")
        self.driver.get(self.LOGIN_URL)
        time.sleep(4)
        
        self.take_screenshot("01-login-page")
        
        def js_set_value(element, value):
            element.clear()
            element.click()
            time.sleep(0.2)
            element.send_keys(value)
            time.sleep(0.2)
            self.driver.execute_script("""
                arguments[0].value = arguments[1];
                arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
            """, element, value)
        
        try:
            email_input = self.wait_for_element_present(By.CSS_SELECTOR, "input[name='identifier']", 15)
            js_set_value(email_input, self.email)
            if email_input.get_attribute('value') != self.email:
                email_input.clear()
                email_input.send_keys(self.email)
            logger.info("✅ 邮箱输入完成")
        except Exception as e:
            self.take_screenshot("error-email")
            raise Exception(f"❌ 输入邮箱失败: {e}")
            
        try:
            time.sleep(1)
            if not self.find_and_click_button():
                self.take_screenshot("error-continue")
                raise Exception("❌ 无法点击Continue按钮")
            
            password_input = self.wait_for_password_field(timeout=15)
            if not password_input:
                error = self.check_for_error()
                if error:
                    self.take_screenshot("error-login")
                    raise Exception(f"❌ 登录错误: {error}")
                self.take_screenshot("error-password-field")
                raise Exception("❌ 密码框未出现")
            
            logger.info("✅ 进入密码步骤")
            time.sleep(1)
        except Exception as e:
            self.take_screenshot("error-step1")
            raise Exception(f"❌ 第一步失败: {e}")

        try:
            password_input = self.wait_for_element_present(By.CSS_SELECTOR, "input[type='password']", 10)
            js_set_value(password_input, self.password)
            logger.info("✅ 密码输入完成")
        except Exception as e:
            self.take_screenshot("error-password")
            raise Exception(f"❌ 输入密码失败: {e}")

        try:
            time.sleep(2)
            if not self.find_and_click_button():
                self.take_screenshot("error-submit")
                raise Exception("❌ 无法点击登录按钮")
        except Exception as e:
            raise Exception(f"❌ 点击登录失败: {e}")

        try:
            for _ in range(self.WAIT_TIME_AFTER_LOGIN // 2):
                time.sleep(2)
                url = self.driver.current_url
                
                if '/home' in url or '/dashboard' in url:
                    logger.info("✅ 登录成功")
                    self.take_screenshot("02-logged-in")
                    return True
                
                error = self.check_for_error()
                if error:
                    self.take_screenshot("error-auth")
                    raise Exception(f"❌ 登录失败: {error}")
                
                if '/login' not in url and '/sign-in' not in url:
                    self.driver.get(self.HOME_URL)
                    time.sleep(2)
                    if '/home' in self.driver.current_url:
                        logger.info("✅ 登录成功")
                        self.take_screenshot("02-logged-in")
                        return True
            
            self.driver.get(self.HOME_URL)
            time.sleep(3)
            if '/home' in self.driver.current_url:
                logger.info("✅ 登录成功")
                self.take_screenshot("02-logged-in")
                return True
            
            self.take_screenshot("error-timeout")
            raise Exception("❌ 登录超时")
        except Exception as e:
            raise Exception(f"❌ 登录验证失败: {e}")

    def get_server_url(self):
        if '/home' not in self.driver.current_url:
            self.driver.get(self.HOME_URL)
            time.sleep(3)
            
        try:
            link = self.wait_for_element_clickable(By.CSS_SELECTOR, "a[href*='/server/']", 15)
            link.click()
            WebDriverWait(self.driver, 10).until(EC.url_contains("/server/"))
            self.server_url = self.driver.current_url
            logger.info(f"✅ 获取服务器URL成功")
            self.take_screenshot("03-server-page")
            return True
        except Exception as e:
            self.take_screenshot("error-server")
            raise Exception(f"❌ 获取服务器失败: {e}")
    
    def check_server_status(self):
        """检查服务器当前状态"""
        if not self.server_url:
            return "unknown"
        
        if '/server/' not in self.driver.current_url:
            self.driver.get(self.server_url)
            time.sleep(3)
        
        page_text = self.driver.find_element(By.TAG_NAME, "body").text.upper()
        
        running_indicators = ["STATUS: RUNNING", "RUNNING", "ONLINE", "ACTIVE"]
        stopped_indicators = ["STATUS: STOPPED", "STOPPED", "OFFLINE", "INACTIVE", "NOT RUNNING"]
        
        try:
            status_elements = self.driver.find_elements(By.XPATH, 
                "//*[contains(text(), 'Status') or contains(text(), 'status')]")
            
            for elem in status_elements:
                try:
                    parent = elem.find_element(By.XPATH, "./..")
                    parent_text = parent.text.upper()
                    
                    for indicator in running_indicators:
                        if indicator in parent_text:
                            self.server_status = "running"
                            return "running"
                    
                    for indicator in stopped_indicators:
                        if indicator in parent_text:
                            self.server_status = "stopped"
                            return "stopped"
                except:
                    continue
        except:
            pass
        
        try:
            start_buttons = self.driver.find_elements(By.XPATH, 
                "//button[contains(text(), 'START') and not(contains(text(), 'RESTART'))]")
            
            for btn in start_buttons:
                if btn.is_displayed() and btn.is_enabled():
                    btn_text = btn.text.upper().strip()
                    if btn_text == "START" or btn_text == "START SERVER":
                        self.server_status = "stopped"
                        return "stopped"
        except:
            pass
        
        for indicator in running_indicators:
            if indicator in page_text:
                self.server_status = "running"
                return "running"
        
        for indicator in stopped_indicators:
            if indicator in page_text:
                self.server_status = "stopped"
                return "stopped"
        
        self.server_status = "unknown"
        return "unknown"
    
    def renew_server(self):
        if not self.server_url:
            raise Exception("❌ 缺少服务器URL")
            
        self.driver.get(self.server_url)
        time.sleep(5)

        self.initial_expiry_details, self.initial_expiry_value = self.extract_expiry_days(self.driver.page_source)
        logger.info(f"📅 当前过期: {self.initial_expiry_details}")

        if self.initial_expiry_value == -1.0:
            self.take_screenshot("error-expiry")
            raise Exception("❌ 无法提取过期时间")

        try:
            selector = "a[href*='/renew/']:not(.opacity-50):not(.pointer-events-none)"
            count = 0
            original = self.driver.current_window_handle
            
            while True:
                buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if not buttons:
                    break

                url = buttons[0].get_attribute('href')
                logger.info(f"续期 #{count + 1}")
                
                self.driver.execute_script("window.open(arguments[0]);", url)
                time.sleep(1)
                self.driver.switch_to.window(self.driver.window_handles[-1])
                time.sleep(self.RENEW_WAIT_TIME)
                self.driver.close()
                self.driver.switch_to.window(original)
                count += 1
                
                self.driver.get(self.server_url)
                time.sleep(3)

            if count == 0:
                disabled = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/renew/'].opacity-50")
                self.take_screenshot("04-already-renewed")
                return "today_renewed" if disabled else "no_button"

            self.driver.get(self.server_url)
            time.sleep(5)
            
            final, final_val = self.extract_expiry_days(self.driver.page_source)
            logger.info(f"📅 续期后: {final}")
            
            self.take_screenshot("04-renewed")
            
            if final_val > self.initial_expiry_value:
                return f"success:{self.initial_expiry_details}->{final}"
            return f"unchanged:{final}"

        except Exception as e:
            self.take_screenshot("error-renew")
            raise Exception(f"❌ 续期错误: {e}")

    def restart_server(self):
        """重启服务器（仅在停止时）"""
        if not self.server_url:
            return "skip", "缺少服务器URL"
        
        status = self.check_server_status()
        
        if status == "running":
            logger.info("✅ 服务器正在运行，无需重启")
            return "running", "运行中(无需重启)"
        
        if status == "unknown":
            return "unknown", "无法确定状态"
        
        logger.info("🔄 服务器已停止，开始重启...")
        
        if '/server/' not in self.driver.current_url:
            self.driver.get(self.server_url)
            time.sleep(3)
        
        try:
            restart_btn = None
            selectors = [
                "//button[contains(text(), 'RESTART')]",
                "//button[.//text()[contains(., 'RESTART')]]",
            ]
            
            for sel in selectors:
                try:
                    restart_btn = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, sel))
                    )
                    if restart_btn:
                        break
                except:
                    continue
            
            if not restart_btn:
                buttons = self.driver.find_elements(By.TAG_NAME, "button")
                for btn in buttons:
                    try:
                        if 'RESTART' in btn.text.upper():
                            restart_btn = btn
                            break
                    except:
                        continue
            
            if not restart_btn:
                return "no_button", "未找到RESTART按钮"
            
            self.driver.execute_script("arguments[0].scrollIntoView(true);", restart_btn)
            time.sleep(0.5)
            self.driver.execute_script("arguments[0].click();", restart_btn)
            logger.info("✅ 已点击 RESTART 按钮")
            
            # 等待重启完成
            time.sleep(self.RESTART_WAIT_TIME)
            self.take_screenshot("05-restarted")
            
            return "restarted", "重启完成"
                
        except Exception as e:
            logger.error(f"❌ 重启失败: {e}")
            self.take_screenshot("error-restart")
            return "error", f"重启失败: {e}"
            
    def run(self):
        try:
            logger.info(f"处理账号: {mask_email(self.email)}")
            
            if self.login() and self.get_server_url():
                renew_result = self.renew_server()
                logger.info(f"续期结果: {renew_result}")
                
                restart_status, restart_msg = self.restart_server()
                
                return True, renew_result, restart_status, restart_msg, self.last_screenshot
                
            return False, "login_failed", "skip", "登录失败", self.last_screenshot
                
        except Exception as e:
            logger.error(f"❌ 失败: {e}")
            return False, f"error:{e}", "skip", "异常", self.last_screenshot
        finally:
            if self.driver:
                self.driver.quit()


class MultiAccountManager:
    def __init__(self):
        self.tg_token = os.getenv('TG_BOT_TOKEN', '')
        self.tg_chat = os.getenv('TG_CHAT_ID', '')
        self.accounts = self.load_accounts()
        self.target_account = os.getenv('ACCOUNT_NAME', '').strip()
    
    def load_accounts(self):
        accounts = []
        
        accounts_str = os.getenv('PELLA_ACCOUNTS', '').strip()
        if not accounts_str:
            raise ValueError("❌ 未找到 PELLA_ACCOUNTS 配置")
        
        for pair in [p.strip() for p in re.split(r'[;,]', accounts_str) if p.strip()]:
            if ':' in pair:
                email, pwd = pair.split(':', 1)
                if email.strip() and pwd.strip():
                    accounts.append({'email': email.strip(), 'password': pwd.strip()})
        
        if not accounts:
            raise ValueError("❌ PELLA_ACCOUNTS 格式错误，正确格式: 邮箱1:密码1,邮箱2:密码2")
        
        logger.info(f"加载 {len(accounts)} 个账号")
        return accounts
    
    def filter_accounts(self, accounts):
        """根据指定账号过滤"""
        if not self.target_account:
            return accounts
        
        target = self.target_account.lower()
        filtered = []
        
        for acc in accounts:
            email_lower = acc['email'].lower()
            username = get_username_from_email(email_lower)
            
            if email_lower == target or username == target:
                filtered.append(acc)
        
        return filtered
    
    def format_renew_result(self, renew_result):
        """格式化续期结果"""
        if renew_result.startswith("success:"):
            change = renew_result.replace("success:", "")
            return f"续期成功 {change}"
        elif renew_result == "today_renewed":
            return "今日已续期"
        elif renew_result == "no_button":
            return "未找到续期按钮"
        elif renew_result.startswith("unchanged:"):
            return f"天数未变化 ({renew_result.replace('unchanged:', '')})"
        elif renew_result.startswith("error:"):
            return renew_result.replace("error:", "失败: ")
        elif renew_result == "login_failed":
            return "登录失败"
        else:
            return renew_result
    
    def format_restart_result(self, restart_status, restart_msg):
        """格式化重启结果"""
        if restart_status == "running":
            return "运行中(无需重启)"
        elif restart_status == "restarted":
            return "重启完成"
        elif restart_status == "skip":
            return f"跳过({restart_msg})"
        elif restart_status == "unknown":
            return "无法确定状态"
        elif restart_status == "no_button":
            return "未找到重启按钮"
        elif restart_status == "error":
            return restart_msg
        else:
            return restart_msg
    
    def get_status_icon(self, renew_result):
        """获取状态图标"""
        if renew_result.startswith("success:"):
            return "✅"
        elif renew_result == "today_renewed":
            return "📅"
        else:
            return "❌"
    
    def send_notification(self, email, success, renew_result, restart_status, restart_msg, screenshot):
        """发送单个账号的通知（带截图）"""
        if not self.tg_token or not self.tg_chat:
            return
        
        try:
            icon = self.get_status_icon(renew_result)
            renew_display = self.format_renew_result(renew_result)
            restart_display = self.format_restart_result(restart_status, restart_msg)
            
            text = f"""{icon} Pella Free 续期

账号：{email}
续期：{renew_display}
重启：{restart_display}
时间：{cn_time_str()}

Pella Free Auto Restart"""

            if screenshot and Path(screenshot).exists():
                with open(screenshot, "rb") as f:
                    response = requests.post(
                        f"https://api.telegram.org/bot{self.tg_token}/sendPhoto",
                        data={"chat_id": self.tg_chat, "caption": text},
                        files={"photo": f},
                        timeout=60
                    )
            else:
                response = requests.post(
                    f"https://api.telegram.org/bot{self.tg_token}/sendMessage",
                    json={"chat_id": self.tg_chat, "text": text},
                    timeout=30
                )
            
            if response.status_code == 200:
                logger.info(f"✅ {mask_email(email)} 通知已发送")
            else:
                logger.warning(f"⚠️ 通知发送失败: {response.text}")
                
        except Exception as e:
            logger.error(f"❌ 通知失败: {e}")
    
    def run_all(self):
        # 过滤账号
        accounts = self.filter_accounts(self.accounts)
        
        if self.target_account:
            if not accounts:
                logger.error(f"❌ 未找到匹配的账号: {self.target_account}")
                logger.info("可用账号:")
                for acc in self.accounts:
                    username = get_username_from_email(acc['email'])
                    logger.info(f"  - {username}")
                sys.exit(1)
            logger.info(f"🎯 指定账号模式: {mask_email(accounts[0]['email'])}")
        else:
            logger.info(f"📋 全量模式: 运行所有 {len(accounts)} 个账号")
        
        results = []
        total = len(accounts)
        
        for i, acc in enumerate(accounts, 1):
            logger.info(f"\n[{i}/{total}] {mask_email(acc['email'])}")
            
            try:
                renew = PellaAutoRenew(acc['email'], acc['password'], i)
                success, renew_result, restart_status, restart_msg, screenshot = renew.run()
                
                # 发送通知
                self.send_notification(
                    acc['email'], success, renew_result, 
                    restart_status, restart_msg, screenshot
                )
                
                results.append({
                    'email': acc['email'],
                    'success': success,
                    'renew': renew_result,
                    'restart': restart_status
                })
                
                if i < total:
                    time.sleep(5)
                    
            except Exception as e:
                logger.error(f"❌ 异常: {e}")
                self.send_notification(
                    acc['email'], False, f"error:{e}", 
                    "skip", "异常", None
                )
                results.append({
                    'email': acc['email'],
                    'success': False,
                    'renew': f"error:{e}",
                    'restart': 'skip'
                })
        
        # 打印汇总
        ok_count = sum(1 for r in results if r['success'])
        logger.info(f"\n{'=' * 50}")
        logger.info(f"📊 执行汇总: {ok_count}/{len(results)} 成功")
        logger.info(f"{'─' * 50}")
        for r in results:
            icon = "✅" if r['success'] else "❌"
            logger.info(f"{icon} {mask_email(r['email'])}: {self.format_renew_result(r['renew'])}")
        logger.info(f"{'=' * 50}")
        
        return ok_count > 0, results


def main():
    try:
        manager = MultiAccountManager()
        success, _ = manager.run_all()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"❌ 错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
