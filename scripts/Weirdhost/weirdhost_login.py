#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from DrissionPage import ChromiumPage, ChromiumOptions
import time
import os
import random
import requests
import tempfile
import re
import html  # 用于解码 HTML 转义
from typing import Optional

# ============== 配置 ==============
DEBUG = True
SCREENSHOT_DIR = "debug_screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

LOGIN_URL = "https://hub.weirdhost.xyz/auth/login"
WIT_AI_TOKEN = os.environ.get("WIT_AI_TOKEN", "")


class WitAiRecognizer:
    """Wit.ai 语音识别器"""
    
    def __init__(self, token: str):
        self.token = token
        if not self.token:
            raise ValueError("WIT_AI_TOKEN 未设置")
    
    def recognize(self, audio_path: str) -> Optional[str]:
        """识别音频文件"""
        try:
            with open(audio_path, 'rb') as f:
                audio_data = f.read()
            
            print(f"      📤 上传音频 ({len(audio_data)} bytes)...")
            
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
                text = response.text.strip()
                print(f"      📥 原始响应: {text[:200]}")
                
                lines = text.split('\n')
                result_text = ""
                
                for line in reversed(lines):
                    try:
                        import json
                        result = json.loads(line)
                        if 'text' in result and result['text']:
                            result_text = result['text']
                            break
                    except:
                        continue
                
                if result_text:
                    cleaned = self._clean_text(result_text)
                    print(f"      ✅ 原始识别: {result_text}")
                    print(f"      ✅ 清理后: {cleaned}")
                    return cleaned
                else:
                    print(f"      ⚠️ 响应中无 text 字段")
                    
            return None
                
        except Exception as e:
            print(f"      ❌ 识别异常: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _clean_text(self, text: str) -> str:
        """清理识别文本，转换数字单词"""
        if not text:
            return ""
        
        text = text.lower().strip()
        text = re.sub(r'[^\w\s]', '', text)
        
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
        """创建浏览器"""
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
    
    def _save_screenshot(self, name: str):
        """保存截图"""
        if DEBUG and self.page:
            path = f"{SCREENSHOT_DIR}/{name}.png"
            self.page.get_screenshot(path=path)
            print(f"      📸 截图: {name}.png")
    
    def login(self, email: str, password: str) -> bool:
        """执行登录"""
        print(f"\n{'='*60}")
        print(f"🔐 Weirdhost 自动登录")
        print(f"{'='*60}")
        
        self.page = self._create_browser()
        
        try:
            # 步骤1: 打开页面
            print(f"\n[1/6] 打开登录页面...")
            self.page.get(LOGIN_URL)
            self.page.wait.doc_loaded()
            time.sleep(2)
            self._save_screenshot("01_login_page")
            
            # 步骤2: 填写邮箱
            print(f"\n[2/6] 填写邮箱...")
            email_input = self.page.ele('@name=username') or self.page.ele('@type=email')
            if email_input:
                email_input.clear()
                email_input.input(email)
                print(f"   ✅ 已输入")
            
            time.sleep(0.5)
            
            # 步骤3: 填写密码
            print(f"\n[3/6] 填写密码...")
            pwd_input = self.page.ele('@name=password') or self.page.ele('@type=password')
            if pwd_input:
                pwd_input.clear()
                pwd_input.input(password)
                print(f"   ✅ 已输入")
            
            time.sleep(0.5)
            
            # 步骤4: 勾选条款
            print(f"\n[4/6] 勾选条款...")
            checkbox = self.page.ele('@type=checkbox')
            if checkbox and not checkbox.states.is_checked:
                checkbox.click()
                print(f"   ✅ 已勾选")
            
            time.sleep(0.5)
            self._save_screenshot("02_form_filled")
            
            # 步骤5: 点击登录
            print(f"\n[5/6] 点击登录...")
            login_btn = (self.page.ele('@tag()=button@@text():로그인') or 
                        self.page.ele('@tag()=button@@text():Login') or
                        self.page.ele('@@tag()=button@@type=submit'))
            if login_btn:
                login_btn.click()
                print(f"   ✅ 已点击")
            
            time.sleep(2)
            self._save_screenshot("03_after_click")
            
            # 步骤6: 验证码
            print(f"\n[6/6] 处理 reCAPTCHA...")
            success = self._handle_recaptcha()
            
            time.sleep(2)
            if "/auth/login" not in self.page.url:
                print(f"\n🎉 登录成功!")
                self._save_screenshot("99_success")
                return True
            
            self._save_screenshot("99_failed")
            return False
                
        except Exception as e:
            print(f"\n❌ 异常: {e}")
            import traceback
            traceback.print_exc()
            self._save_screenshot("99_error")
            return False
        
        finally:
            if self.page:
                self.page.quit()
    
    def _get_recaptcha_frame(self):
        """获取验证码 iframe"""
        for src in ['recaptcha.net/recaptcha/api2/bframe',
                    'google.com/recaptcha/api2/bframe',
                    'recaptcha/api2/bframe']:
            frame = self.page.get_frame(f'@src:{src}')
            if frame:
                return frame
        return None
    
    def _get_audio_url(self, frame) -> Optional[str]:
        """
        获取音频 URL (修复 HTML 转义问题)
        """
        audio_url = None
        
        # 方法1: 下载链接 (最可靠)
        dl_link = frame.ele(".rc-audiochallenge-tdownload-link")
        if dl_link:
            href = dl_link.attr("href")
            if href:
                # 关键修复: 解码 HTML 转义字符 (&amp; -> &)
                audio_url = html.unescape(href)
                print(f"      📎 下载链接: {audio_url[:80]}...")
                return audio_url
        
        # 方法2: audio source
        audio_src = frame.ele("#audio-source")
        if audio_src:
            src = audio_src.attr("src")
            if src:
                audio_url = html.unescape(src)
                print(f"      📎 audio-source: {audio_url[:80]}...")
                return audio_url
        
        # 方法3: audio 标签
        audio_tag = frame.ele("tag:audio")
        if audio_tag:
            src = audio_tag.attr("src")
            if src:
                audio_url = html.unescape(src)
                print(f"      📎 audio tag: {audio_url[:80]}...")
                return audio_url
            
            source = audio_tag.ele("tag:source")
            if source:
                src = source.attr("src")
                if src:
                    audio_url = html.unescape(src)
                    print(f"      📎 source: {audio_url[:80]}...")
                    return audio_url
        
        # 方法4: 从 HTML 正则提取
        try:
            frame_html = frame.html
            if frame_html:
                # 查找音频 URL 模式
                patterns = [
                    r'href="([^"]*recaptcha[^"]*payload[^"]*audio\.mp3[^"]*)"',
                    r'src="([^"]*recaptcha[^"]*payload[^"]*)"',
                    r'(https?://recaptcha\.net/recaptcha/api2/payload/audio\.mp3[^"\'<>\s]*)',
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, frame_html)
                    if matches:
                        audio_url = html.unescape(matches[0])
                        print(f"      📎 正则提取: {audio_url[:80]}...")
                        return audio_url
        except:
            pass
        
        return None
    
    def _handle_recaptcha(self) -> bool:
        """处理语音验证"""
        max_attempts = 10
        
        for attempt in range(max_attempts):
            print(f"\n   🔄 尝试 {attempt + 1}/{max_attempts}")
            
            if "/auth/login" not in self.page.url:
                print(f"   ✅ 已跳转!")
                return True
            
            frame = self._get_recaptcha_frame()
            
            if not frame:
                print(f"   📭 未检测到验证码")
                time.sleep(1.5)
                
                if attempt >= 2 and attempt % 2 == 0:
                    btn = self.page.ele('@tag()=button@@text():로그인') or self.page.ele('@@tag()=button@@type=submit')
                    if btn:
                        btn.click()
                        time.sleep(2)
                continue
            
            print(f"   🎯 检测到 reCAPTCHA!")
            self._save_screenshot(f"cap_{attempt:02d}")
            
            # ===== 切换语音模式 =====
            audio_btn = frame.ele("#recaptcha-audio-button")
            if audio_btn and audio_btn.states.is_displayed:
                print(f"   🔊 切换语音模式...")
                audio_btn.click()
                time.sleep(3)
                self._save_screenshot(f"audio_{attempt:02d}")
            
            # ===== 检查错误 =====
            error_el = frame.ele(".rc-audiochallenge-error-message")
            if error_el and error_el.states.is_displayed:
                error_text = error_el.text
                print(f"   ❌ 错误: {error_text}")
                
                reload_btn = frame.ele("#recaptcha-reload-button")
                if reload_btn:
                    reload_btn.click()
                    time.sleep(2)
                continue
            
            # ===== 获取音频 URL =====
            print(f"   📥 获取音频...")
            audio_url = self._get_audio_url(frame)
            
            if not audio_url:
                print(f"   ⚠️ 无法获取音频 URL")
                
                # 打印调试信息
                print(f"   🔍 调试: 检查 frame 元素...")
                for sel in [".rc-audiochallenge-tdownload-link", "#audio-source", "tag:audio"]:
                    el = frame.ele(sel)
                    if el:
                        print(f"      ✅ {sel}: href={el.attr('href')}, src={el.attr('src')}")
                    else:
                        print(f"      ❌ {sel}: 不存在")
                
                reload_btn = frame.ele("#recaptcha-reload-button")
                if reload_btn:
                    reload_btn.click()
                    time.sleep(2)
                continue
            
            # ===== 下载音频 =====
            print(f"   📥 下载音频...")
            audio_path = self._download_audio(audio_url)
            
            if not audio_path:
                reload_btn = frame.ele("#recaptcha-reload-button")
                if reload_btn:
                    reload_btn.click()
                    time.sleep(2)
                continue
            
            # ===== 语音识别 =====
            print(f"   🎤 Wit.ai 识别...")
            text = self.recognizer.recognize(audio_path)
            
            try:
                os.remove(audio_path)
            except:
                pass
            
            if not text:
                print(f"   ⚠️ 识别失败")
                reload_btn = frame.ele("#recaptcha-reload-button")
                if reload_btn:
                    reload_btn.click()
                    time.sleep(2)
                continue
            
            print(f"   📝 识别: {text}")
            
            # ===== 输入答案 =====
            print(f"   ⌨️ 输入...")
            input_el = frame.ele("#audio-response")
            
            if not input_el:
                continue
            
            input_el.clear()
            time.sleep(0.3)
            
            for char in text:
                input_el.input(char)
                time.sleep(random.uniform(0.05, 0.1))
            
            time.sleep(0.5)
            self._save_screenshot(f"input_{attempt:02d}")
            
            # ===== 验证 =====
            print(f"   🖱️ 验证...")
            verify_btn = frame.ele("#recaptcha-verify-button")
            if verify_btn:
                verify_btn.click()
                time.sleep(3)
            
            self._save_screenshot(f"verify_{attempt:02d}")
            
            if "/auth/login" not in self.page.url:
                print(f"   ✅ 成功!")
                return True
            
            time.sleep(1)
            new_frame = self._get_recaptcha_frame()
            if not new_frame:
                time.sleep(2)
                if "/auth/login" not in self.page.url:
                    return True
        
        return False
    
    def _download_audio(self, url: str) -> Optional[str]:
        """下载音频"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'audio/*,*/*;q=0.8',
                'Referer': 'https://www.google.com/',
            }
            
            print(f"      🔗 URL: {url[:100]}...")
            
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            
            print(f"      ✅ 下载: {len(resp.content)} bytes, Content-Type: {resp.headers.get('Content-Type', 'unknown')}")
            
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
                f.write(resp.content)
                return f.name
                
        except Exception as e:
            print(f"      ❌ 下载错误: {e}")
            return None


def main():
    print("=" * 60)
    print("🚀 Weirdhost 自动登录 (Wit.ai)")
    print("=" * 60)
    
    email = os.environ.get("TEST_EMAIL", "")
    password = os.environ.get("TEST_PASSWORD", "")
    wit_token = os.environ.get("WIT_AI_TOKEN", "")
    
    if not all([email, password, wit_token]):
        print("❌ 缺少环境变量")
        exit(1)
    
    print(f"\n📋 配置:")
    print(f"   📧 邮箱: {email[:3]}***")
    print(f"   🎤 Token: {wit_token[:8]}***")
    
    headless = os.environ.get("HEADLESS", "true").lower() == "true"
    
    login = WeirdhostLogin(headless=headless)
    success = login.login(email, password)
    
    exit(0 if success else 1)


if __name__ == "__main__":
    main()
