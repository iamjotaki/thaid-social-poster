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
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        sanitized = pattern.sub("", sanitized)
    
    sanitized = re.sub(r' +', ' ', sanitized)
    return sanitized.strip()

def detect_article_category(title: str, summary: str = "", source_name: str = "") -> str:
    """
    ตรวจจับหมวดหมู่ของข่าวจากหัวข้อ เนื้อหา และแหล่งที่มา
    ส่งคืน: 'tech' | 'biz' | 'sports' | 'general'
    """
    text = f"{title} {summary} {source_name}".lower()

    # Sports
    sports_kw = [
        'football', 'soccer', 'premier league', 'liverpool', 'chelsea', 'arsenal',
        'manchester', 'real madrid', 'barcelona', 'bayern', 'fifa', 'uefa', 'nba',
        'tennis', 'formula 1', 'f1', 'champions league', 'laliga', 'serie a', 'bundesliga',
        'striker', 'midfielder', 'winger', 'goalkeeper', 'anfield', 'klopp', 'slot'
    ]
    if any(k in text for k in sports_kw):
        return 'sports'

    # Tech / AI
    tech_kw = [
        'ai', 'artificial intelligence', 'semiconductor', 'chip', 'tech', 'technology',
        'software', 'nvidia', 'openai', 'gemini', 'chatgpt', 'google', 'apple',
        'microsoft', 'meta', 'robot', 'robotics', 'cyber', 'gadget', 'algorithm',
        'machine learning', 'cloud computing', 'quantum', 'smartphone', 'hardware'
    ]
    if any(k in text for k in tech_kw):
        return 'tech'

    # Business / Finance
    biz_kw = [
        'stock', 'stocks', 'market', 'business', 'economy', 'invest', 'investing',
        'shares', 'finance', 'dollar', 'crypto', 'cryptocurrency', 'bitcoin', 'fund',
        'bank', 'banking', 'earnings', 'revenue', 'wall street', 'nasdaq', 's&p 500',
        'inflation', 'fed', 'interest rate', 'acquisition', 'merger'
    ]
    if any(k in text for k in biz_kw):
        return 'biz'

    return 'general'

def get_niche_system_instruction(category: str, source_name: str) -> str:
    """สร้าง System Instruction ที่ตรงกับหมวดหมู่ข่าวอย่างแท้จริง"""
    if category == 'sports':
        return AI_SYSTEM_INSTRUCTION.replace("{source_name}", source_name)
    elif category == 'tech':
        return f"""คุณคือนักเขียนและครีเอเตอร์สายไอที & นวัตกรรม (Tech Influencer) ระดับท็อป
- แปลและเรียบเรียงข่าวเทคโนโลยีและ AI จากภาษาอังกฤษเป็นภาษาไทยให้น่าสนใจ เข้าใจง่าย ทันสมัย
- ชี้ให้เห็นว่าเทคโนโลยีหรือข่าวนั้นส่งผลกระทบหรือมีประโยชน์อย่างไร
- ใช้ภาษาเป็นกันเอง คมชัด ทรงพลัง จัดย่อหน้าให้อ่านง่าย มีอีโมจิประกอบ
- ห้ามนำเรื่องฟุตบอลหรือทีมกีฬามาปะปนกับข่าวเทคโนโลยีโดยเด็ดขาด 100%
- ใช้แฮชแท็กที่ตรงกับเนื้อหา เช่น #เทคโนโลยี #AI #นวัตกรรม #ปัญญาประดิษฐ์ #TechNews
- ระบุเครดิต: 📌 ที่มา: {source_name}"""
    elif category == 'biz':
        return f"""คุณคือนักวิเคราะห์ข่าวเศรษฐกิจ ธุรกิจ และการเงินมืออาชีพ
- แปลและสรุปข่าวธุรกิจ หุ้น และการลงทุนจากภาษาอังกฤษเป็นภาษาไทยอย่างกระชับ ฉับไว คมชัด
- สรุปตัวเลข สาระสำคัญ และผลกระทบต่อตลาดหรือนักลงทุน
- จัดรูปแบบให้อ่านง่าย มีหัวข้อย่อยและเว้นวรรคชัดเจน
- ห้ามนำเรื่องฟุตบอลมาปะปนกับข่าวธุรกิจโดยเด็ดขาด 100%
- ใช้แฮชแท็ก เช่น #ธุรกิจ #การเงิน #หุ้นต่างประเทศ #เศรษฐกิจโลก #การลงทุน
- ระบุเครดิต: 📌 ที่มา: {source_name}"""
    else:
        return f"""คุณคือนักสื่อสารมวลชนและคอนเทนต์ครีเอเตอร์เพจ Facebook มืออาชีพ
- แปลและเล่าข่าวสถานการณ์ต่างประเทศเป็นภาษาไทยให้อ่านสนุก น่าติดตาม มีสาระ
- จัดรูปแบบ 3-4 ย่อหน้าให้อ่านง่ายบนมือถือ
- สรุปใจความสำคัญและชวนผู้อ่านแลกเปลี่ยนความคิดเห็น
- ใช้แฮชแท็กที่ตรงกับเนื้อหาข่าว
- ระบุเครดิต: 📌 ที่มา: {source_name}"""

