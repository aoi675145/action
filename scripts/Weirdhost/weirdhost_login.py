#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from DrissionPage import ChromiumPage, ChromiumOptions
import time
import os
import random
import requests
import tempfile
from typing import Optional

# ============== 配置 ==============
DEBUG = True
SCREENSHOT_DIR = "debug_screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

LOGIN_URL = "https://hub.weirdhost.xyz/auth/login"


class SpeechRecognizer:
    """语音识别器"""
    
    def __init__(self):
        self.recognizer = None
        self._init_recognizer()
    
    def _init_recognizer(self):
        """初始化语音识别"""
        try:
            # 方案1: 使用 OpenAI Whisper (推荐)
            import whisper
            self.model = whisper.load_model("base")
            self.method = "whisper"
            print("✅ 使用 Whisper 语音识别")
        except ImportError:
            try:
                # 方案2: 使用 SpeechRecognition
                import speech_recognition as sr
                self.recognizer = sr.Recognizer()
                self.method = "speech_recognition"
                print("✅ 使用 SpeechRecognition")
            except ImportError:
                print("⚠️ 未安装语音识别库，将使用在线 API")
                self.method = "api"
    
    def recognize(self, audio_path: str) -> Optional[str]:
        """识别音频"""
        if self.method == "whisper":
            return self._recognize_whisper(audio_path)
        elif self.method == "speech_recognition":
            return self._recognize_sr(audio_path)
        else:
            return self._recognize_api(audio_path)
    
    def _recognize_whisper(self, audio_path: str) -> Optional[str]:
        """使用 Whisper 识别"""
        try:
            import whisper
            result = self.model.transcribe(audio_path, language="en")
            text = result["text"].strip()
            # 清理文本，只保留数字和字母
            cleaned = ''.join(c for c in text if c.isalnum() or c.isspace())
            return cleaned.lower().strip()
        except Exception as e:
            print(f"   ⚠️ Whisper 识别失败: {e}")
            return None
    
    def _recognize_sr(self, audio_path: str) -> Optional[str]:
        """使用 SpeechRecognition 识别"""
        try:
            import speech_recognition as sr
            from pydub import AudioSegment
            
            # 转换 MP3 到 WAV
            wav_path = audio_path.replace('.mp3', '.wav')
            audio = AudioSegment.from_mp3(audio_path)
            audio.export(wav_path, format="wav")
            
            with sr.AudioFile(wav_path) as source:
                audio_data = self.recognizer.record(source)
            
            # 使用 Google 语音识别
            text = self.recognizer.recognize_google(audio_data, language="en-US")
            return text.lower().strip()
        except Exception as e:
            print(f"   ⚠️ SpeechRecognition 识别失败: {e}")
            return None
    
    def _recognize_api(self, audio_path: str) -> Optional[str]:
        """使用在线 API 识别 (备用)"""
        # 可以集成其他在线 API
        print("   ⚠️ 在线 API 识别暂未实现")
        return None


