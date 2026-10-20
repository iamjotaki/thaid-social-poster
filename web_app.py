import os
import sys
import json
import time
import sqlite3
import datetime
import threading
import webbrowser
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory

# ปรับ encoding ของ stdout/stderr บน Windows
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import config
from database import (
    get_connection,
    get_all_pages,
    get_page_by_id,
    save_or_update_page,
    delete_page,
    get_feeds_by_page,
    add_feed_to_page,
    toggle_feed,
    delete_feed,
    get_recent_articles,
    is_article_seen,
    mark_as_posted,
    update_rewritten,
    save_article,
    create_scheduled_post,
    get_scheduled_posts,
    get_due_scheduled_posts,
    update_scheduled_post_status,
    cancel_scheduled_post,
    delete_scheduled_post,
    update_card_image
)
from news_fetcher import fetch_all_new_articles, download_image
from ai_rewriter import rewrite_article
from fb_poster import post_to_facebook, post_reel_to_facebook
from card_generator import generate_social_card
from match_center import (
    get_liverpool_schedule,
    get_premier_league_standings,
    generate_ai_match_preview,
    generate_ai_player_ratings,
    generate_ai_postmatch_report
)
from video_generator import generate_short_video
from community_manager import (
    generate_engagement_post,
    draft_ai_comment_reply,
    fetch_facebook_post_comments,
    reply_to_facebook_comment
)
from affiliate_manager import (
    load_affiliate_products,
    save_affiliate_products,
    attach_affiliate_if_enabled
)

app = Flask(__name__, template_folder="templates", static_folder="static")

# ตัวแปรสถานะเบื้องหลัง
auto_bot_running = False
auto_bot_interval = 30  # นาที
auto_thread = None
scheduler_thread = None
system_logs = []
MAX_LOGS = 150

def add_log(message: str, level: str = "info"):
    """บันทึก Log ลงหน่วยความจำสำหรับส่งให้ Frontend"""
    timestamp = time.strftime("%H:%M:%S")
    entry = {"time": timestamp, "message": message, "level": level}
    system_logs.insert(0, entry)
    if len(system_logs) > MAX_LOGS:
        system_logs.pop()
    print(f"[{timestamp}] {message}")

# -------------------------------------------------------------
# WEB ROUTES
# -------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/images/<path:filename>")
def serve_image(filename):
    """ส่งรูปภาพที่บอทดาวน์โหลดไว้"""
    images_dir = config.BASE_DIR / "downloads" / "images"
    return send_from_directory(images_dir, filename)

@app.route("/cards/<path:filename>")
def serve_card(filename):
    """ส่งรูปภาพ Social Card ที่สร้างไว้"""
    cards_dir = config.BASE_DIR / "downloads" / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    return send_from_directory(cards_dir, filename)

@app.route("/videos/<path:filename>")
def serve_video(filename):
    """ส่งไฟล์วิดีโอสั้น MP4 สำหรับ TikTok / Reels / Shorts"""
    videos_dir = config.BASE_DIR / "downloads" / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    return send_from_directory(videos_dir, filename)

# -------------------------------------------------------------
# API: STATUS & OVERVIEW
# -------------------------------------------------------------
@app.route("/api/status")
def get_status():
    """ดึงสถานะระบบปัจจุบันและสถิติภาพรวม"""
    page_id = request.args.get("page_id")
    with get_connection() as conn:
        cursor = conn.cursor()
        
        if page_id:
            cursor.execute("SELECT COUNT(*) FROM articles WHERE page_id = ?", (page_id,))
            total_news = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM articles WHERE status = 'posted' AND page_id = ?", (page_id,))
            posted_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM articles WHERE status != 'posted' AND page_id = ?", (page_id,))
            pending_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM page_feeds WHERE page_id = ? AND is_enabled = 1", (page_id,))
            sources_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM scheduled_posts WHERE page_id = ? AND status = 'scheduled'", (page_id,))
            scheduled_count = cursor.fetchone()[0]
        else:
            cursor.execute("SELECT COUNT(*) FROM articles")
            total_news = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM articles WHERE status = 'posted'")
            posted_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM articles WHERE status != 'posted'")
            pending_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM page_feeds WHERE is_enabled = 1")
            sources_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'scheduled'")
            scheduled_count = cursor.fetchone()[0]

    pages = get_all_pages()
    return jsonify({
        "gemini_ready": bool(config.GEMINI_API_KEY),
        "fb_ready": len(pages) > 0,
        "pages_count": len(pages),
        "dry_run": config.DRY_RUN,
        "auto_running": auto_bot_running,
        "interval_minutes": auto_bot_interval,
        "stats": {
            "total": total_news,
            "posted": posted_count,
            "pending": pending_count,
            "sources_count": sources_count,
            "scheduled_count": scheduled_count
        }
    })

