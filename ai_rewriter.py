import os
import sys
import re
from typing import Optional, Dict, Tuple

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
    ตรวจจับหมวดหมู่เนื้อหาอย่างแม่นยำด้วย Word-Boundary Regex
    ป้องกันบั๊ก 'ai' ในคำว่า remains, mountain, said, claim
    ส่งคืน: 'mystery' | 'history' | 'nature' | 'health' | 'tech' | 'biz' | 'sports' | 'general'
    """
    text = f"{title} {summary} {source_name}".lower()

    # 1. Mystery, Paranormal, True Crime, Cold Cases
    mystery_patterns = [
        r'\b(mystery|mysteries|mysterious|unsolved|unresolved|disappearance|disappeared|missing person|missing people)\b',
        r'\b(homicide|murder|murdered|murderer|dismemberment|crime|investigation|investigators|cold case|cold cases)\b',
        r'\b(remains|skeletal|skeleton|corpse|autopsy|forensic|forensics|grave|buried)\b',
        r'\b(paranormal|ufo|ufos|uap|alien|aliens|cryptid|cryptids|cryptozoology|bigfoot|sasquatch|loch ness)\b',
        r'\b(ghost|ghosts|haunted|haunting|supernatural|conspiracy|bizarre|unexplained creature|creatures|monster|monsters)\b',
        r'\b(abduction|abducted|crime scene|suspect|suspects|serial killer)\b'
    ]
    if any(re.search(pat, text) for pat in mystery_patterns):
        return 'mystery'

    # 2. History, Archaeology, Ancient Civilizations
    history_patterns = [
        r'\b(ancient|archaeology|archaeological|archaeologist|archaeologists|excavation|excavated)\b',
        r'\b(tomb|tombs|pharaoh|pharaohs|pyramid|pyramids|civilization|civilizations|artifact|artifacts|relic|relics)\b',
        r'\b(dynasty|fossil|fossils|ruins|empire|medieval|mythology|mythological|origins|historical|centuries ago)\b',
        r'\b(neolithic|bronze age|stone age|iron age|gladiator|roman empire|ancient egypt|ancient greece|mesopotamia)\b'
    ]
    if any(re.search(pat, text) for pat in history_patterns):
        return 'history'

    # 3. Nature, Animals, Wildlife, Space & Astronomy
    nature_patterns = [
        r'\b(wildlife|animal|animals|species|fauna|flora|mammal|mammals|reptile|reptiles|predator)\b',
        r'\b(ocean|oceans|marine|deep sea|coral reef|shark|sharks|whale|whales|dolphin)\b',
        r'\b(space|nasa|astronomy|astronomer|astronomers|galaxy|galaxies|planet|planets|telescope|universe|asteroid|black hole)\b',
        r'\b(earthquake|volcano|ecosystem|rainforest|biodiversity)\b'
    ]
    if any(re.search(pat, text) for pat in nature_patterns):
        return 'nature'

    # 4. Health, Medicine, Psychology, Wellness
    health_patterns = [
        r'\b(health|wellness|mental health|psychology|psychologist|brain|neuroscience)\b',
        r'\b(nutrition|diet|fitness|exercise|sleep|longevity|disease|cancer|medicine|medical|hospital|therapy)\b'
    ]
    if any(re.search(pat, text) for pat in health_patterns):
        return 'health'

    # 5. Sports
    sports_patterns = [
        r'\b(football|soccer|premier league|liverpool|chelsea|arsenal|manchester|real madrid|barcelona|bayern)\b',
        r'\b(fifa|uefa|nba|tennis|formula 1|f1|champions league|laliga|serie a|bundesliga)\b',
        r'\b(striker|midfielder|winger|goalkeeper|anfield|klopp|slot|head coach|transfers|matchday)\b'
    ]
    if any(re.search(pat, text) for pat in sports_patterns):
        return 'sports'

    # 6. Tech / AI (Strict Word Boundaries only!)
    tech_patterns = [
        r'\b(ai|artificial intelligence|generative ai|llm|llms|chatgpt|openai|gemini|deepmind|deepseek|claude|copilot)\b',
        r'\b(semiconductor|semiconductors|chip|chips|nvidia|gpu|gpus|software|hardware|algorithm|algorithms)\b',
        r'\b(robot|robots|robotics|cybersecurity|cyber|cloud computing|quantum computing|smartphone|smartphones)\b',
        r'\b(tech|technology|technologies|gadget|gadgets|metaverse)\b'
    ]
    if any(re.search(pat, text) for pat in tech_patterns):
        return 'tech'

    # 7. Business & Finance
    biz_patterns = [
        r'\b(stock|stocks|stock market|cryptocurrency|crypto|bitcoin|btc|ethereum|eth|finance|financial)\b',
        r'\b(wall street|nasdaq|s&p 500|inflation|interest rate|federal reserve|fed|central bank)\b',
        r'\b(quarterly revenue|earnings|market cap|venture capital|investment|investing|investor|investors|acquisition|merger|ipo)\b'
    ]
    if any(re.search(pat, text) for pat in biz_patterns):
        return 'biz'

    return 'general'

def get_card_category_and_theme(cat_type: str, p_name: str = "", title_source: str = "") -> Tuple[str, str]:
    """แปลงประเภทบทความเป็นชื่อหมวดบนการ์ดและธีมสีที่เหมาะสม"""
    if cat_type == "mystery":
        return "เรื่องลึกลับ & ปริศนา", "mystery"
    elif cat_type == "history":
        return "ประวัติศาสตร์ & โบราณคดี", "history"
    elif cat_type == "nature":
        return "ธรรมชาติ & วิทยาศาสตร์", "nature"
    elif cat_type == "health":
        return "สุขภาพ & จิตวิทยา", "health"
    elif cat_type == "tech":
        return "เทคโนโลยี & AI", "tech"
    elif cat_type == "biz":
        return "ธุรกิจ & การเงิน", "biz"
    elif cat_type == "sports":
        theme = "lfc" if "หงส์" in p_name or "liverpool" in title_source.lower() else "sports"
        return "ข่าวกีฬา", theme
    else:
        return "เรื่องน่ารู้รอบโลก", "breaking"

def get_niche_system_instruction(category: str, source_name: str) -> str:
    """สร้าง System Instruction ที่ตรงกับหมวดหมู่และสไตล์การเล่าเรื่องอย่างแท้จริง"""
    if category == 'mystery':
        return f"""คุณคือนักเล่าเรื่องคดีปริศนา เรื่องลี้ลับ และคดีดังระดับโลก (Master Storyteller & True Crime Narrator)
