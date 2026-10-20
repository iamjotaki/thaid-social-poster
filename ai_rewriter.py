import os
import sys
import re
from typing import Optional, Dict

# ปรับ encoding ของ stdout/stderr บน Windows ป้องกัน UnicodeEncodeError
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from config import GEMINI_API_KEY, AI_SYSTEM_INSTRUCTION, FORBIDDEN_WORDS

def sanitize_forbidden_words(text: str) -> str:
    """
    ตรวจสอบและคัดกรองคำต้องห้ามเด็ดขาด
    หากพบชื่อที่ห้ามเอ่ย จะทำการลบหรือแทนที่ด้วยคำที่เป็นกลางทันที
    """
    sanitized = text
    for word in FORBIDDEN_WORDS:
        # ลบคำต้องห้ามทุกรูปแบบ ทั้งมีจุด ไม่มีจุด หรือเว้นวรรค
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        sanitized = pattern.sub("", sanitized)
    
    # ลบช่องว่างซ้ำซ้อนที่อาจเกิดจากการลบคำ
    sanitized = re.sub(r' +', ' ', sanitized)
    return sanitized.strip()

def rewrite_with_gemini(title: str, summary: str, source_name: str) -> Optional[str]:
    """ใช้ Google Gemini API เขียนข่าวใหม่ตามสไตล์ที่กำหนด พร้อมระบบ Fallback หลายโมเดล"""
    if not GEMINI_API_KEY:
        print("⚠️ ยังไม่ได้ตั้งค่า GEMINI_API_KEY ในไฟล์ .env (จะใช้เทมเพลตตัวอย่างแทน)")
        return generate_mock_rewrite(title, summary, source_name)

    # รายชื่อโมเดลที่จะลองตามลำดับ (หากโมเดลแรกติด 503 คิวยาว จะสลับไปโมเดลถัดไปทันที)
    candidate_models = [
        'gemini-3.8-flash',
        'gemini-3.7-flash',
        'gemini-3.5-flash',
        'gemini-3.5-flash-lite'
    ]

    prompt = f"""
กรุณานำข่าวฟุตบอลลิเวอร์พูลต่อไปนี้ มาเขียนใหม่เป็นภาษาไทยตามสไตล์ที่ได้รับมอบหมายอย่างเคร่งครัด:

[ข่าวต้นฉบับภาษาอังกฤษ]
หัวข้อ: {title}
แหล่งที่มา: {source_name}
เนื้อหา: {summary}

ย้ำกฎเหล็ก: ห้ามพิมพ์หรือเอ่ยชื่อ บอ.บู๋ หรือ บอบู๋ โดยเด็ดขาด 100%!
เขียนออกมาเป็นโพสต์ Facebook พร้อมพาดหัว เนื้อหา ทัศนะคมๆ แฮชแท็ก และเครดิตแหล่งข่าวท้ายโพสต์
"""

    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)

        for model_name in candidate_models:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={
                        'system_instruction': AI_SYSTEM_INSTRUCTION.replace("{source_name}", source_name),
                        'temperature': 0.8,
                    }
                )
                if response and response.text:
                    rewritten_text = response.text.strip()
                    # กรองคำต้องห้ามรอบสุดท้ายเพื่อความปลอดภัย 100%
                    return sanitize_forbidden_words(rewritten_text)
            except Exception as em:
                print(f"⚠️ โมเดล {model_name} ใช้งานไม่ได้ ({str(em)[:60]}...), กำลังสลับไปโมเดลถัดไป...")
                continue

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการเชื่อมต่อ SDK: {e}")

    # หากทุกโมเดลล้มเหลว ใช้เทมเพลตสำรองเพื่อไม่ให้ข่าวว่าง
    print("⚠️ ทุกโมเดลไม่ตอบสนอง ใช้เทมเพลตสำรองชั่วคราว")
    return generate_mock_rewrite(title, summary, source_name)

def generate_mock_rewrite(title: str, summary: str, source_name: str) -> str:
    """ฟังก์ชันจำลองสำหรับทดสอบระบบเมื่อยังไม่ได้ใส่ Gemini API Key"""
    text = f"""🔥 แหม่... พ่อคุณรุนช่อง! เอาอีกแล้วครับท่าน!

ว่าด้วยเรื่องประเด็นร้อนล่าสุดของทัพ "หงส์แดง" ลิเวอร์พูล เมื่อมีรายงานข่าวสดๆ ร้อนๆ เกี่ยวกับ "{title}" 

ปัดโธ่เอ๊ย... ดูทรงแล้วงานนี้คงมีเรื่องให้แฟนบอลได้วิจารณ์กันขรม เนื้อหาเขาบอกมาว่า {summary[:200]}... ซึ่งถ้าเป็นแบบนั้นจริง บอกเลยว่าสนุกแน่ขอรับกระผม!

เอาเป็นว่ารอดูกันต่อไป อย่าเพิ่งรีบด่วนสรุป เอาที่สบายใจกันเลย แต่ที่แน่ๆ สนามแอนฟิลด์ลุกเป็นไฟแน่นอน! 🔴

#ลิเวอร์พูล #หงส์แดง #พรีเมียร์ลีก #LFC #เด็กหงส์
📰 แหล่งที่มา: {source_name}
"""
    return sanitize_forbidden_words(text)

def rewrite_article(article: Dict) -> Optional[str]:
    """รับข้อมูลข่าวและส่งไปเขียนใหม่"""
    title = article.get("title", "")
    summary = article.get("summary", "")
    source = article.get("source", "ต่างประเทศ")

    try:
        print(f"[AI Rewriter] กำลังเรียบเรียงข่าว: '{title[:45]}...'")
    except Exception:
        pass

    rewritten = rewrite_with_gemini(title, summary, source)
    
    # ดับเบิ้ลเช็คอีกครั้ง
    if rewritten:
        rewritten = sanitize_forbidden_words(rewritten)
    return rewritten
