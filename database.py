import os
import re
import sqlite3
import datetime
import calendar
from pathlib import Path
from typing import Optional, Dict, List
import config

try:
    import psycopg2
    import psycopg2.extras
    from psycopg2.pool import ThreadedConnectionPool
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

DB_PATH = Path(__file__).resolve().parent / "news_history.db"

class PostgresCursorWrapper:
    def __init__(self, raw_cursor):
        self._cur = raw_cursor

    def _convert_sql(self, sql: str) -> str:
        # 1. Convert INTEGER PRIMARY KEY AUTOINCREMENT -> SERIAL PRIMARY KEY
        converted = re.sub(r'INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT', 'SERIAL PRIMARY KEY', sql, flags=re.IGNORECASE)
        # 2. Convert INSERT OR IGNORE INTO -> INSERT INTO ... ON CONFLICT DO NOTHING
        if re.search(r'INSERT\s+OR\s+IGNORE\s+INTO', converted, flags=re.IGNORECASE):
            converted = re.sub(r'INSERT\s+OR\s+IGNORE\s+INTO', 'INSERT INTO', converted, flags=re.IGNORECASE)
            if 'ON CONFLICT' not in converted.upper():
                converted = converted.rstrip().rstrip(';') + ' ON CONFLICT DO NOTHING'
        # 3. Convert ALTER TABLE ADD COLUMN ... -> ADD COLUMN IF NOT EXISTS ...
        if re.search(r'ADD\s+COLUMN\s+(?!IF\s+NOT\s+EXISTS)', converted, flags=re.IGNORECASE):
            converted = re.sub(r'ADD\s+COLUMN\s+', 'ADD COLUMN IF NOT EXISTS ', converted, flags=re.IGNORECASE)
        # 4. Convert strftime('%Y-%m', 'now'...) -> to_char(NOW(), 'YYYY-MM')
        converted = re.sub(r"strftime\('%Y-%m',\s*'now'[^)]*\)", "to_char(NOW(), 'YYYY-MM')", converted, flags=re.IGNORECASE)
        converted = re.sub(r"strftime\('%Y-%m',\s*([^)]+)\)", r"to_char(\g<1>::timestamp, 'YYYY-MM')", converted, flags=re.IGNORECASE)
        # 5. Convert ? to %s
        converted = converted.replace('?', '%s')
        return converted

    def execute(self, query, params=None):
        sql = self._convert_sql(query)
        if params is not None:
            return self._cur.execute(sql, params)
        return self._cur.execute(sql)

    def executemany(self, query, seq_of_params):
        sql = self._convert_sql(query)
        return self._cur.executemany(sql, seq_of_params)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def fetchmany(self, size=None):
        return self._cur.fetchmany(size) if size else self._cur.fetchmany()

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def lastrowid(self):
        return getattr(self._cur, 'lastrowid', None)

    def close(self):
        self._cur.close()

class PostgresConnectionWrapper:
    def __init__(self, raw_conn, pool=None):
        self._conn = raw_conn
        self._pool = pool
        self._closed = False
        self._row_factory = None

    @property
    def row_factory(self):
        return self._row_factory

    @row_factory.setter
    def row_factory(self, val):
        self._row_factory = val

    def cursor(self):
        return PostgresCursorWrapper(self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor))

    def commit(self):
        if not self._closed and self._conn and not getattr(self._conn, 'closed', 0):
            self._conn.commit()

    def rollback(self):
        if not self._closed and self._conn and not getattr(self._conn, 'closed', 0):
            self._conn.rollback()

    def close(self):
        if not self._closed:
            self._closed = True
            if self._pool and self._conn:
                try:
                    self._pool.putconn(self._conn)
                except Exception:
                    pass
            elif self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type:
                self.rollback()
            else:
                self.commit()
        finally:
            self.close()

_PG_POOL = None
_PG_POOL_DSN = ""

def get_pg_pool(db_url: str):
    global _PG_POOL, _PG_POOL_DSN
    if _PG_POOL is None or getattr(_PG_POOL, 'closed', False) or _PG_POOL_DSN != db_url:
        if _PG_POOL and not getattr(_PG_POOL, 'closed', False):
            try:
                _PG_POOL.closeall()
            except Exception:
                pass
        _PG_POOL = ThreadedConnectionPool(minconn=1, maxconn=10, dsn=db_url)
        _PG_POOL_DSN = db_url
    return _PG_POOL

def get_connection():
    db_url = getattr(config, 'DATABASE_URL', '') or os.getenv('DATABASE_URL', '').strip()
    if db_url and HAS_PSYCOPG2:
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        pool = get_pg_pool(db_url)
        try:
            raw_conn = pool.getconn()
            if getattr(raw_conn, 'closed', 0) != 0:
                pool.putconn(raw_conn, close=True)
                raw_conn = pool.getconn()
        except Exception:
            # Recreate pool if stale or broken
            global _PG_POOL
            try:
                if _PG_POOL:
                    _PG_POOL.closeall()
            except Exception:
                pass
            _PG_POOL = ThreadedConnectionPool(minconn=1, maxconn=10, dsn=db_url)
            _PG_POOL_DSN = db_url
            raw_conn = _PG_POOL.getconn()
        return PostgresConnectionWrapper(raw_conn, pool=pool)
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
        except (sqlite3.OperationalError, Exception):
            pass  # คอลัมน์มีอยู่แล้ว

        # เพิ่มคอลัมน์ card_image_path ในตาราง articles สำหรับเก็บ Social Card
        try:
            cursor.execute("ALTER TABLE articles ADD COLUMN card_image_path TEXT DEFAULT ''")
        except (sqlite3.OperationalError, Exception):
            pass

        # เพิ่มคอลัมน์ fb_post_id และ fb_post_url ในตาราง articles สำหรับลิงก์ไปยัง Facebook Post
        for col_name, col_type in [
            ("fb_post_id", "TEXT DEFAULT ''"),
            ("fb_post_url", "TEXT DEFAULT ''")
        ]:
            try:
                cursor.execute(f"ALTER TABLE articles ADD COLUMN {col_name} {col_type}")
            except (sqlite3.OperationalError, Exception):
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

        # 5. ตารางผู้ใช้งาน (Users) สำหรับ SaaS & Admin
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                avatar_url TEXT DEFAULT '',
                role TEXT DEFAULT 'member',
                plan_name TEXT DEFAULT 'Free Trial',
                plan_expires_at TEXT,
                video_credits INTEGER DEFAULT 5,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 6. ตารางคลัง Google Gemini API Keys ประจำตัวสมาชิก (Unlimited BYOK)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                api_key TEXT NOT NULL,
                label TEXT DEFAULT 'Google Gemini Key',
                is_active INTEGER DEFAULT 1,
                usage_count INTEGER DEFAULT 0,
                last_used_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # เพิ่มคอลัมน์ user_id ในตารางหลักต่างๆ (Multi-Tenancy)
        for tbl in ["pages", "scheduled_posts", "articles"]:
            try:
                cursor.execute(f"ALTER TABLE {tbl} ADD COLUMN user_id INTEGER DEFAULT 1")
            except (sqlite3.OperationalError, Exception):
                pass

        # เพิ่มคอลัมน์สำหรับการตั้งค่าความถี่และโควตาโพสต์ประจำเพจ
        for col_name, col_type in [
            ("posts_per_day", "INTEGER DEFAULT 3"),
            ("reels_per_day", "INTEGER DEFAULT 2"),
            ("posting_times", "TEXT DEFAULT '09:00,13:00,17:00,20:00'"),
            ("schedule_mode", "TEXT DEFAULT 'facebook'")
        ]:
            try:
                cursor.execute(f"ALTER TABLE pages ADD COLUMN {col_name} {col_type}")
            except (sqlite3.OperationalError, Exception):
                pass

        # เพิ่มคอลัมน์สำหรับ Native FB Scheduling & สถิติประวัติโพสต์ใน scheduled_posts
        for col_name, col_type in [
            ("post_type", "TEXT DEFAULT 'post'"),
            ("is_fb_native", "INTEGER DEFAULT 1"),
            ("video_path", "TEXT DEFAULT ''"),
            ("published_at", "TEXT"),
            ("fb_post_url", "TEXT")
        ]:
            try:
                cursor.execute(f"ALTER TABLE scheduled_posts ADD COLUMN {col_name} {col_type}")
            except (sqlite3.OperationalError, Exception):
                pass

        conn.commit()

        # สร้างผู้ใช้เริ่มต้น & เพจเริ่มต้นอัตโนมัติ
        _seed_default_users(cursor, conn)
        _seed_default_page_and_feeds(cursor, conn)
        _seed_default_api_keys(cursor, conn)

