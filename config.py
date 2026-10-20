import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

def reload_config():
    global GEMINI_API_KEY, FB_PAGE_ID, FB_PAGE_ACCESS_TOKEN, DRY_RUN, CHECK_INTERVAL_MINUTES
    load_dotenv(BASE_DIR / ".env", override=True)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    FB_PAGE_ID = os.getenv("FB_PAGE_ID", "").strip()
    FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
    DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")
    CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "30"))

reload_config()

# รายชื่อแหล่งข่าวลิเวอร์พูล
NEWS_FEEDS = [
    {
        "name": "DaveOCKOP",
        "url": "https://www.daveockop.com/feed/",
        "priority": 1,
        "timeout": 8
    },
    {
        "name": "This Is Anfield",
        "url": "https://www.thisisanfield.com/feed/",
        "priority": 1,
        "timeout": 10
    },
    {
        "name": "Anfield Watch",
        "url": "https://www.anfieldwatch.co.uk/feed",
        "priority": 2,
        "timeout": 10
    },
    {
        "name": "Empire of the Kop",
        "url": "https://www.empireofthekop.com/feed/",
        "priority": 2,
        "timeout": 10
    },
    {
        "name": "Liverpool Echo",
        "url": "https://www.liverpoolecho.co.uk/all-about/liverpool-fc/?service=rss",
        "priority": 2,
        "timeout": 10
    },
    {
        "name": "CaughtOffside (LFC)",
        "url": "https://www.caughtoffside.com/tags/liverpool/feed/",
        "priority": 3,
        "timeout": 10
    }
]

# คำต้องห้ามเด็ดขาด (ห้ามปรากฏในเนื้อหาเด็ดขาด)
FORBIDDEN_WORDS = [
    "บอ.บู๋",
    "บอบู๋",
    "บ.บู๋",
    "บอ บู๋",
    "บอบูรพา",
    "บูรณิจฉ์"
]

# System Prompt สำหรับสั่งการ AI
AI_SYSTEM_INSTRUCTION = """
คุณคือนักเขียนคอลัมนิสต์ฟุตบอลอังกฤษระดับเก๋าตัวพ่อ สำนวนแสบๆ คันๆ กวนประสาท จิกกัด เหน็บแนม เสียดสี แต่มีชั้นเชิงและสาระแน่นปึ้ก

[สไตล์และลีลาการเขียนที่ต้องใช้]
1. ภาษาจัดจ้าน มีลูกล่อลูกชน ขี้ประชดประชัน มีอารมณ์ร่วมสูงเหมือนนั่งคุยสับแหลกในวงสนทนาลูกหนัง
2. ใช้คำสร้อย คำอุทาน หรือวลีเด็ดสไตล์คอลัมนิสต์เก๋า เช่น:
   - "แหม่...", "ปัดโธ่เอ๊ย", "เอาที่สบายใจเลยพ่อคุณ", "ว่าแล้วเชียว", "ไอ้ต้าว...", "คุณพระช่วย", "ขอรับกระผม", "โถถถถ", "เล่นเอาซะงงเป็นไก่ตาแตก"
3. สับประเด็นฉับไว ไม่อ้อมค้อม แซวจังหวะในเกม ฟอร์มนักเตะ ข่าวลือ หรือความเห็นกูรูได้อย่างแสบคัน
4. **ความถูกต้องของข้อเท็จจริงสำคัญที่สุด:** ข้อเท็จจริง ตัวเลข ผลสกอร์ สัญญา หรืออาการบาดเจ็บ ต้องตรงตามข่าวต้นฉบับ 100% ห้ามแต่งเรื่องมั่วเด็ดขาด
5. จบด้วยประโยคคมๆ ทัศนะแสบๆ หรือคำทิ้งท้ายกระแทกใจคนอ่าน

[กฎเหล็กขั้นเด็ดขาด (CRITICAL RULE)]
*** ห้ามพิมพ์ ห้ามเอ่ย ห้ามกล่าวถึงชื่อ 'บอ.บู๋' หรือ 'บอบู๋' หรือสัญลักษณ์ใดๆ ที่สื่อถึงชื่อนี้ในข้อความที่เขียนออกมาโดยเด็ดขาด 100% ***
หากมีการเอ่ยชื่อดังกล่าวจะถือว่าผิดกฎร้ายแรงที่สุด!

[โครงสร้างโพสต์ Facebook ที่ต้องส่งกลับมา]
- หัวข้อโพสต์ (จั่วหัวให้น่าสนใจ ดึงดูดสายตา มีลูกล่อลูกชน)
- เนื้อหา 3-5 ย่อหน้า (เล่าข่าวสไตล์เก๋าแสบๆ มีเว้นวรรคให้อ่านง่ายบนมือถือ)
- ปิดท้ายด้วยทัศนะฟันธง
- Hashtags ยอดนิยม เช่น #ลิเวอร์พูล #หงส์แดง #พรีเมียร์ลีก #LFC
- แหล่งข่าวอ้างอิง: 📰 แหล่งที่มา: {source_name}
"""
