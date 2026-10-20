"""
Module: video_generator.py
สร้างคลิปวิดีโอสั้นแนวตั้ง 9:16 (1080x1920) สำหรับ TikTok, Instagram Reels และ YouTube Shorts
พร้อมเสียงพากย์ภาษาไทยจาก Google Text-to-Speech (gTTS) และภาพกราฟิกข่าวกีฬา
"""

import os
import sys
import re
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from gtts import gTTS
from moviepy import ImageClip, AudioFileClip

try:
    import pythainlp
    HAS_PYTHAINLP = True
except ImportError:
    HAS_PYTHAINLP = False

BASE_DIR = Path(__file__).resolve().parent
FONTS_DIR = BASE_DIR / "fonts"
VIDEOS_DIR = BASE_DIR / "downloads" / "videos"
AUDIO_DIR = BASE_DIR / "downloads" / "audio"

VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

FONT_HEADLINE_PATH = FONTS_DIR / "Kanit-Bold.ttf"
FONT_BODY_PATH = FONTS_DIR / "Prompt-SemiBold.ttf"

def clean_text_for_speech(text: str) -> str:
    """ขจัด Emoji, Markdown, URL, และ Hashtags ออกเพื่อให้อ่านออกเสียงภาษาไทยได้ลื่นไหล ไม่ติดขัด"""
    if not text:
        return ""
    # เอา URL ออก
    cleaned = re.sub(r'https?://\S+|www\.\S+', '', text)
    # เอา Hashtags ออก
    cleaned = re.sub(r'#\S+', '', cleaned)
    # เอา Markdown symbols (*, _, ~, `, #)
    cleaned = re.sub(r'[*_~`#]', '', cleaned)
    # เอา Emojis ทั่วไปออก
    cleaned = re.sub(r'[🔴⚡🔥👑⚽🏆📊💬⭐📌🛒👉❌✅🦅🚨💥]', '', cleaned)
    # ตัดช่องว่างซ้ำซ้อน
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def generate_voiceover_google(text: str, output_path: str = None) -> str:
    """สร้างไฟล์เสียงพากย์ภาษาไทยด้วย Google TTS Engine"""
    clean_speech = clean_text_for_speech(text)
    if not clean_speech:
        clean_speech = "ข่าวด่วนล่าสุดจากสโมสรลิเวอร์พูล"

    if not output_path:
        output_path = str(AUDIO_DIR / f"voice_{int(time.time()*1000)}.mp3")

    tts = gTTS(text=clean_speech, lang="th", slow=False)
    tts.save(output_path)
    return output_path

def get_font(path, size):
    """โหลดฟอนต์"""
    if path.exists():
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            pass
    for win_font in ["C:/Windows/Fonts/tahomabd.ttf", "C:/Windows/Fonts/leelawdb.ttf", "C:/Windows/Fonts/tahoma.ttf"]:
        if os.path.exists(win_font):
            try:
                return ImageFont.truetype(win_font, size)
            except Exception:
                pass
    return ImageFont.load_default()

def wrap_thai(text: str, font, max_width: int, max_lines: int = 3) -> list:
    """ตัดคำไทยสำหรับ Subtitle"""
    if HAS_PYTHAINLP:
        words = pythainlp.tokenize.word_tokenize(text, engine="newmm")
    else:
        words = text.split(" ")

    lines = []
    curr = ""
    for w in words:
        test = curr + w
        bbox = font.getbbox(test)
        if (bbox[2] - bbox[0]) <= max_width:
            curr = test
        else:
            if curr:
                lines.append(curr)
                curr = w
            else:
                lines.append(w)
                curr = ""
            if len(lines) >= max_lines:
                break
    if curr and len(lines) < max_lines:
        lines.append(curr)
    return lines

