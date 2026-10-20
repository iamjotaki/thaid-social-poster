import sqlite3
import datetime
from pathlib import Path
from typing import Optional, Dict, List
import config

DB_PATH = Path(__file__).resolve().parent / "news_history.db"

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    """สร้างตารางและอัปเกรดโครงสร้างฐานข้อมูลรองรับหลายเพจ, ฟีดแยกเพจ, และการตั้งเวลา"""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. ตารางเพจ Facebook (Pages)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                access_token TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. ตาราง RSS Feeds ประจำเพจ (Page Feeds)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS page_feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page_id TEXT NOT NULL,
                feed_name TEXT NOT NULL,
                feed_url TEXT NOT NULL,
                is_enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(page_id, feed_url)
            )
        """)

        # 3. ตารางประวัติข่าว (Articles)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                title TEXT,
                source TEXT,
                image_url TEXT,
                summary TEXT,
                rewritten_text TEXT,
                status TEXT DEFAULT 'pending',
                published_at TEXT,
                page_id TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # เพิ่มคอลัมน์ page_id ในตาราง articles หากยังไม่มี
        try:
            cursor.execute("ALTER TABLE articles ADD COLUMN page_id TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # คอลัมน์มีอยู่แล้ว

        # เพิ่มคอลัมน์ card_image_path ในตาราง articles สำหรับเก็บ Social Card
        try:
            cursor.execute("ALTER TABLE articles ADD COLUMN card_image_path TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass

        # 4. ตารางคิวตั้งเวลาโพสต์ (Scheduled Posts)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page_id TEXT NOT NULL,
                title TEXT,
                article_url TEXT,
                caption TEXT NOT NULL,
                image_url TEXT,
                local_image_path TEXT,
                scheduled_time TEXT NOT NULL,
                status TEXT DEFAULT 'scheduled',
                post_id TEXT,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()

        # นำเข้าเพจแรกและฟีดเริ่มต้นอัตโนมัติ (Migration)
        _seed_default_page_and_feeds(cursor, conn)

def _seed_default_page_and_feeds(cursor, conn):
    """สร้างเพจเริ่มต้นหากยังไม่มีข้อมูลในระบบ"""
    cursor.execute("SELECT COUNT(*) FROM pages")
    if cursor.fetchone()[0] == 0 and config.FB_PAGE_ID:
        cursor.execute("""
            INSERT OR IGNORE INTO pages (page_id, name, access_token, is_active)
            VALUES (?, ?, ?, 1)
        """, (config.FB_PAGE_ID, "หงส์นิวส์", config.FB_PAGE_ACCESS_TOKEN))
        conn.commit()

        # ผูก feeds เริ่มต้นเข้ากับเพจนี้
        for f in config.NEWS_FEEDS:
            cursor.execute("""
                INSERT OR IGNORE INTO page_feeds (page_id, feed_name, feed_url, is_enabled)
                VALUES (?, ?, ?, 1)
            """, (config.FB_PAGE_ID, f["name"], f["url"]))
        
        # ปรับข่าวเดิมให้ผูกกับเพจนี้
        cursor.execute("UPDATE articles SET page_id = ? WHERE page_id = '' OR page_id IS NULL", (config.FB_PAGE_ID,))
        conn.commit()

# -------------------------------------------------------------
# จัดการเพจ (Pages Management)
# -------------------------------------------------------------
def get_all_pages() -> List[Dict]:
    """ดึงรายชื่อเพจทั้งหมด พร้อมสถิติจำนวนฟีดและข่าว"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.*,
                   (SELECT COUNT(*) FROM page_feeds WHERE page_id = p.page_id) as feeds_count,
                   (SELECT COUNT(*) FROM articles WHERE page_id = p.page_id) as articles_count
            FROM pages p
            ORDER BY p.id ASC
        """)
        return [dict(r) for r in cursor.fetchall()]

def get_page_by_id(page_id: str) -> Optional[Dict]:
    """ดึงข้อมูลเพจตาม Page ID"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pages WHERE page_id = ?", (page_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def save_or_update_page(page_id: str, name: str, access_token: str, is_active: int = 1) -> bool:
    """เพิ่มหรือแก้ไขเพจ Facebook"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO pages (page_id, name, access_token, is_active)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(page_id) DO UPDATE SET
                name = excluded.name,
                access_token = excluded.access_token,
                is_active = excluded.is_active
        """, (page_id, name, access_token, is_active))
        conn.commit()
        return True

def delete_page(page_id: str) -> bool:
    """ลบเพจและฟีดที่เกี่ยวข้อง"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM pages WHERE page_id = ?", (page_id,))
        cursor.execute("DELETE FROM page_feeds WHERE page_id = ?", (page_id,))
        cursor.execute("DELETE FROM scheduled_posts WHERE page_id = ? AND status = 'scheduled'", (page_id,))
        conn.commit()
        return True

# -------------------------------------------------------------
# จัดการ RSS Feeds ประจำเพจ (Page Feeds Management)
# -------------------------------------------------------------
def get_feeds_by_page(page_id: str, only_enabled: bool = False) -> List[Dict]:
    """ดึงรายการ RSS Feeds ของเพจที่เลือก"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if only_enabled:
            cursor.execute("SELECT * FROM page_feeds WHERE page_id = ? AND is_enabled = 1 ORDER BY id ASC", (page_id,))
        else:
            cursor.execute("SELECT * FROM page_feeds WHERE page_id = ? ORDER BY id ASC", (page_id,))
        return [dict(r) for r in cursor.fetchall()]

