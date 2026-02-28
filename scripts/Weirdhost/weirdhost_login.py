#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Weirdhost 自动登录 - Google Speech Recognition
"""

from DrissionPage import ChromiumPage, ChromiumOptions
import time
import os
import random
import requests
import tempfile
import html
from typing import Optional

DEBUG = True
SCREENSHOT_DIR = "debug_screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

LOGIN_URL = "https://hub.weirdhost.xyz/auth/login"


class RecaptchaSolver:
    """reCAPTCHA 音频验证破解器"""
    
    def __init__(self, page):
        self.page = page
    
    def log(self, msg):
        print(f"   [Solver] {msg}")
    
    def get_bframe(self):
        """获取 reCAPTCHA bframe"""
        for src in ['recaptcha.net/recaptcha/api2/bframe',
                    'google.com/recaptcha/api2/bframe',
                    'recaptcha/api2/bframe']:
            frame = self.page.get_frame(f'@src:{src}')
            if frame:
                return frame
        return None
    
    def get_audio_source(self, iframe_ele) -> Optional[str]:
        """获取音频下载链接"""
        try:
            # 检查是否被拦截
            err_msg = iframe_ele.ele('css:.rc-audiochallenge-error-message')
            if err_msg and err_msg.states.is_displayed:
                self.log(f"⛔ 被拦截: {err_msg.text}")
                return None
            
            # 方法1: 下载链接
            download_link = iframe_ele.ele('css:.rc-audiochallenge-tdownload-link')
            if download_link:
                href = download_link.attr('href')
                if href:
                    return html.unescape(href)
            
            # 方法2: XPath 查找 mp3
            download_link = iframe_ele.ele('xpath://a[contains(@href, ".mp3")]')
            if download_link:
                href = download_link.attr('href')
                if href:
                    return html.unescape(href)
            
            # 方法3: audio-source
            audio_tag = iframe_ele.ele('css:#audio-source')
            if audio_tag:
                src = audio_tag.attr('src')
                if src:
                    return html.unescape(src)
            
            return None
        except:
            return None
    
    def download_audio(self, url: str) -> Optional[str]:
        """下载音频"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.google.com/',
            }
            
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            
            self.log(f"📥 下载: {len(r.content)} bytes")
            
            mp3_path = tempfile.mktemp(suffix='.mp3')
            with open(mp3_path, 'wb') as f:
                f.write(r.content)
            return mp3_path
                
        except Exception as e:
            self.log(f"❌ 下载失败: {e}")
            return None
    
    def recognize_audio(self, mp3_path: str) -> Optional[str]:
        """Google 语音识别"""
        try:
            import speech_recognition as sr
            from pydub import AudioSegment
            
            # MP3 转 WAV
            self.log("🔄 转换格式...")
            wav_path = mp3_path.replace('.mp3', '.wav')
            sound = AudioSegment.from_mp3(mp3_path)
            sound.export(wav_path, format="wav")
            
            # 识别
            self.log("🎤 Google 识别...")
            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                audio_data = recognizer.record(source)
                text = recognizer.recognize_google(audio_data)
            
            # 清理
            try:
                os.remove(wav_path)
            except:
                pass
            
            return text
            
        except Exception as e:
            self.log(f"❌ 识别失败: {e}")
            return None
    
    def solve(self, max_attempts: int = 8) -> bool:
        """解决 reCAPTCHA"""
        self.log("🎧 启动音频破解...")
        
        for attempt in range(max_attempts):
            self.log(f"\n===== 尝试 {attempt + 1}/{max_attempts} =====")
            
            # 检查是否已跳转
            if "/auth/login" not in self.page.url:
                self.log("✅ 已跳转!")
                return True
            
            # 获取 iframe
            iframe_ele = self.get_bframe()
            if not iframe_ele:
                self.log("📭 未检测到验证码")
                time.sleep(2)
                continue
            
            self.log("🎯 找到 reCAPTCHA")
            self.page.get_screenshot(path=f"{SCREENSHOT_DIR}/attempt_{attempt:02d}_00.png")
            
            # 点击音频按钮
            audio_btn = iframe_ele.ele('css:#recaptcha-audio-button', timeout=3)
            if audio_btn:
                try:
                    if audio_btn.states.is_displayed:
                        self.log("🖱️ 点击音频按钮...")
                        audio_btn.click()
                        time.sleep(random.uniform(2, 4))
                except:
                    audio_btn.click()
                    time.sleep(3)
            
            self.page.get_screenshot(path=f"{SCREENSHOT_DIR}/attempt_{attempt:02d}_01.png")
            
            # 获取音频链接
            src = self.get_audio_source(iframe_ele)
            
            if not src:
                self.log("⚠️ 获取音频失败，刷新...")
                reload_btn = iframe_ele.ele('css:#recaptcha-reload-button', timeout=3)
                if reload_btn:
                    reload_btn.click()
                    time.sleep(random.uniform(3, 5))
                    src = self.get_audio_source(iframe_ele)
            
            if not src:
                self.log("❌ 无法获取音频")
                # 保存 HTML 调试
                try:
                    with open(f"{SCREENSHOT_DIR}/attempt_{attempt:02d}.html", 'w') as f:
                        f.write(iframe_ele.html)
                except:
                    pass
                time.sleep(2)
                continue
            
            self.log(f"📎 音频: {src[:60]}...")
            
            # 下载音频
            mp3_path = self.download_audio(src)
            if not mp3_path:
                continue
            
            # 语音识别
            key_text = self.recognize_audio(mp3_path)
            
            # 清理
            try:
                os.remove(mp3_path)
            except:
                pass
            
            if not key_text:
                self.log("❌ 识别失败，刷新重试...")
                reload_btn = iframe_ele.ele('css:#recaptcha-reload-button')
                if reload_btn:
                    reload_btn.click()
                    time.sleep(3)
                continue
            
            self.log(f"🗣️ 识别: [{key_text}]")
            
            # 输入答案
            input_box = iframe_ele.ele('css:#audio-response')
            if not input_box:
                self.log("❌ 未找到输入框")
                continue
            
            input_box.click()
            time.sleep(0.5)
            
            # 模拟人工输入
            for char in key_text:
                input_box.input(char, clear=False)
                time.sleep(random.uniform(0.05, 0.15))
            
            time.sleep(1)
            self.page.get_screenshot(path=f"{SCREENSHOT_DIR}/attempt_{attempt:02d}_02.png")
            
            # 点击验证
            verify_btn = iframe_ele.ele('css:#recaptcha-verify-button')
            if verify_btn:
                verify_btn.click()
                self.log("🚀 提交验证...")
                time.sleep(4)
            
            self.page.get_screenshot(path=f"{SCREENSHOT_DIR}/attempt_{attempt:02d}_03.png")
            
            # 检查结果
            if "/auth/login" not in self.page.url:
                self.log("✅ 验证通过!")
                return True
            
            # 检查错误
            try:
                err = iframe_ele.ele('css:.rc-audiochallenge-error-message')
                if err and err.states.is_displayed:
                    self.log(f"❌ 错误: {err.text}")
            except:
                pass
        
        return False


