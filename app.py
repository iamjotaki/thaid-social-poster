import sys
import time
import argparse
from typing import Optional

# ปรับ encoding ของ stdout/stderr ให้รองรับ UTF-8 ภาษาไทยและ emoji บน Windows
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import CHECK_INTERVAL_MINUTES, DRY_RUN, GEMINI_API_KEY, FB_PAGE_ID
from database import init_db, save_article, update_rewritten, mark_as_posted, is_article_seen
from news_fetcher import fetch_all_new_articles, download_image
from ai_rewriter import rewrite_article
from fb_poster import post_to_facebook, PREVIEW_HTML_PATH

def print_banner():
    banner = """
    ==================================================================
              LIVERPOOL FC AUTO NEWS & FACEBOOK POSTER BOT
        ระบบดึงข่าวหงส์แดง แปลสำนวนเก๋า & โพสต์ Facebook อัตโนมัติ
    ==================================================================
    """
    print(banner)

def process_single_article(article: dict, dry_run: bool = False) -> bool:
    """ประมวลผลข่าวเดี่ยว: บันทึก -> โหลดรูป -> AI เขียนใหม่ -> โพสต์"""
    url = article["url"]
    title = article["title"]
    source = article["source"]
    image_url = article.get("image_url")
    summary = article.get("summary", "")
    published_at = article.get("published_at", "")

    print("\n" + "="*60)
    print(f"📰 ข่าวใหม่จาก: [{source}]")
    print(f"📌 หัวข้อ: {title}")
    print(f"🔗 ลิงก์: {url}")
    if image_url:
        print(f"🖼️  รูปภาพ: {image_url}")

    # 1. บันทึกลง SQLite
    save_article(url, title, source, image_url, summary, published_at)

    # 2. ดาวน์โหลดรูปภาพ
    local_image_path = None
    if image_url:
        local_image_path = download_image(image_url, filename_prefix=source + "_" + title[:20])

    # 3. ให้ AI เรียบเรียงใหม่
    rewritten_content = rewrite_article(article)
    if not rewritten_content:
        print("❌ ข้ามการโพสต์เนื่องจากไม่สามารถเขียนเนื้อหาได้")
        return False

    update_rewritten(url, rewritten_content)

    print("\n--- [ตัวอย่างเนื้อหาที่จะโพสต์] ---")
    print(rewritten_content)
    print("---------------------------------\n")

    # 4. โพสต์ไปยัง Facebook (หรือพรีวิว)
    res = post_to_facebook(
        message=rewritten_content,
        image_path=local_image_path,
        image_url=image_url
    )

    if res.get("success"):
        mark_as_posted(url)
        print("🎉 สำเร็จเรียบร้อย!")
        return True
    else:
        print(f"⚠️ การโพสต์มีปัญหา: {res.get('error')}")
        return False

def run_once(limit: int = 3, dry_run: Optional[bool] = None):
    """รันการทำงาน 1 รอบ"""
    if dry_run is None:
        dry_run = DRY_RUN

    print(f"\n🚀 เริ่มต้นตรวจสอบข่าวรอบใหม่ (จำกัดสูงสุด: {limit} ข่าว)...")
    articles = fetch_all_new_articles()

    if not articles:
        print("☕ ยังไม่มีข่าวใหม่ที่ยังไม่เคยโพสต์ในตอนนี้")
        return

    print(f"\n📦 พบข่าวใหม่ทั้งหมด {len(articles)} ข่าว จะทำการประมวลผล {min(limit, len(articles))} ข่าวแรก")

    count = 0
    for art in articles:
        if count >= limit:
            break
        # เช็คซ้ำอีกรอบ
        if is_article_seen(art["url"]):
            continue

        success = process_single_article(art, dry_run=dry_run)
        if success:
            count += 1
            # พักสักนิดเพื่อไม่ให้ยิงรัวเกินไป
            time.sleep(3)

    print(f"\n✅ ประมวลผลเสร็จสิ้น: โพสต์ไปทั้งหมด {count} ข่าว")
    if dry_run:
        print(f"📂 เปิดดูตัวอย่างโพสต์ได้ที่: {PREVIEW_HTML_PATH}")

def run_loop(interval_minutes: int = 30, limit: int = 3):
    """รันวนลูปอัตโนมัติตามระยะเวลาที่กำหนด"""
    print(f"⏱️  เริ่มระบบ Auto-run ทุกๆ {interval_minutes} นาที (กด Ctrl+C เพื่อหยุด)")
    while True:
        try:
            run_once(limit=limit)
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดในรอบนี้: {e}")
        
        print(f"\n⏳ รอตรวจสอบรอบถัดไปในอีก {interval_minutes} นาที...")
        time.sleep(interval_minutes * 60)

def main():
    parser = argparse.ArgumentParser(description="Liverpool FC Auto News Scraper & Facebook Poster")
    parser.add_argument("--auto", action="store_true", help="รันอัตโนมัติแบบวนลูปต่อเนื่อง")
    parser.add_argument("--dry-run", action="store_true", help="รันแบบทดสอบ ไม่โพสต์ขึ้น Facebook จริง")
    parser.add_argument("--limit", type=int, default=2, help="จำนวนข่าวสูงสุดที่จะประมวลผลในรอบนี้")
    parser.add_argument("--interval", type=int, default=CHECK_INTERVAL_MINUTES, help="ระยะเวลารอแต่ละรอบ (นาที)")
    args = parser.parse_args()

    print_banner()
    init_db()

    # ตรวจสอบสถานะการตั้งค่า
    print("📋 สถานะระบบ:")
    print(f"  • Gemini API Key: {'✅ ตั้งค่าแล้ว' if GEMINI_API_KEY else '⚠️ ยังไม่ได้ใส่ (จะใช้โหมดตัวอย่าง)'}")
    print(f"  • Facebook Page ID: {'✅ ตั้งค่าแล้ว' if FB_PAGE_ID else '⚠️ ยังไม่ได้ใส่'}")
    print(f"  • โหมดการทำงาน: {'🟡 DRY RUN (ทดสอบลงไฟล์ HTML)' if (args.dry_run or DRY_RUN) else '🟢 LIVE (โพสต์จริงขึ้น Facebook)'}")

    if args.auto:
        run_loop(interval_minutes=args.interval, limit=args.limit)
    else:
        run_once(limit=args.limit, dry_run=args.dry_run or DRY_RUN)

if __name__ == "__main__":
    main()
