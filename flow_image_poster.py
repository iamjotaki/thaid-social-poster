"""
Module: flow_image_poster.py
ระบบสร้างรูปภาพโพสต์อัตโนมัติด้วย Google Flow (ผ่าน Chrome CDP Bridge c:\\NV)
- วิเคราะห์รูปภาพอ้างอิงด้วย Gemini Vision เพื่อถอดรหัสสไตล์งานศิลป์และ Prompt
- กำหนดข้อความพาดหัวเอง หรือให้ AI คิดข้อความให้อัตโนมัติ
- สั่งเจนรูปจาก Google Flow (Ports 9222, 9223)
- ตกแต่งภาพด้วย Typography ภาษาไทยระดับพรีเมียม (Kanit / Prompt Fonts)
- ออโต้โพสต์ หรือ ตั้งเวลาบน Facebook (Native Facebook Scheduling)
"""

import os
import sys
import time
import json
import base64
import random
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from PIL import Image, ImageDraw, ImageFont

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import config
import database
from fb_poster import post_to_facebook
from database import record_post_history, create_scheduled_post, get_page_by_id

# Import flow_bridge from c:\NV\novel_studio
NV_STUDIO_DIR = r"c:\NV\novel_studio"
if os.path.exists(NV_STUDIO_DIR) and NV_STUDIO_DIR not in sys.path:
    sys.path.insert(0, NV_STUDIO_DIR)

try:
    import flow_bridge
    HAS_FLOW_BRIDGE = True
except Exception as e:
    HAS_FLOW_BRIDGE = False
    print(f"[FlowPoster Warning] Could not import flow_bridge: {e}")

BASE_DIR = Path(__file__).resolve().parent
POSTS_DIR = BASE_DIR / "static" / "generated_posts"
POSTS_DIR.mkdir(parents=True, exist_ok=True)

FONTS_DIR = BASE_DIR / "fonts"
FONT_HEADLINE_PATH = FONTS_DIR / "Kanit-Bold.ttf"
FONT_BODY_PATH = FONTS_DIR / "Prompt-SemiBold.ttf"

THEMES = {
    "lfc_red": {
        "name": "🔴 LFC แดงเพลิง (Official Matchday)",
        "primary": (200, 16, 46),       # #C8102E
        "accent": (246, 235, 97),       # #F6EB61 Gold
        "badge_bg": (200, 16, 46, 240),
        "badge_text": (255, 255, 255),
    },
    "breaking_gold": {
        "name": "⚡ Breaking News ป้ายทอง",
        "primary": (220, 30, 30),
        "accent": (255, 204, 0),
        "badge_bg": (255, 204, 0, 240),
        "badge_text": (15, 15, 18),
    },
    "dark_cinematic": {
        "name": "🎬 Dark Aesthetic สไตล์ภาพยนตร์",
        "primary": (30, 30, 40),
        "accent": (0, 210, 255),
        "badge_bg": (0, 178, 169, 230),
        "badge_text": (255, 255, 255),
    },
    "cyber_neon": {
        "name": "🔥 Cyberpunk Neon ล้ำสมัย",
        "primary": (255, 0, 128),
        "accent": (0, 255, 204),
        "badge_bg": (255, 0, 128, 230),
        "badge_text": (255, 255, 255),
    }
}

def get_flow_status() -> Dict[str, Any]:
    """ตรวจสอบสถานะ Google Flow Chrome Ports (9222, 9223)"""
    ports = [9222, 9223]
    alive_ports = []
    for port in ports:
        try:
            url = f"http://127.0.0.1:{port}/json/version"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                if resp.status == 200:
                    alive_ports.append(port)
        except Exception:
            pass

    return {
        "is_ready": len(alive_ports) > 0,
        "alive_ports": alive_ports,
        "has_bridge": HAS_FLOW_BRIDGE,
        "message": f"พร้อมใช้งาน (Google Flow กำลังทำงานอยู่ {len(alive_ports)} พอร์ต: {alive_ports})" if alive_ports else "Google Flow Chrome ยังไม่เปิด (รัน auto_start_flow_bridge.bat เพื่อเปิด)"
    }

def get_best_gemini_key(user_id: Optional[int] = None) -> Optional[str]:
    """ดึงคีย์ Gemini ที่พร้อมใช้งาน"""
    if user_id:
        try:
            keys = database.get_active_api_keys_for_user(user_id)
            if keys:
                return keys[0]
        except Exception:
            pass
    return config.GEMINI_API_KEY or None