class WeirdhostLogin:
    """Weirdhost 登录器"""
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.page = None
    
    def _create_browser(self) -> ChromiumPage:
        co = ChromiumOptions()
        co.auto_port()
        
        if self.headless:
            co.headless()
        
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-dev-shm-usage')
        co.set_argument('--disable-gpu')
        co.set_argument('--window-size=1280,900')
        co.set_argument('--disable-blink-features=AutomationControlled')
        
        chrome_path = '/usr/bin/google-chrome'
        if os.path.exists(chrome_path):
            co.set_browser_path(chrome_path)
        
        co.set_user_agent(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )
        
        return ChromiumPage(co)
    
    def login(self, email: str, password: str) -> bool:
        print(f"\n{'='*60}")
        print(f"🔐 Weirdhost 自动登录")
        print(f"{'='*60}")
        
        self.page = self._create_browser()
        
        try:
            # 打开页面
            print(f"\n[1/5] 打开页面...")
            self.page.get(LOGIN_URL)
            self.page.wait.doc_loaded()
            time.sleep(2)
            
            # 填写表单
            print(f"\n[2/5] 填写邮箱...")
            email_input = self.page.ele('@name=username') or self.page.ele('@type=email')
            if email_input:
                email_input.clear()
                email_input.input(email)
            
            print(f"\n[3/5] 填写密码...")
            pwd_input = self.page.ele('@name=password') or self.page.ele('@type=password')
            if pwd_input:
                pwd_input.clear()
                pwd_input.input(password)
            
            print(f"\n[4/5] 勾选条款...")
            checkbox = self.page.ele('@type=checkbox')
            if checkbox and not checkbox.states.is_checked:
                checkbox.click()
            
            # 点击登录
            print(f"\n[5/5] 点击登录...")
            login_btn = (self.page.ele('@tag()=button@@text():로그인') or 
                        self.page.ele('@tag()=button@@text():Login') or
                        self.page.ele('@@tag()=button@@type=submit'))
            if login_btn:
                login_btn.click()
            
            time.sleep(2)
            
            # 处理验证码
            print(f"\n[*] 处理 reCAPTCHA...")
            solver = RecaptchaSolver(self.page)
            success = solver.solve()
            
            time.sleep(2)
            final_url = self.page.url
            print(f"\n📍 最终 URL: {final_url}")
            
            if "/auth/login" not in final_url:
                print(f"\n🎉 登录成功!")
                return True
            
            return False
                
        except Exception as e:
            print(f"\n❌ 异常: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        finally:
            if self.page:
                self.page.quit()


def main():
    print("=" * 60)
    print("🚀 Weirdhost 自动登录 (Google Speech)")
    print("=" * 60)
    
    email = os.environ.get("TEST_EMAIL", "")
    password = os.environ.get("TEST_PASSWORD", "")
    
    if not all([email, password]):
        print("❌ 缺少 TEST_EMAIL 或 TEST_PASSWORD")
        exit(1)
    
    print(f"\n📋 邮箱: {email[:3]}***")
    
    headless = os.environ.get("HEADLESS", "true").lower() == "true"
    
    login = WeirdhostLogin(headless=headless)
    success = login.login(email, password)
    
    exit(0 if success else 1)


if __name__ == "__main__":
    main()
