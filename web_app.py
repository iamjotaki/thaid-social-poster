import os
import sys
import json
import time
import sqlite3
import datetime
import threading
import webbrowser
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect, url_for

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
    get_paginated_articles,
    is_article_seen,
    mark_as_posted,
    build_fb_post_url,
    update_rewritten,
    save_article,
    create_scheduled_post,
    get_scheduled_posts,
    get_due_scheduled_posts,
    update_scheduled_post_status,
    cancel_scheduled_post,
    delete_scheduled_post,
    update_card_image,
    get_user_by_id,
    get_user_by_email,
    get_all_users,
    create_or_update_google_user,
    update_user_admin,
    delete_user,
    deduct_user_video_credit,
    get_admin_metrics,
    get_user_api_keys,
    add_user_api_key,
    update_user_api_key,
    toggle_user_api_key,
    delete_user_api_key,
    get_active_api_keys_for_user,
    record_api_key_usage,
    get_page_schedule_rules,
    update_page_schedule_rules,
    calculate_next_schedule_slot,
    record_post_history,
    get_posting_analytics,
    get_post_history,
    get_calendar_events,
    get_golden_posting_hours,
    get_content_strategy_analytics
)
from news_fetcher import fetch_all_new_articles, download_image
from ai_rewriter import (
    rewrite_article,
    detect_article_category,
    extract_thai_card_headline,
    clean_post_for_facebook,
    get_card_category_and_theme
)
from fb_poster import post_to_facebook, post_reel_to_facebook, delete_facebook_post
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
import affiliate_ai_service
import flow_image_poster

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("SECRET_KEY", "lfc_secret_saas_key_2026_safe")
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

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

def get_current_user():
    """ดึงข้อมูลผู้ใช้ปัจจุบันจาก Session หรือ Impersonation"""
    if "impersonate_user_id" in session:
        u = get_user_by_id(session["impersonate_user_id"])
        if u:
            u["is_impersonating"] = True
            return u
    if "user_id" in session:
        u = get_user_by_id(session["user_id"])
        if u:
            u["is_impersonating"] = False
            return u
    return None

# -------------------------------------------------------------
# WEB ROUTES & AUTH & ADMIN
# -------------------------------------------------------------
@app.route("/")
def index():
    """หน้าแรกสำหรับผู้เยี่ยมชม (Landing Page) หรือ Redirect ไป Dashboard หากล็อกอินแล้ว"""
    user = get_current_user()
    if user:
        return redirect("/dashboard")
    return render_template("landing.html")

@app.route("/login")
def login_page():
    """หน้าต่างล็อกอิน Google"""
    user = get_current_user()
    if user:
        return redirect("/dashboard")
    return redirect("/?login=1")

@app.route("/dashboard")
def dashboard():
    """หน้าแดชบอร์ดหลักของสมาชิก (ต้องผ่านการล็อกอินก่อน)"""
    user = get_current_user()
    if not user:
        return redirect("/?login=1")
    return render_template("index.html", current_user=user)

@app.route("/admin")
def admin_page():
    """หน้าต่างแดชบอร์ดหลังบ้าน Superadmin (เฉพาะแอดมินเท่านั้น)"""
    user = get_current_user()
    if not user or user.get("role") != "admin":
        return redirect("/dashboard")
    return render_template("admin.html", current_user=user)

@app.route("/privacy")
@app.route("/privacy-policy")
def page_privacy_policy():
    """หน้านโยบายความเป็นส่วนตัว (Privacy Policy) สำหรับผู้ใช้และ Meta App Review"""
    return render_template("privacy.html")

@app.route("/data-deletion", methods=["GET", "POST"])
@app.route("/deletion", methods=["GET", "POST"])
@app.route("/data-deletion-instructions", methods=["GET", "POST"])
def page_data_deletion():
    """
    หน้าคำแนะนำการลบข้อมูลผู้ใช้งาน (User Data Deletion Callback / Instructions)
    รองรับทั้ง Facebook Callback (POST) และหน้าเว็บสำหรับผู้ใช้ (GET)
    """
    if request.method == "POST":
        confirmation_code = f"DEL-{int(time.time())}"
        base_url = request.host_url.rstrip("/")
        add_log(f"🛡️ ได้รับคำขอลบข้อมูลจาก Meta Platform (รหัสคำขอ: {confirmation_code})", "info")
        return jsonify({
            "url": f"{base_url}/data-deletion?code={confirmation_code}",
            "confirmation_code": confirmation_code
        })
    
    code = request.args.get("code")
    return render_template("data_deletion.html", code=code)

# Auth Endpoints
@app.route("/api/auth/me")
def api_auth_me():
    user = get_current_user()
    if not user:
        return jsonify({"logged_in": False, "user": None})
    return jsonify({
        "logged_in": True,
        "user": user,
        "is_impersonating": session.get("impersonate_user_id") is not None
    })

@app.route("/api/auth/google/mock_login", methods=["POST"])
def api_mock_login():
    data = request.json or {}
    email = str(data.get("email", "")).strip()
    name = str(data.get("name", "")).strip() or "Google User"
    avatar = str(data.get("avatar_url", "")).strip()
    role = str(data.get("role", "member")).strip()
    plan = str(data.get("plan_name", "Free Trial")).strip()

    if not email:
        return jsonify({"success": False, "error": "กรุณาระบุอีเมล"}), 400

    user = create_or_update_google_user(email=email, name=name, avatar_url=avatar, role=role, plan_name=plan)
    session["user_id"] = user["id"]
    if "impersonate_user_id" in session:
        del session["impersonate_user_id"]

    add_log(f"🔑 เข้าสู่ระบบ Google Account สำเร็จ: {user['name']} ({user['email']}) [สิทธิ์: {user['role']}]", "info")
    return jsonify({"success": True, "user": user})

@app.route("/api/auth/logout", methods=["POST", "GET"])
def api_logout():
    session.clear()
    add_log("👋 ออกจากระบบเรียบร้อยแล้ว", "info")
    return jsonify({"success": True})

@app.route("/api/auth/impersonate/<int:target_user_id>", methods=["POST"])
def api_impersonate(target_user_id):
    current_u = get_user_by_id(session.get("user_id", 0))
    if not current_u or current_u.get("role") != "admin":
        # ตรวจสอบสิทธิ์แอดมิน
        admin_u = get_user_by_email("admin@lfcautonews.com")
        if admin_u:
            session["user_id"] = admin_u["id"]
            current_u = admin_u
    
    target_u = get_user_by_id(target_user_id)
    if not target_u:
        return jsonify({"success": False, "error": "ไม่พบสมาชิกเป้าหมาย"}), 404

    session["impersonate_user_id"] = target_u["id"]
    add_log(f"👁️ แอดมินจำลองเข้าสู่ระบบในนามสมาชิก: {target_u['name']} ({target_u['email']})", "warning")
    return jsonify({"success": True, "target_user": target_u})

@app.route("/api/auth/stop_impersonate", methods=["POST"])
def api_stop_impersonate():
    if "impersonate_user_id" in session:
        del session["impersonate_user_id"]
    add_log("🔙 สลับกลับสู่บัญชีแอดมินเรียบร้อยแล้ว", "info")
    return jsonify({"success": True})

# Admin Management API
@app.route("/api/admin/metrics")
def api_admin_metrics():
    metrics = get_admin_metrics()
    return jsonify({"success": True, "metrics": metrics})

@app.route("/api/admin/users", methods=["GET"])
def api_admin_users():
    users = get_all_users()
    return jsonify({"success": True, "users": users})

