"""
Module: card_generator.py
สร้างภาพกราฟิกข่าวกีฬาระดับพรีเมียม (Social Card) สไตล์สื่อกีฬาชั้นนำ (Main Stand / ขอบสนาม)
รองรับการตัดคำภาษาไทยด้วย pythainlp และฟอนต์ Kanit / Prompt
"""

import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

try:
    import pythainlp
    HAS_PYTHAINLP = True
except ImportError:
    HAS_PYTHAINLP = False

BASE_DIR = Path(__file__).resolve().parent
FONTS_DIR = BASE_DIR / "fonts"
FONTS_DIR.mkdir(parents=True, exist_ok=True)

FONT_HEADLINE_PATH = FONTS_DIR / "Kanit-Bold.ttf"
FONT_BODY_PATH = FONTS_DIR / "Prompt-SemiBold.ttf"

THEMES = {
    "lfc": {
        "primary": (200, 16, 46),       # #C8102E (LFC Red)
        "accent": (246, 235, 97),       # #F6EB61 (LFC Gold)
        "badge_bg": (200, 16, 46, 240),
        "badge_text": (255, 255, 255),
        "bar": (200, 16, 46),
    },
    "breaking": {
        "primary": (220, 20, 20),       # Vibrant Red
        "accent": (255, 204, 0),        # Warning Yellow
        "badge_bg": (220, 20, 20, 240),
        "badge_text": (255, 255, 255),
        "bar": (255, 204, 0),
    },
    "tactics": {
        "primary": (0, 178, 169),       # LFC Teal / Cyan
        "accent": (246, 235, 97),
        "badge_bg": (0, 178, 169, 240),
        "badge_text": (255, 255, 255),
        "bar": (0, 178, 169),
    },
    "gold": {
        "primary": (212, 160, 23),      # Gold
        "accent": (255, 255, 255),
        "badge_bg": (212, 160, 23, 240),
        "badge_text": (15, 15, 18),
        "bar": (212, 160, 23),
    }
}

def get_font(path, size):
    """โหลดฟอนต์พร้อม fallback"""
    if path.exists():
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            pass
    # Fallback to Windows tahoma/leelawadee if available
    for win_font in ["C:/Windows/Fonts/tahomabd.ttf", "C:/Windows/Fonts/leelawdb.ttf", "C:/Windows/Fonts/tahoma.ttf"]:
        if os.path.exists(win_font):
            try:
                return ImageFont.truetype(win_font, size)
            except Exception:
                pass
    return ImageFont.load_default()

def wrap_thai_text(text: str, font, max_width: int, max_lines: int = 3) -> list:
    """ตัดคำภาษาไทยให้พอดีความกว้าง โดยไม่ตัดผ่ากลางคำ"""
    if not text:
        return []

    if HAS_PYTHAINLP:
        words = pythainlp.tokenize.word_tokenize(text, engine="newmm")
    else:
        words = text.split(" ")

    lines = []
    current_line = ""

    for w in words:
        test_line = current_line + w
        # วัดความกว้างของข้อความ
        bbox = font.getbbox(test_line)
        w_width = bbox[2] - bbox[0]

        if w_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
                current_line = w
            else:
                # ถ้าคำเดียวเกิน max_width ให้ใส่ไปเลย
                lines.append(w)
                current_line = ""

            if len(lines) >= max_lines:
                break

    if current_line and len(lines) < max_lines:
        lines.append(current_line)

    # ถ้าตัดแล้วเกิน 3 บรรทัด ให้ใส่ ... ที่บรรทัดสุดท้าย
    if len(lines) == max_lines and len(words) > 0:
        last = lines[-1]
        if not last.endswith("..."):
            lines[-1] = last.rstrip() + "..."

    return lines