# -------------------------------------------------------------
# API: ANALYTICS & INSIGHTS (สถิติวิว, คลิก, การมีส่วนร่วม)
# -------------------------------------------------------------
@app.route("/api/analytics", methods=["GET"])
def api_get_analytics():
    """ดึงข้อมูลสถิติเชิงลึกของเพจและโพสต์ (Followers, Reactions, Comments, Shares, Views/Clicks)"""
    import requests
    page_id = request.args.get("page_id")
    
    # หากไม่ได้ระบุ page_id ให้เลือกเพจแรกในระบบ
    pages = get_all_pages()
    if not pages:
        return jsonify({"success": False, "error": "ยังไม่มีเพจในระบบ"}), 404

    target_page = None
    if page_id:
        target_page = get_page_by_id(page_id)
    if not target_page:
        target_page = pages[0]

    pid = target_page["page_id"]
    token = target_page["access_token"]
    pname = target_page["name"]

    try:
        # 1. ข้อมูลพื้นฐานของเพจ (Page Metadata & Followers)
        url_page = f"https://graph.facebook.com/v19.0/{pid}?fields=name,about,fan_count,followers_count,link,talking_about_count,category&access_token={token}"
        r_page = requests.get(url_page, timeout=10)
        page_data = r_page.json() if r_page.status_code == 200 else {}

        # 2. ตรวจสอบสิทธิ์ (Scopes) ว่ามี read_insights หรือไม่
        has_insights_scope = False
        try:
            url_debug = f"https://graph.facebook.com/v19.0/debug_token?input_token={token}&access_token={token}"
            r_debug = requests.get(url_debug, timeout=10)
            if r_debug.status_code == 200:
                scopes = r_debug.json().get("data", {}).get("scopes", [])
                has_insights_scope = "read_insights" in scopes
        except Exception:
            pass

        # 3. ดึงโพสต์ล่าสุดพร้อมสถิติ (Reactions, Comments, Shares)
        url_posts = f"https://graph.facebook.com/v19.0/{pid}/published_posts?fields=id,message,created_time,full_picture,permalink_url,shares,comments.summary(true),reactions.summary(true)&limit=15&access_token={token}"
        r_posts = requests.get(url_posts, timeout=12)
        posts_raw = r_posts.json().get("data", []) if r_posts.status_code == 200 else []

        posts_analytics = []
        total_reactions = 0
        total_comments = 0
        total_shares = 0

        for p in posts_raw:
            rx_count = p.get("reactions", {}).get("summary", {}).get("total_count", 0)
            cm_count = p.get("comments", {}).get("summary", {}).get("total_count", 0)
            sh_count = p.get("shares", {}).get("count", 0) if p.get("shares") else 0

            total_reactions += rx_count
            total_comments += cm_count
            total_shares += sh_count

            posts_analytics.append({
                "id": p.get("id"),
                "message": (p.get("message") or "").strip(),
                "created_time": p.get("created_time"),
                "full_picture": p.get("full_picture"),
                "permalink_url": p.get("permalink_url"),
                "reactions": rx_count,
                "comments": cm_count,
                "shares": sh_count
            })

        return jsonify({
            "success": True,
            "page": {
                "id": pid,
                "name": page_data.get("name", pname),
                "followers": page_data.get("followers_count", 0),
                "fans": page_data.get("fan_count", 0),
                "talking_about": page_data.get("talking_about_count", 0),
                "link": page_data.get("link", f"https://facebook.com/{pid}"),
                "category": page_data.get("category", "General")
            },
            "summary": {
                "posts_count": len(posts_analytics),
                "total_reactions": total_reactions,
                "total_comments": total_comments,
                "total_shares": total_shares
            },
            "has_read_insights_scope": has_insights_scope,
            "posts": posts_analytics
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# -------------------------------------------------------------
# API: PAGES MANAGEMENT (จัดการเพจหลายเพจ)
# -------------------------------------------------------------
@app.route("/api/pages", methods=["GET"])
def api_get_pages():
    """ดึงรายชื่อเพจทั้งหมดพร้อมจำนวนฟีด"""
    pages = get_all_pages()
    return jsonify(pages)

@app.route("/api/pages/save", methods=["POST"])
def api_save_page():
    """เพิ่มหรืออัปเดตเพจ Facebook"""
    data = request.json or {}
    page_id = str(data.get("page_id", "")).strip()
    name = str(data.get("name", "")).strip()
    token = str(data.get("access_token", "")).strip()
    is_active = 1 if data.get("is_active", True) else 0

    if not page_id or not token:
        return jsonify({"success": False, "error": "กรุณากรอก Page ID และ Access Token"}), 400

    if not name:
        name = f"เพจ {page_id}"

    success = save_or_update_page(page_id, name, token, is_active)
    if success:
        # หากยังไม่มีฟีดในเพจนี้ ให้เพิ่มฟีดมาตรฐาน 3 แหล่ง
        feeds = get_feeds_by_page(page_id)
        if not feeds:
            add_feed_to_page(page_id, "This Is Anfield", "https://www.thisisanfield.com/feed/")
            add_feed_to_page(page_id, "DaveOCKOP", "https://www.daveockop.com/feed/")
            add_feed_to_page(page_id, "Anfield Watch", "https://www.anfieldwatch.co.uk/feed")

        add_log(f"💾 บันทึกและอัปเดตเพจสำเร็จ: '{name}' (ID: {page_id})", "success")

        # ซิงค์กลับไฟล์ .env หากเป็นเพจหลัก
        if page_id == config.FB_PAGE_ID:
            config.FB_PAGE_ACCESS_TOKEN = token
            try:
                env_path = config.BASE_DIR / ".env"
                if env_path.exists():
                    env_content = env_path.read_text(encoding="utf-8")
                    import re
                    env_content = re.sub(r"FB_PAGE_ACCESS_TOKEN=.*", f"FB_PAGE_ACCESS_TOKEN={token}", env_content)
                    env_path.write_text(env_content, encoding="utf-8")
                    config.reload_config()
            except Exception as e_env:
                print(f"Warning: could not sync .env: {e_env}")

        return jsonify({"success": True})
    return jsonify({"success": False, "error": "บันทึกไม่สำเร็จ"}), 500

@app.route("/api/pages/delete", methods=["POST"])
def api_delete_page():
    """ลบเพจออกจากระบบ"""
    data = request.json or {}
    page_id = str(data.get("page_id", "")).strip()
    if not page_id:
        return jsonify({"success": False, "error": "Missing page_id"}), 400

    delete_page(page_id)
    add_log(f"🗑️ ลบเพจ ID: {page_id} ออกจากระบบแล้ว", "info")
    return jsonify({"success": True})

@app.route("/api/pages/test", methods=["POST"])
def api_test_page():
    """ทดสอบเชื่อมต่อ Meta Graph API ของเพจใดๆ"""
    data = request.json or {}
    page_id = str(data.get("page_id", "")).strip()
    token = str(data.get("access_token", "")).strip()

    if not page_id or not token:
        return jsonify({"success": False, "error": "กรุณาระบุ Page ID และ Access Token"}), 400

    import requests
    try:
        url = f"https://graph.facebook.com/v19.0/{page_id}?fields=name,id,category&access_token={token}"
        resp = requests.get(url, timeout=10)
        res_data = resp.json()
        if resp.status_code == 200 and "name" in res_data:
            return jsonify({
                "success": True,
                "name": res_data.get("name"),
                "id": res_data.get("id"),
                "category": res_data.get("category")
            })
        else:
            err = res_data.get("error", {}).get("message", "Invalid Token or Page ID")
            return jsonify({"success": False, "error": err}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# -------------------------------------------------------------
# API: FEEDS MANAGEMENT PER PAGE (จัดการ RSS ประจำเพจ)
# -------------------------------------------------------------
@app.route("/api/pages/<page_id>/feeds", methods=["GET"])
def api_get_page_feeds(page_id):
    """ดึงรายการ RSS Feeds ของเพจนี้"""
    feeds = get_feeds_by_page(page_id)
    return jsonify(feeds)

@app.route("/api/pages/<page_id>/feeds/add", methods=["POST"])
def api_add_page_feed(page_id):
    """เพิ่ม RSS Feed เข้าเพจนี้"""
    data = request.json or {}
    feed_name = str(data.get("feed_name", "")).strip()
    feed_url = str(data.get("feed_url", "")).strip()

    if not feed_name or not feed_url:
        return jsonify({"success": False, "error": "กรุณากรอกชื่อแหล่งข่าวและ URL Feed"}), 400

    success = add_feed_to_page(page_id, feed_name, feed_url)
    if success:
        add_log(f"📡 เพิ่ม RSS Feed ใหม่ให้เพจ {page_id}: [{feed_name}] {feed_url}", "success")
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Feed URL นี้มีอยู่แล้วในเพจนี้"}), 400

@app.route("/api/feeds/<int:feed_id>/toggle", methods=["POST"])
def api_toggle_feed(feed_id):
    """เปิด/ปิด การดึงข่าวจาก Feed"""
    data = request.json or {}
    is_enabled = 1 if data.get("is_enabled") else 0
    toggle_feed(feed_id, is_enabled)
    return jsonify({"success": True, "is_enabled": is_enabled})

@app.route("/api/feeds/<int:feed_id>/delete", methods=["POST"])
def api_delete_feed(feed_id):
    """ลบ Feed ออกจากเพจ"""
    delete_feed(feed_id)
    add_log(f"🗑️ ลบ Feed รหัส {feed_id} ออกแล้ว", "info")
    return jsonify({"success": True})

# -------------------------------------------------------------
# API: SCHEDULED POSTS (ระบบตั้งเวลาโพสต์)
# -------------------------------------------------------------
@app.route("/api/schedule", methods=["GET"])
def api_get_schedules():
    """ดึงรายการโพสต์ที่ตั้งเวลาไว้"""
    page_id = request.args.get("page_id")
    status = request.args.get("status")
    posts = get_scheduled_posts(page_id=page_id, status=status)
    return jsonify(posts)

@app.route("/api/schedule/create", methods=["POST"])
def api_create_schedule():
    """สร้างการตั้งเวลาโพสต์ใหม่"""
    data = request.json or {}
    page_id = str(data.get("page_id", "")).strip()
    caption = str(data.get("caption", "")).strip()
    scheduled_time = str(data.get("scheduled_time", "")).strip()
    title = str(data.get("title", "")).strip()
    article_url = str(data.get("article_url", "")).strip()
    image_url = str(data.get("image_url", "")).strip()

    if not page_id or not caption or not scheduled_time:
        return jsonify({"success": False, "error": "กรุณาระบุเพจ, แคปชัน และวันเวลาที่ต้องการโพสต์"}), 400

    # ดาวน์โหลดรูปลงเครื่องเก็บไว้ล่วงหน้า
    card_image_path = data.get("card_image_path")
    use_card = data.get("use_card", True)

    # แนบลิงก์ Affiliate ท้ายโพสต์อัตโนมัติหากเปิดตัวเลือกไว้
    enable_affiliate = data.get("enable_affiliate", False)
    aff_prod_id = data.get("affiliate_product_id")
    if enable_affiliate:
        caption = attach_affiliate_if_enabled(caption, True, aff_prod_id)

    local_img = None
    if use_card and card_image_path and os.path.exists(card_image_path):
        local_img = card_image_path
    elif image_url:
        local_img = download_image(image_url, filename_prefix=f"sched_{page_id}")

    post_id = create_scheduled_post(
        page_id=page_id,
        caption=caption,
        scheduled_time=scheduled_time,
        title=title,
        article_url=article_url,
        image_url=image_url,
        local_image_path=local_img or ""
    )

    page_info = get_page_by_id(page_id)
    pname = page_info["name"] if page_info else page_id
    add_log(f"📅 ตั้งเวลาโพสต์เรียบร้อย! เพจ: '{pname}' นัดหมายเวลา: {scheduled_time}", "success")
    return jsonify({"success": True, "schedule_id": post_id})

@app.route("/api/schedule/<int:post_id>/cancel", methods=["POST"])
def api_cancel_schedule(post_id):
    """ยกเลิกการตั้งเวลาโพสต์"""
    cancel_scheduled_post(post_id)
    add_log(f"⏹️ ยกเลิกรายการตั้งเวลา #{post_id} แล้ว", "info")
    return jsonify({"success": True})

@app.route("/api/schedule/<int:post_id>/delete", methods=["POST"])
def api_delete_schedule(post_id):
    """ลบรายการตั้งเวลาออกจากฐานข้อมูล"""
    delete_scheduled_post(post_id)
    return jsonify({"success": True})

# -------------------------------------------------------------
# API: NEWS & POSTING
# -------------------------------------------------------------
@app.route("/api/news")
def get_news():
    """ดึงรายการข่าวล่าสุด (สามารถกรองตาม page_id ได้)"""
    limit = request.args.get("limit", 30, type=int)
    page_id = request.args.get("page_id")
    articles = get_recent_articles(limit=limit, page_id=page_id)
    
    for art in articles:
        img = art.get("image_url")
        if img:
            matching = list((config.BASE_DIR / "downloads" / "images").glob(f"*{art.get('source', '')}*"))
            if matching:
                art["local_image"] = f"/images/{matching[0].name}"
            else:
                art["local_image"] = img
        else:
            art["local_image"] = None

    return jsonify(articles)

@app.route("/api/logs")
def get_logs():
    return jsonify(system_logs)

@app.route("/api/news/update", methods=["POST"])
def update_news_caption():
    """บันทึกการแก้ไขข้อความแคปชัน"""
    data = request.json or {}
    url = data.get("url")
    text = data.get("text")
    if not url or text is None:
        return jsonify({"success": False, "error": "Missing url or text"}), 400
    
    update_rewritten(url, text)
    add_log(f"💾 บันทึกการแก้ไขข้อความข่าว: {url[:35]}...", "info")
    return jsonify({"success": True})

@app.route("/api/news/regenerate", methods=["POST"])
def regenerate_single_news():
    """สั่งให้ AI เขียนข่าวนี้ใหม่ตามต้องการ"""
    data = request.json or {}
    url = data.get("url")
    if not url:
        return jsonify({"success": False, "error": "Missing URL"}), 400

    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM articles WHERE url = ?", (url,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"success": False, "error": "Article not found"}), 404
        art = dict(row)

    add_log(f"✨ สั่ง AI เขียนข่าวนี้ใหม่: {art.get('title', '')[:35]}...", "info")
    new_text = rewrite_article(art)
    if new_text:
        update_rewritten(url, new_text)
        add_log(f"🎉 AI เขียนข่าวใหม่สำเร็จเรียบร้อย!", "success")
        return jsonify({"success": True, "rewritten_text": new_text})
    else:
        return jsonify({"success": False, "error": "AI ไม่สามารถเขียนข่าวได้"}), 500

@app.route("/api/articles/<int:article_id>/generate_card", methods=["POST"])
def api_generate_card(article_id):
    """สร้างหรือปรับแต่งภาพกราฟิกข่าวกีฬา Social Card สำหรับบทความ"""
    data = request.json or {}
    headline = str(data.get("headline", "")).strip()
    category = str(data.get("category", "🔴 ข่าวลิเวอร์พูล")).strip()
    theme = str(data.get("theme", "lfc")).strip()
    subtitle = str(data.get("subtitle", "")).strip() or None

    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM articles WHERE id = ?", (article_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"success": False, "error": "ไม่พบบทความ"}), 404
        article = dict(row)

    if not headline:
        rw_text = article.get("rewritten_text") or ""
        first_line = rw_text.strip().split("\n")[0].replace("🔴", "").replace("⚡", "").replace("🔥", "").strip()
        if len(first_line) > 10 and len(first_line) < 120:
            headline = first_line
        else:
            headline = article.get("title", "ข่าวลิเวอร์พูลล่าสุด")

    page_name = "หงส์นิวส์"
    page_id = article.get("page_id")
    if page_id:
        pinfo = get_page_by_id(page_id)
        if pinfo:
            page_name = pinfo.get("name", "หงส์นิวส์")

    # หาภาพต้นฉบับ
    local_img = None
    img_url = article.get("image_url")
    if img_url:
        local_img = download_image(img_url, filename_prefix=f"art_{article_id}")

    try:
        cards_dir = config.BASE_DIR / "downloads" / "cards"
        cards_dir.mkdir(parents=True, exist_ok=True)
        out_filename = f"card_{article_id}_{int(time.time())}.jpg"
        out_path = str(cards_dir / out_filename)

        card_path = generate_social_card(
            image_path=local_img,
            headline=headline,
            category=category,
            page_name=page_name,
            subtitle=subtitle,
            output_path=out_path,
            theme=theme
        )

        update_card_image(article_id, card_path)

        add_log(f"🎨 สร้าง Social Card สำเร็จ: {headline[:35]}...", "success")
        return jsonify({
            "success": True,
            "card_image_path": card_path,
            "card_url": f"/cards/{out_filename}?t={int(time.time())}"
        })
    except Exception as e:
        add_log(f"❌ ไม่สามารถสร้าง Social Card ได้: {e}", "error")
        return jsonify({"success": False, "error": str(e)}), 500

# -------------------------------------------------------------
# API: MATCH CENTER (SCHEDULE, STANDINGS, PREVIEW & RATINGS)
# -------------------------------------------------------------
@app.route("/api/match_center/schedule")
def api_match_center_schedule():
    """ดึงตารางแข่งและผลการแข่งขันล่าสุดของลิเวอร์พูล"""
    data = get_liverpool_schedule()
    return jsonify(data)

@app.route("/api/match_center/standings")
def api_match_center_standings():
    """ดึงตารางคะแนนพรีเมียร์ลีกแบบเรียลไทม์"""
    standings = get_premier_league_standings()
    return jsonify(standings)

@app.route("/api/match_center/preview", methods=["POST"])
def api_generate_match_preview():
    """สร้างบทความพรีวิวแมตช์ด้วย AI"""
    data = request.json or {}
    opponent = data.get("opponent", "คู่แข่ง")
    competition = data.get("competition", "พรีเมียร์ลีก")
    venue = data.get("venue", "แอนฟิลด์ (เหย้า)")
    date_str = data.get("date_str", "สุดสัปดาห์นี้")
    focus_player = data.get("focus_player")
    extra_notes = data.get("extra_notes")

    add_log(f"⚽ สั่ง AI วิเคราะห์พรีวิวก่อนเกม: ลิเวอร์พูล พบ {opponent}...", "info")
    content = generate_ai_match_preview(
        opponent=opponent,
        competition=competition,
        venue=venue,
        date_str=date_str,
        focus_player=focus_player,
        extra_notes=extra_notes
    )
    if content:
        add_log(f"🎉 สร้างบทความพรีวิวคู่ {opponent} สำเร็จ!", "success")
        return jsonify({"success": True, "content": content})
    return jsonify({"success": False, "error": "AI ไม่สามารถสร้างพรีวิวได้"}), 500

@app.route("/api/match_center/ratings", methods=["POST"])
def api_generate_match_ratings():
    """สร้างบทความตัดเกรดคะแนนผู้เล่นหลังเกมด้วย AI"""
    data = request.json or {}
    opponent = data.get("opponent", "คู่แข่ง")
    score = data.get("score", "2-1")
    competition = data.get("competition", "พรีเมียร์ลีก")
    match_highlight = data.get("match_highlight")
    extra_notes = data.get("extra_notes")

    add_log(f"⭐ สั่ง AI ตัดเกรดคะแนนผู้เล่นหลังเกม: ลิเวอร์พูล {score} {opponent}...", "info")
    content = generate_ai_player_ratings(
        opponent=opponent,
        score=score,
        competition=competition,
        match_highlight=match_highlight,
        extra_notes=extra_notes
    )
    if content:
        add_log(f"🎉 ตัดเกรดคะแนนผู้เล่นคู่ {opponent} สำเร็จ!", "success")
        return jsonify({"success": True, "content": content})
    return jsonify({"success": False, "error": "AI ไม่สามารถตัดเกรดได้"}), 500

@app.route("/api/match_center/report", methods=["POST"])
def api_generate_match_report():
    """สร้างรายงานผลการแข่งขันฉบับเต็มหลังเกมด้วย AI"""
    data = request.json or {}
    opponent = data.get("opponent", "คู่แข่ง")
    score = data.get("score", "2-0")
    competition = data.get("competition", "พรีเมียร์ลีก")
    goals = data.get("goals")

    add_log(f"📝 สั่ง AI เขียนรายงานผลการแข่งขัน: ลิเวอร์พูล {score} {opponent}...", "info")
    content = generate_ai_postmatch_report(
        opponent=opponent,
        score=score,
        competition=competition,
        goals=goals
    )
    if content:
        add_log(f"🎉 สร้างรายงานผลคู่ {opponent} สำเร็จ!", "success")
        return jsonify({"success": True, "content": content})
    return jsonify({"success": False, "error": "AI ไม่สามารถสร้างรายงานผลได้"}), 500

@app.route("/api/news/post", methods=["POST"])
def post_single_news():
    """สั่งโพสต์ข่าวนี้ขึ้น Facebook ทันที (ระบุ target page_id ได้)"""
    data = request.json or {}
    url = data.get("url")
    text = data.get("text")
    image_url = data.get("image_url")
    target_page_id = data.get("page_id")
    card_image_path = data.get("card_image_path")
    use_card = data.get("use_card", True)

    if not url or not text:
        return jsonify({"success": False, "error": "ข้อมูลไม่ครบถ้วน"}), 400

    target_token = None
    target_name = "เพจหลัก"
    if target_page_id:
        p_info = get_page_by_id(target_page_id)
        if p_info:
            target_token = p_info.get("access_token")
            target_name = p_info.get("name", target_page_id)

    add_log(f"🚀 กำลังส่งโพสต์ขึ้น Facebook เพจ '{target_name}': {url[:35]}...", "info")

    local_img = None
    if use_card and card_image_path and os.path.exists(card_image_path):
        local_img = card_image_path
        add_log(f"🖼️ ใช้ภาพ Social Card คุณภาพสูงสำหรับโพสต์นี้", "info")
    elif image_url:
        local_img = download_image(image_url, filename_prefix="web_post")

    # แนบลิงก์ Affiliate ท้ายโพสต์อัตโนมัติหากเปิดตัวเลือกไว้
    enable_affiliate = data.get("enable_affiliate", False)
    aff_prod_id = data.get("affiliate_product_id")
    if enable_affiliate:
        text = attach_affiliate_if_enabled(text, True, aff_prod_id)

    res = post_to_facebook(
        message=text,
        image_path=local_img,
        image_url=image_url if not local_img else None,
        target_page_id=target_page_id,
        target_access_token=target_token
    )

# -------------------------------------------------------------
# API: SHORT VIDEO GENERATOR (TIKTOK / REELS / SHORTS)
# -------------------------------------------------------------
@app.route("/api/articles/<int:article_id>/generate_video", methods=["POST"])
def api_generate_video(article_id):
    """สร้างคลิปวิดีโอสั้น 9:16 สำหรับ TikTok, Reels และ Shorts พร้อมเสียงพากย์ Google AI Studio Gemini TTS"""
    data = request.json or {}
    headline = str(data.get("headline", "")).strip()
    speech_text = str(data.get("speech_text", "")).strip()
    voice = str(data.get("voice", "Charon")).strip()

    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM articles WHERE id = ?", (article_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"success": False, "error": "ไม่พบบทความ"}), 404
        article = dict(row)

    if not headline:
        headline = article.get("title", "ข่าวด่วนลิเวอร์พูล")

    if not speech_text:
        speech_text = article.get("rewritten_text") or article.get("summary") or headline

    page_name = "หงส์นิวส์"
    page_id = article.get("page_id")
    if page_id:
        p_info = get_page_by_id(page_id)
        if p_info:
            page_name = p_info.get("name", "หงส์นิวส์")

    # หาภาพที่คมชัดที่สุด (ใช้ Social Card ถ้ามี หรือภาพต้นฉบับ)
    img_path = None
    if article.get("card_image_path") and os.path.exists(article["card_image_path"]):
        img_path = article["card_image_path"]
    elif article.get("image_url"):
        img_path = download_image(article["image_url"], filename_prefix=f"vid_art_{article_id}")

    try:
        add_log(f"🎬 กำลังสร้างวิดีโอสั้นด้วยเสียงพากย์ Google AI Studio ({voice}): {headline[:30]}...", "info")
        out_filename = f"short_{article_id}_{int(time.time())}.mp4"
        out_path = str(config.BASE_DIR / "downloads" / "videos" / out_filename)

        vid_path = generate_short_video(
            image_path=img_path,
            headline=headline,
            speech_text=speech_text,
            page_name=page_name,
            output_path=out_path,
            voice_name=voice
        )

        add_log(f"🎉 สร้างคลิปวิดีโอสั้นสำเร็จ: {out_filename}", "success")
        return jsonify({
            "success": True,
            "video_url": f"/videos/{out_filename}?t={int(time.time())}",
            "filename": out_filename
        })
    except Exception as e:
        add_log(f"❌ สร้างวิดีโอสั้นล้มเหลว: {e}", "error")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/articles/<int:article_id>/post_reel", methods=["POST"])
def api_post_reel(article_id):
    """โพสต์วิดีโอสั้นที่สร้างขึ้นไปยัง Facebook Reels"""
    data = request.json or {}
    filename = data.get("filename")
    caption = str(data.get("caption", "")).strip()

    if not filename:
        return jsonify({"success": False, "error": "ไม่พบชื่อไฟล์วิดีโอ"}), 400

    videos_dir = config.BASE_DIR / "downloads" / "videos"
    video_path = str(videos_dir / filename)
    if not os.path.exists(video_path):
        return jsonify({"success": False, "error": "ไม่พบไฟล์วิดีโอนี้ในโฟลเดอร์"}), 404

    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM articles WHERE id = ?", (article_id,))
        row = cursor.fetchone()
        article = dict(row) if row else {}

    target_page_id = data.get("page_id") or article.get("page_id")
    target_token = None
    if target_page_id:
        p_info = get_page_by_id(target_page_id)
        if p_info:
            target_token = p_info.get("access_token")

    if not caption:
        caption = article.get("rewritten_text") or article.get("title") or "ข่าวด่วนลิเวอร์พูลล่าสุด #LFC #Liverpool #Reels"

    add_log(f"🚀 กำลังส่งคลิปขึ้น Facebook Reels ({filename})...", "info")
    res = post_reel_to_facebook(
        video_path=video_path,
        description=caption,
        target_page_id=target_page_id,
        target_access_token=target_token
    )

    if res.get("success"):
        mode = " [DRY RUN]" if res.get("mode") == "dry_run" else ""
        add_log(f"🎉 โพสต์ Facebook Reel สำเร็จเรียบร้อย!{mode} (Video ID: {res.get('video_id', 'N/A')})", "success")
        return jsonify({"success": True, "result": res})
    else:
        err = res.get("error", "ไม่สามารถโพสต์ได้")
        add_log(f"❌ โพสต์ Facebook Reel ล้มเหลว: {err}", "error")
        return jsonify({"success": False, "error": err}), 500

# -------------------------------------------------------------
# API: COMMUNITY MANAGER & COMMENTS
# -------------------------------------------------------------
@app.route("/api/community/generate_engagement", methods=["POST"])
def api_community_engagement():
    """สร้างโพสต์ชวนคุย โพลล์ หรือทายผลบอล"""
    data = request.json or {}
    p_type = data.get("type", "poll")
    topic = data.get("topic")

    add_log(f"💬 กำลังให้ AI คิดโพสต์ Engagement ({p_type})...", "info")
    content = generate_engagement_post(post_type=p_type, custom_topic=topic)
    if content:
        return jsonify({"success": True, "content": content})
    return jsonify({"success": False, "error": "AI ไม่สามารถสร้างโพสต์ได้"}), 500

@app.route("/api/community/comments", methods=["GET"])
def api_community_get_comments():
    """ดึงคอมเมนต์จาก Facebook โพสต์"""
    page_id = request.args.get("page_id")
    post_id = request.args.get("post_id")

    if not page_id or not post_id:
        return jsonify({"success": False, "error": "กรุณาระบุ page_id และ post_id"}), 400

    p_info = get_page_by_id(page_id)
    if not p_info:
        return jsonify({"success": False, "error": "ไม่พบเพจ"}), 404

    comments = fetch_facebook_post_comments(post_id, p_info["access_token"])
    return jsonify({"success": True, "comments": comments})

@app.route("/api/community/draft_reply", methods=["POST"])
def api_community_draft_reply():
    """ให้ AI ช่วยร่างคำตอบคอมเมนต์"""
    data = request.json or {}
    comment = data.get("comment", "")
    caption = data.get("caption", "")

    if not comment:
        return jsonify({"success": False, "error": "ไม่มีข้อความคอมเมนต์"}), 400

    reply = draft_ai_comment_reply(comment, caption)
    return jsonify({"success": True, "reply": reply})

@app.route("/api/community/send_reply", methods=["POST"])
def api_community_send_reply():
    """ส่งข้อความตอบกลับไปยัง Facebook"""
    data = request.json or {}
    comment_id = data.get("comment_id")
    reply_text = data.get("reply_text")
    page_id = data.get("page_id")

    if not comment_id or not reply_text or not page_id:
        return jsonify({"success": False, "error": "ข้อมูลไม่ครบถ้วน"}), 400

    p_info = get_page_by_id(page_id)
    if not p_info:
        return jsonify({"success": False, "error": "ไม่พบเพจ"}), 404

    res = reply_to_facebook_comment(comment_id, reply_text, p_info["access_token"])
    if res.get("success"):
        add_log(f"💬 ตอบกลับคอมเมนต์บนเพจ '{p_info['name']}' เรียบร้อยแล้ว!", "success")
        return jsonify({"success": True, "result": res})
    return jsonify({"success": False, "error": res.get("error")}), 500

# -------------------------------------------------------------
# API: AFFILIATE MANAGER
# -------------------------------------------------------------
@app.route("/api/affiliate/products", methods=["GET"])
def api_affiliate_get_products():
    """ดึงรายการสินค้า Affiliate"""
    return jsonify(load_affiliate_products())

@app.route("/api/affiliate/save", methods=["POST"])
def api_affiliate_save_products():
    """บันทึกรายการสินค้า Affiliate"""
    products = request.json or []
    success = save_affiliate_products(products)
    if success:
        add_log("🛒 บันทึกรายการสินค้าและลิงก์ Affiliate สำเร็จแล้ว!", "success")
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "ไม่สามารถบันทึกได้"}), 500

    if res.get("success"):
        mark_as_posted(url)
        add_log(f"🎉 โพสต์ขึ้นเพจ '{target_name}' เรียบร้อยแล้ว! (ID: {res.get('post_id', 'Dry-Run')})", "success")
        return jsonify({"success": True, "result": res})
    else:
        err = res.get("error", "Unknown error")
        add_log(f"❌ โพสต์ล้มเหลว: {err}", "error")
        return jsonify({"success": False, "error": err}), 500

@app.route("/api/fetch", methods=["POST"])
def manual_fetch():
    """ดึงข่าวและเขียนใหม่ทันที (เลือกระบุ page_id ได้)"""
    data = request.json or {}
    page_id = data.get("page_id")

    def worker():
        pname = "ทุกเพจ"
        if page_id:
            pinfo = get_page_by_id(page_id)
            if pinfo:
                pname = pinfo["name"]

        add_log(f"🔍 เริ่มต้นตรวจสอบข่าวฟีดสำหรับ: '{pname}'...", "info")
        try:
            # 1. จัดการข่าวที่ค้างเขียน
            with get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                if page_id:
                    cursor.execute("SELECT * FROM articles WHERE (rewritten_text IS NULL OR rewritten_text = '') AND page_id = ? LIMIT 5", (page_id,))
                else:
                    cursor.execute("SELECT * FROM articles WHERE (rewritten_text IS NULL OR rewritten_text = '') LIMIT 5")
                unwritten = [dict(r) for r in cursor.fetchall()]

            if unwritten:
                add_log(f"📝 พบข่าวที่ยังไม่ได้เรียบเรียง {len(unwritten)} ข่าว กำลังส่งให้ AI...", "info")
                for u_art in unwritten:
                    rw = rewrite_article(u_art)
                    if rw:
                        update_rewritten(u_art["url"], rw)
                        add_log(f"✅ เรียบเรียงข่าวสำเร็จ: {u_art['title'][:30]}...", "success")
                    time.sleep(2)

            # 2. ดึงข่าวใหม่จากฟีดของเพจ
            articles = fetch_all_new_articles(page_id=page_id)
            if not articles:
                add_log(f"☕ ไม่มีข่าวใหม่ในฟีดของ '{pname}' ขณะนี้", "info")
                return

            add_log(f"📦 พบข่าวใหม่ {len(articles)} ข่าว (กำลังประมวลผล 5 ข่าวล่าสุด)", "info")
            for art in articles[:5]:
                url = art["url"]
                title = art["title"]
                source = art["source"]
                img = art.get("image_url")
                summary = art.get("summary", "")
                pub = art.get("published_at", "")
                art_page = art.get("page_id") or page_id or ""

                save_article(url, title, source, img, summary, pub, page_id=art_page)
                add_log(f"📰 กำลังเรียบเรียงข่าว: [{source}] {title[:35]}...", "info")

                local_img = download_image(img, filename_prefix=f"{source}_{title[:20]}") if img else None

                rewritten = rewrite_article(art)
                if rewritten:
                    update_rewritten(url, rewritten)

                    # สร้างภาพ Social Card อัตโนมัติ
                    card_path = None
                    try:
                        p_name = "หงส์นิวส์"
                        if art_page:
                            p_info_card = get_page_by_id(art_page)
                            if p_info_card:
                                p_name = p_info_card.get("name", "หงส์นิวส์")

                        first_line = rewritten.strip().split("\n")[0].replace("🔴", "").replace("⚡", "").replace("🔥", "").strip()
                        card_hl = first_line if 10 < len(first_line) < 120 else title

                        cards_dir = config.BASE_DIR / "downloads" / "cards"
                        cards_dir.mkdir(parents=True, exist_ok=True)
                        out_card = str(cards_dir / f"card_{int(time.time()*1000)}.jpg")

                        card_path = generate_social_card(
                            image_path=local_img,
                            headline=card_hl,
                            category="🔴 ข่าวลิเวอร์พูล",
                            page_name=p_name,
                            output_path=out_card,
                            theme="lfc"
                        )
                        if card_path:
                            with get_connection() as c_conn:
                                c_conn.cursor().execute("UPDATE articles SET card_image_path = ? WHERE url = ?", (card_path, url))
                                c_conn.commit()
                            add_log(f"🎨 สร้าง Social Card ข่าว '{card_hl[:25]}...' สำเร็จ", "success")
                    except Exception as e_c:
                        print(f"Auto card generation error: {e_c}")

                    # โพสต์อัตโนมัติหากเปิดโหมด Live
                    if not config.DRY_RUN and art_page:
                        p_info = get_page_by_id(art_page)
                        if p_info:
                            post_img = card_path if (card_path and os.path.exists(card_path)) else local_img
                            res = post_to_facebook(
                                message=rewritten,
                                image_path=post_img,
                                image_url=img if not post_img else None,
                                target_page_id=art_page,
                                target_access_token=p_info["access_token"]
                            )
                            if res.get("success"):
                                mark_as_posted(url)
                                add_log(f"✅ โพสต์ขึ้นเพจ '{p_info['name']}' สำเร็จ: {title[:30]}...", "success")
                    else:
                        add_log(f"✅ เขียนข่าวเสร็จแล้ว (รอให้คุณตรวจดูในหน้าเว็บ)", "success")
                time.sleep(2)

        except Exception as e:
            add_log(f"❌ เกิดข้อผิดพลาดในการดึงข่าว: {e}", "error")

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"success": True, "message": "เริ่มดึงข่าวแล้ว"})

