"""
Script: create_page_branding.py
สร้างรูปโปรไฟล์ (Profile Avatar 1024x1024) และรูปหน้าปก (Cover Banner 1640x924)
สำหรับเพจ Facebook 'ทันข่าว' ด้วยฟอนต์ Kanit-Bold / Prompt-SemiBold คุณภาพสูงระดับสตูดิโอ
"""

import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

BASE_DIR = Path(__file__).resolve().parent
FONTS_DIR = BASE_DIR / "fonts"
OUTPUT_DIR = BASE_DIR / "downloads" / "branding"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FONT_KANIT = FONTS_DIR / "Kanit-Bold.ttf"
FONT_PROMPT = FONTS_DIR / "Prompt-SemiBold.ttf"

def get_font(path, size):
    if path.exists():
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            pass
    return ImageFont.load_default()

# -------------------------------------------------------------
# 1. สร้างรูปโปรไฟล์ (Facebook Profile Picture: 1024x1024)
# -------------------------------------------------------------
def generate_profile_avatar():
    w, h = 1024, 1024
    img = Image.new("RGBA", (w, h), (10, 14, 23, 255))
    draw = ImageDraw.Draw(img)

    # 1.1 พื้นหลังเรเดียลแกรเดียนท์มืดลึก (Deep Radial Glow)
    cx, cy = w // 2, h // 2
    for r in range(512, 0, -8):
        alpha = int(120 * (1 - (r / 512)))
        color = (14, 165, 233, alpha) # Cyan Glow
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)

    # เบลอพื้นหลังแสงให้นุ่มนวล
    img = img.filter(ImageFilter.GaussianBlur(radius=18))
    draw = ImageDraw.Draw(img)

    # 1.2 วงกลม Safe Zone & เส้นเรดาร์เรืองแสงสไตล์ข่าวระดับโลก
    # วงแหวนนอก
    draw.ellipse([cx - 460, cy - 460, cx + 460, cy + 460], outline=(255, 255, 255, 30), width=2)
    # วงแหวนใน
    draw.ellipse([cx - 430, cy - 430, cx + 430, cy + 430], outline=(14, 165, 233, 90), width=3)
    
    # วงโคจรรอบโลโก้ (Orbit arc)
    draw.arc([cx - 390, cy - 390, cx + 390, cy + 390], start=210, end=330, fill=(239, 68, 68, 220), width=6)
    draw.arc([cx - 390, cy - 390, cx + 390, cy + 390], start=30, end=150, fill=(14, 165, 233, 220), width=6)

    # 1.3 ไอคอนลูกโลกดิจิทัล / สัญญาณบรอดแคสต์ (Digital Globe & Signal Waves)
    icon_cy = cy - 130
    globe_r = 110

    # ลูกโลกพื้นหลังเรืองแสงสีฟ้า
    draw.ellipse([cx - globe_r, icon_cy - globe_r, cx + globe_r, icon_cy + globe_r], fill=(15, 23, 42, 240), outline=(56, 189, 248, 220), width=4)
    
    # เส้นละติจูด-ลองจิจูดของลูกโลก
    draw.ellipse([cx - (globe_r * 0.65), icon_cy - globe_r, cx + (globe_r * 0.65), icon_cy + globe_r], outline=(56, 189, 248, 120), width=2)
    draw.line([(cx, icon_cy - globe_r), (cx, icon_cy + globe_r)], fill=(56, 189, 248, 140), width=2)
    draw.line([(cx - globe_r, icon_cy), (cx + globe_r, icon_cy)], fill=(56, 189, 248, 140), width=2)
    draw.line([(cx - int(globe_r*0.85), icon_cy - 45), (cx + int(globe_r*0.85), icon_cy - 45)], fill=(56, 189, 248, 80), width=1)
    draw.line([(cx - int(globe_r*0.85), icon_cy + 45), (cx + int(globe_r*0.85), icon_cy + 45)], fill=(56, 189, 248, 80), width=1)

    # คลื่นสัญญาณวิทยุ/ข่าวสาร (Broadcast pulse waves)
    for wave_r in [145, 185]:
        draw.arc([cx - wave_r, icon_cy - wave_r, cx + wave_r, icon_cy + wave_r], start=215, end=325, fill=(14, 165, 233, 140), width=3)
        draw.arc([cx - wave_r, icon_cy - wave_r, cx + wave_r, icon_cy + wave_r], start=35, end=145, fill=(14, 165, 233, 140), width=3)

    # จุดกะพริบสดสีแดง (Live Red Dot)
    draw.ellipse([cx + 70, icon_cy - 70, cx + 96, icon_cy - 44], fill=(239, 68, 68, 255), outline=(255, 255, 255, 220), width=2)

    # 1.4 ตัวหนังสือชื่อเพจหลัก "ทันข่าว"
    font_main = get_font(FONT_KANIT, 138)
    text = "ทันข่าว"
    bbox = font_main.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = cx - (tw // 2)
    ty = cy + 40

    # เงาตัวหนังสือ
    draw.text((tx + 4, ty + 6), text, font=font_main, fill=(0, 0, 0, 240))
    draw.text((tx + 2, ty + 3), text, font=font_main, fill=(14, 165, 233, 120))
    # ตัวหนังสือสีขาวบริสุทธิ์
    draw.text((tx, ty), text, font=font_main, fill=(255, 255, 255, 255))

    # 1.5 เส้น Accent Bar แยกหมวด
    bar_w = 340
    bar_y = ty + th + 36
    draw.line([(cx - bar_w//2, bar_y), (cx + bar_w//2, bar_y)], fill=(14, 165, 233, 200), width=4)
    # จุดกึ่งกลาง
    draw.ellipse([cx - 6, bar_y - 6, cx + 6, bar_y + 6], fill=(239, 68, 68, 255))

    # 1.6 ป้ายสโลแกน "24 HOURS NEWS UPDATE"
    font_sub = get_font(FONT_PROMPT, 34)
    sub_text = "24 HOURS NEWS UPDATE"
    s_bbox = font_sub.getbbox(sub_text)
    s_tw = s_bbox[2] - s_bbox[0]
    s_th = s_bbox[3] - s_bbox[1]
    s_tx = cx - (s_tw // 2)
    s_ty = bar_y + 24

    pill_pad_x = 26
    pill_pad_y = 8
    draw.rounded_rectangle(
        [s_tx - pill_pad_x, s_ty - pill_pad_y, s_tx + s_tw + pill_pad_x, s_ty + s_th + pill_pad_y + 4],
        radius=14,
        fill=(15, 23, 42, 220),
        outline=(56, 189, 248, 120),
        width=1
    )
    draw.text((s_tx, s_ty), sub_text, font=font_sub, fill=(224, 242, 254, 255))

    out_path = OUTPUT_DIR / "profile_avatar_thai.png"
    img.save(out_path, "PNG")
    print(f"Profile Avatar generated: {out_path}")
    return str(out_path)

# -------------------------------------------------------------
# 2. สร้างรูปหน้าปกเพจ (Facebook Cover Banner: 1640x924)
# -------------------------------------------------------------
def generate_cover_banner():
    w, h = 1640, 924
    img = Image.new("RGBA", (w, h), (8, 12, 20, 255))
    draw = ImageDraw.Draw(img)

    # 2.1 แบ็คกราวด์เส้นกริดดิจิทัล (Cyber News Grid)
    grid_color = (255, 255, 255, 8)
    for x in range(0, w, 60):
        draw.line([(x, 0), (x, h)], fill=grid_color, width=1)
    for y in range(0, h, 60):
        draw.line([(0, y), (w, y)], fill=grid_color, width=1)

    # 2.2 วงรัศมีแสงเรืองรอง (Ambient Lighting Gradients)
    # แสงสีฟ้าด้านซ้ายบน
    for r in range(400, 0, -10):
        draw.ellipse([-100 - r, 200 - r, -100 + r, 200 + r], fill=(14, 165, 233, int(60 * (1 - r/400))))
    # แสงสีแดงขวาล่าง
    for r in range(450, 0, -10):
        draw.ellipse([w - r, h - 150 - r, w + r, h - 150 + r], fill=(239, 68, 68, int(50 * (1 - r/450))))
    # แสงสว่างสีฟ้าตรงกลางขวา
    for r in range(350, 0, -10):
        draw.ellipse([1250 - r, 450 - r, 1250 + r, 450 + r], fill=(30, 58, 138, int(80 * (1 - r/350))))

    img = img.filter(ImageFilter.GaussianBlur(radius=15))
    draw = ImageDraw.Draw(img)

    # 2.3 กราฟิกลูกโลกโฮโลแกรมด้านขวา (Holographic Global Wireframe)
    gw_cx, gw_cy = 1260, 460
    gw_r = 260
    draw.ellipse([gw_cx - gw_r, gw_cy - gw_r, gw_cx + gw_r, gw_cy + gw_r], outline=(56, 189, 248, 100), width=3)
    draw.ellipse([gw_cx - int(gw_r*0.65), gw_cy - gw_r, gw_cx + int(gw_r*0.65), gw_cy + gw_r], outline=(56, 189, 248, 70), width=2)
    draw.ellipse([gw_cx - int(gw_r*0.3), gw_cy - gw_r, gw_cx + int(gw_r*0.3), gw_cy + gw_r], outline=(56, 189, 248, 50), width=1)
    draw.line([(gw_cx - gw_r, gw_cy), (gw_cx + gw_r, gw_cy)], fill=(56, 189, 248, 80), width=2)
    draw.line([(gw_cx, gw_cy - gw_r), (gw_cx, gw_cy + gw_r)], fill=(56, 189, 248, 80), width=2)
    draw.ellipse([gw_cx - int(gw_r*0.86), gw_cy - 110, gw_cx + int(gw_r*0.86), gw_cy + 110], outline=(56, 189, 248, 40), width=1)

    # วงแหวนสัญญาณหมุนรอบลูกโลก
    draw.arc([gw_cx - 330, gw_cy - 330, gw_cx + 330, gw_cy + 330], start=290, end=70, fill=(239, 68, 68, 180), width=4)
    draw.arc([gw_cx - 300, gw_cy - 300, gw_cx + 300, gw_cy + 300], start=120, end=260, fill=(14, 165, 233, 180), width=4)

    # 2.4 ป้ายสถานะ LIVE ด้านซ้ายบน
    tag_x = 120
    tag_y = 190
    font_tag = get_font(FONT_PROMPT, 26)
    tag_text = "เกาะติดสถานการณ์สำคัญรอบโลก • ตลอด 24 ชั่วโมง"
    t_bbox = font_tag.getbbox(tag_text)
    t_w = t_bbox[2] - t_bbox[0]
    t_h = t_bbox[3] - t_bbox[1]

    # Pill สำหรับแท็ก
    draw.rounded_rectangle([tag_x, tag_y, tag_x + t_w + 64, tag_y + t_h + 20], radius=14, fill=(15, 23, 42, 220), outline=(239, 68, 68, 180), width=2)
    # จุดแดง Live
    draw.ellipse([tag_x + 18, tag_y + 11, tag_x + 32, tag_y + 25], fill=(239, 68, 68, 255))
    draw.text((tag_x + 44, tag_y + 7), tag_text, font=font_tag, fill=(240, 245, 255, 255))

    # 2.5 ชื่อแบรนด์หลัก "ทันข่าว" ขนาดใหญ่พิเศษ คมกริบ
    font_title = get_font(FONT_KANIT, 155)
    title_text = "ทันข่าว"
    title_y = tag_y + 60

    # เงาตัวหนังสือ
    draw.text((tag_x + 5, title_y + 7), title_text, font=font_title, fill=(0, 0, 0, 240))
    draw.text((tag_x + 2, title_y + 3), title_text, font=font_title, fill=(14, 165, 233, 140))
    # ตัวหนังสือจริงสีขาวบริสุทธิ์
    draw.text((tag_x, title_y), title_text, font=font_title, fill=(255, 255, 255, 255))

    # ป้ายกำกับเล็กภาษาอังกฤษข้างชื่อ "NEWS NETWORK"
    font_en = get_font(FONT_PROMPT, 38)
    draw.text((tag_x + 480, title_y + 40), "NEWS 24H", font=font_en, fill=(56, 189, 248, 255))
    draw.text((tag_x + 480, title_y + 88), "REALTIME BROADCAST", font=get_font(FONT_PROMPT, 22), fill=(148, 163, 184, 255))

    # 2.6 คำโปรยภาษาไทย
    font_slogan = get_font(FONT_PROMPT, 42)
    slogan_text = "รวดเร็ว แม่นยำ ครบทุกมิติข่าวสารที่คุณต้องรู้"
    slogan_y = title_y + 175
    draw.text((tag_x + 2, slogan_y + 2), slogan_text, font=font_slogan, fill=(0, 0, 0, 200))
    draw.text((tag_x, slogan_y), slogan_text, font=font_slogan, fill=(226, 232, 240, 255))

    # 2.7 แถบหมวดหมู่ข่าว (Category Pills) 4 หมวดหลัก
    cats = [
        ("เทคโนโลยี & AI", (14, 165, 233)),
        ("ธุรกิจ & การเงิน", (16, 185, 129)),
        ("ข่าวกีฬา", (239, 68, 68)),
        ("สถานการณ์โลก", (139, 92, 246)),
    ]

    cat_x = tag_x
    cat_y = slogan_y + 85
    font_cat = get_font(FONT_PROMPT, 28)

    for c_text, c_color in cats:
        c_bbox = font_cat.getbbox(c_text)
        c_w = c_bbox[2] - c_bbox[0]
        c_h = c_bbox[3] - c_bbox[1]
        pill_w = c_w + 50
        pill_h = c_h + 20

        # กล่องหมวดหมู่
        draw.rounded_rectangle([cat_x, cat_y, cat_x + pill_w, cat_y + pill_h], radius=12, fill=(15, 23, 42, 220), outline=c_color, width=2)
        # จุดสีประจำหมวด
        draw.ellipse([cat_x + 16, cat_y + (pill_h//2) - 5, cat_x + 26, cat_y + (pill_h//2) + 5], fill=c_color)
        # ข้อความหมวดหมู่
        draw.text((cat_x + 34, cat_y + 8), c_text, font=font_cat, fill=(255, 255, 255, 255))

        cat_x += pill_w + 18

    # 2.8 แถบสี Accent Bar ใต้รูป (ล่างสุด)
    footer_bar_h = 10
    for x in range(w):
        r_ratio = x / w
        r = int(14 * (1 - r_ratio) + 239 * r_ratio)
        g = int(165 * (1 - r_ratio) + 68 * r_ratio)
        b = int(233 * (1 - r_ratio) + 68 * r_ratio)
        draw.line([(x, h - footer_bar_h), (x, h)], fill=(r, g, b, 255))

    out_path = OUTPUT_DIR / "facebook_cover_thai.png"
    img.save(out_path, "PNG")
    print(f"Cover Banner generated: {out_path}")
    return str(out_path)

if __name__ == "__main__":
    p_path = generate_profile_avatar()
    c_path = generate_cover_banner()
    print("All branding assets generated successfully!")
