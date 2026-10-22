import os
import re
import json
import urllib.parse
from typing import List, Dict, Optional
import config
from ai_rewriter import get_active_api_key

CANDIDATE_MODELS = [
    'gemini-flash-lite-latest',
    'gemini-flash-latest',
    'gemini-3.5-flash-lite',
    'gemini-3.5-flash',
    'gemini-2.5-flash-lite'
]

def generate_fallback_feeds_for_topic(topic: str) -> List[Dict]:
    """สร้างรายการ 10 RSS Feeds คุณภาพสูงสำรองสำหรับหัวข้อที่ผู้ใช้ค้นหา (กรณี AI ขัดข้อง)"""
    encoded_topic = urllib.parse.quote(topic)
    
    # คำศัพท์และแนวทางค้นหาภาษาอังกฤษเบื้องต้น
    topic_clean = topic.strip()
    
    return [
        {
            "name": f"Google News: ข่าวยอดนิยม {topic_clean}",
            "url": f"https://news.google.com/rss/search?q={encoded_topic}+when:7d&hl=th&gl=TH&ceid=TH:th",
            "site": "news.google.com",
            "description": f"อัปเดตข่าวสารและบทความล่าสุดเกี่ยวกับ '{topic_clean}' จากสำนักข่าวชั้นนำ",
            "category": topic_clean
        },
        {
            "name": f"Google News: บทวิเคราะห์และเจาะลึก {topic_clean}",
            "url": f"https://news.google.com/rss/search?q={encoded_topic}+insight+when:7d&hl=en-US&gl=US&ceid=US:en",
            "site": "news.google.com (Global)",
            "description": f"รวมบทวิเคราะห์และรายงานเจาะลึกระดับโลกเกี่ยวกับ '{topic_clean}'",
            "category": "บทวิเคราะห์"
        },
        {
            "name": f"Google News: ประเด็นร้อนและกระแสโลก {topic_clean}",
            "url": f"https://news.google.com/rss/search?q={encoded_topic}+trending+when:3d&hl=en-US&gl=US&ceid=US:en",
            "site": "news.google.com (Trending)",
            "description": f"เกาะติดประเด็นร้อนที่ผู้คนทั่วโลกกำลังพูดถึงเกี่ยวกับ '{topic_clean}'",
            "category": "เทรนด์โลก"
        },
        {
            "name": f"The Verge - ข่าวและเทรนด์ร่วมสมัย",
            "url": "https://www.theverge.com/rss/index.xml",
            "site": "theverge.com",
            "description": "นิตยสารเทคโนโลยี วิทยาศาสตร์ และวัฒนธรรมดิจิทัลชั้นนำระดับโลก (มีภาพความละเอียดสูง)",
            "category": "นิตยสารออนไลน์"
        },
        {
            "name": f"Engadget - นวัตกรรมและอุปกรณ์ใหม่",
            "url": "https://www.engadget.com/rss.xml",
            "site": "engadget.com",
            "description": "รายงานแกดเจ็ต นวัตกรรม และสาระน่ารู้ระดับสากล",
            "category": "แกดเจ็ต & นวัตกรรม"
        },
        {
            "name": f"Reddit ชุมชนแลกเปลี่ยนเรื่อง {topic_clean}",
            "url": f"https://www.reddit.com/r/all/search.rss?q={encoded_topic}&sort=top&t=week",
            "site": "reddit.com",
            "description": f"กระทู้ยอดนิยมที่มีการแลกเปลี่ยนพูดคุยเกี่ยวกับ '{topic_clean}' มากที่สุดในสัปดาห์นี้",
            "category": "เว็บบอร์ดสากล"
        },
        {
            "name": f"ไทยรัฐออนไลน์ - ข่าวด่วนประเด็นร้อน",
            "url": "https://www.thairath.co.th/rss/news",
            "site": "thairath.co.th",
            "description": "สำนักข่าวภาษาไทยอันดับ 1 รายงานเหตุการณ์ปัจจุบันและสาระน่ารู้ตลอด 24 ชั่วโมง",
            "category": "สำนักข่าวไทย"
        },
        {
            "name": f"ข่าวสดออนไลน์ - เกาะติดสถานการณ์",
            "url": "https://www.khaosod.co.th/feed",
            "site": "khaosod.co.th",
            "description": "สำนักข่าวออนไลน์ยอดนิยม อัปเดตข่าวด่วนและเรื่องน่าสนใจรวดเร็ว",
            "category": "สำนักข่าวไทย"
        },
        {
            "name": f"Google News: สาระความรู้และงานวิจัย {topic_clean}",
            "url": f"https://news.google.com/rss/search?q={encoded_topic}+research+discovery+when:14d&hl=en-US&gl=US&ceid=US:en",
            "site": "news.google.com (Research)",
            "description": f"รวมงานวิจัยและการค้นพบใหม่ๆ เกี่ยวกับ '{topic_clean}'",
            "category": "ความรู้ & วิจัย"
        },
        {
            "name": f"BBC News - รายงานสถานการณ์รอบโลก",
            "url": "http://feeds.bbci.co.uk/news/world/rss.xml",
            "site": "bbc.com",
            "description": "สำนักข่าวมาตรฐานโลก รายงานสารคดีและเหตุการณ์สำคัญระดับนานาชาติ",
            "category": "ข่าวโลก"
        }
    ]

