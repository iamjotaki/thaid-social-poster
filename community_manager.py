"""
Module: community_manager.py
ระบบบอทสร้าง Engagement & ตอบคอมเมนต์ลูกเพจ (AI Community Manager)
1. สร้างโพสต์โพลล์ (Poll), ประเด็นชวนคุยเดือดๆ และเกมทายผลสกอร์
2. ผู้ช่วยอ่านและร่างคำตอบคอมเมนต์ลูกเพจสไตล์คอลัมนิสต์เก๋าจัดจ้าน
3. ดึงคอมเมนต์จาก Facebook Graph API และตอบกลับอัตโนมัติ
"""

import os
import sys
import json
import re
import requests
from typing import Dict, List, Optional

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import config
from ai_rewriter import sanitize_forbidden_words

def call_gemini(prompt: str) -> Optional[str]:
    """ส่ง Prompt ให้ Gemini สร้างข้อความ"""
    if not config.GEMINI_API_KEY:
        return None

    candidate_models = [
        'gemini-3.8-flash',
        'gemini-3.7-flash',
        'gemini-3.5-flash',
        'gemini-3.5-flash-lite'
    ]

    try:
        from google import genai
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        for model in candidate_models:
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config={
                        'system_instruction': config.AI_SYSTEM_INSTRUCTION,
                        'temperature': 0.9,
                        'top_p': 0.95
                    }
                )
                if resp and resp.text:
                    return sanitize_forbidden_words(resp.text)
            except Exception as e_m:
                print(f"[CommunityManager] Model {model} error: {e_m}")
                continue
    except Exception as e:
        print(f"[CommunityManager Global Error]: {e}")
    return None

def generate_engagement_post(post_type: str = "poll", custom_topic: str = None) -> str:
    """
    สร้างโพสต์กระตุ้น Engagement หลากหลายรูปแบบ:
    :param post_type: 'poll' (โพลล์โหวต), 'debate' (ประเด็นชวนถกเถียง), 'trivia' (ทายผล/คำถามแฟนพันธุ์แท้)
    :param custom_topic: หัวข้อที่ต้องการเน้น (ถ้ามี)
    """
    topic_str = f"เน้นในหัวข้อ: {custom_topic}" if custom_topic else "คิดหัวข้อเกี่ยวกับสถานการณ์ล่าสุดของลิเวอร์พูล"

    if post_type == "poll":
        prompt = f"""
คุณคือนักเขียนคอลัมนิสต์แฟนเพจลิเวอร์พูล
กรุณาเขียน "โพสต์โพลล์สำรวจความเห็นแฟนบอล (Facebook Poll)" เพื่อดึงดูดคอมเมนต์ให้ทะลัก:
{topic_str}

โครงสร้างโพสต์:
1. 🔴 พาดหัวคำถามตัวใหญ่ๆ ชวนกดไลก์
2. คำโปรยเปิดประเด็นแบบกวนๆ ถึงพริกถึงขิง
3. ตัวเลือก 3-4 ข้อ ชัดเจน เช่น:
   กด [❤️] เลือก A)...
   กด [😆] เลือก B)...
   กด [😮] เลือก C)...
   หรือคอมเมนต์เหตุผลใต้โพสต์!
4. ประโยคปิดท้ายชวนลูกเพจแสดงความเห็น
5. แฮชแท็ก #LFC #โพลล์หงส์แดง #Liverpool

กฎเหล็ก: ห้ามเอ่ยชื่อ บอ.บู๋ หรือ บอบู๋ โดยเด็ดขาด 100%!
"""
    elif post_type == "debate":
        prompt = f"""
คุณคือนักเขียนคอลัมนิสต์แฟนเพจลิเวอร์พูล ผู้มีลีลากวนจัดจ้าน
กรุณาเขียน "โพสต์เปิดประเด็นชวนถกเถียงเดือดๆ (Debate / Open Discussion)" เพื่อให้ลูกเพจเข้ามาคอมเมนต์แลกเปลี่ยนความเห็นกันสนั่นเพจ:
{topic_str}

โครงสร้าง:
1. 🔴 หัวข้อเปิดประเด็นร้อน
2. ลีลาการโยนประเด็นแบบกวนๆ แทงใจดำ ชวนให้คนอ่านคันไม้คันมืออยากคอมเมนต์ตอบ
3. ประโยคตั้งคำถามปลายเปิด เช่น "คุณคิดว่าไง? จัดมาในคอมเมนต์ อย่าเงียบ!"
4. แฮชแท็ก #LFC #ชวนคุยเด็กหงส์

กฎเหล็ก: ห้ามเอ่ยชื่อ บอ.บู๋ หรือ บอบู๋ โดยเด็ดขาด 100%!
"""
    else:  # trivia / score prediction
        prompt = f"""
คุณคือนักเขียนคอลัมนิสต์แฟนเพจลิเวอร์พูล
กรุณาเขียน "โพสต์ทายผลการแข่งขัน หรือคำถามชิงรางวัลแฟนพันธุ์แท้" สไตล์สนุกสนาน:
{topic_str}

โครงสร้าง:
1. 🎯 กิจกรรมทายผลแมตช์ต่อไป หรือคำถามท้าดวลความจำแฟนหงส์
2. กติการ่วมสนุกง่ายๆ (คอมเมนต์สกอร์ + คนยิงประตูแรก)
3. สำนวนชวนคุยสนุกสนาน เฮฮา เป็นกันเอง
4. แฮชแท็ก #LFC #ทายผลบอล

กฎเหล็ก: ห้ามเอ่ยชื่อ บอ.บู๋ หรือ บอบู๋ โดยเด็ดขาด 100%!
"""

    res = call_gemini(prompt)
    if not res:
        return "🔴 [เปิดประเด็นชวนคุย] คืนนี้แฟนหงส์แดงคิดว่าจุดไหนของทีมเราที่ต้องรีบปรับปรุงด่วนที่สุด? จัดมาในคอมเมนต์!"
    return res