def add_feed_to_page(page_id: str, feed_name: str, feed_url: str) -> bool:
    """เพิ่ม RSS Feed ให้กับเพจ"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO page_feeds (page_id, feed_name, feed_url, is_enabled)
                VALUES (?, ?, ?, 1)
            """, (page_id, feed_name.strip(), feed_url.strip()))
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False

def toggle_feed(feed_id: int, is_enabled: int) -> bool:
    """เปิดหรือปิดการดึงข่าวจาก Feed นี้"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE page_feeds SET is_enabled = ? WHERE id = ?", (is_enabled, feed_id))
        conn.commit()
        return True

def delete_feed(feed_id: int) -> bool:
    """ลบ RSS Feed ออกจากเพจ"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM page_feeds WHERE id = ?", (feed_id,))
        conn.commit()
        return True

# -------------------------------------------------------------
# จัดการบทความและข่าว (Articles)
# -------------------------------------------------------------
def is_article_seen(url: str, page_id: Optional[str] = None) -> bool:
    """ตรวจสอบว่าเคยดึงข่าวจาก URL นี้หรือยัง"""
    with get_connection() as conn:
        cursor = conn.cursor()
        if page_id:
            cursor.execute("SELECT id FROM articles WHERE url = ? AND page_id = ?", (url, page_id))
        else:
            cursor.execute("SELECT id FROM articles WHERE url = ?", (url,))
        return cursor.fetchone() is not None

def save_article(url: str, title: str, source: str, image_url: Optional[str], summary: str, published_at: str, page_id: str = "") -> bool:
    """บันทึกข่าวใหม่เข้าระบบ"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO articles (url, title, source, image_url, summary, published_at, page_id, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """, (url, title, source, image_url, summary, published_at, page_id))
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False

def update_rewritten(url: str, rewritten_text: str):
    """อัปเดตเนื้อหาที่ AI เขียนใหม่แล้ว"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE articles
            SET rewritten_text = ?, status = 'rewritten'
            WHERE url = ?
        """, (rewritten_text, url))
        conn.commit()

def mark_as_posted(url: str):
    """บันทึกสถานะว่าโพสต์ขึ้น Facebook สำเร็จแล้ว"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE articles
            SET status = 'posted'
            WHERE url = ?
        """, (url,))
        conn.commit()

def update_card_image(article_id: int, card_image_path: str):
    """อัปเดตไฟล์ Social Card ของบทความ"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE articles
            SET card_image_path = ?
            WHERE id = ?
        """, (card_image_path, article_id))
        conn.commit()

def get_recent_articles(limit: int = 30, page_id: Optional[str] = None) -> List[Dict]:
    """ดึงรายการข่าวล่าสุด (กรองตาม page_id ได้)"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if page_id:
            cursor.execute("SELECT * FROM articles WHERE page_id = ? ORDER BY id DESC LIMIT ?", (page_id, limit))
        else:
            cursor.execute("SELECT * FROM articles ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in cursor.fetchall()]

# -------------------------------------------------------------
# จัดการระบบตั้งเวลาโพสต์ (Scheduled Posts Queue)
# -------------------------------------------------------------
def create_scheduled_post(page_id: str, caption: str, scheduled_time: str, title: str = "", article_url: str = "", image_url: str = "", local_image_path: str = "") -> int:
    """สร้างรายการตั้งเวลาโพสต์ใหม่"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO scheduled_posts (page_id, title, article_url, caption, image_url, local_image_path, scheduled_time, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'scheduled')
        """, (page_id, title, article_url, caption, image_url, local_image_path, scheduled_time))
        conn.commit()
        return cursor.lastrowid

def get_scheduled_posts(page_id: Optional[str] = None, status: Optional[str] = None) -> List[Dict]:
    """ดึงรายการโพสต์ที่ตั้งเวลาไว้"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        query = """
            SELECT sp.*, p.name as page_name
            FROM scheduled_posts sp
            LEFT JOIN pages p ON sp.page_id = p.page_id
            WHERE 1=1
        """
        params = []
        if page_id:
            query += " AND sp.page_id = ?"
            params.append(page_id)
        if status:
            query += " AND sp.status = ?"
            params.append(status)
        query += " ORDER BY sp.scheduled_time ASC"
        cursor.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]

def get_due_scheduled_posts() -> List[Dict]:
    """ดึงรายการโพสต์ที่ถึงเวลาต้องยิงโพสต์แล้ว"""
    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now_iso_t = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT sp.*, p.access_token, p.name as page_name
            FROM scheduled_posts sp
            JOIN pages p ON sp.page_id = p.page_id
            WHERE sp.status = 'scheduled'
              AND (sp.scheduled_time <= ? OR sp.scheduled_time <= ?)
            ORDER BY sp.scheduled_time ASC
        """, (now_iso, now_iso_t))
        return [dict(r) for r in cursor.fetchall()]

def update_scheduled_post_status(post_id: int, status: str, post_fb_id: Optional[str] = None, error_message: Optional[str] = None):
    """อัปเดตผลลัพธ์การโพสต์ตามคิวตั้งเวลา"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE scheduled_posts
            SET status = ?, post_id = ?, error_message = ?
            WHERE id = ?
        """, (status, post_fb_id, error_message, post_id))
        conn.commit()

def cancel_scheduled_post(post_id: int) -> bool:
    """ยกเลิกรายการตั้งเวลา"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE scheduled_posts SET status = 'cancelled' WHERE id = ? AND status = 'scheduled'", (post_id,))
        conn.commit()
        return True

def delete_scheduled_post(post_id: int) -> bool:
    """ลบรายการตั้งเวลาออกจากฐานข้อมูล"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM scheduled_posts WHERE id = ?", (post_id,))
        conn.commit()
        return True

# สร้างตารางทันทีเมื่อโหลดโมดูล
init_db()