def _seed_default_api_keys(cursor, conn):
    """เพิ่ม API Key ตัวอย่างหากยังไม่มีในระบบ"""
    cursor.execute("SELECT COUNT(*) FROM user_api_keys")
    if cursor.fetchone()[0] == 0:
        # ดึง Admin ID
        cursor.execute("SELECT id FROM users WHERE email = 'admin@lfcautonews.com'")
        row = cursor.fetchone()
        if row and config.GEMINI_API_KEY:
            cursor.execute("""
                INSERT INTO user_api_keys (user_id, api_key, label, is_active)
                VALUES (?, ?, 'Google AI Studio (Key หลัก)', 1)
            """, (row[0], config.GEMINI_API_KEY))
            conn.commit()

def _seed_default_users(cursor, conn):
    """สร้างสมาชิกตัวอย่างเริ่มต้นสำหรับระบบ Mockup SaaS & Admin"""
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        default_users = [
            (
                "admin@lfcautonews.com",
                "Admin Boss (ผู้ดูแลระบบ)",
                "https://api.dicebear.com/7.x/bottts/svg?seed=AdminBoss",
                "admin",
                "VIP Agency",
                "2027-12-31 23:59:59",
                999,
                "active"
            ),
            (
                "thekop@fanpage.com",
                "The Kop Thailand (คุณกฤต)",
                "https://api.dicebear.com/7.x/avataaars/svg?seed=TheKop",
                "member",
                "Pro",
                "2026-12-31 23:59:59",
                30,
                "active"
            ),
            (
                "newbie@gmail.com",
                "สมาชิกใหม่ บอลเต็ง",
                "https://api.dicebear.com/7.x/avataaars/svg?seed=Newbie",
                "member",
                "Free Trial",
                "2026-11-05 23:59:59",
                5,
                "active"
            )
        ]
        cursor.executemany("""
            INSERT OR IGNORE INTO users (email, name, avatar_url, role, plan_name, plan_expires_at, video_credits, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, default_users)
        conn.commit()

def _seed_default_page_and_feeds(cursor, conn):
    """สร้างเพจเริ่มต้นหากยังไม่มีข้อมูลในระบบ หรืออัปเดตชื่อเพจเริ่มต้น"""
    default_name = getattr(config, "DEFAULT_PAGE_NAME", "ทันข่าว") or "ทันข่าว"
    
    # 1. ตรวจสอบหากมีเพจชื่อ "หงส์นิวส์" อยู่ ให้เปลี่ยนเป็น DEFAULT_PAGE_NAME อัตโนมัติ
    cursor.execute("SELECT page_id, name FROM pages WHERE name = 'หงส์นิวส์'")
    old_hong = cursor.fetchall()
    if old_hong and default_name != "หงส์นิวส์":
        for (old_pid, _) in old_hong:
            cursor.execute("UPDATE pages SET name = ? WHERE page_id = ?", (default_name, old_pid))
            # ลบ feed ลิเวอร์พูลเดิมออกจากเพจนี้
            cursor.execute("""
                DELETE FROM page_feeds 
                WHERE page_id = ? AND feed_name IN ('DaveOCKOP', 'This Is Anfield', 'Anfield Watch', 'Empire of the Kop', 'Liverpool Echo', 'CaughtOffside (LFC)')
            """, (old_pid,))
            # เพิ่ม Google News Feeds ถ้าเพจนี้ไม่มีฟีดเหลือ
            cursor.execute("SELECT COUNT(*) FROM page_feeds WHERE page_id = ?", (old_pid,))
            if cursor.fetchone()[0] == 0:
                feeds_to_add = getattr(config, "DEFAULT_NEWS_FEEDS", [])
                for f in feeds_to_add:
                    cursor.execute("""
                        INSERT OR IGNORE INTO page_feeds (page_id, feed_name, feed_url, is_enabled)
                        VALUES (?, ?, ?, 1)
                    """, (old_pid, f["name"], f["url"]))
        conn.commit()

    # 2. กรณีตารางเพจว่างเปล่า (เช่น deploy ครั้งแรกบน Render)
    cursor.execute("SELECT COUNT(*) FROM pages")
    if cursor.fetchone()[0] == 0 and config.FB_PAGE_ID:
        cursor.execute("""
            INSERT OR IGNORE INTO pages (page_id, name, access_token, is_active)
            VALUES (?, ?, ?, 1)
        """, (config.FB_PAGE_ID, default_name, config.FB_PAGE_ACCESS_TOKEN))
        conn.commit()

        # ผูก feeds เริ่มต้นเข้ากับเพจนี้ (ถ้าเป็นลิเวอร์พูลให้ใส่ NEWS_FEEDS ถ้าเป็นเพจอื่นให้ใส่ DEFAULT_NEWS_FEEDS)
        if any(w in default_name.lower() for w in ["หงส์", "liverpool"]):
            feeds_to_seed = config.NEWS_FEEDS
        else:
            feeds_to_seed = getattr(config, "DEFAULT_NEWS_FEEDS", [
                {"name": "Google News - Technology", "url": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en"},
                {"name": "Google News - Artificial Intelligence", "url": "https://news.google.com/rss/search?q=Artificial+Intelligence+when:2d&hl=en-US&gl=US&ceid=US:en"}
            ])

        for f in feeds_to_seed:
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
                   (SELECT COUNT(*) FROM page_feeds WHERE page_id = p.page_id AND is_enabled = 1) as active_feeds_count,
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

def build_fb_post_url(post_id: Optional[str] = None, page_id: Optional[str] = None) -> str:
    """สร้าง URL สำหรับเปิดดูโพสต์บน Facebook โดยตรง"""
    post_id_str = str(post_id or "").strip()
    page_id_str = str(page_id or "").strip()
    if page_id_str == "your_page_id_here":
        page_id_str = ""

    # กรณี post_id ใช้งานได้จริง (ไม่ใช่ค่าจำลอง Dry-Run เช่น sim_...)
    if post_id_str and not post_id_str.startswith("sim_") and post_id_str.lower() != "dry-run":
        if "_" in post_id_str:
            p_part, id_part = post_id_str.split("_", 1)
            return f"https://www.facebook.com/{p_part}/posts/{id_part}"
        elif page_id_str:
            return f"https://www.facebook.com/{page_id_str}/posts/{post_id_str}"
        else:
            return f"https://www.facebook.com/{post_id_str}"

    # กรณีไม่มี post_id หรือเป็นโพสต์จำลอง dry-run ให้ลิงก์ไปยังหน้าเพจ Facebook
    if page_id_str:
        return f"https://www.facebook.com/{page_id_str}"

    default_pid = getattr(config, "FB_PAGE_ID", "")
    if default_pid and default_pid != "your_page_id_here":
        return f"https://www.facebook.com/{default_pid}"

    return "https://www.facebook.com"

def mark_as_posted(url: str, post_id: Optional[str] = None, fb_post_url: Optional[str] = None, page_id: Optional[str] = None):
    """บันทึกสถานะว่าโพสต์ขึ้น Facebook สำเร็จแล้ว พร้อมเก็บ post_id และ ลิงก์ตรง fb_post_url"""
    if not fb_post_url and (post_id or page_id):
        fb_post_url = build_fb_post_url(post_id, page_id)

    with get_connection() as conn:
        cursor = conn.cursor()
        if not fb_post_url or fb_post_url == "https://www.facebook.com":
            try:
                cursor.execute("SELECT page_id FROM articles WHERE url = ?", (url,))
                row = cursor.fetchone()
                if row and row[0]:
                    page_id = row[0]
                    fb_post_url = build_fb_post_url(post_id, page_id)
            except Exception:
                pass

        if not fb_post_url:
            fb_post_url = build_fb_post_url(post_id, page_id)

        cursor.execute("""
            UPDATE articles
            SET status = 'posted',
                fb_post_id = COALESCE(NULLIF(?, ''), fb_post_id, ''),
                fb_post_url = COALESCE(NULLIF(?, ''), fb_post_url, '')
            WHERE url = ?
        """, (post_id or '', fb_post_url or '', url))
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

def get_paginated_articles(
    page: int = 1,
    limit: int = 15,
    page_id: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None
) -> Dict:
    """ดึงรายการข่าวล่าสุดพร้อมระบบแบ่งหน้า Pagination และ Filter"""
    import math
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        where = ["1=1"]
        params = []
        if page_id:
            where.append("page_id = ?")
            params.append(page_id)
        if status and status != 'all':
            if status == 'posted':
                where.append("status = 'posted'")
            elif status == 'pending':
                where.append("status != 'posted'")
        if search:
            where.append("(title LIKE ? OR summary LIKE ? OR source LIKE ?)")
            s_param = f"%{search}%"
            params.extend([s_param, s_param, s_param])
            
        where_sql = " AND ".join(where)
        offset = max(0, (page - 1) * limit)

        # Single-query execution with window function for high performance (reduces DB roundtrips)
        fetch_sql = f"SELECT *, count(*) OVER() as full_count FROM articles WHERE {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?"
        fetch_params = tuple(params + [limit, offset])
        cursor.execute(fetch_sql, fetch_params)
        raw_rows = cursor.fetchall()

        if raw_rows:
            first_row = dict(raw_rows[0])
            total = int(first_row.get("full_count", len(raw_rows)))
            rows = []
            for r in raw_rows:
                d = dict(r)
                d.pop("full_count", None)
                rows.append(d)
        else:
            if page == 1:
                total = 0
                rows = []
            else:
                count_sql = f"SELECT COUNT(*) FROM articles WHERE {where_sql}"
                cursor.execute(count_sql, tuple(params))
                res = cursor.fetchone()
                total = (res[0] if res else 0) or 0
                rows = []
        
        for art in rows:
            if art.get("status") == "posted" and not art.get("fb_post_url"):
                art["fb_post_url"] = build_fb_post_url(art.get("fb_post_id"), art.get("page_id") or page_id)
                
        total_pages = max(1, math.ceil(total / limit)) if total > 0 else 1
        
        return {
            "items": rows,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "has_more": page < total_pages
        }

def get_recent_articles(limit: int = 30, page_id: Optional[str] = None) -> List[Dict]:
    """ดึงรายการข่าวล่าสุด (สำหรับ backward compatibility)"""
    res = get_paginated_articles(page=1, limit=limit, page_id=page_id)
    return res["items"]

def delete_article(article_id: int) -> bool:
    """ลบข่าวออกจากฐานข้อมูลตาม article_id พร้อมลบไฟล์ Social Card ที่เกี่ยวข้อง"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT card_image_path FROM articles WHERE id = ?", (article_id,))
        row = cursor.fetchone()
        if not row:
            return False
        card_img = row[0] if row else None
        cursor.execute("DELETE FROM articles WHERE id = ?", (article_id,))
        conn.commit()
        
        # ลบไฟล์ภาพ Social Card ที่เกี่ยวข้องในโฟลเดอร์ static หากมี
        if card_img and isinstance(card_img, str) and not card_img.startswith("http"):
            try:
                local_path = Path(__file__).resolve().parent / card_img.lstrip("/")
                if local_path.is_file():
                    local_path.unlink()
            except Exception:
                pass
        return True

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

