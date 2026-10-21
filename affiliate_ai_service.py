"""
Module: affiliate_ai_service.py
ระบบดึงข้อมูลสินค้า Shopee, Lazada, TikTok และใช้ Gemini AI สร้างคำโปรโมทสินค้า (Affiliate Copywriting)
พร้อมส่งโพสต์หรือตั้งเวลาบน Facebook Pages
"""

import os
import sys
import re
import json
import random
import urllib.parse
from typing import Dict, Any, Optional, List
import requests
from bs4 import BeautifulSoup

# ปรับ encoding ของ stdout/stderr บน Windows
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from config import GEMINI_API_KEY
import database

# รายชื่อโมเดล Gemini Fallback
GEMINI_MODELS = [
    'gemini-2.5-flash',
    'gemini-2.0-flash',
    'gemini-1.5-flash'
]

COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'th,en-US;q=0.9,en;q=0.8',
    'Cache-Control': 'no-cache',
}

def detect_platform(url: str) -> str:
    """ระบุแพลตฟอร์มสินค้าจาก URL"""
    if not url:
        return 'general'
    u = url.lower()
    if 'shopee' in u or 'shp.ee' in u:
        return 'shopee'
    elif 'lazada' in u or 'laz.' in u:
        return 'lazada'
    elif 'tiktok' in u:
        return 'tiktok'
    return 'general'

def fetch_product_details(url: str) -> Dict[str, Any]:
    """
    ดึงข้อมูลสินค้าจาก Shopee / Lazada / TikTok หรือ URL ทั่วไป
    สกัด: ชื่อสินค้า, รูปภาพหลัก, ราคา, รายละเอียด, แพลตฟอร์ม
    """
    clean_url = url.strip()
    platform = detect_platform(clean_url)
    
    result = {
        "success": True,
        "platform": platform,
        "url": clean_url,
        "title": "",
        "image": "",
        "price": "",
        "desc": "",
        "raw_platform_name": "Shopee" if platform == "shopee" else ("Lazada" if platform == "lazada" else ("TikTok Shop" if platform == "tiktok" else "Online Store"))
    }

    try:
        session = requests.Session()
        session.headers.update(COMMON_HEADERS)
        
        # ตาม Redirect เพื่อถอดรหัส Short link เช่น s.shopee.co.th, vt.tiktok.com
        resp = session.get(clean_url, timeout=12, allow_redirects=True)
        final_url = resp.url
        result["final_url"] = final_url
        
        # อัปเดต platform อีกครั้งหลัง redirect
        platform = detect_platform(final_url)
        result["platform"] = platform
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 1. ค้นหาชื่อสินค้า (Title)
        og_title = soup.find('meta', property='og:title') or soup.find('meta', attrs={'name': 'twitter:title'})
        if og_title and og_title.get('content'):
            result["title"] = og_title['content'].strip()
        elif soup.title and soup.title.string:
            result["title"] = soup.title.string.strip()
            
        # ลบชื่อเว็บไซต์ส่วนเกินจาก Title เช่น | Shopee Thailand, | Lazada.co.th
        if result["title"]:
            result["title"] = re.sub(r'(\s*\|\s*(Shopee|Lazada|TikTok|ช้อปปี้|ลาซาด้า).*)$', '', result["title"], flags=re.IGNORECASE).strip()
            
        # 2. ค้นหารูปภาพสินค้า (Image)
        og_image = soup.find('meta', property='og:image') or soup.find('meta', attrs={'name': 'twitter:image'})
        if og_image and og_image.get('content'):
            result["image"] = og_image['content'].strip()
            
        # 3. ค้นหารายละเอียดสินค้า (Description)
        og_desc = soup.find('meta', property='og:description') or soup.find('meta', attrs={'name': 'description'})
        if og_desc and og_desc.get('content'):
            result["desc"] = og_desc['content'].strip()
            
        # 4. ค้นหาราคา (Price)
        price_tag = (
            soup.find('meta', property='product:price:amount') or
            soup.find('meta', attrs={'name': 'twitter:data1'}) or
            soup.find('meta', property='og:price:amount')
        )
        if price_tag and price_tag.get('content'):
            result["price"] = price_tag['content'].strip()
        else:
            # ลองค้นหาตัวเลขราคาจากข้อความ desc หรือ title
            price_match = re.search(r'฿\s*([\d,]+(?:\.\d{2})?)|(\d[\d,]+)\s*บาท', (result["desc"] or "") + " " + (result["title"] or ""))
            if price_match:
                result["price"] = price_match.group(1) or price_match.group(2)
                
    except Exception as e:
        print(f"[Affiliate Scraper Warning]: {e}")
        # แม้ fetch ล้มเหลวจากบ็อทบล็อก ก็ยังคืนค่าเพื่อเปิดให้ผู้ใช้ใส่เองได้
        result["fetch_warning"] = str(e)

    # Fallback ชื่อสินค้าหากหาไม่เจอ
    if not result["title"]:
        parsed = urllib.parse.urlparse(clean_url)
        path_parts = [p for p in parsed.path.split('/') if p]
        if path_parts:
            slug = path_parts[0] if path_parts[0] != 'product' else (path_parts[1] if len(path_parts) > 1 else '')
            slug_clean = urllib.parse.unquote(slug).replace('-', ' ').replace('_', ' ')
            if len(slug_clean) > 3:
                result["title"] = slug_clean.capitalize()
                
    if not result["title"]:
        result["title"] = f"สินค้ายอดนิยม ({result['raw_platform_name']})"

    return result