def create_vertical_frame(
    image_path: str,
    headline: str,
    page_name: str = "หงส์นิวส์",
    width: int = 1080,
    height: int = 1920
) -> Image.Image:
    """สร้างเฟรมแนวตั้ง 9:16 (1080x1920) สไตล์ TikTok/Reels แบบพรีเมียม"""
    
    # 1. โหลดภาพหลัก
    if image_path and os.path.exists(image_path):
        try:
            raw_img = Image.open(image_path).convert("RGB")
        except Exception:
            raw_img = Image.new("RGB", (width, height), (15, 15, 20))
    else:
        raw_img = Image.new("RGB", (width, height), (15, 15, 20))

    # 2. ทำภาพพื้นหลัง (Full Canvas Zoom & Blur Effect)
    bg_w, bg_h = raw_img.size
    bg_ratio = width / height
    raw_ratio = bg_w / bg_h

    if raw_ratio > bg_ratio:
        crop_w = int(bg_h * bg_ratio)
        bg_crop = raw_img.crop(((bg_w - crop_w) // 2, 0, (bg_w + crop_w) // 2, bg_h))
    else:
        crop_h = int(bg_w / bg_ratio)
        bg_crop = raw_img.crop((0, (bg_h - crop_h) // 2, bg_w, (bg_h + crop_h) // 2))

    bg_img = bg_crop.resize((width, height), Image.Resampling.LANCZOS)
    # ใส่ Blur ให้พื้นหลังดูนุ่มนวล มีมิติ
    bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=28))
    # ปรับความมืดลง
    darken = ImageEnhance.Brightness(bg_img).enhance(0.40)
    canvas = darken.convert("RGBA")

    # 3. วาดภาพข่าวหลักตรงกลาง (Center 1000x1000 พร้อมขอบแดงและเงา)
    center_size = 980
    c_x = (width - center_size) // 2
    c_y = 360  # ตำแหน่งแกน Y ตรงกลางแนวตั้ง

    center_crop = raw_img.resize((center_size, center_size), Image.Resampling.LANCZOS).convert("RGBA")

    # ใส่กรอบเส้นขอบสีแดงหงส์แดงรอบรูป
    border_draw = ImageDraw.Draw(center_crop)
    border_draw.rectangle([0, 0, center_size-1, center_size-1], outline=(200, 16, 46, 255), width=6)

    canvas.paste(center_crop, (c_x, c_y), center_crop)

    draw = ImageDraw.Draw(canvas)

    # 4. ส่วนหัวด้านบน (Top Header: Branding Badge)
    top_badge_text = f"🔴 {page_name} • LFC REELS SHORT"
    font_top = get_font(FONT_BODY_PATH, 34)
    t_bbox = font_top.getbbox(top_badge_text)
    t_w = t_bbox[2] - t_bbox[0]
    badge_x = (width - t_w - 50) // 2

    # ป้ายขอบมนด้านบน
    draw.rounded_rectangle(
        [badge_x, 180, badge_x + t_w + 50, 245],
        radius=16,
        fill=(200, 16, 46, 230),
        outline=(246, 235, 97, 200),
        width=2
    )
    draw.text((badge_x + 25, 192), top_badge_text, font=font_top, fill=(255, 255, 255))

    # 5. ส่วนล่าง (Bottom Subtitle Box: พาดหัวตัวเบิ้มๆ สำหรับคนดู TikTok)
    box_y = c_y + center_size + 45
    box_h = 320
    box_margin = 45

    # กล่องดำโปร่งใส Glassmorphism
    draw.rounded_rectangle(
        [box_margin, box_y, width - box_margin, box_y + box_h],
        radius=24,
        fill=(10, 10, 14, 230),
        outline=(200, 16, 46, 120),
        width=2
    )

    # Accent Bar สีทอง/แดงด้านบนของกล่อง
    draw.rounded_rectangle(
        [box_margin + 30, box_y + 20, box_margin + 120, box_y + 26],
        radius=3,
        fill=(246, 235, 97, 255)
    )

    font_sub_label = get_font(FONT_BODY_PATH, 24)
    draw.text((box_margin + 135, box_y + 12), "⚡ สรุปข่าวด่วน", font=font_sub_label, fill=(246, 235, 97))

    # วาดตัวหนังสือพาดหัวภาษาไทย
    font_headline = get_font(FONT_HEADLINE_PATH, 46)
    wrapped = wrap_thai(headline, font_headline, max_width=(width - (box_margin * 2) - 60), max_lines=3)

    cur_ty = box_y + 65
    for line in wrapped:
        draw.text((box_margin + 32, cur_ty + 2), line, font=font_headline, fill=(0, 0, 0, 200))
        draw.text((box_margin + 30, cur_ty), line, font=font_headline, fill=(255, 255, 255))
        cur_ty += 58

    # 6. เส้นขอบล่างสุด
    for x in range(width):
        ratio = x / width
        r = int(200 * (1 - ratio) + 246 * ratio)
        g = int(16 * (1 - ratio) + 235 * ratio)
        b = int(46 * (1 - ratio) + 97 * ratio)
        draw.line([(x, height - 10), (x, height)], fill=(r, g, b, 255))

    return canvas.convert("RGB")

def generate_short_video(
    image_path: str,
    headline: str,
    speech_text: str,
    page_name: str = "หงส์นิวส์",
    output_path: str = None
) -> str:
    """
    สร้างไฟล์วิดีโอแนวตั้ง 9:16 (MP4) พร้อมเสียงพากย์ภาษาไทยจาก Google TTS
    :return: ที่อยู่ไฟล์ MP4 ที่สร้างสำเร็จ
    """
    # 1. สร้างเสียงพากย์ Google TTS
    voice_file = generate_voiceover_google(speech_text)

    # 2. วัดความยาวของเสียง
    audio_clip = AudioFileClip(voice_file)
    duration = max(3.0, audio_clip.duration + 0.5)

    # 3. สร้างเฟรมภาพ 9:16 (1080x1920)
    frame_img = create_vertical_frame(image_path, headline, page_name)
    temp_frame_path = str(VIDEOS_DIR / f"frame_{int(time.time()*1000)}.png")
    frame_img.save(temp_frame_path, "PNG")

    # 4. รวมภาพและเสียงเป็นคลิป MP4 ด้วย MoviePy
    if not output_path:
        output_path = str(VIDEOS_DIR / f"short_{int(time.time()*1000)}.mp4")

    try:
        video_clip = ImageClip(temp_frame_path).with_duration(duration)
        final_video = video_clip.with_audio(audio_clip)

        # เรนเดอร์ด้วยความเร็วสูง fps=24
        final_video.write_videofile(
            output_path,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            preset="ultrafast",
            threads=4,
            logger=None
        )

        audio_clip.close()
        video_clip.close()
    finally:
        # ลบไฟล์เฟรมชั่วคราว
        if os.path.exists(temp_frame_path):
            try:
                os.remove(temp_frame_path)
            except Exception:
                pass

    return output_path

if __name__ == "__main__":
    print("Testing video_generator.py...")
    test_out = generate_short_video(
        image_path=None,
        headline="คล็อปป์ส่งสัญญาณ! หงส์แดงเตรียมปิดดีลแข้งใหม่ค่าตัวสถิติสโมสร",
        speech_text="สวัสดีครับแฟนบอลลิเวอร์พูลทุกท่าน ล่าสุดมีรายงานว่าหงส์แดงใกล้จะบรรลุข้อตกลงคว้าตัวแข้งใหม่มาร่วมทัพแล้วครับ",
        page_name="หงส์นิวส์"
    )
    print("Generated short video:", test_out)
