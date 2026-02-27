#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Weirdhost 自动登录 - Wit.ai 语音验证方案
参考: https://github.com/dessant/buster
"""

from DrissionPage import ChromiumPage, ChromiumOptions
import time
import os
import random
import requests
import tempfile
import re
from typing import Optional

# ============== 配置 ==============
DEBUG = True
SCREENSHOT_DIR = "debug_screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

LOGIN_URL = "https://hub.weirdhost.xyz/auth/login"

# Wit.ai Token
WIT_AI_TOKEN = os.environ.get("WIT_AI_TOKEN", "")


class WitAiRecognizer:
    """Wit.ai 语音识别器"""
    
    def __init__(self, token: str):
        self.token = token
        if not self.token:
            raise ValueError("WIT_AI_TOKEN 未设置")
    
    def recognize(self, audio_path: str) -> Optional[str]:
        """
        识别音频文件
        
        Args:
            audio_path: MP3 音频文件路径
            
        Returns:
            识别的文本，失败返回 None
        """
        try:
            # 读取音频文件
            with open(audio_path, 'rb') as f:
                audio_data = f.read()
            
            print(f"      📤 上传音频 ({len(audio_data)} bytes)...")
            
            # 调用 Wit.ai API
            headers = {
                'Authorization': f'Bearer {self.token}',
                'Content-Type': 'audio/mpeg3',
            }
            
            response = requests.post(
                'https://api.wit.ai/speech?v=20231117',
                headers=headers,
                data=audio_data,
                timeout=30
            )
            
            print(f"      📥 响应状态: {response.status_code}")
            
            if response.status_code == 200:
                # Wit.ai 返回的可能是多行 JSON
                # 取最后一个完整的 JSON
                text = response.text.strip()
                lines = text.split('\n')
                
                result_text = ""
                for line in reversed(lines):
                    try:
                        result = __import__('json').loads(line)
                        if 'text' in result:
                            result_text = result['text']
                            break
                    except:
                        continue
                
                if result_text:
                    cleaned = self._clean_text(result_text)
                    print(f"      ✅ 原始: {result_text}")
                    print(f"      ✅ 清理: {cleaned}")
                    return cleaned
                else:
                    print(f"      ⚠️ 响应中无文本: {text[:200]}")
                    return None
            else:
                print(f"      ❌ API 错误: {response.status_code}")
                print(f"      ❌ 响应: {response.text[:200]}")
                return None
                
        except Exception as e:
            print(f"      ❌ 识别异常: {e}")
            return None
    
    def _clean_text(self, text: str) -> str:
        """
        清理识别文本
        reCAPTCHA 音频通常是数字或简单单词
        """
        if not text:
            return ""
        
        # 转小写
        text = text.lower().strip()
        
        # 移除标点符号
        text = re.sub(r'[^\w\s]', '', text)
        
        # 数字单词转数字
        word_to_num = {
            'zero': '0', 'oh': '0', 'o': '0',
            'one': '1', 'won': '1',
            'two': '2', 'to': '2', 'too': '2',
            'three': '3', 'tree': '3',
            'four': '4', 'for': '4', 'fore': '4',
            'five': '5', 'fife': '5',
            'six': '6', 'sex': '6',
            'seven': '7',
            'eight': '8', 'ate': '8',
            'nine': '9', 'niner': '9',
        }
        
        words = text.split()
        result = []
        for word in words:
            word = word.strip()
            if word in word_to_num:
                result.append(word_to_num[word])
            elif word:
                result.append(word)
        
        return ' '.join(result)


class WeirdhostLogin:
    """Weirdhost 登录器"""
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.page = None
        self.recognizer = WitAiRecognizer(WIT_AI_TOKEN)
    
    def _create_browser(self) -> ChromiumPage:
        """创建浏览器实例"""
        co = ChromiumOptions()
        co.auto_port()
        
        if self.headless:
            co.headless()
        
        # 基本参数
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-dev-shm-usage')
        co.set_argument('--disable-gpu')
        co.set_argument('--window-size=1280,900')
        
        # 反检测参数
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--disable-infobars')
        co.set_argument('--disable-extensions')
        
        # Chrome 路径
        chrome_path = '/usr/bin/google-chrome'
        if os.path.exists(chrome_path):
            co.set_browser_path(chrome_path)
        
        # User-Agent
        co.set_user_agent(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )
        
        return ChromiumPage(co)
    
    def _save_screenshot(self, name: str):
        """保存截图"""
        if DEBUG and self.page:
            path = f"{SCREENSHOT_DIR}/{name}.png"
            self.page.get_screenshot(path=path)
            print(f"      📸 截图: {name}.png")
    
    def login(self, email: str, password: str) -> bool:
        """
        执行登录
        
        Args:
            email: 邮箱
            password: 密码
            
        Returns:
            是否成功
        """
        print(f"\n{'='*60}")
        print(f"🔐 Weirdhost 自动登录")
        print(f"{'='*60}")
        print(f"📧 账号: {email[:3]}***@***")
        print(f"🔑 密码: {'*' * 8}")
        
        self.page = self._create_browser()
        
        try:
            # ========== 步骤1: 打开登录页面 ==========
            print(f"\n[1/6] 打开登录页面...")
            self.page.get(LOGIN_URL)
            self.page.wait.doc_loaded()
            time.sleep(2)
            
            self._save_screenshot("01_login_page")
            print(f"   ✅ 页面已加载")
            
            # ========== 步骤2: 填写邮箱 ==========
            print(f"\n[2/6] 填写邮箱...")
            email_input = self.page.ele('@name=username')
            if not email_input:
                email_input = self.page.ele('@type=email')
            if not email_input:
                email_input = self.page.ele('@placeholder:email')
            
            if email_input:
                email_input.clear()
                email_input.input(email)
                print(f"   ✅ 已输入邮箱")
            else:
                raise Exception("未找到邮箱输入框")
            
            time.sleep(random.uniform(0.3, 0.6))
            
            # ========== 步骤3: 填写密码 ==========
            print(f"\n[3/6] 填写密码...")
            password_input = self.page.ele('@name=password')
            if not password_input:
                password_input = self.page.ele('@type=password')
            
            if password_input:
                password_input.clear()
                password_input.input(password)
                print(f"   ✅ 已输入密码")
            else:
                raise Exception("未找到密码输入框")
            
            time.sleep(random.uniform(0.3, 0.6))
            
            # ========== 步骤4: 勾选条款 ==========
            print(f"\n[4/6] 勾选条款...")
            checkbox = self.page.ele('@type=checkbox')
            if checkbox:
                if not checkbox.states.is_checked:
                    checkbox.click()
                print(f"   ✅ 已勾选")
            else:
                print(f"   ⚠️ 未找到复选框")
            
            time.sleep(random.uniform(0.3, 0.6))
            self._save_screenshot("02_form_filled")
            
            # ========== 步骤5: 点击登录 ==========
            print(f"\n[5/6] 点击登录按钮...")
            
            # 尝试多种方式找登录按钮
            login_btn = None
            btn_selectors = [
                '@tag()=button@@text():로그인',      # 韩文登录
                '@tag()=button@@text():Login',       # 英文登录
                '@tag()=button@@text():登录',        # 中文登录
                '@@tag()=button@@type=submit',       # 提交按钮
                'css:button[type="submit"]',
                'css:form button',
            ]
            
            for selector in btn_selectors:
                login_btn = self.page.ele(selector)
                if login_btn:
                    break
            
            if login_btn:
                login_btn.click()
                print(f"   ✅ 已点击登录按钮")
            else:
                raise Exception("未找到登录按钮")
            
            time.sleep(2)
            self._save_screenshot("03_after_login_click")
            
            # ========== 步骤6: 处理验证码 ==========
            print(f"\n[6/6] 处理 reCAPTCHA...")
            success = self._handle_recaptcha()
            
            # ========== 检查结果 ==========
            time.sleep(2)
            current_url = self.page.url
            print(f"\n📍 当前 URL: {current_url}")
            
            if "/auth/login" not in current_url:
                print(f"\n{'='*60}")
                print(f"🎉 登录成功!")
                print(f"{'='*60}")
                self._save_screenshot("99_success")
                return True
            else:
                print(f"\n{'='*60}")
                print(f"❌ 登录失败 - 仍在登录页面")
                print(f"{'='*60}")
                self._save_screenshot("99_failed")
                return False
                
        except Exception as e:
            print(f"\n❌ 登录异常: {e}")
            import traceback
            traceback.print_exc()
            self._save_screenshot("99_error")
            return False
        
        finally:
            if self.page:
                print(f"\n🔒 关闭浏览器...")
                self.page.quit()
    
    def _get_recaptcha_frame(self):
        """获取 reCAPTCHA 弹窗 iframe"""
        frame_srcs = [
            'recaptcha.net/recaptcha/api2/bframe',
            'google.com/recaptcha/api2/bframe',
            'recaptcha/api2/bframe',
            'recaptcha/enterprise/bframe',
        ]
        
        for src in frame_srcs:
            frame = self.page.get_frame(f'@src:{src}')
            if frame:
                return frame
        
        return None
    
    def _handle_recaptcha(self) -> bool:
        """
        处理 reCAPTCHA 语音验证
        
        Returns:
            是否成功
        """
        max_attempts = 15
        
        for attempt in range(max_attempts):
            print(f"\n   🔄 尝试 {attempt + 1}/{max_attempts}")
            
            # 检查是否已跳转
            if "/auth/login" not in self.page.url:
                print(f"   ✅ 页面已跳转，无需验证!")
                return True
            
            # 获取验证码 iframe
            frame = self._get_recaptcha_frame()
            
            if not frame:
                print(f"   📭 未检测到 reCAPTCHA 弹窗")
                time.sleep(1)
                
                # 检查是否已跳转
                if "/auth/login" not in self.page.url:
                    return True
                
                # 多次未检测到，尝试重新点击登录
                if attempt >= 2 and attempt % 3 == 0:
                    print(f"   🔄 重新点击登录按钮...")
                    for selector in ['@tag()=button@@text():로그인', 
                                     '@tag()=button@@type=submit']:
                        btn = self.page.ele(selector)
                        if btn:
                            btn.click()
                            time.sleep(2)
                            break
                continue
            
            print(f"   🎯 检测到 reCAPTCHA 弹窗!")
            self._save_screenshot(f"captcha_{attempt:02d}")
            
            # ===== 步骤1: 切换到语音验证 =====
            audio_challenge = frame.ele("#rc-audio")
            if not audio_challenge or not audio_challenge.states.is_displayed:
                print(f"   🔊 切换到语音验证模式...")
                audio_btn = frame.ele("#recaptcha-audio-button")
                
                if audio_btn and audio_btn.states.is_displayed:
                    audio_btn.click()
                    time.sleep(2)
                    self._save_screenshot(f"audio_mode_{attempt:02d}")
                else:
                    print(f"   ⚠️ 语音按钮不可用")
            
            # ===== 步骤2: 检查错误消息 =====
            error_el = frame.ele(".rc-audiochallenge-error-message")
            if error_el and error_el.states.is_displayed:
                error_text = error_el.text
                print(f"   ❌ 错误消息: {error_text}")
                
                # 检查是否被限制
                if any(kw in error_text.lower() for kw in 
                       ['automated', '自动', 'later', '稍后', 'try again']):
                    print(f"   ⚠️ 被检测到自动化，等待后刷新...")
                    time.sleep(random.uniform(3, 6))
                    
                    reload_btn = frame.ele("#recaptcha-reload-button")
                    if reload_btn:
                        reload_btn.click()
                        time.sleep(2)
                    continue
            
            # ===== 步骤3: 获取音频链接 =====
            print(f"   📥 获取音频链接...")
            audio_url = None
            
            # 方法1: 从下载链接获取
            download_link = frame.ele(".rc-audiochallenge-tdownload-link")
            if download_link:
                audio_url = download_link.attr("href")
                print(f"   📎 从下载链接获取")
            
            # 方法2: 从 audio source 获取
            if not audio_url:
                audio_source = frame.ele("#audio-source")
                if audio_source:
                    audio_url = audio_source.attr("src")
                    print(f"   📎 从 audio source 获取")
            
            if not audio_url:
                print(f"   ⚠️ 无法获取音频链接，刷新重试...")
                reload_btn = frame.ele("#recaptcha-reload-button")
                if reload_btn:
                    reload_btn.click()
                    time.sleep(2)
                continue
            
            print(f"   🔗 音频 URL: {audio_url[:70]}...")
            
            # ===== 步骤4: 下载音频 =====
            print(f"   📥 下载音频文件...")
            audio_path = self._download_audio(audio_url)
            
            if not audio_path:
                print(f"   ⚠️ 下载失败，刷新重试...")
                reload_btn = frame.ele("#recaptcha-reload-button")
                if reload_btn:
                    reload_btn.click()
                    time.sleep(2)
                continue
            
            print(f"   ✅ 音频已下载: {audio_path}")
            
            # ===== 步骤5: 语音识别 =====
            print(f"   🎤 调用 Wit.ai 识别...")
            recognized_text = self.recognizer.recognize(audio_path)
            
            # 清理临时文件
            try:
                os.remove(audio_path)
            except:
                pass
            
            if not recognized_text:
                print(f"   ⚠️ 识别失败，刷新重试...")
                reload_btn = frame.ele("#recaptcha-reload-button")
                if reload_btn:
                    reload_btn.click()
                    time.sleep(2)
                continue
            
            print(f"   📝 识别结果: {recognized_text}")
            
            # ===== 步骤6: 输入验证答案 =====
            print(f"   ⌨️ 输入验证答案...")
            response_input = frame.ele("#audio-response")
            
            if not response_input:
                print(f"   ⚠️ 未找到输入框")
                continue
            
            # 清空输入框
            response_input.clear()
            time.sleep(0.2)
            
            # 模拟人类输入
            for char in recognized_text:
                response_input.input(char)
                time.sleep(random.uniform(0.05, 0.12))
            
            time.sleep(0.5)
            self._save_screenshot(f"input_{attempt:02d}")
            
            # ===== 步骤7: 点击验证按钮 =====
            print(f"   🖱️ 点击验证按钮...")
            verify_btn = frame.ele("#recaptcha-verify-button")
            
            if verify_btn:
                verify_btn.click()
                time.sleep(3)
            else:
                print(f"   ⚠️ 未找到验证按钮")
                continue
            
            self._save_screenshot(f"verify_{attempt:02d}")
            
            # ===== 检查验证结果 =====
            # 检查是否跳转
            if "/auth/login" not in self.page.url:
                print(f"   ✅ 验证成功，页面已跳转!")
                return True
            
            # 检查验证码是否消失
            time.sleep(1)
            new_frame = self._get_recaptcha_frame()
            if not new_frame:
                print(f"   ✅ 验证码已消失!")
                time.sleep(2)
                if "/auth/login" not in self.page.url:
                    return True
                # 可能需要等待页面跳转
                time.sleep(3)
                if "/auth/login" not in self.page.url:
                    return True
            
            # 检查是否有新的错误
            if new_frame:
                # 检查是否显示"请重试"
                retry_msg = new_frame.ele(".rc-audiochallenge-error-message")
                if retry_msg and retry_msg.states.is_displayed:
                    print(f"   ⚠️ 验证失败: {retry_msg.text}")
                
                # 多次重试响应错误，刷新换一个
                incorrect = new_frame.ele("text:incorrect") or new_frame.ele("text:请重试")
                if incorrect:
                    print(f"   🔄 答案错误，刷新重试...")
                    reload_btn = new_frame.ele("#recaptcha-reload-button")
                    if reload_btn:
                        reload_btn.click()
                        time.sleep(2)
            
            print(f"   🔄 继续下一轮尝试...")
        
        print(f"\n   ❌ 已达最大尝试次数")
        return False
    
    def _download_audio(self, url: str) -> Optional[str]:
        """
        下载音频文件
        
        Args:
            url: 音频 URL
            
        Returns:
            本地文件路径，失败返回 None
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'audio/webm,audio/ogg,audio/wav,audio/*;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.google.com/',
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            # 保存到临时文件
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
                f.write(response.content)
                return f.name
                
        except requests.RequestException as e:
            print(f"      ❌ 下载失败: {e}")
            return None