@app.route("/api/auto/toggle", methods=["POST"])
def toggle_auto():
    """เปิด/ปิดระบบรันวนลูปอัตโนมัติ"""
    global auto_bot_running, auto_thread, auto_bot_interval
    data = request.json or {}
    interval = data.get("interval")
    if interval:
        auto_bot_interval = int(interval)

    auto_bot_running = not auto_bot_running

    if auto_bot_running:
        add_log(f"⏱️ เริ่มต้น Auto-Bot ตรวจข่าวอัตโนมัติทุกๆ {auto_bot_interval} นาที", "info")
        def auto_worker():
            while auto_bot_running:
                add_log("🔄 [Auto-Bot] กำลังเริ่มรอบตรวจข่าวอัตโนมัติจากทุกเพจ...", "info")
                try:
                    pages = get_all_pages()
                    for p in pages:
                        if not auto_bot_running:
                            break
                        pid = p["page_id"]
                        token = p["access_token"]
                        articles = fetch_all_new_articles(page_id=pid)
                        for art in articles[:2]:
                            if not auto_bot_running:
                                break
                            if is_article_seen(art["url"]):
                                continue
                            
                            save_article(art["url"], art["title"], art["source"], art.get("image_url"), art.get("summary", ""), art.get("published_at", ""), page_id=pid)
                            local_img = download_image(art.get("image_url"), filename_prefix=f"auto_{pid}_{art['title'][:15]}") if art.get("image_url") else None
                            rewritten = rewrite_article(art)
                            if rewritten:
                                update_rewritten(art["url"], rewritten)
                                post_to_facebook(rewritten, local_img, art.get("image_url"), target_page_id=pid, target_access_token=token)
                                mark_as_posted(art["url"])
                                add_log(f"🎉 [Auto-Bot] โพสต์ข่าวใหม่ขึ้นเพจ '{p['name']}': {art['title'][:30]}...", "success")
                            time.sleep(3)
                except Exception as e:
                    add_log(f"⚠️ [Auto-Bot Error]: {e}", "error")

                for _ in range(auto_bot_interval * 60):
                    if not auto_bot_running:
                        break
                    time.sleep(1)

        auto_thread = threading.Thread(target=auto_worker, daemon=True)
        auto_thread.start()
    else:
        add_log("⏹️ หยุดระบบ Auto-Bot เรียบร้อยแล้ว", "info")

    return jsonify({"auto_running": auto_bot_running, "interval": auto_bot_interval})