def discover_niche_feeds(topic: str, api_key: Optional[str] = None) -> List[Dict]:
    """
    ใช้ AI วิเคราะห์หัวข้อภาษาไทย (เช่น 'เรื่องลึกลับ', 'ดาราศาสตร์', 'คริปโต')
    และค้นหาแหล่ง RSS Feed คุณภาพสูงจากเว็บไซต์ต่างประเทศที่ตรงกับหัวข้อนั้น 10 แหล่ง
    """
    topic = (topic or "").strip()
    if not topic:
        return []

    active_key = get_active_api_key(api_key)
    if not active_key:
        print(f"⚠️ ไม่พบ Gemini API Key สำหรับค้นหาฟีด จึงใช้ระบบ Smart Niche Fallback")
        return generate_fallback_feeds_for_topic(topic)

    prompt = f"""คุณคือผู้เชี่ยวชาญด้าน RSS Feeds, ข่าวสารสากล และ Content Strategy ระดับโลก
ผู้ใช้งานต้องการทำเพจ Facebook ภาษาไทยเกี่ยวกับหัวข้อ: "{topic}"
กรุณาค้นหาและแนะนำ RSS Feeds จากเว็บไซต์ต่างประเทศที่มีคุณภาพสูง เป็นที่นิยม น่าเชื่อถือ อัปเดตสม่ำเสมอ และตรงกับหัวข้อนี้ที่สุด จำนวน 10 แหล่ง

กรุณาผสมผสานประเภทแหล่งข่าวให้หลากหลายและน่าติดตาม:
1. เว็บไซต์นิตยสาร บล็อก หรือสำนักข่าวเฉพาะทางระดับสากลที่มีชื่อเสียงในหัวข้อนี้โดยตรง
2. ชุมชนเว็บบอร์ด Reddit Subreddit ที่มีสมาชิกจำนวนมากและพูดคุยเรื่องนี้กันอย่างเข้มข้น เช่น https://www.reddit.com/r/.../.rss
3. Google News Topic Search RSS ที่เจาะจงคีย์เวิร์ดภาษาอังกฤษของเรื่องนี้ เช่น https://news.google.com/rss/search?q=...&hl=en-US&gl=US&ceid=US:en

ข้อกำหนดสำคัญที่สุด:
- ทุก Feed ต้องมี URL ที่ใช้งานได้จริงในรูปแบบ RSS หรือ Atom
- ให้ส่งผลลัพธ์กลับมาเป็น JSON Array ที่ถูกต้อง 10 รายการเท่านั้น (ห้ามมีข้อความเกริ่นหรือข้อความสรุปใดๆ นอก JSON)

รูปแบบ JSON Array:
[
  {{
    "name": "ชื่อฟีดภาษาไทยกระชับเข้าใจง่าย (เช่น Mysterious Universe - เรื่องลึกลับรอบโลก)",
    "url": "https://.../feed",
    "site": "ชื่อเว็บไซต์หรือสำนักข่าว เช่น mysteriousuniverse.org",
    "description": "คำอธิบายภาษาไทยสั้นๆ 1 ประโยค ว่าฟีดนี้มีเนื้อหาอะไรและทำไมถึงน่าติดตาม",
    "category": "แท็กหมวดหมู่ เช่น ปรากฏการณ์ลี้ลับ, โบราณคดี, คดีปริศนา"
  }}
]
"""

    try:
        from google import genai
        client = genai.Client(api_key=active_key)

        for model_name in CANDIDATE_MODELS:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={
                        'temperature': 0.4
                    }
                )
                if response and response.text:
                    raw_text = response.text.strip()
                    clean_json = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.IGNORECASE)
                    clean_json = re.sub(r"\s*```$", "", clean_json)
                    clean_json = clean_json.strip()

                    match = re.search(r'\[\s*\{.*\}\s*\]', clean_json, re.DOTALL)
                    if match:
                        clean_json = match.group(0)

                    feeds = json.loads(clean_json)
                    if isinstance(feeds, list) and len(feeds) > 0:
                        formatted_feeds = []
                        for f in feeds:
                            name = str(f.get("name") or "").strip()
                            url = str(f.get("url") or "").strip()
                            site = str(f.get("site") or "").strip()
                            desc = str(f.get("description") or "").strip()
                            cat = str(f.get("category") or topic).strip()

                            if name and url and url.startswith("http"):
                                formatted_feeds.append({
                                    "name": name,
                                    "url": url,
                                    "site": site or urllib.parse.urlparse(url).netloc,
                                    "description": desc or f"อัปเดตสาระน่ารู้เกี่ยวกับ {topic}",
                                    "category": cat
                                })

                        if len(formatted_feeds) >= 5:
                            print(f"✅ AI ({model_name}) ค้นพบ {len(formatted_feeds)} ฟีดสำหรับหัวข้อ: '{topic}'")
                            return formatted_feeds[:10]
            except Exception as em:
                print(f"⚠️ ลองค้นหาด้วยโมเดล {model_name} ไม่สำเร็จ: {em}")
                continue

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการเรียก AI Feed Discovery: {e}")

    return generate_fallback_feeds_for_topic(topic)