def get_best_gemini_key(user_id: Optional[int] = None) -> Optional[str]:
    """ดึง Gemini API Key ที่พร้อมใช้งาน (ดึงของ User ก่อน หากไม่มีดึงจาก Config)"""
    if user_id:
        try:
            keys = database.get_active_api_keys_for_user(user_id)
            if keys:
                return keys[0]
        except Exception:
            pass
    return GEMINI_API_KEY or None

def generate_affiliate_caption(
    product_name: str,
    product_desc: str = "",
    price: str = "",
    affiliate_url: str = "",
    platform: str = "general",
    style: str = "flash_sale",
    page_context: str = "เพจกีฬาและไลฟ์สไตล์",
    user_id: Optional[int] = None
) -> str:
    """
    ใช้ Google Gemini สร้างแคปชั่นโปรโมทสินค้าป้ายยา Affiliate ตามสไตล์ที่เลือก
    styles:
      - 'flash_sale': ดีลโปรโมชัน ด่วนจำกัดเวลา โค้ดส่งฟรี ลดราคาเดือด
      - 'review': รีวิวป้ายยาจากผู้ใช้จริง เล่าปัญหา -> ทางแก้ -> จุดเด่น
      - 'fan_story': สไตล์คอบอล/แฟนเพจ โยงเข้ากับแมตช์เดย์หรือไลฟ์สไตล์ดูบอล
      - 'minimal': สั้นกระชับ แปะพิกัดตรงจุด อ่านง่ายใน 5 วินาที
    """
    platform_name = {
        "shopee": "Shopee",
        "lazada": "Lazada",
        "tiktok": "TikTok Shop"
    }.get(platform, "ออนไลน์")

    price_str = f"ราคาพิเศษเพียง {price} บาท" if price else "ราคาโปรโมชันพิเศษ"
    aff_link = affiliate_url.strip() if affiliate_url else "👉 [ลิงก์สั่งซื้อ]"

    prompt = f"""
คุณเป็น Copywriter มืออาชีพระดับท็อปด้าน Affiliate Marketing และ Social Media Content Creator ในไทย
หน้าที่ของคุณคือ เขียนโพสต์ Facebook โปรโมทสินค้าชิ้นนี้เพื่อสร้างยอดคลิกและยอดซื้อ (High CTR & Conversion Rate)

[ข้อมูลสินค้า]
- ชื่อสินค้า: {product_name}
- รายละเอียด/จุดเด่น: {product_desc or 'สินค้าคุณภาพดี การันตีของแท้ 100%'}
- ราคา: {price_str}
- แพลตฟอร์ม: {platform_name}
- ลิงก์ Affiliate ของเรา: {aff_link}
- กลุ่มเป้าหมายของเพจ: {page_context}

[สไตล์การเขียนที่ต้องการ: {style.upper()}]
{_get_style_instruction(style, platform_name, aff_link)}

[กฎเหล็กและข้อกำหนด]
1. ใช้ภาษาไทยเป็นธรรมชาติ น่าอ่าน น่าเชื่อถือ เหมือนคนเล่นโซเชียลแนะนำของดีจริงๆ ไม่แข็งทื่อเหมือนแปลจากภาษาอังกฤษ
2. ใส่ Emojis ประกอบให้น่าสนใจ และจัดย่อหน้าให้อ่านง่าย สบายตา
3. ต้องมีส่วน Call-to-Action (CTA) ชี้เป้าให้กดซื้อผ่านลิงก์อย่างชัดเจน
4. จบด้วย Hashtags ที่ตรงกลุ่มเป้าหมาย (เช่น #ShopeeTH #LazadaTH #TikTokShopครีเอเตอร์ #พิกัดของดี #รีวิว #ของมันต้องมี)
5. ห้ามใส่คำว่า [ข้อความที่ AI ตอบ] หรือส่วนอธิบายเพิ่มเติมใดๆ ให้ส่งออกมาเฉพาะข้อความโพสต์ Facebook เท่านั้น!
"""

    api_key = get_best_gemini_key(user_id)
    if not api_key or api_key.startswith("your_"):
        # ใช้ High Quality Mock Generator
        return generate_mock_affiliate_caption(product_name, product_desc, price, aff_link, platform_name, style)

    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        
        last_error = None
        for model in GEMINI_MODELS:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt
                )
                if response and response.text:
                    if user_id:
                        database.record_api_key_usage(api_key)
                    return response.text.strip()
            except Exception as e:
                last_error = e
                continue
                
        print(f"[Gemini Affiliate Error all models failed]: {last_error}")
        return generate_mock_affiliate_caption(product_name, product_desc, price, aff_link, platform_name, style)
    except Exception as e:
        print(f"[Gemini Client Init Error]: {e}")
        return generate_mock_affiliate_caption(product_name, product_desc, price, aff_link, platform_name, style)

