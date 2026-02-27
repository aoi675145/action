#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scripts/Weirdhost/weirdhost_login.py

"""
Weirdhost 自动登录 + reCAPTCHA 图片验证 (优化版)
"""

from ultralytics import YOLO
from DrissionPage import ChromiumPage, ChromiumOptions
from PIL import Image
import io
import time
import os
import random
from typing import Set, List, Optional

# ============== 配置 ==============
DEBUG = True
SCREENSHOT_DIR = "debug_screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

LOGIN_URL = "https://hub.weirdhost.xyz/auth/login"

# 类别映射表 (扩展)
CATEGORY_MAPPING = {
    "摩托": ["motorcycle"], "motorcycle": ["motorcycle"],
    "公交": ["bus"], "巴士": ["bus"], "bus": ["bus"],
    "自行": ["bicycle"], "bicycle": ["bicycle"],
    "红绿灯": ["traffic light"], "traffic light": ["traffic light"],
    "消防": ["fire hydrant"], "hydrant": ["fire hydrant"],
    "汽车": ["car", "truck"], "轿车": ["car"], "car": ["car", "truck"],
    "船": ["boat"], "boat": ["boat"],
    "卡车": ["truck"], "truck": ["truck"],
}

UNSUPPORTED_KEYWORDS = [
    "crosswalk", "人行横道", "斑马线",
    "stair", "楼梯", "bridge", "桥",
    "chimney", "烟囱", "palm", "棕榈",
    "mountain", "山", "parking meter", "停车计时器"
]


def crop_image_from_bytes(image_bytes: bytes, crop_box) -> Optional[bytes]:
    """裁剪图片"""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        cropped = img.crop(crop_box)
        output = io.BytesIO()
        cropped.save(output, format='JPEG', quality=95)
        return output.getvalue()
    except Exception as e:
        print(f"⚠️ 裁剪出错: {e}")
        return None


def get_target_labels(text: str) -> List[str]:
    """根据题目文本获取目标标签"""
    text_lower = text.lower()
    for keyword in UNSUPPORTED_KEYWORDS:
        if keyword in text_lower:
            return []
    for keyword, labels in CATEGORY_MAPPING.items():
        if keyword in text_lower:
            return labels
    return []


