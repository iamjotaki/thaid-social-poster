import sys
import re
import urllib.request
import feedparser
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
from pathlib import Path
import requests

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from config import NEWS_FEEDS, BASE_DIR
from database import is_article_seen

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,th;q=0.8"
}

IMAGES_DIR = BASE_DIR / "downloads" / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# คลังภาพปกความละเอียดสูงแยกตามหมวดหมู่ (สำหรับ Fallback กรณีข่าวไม่มีรูป หรือเว็บต้นทางบล็อกการดูดรูป)
NICHE_FALLBACK_IMAGES = {
    "tech": [
        "https://images.unsplash.com/photo-1518770660439-4636190af475?w=1200&q=80", # ชิปและบอร์ดเทคโนโลยี
        "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=1200&q=80", # กราฟิกคลื่น AI
        "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?w=1200&q=80", # หุ่นยนต์ AI
        "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?w=1200&q=80"  # Cyber Matrix Data
    ],
    "biz": [
        "https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?w=1200&q=80", # กราฟหุ้นและการเงิน
        "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?w=1200&q=80", # ตึกการเงินระดับโลก
        "https://images.unsplash.com/photo-1460925895917-afdab827c52f?w=1200&q=80"  # ข้อมูลวิเคราะห์ธุรกิจ
    ],
    "sports": [
        "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?w=1200&q=80", # สนามฟุตบอลและสปอตไลท์
        "https://images.unsplash.com/photo-1579952363873-27f3bade9f55?w=1200&q=80", # ลูกฟุตบอลบนสนาม
        "https://images.unsplash.com/photo-1522778119026-d647f0596c20?w=1200&q=80"  # อัฒจันทร์สนามแข่งขัน
    ],
    "general": [
        "https://images.unsplash.com/photo-1504711434969-e33886168f5c?w=1200&q=80", # ไมโครโฟนแถลงข่าว
        "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1200&q=80", # ลูกโลกดิจิทัลรอบโลก
        "https://images.unsplash.com/photo-1585829365295-ab7cd400c167?w=1200&q=80"  # หนังสือพิมพ์และข่าวสาร
    ]
}

def resolve_article_url(url: str) -> str:
    """ถอดรหัส Google News redirect URL ให้เป็น URL ของสำนักข่าวต้นทางจริง"""
    if not url:
        return url
    if "news.google.com" in url:
        try:
            from googlenewsdecoder import gnewsdecoder
            res = gnewsdecoder(url, interval=1)
            if res.get("status") or res.get("success"):
                decoded = res.get("decoded_url")
                if decoded and decoded.startswith("http"):
                    return decoded
        except Exception as e:
            pass
    return url

def extract_image_from_html(html_text: str) -> Optional[str]:
    """สกัด URL รูปภาพจากแท็ก img ในข้อความ HTML"""
    if not html_text:
        return None
    soup = BeautifulSoup(html_text, "html.parser")
    img = soup.find("img")
    if img and img.get("src"):
        src = img.get("src")
        # กรอง icon / tracking pixel / google thumbnail ขนาดเล็กออก
        if not re.search(r'(avatar|emoji|icon|1x1|gravatar|googleusercontent|gstatic)', src, re.IGNORECASE):
            return src
    return None