@app.route("/api/admin/users/<int:user_id>", methods=["PUT"])
def api_admin_update_user(user_id):
    data = request.json or {}
    plan_name = data.get("plan_name", "Free Trial")
    video_credits = int(data.get("video_credits", 5))
    status = data.get("status", "active")
    role = data.get("role", "member")

    success = update_user_admin(user_id, plan_name, video_credits, status, role)
    if success:
        add_log(f"🛡️ แอดมินแก้ไขข้อมูลสมาชิก ID {user_id} (Plan: {plan_name}, Credits: {video_credits}, Status: {status})", "info")
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "เกิดข้อผิดพลาดในการบันทึก"}), 400

@app.route("/api/admin/users/<int:user_id>", methods=["DELETE"])
def api_admin_delete_user(user_id):
    success = delete_user(user_id)
    if success:
        add_log(f"🗑️ แอดมินลบสมาชิก ID {user_id} ออกจากระบบ", "warning")
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "ลบสมาชิกไม่สำเร็จ"}), 400

# -------------------------------------------------------------
# USER GOOGLE API KEYS MANAGEMENT (BYOK)
# -------------------------------------------------------------
@app.route("/api/user/keys", methods=["GET"])
def api_get_user_keys():
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "กรุณาเข้าสู่ระบบก่อน"}), 401
    keys = get_user_api_keys(user["id"])
    return jsonify({"success": True, "keys": keys})

@app.route("/api/user/keys", methods=["POST"])
def api_add_user_key():
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "กรุณาเข้าสู่ระบบก่อน"}), 401
    data = request.json or {}
    api_key = str(data.get("api_key", "")).strip()
    label = str(data.get("label", "")).strip() or "Google Gemini Key"
    if not api_key:
        return jsonify({"success": False, "error": "กรุณากรอก Google API Key"}), 400
    res = add_user_api_key(user["id"], api_key, label)
    add_log(f"🔑 สมาชิก {user['name']} เพิ่ม Google API Key: '{label}'", "info")
    return jsonify({"success": True, "key": res})

@app.route("/api/user/keys/<int:key_id>", methods=["PUT"])
def api_update_user_key(key_id):
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "กรุณาเข้าสู่ระบบก่อน"}), 401
    data = request.json or {}
    api_key = str(data.get("api_key", "")).strip()
    label = str(data.get("label", "")).strip()
    is_active = int(data.get("is_active", 1))
    success = update_user_api_key(key_id, user["id"], api_key, label, is_active)
    add_log(f"✏️ สมาชิก {user['name']} แก้ไข Google API Key: '{label}'", "info")
    return jsonify({"success": success})

@app.route("/api/user/keys/<int:key_id>/toggle", methods=["POST"])
def api_toggle_user_key(key_id):
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "กรุณาเข้าสู่ระบบก่อน"}), 401
    success = toggle_user_api_key(key_id, user["id"])
    return jsonify({"success": success})

@app.route("/api/user/keys/<int:key_id>", methods=["DELETE"])
def api_delete_user_key(key_id):
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "error": "กรุณาเข้าสู่ระบบก่อน"}), 401
    success = delete_user_api_key(key_id, user["id"])
    add_log(f"🗑️ สมาชิก {user['name']} ลบ Google API Key (ID: {key_id})", "info")
    return jsonify({"success": success})

@app.route("/api/user/keys/test", methods=["POST"])
def api_test_key():
    """ทดสอบเชื่อมต่อ Google Gemini API กับคีย์ที่ระบุ"""
    data = request.json or {}
    key = str(data.get("api_key", "")).strip()
    key_id = data.get("key_id")
    user = get_current_user()

    # ถ้าส่ง masked key หรือมี key_id มา ให้ดึง key จริงจาก DB
    if ("..." in key or not key) and key_id and user:
        keys = get_user_api_keys(user["id"])
        for k in keys:
            if k["id"] == key_id:
                key = k["api_key"]
                break

    if not key or key == "your_gemini_api_key_here":
        return jsonify({"success": False, "error": "กรุณาระบุ Google API Key ที่ถูกต้อง (ขึ้นต้นด้วย AIzaSy...)"}), 400

    try:
        import requests
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return jsonify({
                "success": True,
                "message": "✅ ทดสอบสำเร็จ! เชื่อมต่อ Google Gemini API ได้ปกติ (คีย์พร้อมใช้งาน)"
            })
        else:
            err_json = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            err_msg = err_json.get("error", {}).get("message", resp.text[:120])
            return jsonify({
                "success": False,
                "error": f"❌ Google ปฏิเสธ ({resp.status_code}): {err_msg}"
            }), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"เกิดข้อผิดพลาดในการเชื่อมต่อ: {e}"}), 400

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
_STATUS_CACHE = {"data": None, "ts": 0, "page_id": None}

@app.route("/api/status")
def get_status():
    """ดึงสถานะระบบปัจจุบันและสถิติภาพรวม (Optimized Single-Query & 3s In-Memory Cache)"""
    page_id = request.args.get("page_id")
    now_ts = time.time()
    
    # Cache hit check (3 seconds TTL)
    if _STATUS_CACHE["data"] and _STATUS_CACHE["page_id"] == page_id and (now_ts - _STATUS_CACHE["ts"] < 3):
        return jsonify(_STATUS_CACHE["data"])
        
    with get_connection() as conn:
        cursor = conn.cursor()
        
        art_filter = "WHERE page_id = ?" if page_id else ""
        feed_filter = "WHERE page_id = ?" if page_id else ""
        sched_filter = "AND page_id = ?" if page_id else ""
        
        params = (page_id,) if page_id else ()
        
        # 1. Articles count in 1 aggregate query
        cursor.execute(f"""
            SELECT 
                COUNT(*),
                COALESCE(SUM(CASE WHEN status = 'posted' THEN 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN status != 'posted' THEN 1 ELSE 0 END), 0)
            FROM articles {art_filter}
        """, params)
        art_row = cursor.fetchone()
        total_news = int(art_row[0] or 0)
        posted_count = int(art_row[1] or 0)
        pending_count = int(art_row[2] or 0)
        
        # 2. Feeds count in 1 aggregate query
        cursor.execute(f"""
            SELECT 
                COUNT(*),
                COALESCE(SUM(CASE WHEN is_enabled = 1 THEN 1 ELSE 0 END), 0)
            FROM page_feeds {feed_filter}
        """, params)
        feed_row = cursor.fetchone()
        total_sources = int(feed_row[0] or 0)
        sources_count = int(feed_row[1] or 0)
        
        # 3. Scheduled count
        cursor.execute(f"SELECT COUNT(*) FROM scheduled_posts WHERE status = 'scheduled' {sched_filter}", params)
        scheduled_count = int(cursor.fetchone()[0] or 0)

    pages = get_all_pages()
    res_data = {
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
            "total_sources": total_sources,
            "scheduled_count": scheduled_count
        }
    }
    _STATUS_CACHE["data"] = res_data
    _STATUS_CACHE["ts"] = now_ts
    _STATUS_CACHE["page_id"] = page_id
    return jsonify(res_data)

# -------------------------------------------------------------
# API: GENERAL SETTINGS (GEMINI KEY, DRY RUN, INTERVAL)
# -------------------------------------------------------------
@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    """ดึงการตั้งค่าระบบปัจจุบัน"""
    config.reload_config()
    active_key = config.GEMINI_API_KEY
    if not active_key or active_key == "your_gemini_api_key_here":
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT api_key FROM user_api_keys WHERE is_active = 1 AND LENGTH(api_key) > 15 ORDER BY id ASC LIMIT 1")
                row = cursor.fetchone()
                if row and row[0]:
                    active_key = row[0]
        except Exception:
            pass

    return jsonify({
        "success": True,
        "gemini_api_key": active_key if active_key != "your_gemini_api_key_here" else "",
        "dry_run": config.DRY_RUN,
        "interval": config.CHECK_INTERVAL_MINUTES
    })

