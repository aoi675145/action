# requirements.txt



#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Weirdhost 自动登录 - 支持代理
"""

from DrissionPage import ChromiumPage, ChromiumOptions
import time
import os
import random
import requests
import tempfile
import html
import sys
from typing import Optional

sys.stdout.reconfigure(line_buffering=True)

SCREENSHOT_DIR = "debug_screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

LOGIN_URL = "https://hub.weirdhost.xyz/auth/login"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class RecaptchaSolver:
    """reCAPTCHA 音频验证破解器"""
    
    def __init__(self, page, proxy=None):
        self.page = page
        self.proxy = proxy
    
    def get_bframe(self):
        """获取 reCAPTCHA bframe"""
        for src in ['recaptcha.net/recaptcha/api2/bframe',
                    'google.com/recaptcha/api2/bframe',
                    'recaptcha/api2/bframe']:
            frame = self.page.get_frame(f'@src:{src}')
            if frame:
                return frame
        return None
    
    def check_blocked(self, iframe_ele) -> bool:
        """检查是否被封锁"""
        try:
            # 检查 "Try again later" 消息
            blocked_msg = iframe_ele.ele('css:.rc-doscaptcha-header-text', timeout=2)
            if blocked_msg and 'try again later' in blocked_msg.text.lower():
                log("   ⛔ IP 被 Google 封锁!")
                return True
            
            # 检查错误消息
            err_msg = iframe_ele.ele('css:.rc-audiochallenge-error-message')
            if err_msg and err_msg.states.is_displayed:
                log(f"   ⛔ 被拦截: {err_msg.text}")
                return True
            
            return False
        except:
            return False
    
    def get_audio_source(self, iframe_ele) -> Optional[str]:
        """获取音频下载链接"""
        try:
            # 先检查是否被封锁
            if self.check_blocked(iframe_ele):
                return None
            
            # 方法1: 下载链接
            download_link = iframe_ele.ele('css:.rc-audiochallenge-tdownload-link', timeout=5)
            if download_link:
                href = download_link.attr('href')
                if href:
                    log(f"   📎 找到下载链接")
                    return html.unescape(href)
            
            # 方法2: audio 标签
            audio_tag = iframe_ele.ele('css:#audio-source', timeout=3)
            if audio_tag:
                src = audio_tag.attr('src')
                if src:
                    log(f"   📎 找到 audio src")
                    return html.unescape(src)
            
            return None
        except Exception as e:
            log(f"   ⚠️ 获取音频失败: {e}")
            return None
    
    def download_audio(self, url: str) -> Optional[str]:
        """下载音频"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.google.com/',
            }
            
            proxies = None
            if self.proxy:
                proxies = {
                    'http': self.proxy,
                    'https': self.proxy
                }
                log(f"   🔗 使用代理下载")
            
            r = requests.get(url, headers=headers, timeout=30, proxies=proxies)
            r.raise_for_status()
            
            log(f"   📥 下载: {len(r.content)} bytes")
            
            mp3_path = tempfile.mktemp(suffix='.mp3')
            with open(mp3_path, 'wb') as f:
                f.write(r.content)
            return mp3_path
                
        except Exception as e:
            log(f"   ❌ 下载失败: {e}")
            return None
    
    def recognize_audio(self, mp3_path: str) -> Optional[str]:
        """Google 语音识别"""
        try:
            import speech_recognition as sr
            from pydub import AudioSegment
            
            log("   🔄 转换 MP3 -> WAV...")
            wav_path = mp3_path.replace('.mp3', '.wav')
            sound = AudioSegment.from_mp3(mp3_path)
            sound.export(wav_path, format="wav")
            
            log("   🎤 Google 语音识别...")
            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                audio_data = recognizer.record(source)
                text = recognizer.recognize_google(audio_data)
            
            try:
                os.remove(wav_path)
            except:
                pass
            
            return text
            
        except Exception as e:
            log(f"   ❌ 识别失败: {e}")
            return None
    
    def solve(self, max_attempts: int = 5) -> bool:
        """解决 reCAPTCHA"""
        log("🎧 启动音频破解...")
        
        for attempt in range(max_attempts):
            log(f"\n--- 尝试 {attempt + 1}/{max_attempts} ---")
            
            if "/auth/login" not in self.page.url:
                log("✅ 已跳转!")
                return True
            
            iframe_ele = self.get_bframe()
            if not iframe_ele:
                log("   📭 未检测到验证码弹窗，等待...")
                time.sleep(3)
                continue
            
            log("   🎯 找到 reCAPTCHA")
            
            # 截图
            try:
                self.page.get_screenshot(path=f"{SCREENSHOT_DIR}/captcha_{attempt}.png")
            except:
                pass
            
            # 检查是否被封锁
            if self.check_blocked(iframe_ele):
                log("   ⛔ IP 被封锁，需要更换代理!")
                return False
            
            # 检查是否已经在音频模式
            audio_response = iframe_ele.ele('css:#audio-response', timeout=2)
            if not audio_response:
                # 点击音频按钮
                audio_btn = iframe_ele.ele('css:#recaptcha-audio-button', timeout=3)
                if audio_btn and audio_btn.states.is_displayed:
                    log("   🖱️ 点击音频按钮...")
                    audio_btn.click()
                    time.sleep(random.uniform(2, 4))
                    
                    # 再次检查封锁
                    if self.check_blocked(iframe_ele):
                        log("   ⛔ 切换音频后被封锁!")
                        return False
            
            # 获取音频链接
            src = self.get_audio_source(iframe_ele)
            
            if not src:
                log("   ⚠️ 无音频链接，刷新...")
                reload_btn = iframe_ele.ele('css:#recaptcha-reload-button', timeout=2)
                if reload_btn:
                    reload_btn.click()
                    time.sleep(3)
                continue
            
            # 下载
            mp3_path = self.download_audio(src)
            if not mp3_path:
                continue
            
            # 识别
            key_text = self.recognize_audio(mp3_path)
            
            try:
                os.remove(mp3_path)
            except:
                pass
            
            if not key_text:
                log("   ❌ 识别失败，刷新...")
                reload_btn = iframe_ele.ele('css:#recaptcha-reload-button')
                if reload_btn:
                    reload_btn.click()
                    time.sleep(3)
                continue
            
            log(f"   🗣️ 识别结果: [{key_text}]")
            
            # 输入
            input_box = iframe_ele.ele('css:#audio-response')
            if not input_box:
                log("   ❌ 未找到输入框")
                continue
            
            input_box.click()
            time.sleep(0.3)
            
            for char in key_text:
                input_box.input(char, clear=False)
                time.sleep(random.uniform(0.05, 0.1))
            
            time.sleep(0.5)
            
            # 提交
            verify_btn = iframe_ele.ele('css:#recaptcha-verify-button')
            if verify_btn:
                log("   🚀 提交...")
                verify_btn.click()
                time.sleep(4)
            
            if "/auth/login" not in self.page.url:
                log("✅ 验证通过!")
                return True
        
        return False