def main():
    """主函数"""
    print("=" * 60)
    print("🚀 Weirdhost 自动登录 (Wit.ai 语音验证)")
    print("=" * 60)
    
    # 获取环境变量
    email = os.environ.get("TEST_EMAIL", "")
    password = os.environ.get("TEST_PASSWORD", "")
    wit_token = os.environ.get("WIT_AI_TOKEN", "")
    
    # 检查配置
    if not email:
        print("❌ 错误: 未设置 TEST_EMAIL 环境变量")
        exit(1)
    
    if not password:
        print("❌ 错误: 未设置 TEST_PASSWORD 环境变量")
        exit(1)
    
    if not wit_token:
        print("❌ 错误: 未设置 WIT_AI_TOKEN 环境变量")
        print("   请访问 https://wit.ai/ 创建 App 并获取 Token")
        exit(1)
    
    print(f"\n📋 配置检查:")
    print(f"   📧 邮箱: {email[:3]}***@***")
    print(f"   🔑 密码: {'*' * len(password)}")
    print(f"   🎤 Wit.ai Token: {wit_token[:8]}***")
    
    # 执行登录
    headless = os.environ.get("HEADLESS", "true").lower() == "true"
    print(f"   🖥️ 无头模式: {headless}")
    
    login_handler = WeirdhostLogin(headless=headless)
    success = login_handler.login(email, password)
    
    # 返回结果
    if success:
        print("\n✅ 程序执行成功")
        exit(0)
    else:
        print("\n❌ 程序执行失败")
        exit(1)


if __name__ == "__main__":
    main()
