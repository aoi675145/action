#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ReCAPTCHA v2 本地 AI 解决器 (DrissionPage 版)
适配 GitHub Actions headless 环境
"""

from ultralytics import YOLO
from DrissionPage import ChromiumPage, ChromiumOptions
from DrissionPage import errors as Derrors
from PIL import Image
import numpy as np
import cv2
import io
import time
import os
import random
from typing import Optional, Set, List, Tuple

# ============== 配置 ==============
DEBUG = True
SCREENSHOT_DIR = "debug_screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# 类别映射表 (扩展版)
CATEGORY_MAPPING = {
    # 中文
    "摩托": ["motorcycle"],
    "公交": ["bus"], "巴士": ["bus"],
    "自行": ["bicycle"],
    "红绿灯": ["traffic light"],
    "消防": ["fire hydrant"],
    "汽车": ["car", "truck"], "轿车": ["car"],
    "船": ["boat"],
    "出租车": ["car"],  # taxi 通常识别为 car
    "卡车": ["truck"],
    # 英文
    "motorcycle": ["motorcycle"],
    "bus": ["bus"],
    "bicycle": ["bicycle"],
    "traffic light": ["traffic light"],
    "hydrant": ["fire hydrant"],
    "car": ["car", "truck"],
    "boat": ["boat"],
    "truck": ["truck"],
    "taxi": ["car"],
}

# 不支持的类别 (YOLO 无法识别，需要刷新)
UNSUPPORTED_CATEGORIES = [
    "crosswalk", "人行横道", "斑马线",
    "stair", "楼梯",
    "bridge", "桥",
    "chimney", "烟囱",
    "palm", "棕榈",
    "mountain", "山",
    "parking meter", "停车"
]


def crop_image_from_bytes(image_bytes: bytes, crop_box: Tuple[int, int, int, int]) -> Optional[bytes]:
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


def preprocess_image(img: Image.Image) -> Image.Image:
    """图像预处理增强"""
    img_np = np.array(img)
    if len(img_np.shape) == 3 and img_np.shape[2] == 3:
        img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
    else:
        img_bgr = img_np
    
    # 轻度去噪
    img_denoised = cv2.fastNlMeansDenoisingColored(img_bgr, None, 3, 3, 7, 21)
    
    # CLAHE 增强对比度
    lab = cv2.cvtColor(img_denoised, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_enhanced = clahe.apply(l)
    lab_enhanced = cv2.merge([l_enhanced, a, b])
    img_enhanced = cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2BGR)
    
    # 转回 RGB
    img_rgb = cv2.cvtColor(img_enhanced, cv2.COLOR_BGR2RGB)
    return Image.fromarray(img_rgb)


def get_target_labels(text: str) -> List[str]:
    """根据题目文本获取目标标签"""
    text_lower = text.lower()
    
    # 检查是否是不支持的类别
    for unsupported in UNSUPPORTED_CATEGORIES:
        if unsupported in text_lower:
            return []
    
    # 匹配支持的类别
    for keyword, labels in CATEGORY_MAPPING.items():
        if keyword in text_lower:
            return labels
    
    return []


class RecaptchaSolver:
    """ReCAPTCHA v2 解决器"""
    
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
        """创建浏览器实例"""
        co = ChromiumOptions()
        co.auto_port()
        
        if self.headless:
            co.headless()
        
        # 反检测设置
        co.set_argument('--no-sandbox')
        co.set_argument('--disable-dev-shm-usage')
        co.set_argument('--disable-blink-features=AutomationControlled')
        co.set_argument('--disable-infobars')
        co.set_argument('--window-size=1280,800')
        
        # 设置 User-Agent
        co.set_user_agent(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )
        
        return ChromiumPage(co)
    
    def solve(self, url: str, timeout: int = 120) -> bool:
        """
        解决页面上的 reCAPTCHA
        
        :param url: 目标页面 URL
        :param timeout: 超时时间（秒）
        :return: 是否成功
        """
        print(f"🌐 正在打开: {url}")
        
        self.page = self._create_browser()
        self.page.get(url)
        self.page.wait.doc_loaded()
        
        try:
            return self._solve_challenge(timeout)
        finally:
            if self.page:
                self.page.quit()
    
    def _solve_challenge(self, timeout: int) -> bool:
        """内部方法：解决验证"""
        start_time = time.time()
        max_retries = 30
        current_try = 0
        clicked_history: Set[int] = set()
        last_category = None
        
        # 等待 reCAPTCHA 加载
        print("⏳ 等待 reCAPTCHA 加载...")
        self.page.wait.ele_displayed("@title:reCAPTCHA", timeout=10)
        time.sleep(1)
        
        # 点击主验证框
        main_frame = self.page.get_frame("@title=reCAPTCHA")
        if not main_frame:
            print("❌ 未找到 reCAPTCHA 框架")
            return False
        
        anchor = main_frame.ele("@class^rc-anchor-center-item")
        if anchor:
            print("🖱️ 点击验证框...")
            anchor.click()
        
        time.sleep(1)
        
        while current_try < max_retries and (time.time() - start_time) < timeout:
            current_try += 1
            print(f"\n🔄 --- 第 {current_try} 次循环 ---")
            
            # 检查是否成功
            if main_frame.ele('@aria-checked=true'):
                print("✅ 验证成功！")
                return True
            
            time.sleep(0.5)
            
            # 获取弹出层 iframe
            recaptcha_frame = self.page.get_frame('@src:recaptcha/api2/bframe')
            if not recaptcha_frame:
                recaptcha_frame = self.page.get_frame('@src:recaptcha/enterprise/bframe')
            
            if not recaptcha_frame:
                print("❓ 验证窗口未找到...")
                time.sleep(1)
                if main_frame.ele('@aria-checked=true'):
                    print("✅ 验证成功！")
                    return True
                continue
            
            # 等待图片容器
            target_ele = recaptcha_frame.wait.ele_displayed(
                "@class=rc-imageselect-challenge", timeout=3
            )
            if not target_ele:
                print("⏳ 图片未加载...")
                time.sleep(1)
                continue
            
            # 获取题目文本
            text_str = ""
            try:
                texts = recaptcha_frame.ele("@class=rc-imageselect-desc-no-canonical").texts()
                text_str = "".join(texts).lower()
            except Derrors.ElementNotFoundError:
                try:
                    texts = recaptcha_frame.ele("@class=rc-imageselect-desc").texts()
                    text_str = "".join(texts).lower()
                except:
                    pass
            
            print(f"📝 题目: {text_str}")
            
            # 获取目标标签
            target_labels = get_target_labels(text_str)
            
            # 重置历史（新题目）
            if target_labels != last_category:
                clicked_history.clear()
                last_category = target_labels
            
            # 检测网格类型
            tiles_elements = recaptcha_frame.eles(".rc-image-tile-target")
            grid_side = 4 if len(tiles_elements) == 16 else 3
            
            # 检测动态模式
            dynamic_keywords = ["直到", "until", "once there are none", "没有新图片"]
            is_dynamic = any(kw in text_str for kw in dynamic_keywords)
            
            print(f"   📊 网格: {grid_side}x{grid_side}, 动态: {is_dynamic}")
            
            # 不支持的类别 -> 刷新
            if not target_labels:
                print(f"⚠️ 不支持的类别，刷新换题!")
                self._click_reload(recaptcha_frame)
                continue
            
            print(f"   🎯 目标: {target_labels}")
            
            # 截图
            time.sleep(0.5)
            
            dpr = self.page.run_js("return window.devicePixelRatio;")
            iframe_rect = recaptcha_frame.frame_ele.rect
            ele_rect = target_ele.rect
            
            x1 = int((iframe_rect.location[0] + ele_rect.location[0]) * dpr)
            y1 = int((iframe_rect.location[1] + ele_rect.location[1]) * dpr)
            x2 = int(x1 + (ele_rect.size[0] * dpr))
            y2 = int(y1 + (ele_rect.size[1] * dpr))
            
            full_screenshot = self.page.get_screenshot(as_bytes=True)
            
            if DEBUG:
                with open(f"{SCREENSHOT_DIR}/full_{current_try}.png", "wb") as f:
                    f.write(full_screenshot)
            
            image_cp = crop_image_from_bytes(full_screenshot, (x1, y1, x2, y2))
            if not image_cp:
                continue
            
            if DEBUG:
                with open(f"{SCREENSHOT_DIR}/crop_{current_try}.jpg", "wb") as f:
                    f.write(image_cp)
            
            # 预处理 + YOLO 识别
            img_obj = Image.open(io.BytesIO(image_cp))
            img_enhanced = preprocess_image(img_obj)
            
            if DEBUG:
                img_enhanced.save(f"{SCREENSHOT_DIR}/enhanced_{current_try}.jpg")
            
            results = self.model(img_enhanced, verbose=False)
            
            # 网格交集算法
            img_w, img_h = img_obj.size
            tile_w = img_w / grid_side
            tile_h = img_h / grid_side
            
            click_indices: Set[int] = set()
            
            for r in results:
                for box in r.boxes:
                    cls_name = self.model.names[int(box.cls[0])]
                    conf = float(box.conf[0])
                    
                    if cls_name in target_labels and conf > 0.3:
                        bx1, by1, bx2, by2 = box.xyxy[0].tolist()
                        
                        if DEBUG:
                            print(f"      检测: {cls_name} conf={conf:.2f}")
                        
                        # 遍历所有格子计算交集
                        for row in range(grid_side):
                            for col in range(grid_side):
                                tx1 = col * tile_w
                                ty1 = row * tile_h
                                tx2 = (col + 1) * tile_w
                                ty2 = (row + 1) * tile_h
                                
                                # 计算交集
                                inter_x1 = max(bx1, tx1)
                                inter_y1 = max(by1, ty1)
                                inter_x2 = min(bx2, tx2)
                                inter_y2 = min(by2, ty2)
                                
                                if inter_x2 > inter_x1 and inter_y2 > inter_y1:
                                    inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
                                    tile_area = tile_w * tile_h
                                    overlap = inter_area / tile_area
                                    
                                    if overlap > 0.04:
                                        idx = row * grid_side + col
                                        click_indices.add(idx)
            
            sorted_indices = sorted(list(click_indices))
            print(f"🎯 需点击: {sorted_indices}")
            
            # 过滤已点击（静态模式）
            if not is_dynamic:
                sorted_indices = [i for i in sorted_indices if i not in clicked_history]
            
            # 执行点击
            if sorted_indices:
                print(f"🖱️ 点击 {len(sorted_indices)} 个图块...")
                
                # 随机顺序
                if len(sorted_indices) > 2:
                    random.shuffle(sorted_indices)
                
                for idx in sorted_indices:
                    if idx < len(tiles_elements):
                        tiles_elements[idx].click()
                        if not is_dynamic:
                            clicked_history.add(idx)
                        time.sleep(random.uniform(0.1, 0.2))
            else:
                print("🤷 未发现目标")
            
            # 动态模式：等待新图片
            if is_dynamic and sorted_indices:
                print("   ⏳ 动态模式: 等待新图片...")
                time.sleep(2.5)
                continue
            
            # 提交验证
            verify_btn = recaptcha_frame.ele("#recaptcha-verify-button")
            if verify_btn and verify_btn.states.is_enabled:
                print("🖱️ 提交验证...")
                verify_btn.click()
                time.sleep(1.5)
                
                # 检查错误
                error_msg = recaptcha_frame.ele("@class:rc-imageselect-error")
                if error_msg and error_msg.states.is_displayed:
                    print("❌ 需要选择更多...")
                    if not sorted_indices:
                        print("⚠️ 死局! 刷新换题...")
                        self._click_reload(recaptcha_frame)
        
        return False
    
    def _click_reload(self, frame):
        """点击刷新按钮"""
        try:
            reload_btn = frame.ele("#recaptcha-reload-button")
            if reload_btn:
                reload_btn.click()
                time.sleep(2)
        except:
            pass


def solve_recaptcha_on_page(url: str, headless: bool = True) -> bool:
    """便捷函数"""
    solver = RecaptchaSolver(headless=headless)
    return solver.solve(url)


# ============== 测试 ==============
if __name__ == "__main__":
    test_url = "https://2captcha.com/demo/recaptcha-v2"
    print(f"🌐 测试 URL: {test_url}")
    
    success = solve_recaptcha_on_page(test_url, headless=False)
    
    if success:
        print("\n🎉 验证成功!")
    else:
        print("\n❌ 验证失败")