def get_active_api_key(passed_key: str = None) -> Optional[str]:
    """ค้นหา Gemini API Key ที่ใช้งานได้จริงจากหลายแหล่ง"""
    if passed_key and passed_key.strip() and passed_key != "your_gemini_api_key_here":
        return passed_key.strip()

    # 1. ลองดึงจากฐานข้อมูล user_api_keys
    try:
        from database import get_connection
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT api_key FROM user_api_keys 
                WHERE is_active = 1 AND api_key != 'your_gemini_api_key_here' AND LENGTH(api_key) > 15
                ORDER BY id ASC LIMIT 1
            """)
            row = cursor.fetchone()
            if row and row[0]:
                return row[0].strip()
    except Exception:
        pass

    # 2. ลองดึงจาก GEMINI_API_KEY ใน config/.env
    if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here" and len(GEMINI_API_KEY) > 15:
        return GEMINI_API_KEY

    return None

def generate_mock_rewrite(title: str, summary: str, source_name: str) -> str:
    """ฟังก์ชันจำลองอัจฉริยะ ปรับตามหมวดหมู่อัตโนมัติเมื่อยังไม่มี Gemini API Key หรือเกิดข้อผิดพลาด"""
    category = detect_article_category(title, summary, source_name)
    clean_summary = summary.strip() if summary else ""
    # กำจัดแท็กหรือรายชื่อสำนักข่าวที่ติดมาจาก Google News RSS
    clean_summary = re.sub(r'<\/?(ol|li|font|a|b|i)[^>]*>', ' ', clean_summary)
    clean_summary = re.sub(r'\b(Bloomberg|Ars Technica|Deadline|Yahoo Finance|The New York Times|Reuters|Associated Press|Forbes|TechCrunch|Engadget|The Verge|MacRumors)\b(\.com)?', '', clean_summary, flags=re.IGNORECASE)
    clean_summary = re.sub(r'\s+', ' ', clean_summary).strip()
    if not clean_summary or len(clean_summary) < 20:
        clean_summary = f"รายงานความเคลื่อนไหวล่าสุดเกี่ยวกับ '{title}' ซึ่งกำลังเป็นประเด็นน่าจับตามองในระดับสากลขณะนี้"

    if category == 'tech':
        text = f"""💡 เกาะติดกระแสเทคโนโลยี & AI ระดับโลก! 🚀

เปิดประเด็นร้อนน่าจับตา: "{title}"

{clean_summary}...

ถือเป็นอีกหนึ่งก้าวสำคัญของวงการเทคโนโลยีที่น่าติดตามอย่างยิ่ง ว่านวัตกรรมและทิศทางนี้จะเข้ามาเปลี่ยนโฉมหน้าของอุตสาหกรรม และส่งผลกระทบต่อผู้ใช้งานทั่วโลกอย่างไรต่อไป!

คุณคิดเห็นอย่างไรกับเรื่องนี้ มาร่วมพูดคุยกันได้ในคอมเมนต์เลยครับ 👇

#เทคโนโลยี #AI #นวัตกรรม #ปัญญาประดิษฐ์ #TechNews
📰 แหล่งที่มา: {source_name}"""

    elif category == 'biz':
        text = f"""📈 สรุปสถานการณ์ธุรกิจ & การเงินโลก 💼

รายงานประเด็นเด่น: "{title}"

{clean_summary}...

ความเคลื่อนไหวในครั้งนี้กำลังเป็นที่จับตาของนักลงทุนและตลาดอย่างใกล้ชิด เพราะอาจส่งผลต่อทิศทางเศรษฐกิจและโอกาสทางธุรกิจในอนาคต!

ชาวเพจคิดว่าทิศทางหลังจากนี้จะเป็นอย่างไรบ้าง คอมเมนต์แลกเปลี่ยนมุมมองกันได้ครับ 👇

#ธุรกิจ #การเงิน #เศรษฐกิจโลก #การลงทุน #หุ้นต่างประเทศ
📰 แหล่งที่มา: {source_name}"""

    elif category == 'sports':
        text = f"""🔥 ประเด็นร้อนวงการลูกหนัง! จัดจ้านตามสไตล์คอลัมนิสต์เก๋า!

เจาะลึกข่าวล่าสุด: "{title}"

{clean_summary}...

งานนี้บอกเลยว่ามีเรื่องให้แฟนบอลได้พูดคุยวิจารณ์กันสนั่นแน่นอน รอดูกันต่อไปว่าผลลัพธ์จะออกมาทิศทางไหน! ⚽

แฟนบอลมีความเห็นอย่างไรกับประเด็นนี้ คอมเมนต์กันมาได้เลย! 👇