def analyze_reference_image_and_prompt(
    ref_image_path: Optional[str] = None,
    topic: str = "",
    user_style_note: str = "",
    user_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    วิเคราะห์ภาพอ้างอิง และ/หรือ หัวข้อที่ต้องการ
    คืนค่า Prompt ภาษาอังกฤษสำหรับส่งให้ Google Flow, ข้อความพาดหัว, และแคปชั่น Facebook
    """
    api_key = get_best_gemini_key(user_id)
    has_valid_key = api_key and not api_key.startswith("your_")

    if has_valid_key:
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=api_key)

            instruction = f"""
คุณเป็น AI Art Director และ Copywriter ผู้เชี่ยวชาญด้าน Visual Prompt Engineering สำหรับ Google Flow (Imagen) และสื่อโซเชียลมีเดียฟุตบอลระดับพรีเมียม

[เป้าหมายของผู้ใช้]
- หัวข้อที่ต้องการสร้างภาพ: {topic or 'ภาพโปสเตอร์ฟุตบอลลิเวอร์พูล แอนฟิลด์ สวยงามระดับพรีเมียม'}
- คำแนะนำสไตล์เพิ่มเติม: {user_style_note or 'เน้นแสงเงาสวยงาม อารมณ์เข้มข้น ดึงดูดสายตา'}

[งานของคุณ]
1. ถอดรหัสองค์ประกอบภาพศิลป์ ออกมาเป็น English Visual Prompt สำหรับ Google Flow ความยาว 25-45 คำ (ครอบคลุม: Subject, Composition, Lighting, Atmosphere, Color palette, Quality tags)
2. คิดข้อความภาษาไทย 3 ส่วน:
   - headline: พาดหัวเดือดๆ บนภาพ (สั้นกระชับ 5-10 คำ)
   - subtitle: ข้อความรองบนภาพ (1 ประโยคชวนติดตาม)
   - badge: ป้ายหัวข้อสั้นๆ เช่น 🔴 MATCHDAY, ⚡ BREAKING, 🔥 HOT QUOTE, 🏆 EXCLUSIVE
3. คิดข้อความแคปชั่น Facebook (facebook_caption) พร้อมอิโมจิและแฮชแท็กติดเทรนด์

ตอบกลับมาเป็น JSON ตามรูปแบบนี้เท่านั้น:
{{
  "flow_prompt": "English prompt for Google Flow...",
  "headline": "พาดหัวไทย...",
  "subtitle": "ข้อความรอง...",
  "badge": "🔴 MATCHDAY",
  "facebook_caption": "แคปชั่นโพสต์ Facebook..."
}}
"""
            contents = []
            if ref_image_path and os.path.exists(ref_image_path):
                try:
                    pil_img = Image.open(ref_image_path)
                    contents.append(pil_img)
                    instruction += "\n* สำคัญ: กรุณาวิเคราะห์รูปภาพอ้างอิงที่แนบมานี้ ถอดสไตล์ composition, lighting, และ color grading มาประยุกต์ใช้กับ prompt ใหม่ด้วย"
                except Exception as e_img:
                    print(f"[AnalyzeRef Warning] Cannot load PIL image: {e_img}")

            contents.append(instruction)

            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents
            )

            if response and response.text:
                raw_text = response.text.strip()
                # Clean markdown backticks
                if "```json" in raw_text:
                    raw_text = raw_text.split("```json")[1].split("```")[0].strip()
                elif "```" in raw_text:
                    raw_text = raw_text.split("```")[1].split("```")[0].strip()

                parsed = json.loads(raw_text)
                if user_id:
                    database.record_api_key_usage(api_key)
                return {
                    "success": True,
                    "flow_prompt": parsed.get("flow_prompt", ""),
                    "headline": parsed.get("headline", ""),
                    "subtitle": parsed.get("subtitle", ""),
                    "badge": parsed.get("badge", "🔴 MATCHDAY"),
                    "facebook_caption": parsed.get("facebook_caption", "")
                }
        except Exception as e:
            print(f"[Gemini Vision Analysis Error]: {e}")

    # Fallback Preset Generator
    return _generate_fallback_style_prompt(topic, user_style_note)

def _generate_fallback_style_prompt(topic: str, user_style_note: str) -> Dict[str, Any]:
    """สร้าง Prompt และข้อความสำเร็จรูปเมื่อยังไม่ได้เชื่อมต่อ Gemini Key"""
    clean_topic = topic.strip() or "ลิเวอร์พูล เปิดรังแอนฟิลด์ทำศึกใหญ่"
    
    flow_prompt = (
        f"Masterpiece cinematic sports photography of {clean_topic}, "
        "dramatic Anfield stadium background, intense stadium floodlights, volumetric atmospheric red smoke, "
        "hyper-detailed, dynamic action composition, 8k resolution, cinematic color grading, vertical 3:4 poster art"
    )

    headline = clean_topic if len(clean_topic) < 30 else clean_topic[:28] + "..."
    subtitle = "ศึกแห่งศักดิ์ศรีและความยิ่งใหญ่ ณ รังแอนฟิลด์ ค่ำคืนที่แฟนบอลทุกคนต้องจับตา!"
    badge = "🔴 MATCHDAY"
    caption = f"""🔴 {clean_topic} ⚽️🔥

{subtitle}
พร้อมเสียงเชียร์กึกก้องจากแฟนบอลเดอะค็อปทั่วทุกมุมโลก ร่วมส่งพลังใจเชียร์ทีมรักไปด้วยกันคืนนี้! 🔴

#LFC #LiverpoolFC #เด็กหงส์ #TheKop #Anfield #หงส์แดง #ฟุตบอลพรีเมียร์ลีก"""

    return {
        "success": True,
        "flow_prompt": flow_prompt,
        "headline": headline,
        "subtitle": subtitle,
        "badge": badge,
        "facebook_caption": caption
    }

def generate_image_with_google_flow(
    prompt: str,
    port: Optional[int] = None,
    timeout: int = 65
) -> Tuple[bool, str]:
    """
    ส่ง Prompt ไปยัง Google Flow เพื่อสร้างรูปภาพใหม่ผ่าน Chrome CDP Bridge
    คืนค่า (True, local_image_path) หรือ (False, error_message)
    """
    if not HAS_FLOW_BRIDGE:
        return False, "ไม่พบโมดูล flow_bridge ในระบบ c:\\NV\\novel_studio"

    status = get_flow_status()
    if not status["is_ready"]:
        return False, "Google Flow Chrome ยังไม่เปิดใช้งาน (กรุณาเปิด auto_start_flow_bridge.bat บนพอร์ต 9222 หรือ 9223)"

    target_port = port or (status["alive_ports"][0] if status["alive_ports"] else 9222)
    print(f"[FlowPoster] 🚀 Submitting to Google Flow on Port {target_port}...")

    try:
        raw_result, err = flow_bridge.send_prompt_to_google_flow(
            prompt=prompt,
            wait_for_result=True,
            timeout=timeout,
            port=target_port
        )

        if not raw_result:
            flow_bridge.release_flow_lane(target_port, "Generation failed or timed out")
            return False, f"Google Flow ไม่สามารถสร้างภาพได้: {err or 'Timed out'}"

        # Copy raw image to our project's static folder
        ext = os.path.splitext(raw_result)[1] or ".jpg"
        save_filename = f"flow_raw_{int(time.time()*1000)}{ext}"
        dest_path = str(POSTS_DIR / save_filename)

        with open(raw_result, "rb") as f_src, open(dest_path, "wb") as f_dst:
            f_dst.write(f_src.read())

        # Release lane lock so next requests can proceed
        flow_bridge.release_flow_lane(target_port, "Image generated and saved successfully")

        print(f"[FlowPoster] ✅ Flow image generated and saved to: {dest_path}")
        return True, dest_path

    except Exception as e:
        if HAS_FLOW_BRIDGE:
            try:
                flow_bridge.release_flow_lane(target_port, f"Exception: {e}")
            except Exception:
                pass
        return False, f"เกิดข้อผิดพลาดในการเชื่อมต่อ Google Flow: {e}"

def stamp_typography(
    image_path: str,
    headline: str,
    subtitle: str = "",
    badge: str = "🔴 MATCHDAY",
    theme_key: str = "lfc_red"
) -> str:
    """
    ประทับข้อความพาดหัวภาษาไทยและ Badge ลงบนรูปภาพด้วย Typography ระดับพรีเมียม
    คืนค่า path ของรูปภาพที่ตกแต่งเสร็จแล้ว
    """
    if not os.path.exists(image_path):
        return image_path

    theme = THEMES.get(theme_key, THEMES["lfc_red"])
    base = Image.open(image_path).convert("RGBA")
    w, h = base.size

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # 1. Gradient Backplate at the bottom (40% height)
    gradient_h = int(h * 0.45)
    for y in range(h - gradient_h, h):
        ratio = (y - (h - gradient_h)) / gradient_h
        alpha = int(240 * (ratio ** 1.3))
        draw.line([(0, y), (w, y)], fill=(8, 8, 12, alpha))

    # Top vignette subtle shadow
    top_gradient_h = int(h * 0.18)
    for y in range(top_gradient_h):
        ratio = 1.0 - (y / top_gradient_h)
        alpha = int(140 * ratio)
        draw.line([(0, y), (w, y)], fill=(5, 5, 8, alpha))

    # 2. Font Loading
    h_size = int(w * 0.058) # Responsive headline font size (~52px for 896px width)
    sub_size = int(w * 0.028) # Responsive subtitle font size (~25px)
    badge_size = int(w * 0.022)

    font_h = _load_font(FONT_HEADLINE_PATH, h_size, "tahomabd.ttf")
    font_sub = _load_font(FONT_BODY_PATH, sub_size, "tahoma.ttf")
    font_badge = _load_font(FONT_HEADLINE_PATH, badge_size, "tahomabd.ttf")

    padding_x = int(w * 0.05)
    bottom_y = h - int(h * 0.06)

    # 3. Draw Subtitle (if any)
    curr_y = bottom_y
    if subtitle:
        sub_lines = _wrap_text(subtitle, font_sub, max_width=w - (padding_x * 2))
        sub_lines.reverse()
        for s_line in sub_lines:
            curr_y -= int(sub_size * 1.35)
            # Drop shadow
            draw.text((padding_x + 2, curr_y + 2), s_line, font=font_sub, fill=(0, 0, 0, 190))
            draw.text((padding_x, curr_y), s_line, font=font_sub, fill=(*theme["accent"], 240))
        curr_y -= int(h * 0.015)

    # 4. Draw Headline
    if headline:
        h_lines = _wrap_text(headline, font_h, max_width=w - (padding_x * 2))
        h_lines.reverse()
        for h_line in h_lines:
            curr_y -= int(h_size * 1.3)
            # Heavy drop shadow
            draw.text((padding_x + 3, curr_y + 3), h_line, font=font_h, fill=(0, 0, 0, 220))
            draw.text((padding_x, curr_y), h_line, font=font_h, fill=(255, 255, 255, 255))
        curr_y -= int(h * 0.018)

    # 5. Draw Badge & Accent Line
    curr_y -= int(badge_size * 1.8)
    badge_text = badge.strip() or "🔴 MATCHDAY"
    
    # Calculate badge bounding box
    bbox = font_badge.getbbox(badge_text)
    badge_w = (bbox[2] - bbox[0]) + int(w * 0.03)
    badge_h = int(badge_size * 1.6)

    # Badge background
    draw.rounded_rectangle(
        [padding_x, curr_y, padding_x + badge_w, curr_y + badge_h],
        radius=6,
        fill=theme["badge_bg"],
        outline=(255, 255, 255, 120),
        width=1
    )
    draw.text(
        (padding_x + int(w * 0.015), curr_y + int(badge_size * 0.25)),
        badge_text,
        font=font_badge,
        fill=theme["badge_text"]
    )

    # Accent horizontal bar
    line_x0 = padding_x + badge_w + int(w * 0.02)
    line_x1 = line_x0 + int(w * 0.12)
    line_y = curr_y + (badge_h // 2)
    draw.line([(line_x0, line_y), (line_x1, line_y)], fill=(*theme["accent"], 255), width=3)

    # 6. Composite & Save
    final = Image.alpha_composite(base, overlay).convert("RGB")
    final_filename = f"flow_post_{int(time.time()*1000)}.jpg"
    final_path = str(POSTS_DIR / final_filename)
    final.save(final_path, "JPEG", quality=95)

    return final_path

def _load_font(path: Path, size: int, fallback_win_font: str = "tahoma.ttf"):
    if path.exists():
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            pass
    for win_font in [f"C:/Windows/Fonts/{fallback_win_font}", "C:/Windows/Fonts/tahoma.ttf", "C:/Windows/Fonts/leelawdb.ttf"]:
        if os.path.exists(win_font):
            try:
                return ImageFont.truetype(win_font, size)
            except Exception:
                pass
    return ImageFont.load_default()

def _wrap_text(text: str, font, max_width: int) -> List[str]:
    """ตัดข้อความขึ้นบรรทัดใหม่ให้พอดีความกว้าง"""
    words = text.split(" ")
    lines = []
    curr = ""
    for w in words:
        test = f"{curr} {w}".strip() if curr else w
        bbox = font.getbbox(test)
        if (bbox[2] - bbox[0]) <= max_width:
            curr = test
        else:
            if curr:
                lines.append(curr)
            curr = w
    if curr:
        lines.append(curr)
    return lines or [text]