class WeirdhostLogin:
    """Weirdhost 登录器"""
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.model = None
        self.page = None
        self._load_model()
    
    def _load_model(self):
        """加载 YOLO 模型"""
        print("🚀 正在加载 YOLO 模型...")
        self.model = YOLO("yolo11x.pt")
        print("✅ YOLO11x 加载完成")
    
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
            print("\n[1/5] 打开登录页面...")
            self.page.get(LOGIN_URL)
            self.page.wait.doc_loaded()
            time.sleep(2)
            
            if DEBUG:
                self.page.get_screenshot(path=f"{SCREENSHOT_DIR}/01_login_page.png")
            
            print("[2/5] 填写邮箱...")
            email_input = self.page.ele('@name=username')
            if email_input:
                email_input.input(email)
                print("   ✅ 已输入邮箱")
            else:
                raise Exception("未找到邮箱输入框")
            
            time.sleep(0.3)
            
            print("[3/5] 填写密码...")
            password_input = self.page.ele('@name=password')
            if password_input:
                password_input.input(password)
                print("   ✅ 已输入密码")
            else:
                raise Exception("未找到密码输入框")
            
            time.sleep(0.3)
            
            print("[4/5] 勾选条款...")
            checkbox = self.page.ele('@type=checkbox')
            if checkbox:
                checkbox.click()
                print("   ✅ 已勾选")
            
            time.sleep(0.5)
            
            if DEBUG:
                self.page.get_screenshot(path=f"{SCREENSHOT_DIR}/02_filled.png")
            
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
            
            success = self._handle_recaptcha()
            
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
            if DEBUG:
                self.page.get_screenshot(path=f"{SCREENSHOT_DIR}/error.png")
            return False
        
        finally:
            if self.page:
                self.page.quit()
    
    def _detect_targets(self, image_bytes: bytes, target_labels: List[str], 
                        grid_side: int, conf_threshold: float = 0.20) -> Set[int]:
        """
        使用 YOLO 检测目标，返回需要点击的格子索引
        """
        img_obj = Image.open(io.BytesIO(image_bytes))
        results = self.model(img_obj, verbose=False)
        
        img_w, img_h = img_obj.size
        tile_w = img_w / grid_side
        tile_h = img_h / grid_side
        
        click_indices: Set[int] = set()
        
        for r in results:
            for box in r.boxes:
                cls_name = self.model.names[int(box.cls[0])]
                conf = float(box.conf[0])
                
                if cls_name in target_labels and conf > conf_threshold:
                    bx1, by1, bx2, by2 = box.xyxy[0].tolist()
                    
                    print(f"      🔍 {cls_name} conf={conf:.2f} box=({bx1:.0f},{by1:.0f},{bx2:.0f},{by2:.0f})")
                    
                    for row in range(grid_side):
                        for col in range(grid_side):
                            tx1 = col * tile_w
                            ty1 = row * tile_h
                            tx2 = (col + 1) * tile_w
                            ty2 = (row + 1) * tile_h
                            
                            inter_x1 = max(bx1, tx1)
                            inter_y1 = max(by1, ty1)
                            inter_x2 = min(bx2, tx2)
                            inter_y2 = min(by2, ty2)
                            
                            if inter_x2 > inter_x1 and inter_y2 > inter_y1:
                                inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
                                tile_area = tile_w * tile_h
                                overlap = inter_area / tile_area
                                
                                if overlap > 0.03:  # 降低重叠阈值
                                    idx = row * grid_side + col
                                    click_indices.add(idx)
        
        return click_indices
    
    def _capture_challenge_image(self, recaptcha_frame, target_ele, try_num: int) -> Optional[bytes]:
        """截取验证码图片区域"""
        try:
            dpr = self.page.run_js("return window.devicePixelRatio;") or 1
            iframe_rect = recaptcha_frame.frame_ele.rect
            ele_rect = target_ele.rect
            
            x1 = int((iframe_rect.location[0] + ele_rect.location[0]) * dpr)
            y1 = int((iframe_rect.location[1] + ele_rect.location[1]) * dpr)
            x2 = int(x1 + (ele_rect.size[0] * dpr))
            y2 = int(y1 + (ele_rect.size[1] * dpr))
            
            full_screenshot = self.page.get_screenshot(as_bytes=True)
            
            if DEBUG:
                with open(f"{SCREENSHOT_DIR}/full_{try_num}.png", "wb") as f:
                    f.write(full_screenshot)
            
            image_cp = crop_image_from_bytes(full_screenshot, (x1, y1, x2, y2))
            
            if DEBUG and image_cp:
                with open(f"{SCREENSHOT_DIR}/crop_{try_num}.jpg", "wb") as f:
                    f.write(image_cp)
            
            return image_cp
        except Exception as e:
            print(f"   ⚠️ 截图失败: {e}")
            return None
    
    def _wait_for_new_images(self, recaptcha_frame, wait_time: float = 3.5):
        """等待新图片加载完成"""
        print(f"   ⏳ 等待新图片加载 ({wait_time}s)...")
        time.sleep(wait_time)
        
        # 额外检查是否还有加载动画
        for _ in range(5):
            try:
                # 检查是否有正在加载的图块
                loading = recaptcha_frame.ele("@class:rc-imageselect-dynamic-selected")
                if loading:
                    time.sleep(0.5)
                else:
                    break
            except:
                break
    
    def _handle_recaptcha(self) -> bool:
        """处理 reCAPTCHA"""
        print("\n🔍 检测 reCAPTCHA...")
        
        max_retries = 50  # 增加重试次数
        current_try = 0
        clicked_history: Set[int] = set()
        last_category = None
        consecutive_empty = 0  # 连续空检测计数
        
        while current_try < max_retries:
            current_try += 1
            print(f"\n🔄 --- 第 {current_try} 次循环 ---")
            
            # 检查是否已跳转
            if "/auth/login" not in self.page.url:
                print("✅ 页面已跳转!")
                return True
            
            # 查找 reCAPTCHA 弹窗
            recaptcha_frame = self.page.get_frame('@src:recaptcha.net/recaptcha/api2/bframe')
            if not recaptcha_frame:
                recaptcha_frame = self.page.get_frame('@src:recaptcha/api2/bframe')
            if not recaptcha_frame:
                recaptcha_frame = self.page.get_frame('@src:recaptcha/enterprise/bframe')
            
            if not recaptcha_frame:
                print("   📭 未检测到验证弹窗")
                time.sleep(1)
                
                if "/auth/login" not in self.page.url:
                    return True
                
                if current_try > 3:
                    login_btn = self.page.ele('@tag()=button@@text():로그인')
                    if login_btn:
                        login_btn.click()
                        time.sleep(2)
                continue
            
            print("   🎯 检测到 reCAPTCHA 弹窗!")
            
            # 等待图片加载
            target_ele = recaptcha_frame.wait.ele_displayed(
                "@class=rc-imageselect-challenge", timeout=5
            )
            if not target_ele:
                print("   ⏳ 图片未加载...")
                time.sleep(1)
                continue
            
            # 获取题目
            text_str = ""
            try:
                desc_ele = recaptcha_frame.ele("@class=rc-imageselect-desc-no-canonical")
                if desc_ele:
                    text_str = desc_ele.text.lower()
            except:
                pass
            
            if not text_str:
                try:
                    desc_ele = recaptcha_frame.ele("@class=rc-imageselect-desc")
                    if desc_ele:
                        text_str = desc_ele.text.lower()
                except:
                    pass
            
            print(f"   📝 题目: {text_str}")
            
            # 获取目标标签
            target_labels = get_target_labels(text_str)
            
            # 检测题目变化，清空历史
            if str(target_labels) != str(last_category):
                clicked_history.clear()
                consecutive_empty = 0
                last_category = target_labels
            
            # 获取网格信息
            tiles_elements = recaptcha_frame.eles(".rc-image-tile-target")
            grid_side = 4 if len(tiles_elements) == 16 else 3
            
            # 检测是否为动态模式
            dynamic_keywords = ["直到", "until", "once there are none", "没有新图片", "如果没有", "none left"]
            is_dynamic = any(kw in text_str for kw in dynamic_keywords)
            
            print(f"   📊 网格: {grid_side}x{grid_side}, 动态: {is_dynamic}, 图块数: {len(tiles_elements)}")
            
            # 不支持的类别 -> 刷新
            if not target_labels:
                print("   ⚠️ 不支持的类别，刷新!")
                self._click_reload(recaptcha_frame)
                consecutive_empty = 0
                continue
            
            print(f"   🎯 目标: {target_labels}")
            
            # 等待图片稳定
            time.sleep(0.8)
            
            # 截图
            image_cp = self._capture_challenge_image(recaptcha_frame, target_ele, current_try)
            if not image_cp:
                continue
            
            # YOLO 检测 - 动态模式使用更低的置信度阈值
            conf_threshold = 0.15 if is_dynamic else 0.20
            click_indices = self._detect_targets(image_cp, target_labels, grid_side, conf_threshold)
            
            sorted_indices = sorted(list(click_indices))
            print(f"   🎯 检测到: {sorted_indices}")
            
            # 非动态模式：过滤已点击的
            if not is_dynamic:
                sorted_indices = [i for i in sorted_indices if i not in clicked_history]
                print(f"   🎯 需点击(排除已点): {sorted_indices}")
            
            # 点击图块
            if sorted_indices:
                consecutive_empty = 0
                print(f"   🖱️ 点击 {len(sorted_indices)} 个图块...")
                
                click_order = sorted_indices.copy()
                if len(click_order) > 2:
                    random.shuffle(click_order)
                
                for idx in click_order:
                    if idx < len(tiles_elements):
                        tiles_elements[idx].click()
                        if not is_dynamic:
                            clicked_history.add(idx)
                        time.sleep(random.uniform(0.15, 0.35))
                
                # 动态模式：等待新图片加载
                if is_dynamic:
                    self._wait_for_new_images(recaptcha_frame, wait_time=4.0)
                    continue
            else:
                consecutive_empty += 1
                print(f"   🤷 未发现目标 (连续{consecutive_empty}次)")
            
            # 检查错误消息
            error_msg = recaptcha_frame.ele("@class:rc-imageselect-error-select-more")
            has_error = error_msg and error_msg.states.is_displayed
            
            # 也检查 "Please also check the new images"
            check_new_msg = recaptcha_frame.ele("@class:rc-imageselect-error-dynamic-more")
            has_check_new = check_new_msg and check_new_msg.states.is_displayed
            
            if has_check_new:
                print("   ⚠️ 提示: 请检查新图片")
                # 重新扫描而不是刷新
                time.sleep(1.5)
                continue
            
            # 动态模式且连续多次空检测 -> 点击验证
            if is_dynamic and consecutive_empty >= 1:
                verify_btn = recaptcha_frame.ele("#recaptcha-verify-button")
                if verify_btn and verify_btn.states.is_enabled:
                    print(f"   🖱️ 尝试验证...")
                    verify_btn.click()
                    time.sleep(2)
                    
                    # 检查是否有错误
                    error_msg = recaptcha_frame.ele("@class:rc-imageselect-error-select-more")
                    check_new_msg = recaptcha_frame.ele("@class:rc-imageselect-error-dynamic-more")
                    
                    if (error_msg and error_msg.states.is_displayed) or \
                       (check_new_msg and check_new_msg.states.is_displayed):
                        print("   ❌ 验证失败，继续扫描...")
                        
                        # 连续3次以上空检测才刷新
                        if consecutive_empty >= 3:
                            print("   ⚠️ 连续空检测，刷新题目...")
                            self._click_reload(recaptcha_frame)
                            consecutive_empty = 0
                        else:
                            # 等待更长时间再重试
                            time.sleep(2)
                    continue
            
            # 非动态模式：直接点击验证/下一题
            if not is_dynamic:
                verify_btn = recaptcha_frame.ele("#recaptcha-verify-button")
                if verify_btn and verify_btn.states.is_enabled:
                    btn_text = verify_btn.text
                    print(f"   🖱️ 点击: {btn_text}")
                    verify_btn.click()
                    time.sleep(1.5)
                    
                    # 检查错误
                    error_msg = recaptcha_frame.ele("@class:rc-imageselect-error-select-more")
                    if error_msg and error_msg.states.is_displayed:
                        print("   ❌ 需要选择更多...")
                        if not sorted_indices:
                            print("   ⚠️ 死局! 刷新...")
                            self._click_reload(recaptcha_frame)
                    
                    time.sleep(1)
        
        return False
    
    def _click_reload(self, frame):
        """刷新验证码"""
        try:
            reload_btn = frame.ele("#recaptcha-reload-button")
            if reload_btn:
                reload_btn.click()
                print("   🔄 已刷新")
                time.sleep(2.5)
        except Exception as e:
            print(f"   ⚠️ 刷新失败: {e}")


def main():
    print("=" * 60)
    print("🚀 Weirdhost 自动登录 (优化版)")
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
