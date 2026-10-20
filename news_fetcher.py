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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}

IMAGES_DIR = BASE_DIR / "downloads" / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

def extract_image_from_html(html_text: str) -> Optional[str]:
    """สกัด URL รูปภาพจากแท็ก img ในข้อความ HTML"""
    if not html_text:
        return None
    soup = BeautifulSoup(html_text, "html.parser")
    img = soup.find("img")
    if img and img.get("src"):
        src = img.get("src")
        # กรอง icon / tracking pixel ขนาดเล็กออก
        if not re.search(r'(avatar|emoji|icon|1x1|gravatar)', src, re.IGNORECASE):
            return src
    return None

def fetch_og_image(url: str, timeout: int = 6) -> Optional[str]:
    """เข้าหน้าเว็บข่าวเพื่อดึงรูปปกจาก meta tag og:image (กรณีใน RSS ไม่มี)"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            og_img = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
            if og_img and og_img.get("content"):
                return og_img.get("content").strip()
    except Exception:
        pass
    return None

def clean_html_text(raw_html: str) -> str:
    """ลบแท็ก HTML ให้เหลือเฉพาะข้อความเนื้อข่าวสะอาดๆ"""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    # ลบแท็ก script, style
    for elem in soup(["script", "style", "nav", "footer", "iframe"]):
        elem.extract()
    text = soup.get_text(separator=" ")
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def download_image(image_url: str, filename_prefix: str = "img") -> Optional[str]:
    """ดาวน์โหลดรูปภาพมาเก็บไว้ในเครื่องเพื่อใช้อัปโหลดขึ้น Facebook"""
    if not image_url:
        return None
    try:
        ext = ".jpg"
        if ".png" in image_url.lower():
            ext = ".png"
        elif ".webp" in image_url.lower():
            ext = ".webp"
        
        # สร้างชื่อไฟล์ที่ปลอดภัย
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', filename_prefix)[:50]
        local_path = IMAGES_DIR / f"{safe_name}{ext}"

        resp = requests.get(image_url, headers=HEADERS, timeout=10)
        if resp.status_code == 200 and len(resp.content) > 5000:
            with open(local_path, "wb") as f:
                f.write(resp.content)
            return str(local_path)
    except Exception as e:
        print(f"⚠️ ไม่สามารถดาวน์โหลดรูปจาก {image_url}: {e}")
    return None

def fetch_feed(feed_config: Dict) -> List[Dict]:
    """ดึงข่าวจาก RSS feed 1 แหล่ง พร้อมจัดการ error และ timeout"""
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

                # ดึงเนื้อหา (ให้ความสำคัญกับเนื้อหาเต็มก่อน)
                raw_summary = ""
                if "content" in entry and entry.content:
                    raw_summary = entry.content[0].get("value", "")
                if not raw_summary or len(raw_summary) < 150:
                    raw_summary = entry.get("summary", "") or raw_summary
                clean_summary = clean_html_text(raw_summary)

                # ดึงรูปภาพ
                image_url = None
                # 1. จาก media_content
                if "media_content" in entry and entry.media_content:
                    image_url = entry.media_content[0].get("url")
                # 2. จาก enclosures
                elif "enclosures" in entry and entry.enclosures:
                    image_url = entry.enclosures[0].get("href")
                # 3. จากเนื้อหา HTML
                if not image_url:
                    image_url = extract_image_from_html(raw_summary)
                # 4. Fallback: ดึงจาก OpenGraph ในหน้าข่าว
                if not image_url:
                    image_url = fetch_og_image(link)

                published = entry.get("published", "") or entry.get("updated", "")

                articles.append({
                    "title": title,
                    "url": link,
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
        target_feeds = NEWS_FEEDS

    print(f"📡 กำลังเริ่มตรวจสอบข่าวจาก {len(target_feeds)} แหล่ง (Page ID: {page_id or 'All'})...")
    
    for feed in target_feeds:
        print(f"  🔍 กำลังตรวจ: {feed['name']}...")
        new_items = fetch_feed(feed)
        print(f"     ➔ พบข่าวใหม่ที่ยังไม่เคยโพสต์: {len(new_items)} ข่าว")
        for item in new_items:
            item["page_id"] = page_id or ""
        all_articles.extend(new_items)
        
    return all_articles