- ภารกิจหลัก: นำ 'เรื่องราวและข้อเท็จจริงจริง' จากบทความต้นฉบับ มาเล่าเป็นภาษาไทยให้อ่านสนุก ตื่นเต้น น่าติดตาม ดึงดูดอารมณ์ผู้อ่านเหมือนฟังสารคดีสืบสวนชั้นนำ
- เล่าลำดับเหตุการณ์จริง: เปิดปมปริศนา ใครหายตัวไปหรือเกิดเหตุอะไรขึ้นที่ไหน รายละเอียดเบาะแส และความคืบหน้าการค้นพบหลักฐานล่าสุด
- สรุปทฤษฎี ข้อสันนิษฐาน หรือประเด็นที่ยังคลุมเครือ เพื่อให้ผู้อ่านได้ร่วมคิดวิเคราะห์
- ใช้ภาษาไทยที่เข้าใจง่าย ลื่นไหล บรรยายเห็นภาพ ไม่แปลเป็นภาษาหุ่นยนต์
- ห้ามนำเรื่องเทคโนโลยี AI หรือเรื่องอื่นที่ไม่เกี่ยวกับตัวคดีมาแต่งเติมเด็ดขาด 100%
- แฮชแท็ก: #เรื่องลึกลับ #คดีปริศนา #เรื่องจริง #สืบสวน #คดีดัง #ลี้ลับ
- ระบุเครดิตท้ายโพสต์: 📌 ที่มา: {source_name}"""

    elif category == 'history':
        return f"""คุณคือนักเล่าเรื่องประวัติศาสตร์ โบราณคดี และอารยธรรมโบราณรอบโลก (History & Archaeology Narrator)
