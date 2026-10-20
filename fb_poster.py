import os
import html
import requests
from pathlib import Path
from typing import Dict, Optional

import config
from config import BASE_DIR

PREVIEW_HTML_PATH = BASE_DIR / "downloads" / "preview_posts.html"

def post_to_facebook(
    message: str,
    image_path: Optional[str] = None,
    image_url: Optional[str] = None,
    target_page_id: Optional[str] = None,
    target_access_token: Optional[str] = None
) -> Dict:
    """
    โพสต์ข้อความและรูปภาพขึ้น Facebook Page
    รองรับทั้งเพจหลัก และเพจอื่นๆ ที่ส่ง target_page_id / target_access_token เข้ามา
    หากตั้ง DRY_RUN=True จะจำลองการโพสต์และบันทึกลง preview_posts.html แทน
    """
    config.reload_config()

    page_id = target_page_id or config.FB_PAGE_ID
    access_token = target_access_token or config.FB_PAGE_ACCESS_TOKEN

    # โหมดจำลองการโพสต์ (Dry Run)
    if config.DRY_RUN or not page_id or not access_token:
        print(f"📢 [DRY RUN] โหมดทดสอบสำหรับเพจ {page_id}: บันทึกตัวอย่างโพสต์ลงไฟล์พรีวิว (ยังไม่ยิงขึ้น Facebook จริง)")
        save_to_html_preview(message, image_path or image_url)
        return {
            "success": True,
            "mode": "dry_run",
            "message": "บันทึกตัวอย่างลง preview_posts.html เรียบร้อยแล้ว"
        }

    # โหมดโพสต์จริงขึ้น Facebook Page ผ่าน Graph API
    url_base = f"https://graph.facebook.com/v19.0/{page_id}"

    try:
        # กรณีมีรูปภาพในเครื่อง
        if image_path and os.path.exists(image_path):
            endpoint = f"{url_base}/photos"
            with open(image_path, "rb") as img_file:
                files = {"source": img_file}
                data = {
                    "caption": message,
                    "access_token": access_token
                }
                resp = requests.post(endpoint, data=data, files=files, timeout=30)
        # กรณีมี URL รูปภาพตรงๆ
        elif image_url:
            endpoint = f"{url_base}/photos"
            data = {
                "url": image_url,
                "caption": message,
                "access_token": access_token
            }
            resp = requests.post(endpoint, data=data, timeout=30)
        # กรณีไม่มีรูปภาพ โพสต์ข้อความอย่างเดียว
        else:
            endpoint = f"{url_base}/feed"
            data = {
                "message": message,
                "access_token": access_token
            }
            resp = requests.post(endpoint, data=data, timeout=30)

        result = resp.json()
        if resp.status_code == 200:
            post_id = result.get("id") or result.get("post_id")
            print(f"✅ โพสต์ขึ้น Facebook เพจ {page_id} สำเร็จเรียบร้อย! (Post ID: {post_id})")
            return {"success": True, "post_id": post_id}
        else:
            err_msg = result.get("error", {}).get("message", "Unknown error")
            print(f"❌ โพสต์ขึ้น Facebook เพจ {page_id} ล้มเหลว: {err_msg}")
            return {"success": False, "error": err_msg}

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการเชื่อมต่อ Facebook API: {e}")
        return {"success": False, "error": str(e)}

def save_to_html_preview(message: str, image_source: Optional[str] = None):
    """สร้างหน้า HTML พรีวิวเลียนแบบหน้าจอโพสต์ Facebook ให้อ่านง่ายและสวยงาม"""
    PREVIEW_HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # แปลงขึ้นบรรทัดใหม่เป็น <br>
    formatted_msg = html.escape(message).replace("\n", "<br>")
    
    img_tag = ""
    if image_source:
        if os.path.exists(str(image_source)):
            # Local file path
            rel_path = Path(image_source).name
            img_tag = f'<img src="images/{rel_path}" style="max-width:100%; border-radius:8px; margin-top:12px;" />'
        else:
            img_tag = f'<img src="{image_source}" style="max-width:100%; border-radius:8px; margin-top:12px;" />'

    card_html = f"""
    <div style="background:#ffffff; border:1px solid #ddd; border-radius:12px; padding:20px; max-width:650px; margin:20px auto; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; box-shadow:0 4px 12px rgba(0,0,0,0.08);">
        <div style="display:flex; align-items:center; margin-bottom:14px;">
            <div style="width:48px; height:48px; border-radius:50%; background:#c8102e; color:#fff; display:flex; align-items:center; justify-content:center; font-weight:bold; font-size:20px; margin-right:12px;">LFC</div>
            <div>
                <div style="font-weight:bold; font-size:16px; color:#050505;">Liverpool FC News Thailand</div>
                <div style="font-size:12px; color:#65676b;">เมื่อสักครู่ · 🌐 สาธารณะ</div>
            </div>
        </div>
        <div style="font-size:15px; line-height:1.6; color:#1c1e21; white-space:pre-wrap;">{formatted_msg}</div>
        {img_tag}
    </div>
    """

    if not PREVIEW_HTML_PATH.exists():
        header = """<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <title>ตัวอย่างโพสต์ข่าวลิเวอร์พูล (Facebook Preview)</title>
    <style>body { background:#f0f2f5; padding:20px; }</style>
</head>
<body>
    <h2 style="text-align:center; color:#c8102e; font-family:sans-serif;">🔴 พรีวิวตัวอย่างข่าวลิเวอร์พูล (สำนวนเก๋าจัดจ้าน)</h2>
"""
        with open(PREVIEW_HTML_PATH, "w", encoding="utf-8") as f:
            f.write(header + card_html + "</body></html>")
    else:
        with open(PREVIEW_HTML_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        # แทรกการ์ดใหม่ไว้ด้านบนสุด
        if "<body>" in content:
            new_content = content.replace("<body>", f"<body>\n{card_html}")
            with open(PREVIEW_HTML_PATH, "w", encoding="utf-8") as f:
                f.write(new_content)