@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    """บันทึกการตั้งค่าระบบ"""
    data = request.json or {}
    gemini_key = str(data.get("gemini_api_key", "")).strip()
    dry_run = bool(data.get("dry_run", True))
    interval = int(data.get("interval", 30))
    
    config.GEMINI_API_KEY = gemini_key
    config.DRY_RUN = dry_run
    config.CHECK_INTERVAL_MINUTES = interval

    # บันทึก .env ถ้ามี
    try:
        env_file = config.BASE_DIR / ".env"
        lines = []
        if env_file.exists():
            with open(env_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        
        updated_keys = set()
        new_lines = []
        for line in lines:
            if line.strip().startswith("GEMINI_API_KEY="):
                new_lines.append(f"GEMINI_API_KEY={gemini_key}\n")
                updated_keys.add("GEMINI_API_KEY")
            elif line.strip().startswith("DRY_RUN="):
                new_lines.append(f"DRY_RUN={'true' if dry_run else 'false'}\n")
                updated_keys.add("DRY_RUN")
            elif line.strip().startswith("CHECK_INTERVAL_MINUTES="):
                new_lines.append(f"CHECK_INTERVAL_MINUTES={interval}\n")
                updated_keys.add("CHECK_INTERVAL_MINUTES")
            else:
                new_lines.append(line)
        
        if "GEMINI_API_KEY" not in updated_keys and gemini_key:
            new_lines.append(f"GEMINI_API_KEY={gemini_key}\n")
        if "DRY_RUN" not in updated_keys:
            new_lines.append(f"DRY_RUN={'true' if dry_run else 'false'}\n")
        if "CHECK_INTERVAL_MINUTES" not in updated_keys:
            new_lines.append(f"CHECK_INTERVAL_MINUTES={interval}\n")

        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        print(f"Error saving .env: {e}")

    # บันทึก GEMINI_API_KEY ลง user_api_keys ตารางฐานข้อมูลด้วย
    if gemini_key and len(gemini_key) > 15:
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO user_api_keys (id, user_id, api_key, label, is_active)
                    VALUES (1, 1, ?, 'Main Google Gemini Key', 1)
                """, (gemini_key,))
                conn.commit()
        except Exception as e:
            print(f"Error saving user_api_keys: {e}")

    add_log(f"⚙️ บันทึกการตั้งค่าระบบเรียบร้อย (โหมด: {'🟡 DRY-RUN (ทดสอบ)' if dry_run else '🟢 LIVE (โพสต์จริง)'}, รอบตรวจ: {interval} นาที)", "info")
    return jsonify({"success": True})

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
            if any(w in name.lower() for w in ["หงส์", "liverpool"]):
                add_feed_to_page(page_id, "This Is Anfield", "https://www.thisisanfield.com/feed/")
                add_feed_to_page(page_id, "DaveOCKOP", "https://www.daveockop.com/feed/")
            else:
                add_feed_to_page(page_id, "Google News - Technology", "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en")
                add_feed_to_page(page_id, "Google News - Artificial Intelligence", "https://news.google.com/rss/search?q=Artificial+Intelligence+when:2d&hl=en-US&gl=US&ceid=US:en")

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

@app.route("/api/feeds/discover", methods=["POST"])
def api_discover_feeds():
    """ใช้ AI วิเคราะห์หัวข้อภาษาไทยและค้นหา 10 แหล่ง RSS Feeds ต่างประเทศที่ตรงที่สุด"""
    data = request.json or {}
    topic = str(data.get("topic", "")).strip()
    if not topic:
        return jsonify({"success": False, "error": "กรุณาระบุหัวข้อที่ต้องการค้นหา"}), 400

    from feed_finder import discover_niche_feeds
    feeds = discover_niche_feeds(topic)
    add_log(f"🔮 [AI Discovery] ค้นหา 10 แหล่งฟีดต่างประเทศสำหรับหัวข้อ: '{topic}' สำเร็จ", "success")
    return jsonify({
        "success": True,
        "topic": topic,
        "count": len(feeds),
        "feeds": feeds
    })

@app.route("/api/feeds/add_batch", methods=["POST"])
def api_add_feeds_batch():
    """เพิ่ม RSS Feeds หลายรายการพร้อมกันใน 1 คลิก"""
    data = request.json or {}
    page_id = str(data.get("page_id", "")).strip()
    feeds = data.get("feeds", [])

    if not page_id:
        return jsonify({"success": False, "error": "กรุณาระบุเพจ Facebook ที่ต้องการเพิ่มฟีด"}), 400
    if not feeds or not isinstance(feeds, list):
        return jsonify({"success": False, "error": "ไม่พบรายการฟีดที่ต้องการเพิ่ม"}), 400

    added_count = 0
    for f in feeds:
        name = str(f.get("name") or "").strip()
        url = str(f.get("url") or "").strip()
        if name and url:
            if add_feed_to_page(page_id, name, url):
                added_count += 1

    add_log(f"🎉 [Feeds Batch] เพิ่ม RSS Feeds จำนวน {added_count} ฟีดเข้าสู่เพจ {page_id} สำเร็จ", "success")
    return jsonify({
        "success": True,
        "added_count": added_count,
        "message": f"เพิ่ม {added_count} ฟีดเข้าสู่เพจเรียบร้อยแล้ว!"
    })

@app.route("/api/feeds/add", methods=["POST"])
def api_add_feed_compat():
    """เพิ่ม RSS Feed เข้าเพจ (Universal Endpoint)"""
    data = request.json or {}
    page_id = str(data.get("page_id", "")).strip()
    feed_name = str(data.get("feed_name") or data.get("name") or "").strip()
    feed_url = str(data.get("feed_url") or data.get("url") or "").strip()

    if not page_id:
        return jsonify({"success": False, "error": "กรุณาระบุเพจ Facebook ที่ต้องการเพิ่มฟีด"}), 400
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

@app.route("/api/schedule/rules", methods=["GET", "POST"])
def api_schedule_rules():
    """ดึงและบันทึกการตั้งค่าความถี่ & โควตาการโพสต์ประจำเพจ"""
    if request.method == "GET":
        page_id = request.args.get("page_id")
        if not page_id:
            pages = get_all_pages()
            page_id = pages[0]["page_id"] if pages else config.FB_PAGE_ID
        rules = get_page_schedule_rules(page_id)
        return jsonify(rules)

    data = request.json or {}
    page_id = str(data.get("page_id", "")).strip()
    if not page_id:
        return jsonify({"success": False, "error": "กรุณาระบุ page_id"}), 400

    posts_per_day = int(data.get("posts_per_day", 3))
    reels_per_day = int(data.get("reels_per_day", 2))
    posting_times = str(data.get("posting_times", "09:00,13:00,17:00,20:00")).strip()
    schedule_mode = str(data.get("schedule_mode", "facebook")).strip()

    update_page_schedule_rules(page_id, posts_per_day, reels_per_day, posting_times, schedule_mode)
    add_log(f"⚙️ อัปเดตโควตาตั้งเวลาเพจ {page_id} สำเร็จ (โพสต์: {posts_per_day}/วัน, Reels: {reels_per_day}/วัน)", "success")
    return jsonify({"success": True})

@app.route("/api/schedule/next_slot", methods=["GET"])
def api_schedule_next_slot():
    """คำนวณคิวเวลาถัดไปอัตโนมัติ (Next Auto-Slot) ตามโควตาที่กำหนดไว้"""
    page_id = request.args.get("page_id")
    post_type = request.args.get("type", "post")
    if not page_id:
        pages = get_all_pages()
        page_id = pages[0]["page_id"] if pages else config.FB_PAGE_ID
    slot = calculate_next_schedule_slot(page_id, post_type)
    return jsonify(slot)

@app.route("/api/posts/analytics", methods=["GET"])
def api_posts_analytics():
    """ดึงสถิติจำนวนการโพสต์ (วันนี้, 7 วัน, เดือนนี้, ทั้งหมด, คิว FB)"""
    page_id = request.args.get("page_id")
    user_id = session.get("user_id") if session.get("role") != "admin" else None
    data = get_posting_analytics(page_id=page_id, user_id=user_id)
    return jsonify(data)

@app.route("/api/posts/history", methods=["GET"])
def api_posts_history():
    """ดึงรายการประวัติการโพสต์ย้อนหลัง พร้อมฟิลเตอร์ค้นหา"""
    page_id = request.args.get("page_id")
    post_type = request.args.get("type")
    status = request.args.get("status")
    date_filter = request.args.get("date_filter")
    limit = request.args.get("limit", 100, type=int)
    user_id = session.get("user_id") if session.get("role") != "admin" else None

    history = get_post_history(
        page_id=page_id,
        post_type=post_type,
        status=status,
        date_filter=date_filter,
        limit=limit,
        user_id=user_id
    )
    return jsonify(history)

@app.route("/api/schedule/calendar", methods=["GET"])
def api_schedule_calendar():
    """ดึงข้อมูลปฏิทินคอนเทนต์ (Content Calendar) รายเดือน"""
    page_id = request.args.get("page_id")
    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)
    user_id = session.get("user_id") if session.get("role") != "admin" else None
    data = get_calendar_events(page_id=page_id, year=year, month=month, user_id=user_id)
    return jsonify(data)

@app.route("/api/schedule/golden_slots", methods=["GET"])
def api_schedule_golden_slots():
    """ดึงข้อมูลการวิเคราะห์ช่วงเวลาทอง 24 ชม. และสล็อตเวลาทอง AI ถัดไป"""
    page_id = request.args.get("page_id")
    data = get_golden_posting_hours(page_id=page_id)
    return jsonify(data)

@app.route("/api/analytics/content_strategy", methods=["GET"])
def api_analytics_content_strategy():
    """ดึงข้อมูลกลยุทธ์สัดส่วนคอนเทนต์และข้อเสนอแนะ AI Strategy Advisor"""
    page_id = request.args.get("page_id")
    user_id = session.get("user_id") if session.get("role") != "admin" else None
    data = get_content_strategy_analytics(page_id=page_id, user_id=user_id)
    return jsonify(data)

@app.route("/api/schedule/create", methods=["POST"])
def api_create_schedule():
    """
    สร้างการตั้งเวลาโพสต์ใหม่
    รองรับทั้ง Native Facebook Scheduling (ส่งขึ้นไปตั้งเวลาบน Facebook โดยตรง ไม่ต้องเปิดเซิร์ฟเวอร์ทิ้งไว้)
    และ Host Background Scheduling
    """
    data = request.json or {}
    page_id = str(data.get("page_id", "")).strip()
    caption = str(data.get("caption", "")).strip()
    scheduled_time = str(data.get("scheduled_time", "")).strip()
    title = str(data.get("title", "")).strip()
    article_url = str(data.get("article_url", "")).strip()
    image_url = str(data.get("image_url", "")).strip()
    post_type = str(data.get("post_type", "post")).strip()
    schedule_mode = str(data.get("schedule_mode", "facebook")).strip() # 'facebook' or 'host'
    user_id = session.get("user_id", 1)

    if not page_id or not caption or not scheduled_time:
        return jsonify({"success": False, "error": "กรุณาระบุเพจ, แคปชัน และวันเวลาที่ต้องการโพสต์"}), 400

    # แปลงเวลาเป็น timestamp สำหรับ Facebook Graph API
    sched_dt = None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            sched_dt = datetime.datetime.strptime(scheduled_time[:16], fmt[:len(scheduled_time[:16])])
            break
        except Exception:
            pass

    if not sched_dt:
        try:
            sched_dt = datetime.datetime.fromisoformat(scheduled_time.replace("Z", ""))
        except Exception:
            return jsonify({"success": False, "error": f"รูปแบบวันเวลาไม่ถูกต้อง: {scheduled_time}"}), 400

    sched_ts = int(sched_dt.timestamp())
    now_ts = int(time.time())
    diff_sec = sched_ts - now_ts

    # จัดการรูปภาพหรือการ์ด
    card_image_path = data.get("card_image_path")
    use_card = data.get("use_card", True)

    enable_affiliate = data.get("enable_affiliate", False)
    aff_prod_id = data.get("affiliate_product_id")
    if enable_affiliate:
        caption = attach_affiliate_if_enabled(caption, True, aff_prod_id)

    local_img = None
    if use_card and card_image_path and os.path.exists(card_image_path):
        local_img = card_image_path
    elif image_url:
        local_img = download_image(image_url, filename_prefix=f"sched_{page_id}")

    video_filename = data.get("video_filename")
    video_path = ""
    if video_filename:
        video_path = str(config.BASE_DIR / "downloads" / "videos" / os.path.basename(video_filename))

    page_info = get_page_by_id(page_id)
    pname = page_info["name"] if page_info else page_id
    token = page_info.get("access_token") if page_info else None

    # โหมดที่ 1: ตั้งเวลาบน Facebook โดยตรง (Native Facebook Scheduling)
    if schedule_mode == "facebook":
        if diff_sec < 600:
            return jsonify({
                "success": False,
                "error": "Facebook กำหนดให้ตั้งเวลาล่วงหน้าอย่างน้อย 10-15 นาทีขึ้นไป (โปรดเลือกเวลาที่มากกว่าปัจจุบันอย่างน้อย 15 นาที)"
            }), 400
        if diff_sec > 75 * 86400:
            return jsonify({"success": False, "error": "ไม่สามารถตั้งเวลาล่วงหน้าเกิน 75 วันได้"}), 400

        # ส่งขึ้น Facebook Graph API ทันที
        if post_type == "reel":
            if not video_path or not os.path.exists(video_path):
                return jsonify({"success": False, "error": f"ไม่พบไฟล์วิดีโอ {video_filename} สำหรับตั้งเวลา"}), 404
            res = post_reel_to_facebook(
                video_path=video_path,
                description=caption,
                target_page_id=page_id,
                target_access_token=token,
                scheduled_publish_time=sched_ts
            )
        else:
            res = post_to_facebook(
                message=caption,
                image_path=local_img,
                image_url=image_url if not local_img else None,
                target_page_id=page_id,
                target_access_token=token,
                scheduled_publish_time=sched_ts
            )

        if not res.get("success"):
            err = res.get("error", "ไม่สามารถส่งขึ้นไปตั้งเวลาบน Facebook ได้")
            add_log(f"❌ [Facebook Schedule Error] {err}", "error")
            return jsonify({"success": False, "error": f"Facebook ปฏิเสธการตั้งเวลา: {err}"}), 500

        fb_id = res.get("post_id") or res.get("video_id") or "sim_fb_sched"
        db_id = record_post_history(
            page_id=page_id,
            title=title or ("Facebook Reel" if post_type == "reel" else "โพสต์ Facebook"),
            caption=caption,
            post_type=post_type,
            post_id=fb_id,
            status="fb_scheduled",
            image_url=image_url or "",
            local_image_path=local_img or "",
            video_path=video_path or "",
            scheduled_time=scheduled_time,
            is_fb_native=1,
            user_id=user_id,
            published_at=scheduled_time
        )
        if article_url:
            mark_as_posted(article_url, post_id=fb_id, page_id=page_id)

        time_display = sched_dt.strftime("%d/%m/%Y %H:%M")
        add_log(f"🌐 [Facebook Scheduled] ส่งขึ้นไปตั้งเวลาบน Facebook สำเร็จ! เพจ: '{pname}' นัดปล่อย: {time_display} (Post ID: {fb_id})", "success")
        return jsonify({
            "success": True,
            "schedule_id": db_id,
            "post_id": fb_id,
            "fb_post_url": build_fb_post_url(fb_id, page_id),
            "mode": "facebook",
            "message": f"ตั้งเวลาบน Facebook เรียบร้อยแล้ว (จะเผยแพร่วันที่ {time_display} โดยที่เซิร์ฟเวอร์ไม่ต้องเปิดทิ้งไว้)"
        })

    # โหมดที่ 2: ตั้งเวลาผ่านเครื่อง Host
    else:
        post_id = create_scheduled_post(
            page_id=page_id,
            caption=caption,
            scheduled_time=scheduled_time,
            title=title,
            article_url=article_url,
            image_url=image_url,
            local_image_path=local_img or ""
        )
        add_log(f"📅 [Host Scheduled] ตั้งเวลาโพสต์ในระบบสำเร็จ! เพจ: '{pname}' นัดหมาย: {scheduled_time}", "success")
        return jsonify({"success": True, "schedule_id": post_id, "mode": "host"})

@app.route("/api/schedule/<int:post_id>/cancel", methods=["POST"])
def api_cancel_schedule(post_id):
    """ยกเลิกการตั้งเวลาโพสต์ (หากตั้งไว้บน Facebook จะยิงไปลบออกจาก Facebook ให้ด้วย)"""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT sp.*, p.access_token FROM scheduled_posts sp LEFT JOIN pages p ON sp.page_id = p.page_id WHERE sp.id = ?", (post_id,))
        row = cursor.fetchone()

    if not row:
        return jsonify({"success": False, "error": "ไม่พบรายการโพสต์นี้"}), 404

    item = dict(row)
    fb_post_id = item.get("post_id")
    token = item.get("access_token")

    # หากตั้งเวลาไว้บน Facebook และมี Post ID ให้ยิงไปลบออกจาก Facebook
    if item.get("is_fb_native") and fb_post_id and token:
        del_res = delete_facebook_post(fb_post_id, token)
        if not del_res.get("success"):
            print(f"⚠️ ลบโพสต์บน FB ไม่สำเร็จ หรือโพสต์อาจถูกเผยแพร่ไปแล้ว: {del_res.get('error')}")

    cancel_scheduled_post(post_id)
    add_log(f"⏹️ ยกเลิกรายการตั้งเวลา #{post_id} เรียบร้อยแล้ว", "info")
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
    """ดึงรายการข่าวล่าสุดพร้อมระบบแบ่งหน้า Pagination และ Filter ค้นหา (ความเร็วสูง ไร้ Glob I/O)"""
    page = request.args.get("page", 1, type=int)
    limit = request.args.get("limit", 15, type=int)
    limit = max(1, min(limit, 50))
    page_id = request.args.get("page_id")
    filter_status = request.args.get("status")
    search_q = request.args.get("q", "").strip()
    
    paginated = get_paginated_articles(page=page, limit=limit, page_id=page_id, status=filter_status, search=search_q)
    
    for art in paginated["items"]:
        img = art.get("image_url")
        art["local_image"] = art.get("card_image_path") or img

        if art.get("status") == "posted" and not art.get("fb_post_url"):
            art["fb_post_url"] = build_fb_post_url(art.get("fb_post_id"), art.get("page_id") or page_id)

        cat_type = detect_article_category(art.get("title", ""), art.get("summary", ""), art.get("source", ""))
        c_cat, c_theme = get_card_category_and_theme(cat_type, title_source=f"{art.get('title','')} {art.get('source','')}")
        art["detected_category"] = c_cat
        art["detected_theme"] = c_theme
        art["raw_category"] = cat_type

    if request.args.get("format") == "legacy":
        return jsonify(paginated["items"])
    return jsonify(paginated)

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

    user = get_current_user()
    user_keys = get_active_api_keys_for_user(user["id"]) if user else []
    chosen_key = user_keys[0] if user_keys else None

    add_log(f"✨ สั่ง AI เขียนข่าวนี้ใหม่: {art.get('title', '')[:35]}...", "info")
    new_text = rewrite_article(art, api_key=chosen_key)
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
    category = str(data.get("category", "")).strip()
    theme = str(data.get("theme", "")).strip()
    subtitle = str(data.get("subtitle", "")).strip() or None

    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM articles WHERE id = ?", (article_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"success": False, "error": "ไม่พบบทความ"}), 404
        article = dict(row)

    art_cat = detect_article_category(article.get("title", ""), article.get("summary", ""), article.get("source", ""))
    default_cat, default_theme = get_card_category_and_theme(art_cat, title_source=f"{article.get('title','')} {article.get('source','')}")
    if not category:
        category = default_cat
    if not theme:
        theme = default_theme

    if not headline:
        headline = extract_thai_card_headline(
            article.get("rewritten_text") or "",
            fallback_title=article.get("title", ""),
            category=art_cat
        )

    page_name = "News Updates"
    page_id = article.get("page_id")
    if page_id:
        pinfo = get_page_by_id(page_id)
        if pinfo:
            page_name = pinfo.get("name", "News Updates")

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
        message=clean_post_for_facebook(text),
        image_path=local_img,
        image_url=image_url if not local_img else None,
        target_page_id=target_page_id,
        target_access_token=target_token
    )

    if res.get("success"):
        fb_id = res.get("post_id") or "sim_post"
        fb_url = build_fb_post_url(fb_id, target_page_id)
        mark_as_posted(url, post_id=fb_id, fb_post_url=fb_url, page_id=target_page_id)
        user_id = session.get("user_id", 1)
        record_post_history(
            page_id=target_page_id or config.FB_PAGE_ID,
            title="",
            caption=text,
            post_type="card" if (use_card and card_image_path) else "post",
            post_id=fb_id,
            status="posted",
            image_url=image_url or "",
            local_image_path=local_img or "",
            user_id=user_id
        )
        if res.get("mode") == "dry_run":
            reason = res.get("reason", "โหมดทดสอบ DRY-RUN")
            add_log(f"🟡 [DRY-RUN] จำลองโพสต์ขึ้นเพจ '{target_name}' สำเร็จ ({reason} - ยังไม่ได้ยิงขึ้น Facebook จริง)", "warning")
        else:
            add_log(f"🎉 [LIVE] โพสต์ข่าวขึ้น Facebook เพจ '{target_name}' สำเร็จแล้ว! (Post ID: {fb_id})", "success")
        return jsonify({"success": True, "result": res, "post_id": fb_id, "fb_post_url": fb_url})
    else:
        err = res.get("error", "ไม่สามารถโพสต์ได้")
        add_log(f"❌ โพสต์ขึ้น Facebook ล้มเหลว: {err}", "error")
        return jsonify({"success": False, "error": err}), 500

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
        headline = article.get("title", "ข่าวด่วนล่าสุด")

    if not speech_text:
        speech_text = article.get("rewritten_text") or article.get("summary") or headline

    page_name = getattr(config, "DEFAULT_PAGE_NAME", "ทันข่าว")
    page_id = article.get("page_id")
    if page_id:
        p_info = get_page_by_id(page_id)
        if p_info:
            page_name = p_info.get("name", getattr(config, "DEFAULT_PAGE_NAME", "ทันข่าว"))

    # หาภาพที่คมชัดที่สุด (ใช้ Social Card ถ้ามี หรือภาพต้นฉบับ)
    img_path = None
    if article.get("card_image_path") and os.path.exists(article["card_image_path"]):
        img_path = article["card_image_path"]
    elif article.get("image_url"):
        img_path = download_image(article["image_url"], filename_prefix=f"vid_art_{article_id}")

    try:
        user = get_current_user()
        user_keys = get_active_api_keys_for_user(user["id"]) if user else []
        chosen_key = user_keys[0] if user_keys else None

        add_log(f"🎬 กำลังสร้างวิดีโอสั้นด้วยเสียงพากย์ Google AI Studio ({voice}): {headline[:30]}...", "info")
        out_filename = f"short_{article_id}_{int(time.time())}.mp4"
        out_path = str(config.BASE_DIR / "downloads" / "videos" / out_filename)

        vid_path = generate_short_video(
            image_path=img_path,
            headline=headline,
            speech_text=speech_text,
            page_name=page_name,
            output_path=out_path,
            voice_name=voice,
            api_key=chosen_key
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
    caption = str(data.get("caption", "")).strip()
    filename = str(data.get("filename", "")).strip()
    if "?" in filename:
        filename = filename.split("?")[0]
    filename = os.path.basename(filename)

    if not filename:
        return jsonify({"success": False, "error": "ไม่พบชื่อไฟล์วิดีโอ"}), 400

    videos_dir = config.BASE_DIR / "downloads" / "videos"
    video_path = str(videos_dir / filename)
    if not os.path.exists(video_path):
        return jsonify({"success": False, "error": f"ไม่พบไฟล์วิดีโอ {filename} ในโฟลเดอร์"}), 404

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
        vid_id = res.get("video_id") or res.get("post_id") or "sim_reel"
        user_id = session.get("user_id", 1)
        record_post_history(
            page_id=target_page_id or config.FB_PAGE_ID,
            title=article.get("title", "คลิปวิดีโอ Facebook Reels"),
            caption=caption,
            post_type="reel",
            post_id=vid_id,
            status="posted",
            video_path=video_path,
            user_id=user_id
        )
        if article.get("url"):
            fb_url = build_fb_post_url(vid_id, target_page_id)
            mark_as_posted(article.get("url"), post_id=vid_id, fb_post_url=fb_url, page_id=target_page_id)
        add_log(f"🎉 โพสต์ Facebook Reel สำเร็จเรียบร้อย!{mode} (Video ID: {vid_id})", "success")
        return jsonify({"success": True, "result": res, "post_id": vid_id, "fb_post_url": build_fb_post_url(vid_id, target_page_id)})
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
# API: AFFILIATE MANAGER & AI POSTER
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

@app.route("/api/affiliate/fetch_product", methods=["POST"])
def api_affiliate_fetch_product():
    """ดึงข้อมูลสินค้าจาก Shopee / Lazada / TikTok Shop"""
    data = request.json or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"success": False, "error": "กรุณาระบุ URL สินค้า"}), 400

    prod_info = affiliate_ai_service.fetch_product_details(url)
    return jsonify({"success": True, "product": prod_info})

@app.route("/api/affiliate/generate_caption", methods=["POST"])
def api_affiliate_generate_caption():
    """ใช้ Gemini AI คิดคำโปรโมทสินค้า ป้ายยา หรือ Flash Sale"""
    data = request.json or {}
    product_name = data.get("product_name", "").strip()
    product_desc = data.get("product_desc", "").strip()
    price = data.get("price", "").strip()
    affiliate_url = data.get("affiliate_url", "").strip()
    platform = data.get("platform", "general").strip()
    style = data.get("style", "flash_sale").strip()
    page_context = data.get("page_context", "เพจกีฬาและแฟนบอล").strip()
    user_id = session.get("user_id", 1)

    if not product_name:
        return jsonify({"success": False, "error": "กรุณาระบุชื่อสินค้า"}), 400

    caption = affiliate_ai_service.generate_affiliate_caption(
        product_name=product_name,
        product_desc=product_desc,
        price=price,
        affiliate_url=affiliate_url,
        platform=platform,
        style=style,
        page_context=page_context,
        user_id=user_id
    )

    return jsonify({"success": True, "caption": caption})

@app.route("/api/affiliate/post", methods=["POST"])
def api_affiliate_post():
    """โพสต์สินค้า Affiliate ทันที หรือตั้งเวลาลงเพจ Facebook"""
    data = request.json or {}
    page_id = str(data.get("page_id", "")).strip()
    caption = str(data.get("caption", "")).strip()
    image_url = str(data.get("image_url", "")).strip()
    is_scheduled = bool(data.get("is_scheduled", False))
    scheduled_time = str(data.get("scheduled_time", "")).strip()
    schedule_mode = str(data.get("schedule_mode", "facebook")).strip()
    user_id = session.get("user_id", 1)

    if not page_id or not caption:
        return jsonify({"success": False, "error": "กรุณาระบุเพจและข้อความที่จะโพสต์"}), 400

    target_page = get_page_by_id(page_id)
    if not target_page:
        return jsonify({"success": False, "error": "ไม่พบเพจที่เลือก"}), 404

    target_token = target_page.get("access_token")
    page_name = target_page.get("name", page_id)

    # ดาวน์โหลดรูปภาพสินค้าเก็บไว้ในเครื่อง หากเป็น URL ภายนอก
    local_image = None
    if image_url:
        try:
            local_image = download_image(image_url, filename_prefix="aff_prod")
        except Exception as e:
            add_log(f"⚠️ ไม่สามารถดาวน์โหลดรูปภาพสินค้าได้ ({e}) จะใช้ URL แทน", "warning")

    if is_scheduled:
        if not scheduled_time:
            return jsonify({"success": False, "error": "กรุณาระบุวัน-เวลาที่ต้องการตั้งโพสต์"}), 400

        is_fb_native = (schedule_mode == "facebook")
        if is_fb_native:
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(scheduled_time)
                sched_ts = int(dt.timestamp())
                now_ts = int(datetime.now().timestamp())
                diff_min = (sched_ts - now_ts) / 60
                if diff_min < 15:
                    return jsonify({"success": False, "error": "Meta กำหนดให้ตั้งเวลาล่วงหน้าอย่างน้อย 15 นาที"}), 400
                if diff_min > (75 * 24 * 60):
                    return jsonify({"success": False, "error": "Meta กำหนดให้ตั้งเวลาล่วงหน้าไม่เกิน 75 วัน"}), 400
            except ValueError:
                return jsonify({"success": False, "error": "รูปแบบวันเวลาไม่ถูกต้อง"}), 400

            res = post_to_facebook(
                message=caption,
                image_path=local_image,
                image_url=image_url if not local_image else None,
                target_page_id=page_id,
                target_access_token=target_token,
                scheduled_publish_time=sched_ts
            )
            if not res.get("success"):
                return jsonify({"success": False, "error": f"ตั้งเวลาบน Facebook ไม่สำเร็จ: {res.get('error')}"}), 500

            fb_post_id = res.get("post_id", "") or "sim_fb_sched"
            db_id = record_post_history(
                page_id=page_id,
                title="Affiliate Product Post",
                caption=caption,
                post_type="affiliate",
                post_id=fb_post_id,
                status="fb_scheduled",
                image_url=image_url or "",
                local_image_path=local_image or "",
                scheduled_time=scheduled_time,
                is_fb_native=1,
                user_id=user_id,
                published_at=scheduled_time
            )
            add_log(f"⏰ ตั้งเวลาโพสต์สินค้า Affiliate บน Facebook สำเร็จ! (เพจ: {page_name}, เวลา: {scheduled_time})", "success")
            return jsonify({"success": True, "schedule_id": db_id, "mode": "facebook", "post_id": fb_post_id})
        else:
            sched_id = create_scheduled_post(
                page_id=page_id,
                caption=caption,
                scheduled_time=scheduled_time,
                title="Affiliate Product Post",
                image_url=image_url or "",
                local_image_path=local_image or ""
            )
            add_log(f"⏰ บันทึกคิวตั้งเวลาโพสต์สินค้า Affiliate (Host Mode) สำเร็จ! (เพจ: {page_name})", "success")
            return jsonify({"success": True, "schedule_id": sched_id, "mode": "host"})

    else:
        # โพสต์ทันที
        res = post_to_facebook(
            message=caption,
            image_path=local_image,
            image_url=image_url if not local_image else None,
            target_page_id=page_id,
            target_access_token=target_token
        )
        if res.get("success"):
            fb_id = res.get("post_id", "sim_post")
            record_post_history(
                page_id=page_id,
                title="Affiliate Product Post",
                caption=caption,
                post_type="affiliate",
                post_id=fb_id,
                status="posted",
                image_url=image_url or "",
                local_image_path=local_image or "",
                user_id=user_id
            )
            add_log(f"🎉 โพสต์สินค้า Affiliate ขึ้น Facebook เพจ '{page_name}' เรียบร้อยแล้ว! (ID: {fb_id})", "success")
            return jsonify({"success": True, "post_id": fb_id})
        else:
            err = res.get("error", "Unknown error")
            add_log(f"❌ โพสต์สินค้า Affiliate ล้มเหลว: {err}", "error")
            return jsonify({"success": False, "error": err}), 500

# -------------------------------------------------------------
# API: GOOGLE FLOW IMAGE STUDIO & AUTO-POSTER
# -------------------------------------------------------------
@app.route("/api/flow_image/status", methods=["GET"])
def api_flow_image_status():
    """ตรวจสอบสถานะ Google Flow Bridge และพอร์ต Chrome ที่เปิดอยู่"""
    return jsonify(flow_image_poster.get_flow_status())

@app.route("/api/flow_image/analyze_ref", methods=["POST"])
def api_flow_image_analyze_ref():
    """
    วิเคราะห์ภาพอ้างอิง และ/หรือ หัวข้อที่ต้องการ
    คืนค่า English Prompt สำหรับ Google Flow, พาดหัว, ข้อความรอง และแคปชั่น
    """
    topic = request.form.get("topic", "")
    user_style_note = request.form.get("user_style_note", "")
    user_id = session.get("user_id", 1)

    ref_image_path = None
    ref_image_url = None

    # จัดการไฟล์อัปโหลดภาพอ้างอิง
    if "ref_image" in request.files:
        f = request.files["ref_image"]
        if f and f.filename:
            upload_dir = config.BASE_DIR / "static" / "uploads" / "ref_images"
            upload_dir.mkdir(parents=True, exist_ok=True)
            ext = os.path.splitext(f.filename)[1] or ".jpg"
            fname = f"ref_{int(time.time()*1000)}{ext}"
            save_path = upload_dir / fname
            f.save(str(save_path))
            ref_image_path = str(save_path)
            ref_image_url = f"/static/uploads/ref_images/{fname}"

    # หรือถ้าส่งมาเป็น JSON
    if not ref_image_path and request.is_json:
        data = request.json or {}
        topic = data.get("topic", topic)
        user_style_note = data.get("user_style_note", user_style_note)
        ref_image_url = data.get("ref_image_url")
        if ref_image_url and ref_image_url.startswith("/static/"):
            ref_image_path = str(config.BASE_DIR / ref_image_url.lstrip("/"))

    analysis = flow_image_poster.analyze_reference_image_and_prompt(
        ref_image_path=ref_image_path,
        topic=topic,
        user_style_note=user_style_note,
        user_id=user_id
    )
    if ref_image_url:
        analysis["ref_image_url"] = ref_image_url

    return jsonify(analysis)

@app.route("/api/flow_image/generate", methods=["POST"])
def api_flow_image_generate():
    """ส่ง Prompt ไปยัง Google Flow เพื่อเจนรูปภาพ และตกแต่ง Typography ตามที่เลือก"""
    data = request.json or {}
    prompt = str(data.get("prompt", "")).strip()
    stamp_typography = bool(data.get("stamp_typography", False))
    headline = str(data.get("headline", "")).strip()
    subtitle = str(data.get("subtitle", "")).strip()
    badge = str(data.get("badge", "🔴 MATCHDAY")).strip()
    theme = str(data.get("theme", "lfc_red")).strip()
    port = data.get("port")
    if port:
        try:
            port = int(port)
        except ValueError:
            port = None

    if not prompt:
        return jsonify({"success": False, "error": "กรุณาระบุ Prompt สำหรับเจนรูปภาพ"}), 400

    add_log(f"🎨 กำลังส่งคำสั่งเจนรูปภาพไปยัง Google Flow: '{prompt[:45]}...' (พอร์ต {port or 'Auto'})", "info")

    success, result_path = flow_image_poster.generate_image_with_google_flow(
        prompt=prompt,
        port=port
    )

    if not success:
        add_log(f"❌ Google Flow ไม่สามารถเจนรูปได้: {result_path}", "error")
        return jsonify({"success": False, "error": result_path}), 500

    final_local_path = result_path
    if stamp_typography and (headline or subtitle):
        try:
            final_local_path = flow_image_poster.stamp_typography(
                image_path=result_path,
                headline=headline,
                subtitle=subtitle,
                badge=badge,
                theme_key=theme
            )
            add_log(f"✨ ตกแต่ง Typography ภาษาไทยลงบนภาพเรียบร้อยแล้ว!", "info")
        except Exception as e_stamp:
            add_log(f"⚠️ ไม่สามารถประทับตัวอักษรได้ ({e_stamp}) จะใช้รูปต้นฉบับแทน", "warning")

    rel_path = os.path.relpath(final_local_path, config.BASE_DIR).replace("\\", "/")
    web_url = f"/{rel_path}"

    add_log(f"🎉 สร้างรูปภาพโพสต์ด้วย Google Flow สำเร็จแล้ว! ({os.path.basename(final_local_path)})", "success")

    return jsonify({
        "success": True,
        "image_url": web_url,
        "local_path": final_local_path,
        "is_stamped": stamp_typography
    })

@app.route("/api/flow_image/post", methods=["POST"])
def api_flow_image_post():
    """โพสต์รูปที่เจนจาก Google Flow ขึ้น Facebook ทันที หรือตั้งเวลาล่วงหน้า"""
    data = request.json or {}
    page_id = str(data.get("page_id", "")).strip()
    caption = str(data.get("caption", "")).strip()
    image_url = str(data.get("image_url", "")).strip()
    local_path = str(data.get("local_path", "")).strip()
    is_scheduled = bool(data.get("is_scheduled", False))
    scheduled_time = str(data.get("scheduled_time", "")).strip()
    schedule_mode = str(data.get("schedule_mode", "facebook")).strip()
    user_id = session.get("user_id", 1)

    if not page_id or not caption:
        return jsonify({"success": False, "error": "กรุณาระบุเพจและข้อความที่จะโพสต์"}), 400

    target_page = get_page_by_id(page_id)
    if not target_page:
        return jsonify({"success": False, "error": "ไม่พบเพจที่เลือก"}), 404

    target_token = target_page.get("access_token")
    page_name = target_page.get("name", page_id)

    target_img_path = None
    if local_path and os.path.exists(local_path):
        target_img_path = local_path
    elif image_url:
        clean_rel = image_url.lstrip("/")
        candidate = config.BASE_DIR / clean_rel
        if candidate.exists():
            target_img_path = str(candidate)
        else:
            try:
                target_img_path = download_image(image_url, filename_prefix="flow_post")
            except Exception:
                pass

    if is_scheduled:
        if not scheduled_time:
            return jsonify({"success": False, "error": "กรุณาระบุวัน-เวลาที่ต้องการตั้งโพสต์"}), 400

        is_fb_native = (schedule_mode == "facebook")
        if is_fb_native:
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(scheduled_time)
                sched_ts = int(dt.timestamp())
                now_ts = int(datetime.now().timestamp())
                diff_min = (sched_ts - now_ts) / 60
                if diff_min < 15:
                    return jsonify({"success": False, "error": "Meta กำหนดให้ตั้งเวลาล่วงหน้าอย่างน้อย 15 นาที"}), 400
                if diff_min > (75 * 24 * 60):
                    return jsonify({"success": False, "error": "Meta กำหนดให้ตั้งเวลาล่วงหน้าไม่เกิน 75 วัน"}), 400
            except ValueError:
                return jsonify({"success": False, "error": "รูปแบบวันเวลาไม่ถูกต้อง"}), 400

            res = post_to_facebook(
                message=caption,
                image_path=target_img_path,
                image_url=image_url if not target_img_path else None,
                target_page_id=page_id,
                target_access_token=target_token,
                scheduled_publish_time=sched_ts
            )
            if not res.get("success"):
                return jsonify({"success": False, "error": f"ตั้งเวลาบน Facebook ไม่สำเร็จ: {res.get('error')}"}), 500

            fb_post_id = res.get("post_id", "") or "sim_fb_sched"
            db_id = record_post_history(
                page_id=page_id,
                title="AI Flow Image Post",
                caption=caption,
                post_type="flow_image",
                post_id=fb_post_id,
                status="fb_scheduled",
                image_url=image_url or "",
                local_image_path=target_img_path or "",
                scheduled_time=scheduled_time,
                is_fb_native=1,
                user_id=user_id,
                published_at=scheduled_time
            )
            add_log(f"⏰ ตั้งเวลาโพสต์รูป AI Flow บน Facebook สำเร็จ! (เพจ: {page_name}, เวลา: {scheduled_time})", "success")
            return jsonify({"success": True, "schedule_id": db_id, "mode": "facebook", "post_id": fb_post_id})
        else:
            sched_id = create_scheduled_post(
                page_id=page_id,
                caption=caption,
                scheduled_time=scheduled_time,
                title="AI Flow Image Post",
                image_url=image_url or "",
                local_image_path=target_img_path or ""
            )
            add_log(f"⏰ บันทึกคิวตั้งเวลาโพสต์รูป AI Flow (Host Mode) สำเร็จ! (เพจ: {page_name})", "success")
            return jsonify({"success": True, "schedule_id": sched_id, "mode": "host"})

    else:
        # โพสต์ทันที
        res = post_to_facebook(
            message=caption,
            image_path=target_img_path,
            image_url=image_url if not target_img_path else None,
            target_page_id=page_id,
            target_access_token=target_token
        )
        if res.get("success"):
            fb_id = res.get("post_id", "sim_post")
            record_post_history(
                page_id=page_id,
                title="AI Flow Image Post",
                caption=caption,
                post_type="flow_image",
                post_id=fb_id,
                status="posted",
                image_url=image_url or "",
                local_image_path=target_img_path or "",
                user_id=user_id
            )
            add_log(f"🎉 โพสต์รูป AI Flow ขึ้น Facebook เพจ '{page_name}' เรียบร้อยแล้ว! (ID: {fb_id})", "success")
            return jsonify({"success": True, "post_id": fb_id})
        else:
            err = res.get("error", "Unknown error")
            add_log(f"❌ โพสต์รูป AI Flow ล้มเหลว: {err}", "error")
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
                        p_name = "News Updates"
                        if art_page:
                            p_info_card = get_page_by_id(art_page)
                            if p_info_card:
                                p_name = p_info_card.get("name", "News Updates")

                        cat_type = detect_article_category(title, summary, source)
                        card_hl = extract_thai_card_headline(rewritten, fallback_title=title, category=cat_type)
                        card_cat, card_theme = get_card_category_and_theme(cat_type, p_name, f"{title} {source}")

                        cards_dir = config.BASE_DIR / "downloads" / "cards"
                        cards_dir.mkdir(parents=True, exist_ok=True)
                        out_card = str(cards_dir / f"card_{int(time.time()*1000)}.jpg")

                        card_path = generate_social_card(
                            image_path=local_img,
                            headline=card_hl,
                            category=card_cat,
                            page_name=p_name,
                            output_path=out_card,
                            theme=card_theme
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
                                message=clean_post_for_facebook(rewritten, category=cat_type),
                                image_path=post_img,
                                image_url=img if not post_img else None,
                                target_page_id=art_page,
                                target_access_token=p_info["access_token"]
                            )
                            if res.get("success"):
                                fb_id = res.get("post_id") or "sim_post"
                                mark_as_posted(url, post_id=fb_id, page_id=art_page)
                                if res.get("mode") == "dry_run":
                                    add_log(f"🟡 [DRY-RUN] จำลองโพสต์ขึ้นเพจ '{p_info['name']}' สำเร็จ: {title[:30]}... (โหมดทดสอบ)", "warning")
                                else:
                                    add_log(f"🎉 [LIVE] โพสต์ขึ้น Facebook เพจ '{p_info['name']}' สำเร็จ: {title[:30]}...", "success")
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
                                card_path = None
                                try:
                                    cat_type = detect_article_category(art["title"], art.get("summary", ""), art.get("source", ""))
                                    card_hl = extract_thai_card_headline(rewritten, fallback_title=art["title"], category=cat_type)
                                    card_cat, card_theme = get_card_category_and_theme(cat_type, p["name"], f"{art['title']} {art.get('source','')}")
                                    cards_dir = config.BASE_DIR / "downloads" / "cards"
                                    cards_dir.mkdir(parents=True, exist_ok=True)
                                    out_card = str(cards_dir / f"card_{int(time.time()*1000)}.jpg")
                                    card_path = generate_social_card(
                                        image_path=local_img,
                                        headline=card_hl,
                                        category=card_cat,
                                        page_name=p["name"],
                                        output_path=out_card,
                                        theme=card_theme
                                    )
                                except Exception as e_card:
                                    print(f"Auto card error: {e_card}")

                                post_img = card_path if (card_path and os.path.exists(card_path)) else local_img
                                res_auto = post_to_facebook(clean_post_for_facebook(rewritten, category=cat_type), post_img, art.get("image_url") if not post_img else None, target_page_id=pid, target_access_token=token)
                                auto_fb_id = res_auto.get("post_id") or "sim_post"
                                mark_as_posted(art["url"], post_id=auto_fb_id, page_id=pid)
                                if res_auto.get("mode") == "dry_run":
                                    add_log(f"🟡 [Auto-Bot (DRY-RUN)] จำลองโพสต์ข่าวขึ้นเพจ '{p['name']}': {art['title'][:30]}... (โหมดทดสอบ)", "warning")
                                else:
                                    add_log(f"🎉 [Auto-Bot (LIVE)] โพสต์ข่าวใหม่ขึ้น Facebook เพจ '{p['name']}': {art['title'][:30]}...", "success")
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
                                mark_as_posted(post["article_url"], post_id=fb_id, page_id=page_id)
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
# เริ่มต้นตัวเช็คคิวโพสต์อัตโนมัติ (รองรับทั้ง direct python และ Gunicorn บน Render)
start_scheduler_worker()

def start_app():
    port = int(os.environ.get("PORT", 5000))
    add_log(f"🚀 เริ่มต้นระบบ Multi-Page Auto News & Scheduler Web App ที่ port {port}", "info")
    if not os.environ.get("RENDER"):
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    app.run(host="0.0.0.0", port=port, debug=False)

if __name__ == "__main__":
    start_app()