- ภารกิจหลัก: นำ 'เรื่องราวและข้อเท็จจริงจริง' จากการค้นพบทางประวัติศาสตร์หรือโบราณคดี มาเล่าเป็นภาษาไทยให้อ่านสนุก ได้ความรู้ ชวนตื่นตาตื่นใจ พาย้อนเวลาไปสัมผัสอดีต
- เล่าที่มาว่าสิ่งที่ถูกค้นพบคืออะไร มีอายุเก่าแก่แค่ไหน มีความสำคัญอย่างไร และเปลี่ยนความเข้าใจเกี่ยวกับประวัติศาสตร์มนุษย์อย่างไร
- ใช้ภาษาไทยที่สละสลวย ชัดเจน เข้าใจง่าย มีชีวิตชีวา
- ห้ามนำเรื่องเทคโนโลยี AI หรือข่าวเศรษฐกิจมาปนเด็ดขาด 100%
- แฮชแท็ก: #ประวัติศาสตร์ #โบราณคดี #อารยธรรมโบราณ #เรื่องน่ารู้ #ประวัติศาสตร์โลก
- ระบุเครดิตท้ายโพสต์: 📌 ที่มา: {source_name}"""

    elif category == 'nature':
        return f"""คุณคือนักสื่อสารวิทยาศาสตร์ ธรรมชาติ สัตว์โลก และอวกาศ (Science & Nature Explorer)
- ภารกิจหลัก: นำ 'เรื่องราวมหัศจรรย์และข้อเท็จจริงจริง' ของสัตว์โลก ธรรมชาติ ท้องทะเล หรือจักรวาล มาเล่าเป็นภาษาไทยให้อ่านเพลิน น่าทึ่ง เข้าใจง่าย
- ถ่ายทอดความมหัศจรรย์ พฤติกรรม หรือข้อค้นพบใหม่ๆ ให้เห็นภาพชัดเจน
- ใช้ภาษาที่เป็นกันเอง ชวนค้นหา ตื่นเต้น
- แฮชแท็ก: #ธรรมชาติ #สัตว์โลก #วิทยาศาสตร์ #เรื่องน่ารู้ #อวกาศ
- ระบุเครดิตท้ายโพสต์: 📌 ที่มา: {source_name}"""

    elif category == 'health':
        return f"""คุณคือคอนเทนต์ครีเอเตอร์สายสุขภาพ จิตวิทยา และการพัฒนาตัวเอง (Health & Psychology Writer)
- ภารกิจหลัก: แปลและสรุปสาระสำคัญ ข้อเท็จจริง หรือผลการวิจัย ให้เป็นภาษาไทยที่เข้าใจง่าย นำไปปรับใช้ได้จริงในชีวิต
- จัดรูปแบบกระชับ มีหัวข้อย่อยชัดเจน
- แฮชแท็ก: #สุขภาพ #จิตวิทยา #พัฒนาตัวเอง #สาระสุขภาพ #ชีวิตดีขึ้น
- ระบุเครดิตท้ายโพสต์: 📌 ที่มา: {source_name}"""

    elif category == 'sports':
        return AI_SYSTEM_INSTRUCTION.replace("{source_name}", source_name)

    elif category == 'tech':
        return f"""คุณคือนักเขียนและครีเอเตอร์สายไอที & นวัตกรรม (Tech Influencer) ระดับท็อป
- แปลและเรียบเรียงข้อมูลเทคโนโลยี ซอฟต์แวร์ และ AI จากภาษาอังกฤษเป็นภาษาไทยให้น่าสนใจ เข้าใจง่าย ทันสมัย
- ชี้ให้เห็นว่านวัตกรรมนั้นทำงานอย่างไร และส่งผลกระทบหรือมีประโยชน์ต่อผู้ใช้งานอย่างไร
- ใช้ภาษาเป็นกันเอง คมชัด ทรงพลัง จัดย่อหน้าให้อ่านง่าย มีอีโมจิประกอบ
- ห้ามนำเรื่องกีฬาหรือเรื่องอื่นที่ไม่เกี่ยวข้องมาปะปนเด็ดขาด 100%
- ใช้แฮชแท็กที่ตรงกับเนื้อหา เช่น #เทคโนโลยี #AI #นวัตกรรม #ปัญญาประดิษฐ์ #TechNews
- ระบุเครดิต: 📌 ที่มา: {source_name}"""

    elif category == 'biz':
        return f"""คุณคือนักวิเคราะห์ข่าวเศรษฐกิจ ธุรกิจ และการเงินมืออาชีพ