def create_browser(proxy_socks5: str = None) -> ChromiumPage:
    """创建浏览器"""
    log("🌐 启动 Chrome...")
    
    co = ChromiumOptions()
    co.auto_port()
    co.headless()
    
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-dev-shm-usage')
    co.set_argument('--disable-gpu')
    co.set_argument('--disable-software-rasterizer')
    co.set_argument('--window-size=1280,900')
    co.set_argument('--disable-blink-features=AutomationControlled')
    
    # 设置代理
    if proxy_socks5:
        # 从 socks5://127.0.0.1:10808 提取
        proxy_addr = proxy_socks5.replace('socks5://', '').replace('socks://', '')
        co.set_argument(f'--proxy-server=socks5://{proxy_addr}')
        log(f"   🔗 代理: socks5://{proxy_addr}")
    
    co.set_timeouts(base=30, page_load=60, script=30)
    
    for path in ['/usr/bin/google-chrome', '/usr/bin/chromium-browser', '/usr/bin/chromium']:
        if os.path.exists(path):
            co.set_browser_path(path)
            log(f"   Chrome: {path}")
            break
    
    co.set_user_agent(
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
    
    page = ChromiumPage(co)
    log("   ✅ Chrome 已启动")
    return page


def main():
    log("=" * 50)
    log("🚀 Weirdhost 自动登录")
    log("=" * 50)
    
    email = os.environ.get("TEST_EMAIL", "")
    password = os.environ.get("TEST_PASSWORD", "")
    proxy_socks5 = os.environ.get("PROXY_SOCKS5", "")
    
    if not all([email, password]):
        log("❌ 缺少 TEST_EMAIL 或 TEST_PASSWORD")
        sys.exit(1)
    
    log(f"📧 邮箱: {email[:3]}***")
    if proxy_socks5:
        log(f"🔗 代理: {proxy_socks5}")
    else:
        log("⚠️ 未配置代理，可能被 Google 封锁!")
    
    start_time = time.time()
    page = None
    
    try:
        page = create_browser(proxy_socks5)
        
        # 测试代理
        if proxy_socks5:
            log("\n[0/5] 测试代理...")
            page.get('https://api.ipify.org')
            ip = page.ele('tag:body').text.strip()
            log(f"   当前 IP: {ip}")
        
        # 打开页面
        log("\n[1/5] 打开登录页...")
        page.get(LOGIN_URL)
        log(f"   URL: {page.url}")
        
        page.wait.doc_loaded(timeout=30)
        time.sleep(2)
        
        page.get_screenshot(path=f"{SCREENSHOT_DIR}/01_loaded.png")
        log("   ✅ 页面已加载")
        
        # 填写邮箱
        log("\n[2/5] 填写邮箱...")
        email_input = page.ele('@name=username', timeout=10)
        if email_input:
            email_input.clear()
            email_input.input(email)
            log("   ✅ 邮箱已填写")
        else:
            log("   ❌ 未找到邮箱输入框")
        
        # 填写密码
        log("\n[3/5] 填写密码...")
        pwd_input = page.ele('@name=password', timeout=5)
        if pwd_input:
            pwd_input.clear()
            pwd_input.input(password)
            log("   ✅ 密码已填写")
        else:
            log("   ❌ 未找到密码输入框")
        
        # 勾选条款
        log("\n[4/5] 勾选条款...")
        checkbox = page.ele('@type=checkbox', timeout=5)
        if checkbox:
            if not checkbox.states.is_checked:
                checkbox.click()
            log("   ✅ 条款已勾选")
        
        page.get_screenshot(path=f"{SCREENSHOT_DIR}/02_filled.png")
        
        # 点击登录按钮 - 修复选择器
        log("\n[5/5] 点击登录...")
        login_btn = None
        
        # 尝试多种选择器
        selectors = [
            'css:button.jOimeR',                    # class 名
            'css:button[color="red"]',              # color 属性
            '@tag()=button@@text():로그인',          # 韩文
            '@tag()=button@@text():Login',          # 英文
            'css:button span:contains(로그인)',     # span 内文字
            'xpath://button[contains(@class, "Button__ButtonStyle")]',  # 包含 class
        ]
        
        for sel in selectors:
            try:
                btn = page.ele(sel, timeout=2)
                if btn and btn.states.is_displayed:
                    login_btn = btn
                    log(f"   找到按钮: {sel}")
                    break
            except:
                continue
        
        if login_btn:
            login_btn.click()
            log("   ✅ 已点击登录")
        else:
            # 备用方案：用 JS 点击
            log("   ⚠️ 尝试 JS 点击...")
            page.run_js('document.querySelector("button[color=red]")?.click()')
        
        time.sleep(3)
        page.get_screenshot(path=f"{SCREENSHOT_DIR}/03_clicked.png")
        
        # 处理验证码
        log("\n[*] 检查 reCAPTCHA...")
        
        # 转换代理格式给 requests 用
        requests_proxy = None
        if proxy_socks5:
            requests_proxy = proxy_socks5
        
        solver = RecaptchaSolver(page, proxy=requests_proxy)
        result = solver.solve(max_attempts=5)
        
        if not result:
            log("⚠️ 验证码处理失败")
        
        # 检查结果
        time.sleep(2)
        final_url = page.url
        log(f"\n📍 最终URL: {final_url}")
        
        page.get_screenshot(path=f"{SCREENSHOT_DIR}/04_final.png")
        
        elapsed = time.time() - start_time
        log(f"⏱️ 耗时: {elapsed:.1f}秒")
        
        if "/auth/login" not in final_url:
            log("\n🎉 登录成功!")
            return True
        else:
            log("\n❌ 登录失败")
            return False
            
    except Exception as e:
        log(f"\n❌ 异常: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        if page:
            try:
                page.quit()
                log("🔚 浏览器已关闭")
            except:
                pass


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