def fetch_article_details(url: str, timeout: int = 8) -> Dict[str, Optional[str]]:
    """เข้าอ่านหน้าเว็บข่าวจริงเพื่อดึง og:image, og:description และเนื้อหาพารากราฟ"""
    result = {"image_url": None, "description": None, "content": None, "resolved_url": url}
    if not url or not url.startswith("http"):
        return result
    
    target_url = resolve_article_url(url)
    result["resolved_url"] = target_url

    # หากยังคงเป็น news.google.com แสดงว่าถอดรหัสไม่สำเร็จ ไม่ต้องไป fetch หน้า google news
    if "news.google.com" in target_url:
        return result

    try:
        resp = requests.get(target_url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200 and resp.text:
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # ดึง og:image หรือ twitter:image ของสำนักข่าว
            og_img = (
                soup.find("meta", property="og:image") or 
                soup.find("meta", attrs={"name": "og:image"}) or 
                soup.find("meta", attrs={"name": "twitter:image"}) or
                soup.find("meta", property="twitter:image")
            )
            if og_img and og_img.get("content"):
                cand = og_img.get("content").strip()
                if not re.search(r'(googleusercontent\.com|gstatic\.com|logo|icon|avatar|favicon)', cand, re.IGNORECASE):
                    result["image_url"] = cand
            
            # ดึง og:description
            og_desc = (
                soup.find("meta", property="og:description") or 
                soup.find("meta", attrs={"name": "og:description"}) or 
                soup.find("meta", attrs={"name": "description"})
            )
            if og_desc and og_desc.get("content"):
                result["description"] = clean_html_text(og_desc.get("content"))
            
            # ดึงย่อหน้าเนื้อหาข่าวจริง
            for bad in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
                bad.extract()
            
            paragraphs = []
            for p in soup.find_all("p"):
                p_text = p.get_text().strip()
                if len(p_text) > 60 and not re.search(r'(cookie|subscribe|sign in|terms of service|privacy policy|copyright|all rights reserved)', p_text, re.IGNORECASE):
                    paragraphs.append(p_text)
                if len(paragraphs) >= 4:
                    break
            if paragraphs:
                result["content"] = "\n\n".join(paragraphs)
    except Exception:
        pass

    return result

def clean_html_text(raw_html: str) -> str:
    """ลบแท็ก HTML ให้เหลือเฉพาะข้อความเนื้อข่าวสะอาดๆ พร้อมกรองขยะ Google News"""
    if not raw_html:
        return ""
    
    # กรณีเป็น HTML list ของ Google News เช่น <ol><li><a href="...">Headline</a>...</li>...</ol>
    if "<ol>" in raw_html and "<li>" in raw_html:
        soup = BeautifulSoup(raw_html, "html.parser")
        first_li = soup.find("li")
        if first_li:
            a_tag = first_li.find("a")
            if a_tag:
                return a_tag.get_text().strip()
            return first_li.get_text().strip()

    soup = BeautifulSoup(raw_html, "html.parser")
    for elem in soup(["script", "style", "nav", "footer", "iframe"]):
        elem.extract()
    text = soup.get_text(separator=" ")
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_niche_fallback_image(title: str = "", source: str = "") -> str:
    """สุ่มเลือกรูปภาพคุณภาพสูงที่ตรงกับหมวดหมู่ข่าว"""
    import random
    text = f"{title} {source}".lower()
    
    if any(k in text for k in ['ai', 'tech', 'technology', 'chip', 'robot', 'software', 'apple', 'google', 'openai', 'cyber']):
        pool = NICHE_FALLBACK_IMAGES["tech"]
    elif any(k in text for k in ['biz', 'business', 'stock', 'invest', 'market', 'finance', 'economy', 'crypto', 'bank']):
        pool = NICHE_FALLBACK_IMAGES["biz"]
    elif any(k in text for k in ['sport', 'football', 'soccer', 'liverpool', 'premier', 'league', 'match']):
        pool = NICHE_FALLBACK_IMAGES["sports"]
    else:
        pool = NICHE_FALLBACK_IMAGES["general"]
        
    return random.choice(pool)

def download_image(image_url: str, filename_prefix: str = "img", fallback_title: str = "") -> Optional[str]:
    """ดาวน์โหลดรูปภาพมาเก็บไว้ในเครื่องเพื่อใช้อัปโหลดขึ้น Facebook พร้อม fallback อัตโนมัติ"""
    url_to_fetch = image_url

    # หากไม่มี URL หรือเป็น URL รูปไอคอน Google ให้ใช้ภาพสต็อกระดับพรีเมียมตามหมวด
    if not url_to_fetch or re.search(r'(googleusercontent\.com|gstatic\.com|logo|icon|favicon)', url_to_fetch, re.IGNORECASE):
        url_to_fetch = get_niche_fallback_image(title=fallback_title, source=filename_prefix)

    try:
        ext = ".jpg"
        if ".png" in url_to_fetch.lower():
            ext = ".png"
        elif ".webp" in url_to_fetch.lower():
            ext = ".webp"
        
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', filename_prefix)[:50]
        local_path = IMAGES_DIR / f"{safe_name}{ext}"

        resp = requests.get(url_to_fetch, headers=HEADERS, timeout=12)
        if resp.status_code == 200 and len(resp.content) > 3000:
            with open(local_path, "wb") as f:
                f.write(resp.content)
            return str(local_path)
    except Exception as e:
        print(f"⚠️ ไม่สามารถดาวน์โหลดรูปจาก {url_to_fetch}: {e}")

    # Fallback อีกขั้นหากรูปหลักดาวน์โหลดไม่สำเร็จ
    try:
        backup_url = get_niche_fallback_image(title=fallback_title)
        resp = requests.get(backup_url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            local_path = IMAGES_DIR / f"fallback_{safe_name}.jpg"
            with open(local_path, "wb") as f:
                f.write(resp.content)
            return str(local_path)
    except Exception:
        pass

    return None

def fetch_feed(feed_config: Dict) -> List[Dict]:
    """ดึงข่าวจาก RSS feed 1 แหล่ง พร้อมถอดรหัส URL ข่าวจริง และดึงรูปภาพ/เนื้อหาคุณภาพสูง"""
    name = feed_config["name"]
    url = feed_config["url"]
    timeout = feed_config.get("timeout", 10)
    articles = []

    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content = response.read()
            feed = feedparser.parse(content)
            
            for entry in feed.entries[:10]: # เอา 10 ข่าวล่าสุด
                link = entry.get("link", "").strip()
                title = entry.get("title", "").strip()
                if not link or not title:
                    continue
                
                # ตรวจสอบว่าเคยดึงไปแล้วหรือยัง
                if is_article_seen(link):
                    continue

                # 1. ถอดรหัสและดึงข้อมูลเพิ่มเติมจากหน้าเว็บจริง (สำหรับ Google News หรือ RSS ที่ไม่มีรูป)
                details = {"image_url": None, "description": None, "content": None, "resolved_url": link}
                is_google_news = "news.google.com" in link or "google news" in name.lower()
                
                if is_google_news or not entry.get("media_content"):
                    details = fetch_article_details(link, timeout=6)

                # กำหนด URL จริง (ถ้าถอดรหัสได้ให้ใช้ URL สำนักข่าว)
                actual_url = details.get("resolved_url") or link

                # 2. ดึงเนื้อหา (ให้ความสำคัญกับเนื้อหาที่ scrape มาจากเว็บจริงก่อน)
                raw_summary = ""
                if "content" in entry and entry.content:
                    raw_summary = entry.content[0].get("value", "")
                if not raw_summary or len(raw_summary) < 150:
                    raw_summary = entry.get("summary", "") or raw_summary

                clean_summary = clean_html_text(raw_summary)

                # ถ้าเว็บข่าวมีบทคัดย่อ (og:description) หรือเนื้อหาพารากราฟ ให้ใช้แทน HTML list ของ Google News
                if details.get("content"):
                    clean_summary = details["content"]
                elif details.get("description") and len(details["description"]) > len(clean_summary):
                    clean_summary = details["description"]

                # 3. ดึงรูปภาพ
                image_url = details.get("image_url")
                if not image_url and "media_content" in entry and entry.media_content:
                    image_url = entry.media_content[0].get("url")
                elif not image_url and "enclosures" in entry and entry.enclosures:
                    image_url = entry.enclosures[0].get("href")
                elif not image_url:
                    image_url = extract_image_from_html(raw_summary)

                # ถ้ายังไม่มีรูป ให้เลือก Niche Fallback Image ไว้ล่วงหน้า
                if not image_url:
                    image_url = get_niche_fallback_image(title=title, source=name)

                published = entry.get("published", "") or entry.get("updated", "")

                articles.append({
                    "title": title,
                    "url": link,               # เก็บ link เดิมไว้ตรวจสอบ is_article_seen
                    "resolved_url": actual_url,
                    "source": name,
                    "summary": clean_summary,
                    "image_url": image_url,
                    "published_at": published
                })

    except Exception as e:
        print(f"⚠️ ข้าม {name} ({url}) เนื่องจาก: {e}")

    return articles

def fetch_all_new_articles(page_id: Optional[str] = None) -> List[Dict]:
    """ดึงข่าวใหม่จากทุกแหล่งข่าว (หากระบุ page_id จะดึงเฉพาะฟีดของเพจนั้น)"""
    import database
    all_articles = []

    target_feeds = []
    if page_id:
        db_feeds = database.get_feeds_by_page(page_id, only_enabled=True)
        for df in db_feeds:
            target_feeds.append({
                "name": df["feed_name"],
                "url": df["feed_url"],
                "timeout": 10
            })

    if not target_feeds:
        from config import DEFAULT_NEWS_FEEDS
        target_feeds = getattr(config, "DEFAULT_NEWS_FEEDS", NEWS_FEEDS)

    print(f"📡 กำลังเริ่มตรวจสอบข่าวจาก {len(target_feeds)} แหล่ง (Page ID: {page_id or 'All'})...")
    
    for feed in target_feeds:
        print(f"  🔍 กำลังตรวจ: {feed['name']}...")
        new_items = fetch_feed(feed)
        print(f"     ➔ พบข่าวใหม่ที่ยังไม่เคยโพสต์: {len(new_items)} ข่าว")
        for item in new_items:
            item["page_id"] = page_id or ""
        all_articles.extend(new_items)
        
    return all_articles