- แปลและสรุปข่าวธุรกิจ หุ้น และการลงทุนจากภาษาอังกฤษเป็นภาษาไทยอย่างกระชับ ฉับไว คมชัด
- สรุปตัวเลข สาระสำคัญ และผลกระทบต่อตลาดหรือนักลงทุน
- จัดรูปแบบให้อ่านง่าย มีหัวข้อย่อยและเว้นวรรคชัดเจน
- ห้ามนำเรื่องกีฬาหรือเรื่องที่ไม่เกี่ยวข้องมาปะปนเด็ดขาด 100%
- ใช้แฮชแท็ก เช่น #ธุรกิจ #การเงิน #หุ้นต่างประเทศ #เศรษฐกิจโลก #การลงทุน
- ระบุเครดิต: 📌 ที่มา: {source_name}"""

    else:
        return f"""คุณคือนักเล่าเรื่องและคอนเทนต์ครีเอเตอร์เพจ Facebook มืออาชีพ (Master Storyteller & Creator)
- ภารกิจหลัก: นำ 'เรื่องราวและข้อเท็จจริงจริง' จากเนื้อหาต้นฉบับ มาเรียบเรียงเล่าเป็นภาษาไทยให้อ่านสนุก น่าติดตาม ได้สาระ เข้าใจง่าย
- ถ่ายทอดลำดับเหตุการณ์อย่างมีชีวิตชีวา จัดย่อหน้าให้อ่านสบายตาบนสมาร์ทโฟน
- สรุปประเด็นชวนผู้อ่านแลกเปลี่ยนความคิดเห็น
- ใช้แฮชแท็กที่ตรงกับเนื้อหาจริงของเรื่อง (ไม่ติดแฮชแท็กมั่ว)
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

def _fallback_thai_headline(fallback_title: str, category: str) -> str:
    """สร้างพาดหัวภาษาไทยสำรองเมื่อไม่มีพาดหัว เพื่อไม่ให้การ์ดแสดงภาษาอังกฤษล้วน"""
    clean_en = re.sub(r'\s*-\s*[A-Za-z0-9\s.]+$', '', fallback_title).strip() if fallback_title else ""
    if category == 'mystery':
        return "เปิดแฟ้มคดีปริศนาสะเทือนขวัญ ปมลี้ลับที่ทุกคนยังรอคำตอบ"
    elif category == 'history':
        return "ค้นพบหลักฐานโบราณคดีชิ้นประวัติศาสตร์ พลิกโฉมอารยธรรมโลก"
    elif category == 'nature':
        return "เปิดความมหัศจรรย์ของธรรมชาติและสัตว์โลก เรื่องน่าทึ่งรอบตัวเรา"
    elif category == 'health':
        return "สาระน่ารู้เพื่อสุขภาพและจิตวิทยา เคล็ดลับเปลี่ยนชีวิตให้ดีขึ้น"
    elif category == 'tech':
        return "เปิดตัวยิ่งใหญ่! นวัตกรรมเทคโนโลยีและ AI ตัวใหม่ สั่นสะเทือนวงการ"
    elif category == 'biz':
        return "จับตาความเคลื่อนไหวธุรกิจและการเงินโลก ส่อเค้ากระทบตลาดทุน"
    elif category == 'sports':
        return "ประเด็นร้อนวงการลูกหนัง ดราม่าเดือดสะเทือนลีกใหญ่"
    else:
        return "เรื่องจริงน่ารู้รอบโลก ประเด็นร้อนที่ทุกคนกำลังให้ความสนใจ"