#ข่าวกีฬา #ฟุตบอล #พรีเมียร์ลีก #ข่าวบอล
📰 แหล่งที่มา: {source_name}"""

    else:
        text = f"""🌐 เกาะติดสถานการณ์สำคัญรอบโลก 📌

รายงานข่าวเด่นล่าสุด: "{title}"

{clean_summary}...

ความคืบหน้าของสถานการณ์นี้จะเป็นอย่างไรต่อไป ติดตามการอัปเดตแบบเจาะลึกได้ที่นี่ครับ

ผู้อ่านมองประเด็นนี้อย่างไร มาร่วมแสดงความคิดเห็นกันได้ครับ 👇

#ข่าวรอบโลก #สถานการณ์โลก #ข่าวเด่น #สาระความรู้
📰 แหล่งที่มา: {source_name}"""

    return sanitize_forbidden_words(text)

def rewrite_with_gemini(title: str, summary: str, source_name: str, api_key: str = None) -> Optional[str]:
    """ใช้ Google Gemini API เขียนข่าวใหม่ตามสไตล์ที่กำหนด พร้อมระบบ Fallback หลายโมเดล"""
    active_key = get_active_api_key(api_key)
    category = detect_article_category(title, summary, source_name)

    if not active_key:
        print(f"⚠️ ยังไม่ได้ตั้งค่า GEMINI_API_KEY (ใช้เทมเพลตตัวอย่างหมวด {category} แทน)")
        return generate_mock_rewrite(title, summary, source_name)

    # รายชื่อโมเดลที่จะลองตามลำดับ
    candidate_models = [
        'gemini-3.5-flash',
        'gemini-3.5-flash-lite',
        'gemini-3.8-flash',
        'gemini-flash-latest',
        'gemini-2.5-flash'
    ]

    system_instruction = get_niche_system_instruction(category, source_name)

    prompt = f"""
คุณคือนักเขียนโพสต์ Facebook มืออาชีพระดับท็อป กรุณานำเนื้อหาข่าวต้นฉบับภาษาอังกฤษต่อไปนี้ มาเขียนเรียบเรียงใหม่เป็นภาษาไทยให้น่าสนใจ น่าอ่าน ดึงดูดสายตา และสร้างยอดการมีส่วนร่วม (Engagement) สูงสุด:

[เนื้อหาต้นฉบับภาษาอังกฤษ]
หัวข้อ: {title}
แหล่งที่มา: {source_name}
เนื้อหา: {summary}

หมวดหมู่ตรวจพบ: {category}

กฎเหล็กสำคัญที่สุด (CRITICAL RULES):
1. เขียนเนื้อหาให้ครบถ้วนสมบูรณ์ มีรายละเอียดและสาระแน่น 3-5 ย่อหน้า (อธิบายความเป็นมา รายละเอียดการเปลี่ยนแปลง และผลกระทบต่อผู้ใช้งานหรืออุตสาหกรรม)
2. *** ห้ามเขียนเป็นเพียงแค่รายชื่อสำนักข่าวเด็ดขาด เช่น 1. Bloomberg 2. Deadline *** ให้เน้นเนื้อหาของตัวข่าวจริงๆ เท่านั้น
3. จัดวรรคตอนให้อ่านสบายตาบนสมาร์ทโฟน สอดแทรกอีโมจิที่เข้ากับเนื้อหาอย่างมีระดับ
4. ปิดท้ายด้วยประเด็นหรือคำถามชวนผู้อ่านแสดงความคิดเห็นเพื่อสร้าง Engagement
5. ติดแฮชแท็ก 3-5 อันที่ตรงกับเนื้อหาข่าว
6. ระบุเครดิตแหล่งข่าวท้ายโพสต์: 📌 ที่มา: {source_name}
"""

    try:
        from google import genai
        client = genai.Client(api_key=active_key)

        for model_name in candidate_models:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={
                        'system_instruction': system_instruction,
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

    # หากทุกโมเดลล้มเหลว ใช้เทมเพลตสำรองเฉพาะหมวด
    print(f"⚠️ ทุกโมเดลไม่ตอบสนอง ใช้เทมเพลตสำรองหมวด {category}")
    return generate_mock_rewrite(title, summary, source_name)

def rewrite_article(article: Dict, api_key: str = None) -> Optional[str]:
    """รับข้อมูลข่าวและส่งไปเขียนใหม่"""
    title = article.get("title", "")
    summary = article.get("summary", "")
    source = article.get("source", "ต่างประเทศ")

    try:
        print(f"[AI Rewriter] กำลังเรียบเรียงข่าว: '{title[:45]}...'")
    except Exception:
        pass

    rewritten = rewrite_with_gemini(title, summary, source, api_key=api_key)
    
    # ดับเบิ้ลเช็คอีกครั้ง
    if rewritten:
        rewritten = sanitize_forbidden_words(rewritten)
    return rewritten