def _get_style_instruction(style: str, platform_name: str, aff_link: str) -> str:
    if style == "flash_sale":
        return f"""
- โทน: ไฟลุก ด่วน ลดแหลก Flash Sale โค้ดส่งฟรี ป้ายแดง
- เปิดหัว: พาดหัวดึงดูดสายตาด้วยตัวเลขหรือโปรโมชันด่วน
- เนื้อหา: บอกความคุ้มค่า ส่วนลด และรีบจัดก่อนโค้ดหมดหรือสินค้าหมดสต็อก
- ชี้เป้า: สั่งซื้อทันทีที่ {platform_name}
"""
    elif style == "review":
        return f"""
- โทน: ป้ายยา รีวิวบอกต่อจากผู้ใช้จริง ซื่อตรง เป็นมิตร
- เปิดหัว: เล่าปัญหาที่คนทั่วไปเจอ หรือความประทับใจแรกที่ได้ลอง
- เนื้อหา: ไฮไลต์จุดเด่น 3 ข้อ ที่ทำให้สินค้านี้คุ้มค่ากว่าของทั่วไป
- ชี้เป้า: แนะนำพิกัดร้านแท้ ส่งไว ที่ {platform_name}
"""
    elif style == "fan_story":
        return f"""
- โทน: แฟนบอลตัวจริง / ไลฟ์สไตล์คอกีฬา / เพื่อนคุยกับเพื่อน
- เปิดหัว: โยงเข้ากับบรรยากาศการดูบอล วันแข่ง หรือการเชียร์ทีมรัก
- เนื้อหา: แนะนำไอเทมที่ต้องมีติดบ้าน หรือใส่ไปเชียร์บอลแล้วเท่
- ชี้เป้า: ชี้พิกัดไอเทมเด็ดที่ {platform_name}
"""
    else: # minimal
        return f"""
- โทน: สั้น กระชับ ตรงประเด็น อ่านจบใน 5 วินาที
- เปิดหัว: บอกชื่อสินค้าและราคาคุ้มๆ
- เนื้อหา: สรุปจุดเด่น 2-3 บรรทัด
- ชี้เป้า: แปะพิกัดลิงก์สั่งซื้อทันที
"""