def draft_ai_comment_reply(user_comment: str, post_caption: str = "") -> str:
    """
    ให้ AI ช่วยคิดคำตอบคอมเมนต์ลูกเพจ ในสไตล์คอลัมนิสต์กวนๆ ฉลาด น่ารัก เป็นกันเอง
    """
    prompt = f"""
คุณคือแอดมินเพจแฟนบอลลิเวอร์พูลตัวเก๋า กวนๆ อารมณ์ขัน ตลก แต่คุยลูกเพจแบบเป็นกันเองและจริงใจ
มีลูกเพจเข้ามาคอมเมนต์ใต้โพสต์ว่า:
"{user_comment}"

(บริบทของโพสต์ที่เขามาคุย: {post_caption[:150]})

กรุณาเขียนคำตอบสั้นๆ (1-3 ประโยค) เพื่อตอบกลับคอมเมนต์นี้อย่างมีเสน่ห์ ชวนคุยต่อ หรือแซวหยอกเย้าให้ลูกเพจยิ้มได้:
กฎเหล็ก: ห้ามเอ่ยชื่อ บอ.บู๋ หรือ บอบู๋ โดยเด็ดขาด 100%!
ตอบเฉพาะข้อความที่จะส่งตอบกลับเท่านั้น:
"""
    res = call_gemini(prompt)
    if not res:
        return "ขอบคุณที่เข้ามาแลกเปลี่ยนความเห็นกันครับแฟนหงส์! แมตช์หน้าสู้กันต่อครับ 🔴"
    return res.strip().strip('"')

def fetch_facebook_post_comments(post_id: str, access_token: str, limit: int = 15) -> List[Dict]:
    """ดึงรายการคอมเมนต์ล่าสุดจาก Facebook Post ผ่าน Graph API"""
    if not post_id or not access_token:
        return []
    url = f"https://graph.facebook.com/v21.0/{post_id}/comments"
    params = {
        "access_token": access_token,
        "fields": "id,message,from,created_time,like_count",
        "limit": limit
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        comments = data.get("data", [])
        return [
            {
                "id": c.get("id"),
                "message": c.get("message", ""),
                "sender_name": c.get("from", {}).get("name", "ลูกเพจ"),
                "created_time": c.get("created_time", ""),
                "like_count": c.get("like_count", 0)
            }
            for c in comments
        ]
    except Exception as e:
        print(f"[Facebook Comments Error]: {e}")
        return []

def reply_to_facebook_comment(comment_id: str, reply_text: str, access_token: str) -> Dict:
    """ส่งข้อความตอบกลับคอมเมนต์บน Facebook Page"""
    url = f"https://graph.facebook.com/v21.0/{comment_id}/comments"
    payload = {
        "message": reply_text,
        "access_token": access_token
    }
    try:
        resp = requests.post(url, data=payload, timeout=10)
        data = resp.json()
        if "id" in data:
            return {"success": True, "reply_id": data["id"]}
        return {"success": False, "error": data.get("error", {}).get("message", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    print("Testing community_manager.py...")
    poll = generate_engagement_post(post_type="poll", custom_topic="ใครควรเป็นกัปตันทีมคนต่อไปหากฟาน ไดจ์คอำลาทีม")
    print("Poll sample:\n", poll[:200])