# -------------------------------------------------------------
# BACKGROUND WORKER: ตรวจสอบคิวโพสต์ตามเวลาที่ตั้งไว้ (Scheduler)
# -------------------------------------------------------------
def start_scheduler_worker():
    """รันเธรดเบื้องหลัง คอยตรวจเช็คโพสต์ที่ถึงเวลาทุกๆ 20 วินาที"""
    def scheduler_loop():
        while True:
            try:
                due_posts = get_due_scheduled_posts()
                if due_posts:
                    for post in due_posts:
                        post_id = post["id"]
                        page_id = post["page_id"]
                        page_name = post.get("page_name") or page_id
                        caption = post["caption"]
                        img_path = post.get("local_image_path")
                        img_url = post.get("image_url")
                        token = post.get("access_token")

                        add_log(f"⏰ [Schedule] ถึงเวลาโพสต์ตามนัดหมาย: '{post.get('title', '')[:30]}' (เพจ: {page_name})", "info")

                        res = post_to_facebook(
                            message=caption,
                            image_path=img_path,
                            image_url=img_url,
                            target_page_id=page_id,
                            target_access_token=token
                        )

                        if res.get("success"):
                            fb_id = res.get("post_id", "Dry-Run")
                            update_scheduled_post_status(post_id, "posted", post_fb_id=fb_id)
                            if post.get("article_url"):
                                mark_as_posted(post["article_url"])
                            add_log(f"🎉 [Schedule] ยิงโพสต์ตามเวลานัดหมายสำเร็จ! (Post ID: {fb_id})", "success")
                        else:
                            err = res.get("error", "Unknown error")
                            update_scheduled_post_status(post_id, "failed", error_message=err)
                            add_log(f"❌ [Schedule] โพสต์ตามเวลานัดหมายล้มเหลว: {err}", "error")

            except Exception as e:
                print(f"[Scheduler Worker Error]: {e}")

            time.sleep(20)

    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()

# -------------------------------------------------------------
# START SERVER
# -------------------------------------------------------------
def start_app():
    start_scheduler_worker()
    add_log("🚀 เริ่มต้นระบบ Multi-Page Auto News & Scheduler Web App ที่ http://localhost:5000", "info")
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:5000")).start()
    app.run(host="0.0.0.0", port=5000, debug=False)

if __name__ == "__main__":
    start_app()