def extract_thai_card_headline(rewritten_text: str, fallback_title: str = "", category: str = "general") -> str:
    """
    ดึงพาดหัวภาษาไทยที่กระชับ โดนใจ สำหรับใส่ในรูปภาพ Social Card
    รับประกันว่าจะเป็นภาษาไทยเสมอ ไม่เอาภาษาอังกฤษล้วน
    """
    if not rewritten_text:
        return _fallback_thai_headline(fallback_title, category)

    # 1. ค้นหาจากแท็กเฉพาะ [HEADLINE_TH]...[END_HEADLINE]
    match = re.search(r'\[HEADLINE_TH\](.*?)\[END_HEADLINE\]', rewritten_text, re.DOTALL | re.IGNORECASE)
    if match:
        hl = match.group(1).strip()
        hl = sanitize_forbidden_words(hl)
        hl = re.sub(r'[*#"`]', '', hl).strip()
        thai_count = len(re.findall(r'[\u0E00-\u0E7F]', hl))
        if thai_count >= 5 and len(hl) >= 10:
            return hl

    # 2. ค้นหาจากบรรทัดแรกๆ ที่เป็นภาษาไทย
    lines = [l.strip() for l in rewritten_text.split("\n") if l.strip()]
    for line in lines:
        clean_l = re.sub(r'\[\/?HEADLINE_TH\]', '', line, flags=re.IGNORECASE)
        clean_l = re.sub(r'\[\/?END_HEADLINE\]', '', clean_l, flags=re.IGNORECASE)
        clean_l = re.sub(r'[*#"`]', '', clean_l).strip()

        # ข้ามบรรทัดที่เป็นเครดิตหรือแฮชแท็ก
        if clean_l.startswith(('#', '📌', 'ที่มา', 'แหล่งที่มา', 'Credit', 'ข่าวด่วน')):
            continue

        thai_chars = len(re.findall(r'[\u0E00-\u0E7F]', clean_l))
        if thai_chars >= 8 and 15 <= len(clean_l) <= 95:
            return clean_l

    # 3. ถ้าไม่มีบรรทัดที่เข้าเกณฑ์ ให้ใช้พาดหัวภาษาไทยสำรอง
    return _fallback_thai_headline(fallback_title, category)