def generate_social_card(
    image_path: str,
    headline: str,
    category: str = "🔴 ข่าวลิเวอร์พูล",
    page_name: str = "หงส์นิวส์",
    subtitle: str = None,
    logo_path: str = None,
    output_path: str = None,
    theme: str = "lfc",
    width: int = 1080,
    height: int = 1080
) -> str:
    """
    สร้างภาพกราฟิกข่าวกีฬา Social Card (1080x1080)
    :param image_path: ที่อยู่ภาพต้นฉบับ
    :param headline: พาดหัวข่าวหลัก
    :param category: หมวดหมู่ข่าว (แสดงใน Tag มุมซ้ายบน)
    :param page_name: ชื่อเพจ (แสดงใน Watermark มุมขวาบน และ Footer)
    :param subtitle: ข้อความเสริม หรือ โควทเด่น (ไม่ใส่ก็ได้)
    :param logo_path: โลโก้เพจ (ถ้ามี)
    :param output_path: ที่อยู่ไฟล์ผลลัพธ์
    :param theme: ธีมสี (lfc, breaking, tactics, gold)
    :return: path ของไฟล์ที่เซฟสำเร็จ
    """
    theme_cfg = THEMES.get(theme, THEMES["lfc"])

    # 1. โหลดและจัดการภาพพื้นหลัง (Smart Zoom & Crop to 1080x1080)
    if image_path and os.path.exists(image_path):
        try:
            raw_img = Image.open(image_path).convert("RGB")
        except Exception as e:
            print(f"[CardGenerator] Error opening image {image_path}: {e}")
            raw_img = Image.new("RGB", (width, height), (20, 20, 24))
    else:
        raw_img = Image.new("RGB", (width, height), (20, 20, 24))

    # คำนวณ Aspect Ratio เพื่อ Crop กึ่งกลางแบบเน้นบุคคล/เหตุการณ์
    src_w, src_h = raw_img.size
    target_ratio = width / height
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        # ภาพกว้างเกินไป -> crop ด้านข้าง
        new_w = int(src_h * target_ratio)
        offset_x = (src_w - new_w) // 2
        crop_box = (offset_x, 0, offset_x + new_w, src_h)
    else:
        # ภาพสูงเกินไป -> crop บน-ล่าง (เน้นค่อนไปทางบน 25% เพื่อไม่ให้หัวนักเตะขาด)
        new_h = int(src_w / target_ratio)
        offset_y = max(0, int((src_h - new_h) * 0.25))
        crop_box = (0, offset_y, src_w, min(src_h, offset_y + new_h))

    cropped_img = raw_img.crop(crop_box).resize((width, height), Image.Resampling.LANCZOS)

    # ปรับ Contrast และความสดของสีเล็กน้อยให้รูปดูสดใสเตะตา
    enhancer = ImageEnhance.Color(cropped_img)
    cropped_img = enhancer.enhance(1.15)
    contrast_enhancer = ImageEnhance.Contrast(cropped_img)
    cropped_img = contrast_enhancer.enhance(1.08)

    base_card = cropped_img.convert("RGBA")

    # 2. สร้างเลเยอร์เงาไล่โทน (Dark Gradient Overlays)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    # 2.1 เงาบน (Top Vignette สำหรับให้อ่าน Badge / Logo ได้ชัด)
    top_vignette_height = 200
    for y in range(top_vignette_height):
        alpha = int(170 * (1 - (y / top_vignette_height) ** 1.3))
        overlay_draw.line([(0, y), (width, y)], fill=(10, 10, 14, alpha))

    # 2.2 เงาล่าง (Bottom Gradient ปูพื้นให้อ่านพาดหัวข่าวชัดเจน 100%)
    grad_start = int(height * 0.38) # เริ่มไล่เงาตั้งแต่ 38% ของรูป
    grad_len = height - grad_start

    for y in range(grad_start, height):
        ratio = (y - grad_start) / grad_len
        # ใช้ Non-linear curve (smooth cubic) เพื่อให้การไล่เงามืดนุ่มนวลเป็นธรรมชาติ
        curve = ratio ** 1.8
        alpha = int(245 * min(1.0, curve))
        overlay_draw.line([(0, y), (width, y)], fill=(8, 9, 13, alpha))

    base_card = Image.alpha_composite(base_card, overlay)
    draw = ImageDraw.Draw(base_card)

    # 3. วาดส่วนหัว (Top Bar: Category Pill & Watermark)
    top_margin = 45
    side_margin = 55

    font_badge = get_font(FONT_BODY_PATH, 28)
    font_brand = get_font(FONT_BODY_PATH, 24)

    # 3.1 Category Badge (มุมซ้ายบน)
    cat_text = category.strip() if category else "🔴 ข่าวลิเวอร์พูล"
    badge_bbox = font_badge.getbbox(cat_text)
    badge_tw = badge_bbox[2] - badge_bbox[0]
    badge_th = badge_bbox[3] - badge_bbox[1]

    pad_x, pad_y = 22, 10
    pill_w = badge_tw + (pad_x * 2)
    pill_h = badge_th + (pad_y * 2)

    # วาดพื้นหลัง Pill (ขอบมน)
    draw.rounded_rectangle(
        [side_margin, top_margin, side_margin + pill_w, top_margin + pill_h],
        radius=14,
        fill=theme_cfg["badge_bg"]
    )
    # วาดตัวหนังสือ Badge
    draw.text((side_margin + pad_x, top_margin + pad_y - 2), cat_text, font=font_badge, fill=theme_cfg["badge_text"])

    # 3.2 Page Watermark / Logo (มุมขวาบน)
    if logo_path and os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            # ย่อขนาดให้สูงไม่เกิน 55px
            logo_ratio = logo.width / logo.height
            logo_h = 55
            logo_w = int(logo_h * logo_ratio)
            logo = logo.resize((logo_w, logo_h), Image.Resampling.LANCZOS)
            base_card.paste(logo, (width - side_margin - logo_w, top_margin), logo)
            draw = ImageDraw.Draw(base_card)
        except Exception as e_logo:
            print(f"[CardGenerator] Logo load error: {e_logo}")
    else:
        # วาดป้ายชื่อเพจแบบเรียบหรู
        brand_text = f"🦅 {page_name}"
        b_bbox = font_brand.getbbox(brand_text)
        b_tw = b_bbox[2] - b_bbox[0]
        b_th = b_bbox[3] - b_bbox[1]

        b_pill_w = b_tw + 36
        b_pill_h = b_th + 18
        b_x = width - side_margin - b_pill_w

        draw.rounded_rectangle(
            [b_x, top_margin, b_x + b_pill_w, top_margin + b_pill_h],
            radius=12,
            fill=(15, 15, 20, 200),
            outline=(255, 255, 255, 50),
            width=1
        )
        draw.text((b_x + 18, top_margin + 9), brand_text, font=font_brand, fill=(240, 240, 245))

    # 4. วาดพาดหัวข่าว (Main Headline & Accent Bar)
    # เลือกระดับขนาดฟอนต์ตามความยาวของหัวข้อ
    text_len = len(headline)
    if text_len <= 45:
        font_size = 58
        line_spacing = 18
    elif text_len <= 75:
        font_size = 52
        line_spacing = 16
    else:
        font_size = 46
        line_spacing = 14

    font_headline = get_font(FONT_HEADLINE_PATH, font_size)

    # ตัดบรรทัดภาษาไทย
    max_text_width = width - (side_margin * 2) - 40 # เผื่อเส้น Accent Bar
    wrapped_lines = wrap_thai_text(headline, font_headline, max_text_width, max_lines=3)

    # คำนวณความสูงทั้งหมดของชุดข้อความ
    line_heights = []
    for line in wrapped_lines:
        bbox = font_headline.getbbox(line)
        line_heights.append(bbox[3] - bbox[1])

    total_text_h = sum(line_heights) + (line_spacing * (len(wrapped_lines) - 1))

    # ตำแหน่งเริ่มต้นแกน Y (คำนวณให้อยู่ช่วง 680 - 900px)
    if subtitle:
        font_sub = get_font(FONT_BODY_PATH, 30)
        sub_wrapped = wrap_thai_text(subtitle, font_sub, max_text_width, max_lines=2)
        sub_h = len(sub_wrapped) * 36 + 15
    else:
        sub_wrapped = []
        sub_h = 0

    base_y = height - total_text_h - sub_h - 110 # เหนือ footer 110px

    # วาด Accent Bar แนวตั้ง (สีแดง/ทองประจำทีม) ข้างพาดหัว
    bar_x = side_margin
    bar_w = 10
    bar_y_start = base_y
    bar_y_end = base_y + total_text_h
    draw.rounded_rectangle(
        [bar_x, bar_y_start, bar_x + bar_w, bar_y_end],
        radius=4,
        fill=theme_cfg["bar"]
    )

    # วาดตัวหนังสือ Headline
    text_x = bar_x + bar_w + 22
    cur_y = base_y

    for idx, line in enumerate(wrapped_lines):
        # เงา Drop shadow เพื่อความคมชัดเป็นประกาย
        draw.text((text_x + 2, cur_y + 3), line, font=font_headline, fill=(0, 0, 0, 200))
        # ตัวหนังสือจริงสีขาวบริสุทธิ์
        draw.text((text_x, cur_y), line, font=font_headline, fill=(255, 255, 255))
        cur_y += line_heights[idx] + line_spacing

    # 5. วาด Subtitle / คำโปรย (ถ้ามี)
    if sub_wrapped:
        cur_y += 10
        font_sub = get_font(FONT_BODY_PATH, 30)
        for sub_line in sub_wrapped:
            draw.text((text_x, cur_y), sub_line, font=font_sub, fill=(210, 215, 225))
            cur_y += 38

    # 6. วาดเส้น Bottom Accent Footer Bar
    footer_bar_h = 6
    # ไล่สีแดงไปทองที่ขอบล่างสุด
    for x in range(width):
        r_ratio = x / width
        r = int(theme_cfg["primary"][0] * (1 - r_ratio) + theme_cfg["accent"][0] * r_ratio)
        g = int(theme_cfg["primary"][1] * (1 - r_ratio) + theme_cfg["accent"][1] * r_ratio)
        b = int(theme_cfg["primary"][2] * (1 - r_ratio) + theme_cfg["accent"][2] * r_ratio)
        draw.line([(x, height - footer_bar_h), (x, height)], fill=(r, g, b, 255))

    # 7. บันทึกรูปภาพ
    if not output_path:
        cards_dir = BASE_DIR / "downloads" / "cards"
        cards_dir.mkdir(parents=True, exist_ok=True)
        import time
        output_path = str(cards_dir / f"card_{int(time.time()*1000)}.jpg")

    final_card = base_card.convert("RGB")
    final_card.save(output_path, "JPEG", quality=95, optimize=True)
    return output_path


if __name__ == "__main__":
    # ทดสอบสร้าง Social Card จากภาพตัวอย่าง
    sample_images = list((BASE_DIR / "downloads" / "images").glob("*.jpg"))
    test_img = str(sample_images[0]) if sample_images else None

    test_headline = "คล็อปป์ส่งสัญญาณ! หงส์แดงเตรียมปิดดีลแข้งใหม่ค่าตัวสถิติสโมสรซัมเมอร์นี้"
    test_out = generate_social_card(
        image_path=test_img,
        headline=test_headline,
        category="⚡ ข่าวด่วนลิเวอร์พูล",
        page_name="หงส์นิวส์",
        subtitle="แหล่งข่าววงในเผยการเจรจาคืบหน้ากว่า 90% จ่อเปิดตัวสัปดาห์หน้า",
        theme="lfc"
    )
    print(f"Card generated successfully: {test_out}")
