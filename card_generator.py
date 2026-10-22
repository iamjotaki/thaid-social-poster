"""
Module: card_generator.py
สร้างภาพกราฟิกข่าวกีฬาระดับพรีเมียม (Social Card) สไตล์สื่อชั้นนำระดับโลก
รองรับการตัดคำภาษาไทยด้วย pythainlp และฟอนต์ Kanit / Prompt
ตัดอิโมจิอัตโนมัติป้องกันตัวอักษรกล่องสี่เหลี่ยม [ ]
"""

import os
import re
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
    "tech": {
        "primary": (14, 165, 233),       # Electric Cyan / Sky Blue
        "accent": (56, 189, 248),
        "badge_bg": (14, 165, 233, 255),  # Solid High Contrast
        "badge_text": (255, 255, 255),
        "bar": (14, 165, 233),
    },
    "ai": {
        "primary": (139, 92, 246),      # Vivid Violet / Purple
        "accent": (167, 139, 250),
        "badge_bg": (139, 92, 246, 255),
        "badge_text": (255, 255, 255),
        "bar": (139, 92, 246),
    },
    "biz": {
        "primary": (16, 185, 129),      # Emerald Green
        "accent": (52, 211, 153),
        "badge_bg": (16, 185, 129, 255),
        "badge_text": (255, 255, 255),
        "bar": (16, 185, 129),
    },
    "sports": {
        "primary": (239, 68, 68),       # Vibrant Red
        "accent": (252, 165, 165),
        "badge_bg": (239, 68, 68, 255),
        "badge_text": (255, 255, 255),
        "bar": (239, 68, 68),
    },
    "breaking": {
        "primary": (225, 29, 72),       # Rose Crimson
        "accent": (253, 164, 175),
        "badge_bg": (225, 29, 72, 255),
        "badge_text": (255, 255, 255),
        "bar": (225, 29, 72),
    },
    "tactics": {
        "primary": (14, 165, 233),       # Cyan / Sky
        "accent": (56, 189, 248),
        "badge_bg": (14, 165, 233, 255),
        "badge_text": (255, 255, 255),
        "bar": (14, 165, 233),
    },
    "gold": {
        "primary": (245, 158, 11),      # Amber Gold
        "accent": (253, 230, 138),
        "badge_bg": (245, 158, 11, 255),
        "badge_text": (15, 15, 18),
        "bar": (245, 158, 11),
    },
    "lfc": {
        "primary": (200, 16, 46),       # #C8102E (LFC Red)
        "accent": (246, 235, 97),       # #F6EB61 (LFC Gold)
        "badge_bg": (200, 16, 46, 255),
        "badge_text": (255, 255, 255),
        "bar": (200, 16, 46),
    }
}

def strip_emojis(text: str) -> str:
    """ลบอีโมจิและอักขระพิเศษที่ฟอนต์ Kanit/Prompt เรนเดอร์ไม่ติด เพื่อป้องกันกล่องสี่เหลี่ยม [ ]"""
    if not text:
        return ""
    # ลบ Unicode Emojis ทุกช่วง
    cleaned = re.sub(r'[\U00010000-\U0010ffff]', '', text)
    cleaned = re.sub(r'[\u2000-\u3300]', '', cleaned)
    cleaned = re.sub(r'[\uFE00-\uFE0F]', '', cleaned)
    # ลบเครื่องหมายตกแต่ง markdown
    cleaned = cleaned.replace("**", "").replace("*", "").replace("#", "").replace('`', '')
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def get_font(path, size):
    """โหลดฟอนต์พร้อม fallback"""
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
        bbox = font.getbbox(test_line)
        w_width = bbox[2] - bbox[0]

        if w_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
                current_line = w
            else:
                lines.append(w)
                current_line = ""

            if len(lines) >= max_lines:
                break

    if current_line and len(lines) < max_lines:
        lines.append(current_line)

    if len(lines) == max_lines and len(words) > 0:
        last = lines[-1]
        if not last.endswith("..."):
            lines[-1] = last.rstrip() + "..."

    return lines