# -------------------------------------------------------------
# จัดการโควตา & การตั้งเวลาบน Facebook (Native FB Scheduling & History)
# -------------------------------------------------------------
def get_page_schedule_rules(page_id: str) -> Dict:
    """ดึงการตั้งค่าความถี่และโควตาการโพสต์ประจำเพจ"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT posts_per_day, reels_per_day, posting_times, schedule_mode FROM pages WHERE page_id = ?", (page_id,))
        row = cursor.fetchone()
        if row:
            times = [t.strip() for t in (row["posting_times"] or "09:00,13:00,17:00,20:00").split(",") if t.strip()]
            return {
                "posts_per_day": row["posts_per_day"] or 3,
                "reels_per_day": row["reels_per_day"] or 2,
                "posting_times": times,
                "schedule_mode": row["schedule_mode"] or "facebook"
            }
        return {
            "posts_per_day": 3,
            "reels_per_day": 2,
            "posting_times": ["09:00", "13:00", "17:00", "20:00"],
            "schedule_mode": "facebook"
        }

def update_page_schedule_rules(page_id: str, posts_per_day: int, reels_per_day: int, posting_times: str, schedule_mode: str = "facebook") -> bool:
    """อัปเดตการตั้งค่าความถี่และโควตาการโพสต์ประจำเพจ"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE pages
            SET posts_per_day = ?, reels_per_day = ?, posting_times = ?, schedule_mode = ?
            WHERE page_id = ?
        """, (posts_per_day, reels_per_day, posting_times, schedule_mode, page_id))
        conn.commit()
        return True

def calculate_next_schedule_slot(page_id: str, post_type: str = "post") -> Dict:
    """
    คำนวณคิวเวลาถัดไปอัตโนมัติ (Next Auto-Slot) บน Facebook ตามโควตาและช่วงเวลาที่เพจกำหนดไว้
    หากช่วงเวลาในวันนี้เต็มหรือผ่านไปแล้ว จะเลื่อนไปหาสล็อตแรกที่ว่างในวันถัดไปทันที
    """
    rules = get_page_schedule_rules(page_id)
    raw_times = rules.get("posting_times") or ["09:00", "13:00", "17:00", "20:00"]
    slots = sorted(list(set(raw_times)))

    now = datetime.datetime.now()
    # กฎของ Facebook Graph API: ต้องตั้งเวลาล่วงหน้าอย่างน้อย 10-15 นาที
    min_time = now + datetime.timedelta(minutes=15)

    # ดึงเวลาที่มีการจองไว้แล้วใน scheduled_posts
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT scheduled_time FROM scheduled_posts
            WHERE page_id = ? AND status IN ('scheduled', 'fb_scheduled')
        """, (page_id,))
        booked_rows = cursor.fetchall()
        booked_times = set()
        for r in booked_rows:
            st = r[0]
            if st:
                booked_times.add(st[:16])

    # ค้นหาใน 14 วันข้างหน้า
    for day_offset in range(14):
        target_day = (now + datetime.timedelta(days=day_offset)).date()
        for slot_str in slots:
            try:
                hour, minute = map(int, slot_str.split(":"))
                slot_dt = datetime.datetime(target_day.year, target_day.month, target_day.day, hour, minute)
            except Exception:
                continue

            if slot_dt >= min_time:
                slot_iso = slot_dt.strftime("%Y-%m-%d %H:%M")
                if slot_iso not in booked_times:
                    rel = "วันนี้ " if day_offset == 0 else ("พรุ่งนี้ " if day_offset == 1 else f"วันที่ {slot_dt.strftime('%d/%m')} ")
                    return {
                        "scheduled_time": slot_iso,
                        "scheduled_timestamp": int(slot_dt.timestamp()),
                        "slot_label": f"{rel}{slot_str} น.",
                        "day_offset": day_offset
                    }

    fallback_dt = min_time + datetime.timedelta(hours=2)
    return {
        "scheduled_time": fallback_dt.strftime("%Y-%m-%d %H:%M"),
        "scheduled_timestamp": int(fallback_dt.timestamp()),
        "slot_label": f"วันนี้ {fallback_dt.strftime('%H:%M')} น.",
        "day_offset": 0
    }