def generate_mock_affiliate_caption(
    product_name: str,
    product_desc: str,
    price: str,
    aff_link: str,
    platform_name: str,
    style: str
) -> str:
    """สร้างข้อความโปรโมทสินค้าแบบมืออาชีพเมื่อยังไม่ได้เชื่อม Gemini API Key"""
    price_badge = f"🔥 ราคาเพียง {price}.- เท่านั้น!" if price else "🔥 ราคาโปรโมชันพิเศษลดแหลก!"

    if style == "flash_sale":
        return f"""⚡️ ดีลเดือด FLASH SALE! ใครตามหาอยู่ รีบกดด่วนก่อนโค้ดหมด! 🔴

👉 {product_name}
{price_badge}

ของดีที่หลายคนตามหา การันตีคุณภาพและความคุ้มค่า 100%
📦 สต็อกเหลือน้อยมาก + มีโค้ดส่งฟรีและส่วนลดจำกัดสิทธิ์วันนี้

🛒 สั่งซื้อของแท้คลิกพิกัดนี้เลย:
🔗 {aff_link}
(ช้อปง่าย ปลอดภัย มีเก็บเงินปลายทางที่ {platform_name})

#ShopeeTH #LazadaTH #TikTokShopครีเอเตอร์ #พิกัดของดี #FlashSale #ลดราคาพิเศษ #ของมันต้องมี"""

    elif style == "review":
        return f"""⭐ ป้ายยาบอกต่อ! ของดีที่ต้องมีติดบ้าน ใช้แล้วประทับใจจริง 💬

วันนี้ขอมาแชร์ไอเทมเด็ด: **{product_name}**
ใครที่กำลังมองหาอยู่ บอกเลยว่าตัวนี้ตอบโจทย์มาก ทั้งเรื่องวัสดุ ฟังก์ชัน และความคุ้มค่า คุ้มราคาเกินเบอร์มากครับ 👍

{price_badge}

📌 สรุปจุดเด่น:
• ใช้งานง่าย ตอบโจทย์ชีวิตประจำวัน
• วัสดุแข็งแรงทนทาน คุณภาพตรงปก 100%
• รีวิวจากผู้ใช้จริงเพียบ มั่นใจได้

🛒 พิกัดร้านแท้ ส่งไว ชี้เป้าที่นี่ครับ:
👉 {aff_link}

#รีวิวของดี #ของมันต้องมี #ป้ายยา #พิกัดช้อปปิ้ง #{platform_name}TH"""

    elif style == "fan_story":
        return f"""🔴 ไอเทมเด็ดที่เด็กหงส์และคอบอลต้องมีติดบ้าน! ⚽️🔥

สายเชียร์บอลต้องถูกใจสิ่งนี้: **{product_name}**
จัดมาไว้ใช้ตอนนั่งดูบอล หรือสะสมก็เข้ากันสุดๆ เพิ่มอรรถรสในการเชียร์ทีมรักแบบเต็มพิกัด!

{price_badge}

จะซื้อใช้เอง หรือเป็นของขวัญให้เพื่อนคอบอลก็การันตีความเท่แน่นอน ใครยังไม่มีรีบจัดเลยครับ!

🛒 จิ้มพิกัดสั่งซื้อได้ที่นี่เลย:
👉 {aff_link}

#เด็กหงส์ #TheKop #ลิเวอร์พูล #พิกัดของดี #{platform_name}TH #คอบอลต้องมี"""

    else: # minimal
        return f"""📌 ชี้เป้าของดี: {product_name}

{price_badge}
คุณภาพตรงปก ส่งไว การันตีของแท้ 100%

🛒 สั่งซื้อคลิกเลย:
👉 {aff_link}

#พิกัดของดี #{platform_name}TH #ของมันต้องมี"""