class WeirdhostLogin:
    """Weirdhost 登录器"""
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.page = None
        self.speech = SpeechRecognizer()
    
    def _create_browser(self) -> ChromiumPage:
        """创建浏览器"""
        co = ChromiumOptions()
        co.auto_port()
        
        if self.headless:
            co.headless()
        
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-dev-shm-usage')
        co.set_argument('--disable-gpu')
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--window-size=1280,900')
        
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
        """执行登录"""
        print(f"\n{'='*60}")
        print(f"🔐 开始登录: {email[:3]}***@***")
        print(f"{'='*60}")
        
        self.page = self._create_browser()
        
        try:
            # 1. 打开登录页面
            print("\n[1/5] 打开登录页面...")
            self.page.get(LOGIN_URL)
            self.page.wait.doc_loaded()
            time.sleep(2)
            
            if DEBUG:
                self.page.get_screenshot(path=f"{SCREENSHOT_DIR}/01_login_page.png")
            
            # 2. 填写邮箱
            print("[2/5] 填写邮箱...")
            email_input = self.page.ele('@name=username')
            if email_input:
                email_input.input(email)
                print("   ✅ 已输入邮箱")
            else:
                raise Exception("未找到邮箱输入框")
            
            time.sleep(0.3)
            
            # 3. 填写密码
            print("[3/5] 填写密码...")
            password_input = self.page.ele('@name=password')
            if password_input:
                password_input.input(password)
                print("   ✅ 已输入密码")
            else:
                raise Exception("未找到密码输入框")
            
            time.sleep(0.3)
            
            # 4. 勾选条款
            print("[4/5] 勾选条款...")
            checkbox = self.page.ele('@type=checkbox')
            if checkbox:
                checkbox.click()
                print("   ✅ 已勾选")
            
            time.sleep(0.5)
            
            if DEBUG:
                self.page.get_screenshot(path=f"{SCREENSHOT_DIR}/02_filled.png")
            
            # 5. 点击登录
            print("[5/5] 点击登录按钮...")
            login_btn = self.page.ele('@tag()=button@@text():로그인')
            if not login_btn:
                login_btn = self.page.ele('@@tag()=button@@class:jOimeR')
            
            if login_btn:
                login_btn.click()
                print("   ✅ 已点击登录")
            else:
                raise Exception("未找到登录按钮")
            
            time.sleep(2)
            
            if DEBUG:
                self.page.get_screenshot(path=f"{SCREENSHOT_DIR}/03_after_click.png")
            
            # 6. 处理 reCAPTCHA (语音验证)
            success = self._handle_audio_captcha()
            
            if success:
                time.sleep(3)
                current_url = self.page.url
                print(f"\n📍 当前URL: {current_url}")
                
                if "/auth/login" not in current_url:
                    print("✅ 登录成功!")
                    if DEBUG:
                        self.page.get_screenshot(path=f"{SCREENSHOT_DIR}/99_success.png")
                    return True
                else:
                    print("❌ 仍在登录页面")
                    return False
            
            return False
            
        except Exception as e:
            print(f"❌ 登录异常: {e}")
            import traceback
            traceback.print_exc()
            if DEBUG:
                self.page.get_screenshot(path=f"{SCREENSHOT_DIR}/error.png")
            return False
        
        finally:
            if self.page:
                self.page.quit()
    
    def _get_recaptcha_frame(self):
        """获取 reCAPTCHA 弹窗 frame"""
        frame = self.page.get_frame('@src:recaptcha.net/recaptcha/api2/bframe')
        if not frame:
            frame = self.page.get_frame('@src:recaptcha/api2/bframe')
        if not frame:
            frame = self.page.get_frame('@src:recaptcha/enterprise/bframe')
        return frame
    
    def _handle_audio_captcha(self) -> bool:
        """处理语音验证"""
        print("\n🔍 检测 reCAPTCHA...")
        
        max_retries = 10
        
        for attempt in range(max_retries):
            print(f"\n🔄 --- 第 {attempt + 1} 次尝试 ---")
            
            # 检查是否已跳转
            if "/auth/login" not in self.page.url:
                print("✅ 页面已跳转!")
                return True
            
            # 查找 reCAPTCHA 弹窗
            recaptcha_frame = self._get_recaptcha_frame()
            
            if not recaptcha_frame:
                print("   📭 未检测到验证弹窗")
                time.sleep(1)
                
                if "/auth/login" not in self.page.url:
                    return True
                
                # 重新点击登录
                if attempt > 1:
                    login_btn = self.page.ele('@tag()=button@@text():로그인')
                    if login_btn:
                        login_btn.click()
                        time.sleep(2)
                continue
            
            print("   🎯 检测到 reCAPTCHA 弹窗!")
            
            if DEBUG:
                self.page.get_screenshot(path=f"{SCREENSHOT_DIR}/captcha_{attempt}.png")
            
            # 步骤1: 点击语音按钮
            print("   🔊 切换到语音验证...")
            audio_btn = recaptcha_frame.ele("#recaptcha-audio-button")
            
            if not audio_btn:
                print("   ⚠️ 未找到语音按钮")
                time.sleep(1)
                continue
            
            # 检查是否已经在语音模式
            audio_challenge = recaptcha_frame.ele("#rc-audio")
            if not audio_challenge or not audio_challenge.states.is_displayed:
                audio_btn.click()
                time.sleep(2)
            
            if DEBUG:
                self.page.get_screenshot(path=f"{SCREENSHOT_DIR}/audio_mode_{attempt}.png")
            
            # 步骤2: 检查是否有错误消息（被检测到自动化）
            error_msg = recaptcha_frame.ele(".rc-audiochallenge-error-message")
            if error_msg and error_msg.states.is_displayed:
                error_text = error_msg.text
                print(f"   ❌ 错误: {error_text}")
                
                if "自动" in error_text or "automated" in error_text.lower():
                    print("   ⚠️ 被检测到自动化，刷新重试...")
                    reload_btn = recaptcha_frame.ele("#recaptcha-reload-button")
                    if reload_btn:
                        reload_btn.click()
                        time.sleep(2)
                    continue
            
            # 步骤3: 获取音频下载链接
            print("   📥 获取音频链接...")
            download_link = recaptcha_frame.ele(".rc-audiochallenge-tdownload-link")
            
            if not download_link:
                # 备用: 从 audio source 获取
                audio_source = recaptcha_frame.ele("#audio-source")
                if audio_source:
                    audio_url = audio_source.attr("src")
                else:
                    print("   ⚠️ 未找到音频链接")
                    continue
            else:
                audio_url = download_link.attr("href")
            
            if not audio_url:
                print("   ⚠️ 音频链接为空")
                continue
            
            print(f"   🔗 音频URL: {audio_url[:80]}...")
            
            # 步骤4: 下载音频
            print("   📥 下载音频文件...")
            audio_path = self._download_audio(audio_url)
            
            if not audio_path:
                print("   ⚠️ 下载音频失败")
                continue
            
            print(f"   ✅ 音频已保存: {audio_path}")
            
            # 步骤5: 语音识别
            print("   🎤 识别语音内容...")
            recognized_text = self.speech.recognize(audio_path)
            
            if not recognized_text:
                print("   ⚠️ 语音识别失败，刷新重试...")
                reload_btn = recaptcha_frame.ele("#recaptcha-reload-button")
                if reload_btn:
                    reload_btn.click()
                    time.sleep(2)
                continue
            
            print(f"   📝 识别结果: {recognized_text}")
            
            # 步骤6: 输入识别文字
            print("   ⌨️ 输入验证答案...")
            response_input = recaptcha_frame.ele("#audio-response")
            
            if not response_input:
                print("   ⚠️ 未找到输入框")
                continue
            
            response_input.clear()
            time.sleep(0.2)
            
            # 模拟人类输入
            for char in recognized_text:
                response_input.input(char)
                time.sleep(random.uniform(0.05, 0.15))
            
            time.sleep(0.5)
            
            if DEBUG:
                self.page.get_screenshot(path=f"{SCREENSHOT_DIR}/input_{attempt}.png")
            
            # 步骤7: 点击验证
            print("   🖱️ 点击验证按钮...")
            verify_btn = recaptcha_frame.ele("#recaptcha-verify-button")
            
            if verify_btn:
                verify_btn.click()
                time.sleep(3)
            
            if DEBUG:
                self.page.get_screenshot(path=f"{SCREENSHOT_DIR}/verify_{attempt}.png")
            
            # 检查结果
            if "/auth/login" not in self.page.url:
                print("   ✅ 验证成功!")
                return True
            
            # 检查是否还有验证码
            recaptcha_frame = self._get_recaptcha_frame()
            if not recaptcha_frame:
                print("   ✅ 验证码已消失!")
                time.sleep(2)
                if "/auth/login" not in self.page.url:
                    return True
            
            # 检查错误
            if recaptcha_frame:
                error_msg = recaptcha_frame.ele(".rc-audiochallenge-error-message")
                if error_msg and error_msg.states.is_displayed:
                    print(f"   ❌ 验证失败: {error_msg.text}")
                    # 刷新重试
                    reload_btn = recaptcha_frame.ele("#recaptcha-reload-button")
                    if reload_btn:
                        reload_btn.click()
                        time.sleep(2)
            
            # 清理临时文件
            try:
                os.remove(audio_path)
            except:
                pass
        
        return False
    
    def _download_audio(self, url: str) -> Optional[str]:
        """下载音频文件"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'audio/webm,audio/ogg,audio/wav,audio/*;q=0.9,*/*;q=0.8',
                'Referer': 'https://www.google.com/',
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            # 保存到临时文件
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
                f.write(response.content)
                return f.name
                
        except Exception as e:
            print(f"   ⚠️ 下载失败: {e}")
            return None


def main():
    print("=" * 60)
    print("🚀 Weirdhost 自动登录 (语音验证版)")
    print("=" * 60)
    
    email = os.environ.get("TEST_EMAIL", "")
    password = os.environ.get("TEST_PASSWORD", "")
    
    if not email or not password:
        print("❌ 错误: 未设置 TEST_EMAIL 或 TEST_PASSWORD 环境变量")
        exit(1)
    
    print(f"📧 账号: {email[:3]}***@***")
    
    login_handler = WeirdhostLogin(headless=True)
    success = login_handler.login(email, password)
    
    if success:
        print("\n" + "=" * 60)
        print("🎉 登录成功!")
        print("=" * 60)
        exit(0)
    else:
        print("\n" + "=" * 60)
        print("❌ 登录失败!")
        print("=" * 60)
        exit(1)


if __name__ == "__main__":
    main()