def record_post_history(
    page_id: str,
    title: str,
    caption: str,
    post_type: str = "post",
    post_id: str = "",
    status: str = "posted",
    image_url: str = "",
    local_image_path: str = "",
    video_path: str = "",
    scheduled_time: str = "",
    is_fb_native: int = 1,
    user_id: int = 1,
    published_at: Optional[str] = None
) -> int:
    """บันทึกประวัติการโพสต์ลงตาราง scheduled_posts สำหรับทำสถิติและดูย้อนหลัง"""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pub_time = published_at or (now_str if status == "posted" else scheduled_time)
    sched_t = scheduled_time or now_str

    with get_connection() as conn:
        cursor = conn.cursor()
        fb_url = build_fb_post_url(post_id, page_id)
        cursor.execute("""
            INSERT INTO scheduled_posts (
                page_id, title, caption, post_type, post_id, status,
                image_url, local_image_path, video_path, scheduled_time,
                is_fb_native, published_at, user_id, fb_post_url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            page_id, title, caption, post_type, post_id, status,
            image_url, local_image_path, video_path, sched_t,
            is_fb_native, pub_time, user_id, fb_url
        ))
        conn.commit()
        return cursor.lastrowid

def get_posting_analytics(page_id: Optional[str] = None, user_id: Optional[int] = None) -> Dict:
    """
    คำนวณสถิติจำนวนการโพสต์แบบ Single-Query ประสิทธิภาพสูง:
    - วันนี้ (Today)
    - 7 วันที่ผ่านมา (Last 7 Days)
    - เดือนนี้ (This Month)
    - ทั้งหมด (All Time)
    - คิวรอปล่อยบน Facebook (FB Scheduled Queue)
    - สรุปรายวัน 7 วันล่าสุด (Daily Breakdown)
    """
    now = datetime.datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    d7_start = now - datetime.timedelta(days=6)
    d7_str = d7_start.strftime('%Y-%m-%d')
    month_str = now.strftime('%Y-%m')

    with get_connection() as conn:
        cursor = conn.cursor()

        params = [today_str, today_str, today_str, d7_str, month_str]
        extra_where = []
        extra_params = []
        if page_id:
            extra_where.append("page_id = ?")
            extra_params.append(page_id)
        if user_id:
            extra_where.append("user_id = ?")
            extra_params.append(user_id)

        all_params = tuple(params + extra_params)
        where_filter = (" AND " + " AND ".join(extra_where)) if extra_where else ""

        # 1. รวมสถิติหลักทั้งหมดใน 1 Query
        sql_summary = f"""
            SELECT
                COALESCE(SUM(CASE WHEN status = 'posted' AND substr(COALESCE(published_at, created_at || ''), 1, 10) = ? THEN 1 ELSE 0 END), 0) AS today_total,
                COALESCE(SUM(CASE WHEN status = 'posted' AND post_type = 'reel' AND substr(COALESCE(published_at, created_at || ''), 1, 10) = ? THEN 1 ELSE 0 END), 0) AS today_reels,
                COALESCE(SUM(CASE WHEN status = 'posted' AND post_type != 'reel' AND substr(COALESCE(published_at, created_at || ''), 1, 10) = ? THEN 1 ELSE 0 END), 0) AS today_posts,
                COALESCE(SUM(CASE WHEN status = 'posted' AND substr(COALESCE(published_at, created_at || ''), 1, 10) >= ? THEN 1 ELSE 0 END), 0) AS days7_total,
                COALESCE(SUM(CASE WHEN status = 'posted' AND substr(COALESCE(published_at, created_at || ''), 1, 7) = ? THEN 1 ELSE 0 END), 0) AS month_total,
                COALESCE(SUM(CASE WHEN status = 'posted' THEN 1 ELSE 0 END), 0) AS all_time_total,
                COALESCE(SUM(CASE WHEN status = 'fb_scheduled' THEN 1 ELSE 0 END), 0) AS scheduled_fb_total,
                COALESCE(SUM(CASE WHEN status IN ('fb_scheduled', 'scheduled') THEN 1 ELSE 0 END), 0) AS total_scheduled_queue
            FROM scheduled_posts
            WHERE 1=1 {where_filter}
        """
        cursor.execute(sql_summary, all_params)
        row = cursor.fetchone()

        # 2. รวมสถิติรายวัน 7 วันล่าสุดใน 1 Query ผ่าน GROUP BY
        sql_daily = f"""
            SELECT 
                substr(COALESCE(published_at, created_at || ''), 1, 10) AS p_date,
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN post_type = 'reel' THEN 1 ELSE 0 END), 0) AS reels,
                COALESCE(SUM(CASE WHEN post_type != 'reel' THEN 1 ELSE 0 END), 0) AS posts
            FROM scheduled_posts
            WHERE status = 'posted' 
              AND substr(COALESCE(published_at, created_at || ''), 1, 10) >= ?
              {where_filter}
            GROUP BY substr(COALESCE(published_at, created_at || ''), 1, 10)
        """
        cursor.execute(sql_daily, tuple([d7_str] + extra_params))
        daily_map = {r[0]: {"total": int(r[1]), "reels": int(r[2]), "posts": int(r[3])} for r in cursor.fetchall() if r[0]}

        daily_breakdown = []
        for d in range(6, -1, -1):
            day_date = (now - datetime.timedelta(days=d)).strftime('%Y-%m-%d')
            day_data = daily_map.get(day_date, {"total": 0, "reels": 0, "posts": 0})
            daily_breakdown.append({
                "date": day_date,
                "total": day_data["total"],
                "reels": day_data["reels"],
                "posts": day_data["posts"]
            })

        return {
            "today_total": int(row[0] or 0),
            "today_posts": int(row[2] or 0),
            "today_reels": int(row[1] or 0),
            "days7_total": int(row[3] or 0),
            "month_total": int(row[4] or 0),
            "all_time_total": int(row[5] or 0),
            "scheduled_fb_total": int(row[6] or 0),
            "scheduled_queue_total": int(row[7] or 0),
            "daily_breakdown": daily_breakdown
        }

def get_post_history(
    page_id: Optional[str] = None,
    post_type: Optional[str] = None,
    status: Optional[str] = None,
    date_filter: Optional[str] = None,
    limit: int = 100,
    user_id: Optional[int] = None
) -> List[Dict]:
    """ดึงรายการประวัติการโพสต์ย้อนหลัง พร้อมฟิลเตอร์ค้นหา"""
    now = datetime.datetime.now()
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
        if user_id:
            query += " AND sp.user_id = ?"
            params.append(user_id)
        if post_type and post_type != "all":
            query += " AND sp.post_type = ?"
            params.append(post_type)
        if status and status != "all":
            query += " AND sp.status = ?"
            params.append(status)

        if date_filter == "today":
            query += " AND substr(COALESCE(sp.published_at, sp.created_at || ''), 1, 10) = ?"
            params.append(now.strftime('%Y-%m-%d'))
        elif date_filter == "7days":
            query += " AND substr(COALESCE(sp.published_at, sp.created_at || ''), 1, 10) >= ?"
            params.append((now - datetime.timedelta(days=6)).strftime('%Y-%m-%d'))
        elif date_filter == "month":
            query += " AND substr(COALESCE(sp.published_at, sp.created_at || ''), 1, 7) = ?"
            params.append(now.strftime('%Y-%m'))

        query += " ORDER BY COALESCE(sp.scheduled_time, sp.created_at) DESC LIMIT ?"
        params.append(limit)
        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
        for r in rows:
            if not r.get("fb_post_url"):
                r["fb_post_url"] = build_fb_post_url(r.get("post_id"), r.get("page_id"))
        return rows

# -------------------------------------------------------------
# ระบบโพสต์ & วิเคราะห์เชิงกลยุทธ์ (Smart Publishing & Content Calendar)
# -------------------------------------------------------------
def get_calendar_events(
    page_id: Optional[str] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    user_id: Optional[int] = None
) -> Dict:
    """
    ดึงข้อมูลปฏิทินคอนเทนต์รายเดือน (Content Calendar)
    รวบรวมทั้งคิวที่ตั้งเวลาไว้ (Scheduled) และประวัติที่โพสต์แล้ว (Posted)
    พร้อมคำนวณโควตารายวันและสถิติแต่ละวัน
    """
    now = datetime.datetime.now()
    y = int(year) if year else now.year
    m = int(month) if month else now.month

    # จำนวนวันในเดือนและวันเริ่มต้นของสัปดาห์
    first_weekday, num_days = calendar.monthrange(y, m)
    # แปลง weekday ให้วันอาทิตย์ = 0, จันทร์ = 1 ... เสาร์ = 6
    start_col = (first_weekday + 1) % 7

    month_names_th = [
        "", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
        "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"
    ]
    month_label = f"{month_names_th[m]} {y}"

    if m == 1:
        prev_m, prev_y = 12, y - 1
    else:
        prev_m, prev_y = m - 1, y

    if m == 12:
        next_m, next_y = 1, y + 1
    else:
        next_m, next_y = m + 1, y

    month_str = f"{y:04d}-{m:02d}"

    # ดึงโพสต์ในเดือนนี้
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        query = """
            SELECT sp.*, p.name as page_name
            FROM scheduled_posts sp
            LEFT JOIN pages p ON sp.page_id = p.page_id
            WHERE (
                sp.scheduled_time LIKE ? OR
                sp.published_at LIKE ? OR
                sp.created_at LIKE ?
            )
        """
        params = [f"{month_str}%", f"{month_str}%", f"{month_str}%"]
        if page_id:
            query += " AND sp.page_id = ?"
            params.append(page_id)
        if user_id:
            query += " AND sp.user_id = ?"
            params.append(user_id)
        query += " ORDER BY COALESCE(sp.scheduled_time, sp.created_at) ASC"
        cursor.execute(query, params)
        raw_posts = [dict(r) for r in cursor.fetchall()]

    rules = get_page_schedule_rules(page_id) if page_id else {}
    daily_quota = rules.get("posts_per_day", 4)

    events_by_date = {}
    for p in raw_posts:
        time_field = str(p.get("scheduled_time") or p.get("published_at") or p.get("created_at") or "").strip()
        date_key = time_field[:10].replace("T", " ")
        if not date_key.startswith(month_str):
            continue

        ptype = str(p.get("post_type") or "post").lower()
        time_part = time_field[11:16] if len(time_field) >= 16 else "00:00"

        type_meta = {
            "post": {"label": "ข่าวสาร", "icon": "fa-newspaper", "color": "red"},
            "news": {"label": "ข่าวสาร", "icon": "fa-newspaper", "color": "red"},
            "card": {"label": "การ์ดภาพ", "icon": "fa-id-card", "color": "emerald"},
            "match": {"label": "Match Center", "icon": "fa-futbol", "color": "emerald"},
            "affiliate": {"label": "Affiliate", "icon": "fa-bag-shopping", "color": "amber"},
            "flow_image": {"label": "รูป AI", "icon": "fa-paintbrush", "color": "pink"},
            "reel": {"label": "Reels AI", "icon": "fa-video", "color": "purple"}
        }.get(ptype, {"label": "โพสต์", "icon": "fa-file-lines", "color": "blue"})

        post_item = {
            "id": p.get("id"),
            "page_id": p.get("page_id"),
            "page_name": p.get("page_name") or "เพจ Facebook",
            "title": p.get("title") or (p.get("caption", "")[:32] + "..."),
            "caption": p.get("caption", ""),
            "time": time_part,
            "status": p.get("status"),
            "post_type": ptype,
            "type_label": type_meta["label"],
            "type_icon": type_meta["icon"],
            "type_color": type_meta["color"],
            "image_url": p.get("image_url") or "",
            "local_image_path": p.get("local_image_path") or "",
            "is_fb_native": p.get("is_fb_native", 1),
            "fb_post_url": p.get("fb_post_url") or (f"https://facebook.com/{p.get('post_id')}" if p.get('post_id') else "")
        }

        if date_key not in events_by_date:
            events_by_date[date_key] = []
        events_by_date[date_key].append(post_item)

    days_list = []
    today_str = now.strftime("%Y-%m-%d")
    for d in range(1, num_days + 1):
        d_str = f"{y:04d}-{m:02d}-{d:02d}"
        posts_on_day = events_by_date.get(d_str, [])
        is_today = (d_str == today_str)
        is_past = (d_str < today_str)

        days_list.append({
            "day": d,
            "date": d_str,
            "is_today": is_today,
            "is_past": is_past,
            "posts_count": len(posts_on_day),
            "quota_goal": daily_quota,
            "quota_reached": len(posts_on_day) >= daily_quota,
            "posts": posts_on_day
        })

    return {
        "year": y,
        "month": m,
        "month_label": month_label,
        "num_days": num_days,
        "start_weekday": start_col,
        "prev_year": prev_y,
        "prev_month": prev_m,
        "next_year": next_y,
        "next_month": next_m,
        "daily_quota": daily_quota,
        "total_posts_in_month": len(raw_posts),
        "days": days_list,
        "events_by_date": events_by_date
    }

def get_golden_posting_hours(page_id: Optional[str] = None) -> Dict:
    """
    วิเคราะห์ช่วงเวลาทองในการโพสต์ 24 ชั่วโมง (Golden Hours Heatmap & AI Auto-Slot)
    อิงจากพฤติกรรมการเสพคอนเทนต์ฟุตบอล & ข่าวสารของแฟนเพจชาวไทย
    """
    hourly_profiles = [
        {"hour": "00:00", "score": 20, "tier": "low", "desc": "เวลานอน ดึกมาก", "best_type": "สรุปผลค่ำคืน"},
        {"hour": "01:00", "score": 12, "tier": "low", "desc": "เวลานอน ยอดวิวต่ำ", "best_type": "-"},
        {"hour": "02:00", "score": 8,  "tier": "low", "desc": "เวลาหลับใหล", "best_type": "-"},
        {"hour": "03:00", "score": 8,  "tier": "low", "desc": "เวลาหลับใหล", "best_type": "-"},
        {"hour": "04:00", "score": 10, "tier": "low", "desc": "ก่อนรุ่งเช้า", "best_type": "-"},
        {"hour": "05:00", "score": 25, "tier": "low", "desc": "เริ่มตื่นนอน ข่าวแรก", "best_type": "Morning News"},
        {"hour": "06:00", "score": 45, "tier": "medium", "desc": "ตื่นนอน เช็กมือถือ", "best_type": "สรุปผลบอลเมื่อคืน"},
        {"hour": "07:00", "score": 62, "tier": "medium", "desc": "เดินทางไปทำงาน/เรียน", "best_type": "พาดหัวข่าวด่วน"},
        {"hour": "08:00", "score": 58, "tier": "medium", "desc": "เริ่มงานยามเช้า", "best_type": "รูปคำพูดนักเตะ"},
        {"hour": "09:00", "score": 52, "tier": "medium", "desc": "ช่วงเริ่มงานเช้า", "best_type": "บทความวิเคราะห์"},
        {"hour": "10:00", "score": 48, "tier": "medium", "desc": "ทำงานจริงจัง", "best_type": "ข่าวสั้น"},
        {"hour": "11:00", "score": 65, "tier": "high", "desc": "เตรียมพักเที่ยง", "best_type": "ข่าวด่วนรอบวัน"},
        {"hour": "12:00", "score": 88, "tier": "peak", "desc": "พักเที่ยง คนเปิดดูเยอะ (Peak 1)", "best_type": "ข่าวด่วน & ดีลนักเตะ"},
        {"hour": "13:00", "score": 82, "tier": "peak", "desc": "ช่วงพักบ่าย ท่องโซเชียล", "best_type": "สินค้า Affiliate / เสื้อบอล"},
        {"hour": "14:00", "score": 46, "tier": "low", "desc": "ทำงานช่วงบ่าย", "best_type": "บทความทั่วไป"},
        {"hour": "15:00", "score": 50, "tier": "medium", "desc": "แก้ง่วงยามบ่าย", "best_type": "มีม / คอมมูนิตี้"},
        {"hour": "16:00", "score": 60, "tier": "medium", "desc": "เตรียมเลิกงาน", "best_type": "ไฮไลต์สั้น"},
        {"hour": "17:00", "score": 75, "tier": "high", "desc": "เลิกงาน เดินทางกลับ", "best_type": "พรีวิวแมตช์เดย์"},
        {"hour": "18:00", "score": 92, "tier": "peak", "desc": "ช่วงเดินทาง & พักผ่อน (Peak 2)", "best_type": "พรีวิว & ข่าวใหญ่"},
        {"hour": "19:00", "score": 88, "tier": "peak", "desc": "รับประทานอาหารเย็น", "best_type": "วิดีโอ Reels / ภาพ AI"},
        {"hour": "20:00", "score": 94, "tier": "super_peak", "desc": "เริ่มเข้าสู่ Prime Time", "best_type": "พรีวิวเข้มข้น & ไฮไลต์"},
        {"hour": "21:00", "score": 99, "tier": "super_peak", "desc": "สุดยอด Prime Time ฟุตบอล (Peak 3)", "best_type": "ผลบอลสด / ไลน์อัพ / ตัดเกรด"},
        {"hour": "22:00", "score": 95, "tier": "super_peak", "desc": "ช่วงคอมเมนต์หลังแข่ง", "best_type": "ตัดเกรด & ประเด็นหลังเกม"},
        {"hour": "23:00", "score": 72, "tier": "high", "desc": "ก่อนนอน สรุปประเด็น", "best_type": "สรุปคะแนน & ราตรีสวัสดิ์"}
    ]

    golden_windows = [
        {
            "id": "lunch",
            "title": "ช่วงเที่ยงวัน (Lunch Peak)",
            "time_range": "11:30 - 13:30 น.",
            "traffic_score": 88,
            "badge_color": "emerald",
            "recommended_types": "ข่าวด่วน, ดีลซื้อขาย, สินค้า Affiliate แฟลชเซลล์",
            "description": "ช่วงพักกลางวัน แฟนเพจหยิบมือถือเช็กข่าวรอบวัน อัตรา Click-Through สูงสุด"
        },
        {
            "id": "evening",
            "title": "ช่วงเลิกงาน (Evening Rush)",
            "time_range": "17:30 - 19:30 น.",
            "traffic_score": 92,
            "badge_color": "blue",
            "recommended_types": "พรีวิวแมตช์, วิดีโอสั้น Reels, ภาพเจน AI",
            "description": "ช่วงเดินทางกลับบ้านและพักผ่อน คอนเทนต์ภาพสวยและวิดีโอหยุดนิ้วโป้งได้ดีที่สุด"
        },
        {
            "id": "prime_night",
            "title": "ช่วงค่ำไพรม์ไทม์ (Super Prime Night)",
            "time_range": "20:30 - 23:00 น.",
            "traffic_score": 99,
            "badge_color": "amber",
            "recommended_types": "ตัดเกรดนักเตะ, ผลบอลสด, คอมมูนิตี้ถกเถียง, สินค้าโปรเด็ด",
            "description": "ชั่วโมงทองคำของเพจกีฬา ยอดการเข้าถึง (Reach) และการคอมเมนต์ (Comments) สูงที่สุดใน 24 ชั่วโมง"
        }
    ]

    now = datetime.datetime.now()
    min_time = now + datetime.timedelta(minutes=15)
    golden_targets = ["12:00", "13:00", "18:00", "19:00", "21:00", "22:00"]

    booked_times = set()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT scheduled_time FROM scheduled_posts
            WHERE status IN ('scheduled', 'fb_scheduled')
            AND scheduled_time >= ?
        """, (now.strftime("%Y-%m-%d"),))
        for row in cursor.fetchall():
            if row[0]:
                booked_times.add(str(row[0])[:16].replace("T", " "))

    recommended_slot = None
    recommended_label = ""
    recommended_score = 95

    # เช็กสล็อตทองของวันนี้
    today_str = now.strftime("%Y-%m-%d")
    for t_str in golden_targets:
        candidate = datetime.datetime.strptime(f"{today_str} {t_str}", "%Y-%m-%d %H:%M")
        if candidate >= min_time:
            c_iso = candidate.strftime("%Y-%m-%d %H:%M")
            if c_iso not in booked_times:
                recommended_slot = c_iso
                recommended_label = f"วันนี้ เวลา {t_str} น. (เวลาทอง AI 🔥)"
                score = next((h["score"] for h in hourly_profiles if h["hour"].startswith(t_str[:2])), 90)
                recommended_score = score
                break

    # ถ้าวันนี้เต็มแล้ว เช็กวันพรุ่งนี้
    if not recommended_slot:
        tomorrow = now + datetime.timedelta(days=1)
        tomorrow_str = tomorrow.strftime("%Y-%m-%d")
        for t_str in golden_targets:
            candidate = datetime.datetime.strptime(f"{tomorrow_str} {t_str}", "%Y-%m-%d %H:%M")
            c_iso = candidate.strftime("%Y-%m-%d %H:%M")
            if c_iso not in booked_times:
                recommended_slot = c_iso
                recommended_label = f"พรุ่งนี้ เวลา {t_str} น. (เวลาทอง AI 🔥)"
                score = next((h["score"] for h in hourly_profiles if h["hour"].startswith(t_str[:2])), 90)
                recommended_score = score
                break

    return {
        "hourly_profiles": hourly_profiles,
        "golden_windows": golden_windows,
        "recommended_slot": recommended_slot or (now + datetime.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"),
        "recommended_label": recommended_label or "เวลาที่แนะนำถัดไป",
        "recommended_score": recommended_score
    }

def get_content_strategy_analytics(page_id: Optional[str] = None, user_id: Optional[int] = None) -> Dict:
    """
    วิเคราะห์สัดส่วนคอนเทนต์เชิงกลยุทธ์ (Content Mix Strategy)
    และคำนวณคะแนน Algorithm Health Score พร้อมข้อแนะนำ AI
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        base_filter = " WHERE 1=1"
        params = []
        if page_id:
            base_filter += " AND page_id = ?"
            params.append(page_id)
        if user_id:
            base_filter += " AND user_id = ?"
            params.append(user_id)

        cursor.execute(f"""
            SELECT 
                COALESCE(post_type, 'post') as ptype,
                COUNT(*) as count
            FROM scheduled_posts
            {base_filter}
            AND (
                DATE(COALESCE(published_at, created_at)) >= DATE('now', '-30 days', 'localtime')
                OR status IN ('scheduled', 'fb_scheduled')
            )
            GROUP BY ptype
        """, params)
        rows = cursor.fetchall()

    type_counts = {
        "news": 0,
        "match": 0,
        "affiliate": 0,
        "image_gen": 0,
        "reel": 0
    }
    total_posts = 0
    for r in rows:
        raw_type = (r[0] or "post").lower()
        cnt = r[1] or 0
        total_posts += cnt
        if raw_type in ["news", "post", "card"]:
            type_counts["news"] += cnt
        elif raw_type in ["match", "preview", "grades"]:
            type_counts["match"] += cnt
        elif raw_type in ["affiliate", "shopee", "lazada", "tiktok"]:
            type_counts["affiliate"] += cnt
        elif raw_type in ["flow_image", "image_gen", "image"]:
            type_counts["image_gen"] += cnt
        elif raw_type in ["reel", "video"]:
            type_counts["reel"] += cnt
        else:
            type_counts["news"] += cnt

    effective_total = max(total_posts, 1)

    categories = [
        {
            "id": "news",
            "name": "ข่าวสาร & บทความ",
            "icon": "fa-newspaper",
            "color": "red",
            "hex": "#dc2626",
            "count": type_counts["news"],
            "actual_pct": round((type_counts["news"] / effective_total) * 100, 1),
            "target_pct": 45,
            "status": "optimal" if 35 <= ((type_counts["news"] / effective_total) * 100) <= 60 else "adjust"
        },
        {
            "id": "match",
            "name": "Match Center & ตัดเกรด",
            "icon": "fa-futbol",
            "color": "emerald",
            "hex": "#10b981",
            "count": type_counts["match"],
            "actual_pct": round((type_counts["match"] / effective_total) * 100, 1),
            "target_pct": 20,
            "status": "optimal" if 15 <= ((type_counts["match"] / effective_total) * 100) <= 30 else "adjust"
        },
        {
            "id": "affiliate",
            "name": "สินค้า Affiliate สร้างรายได้",
            "icon": "fa-bag-shopping",
            "color": "amber",
            "hex": "#f59e0b",
            "count": type_counts["affiliate"],
            "actual_pct": round((type_counts["affiliate"] / effective_total) * 100, 1),
            "target_pct": 15,
            "status": "warning" if ((type_counts["affiliate"] / effective_total) * 100) > 30 else "optimal"
        },
        {
            "id": "image_gen",
            "name": "รูปเจน AI (Flow Studio)",
            "icon": "fa-paintbrush",
            "color": "pink",
            "hex": "#ec4899",
            "count": type_counts["image_gen"],
            "actual_pct": round((type_counts["image_gen"] / effective_total) * 100, 1),
            "target_pct": 10,
            "status": "optimal"
        },
        {
            "id": "reel",
            "name": "คลิปสั้น Reels AI",
            "icon": "fa-video",
            "color": "purple",
            "hex": "#8b5cf6",
            "count": type_counts["reel"],
            "actual_pct": round((type_counts["reel"] / effective_total) * 100, 1),
            "target_pct": 10,
            "status": "optimal"
        }
    ]

    score = 85
    affiliate_pct = (type_counts["affiliate"] / effective_total) * 100
    if affiliate_pct > 30:
        score -= int((affiliate_pct - 30) * 1.5)
    elif affiliate_pct > 20:
        score -= 5

    news_pct = (type_counts["news"] / effective_total) * 100
    if news_pct > 75:
        score -= 10

    if type_counts["match"] > 0:
        score += 5
    if type_counts["image_gen"] > 0:
        score += 5

    score = max(50, min(98, score))

    recommendations = []
    if affiliate_pct > 25:
        recommendations.append({
            "type": "warning",
            "icon": "fa-triangle-exclamation",
            "title": "สัดส่วน Affiliate ค่อนข้างถี่ (Spam Prevention)",
            "message": f"ปัจจุบันโพสต์สินค้ามีสัดส่วน {affiliate_pct:.1f}% ของทั้งเพจ แนะนำให้ลงข่าวสารหรือภาพ AI สลับอย่างน้อย 3 โพสต์ต่อ 1 โพสต์สินค้า เพื่อป้องกันไม่ให้อัลกอริทึม Facebook ลดการมองเห็น"
        })
    else:
        recommendations.append({
            "type": "success",
            "icon": "fa-circle-check",
            "title": "สัดส่วนโพสต์สร้างรายได้อยู่ในเกณฑ์ปลอดภัย",
            "message": "เพจของคุณมีสมดุลที่ดีระหว่างคอนเทนต์สาระและการโปรโมทสินค้า Affiliate แฟนเพจจะไม่รู้สึกถูกยัดเยียด"
        })

    if type_counts["match"] < 2:
        recommendations.append({
            "type": "opportunity",
            "icon": "fa-futbol",
            "title": "กระตุ้นยอด Engagement ด้วย Match Center",
            "message": "โพสต์ประเภทพรีวิวและตัดเกรดนักเตะหลังเกมสร้างคอมเมนต์ได้สูงกว่าข่าวปกติถึง 3.2 เท่า แนะนำตั้งเวลาพรีวิวก่อนแข่ง 24 ชั่วโมง และตัดเกรดหลังเกมจบ 1 ชั่วโมง"
        })

    recommendations.append({
        "type": "golden_hour",
        "icon": "fa-bolt",
        "title": "ใช้ประโยชน์จาก Golden Slot ช่วง 20:30 - 22:30 น.",
        "message": "เป็นช่วงที่แฟนบอลออนไลน์สูงสุดของวัน หากมีภาพสวยจาก AI Flow หรือคลิปสั้น แนะนำตั้งเวลาลงในช่วงนี้เพื่อบูสต์ Reach ให้พุ่งสูงสุด"
    })

    return {
        "total_posts": total_posts,
        "health_score": score,
        "health_rating": "ยอดเยี่ยม (Healthy Mix)" if score >= 85 else "ดี (Good Balance)" if score >= 70 else "ควรปรับปรุง (Needs Attention)",
        "categories": categories,
        "recommendations": recommendations
    }

# -------------------------------------------------------------
# จัดการสมาชิก & สิทธิ์ระบบ (User & SaaS Management)
# -------------------------------------------------------------
def get_user_by_id(user_id: int) -> Optional[Dict]:
    """ดึงข้อมูลผู้ใช้ตาม ID"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_user_by_email(email: str) -> Optional[Dict]:
    """ดึงข้อมูลผู้ใช้ตาม Email"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(?)", (email.strip(),))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_all_users() -> List[Dict]:
    """ดึงรายชื่อสมาชิกทั้งหมดสำหรับระบบหลังบ้าน Admin"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.*,
                   (SELECT COUNT(*) FROM pages WHERE user_id = u.id) as pages_count,
                   (SELECT COUNT(*) FROM scheduled_posts WHERE user_id = u.id) as scheduled_count
            FROM users u
            ORDER BY u.id ASC
        """)
        return [dict(r) for r in cursor.fetchall()]

def create_or_update_google_user(email: str, name: str, avatar_url: str = "", role: str = "member", plan_name: str = "Free Trial") -> Dict:
    """สร้างหรืออัปเดตสมาชิกจากการเข้าสู่ระบบ Google Account (Mockup & Real)"""
    existing = get_user_by_email(email)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if existing:
            cursor.execute("""
                UPDATE users
                SET name = ?, avatar_url = CASE WHEN ? != '' THEN ? ELSE avatar_url END,
                    last_login_at = ?
                WHERE id = ?
            """, (name, avatar_url, avatar_url, now_str, existing["id"]))
            conn.commit()
            return get_user_by_id(existing["id"])
        else:
            expires_at = (datetime.datetime.now() + datetime.timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
            credits = 999 if role == "admin" else (30 if plan_name == "Pro" else 5)
            cursor.execute("""
                INSERT INTO users (email, name, avatar_url, role, plan_name, plan_expires_at, video_credits, status, last_login_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
            """, (email.strip(), name.strip(), avatar_url, role, plan_name, expires_at, credits, now_str))
            conn.commit()
            new_id = cursor.lastrowid
            return get_user_by_id(new_id)

def update_user_admin(user_id: int, plan_name: str, video_credits: int, status: str, role: str) -> bool:
    """แอดมินอัปเดตข้อมูลและสิทธิ์ของสมาชิก"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users
            SET plan_name = ?, video_credits = ?, status = ?, role = ?
            WHERE id = ?
        """, (plan_name, video_credits, status, role, user_id))
        conn.commit()
        return True

def delete_user(user_id: int) -> bool:
    """ลบสมาชิกออกจากระบบ"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return True

def deduct_user_video_credit(user_id: int) -> bool:
    """หักเครดิตสร้างวิดีโอ 1 เครดิต (ถ้ามี)"""
    user = get_user_by_id(user_id)
    if not user:
        return False
    if user["role"] == "admin":
        return True  # แอดมินใช้ได้ไม่จำกัด
    if user["video_credits"] <= 0:
        return False
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET video_credits = video_credits - 1 WHERE id = ?", (user_id,))
        conn.commit()
        return True

def get_admin_metrics() -> Dict:
    """คำนวณสถิติภาพรวมสำหรับหน้า Admin Dashboard"""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE status = 'active'")
        active_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        admin_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM pages")
        total_pages = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM scheduled_posts")
        total_scheduled = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM articles")
        total_articles = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(video_credits) FROM users")
        total_credits = cursor.fetchone()[0] or 0

        # คำนวณ MRR จำลอง (Pro: 490, VIP: 990)
        cursor.execute("SELECT COUNT(*) FROM users WHERE plan_name = 'Pro'")
        pro_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE plan_name = 'VIP Agency'")
        vip_count = cursor.fetchone()[0]
        estimated_mrr = (pro_count * 490) + (vip_count * 990)

        return {
            "total_users": total_users,
            "active_users": active_users,
            "admin_count": admin_count,
            "total_pages": total_pages,
            "total_scheduled": total_scheduled,
            "total_articles": total_articles,
            "total_credits": total_credits,
            "estimated_mrr": estimated_mrr,
            "pro_count": pro_count,
            "vip_count": vip_count
        }

# -------------------------------------------------------------
# จัดการ Google Gemini API Keys ประจำตัวสมาชิก (BYOK)
# -------------------------------------------------------------
def get_user_api_keys(user_id: int) -> List[Dict]:
    """ดึงรายการ Google API Keys ทั้งหมดของสมาชิกคนนี้"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM user_api_keys
            WHERE user_id = ?
            ORDER BY id ASC
        """, (user_id,))
        rows = [dict(r) for r in cursor.fetchall()]
        # ทำ Masking สำหรับการแสดงผล (เช่น AIzaSyB9...W842X)
        for r in rows:
            raw = r["api_key"]
            if len(raw) > 12:
                r["masked_key"] = raw[:8] + "..." + raw[-4:]
            else:
                r["masked_key"] = "AIzaSy***"
        return rows

def add_user_api_key(user_id: int, api_key: str, label: str = "") -> Optional[Dict]:
    """เพิ่ม Google API Key ใหม่ให้กับสมาชิก (ไม่จำกัดจำนวน)"""
    clean_key = api_key.strip()
    clean_label = label.strip() or "Google Gemini Key"
    if not clean_key:
        return None
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO user_api_keys (user_id, api_key, label, is_active)
            VALUES (?, ?, ?, 1)
        """, (user_id, clean_key, clean_label))
        conn.commit()
        new_id = cursor.lastrowid
        return {"id": new_id, "label": clean_label, "api_key": clean_key, "is_active": 1}

def update_user_api_key(key_id: int, user_id: int, api_key: str, label: str, is_active: int = 1) -> bool:
    """แก้ไข API Key หรือ Label หรือสถานะเปิด/ปิด"""
    with get_connection() as conn:
        cursor = conn.cursor()
        if api_key and api_key.strip() and not api_key.startswith("AIzaSy***"):
            cursor.execute("""
                UPDATE user_api_keys
                SET api_key = ?, label = ?, is_active = ?
                WHERE id = ? AND user_id = ?
            """, (api_key.strip(), label.strip(), is_active, key_id, user_id))
        else:
            cursor.execute("""
                UPDATE user_api_keys
                SET label = ?, is_active = ?
                WHERE id = ? AND user_id = ?
            """, (label.strip(), is_active, key_id, user_id))
        conn.commit()
        return True

def toggle_user_api_key(key_id: int, user_id: int) -> bool:
    """สลับสถานะเปิด/ปิดการใช้งานของ API Key"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE user_api_keys
            SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END
            WHERE id = ? AND user_id = ?
        """, (key_id, user_id))
        conn.commit()
        return True

def delete_user_api_key(key_id: int, user_id: int) -> bool:
    """ลบ Google API Key ของสมาชิก"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_api_keys WHERE id = ? AND user_id = ?", (key_id, user_id))
        conn.commit()
        return True

def get_active_api_keys_for_user(user_id: int) -> List[str]:
    """ดึงรายชื่อ API Keys ที่เปิดใช้งานอยู่ของสมาชิกเพื่อหมุนเวียน (Load Balancing & Failover)"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT api_key FROM user_api_keys
            WHERE user_id = ? AND is_active = 1
            ORDER BY id ASC
        """, (user_id,))
        keys = [r[0] for r in cursor.fetchall()]
        if keys:
            return keys
    # ถ้าสมาชิกไม่มี Key ให้ Fallback ไปที่ System Key ใน .env
    if config.GEMINI_API_KEY:
        return [config.GEMINI_API_KEY]
    return []

def record_api_key_usage(api_key: str):
    """บันทึกสถิติการเรียกใช้งานของ API Key"""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE user_api_keys
            SET usage_count = usage_count + 1, last_used_at = ?
            WHERE api_key = ?
        """, (now_str, api_key.strip()))
        conn.commit()

# สร้างตารางทันทีเมื่อโหลดโมดูล
init_db()