def clean_post_for_facebook(rewritten_text: str, category: str = "general") -> str:
    """ทำความสะอาดเนื้อหาโพสต์ก่อนส่งขึ้น Facebook เพื่อให้แสดงผลอย่างมืออาชีพ"""
    if not rewritten_text:
        return ""

    lead_emoji = {
        "mystery": "🔍",
        "history": "🏛️",
        "nature": "🌿",
        "health": "💡",
        "tech": "⚡",
        "biz": "📈",
        "sports": "⚽",
    }.get(category, "📌")

    match = re.search(r'\[HEADLINE_TH\](.*?)\[END_HEADLINE\]', rewritten_text, re.DOTALL | re.IGNORECASE)
    if match:
        hl = match.group(1).strip()
        body = re.sub(r'\[HEADLINE_TH\].*?\[END_HEADLINE\]', '', rewritten_text, flags=re.DOTALL | re.IGNORECASE).strip()
        cleaned = f"{lead_emoji} {hl}\n\n{body}"
    else:
        cleaned = rewritten_text

    cleaned = re.sub(r'\[\/?HEADLINE_TH\]', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\[\/?END_HEADLINE\]', '', cleaned, flags=re.IGNORECASE)
    return cleaned.strip()

def generate_mock_rewrite(title: str, summary: str, source_name: str) -> str:
    """ฟังก์ชันจำลองอัจฉริยะ ปรับตามหมวดหมู่อัตโนมัติเมื่อยังไม่มี Gemini API Key หรือเกิดข้อผิดพลาด"""
    category = detect_article_category(title, summary, source_name)
    clean_summary = summary.strip() if summary else ""
    clean_summary = re.sub(r'<\/?(ol|li|font|a|b|i)[^>]*>', ' ', clean_summary)
    clean_summary = re.sub(r'\b(Bloomberg|Ars Technica|Deadline|Yahoo Finance|The New York Times|Reuters|Associated Press|Forbes|TechCrunch|Engadget|The Verge|MacRumors)\b(\.com)?', '', clean_summary, flags=re.IGNORECASE)
    clean_summary = re.sub(r'\s+', ' ', clean_summary).strip()
    if not clean_summary or len(clean_summary) < 20:
        clean_summary = f"เรื่องราวและข้อเท็จจริงล่าสุดเกี่ยวกับ '{title}' ซึ่งกำลังเป็นประเด็นน่าติดตามในระดับสากลขณะนี้"

    if category == 'mystery':
        headline = "เปิดแฟ้มคดีปริศนาชวนฉงน ปมลี้ลับที่โลกยังตามหาคำตอบ!"
        text = f"""[HEADLINE_TH]
{headline}
[END_HEADLINE]

🔍 ย้อนรอยเรื่องราวสุดลี้ลับและคดีปริศนาชวนติดตาม! 

ประเด็นที่น่าจับตา: "{title}"

{clean_summary}...

เรื่องราวนี้ยังคงทิ้งปมและคำถามไว้มากมายให้ผู้คนได้ร่วมค้นหาความจริง คุณคิดเห็นอย่างไรกับเรื่องนี้ มาร่วมแชร์มุมมองกันในคอมเมนต์ได้เลยครับ 👇

#เรื่องลึกลับ #คดีปริศนา #เรื่องจริง #ลี้ลับ #ไขปริศนา
📌 ที่มา: {source_name}"""

    elif category == 'history':
        headline = "ค้นพบหลักฐานโบราณคดีชิ้นเอก พลิกหน้าประวัติศาสตร์โลก!"
        text = f"""[HEADLINE_TH]
{headline}
[END_HEADLINE]

🏛️ สัมผัสเรื่องราวประวัติศาสตร์และอารยธรรมโบราณสุดน่าทึ่ง! 📜

เรื่องราวชิ้นสำคัญ: "{title}"

{clean_summary}...

การค้นพบและหลักฐานชิ้นนี้สะท้อนให้เห็นถึงความมหัศจรรย์ของอดีตที่มนุษยชาติกำลังร่วมกันถอดรหัสต่อไป!

#ประวัติศาสตร์ #โบราณคดี #อารยธรรมโบราณ #เรื่องน่ารู้
📌 ที่มา: {source_name}"""

    elif category == 'nature':
        headline = "เปิดความมหัศจรรย์แห่งธรรมชาติและสัตว์โลก เรื่องน่าทึ่งรอบตัวเรา!"
        text = f"""[HEADLINE_TH]
{headline}
[END_HEADLINE]

🌿 สำรวจโลกมหัศจรรย์ของธรรมชาติและสิ่งมีชีวิต! 🌍

เรื่องราวที่น่าสนใจ: "{title}"

{clean_summary}...

ความหลากหลายทางธรรมชาติและความลับของสิ่งมีชีวิตยังคงสร้างความประหลาดใจให้เราได้เสมอ!

#ธรรมชาติ #สัตว์โลก #วิทยาศาสตร์ #เรื่องน่ารู้
📌 ที่มา: {source_name}"""

    elif category == 'health':
        headline = "สาระน่ารู้เพื่อสุขภาพและจิตวิทยา เคล็ดลับเปลี่ยนชีวิตให้ดีขึ้น!"
        text = f"""[HEADLINE_TH]
{headline}
[END_HEADLINE]

💡 สาระดีๆ เพื่อสุขภาพและจิตวิทยาที่นำไปปรับใช้ได้จริง!

ประเด็นน่ารู้: "{title}"

{clean_summary}...

การดูแลตัวเองในมิติต่างๆ เป็นเรื่องใกล้ตัวที่สร้างความเปลี่ยนแปลงเชิงบวกให้กับชีวิตได้อย่างมหาศาลครับ!

#สุขภาพ #จิตวิทยา #พัฒนาตัวเอง #สาระสุขภาพ
📌 ที่มา: {source_name}"""

    elif category == 'tech':
        headline = "เปิดตัวนวัตกรรมเทคโนโลยี & AI สุดล้ำ สะเทือนวงการระดับโลก!"
        text = f"""[HEADLINE_TH]
{headline}
[END_HEADLINE]

💡 เกาะติดกระแสเทคโนโลยี & AI ระดับโลก! 🚀

เปิดประเด็นร้อนน่าจับตา: "{title}"

{clean_summary}...

ถือเป็นอีกหนึ่งก้าวสำคัญของวงการเทคโนโลยีที่น่าติดตามอย่างยิ่ง ว่านวัตกรรมและทิศทางนี้จะเข้ามาเปลี่ยนโฉมหน้าของอุตสาหกรรม และส่งผลกระทบต่อผู้ใช้งานอย่างไรต่อไป!

#เทคโนโลยี #AI #นวัตกรรม #ปัญญาประดิษฐ์ #TechNews
📌 ที่มา: {source_name}"""

    elif category == 'biz':
        headline = "จับตาสถานการณ์ธุรกิจและการเงินโลก ความเคลื่อนไหวสะเทือนตลาด!"
        text = f"""[HEADLINE_TH]
{headline}
[END_HEADLINE]

📈 สรุปสถานการณ์ธุรกิจ & การเงินโลก 💼

รายงานประเด็นเด่น: "{title}"

{clean_summary}...

ความเคลื่อนไหวในครั้งนี้กำลังเป็นที่จับตาของนักลงทุนและตลาดอย่างใกล้ชิด เพราะอาจส่งผลต่อทิศทางเศรษฐกิจและโอกาสทางธุรกิจในอนาคต!

#ธุรกิจ #การเงิน #เศรษฐกิจโลก #การลงทุน #หุ้นต่างประเทศ
📌 ที่มา: {source_name}"""

    elif category == 'sports':
        headline = "ดราม่าเดือดลูกหนัง! สรุปประเด็นร้อนวงการกีฬาที่แฟนบอลห้ามพลาด"
        text = f"""[HEADLINE_TH]
{headline}
[END_HEADLINE]

🔥 ประเด็นร้อนวงการลูกหนัง! จัดจ้านตามสไตล์คอลัมนิสต์เก๋า!

เจาะลึกเรื่องราวล่าสุด: "{title}"

{clean_summary}...

งานนี้บอกเลยว่ามีเรื่องให้แฟนบอลได้พูดคุยวิจารณ์กันสนั่นแน่นอน รอดูกันต่อไปว่าผลลัพธ์จะออกมาทิศทางไหน! ⚽

#ข่าวกีฬา #ฟุตบอล #พรีเมียร์ลีก #ข่าวบอล
📌 ที่มา: {source_name}"""

    else:
        headline = "เรื่องจริงน่ารู้รอบโลก รายงานความเคลื่อนไหวล่าสุด!"
        text = f"""[HEADLINE_TH]
{headline}
[END_HEADLINE]

🌐 เรื่องจริงและสาระน่ารู้รอบโลก 📌

เรื่องเด่นล่าสุด: "{title}"

{clean_summary}...

เรื่องราวนี้นับว่าเป็นอีกหนึ่งประเด็นที่น่าสนใจและชวนติดตามอย่างยิ่งครับ

#เรื่องน่ารู้ #เรื่องจริง #สาระความรู้ #รอบโลก
📌 ที่มา: {source_name}"""

    return sanitize_forbidden_words(text)

def rewrite_with_gemini(title: str, summary: str, source_name: str, api_key: str = None) -> Optional[str]:
    """ใช้ Google Gemini API เขียนเรื่องราวใหม่ตามแนวทางและสไตล์ของเนื้อหาจริง พร้อมระบบ Fallback หลายโมเดล"""
    active_key = get_active_api_key(api_key)
    category = detect_article_category(title, summary, source_name)

    if not active_key:
        print(f"⚠️ ยังไม่ได้ตั้งค่า GEMINI_API_KEY (ใช้เทมเพลตตัวอย่างหมวด {category} แทน)")
        return generate_mock_rewrite(title, summary, source_name)

    candidate_models = [
        'gemini-3.5-flash-lite',
        'gemini-2.5-flash',
        'gemini-flash-latest',
        'gemini-3.5-flash',
        'gemini-1.5-flash'
    ]

    system_instruction = get_niche_system_instruction(category, source_name)

    prompt = f"""
คุณคือนักเล่าเรื่องและคอนเทนต์ครีเอเตอร์ Facebook ระดับท็อป 
กรุณานำเนื้อหาเรื่องราวต้นฉบับภาษาอังกฤษต่อไปนี้ มาเขียนถ่ายทอดและเรียบเรียงใหม่เป็นภาษาไทยให้อ่านสนุก ดึงดูดสายตา น่าติดตาม และสะท้อนเนื้อเรื่องจริง (Real Story & Facts) อย่างถูกต้องแม่นยำ:

[เนื้อหาต้นฉบับภาษาอังกฤษ]
หัวข้อ: {title}
แหล่งที่มา: {source_name}
เนื้อหา: {summary}

หมวดหมู่ตรวจพบ: {category}

กฎเหล็กสำคัญที่สุด (CRITICAL RULES):
1. ให้ขึ้นต้นผลลัพธ์ด้วยแท็ก [HEADLINE_TH] และ [END_HEADLINE] เสมอ โดยภายในแท็กนี้ให้เขียน "พาดหัวภาษาไทยตัวโตๆ สั้นกระชับ คมคาย ได้ใจความ ชวนติดตาม ความยาว 35-65 ตัวอักษร" สำหรับนำไปพิมพ์ลงบนภาพกราฟิก Social Card (ห้ามมีอีโมจิ ดอกจัน หรือเครื่องหมายคำพูดในบรรทัดพาดหัวนี้เด็ดขาด และต้องเป็นประเด็นที่ตรงกับเนื้อเรื่องจริง ไม่แต่งเติมสิ่งที่ไม่มีในเรื่อง)
2. ถัดจาก [END_HEADLINE] ให้เขียนเนื้อหาโพสต์ Facebook ภาษาไทยอย่างสมบูรณ์ 3-5 ย่อหน้า โดยเล่าเนื้อเรื่องจริงจากต้นฉบับอย่างละเอียด ลำดับเหตุการณ์ชัดเจน เข้าใจง่าย ลื่นไหล สอดคล้องกับแนวทางของเรื่อง (หากเป็นคดีปริศนา/เรื่องลึกลับให้เล่าชวนติดตาม หากเป็นประวัติศาสตร์ให้เล่าความน่าทึ่ง หากเป็นสุขภาพ/เทคโนโลยีให้อธิบายสาระประโยชน์)
3. *** ห้ามเขียนเป็นเพียงแค่รายชื่อสำนักข่าวเด็ดขาด เช่น 1. Bloomberg 2. Deadline *** ให้เล่าเนื้อเรื่องจริงของบทความเท่านั้น
4. จัดวรรคตอนให้อ่านสบายตาบนสมาร์ทโฟน สอดแทรกอีโมจิที่เข้ากับอารมณ์ของเนื้อหาอย่างมีระดับ
5. ปิดท้ายด้วยประเด็นหรือคำถามชวนผู้อ่านแลกเปลี่ยนมุมมองเพื่อสร้าง Engagement
6. ติดแฮชแท็ก 3-5 อันที่ตรงกับเนื้อเรื่องจริง (ห้ามติดแฮชแท็กที่ไม่เกี่ยวข้องเด็ดขาด เช่น หากไม่ใช่ข่าวไอที ห้ามมี #เทคโนโลยี #AI)
7. ระบุเครดิตแหล่งที่มาท้ายโพสต์: 📌 ที่มา: {source_name}

รูปแบบผลลัพธ์ที่ต้องการ (STRICT FORMAT):
[HEADLINE_TH]
<พาดหัวภาษาไทยสั้นกระชับ คมคาย 35-65 ตัวอักษร ไม่มีอีโมจิ>
[END_HEADLINE]

<เนื้อหาโพสต์ Facebook ภาษาไทย พร้อมอีโมจิ แฮชแท็ก และเครดิต>
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
                        'temperature': 0.75,
                    }
                )
                if response and response.text:
                    rewritten_text = response.text.strip()
                    return sanitize_forbidden_words(rewritten_text)
            except Exception as em:
                print(f"⚠️ โมเดล {model_name} ใช้งานไม่ได้ ({str(em)[:60]}...), กำลังสลับไปโมเดลถัดไป...")
                continue

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการเชื่อมต่อ SDK: {e}")

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
    
    if rewritten:
        rewritten = sanitize_forbidden_words(rewritten)
    return rewritten
