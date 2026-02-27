#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Weirdhost 自动登录 - 增强调试版
"""

from DrissionPage import ChromiumPage, ChromiumOptions
import time
import os
import random
import requests
import tempfile
import re
import html
from typing import Optional

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
        try:
            with open(audio_path, 'rb') as f:
                audio_data = f.read()
            
            print(f"      📤 上传 ({len(audio_data)} bytes)...")
            
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
            
            if response.status_code == 200:
                text = response.text.strip()
                lines = text.split('\n')
                
                for line in reversed(lines):
                    try:
                        import json
                        result = json.loads(line)
                        if 'text' in result and result['text']:
                            return self._clean_text(result['text'])
                    except:
                        continue
            return None
        except Exception as e:
            print(f"      ❌ 识别错误: {e}")
            return None
    
    def _clean_text(self, text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r'[^\w\s]', '', text)
        
        word_to_num = {
            'zero': '0', 'oh': '0', 'o': '0',
            'one': '1', 'two': '2', 'three': '3',
            'four': '4', 'five': '5', 'six': '6',
            'seven': '7', 'eight': '8', 'nine': '9',
        }
        
        words = text.split()
        result = [word_to_num.get(w, w) for w in words if w]
        return ' '.join(result)


class WeirdhostLogin:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.page = None
        self.recognizer = WitAiRecognizer(WIT_AI_TOKEN)
    
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
    
    def _save_screenshot(self, name: str):
        if DEBUG and self.page:
            path = f"{SCREENSHOT_DIR}/{name}.png"
            self.page.get_screenshot(path=path)
            print(f"      📸 {name}.png")
    
    def _dump_frame_html(self, frame, filename: str):
        """保存 frame HTML 用于调试"""
        try:
            html_content = frame.html
            path = f"{SCREENSHOT_DIR}/{filename}.html"
            with open(path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            print(f"      📄 保存 HTML: {filename}.html ({len(html_content)} chars)")
        except Exception as e:
            print(f"      ⚠️ 保存 HTML 失败: {e}")
    
    def login(self, email: str, password: str) -> bool:
        print(f"\n{'='*60}")
        print(f"🔐 Weirdhost 自动登录 (调试版)")
        print(f"{'='*60}")
        
        self.page = self._create_browser()
        
        try:
            # 步骤1-5: 填写表单并点击登录
            print(f"\n[1/6] 打开页面...")
            self.page.get(LOGIN_URL)
            self.page.wait.doc_loaded()
            time.sleep(2)
            self._save_screenshot("01_page")
            
            print(f"\n[2/6] 填写邮箱...")
            email_input = self.page.ele('@name=username') or self.page.ele('@type=email')
            if email_input:
                email_input.clear()
                email_input.input(email)
            
            print(f"\n[3/6] 填写密码...")
            pwd_input = self.page.ele('@name=password') or self.page.ele('@type=password')
            if pwd_input:
                pwd_input.clear()
                pwd_input.input(password)
            
            print(f"\n[4/6] 勾选条款...")
            checkbox = self.page.ele('@type=checkbox')
            if checkbox and not checkbox.states.is_checked:
                checkbox.click()
            
            self._save_screenshot("02_filled")
            
            print(f"\n[5/6] 点击登录...")
            login_btn = (self.page.ele('@tag()=button@@text():로그인') or 
                        self.page.ele('@tag()=button@@text():Login') or
                        self.page.ele('@@tag()=button@@type=submit'))
            if login_btn:
                login_btn.click()
            
            time.sleep(2)
            self._save_screenshot("03_clicked")
            
            # 步骤6: 处理验证码
            print(f"\n[6/6] 处理 reCAPTCHA...")
            success = self._handle_recaptcha()
            
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
    
    def _get_recaptcha_frame(self):
        """获取验证码 iframe"""
        for src in ['recaptcha.net/recaptcha/api2/bframe',
                    'google.com/recaptcha/api2/bframe',
                    'recaptcha/api2/bframe']:
            frame = self.page.get_frame(f'@src:{src}')
            if frame:
                return frame
        return None
    
    def _handle_recaptcha(self) -> bool:
        max_attempts = 8
        
        for attempt in range(max_attempts):
            print(f"\n   ========== 尝试 {attempt + 1}/{max_attempts} ==========")
            
            if "/auth/login" not in self.page.url:
                print(f"   ✅ 已跳转!")
                return True
            
            # 获取 bframe
            frame = self._get_recaptcha_frame()
            
            if not frame:
                print(f"   📭 未检测到 reCAPTCHA bframe")
                time.sleep(2)
                continue
            
            print(f"   🎯 找到 reCAPTCHA frame")
            self._save_screenshot(f"attempt_{attempt:02d}_00_found")
            
            # ===== 调试: 保存初始 HTML =====
            self._dump_frame_html(frame, f"attempt_{attempt:02d}_initial")
            
            # ===== 检查当前状态 =====
            print(f"\n   🔍 检查 frame 状态...")
            
            # 检查语音按钮
            audio_btn = frame.ele("#recaptcha-audio-button")
            print(f"      语音按钮 #recaptcha-audio-button: {'存在' if audio_btn else '不存在'}")
            if audio_btn:
                try:
                    displayed = audio_btn.states.is_displayed
                    print(f"      - is_displayed: {displayed}")
                except:
                    print(f"      - is_displayed: 无法获取")
            
            # 检查图片挑战区域
            image_challenge = frame.ele(".rc-imageselect-challenge")
            print(f"      图片挑战 .rc-imageselect-challenge: {'存在' if image_challenge else '不存在'}")
            
            # 检查语音挑战区域
            audio_challenge = frame.ele("#rc-audio")
            print(f"      语音挑战 #rc-audio: {'存在' if audio_challenge else '不存在'}")
            if audio_challenge:
                try:
                    displayed = audio_challenge.states.is_displayed
                    print(f"      - is_displayed: {displayed}")
                except:
                    pass
            
            # 检查错误消息
            error_msg = frame.ele(".rc-audiochallenge-error-message")
            if error_msg:
                print(f"      错误消息: {error_msg.text}")
            
            # ===== 点击语音按钮 =====
            if audio_btn:
                try:
                    displayed = audio_btn.states.is_displayed
                except:
                    displayed = True
                
                if displayed:
                    print(f"\n   🔊 点击语音按钮...")
                    
                    # 尝试多种点击方式
                    try:
                        audio_btn.click()
                        print(f"      click() 完成")
                    except Exception as e:
                        print(f"      click() 失败: {e}")
                        try:
                            audio_btn.click(by_js=True)
                            print(f"      click(by_js=True) 完成")
                        except Exception as e2:
                            print(f"      click(by_js=True) 失败: {e2}")
                    
                    # 等待切换
                    print(f"      等待 4 秒...")
                    time.sleep(4)
                    
                    self._save_screenshot(f"attempt_{attempt:02d}_01_after_audio_click")
                else:
                    print(f"   ⚠️ 语音按钮不可见")
            else:
                print(f"   ⚠️ 语音按钮不存在")
            
            # ===== 重新获取 frame (可能刷新了) =====
            print(f"\n   🔄 重新获取 frame...")
            frame = self._get_recaptcha_frame()
            
            if not frame:
                print(f"   ⚠️ frame 消失了")
                continue
            
            # ===== 调试: 保存点击后 HTML =====
            self._dump_frame_html(frame, f"attempt_{attempt:02d}_after_click")
            
            # ===== 再次检查状态 =====
            print(f"\n   🔍 点击后状态...")
            
            audio_challenge = frame.ele("#rc-audio")
            print(f"      语音挑战 #rc-audio: {'存在' if audio_challenge else '不存在'}")
            
            # 检查各种音频元素
            elements_to_check = [
                ("#audio-source", "音频源"),
                (".rc-audiochallenge-tdownload-link", "下载链接"),
                ("tag:audio", "audio 标签"),
                ("#audio-response", "输入框"),
                ("#recaptcha-verify-button", "验证按钮"),
                (".rc-audiochallenge-error-message", "错误消息"),
                (".rc-doscaptcha-header-text", "被封禁提示"),
                (".rc-audiochallenge-play-button", "播放按钮"),
            ]
            
            for selector, name in elements_to_check:
                el = frame.ele(selector)
                if el:
                    text = el.text[:50] if el.text else ""
                    href = el.attr("href")[:50] if el.attr("href") else ""
                    src = el.attr("src")[:50] if el.attr("src") else ""
                    print(f"      ✅ {name}: text='{text}', href='{href}', src='{src}'")
                else:
                    print(f"      ❌ {name}: 不存在")
            
            # ===== 检查是否被封禁 =====
            doscaptcha = frame.ele(".rc-doscaptcha-header-text")
            if doscaptcha:
                print(f"\n   🚫 被检测到自动化! 消息: {doscaptcha.text}")
                print(f"   等待 10 秒后继续...")
                time.sleep(10)
                continue
            
            # ===== 检查错误消息 =====
            error_el = frame.ele(".rc-audiochallenge-error-message")
            if error_el and error_el.text:
                print(f"\n   ❌ 错误: {error_el.text}")
                
                reload_btn = frame.ele("#recaptcha-reload-button")
                if reload_btn:
                    print(f"   🔄 点击刷新...")
                    reload_btn.click()
                    time.sleep(3)
                continue
            
            # ===== 获取音频 URL =====
            print(f"\n   📥 获取音频 URL...")
            audio_url = None
            
            # 方法1: 下载链接
            dl = frame.ele(".rc-audiochallenge-tdownload-link")
            if dl:
                href = dl.attr("href")
                if href:
                    audio_url = html.unescape(href)
                    print(f"      ✅ 下载链接: {audio_url[:70]}...")
            
            # 方法2: audio source
            if not audio_url:
                src_el = frame.ele("#audio-source")
                if src_el:
                    src = src_el.attr("src")
                    if src:
                        audio_url = html.unescape(src)
                        print(f"      ✅ audio-source: {audio_url[:70]}...")
            
            # 方法3: audio 标签
            if not audio_url:
                audio_tag = frame.ele("tag:audio")
                if audio_tag:
                    src = audio_tag.attr("src")
                    if src:
                        audio_url = html.unescape(src)
                        print(f"      ✅ audio tag: {audio_url[:70]}...")
            
            # 方法4: 正则从 HTML 提取
            if not audio_url:
                try:
                    frame_html = frame.html
                    patterns = [
                        r'href="([^"]*payload[^"]*audio\.mp3[^"]*)"',
                        r'src="([^"]*payload[^"]*)"',
                    ]
                    for p in patterns:
                        m = re.search(p, frame_html)
                        if m:
                            audio_url = html.unescape(m.group(1))
                            print(f"      ✅ 正则提取: {audio_url[:70]}...")
                            break
                except:
                    pass
            
            if not audio_url:
                print(f"   ⚠️ 无法获取音频 URL")
                
                # 尝试点击播放按钮
                play_btn = frame.ele(".rc-audiochallenge-play-button")
                if play_btn:
                    print(f"   🎵 尝试点击播放按钮...")
                    play_btn.click()
                    time.sleep(2)
                
                # 刷新
                reload_btn = frame.ele("#recaptcha-reload-button")
                if reload_btn:
                    print(f"   🔄 刷新...")
                    reload_btn.click()
                    time.sleep(3)
                continue
            
            # ===== 下载音频 =====
            print(f"\n   📥 下载音频...")
            audio_path = self._download_audio(audio_url)
            
            if not audio_path:
                continue
            
            # ===== 语音识别 =====
            print(f"\n   🎤 Wit.ai 识别...")
            text = self.recognizer.recognize(audio_path)
            
            try:
                os.remove(audio_path)
            except:
                pass
            
            if not text:
                print(f"   ⚠️ 识别失败")
                continue
            
            print(f"   📝 识别结果: {text}")
            
            # ===== 输入答案 =====
            print(f"\n   ⌨️ 输入答案...")
            input_el = frame.ele("#audio-response")
            
            if not input_el:
                print(f"   ⚠️ 输入框不存在")
                continue
            
            input_el.clear()
            time.sleep(0.3)
            
            for char in text:
                input_el.input(char)
                time.sleep(random.uniform(0.05, 0.1))
            
            self._save_screenshot(f"attempt_{attempt:02d}_02_input")
            
            # ===== 验证 =====
            print(f"\n   🖱️ 点击验证...")
            verify_btn = frame.ele("#recaptcha-verify-button")
            if verify_btn:
                verify_btn.click()
                time.sleep(4)
            
            self._save_screenshot(f"attempt_{attempt:02d}_03_verify")
            
            if "/auth/login" not in self.page.url:
                print(f"   ✅ 成功!")
                return True
        
        return False
    
    def _download_audio(self, url: str) -> Optional[str]:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.google.com/',
            }
            
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            
            print(f"      ✅ {len(resp.content)} bytes")
            
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
                f.write(resp.content)
                return f.name
        except Exception as e:
            print(f"      ❌ 下载失败: {e}")
            return None


def main():
    print("=" * 60)
    print("🚀 Weirdhost 登录 (调试版)")
    print("=" * 60)
    
    email = os.environ.get("TEST_EMAIL", "")
    password = os.environ.get("TEST_PASSWORD", "")
    wit_token = os.environ.get("WIT_AI_TOKEN", "")
    
    if not all([email, password, wit_token]):
        print("❌ 缺少环境变量")
        exit(1)
    
    print(f"\n📋 配置: {email[:3]}***, Token: {wit_token[:8]}***")
    
    headless = os.environ.get("HEADLESS", "true").lower() == "true"
    
    login = WeirdhostLogin(headless=headless)
    success = login.login(email, password)
    
    exit(0 if success else 1)


if __name__ == "__main__":
    main()