def generate_social_card(
    image_path: str,
    headline: str,
    category: str = "ข่าวเด่น",
    page_name: str = None,
    subtitle: str = None,
    logo_path: str = None,
    output_path: str = None,
    theme: str = "tech",
    width: int = 1080,
    height: int = 1080
) -> str:
    """
    สร้างภาพกราฟิกข่าว Social Card (1080x1080)
    :param image_path: ที่อยู่ภาพต้นฉบับ
    :param headline: พาดหัวข่าวหลัก (ภาษาไทย)
    :param category: หมวดหมู่ข่าว (แสดงใน Tag มุมซ้ายบน)
    :param page_name: ชื่อเพจ (แสดงใน Watermark มุมขวาบน)
    :param subtitle: ข้อความเสริม หรือ โควทเด่น (ไม่ใส่ก็ได้)
    :param logo_path: โลโก้เพจ (ถ้ามี)
    :param output_path: ที่อยู่ไฟล์ผลลัพธ์
    :param theme: ธีมสี (tech, ai, biz, sports, breaking, gold, lfc)
    :return: path ของไฟล์ที่เซฟสำเร็จ
    """
    theme_cfg = THEMES.get(theme, THEMES.get("tech", THEMES["breaking"]))

    # 1. โหลดและจัดการภาพพื้นหลัง (Smart Zoom & Crop to 1080x1080)
    if image_path and os.path.exists(image_path):
        try:
            raw_img = Image.open(image_path).convert("RGB")
        except Exception as e:
            print(f"[CardGenerator] Error opening image {image_path}: {e}")
            raw_img = Image.new("RGB", (width, height), (16, 18, 27))
    else:
        raw_img = Image.new("RGB", (width, height), (16, 18, 27))

    src_w, src_h = raw_img.size
    target_ratio = width / height
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        new_w = int(src_h * target_ratio)
        offset_x = (src_w - new_w) // 2
        crop_box = (offset_x, 0, offset_x + new_w, src_h)
    else:
        new_h = int(src_w / target_ratio)
        offset_y = max(0, int((src_h - new_h) * 0.22))
        crop_box = (0, offset_y, src_w, min(src_h, offset_y + new_h))

    cropped_img = raw_img.crop(crop_box).resize((width, height), Image.Resampling.LANCZOS)

    # ปรับแต่งภาพให้คมชัด สีสันสดใส น่าดึงดูด
    enhancer = ImageEnhance.Color(cropped_img)
    cropped_img = enhancer.enhance(1.15)
    contrast_enhancer = ImageEnhance.Contrast(cropped_img)
    cropped_img = contrast_enhancer.enhance(1.08)

    base_card = cropped_img.convert("RGBA")

    # 2. เลเยอร์เงาไล่โทน (Dark Gradient Overlays)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    # 2.1 เงาบน (Top Vignette สำหรับให้อ่าน Badge / Logo ได้ชัด 100%)
    top_vignette_height = 220
    for y in range(top_vignette_height):
        alpha = int(190 * (1 - (y / top_vignette_height) ** 1.3))
        overlay_draw.line([(0, y), (width, y)], fill=(8, 10, 16, alpha))

    # 2.2 เงาล่าง (Bottom Gradient ปูพื้นให้อ่านพาดหัวข่าวชัดเจน 100%)
    grad_start = int(height * 0.36)
    grad_len = height - grad_start

    for y in range(grad_start, height):
        ratio = (y - grad_start) / grad_len
        curve = ratio ** 1.7
        alpha = int(248 * min(1.0, curve))
        overlay_draw.line([(0, y), (width, y)], fill=(6, 8, 14, alpha))

    base_card = Image.alpha_composite(base_card, overlay)
    draw = ImageDraw.Draw(base_card)

    # 3. วาดส่วนหัว (Top Bar: Category Badge & Page Brand Badge)
    top_margin = 46
    side_margin = 54

    font_badge = get_font(FONT_HEADLINE_PATH, 30)  # ใช้ Kanit-Bold ตัวหนา คมชัด 30px
    font_brand = get_font(FONT_HEADLINE_PATH, 28)  # Kanit-Bold 28px

    # 3.1 Category Badge (มุมซ้ายบน) - ป้ายหมวดหมู่ชัดเจน สีสดใส มีจุด Accent Dot
    cat_text = strip_emojis(category).strip() or "ข่าวเด่น"
    cat_bbox = font_badge.getbbox(cat_text)
    cat_tw = cat_bbox[2] - cat_bbox[0]
    cat_th = cat_bbox[3] - cat_bbox[1]

    dot_radius = 5
    dot_margin = 12
    pad_x = 22
    pad_y = 10
    pill_w = pad_x + (dot_radius * 2) + dot_margin + cat_tw + pad_x
    pill_h = cat_th + (pad_y * 2) + 6

    # วาดเงา Pill หมวดหมู่
    draw.rounded_rectangle(
        [side_margin + 2, top_margin + 3, side_margin + pill_w + 2, top_margin + pill_h + 3],
        radius=14,
        fill=(0, 0, 0, 140)
    )
    # วาดพื้นหลัง Pill หมวดหมู่ (Solid High-Contrast)
    draw.rounded_rectangle(
        [side_margin, top_margin, side_margin + pill_w, top_margin + pill_h],
        radius=14,
        fill=theme_cfg["badge_bg"]
    )
    # วาดจุดสีขาว Accent Dot สไตล์สำนักข่าวสากล
    dot_cx = side_margin + pad_x + dot_radius
    dot_cy = top_margin + (pill_h // 2)
    draw.ellipse(
        [dot_cx - dot_radius, dot_cy - dot_radius, dot_cx + dot_radius, dot_cy + dot_radius],
        fill=(255, 255, 255)
    )
    # วาดตัวหนังสือหมวดหมู่สีขาวคมชัด
    text_x = dot_cx + dot_radius + dot_margin
    text_y = top_margin + pad_y - 1
    draw.text((text_x, text_y), cat_text, font=font_badge, fill=theme_cfg["badge_text"])

    # 3.2 Page Brand Badge (มุมขวาบน) - ป้ายชื่อเพจ โดดเด่น ชัดเจน ไม่มีกล่องสี่เหลี่ยม
    if logo_path and os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            logo_ratio = logo.width / logo.height
            logo_h = 56
            logo_w = int(logo_h * logo_ratio)
            logo = logo.resize((logo_w, logo_h), Image.Resampling.LANCZOS)
            base_card.paste(logo, (width - side_margin - logo_w, top_margin), logo)
            draw = ImageDraw.Draw(base_card)
        except Exception as e_logo:
            print(f"[CardGenerator] Logo load error: {e_logo}")
    else:
        raw_pname = page_name or os.getenv("DEFAULT_PAGE_NAME", "ทันข่าว")
        brand_name = strip_emojis(raw_pname).strip() or "ทันข่าว"

        b_bbox = font_brand.getbbox(brand_name)
        b_tw = b_bbox[2] - b_bbox[0]
        b_th = b_bbox[3] - b_bbox[1]

        b_pad_x = 24
        b_pad_y = 10
        b_pill_w = b_tw + (b_pad_x * 2) + 20
        b_pill_h = b_th + (b_pad_y * 2) + 6
        b_x = width - side_margin - b_pill_w

        # เงาของ Brand Badge
        draw.rounded_rectangle(
            [b_x + 2, top_margin + 3, b_x + b_pill_w + 2, top_margin + b_pill_h + 3],
            radius=14,
            fill=(0, 0, 0, 140)
        )
        # กล่องพื้นหลัง Brand Badge สีเข้มกึ่งทึบ ขอบขาวเด่นชัด
        draw.rounded_rectangle(
            [b_x, top_margin, b_x + b_pill_w, top_margin + b_pill_h],
            radius=14,
            fill=(12, 16, 26, 240),
            outline=(255, 255, 255, 140),
            width=2
        )
        # จุดสีประจำธีมใน Brand Badge
        b_dot_cx = b_x + b_pad_x
        b_dot_cy = top_margin + (b_pill_h // 2)
        draw.ellipse(
            [b_dot_cx - 4, b_dot_cy - 4, b_dot_cx + 4, b_dot_cy + 4],
            fill=theme_cfg["primary"]
        )
        # ข้อความชื่อเพจตัวหนาสีขาว
        draw.text((b_dot_cx + 14, top_margin + b_pad_y - 1), brand_name, font=font_brand, fill=(255, 255, 255))

    # 4. วาดพาดหัวข่าวภาษาไทย (Main Thai Headline)
    clean_hl = strip_emojis(headline)
    # ตัดเครื่องหมายคำพูดและดอกจันตกค้าง
    clean_hl = clean_hl.replace('"', '').replace("'", "").replace("“", "").replace("”", "").strip()

    text_len = len(clean_hl)
    if text_len <= 45:
        font_size = 56
        line_spacing = 18
    elif text_len <= 75:
        font_size = 50
        line_spacing = 16
    else:
        font_size = 44
        line_spacing = 14

    font_headline = get_font(FONT_HEADLINE_PATH, font_size)

    max_text_width = width - (side_margin * 2) - 44
    wrapped_lines = wrap_thai_text(clean_hl, font_headline, max_text_width, max_lines=3)

    line_heights = []
    for line in wrapped_lines:
        bbox = font_headline.getbbox(line)
        line_heights.append(bbox[3] - bbox[1])

    total_text_h = sum(line_heights) + (line_spacing * (len(wrapped_lines) - 1))

    if subtitle:
        font_sub = get_font(FONT_BODY_PATH, 28)
        clean_sub = strip_emojis(subtitle)
        sub_wrapped = wrap_thai_text(clean_sub, font_sub, max_text_width, max_lines=2)
        sub_h = len(sub_wrapped) * 36 + 15
    else:
        sub_wrapped = []
        sub_h = 0

    base_y = height - total_text_h - sub_h - 110

    # วาด Accent Bar แนวตั้งข้างพาดหัว
    bar_x = side_margin
    bar_w = 12
    bar_y_start = base_y
    bar_y_end = base_y + total_text_h
    draw.rounded_rectangle(
        [bar_x, bar_y_start, bar_x + bar_w, bar_y_end],
        radius=5,
        fill=theme_cfg["bar"]
    )

    # วาดตัวหนังสือ Headline พร้อม Drop Shadow
    text_x = bar_x + bar_w + 22
    cur_y = base_y

    for idx, line in enumerate(wrapped_lines):
        # เงาสีดำเข้มรอบทิศทางให้อ่านง่ายบนทุกภาพ
        draw.text((text_x + 3, cur_y + 3), line, font=font_headline, fill=(0, 0, 0, 240))
        draw.text((text_x + 1, cur_y + 1), line, font=font_headline, fill=(0, 0, 0, 180))
        # ตัวหนังสือจริงสีขาวบริสุทธิ์
        draw.text((text_x, cur_y), line, font=font_headline, fill=(255, 255, 255))
        cur_y += line_heights[idx] + line_spacing

    # 5. วาด Subtitle (ถ้ามี)
    if sub_wrapped:
        cur_y += 10
        font_sub = get_font(FONT_BODY_PATH, 28)
        for sub_line in sub_wrapped:
            draw.text((text_x + 2, cur_y + 2), sub_line, font=font_sub, fill=(0, 0, 0, 220))
            draw.text((text_x, cur_y), sub_line, font=font_sub, fill=(225, 230, 240))
            cur_y += 36

    # 6. แถบสี Accent Footer Bar ด้านล่างสุด
    footer_bar_h = 7
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
    sample_images = list((BASE_DIR / "downloads" / "images").glob("*.jpg"))
    test_img = str(sample_images[0]) if sample_images else None

    test_headline = "เปิดตัวยิ่งใหญ่! Apple ติดตั้งโมเดล iPhone ยักษ์กลาง Fifth Avenue ต้อนรับการเปิดตัววันศุกร์นี้"
    test_out = generate_social_card(
        image_path=test_img,
        headline=test_headline,
        category="ข่าวเทคโนโลยี & AI",
        page_name="ทันข่าว",
        subtitle="เตรียมพร้อมรับกระแสแฟนคลับทั่วโลกเข้าคิวสัมผัสนวัตกรรมใหม่ล่าสุด",
        theme="tech"
    )
    print(f"Card generated successfully: {test_out}")
