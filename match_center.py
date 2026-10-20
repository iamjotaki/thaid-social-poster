"""
Module: match_center.py
ระบบ Match Center สำหรับแฟนเพจลิเวอร์พูล:
1. ดึงตารางแข่งขันและผลการแข่งขันสด/ย้อนหลัง (All Competitions: EPL, UCL, Carabao, FA Cup)
2. ดึงตารางคะแนนพรีเมียร์ลีกล่าสุด (Standings Table)
3. ระบบ AI พรีวิววิเคราะห์ก่อนเกม (Pre-match Preview) สไตล์คอลัมนิสต์เก๋า
4. ระบบ AI ตัดเกรดคะแนนผู้เล่นหลังเกม (Post-match Player Ratings 1-10)
5. ระบบ AI รายงานผลสดหลังสิ้นเสียงนกหวีด (Post-match Report)
"""

import os
import sys
import json
import urllib.request
import datetime
import re
from typing import Dict, List, Optional

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import config
from ai_rewriter import sanitize_forbidden_words

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def format_thai_datetime(iso_str: str) -> str:
    """แปลง ISO date จาก ESPN API เป็นวันเวลาภาษาไทย (GMT+7)"""
    try:
        # 2026-10-17T14:00Z
        dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        # ปรับเป็นเวลาไทย GMT+7
        dt_th = dt.astimezone(datetime.timezone(datetime.timedelta(hours=7)))
        thai_days = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
        thai_months = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
        
        day_name = thai_days[dt_th.weekday()]
        day_num = dt_th.day
        month_name = thai_months[dt_th.month]
        time_str = dt_th.strftime("%H:%M น.")
        return f"{day_name}ที่ {day_num} {month_name} เวลา {time_str}"
    except Exception:
        return iso_str[:16].replace("T", " ")

def get_liverpool_schedule() -> Dict:
    """
    ดึงตารางการแข่งขันของลิเวอร์พูลจาก ESPN API (ครอบคลุมทุกรายการ)
    แยกเป็น:
    - recent_matches: นัดที่แข่งจบแล้วล่าสุด
    - next_matches: นัดถัดไปในอนาคต
    """
    url = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/364/schedule"
    matches = []

    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            raw_events = data.get("events", [])

            for ev in raw_events:
                comp_data = ev.get("competitions", [{}])[0]
                status_data = comp_data.get("status", {}).get("type", {})
                is_completed = status_data.get("completed", False) or status_data.get("state") == "post"
                status_desc = status_data.get("description", "Scheduled")

                # แข่งที่ไหน
                venue = comp_data.get("venue", {}).get("fullName", "Anfield")
                comp_name = ev.get("season", {}).get("displayName", "Premier League")
                if "Premier League" in comp_name:
                    competition_th = "🏴󠁧󠁢󠁥󠁮󠁧󠁿 พรีเมียร์ลีก"
                elif "Champions League" in comp_name:
                    competition_th = "🏆 ยูฟ่า แชมเปียนส์ลีก"
                elif "Carabao" in comp_name or "EFL" in comp_name:
                    competition_th = "🏆 คาราบาว คัพ"
                elif "FA Cup" in comp_name:
                    competition_th = "🏆 เอฟเอ คัพ"
                else:
                    competition_th = comp_name

                competitors = comp_data.get("competitors", [])
                home_team = "Liverpool"
                away_team = "Opponent"
                home_score = ""
                away_score = ""
                is_lfc_home = True
                opponent_name = ""

                for c in competitors:
                    t_name = c.get("team", {}).get("displayName", "")
                    score = c.get("score", {}).get("displayValue", "")
                    home_away = c.get("homeAway", "home")
                    
                    if "Liverpool" in t_name:
                        is_lfc_home = (home_away == "home")
                    else:
                        opponent_name = t_name

                    if home_away == "home":
                        home_team = t_name
                        home_score = score
                    else:
                        away_team = t_name
                        away_score = score

                match_item = {
                    "id": ev.get("id"),
                    "name": ev.get("name"),
                    "date_iso": ev.get("date"),
                    "date_th": format_thai_datetime(ev.get("date", "")),
                    "competition": competition_th,
                    "venue": venue,
                    "is_completed": is_completed,
                    "status_desc": status_desc,
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_score": home_score,
                    "away_score": away_score,
                    "is_lfc_home": is_lfc_home,
                    "opponent": opponent_name or (away_team if is_lfc_home else home_team)
                }
                matches.append(match_item)

    except Exception as e:
        print(f"[MatchCenter Error] Fetching schedule failed: {e}")

    # แยก completed กับ upcoming
    completed_matches = [m for m in matches if m["is_completed"]]
    upcoming_matches = [m for m in matches if not m["is_completed"]]

    # จัดลำดับล่าสุด
    completed_matches.sort(key=lambda x: x["date_iso"], reverse=True)
    upcoming_matches.sort(key=lambda x: x["date_iso"])

    return {
        "recent_matches": completed_matches[:6],
        "next_matches": upcoming_matches[:6],
        "latest_completed": completed_matches[0] if completed_matches else None,
        "next_upcoming": upcoming_matches[0] if upcoming_matches else None
    }

def get_premier_league_standings() -> List[Dict]:
    """ดึงตารางคะแนนพรีเมียร์ลีกแบบเรียลไทม์จาก ESPN API"""
    url = "https://site.api.espn.com/apis/v2/sports/soccer/eng.1/standings"
    standings = []

    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            children = data.get("children", [{}])
            entries = children[0].get("standings", {}).get("entries", []) if children else []

            for entry in entries:
                team_data = entry.get("team", {})
                stats = entry.get("stats", [])
                
                stat_map = {s.get("name"): s.get("displayValue") for s in stats}
                
                is_lfc = "Liverpool" in team_data.get("displayName", "")

                standings.append({
                    "rank": stat_map.get("rank", "-"),
                    "team": team_data.get("displayName", ""),
                    "short_name": team_data.get("shortDisplayName", ""),
                    "logo": team_data.get("logos", [{}])[0].get("href", "") if team_data.get("logos") else "",
                    "played": stat_map.get("gamesPlayed", "0"),
                    "won": stat_map.get("wins", "0"),
                    "drawn": stat_map.get("ties", "0"),
                    "lost": stat_map.get("losses", "0"),
                    "gd": stat_map.get("pointDifferential", "0"),
                    "points": stat_map.get("points", "0"),
                    "is_lfc": is_lfc
                })

    except Exception as e:
        print(f"[MatchCenter Error] Fetching standings failed: {e}")

    return standings

# -------------------------------------------------------------
# AI GENERATORS (PREVIEW & PLAYER RATINGS & REPORT)
# -------------------------------------------------------------
def call_gemini_for_match(prompt: str) -> Optional[str]:
    """ส่ง Prompt ให้ Gemini สร้างคอนเทนต์แมตช์เซ็นเตอร์"""
    if not config.GEMINI_API_KEY:
        return "⚠️ กรุณาตั้งค่า GEMINI_API_KEY ก่อนใช้งานฟังก์ชัน AI Match Center"

    candidate_models = [
        'gemini-3.8-flash',
        'gemini-3.7-flash',
        'gemini-3.5-flash',
        'gemini-3.5-flash-lite'
    ]

    try:
        from google import genai
        client = genai.Client(api_key=config.GEMINI_API_KEY)

        for model_name in candidate_models:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={
                        'system_instruction': config.AI_SYSTEM_INSTRUCTION,
                        'temperature': 0.85,
                        'top_p': 0.95
                    }
                )
                if response and response.text:
                    return sanitize_forbidden_words(response.text)
            except Exception as e_m:
                print(f"[MatchCenter AI] Model {model_name} error: {e_m}")
                continue

    except Exception as e:
        print(f"[MatchCenter AI Global Error]: {e}")

    return None

def generate_ai_match_preview(
    opponent: str,
    competition: str = "พรีเมียร์ลีก",
    venue: str = "แอนฟิลด์ (เหย้า)",
    date_str: str = "สุดสัปดาห์นี้",
    focus_player: str = None,
    extra_notes: str = None
) -> str:
    """
    สร้างบทความพรีวิวก่อนเตะ สไตล์คอลัมนิสต์ฟุตบอลเก๋าจัดจ้าน
    """
    notes_section = f"\nประเด็นหรือแท็กติกเพิ่มเติมที่ต้องเน้น: {extra_notes}" if extra_notes else ""
    player_section = f"\nนักเตะตัวแปรสำคัญที่น่าจับตามอง: {focus_player}" if focus_player else ""

    prompt = f"""
คุณคือนักเขียนคอลัมนิสต์กีฬาแฟนพันธุ์แท้ลิเวอร์พูล ผู้มีสำนวนเก๋าจัดจ้าน ดุดัน กวนๆ ตลกมีมุกเปรียบเปรยแบบไทยๆ แต่แม่นยำเรื่องแท็กติก
กรุณาเขียนบทความ "พรีวิววิเคราะห์ก่อนเกมแมตช์ต่อไปของลิเวอร์พูล" เพื่อนำไปโพสต์ลง Facebook Fanpage:

[ข้อมูลแมตช์การแข่งขัน]
คู่แข่ง: {opponent}
รายการแข่งขัน: {competition}
สนามแข่งขัน: {venue}
กำหนดการแข่ง: {date_str}
{player_section}
{notes_section}

[โครงสร้างบทความที่ต้องเขียน]:
1. 🔴 พาดหัวตัวเบิ้มๆ เร้าใจสไตล์เดือด (เตะตาก่อนใครบนฟีด)
2. บริบทความสำคัญของเกมนี้ (3 แต้มนี้ชี้ชะตาอะไร คู่แข่งกำลังฟอร์มแบบไหน บรรยากาศแอนฟิลด์หรือเกมเยือนสุดหิน)
3. 11 ตัวจริงที่คาดว่าจะลงสนาม (จัดเต็มตามตำแหน่ง GK, DF, MF, FW แดนกลางใครคุมเกม แนวรุกใครล่าตาข่าย)
4. จุดตัดสินเกม & แผนแท็กติกที่กุนซือต้องสั่งลูกทีม (จุดอ่อนคู่แข่งที่ต้องเจาะ, การระวังลูกโต้กลับ)
5. ฟันธงสกอร์ & คำคมปิดท้ายแบบกวนๆ เด็ดขาด มั่นใจ
6. แฮชแท็กประจำแมตช์ เช่น #LFC #Liverpool #หงส์แดง #พรีวิวพรีเมียร์ลีก

กฎเหล็กเด็ดขาด: ห้ามเอ่ยหรือพิมพ์ชื่อ บอ.บู๋ หรือ บอบู๋ โดยเด็ดขาด 100%!
เขียนให้อ่านสนุก มันส์ สะใจแฟนบอลลิเวอร์พูลตัวจริง!
"""
    result = call_gemini_for_match(prompt)
    if not result:
        return f"🔴 พรีวิวบิ๊กแมตช์: ลิเวอร์พูล ปะทะ {opponent}\n\nเกมนี้ชี้ชะตา 3 แต้มสำคัญ แฟนหงส์แดงห้ามพลาดเด็ดขาด!"
    return result

def generate_ai_player_ratings(
    opponent: str,
    score: str = "2-1",
    competition: str = "พรีเมียร์ลีก",
    match_highlight: str = None,
    extra_notes: str = None
) -> str:
    """
    สร้างบทความตัดเกรดคะแนนผู้เล่นหลังเกม (Player Ratings 1-10) พร้อมวิจารณ์สับแหลก/ชมยับ
    """
    notes_section = f"\nเหตุการณ์เด่นในเกม: {match_highlight}" if match_highlight else ""
    if extra_notes:
        notes_section += f"\nบันทึกเพิ่มเติม: {extra_notes}"

    prompt = f"""
คุณคือนักวิจารณ์คอลัมนิสต์กีฬาตัวเก๋าประจำเพจลิเวอร์พูล อารมณ์ดิบ ดุดัน รักแรง เกลียดแรง ชัดเจน ตรงไปตรงมา
กรุณาเขียนบทความ "ตัดเกรดคะแนนผู้เล่นลิเวอร์พูลหลังเกม (Player Ratings)" โพสต์ลง Facebook:

[ข้อมูลผลการแข่งขัน]
พบกับ: {opponent}
ผลสกอร์: ลิเวอร์พูล {score}
รายการแข่งขัน: {competition}
{notes_section}

[โครงสร้างบทความตัดเกรดที่ต้องมี]:
1. 🔴 พาดหัวตัดเกรดแซ่บๆ สไตล์สะใจแฟนบอล
2. สรุปภาพรวมของเกม 90 นาทีแบบถึงพริกถึงขิง
3. ตัดเกรดคะแนนรายบุคคล (คะแนนเต็ม 10) พร้อมคอมเมนต์สั้นๆ สับแหลกหรือยกย่อง:
   - ผู้รักษาประตู (GK): ให้คะแนน + ความเห็น
   - แผงหลัง (DF): แบ็กขวา, เซ็นเตอร์ 2 ตัว, แบ็กซ้าย (ระบุชื่อนักเตะลิเวอร์พูลตัวจริง เช่น ฟาน ไดจ์ค, โกนาเต้, เทรนต์/แบรดลีย์, โรเบิร์ตสัน)
   - แดนกลาง (MF): 3 ประสานกองกลาง (เช่น กราเฟนแบร์ก, แม็ค อัลลิสเตอร์, โซโบสไล / โจนส์)
   - แผงหน้า (FW): 3 กองหน้าล่าตาข่าย (เช่น ซาลาห์, ดิอาซ, โชต้า / นูนเญซ / คักโป)
   - ตัวสำรอง (Subs): สรุปสั้นๆ ตัวที่เปลี่ยนลงมา
4. 🌟 Man of the Match (แข้งยอดเยี่ยมประจำแมตช์): ใครเด่นสุด และทำไม
5. 💩 บ่อประจำเกม (Flop of the Match): ใครเล่นหลุดฟอร์ม หรือน่าด่าที่สุด
6. ทัศนะสรุปปิดท้าย & แฮชแท็ก #LFC #ตัดเกรดหลังเกม #Liverpool

กฎเหล็กเด็ดขาด: ห้ามเอ่ยหรือพิมพ์ชื่อ บอ.บู๋ หรือ บอบู๋ โดยเด็ดขาด 100%!
เขียนให้สนุก สมจริง ฟีลคนดูบอลจบแล้วเปิดเพจอ่านทันที!
"""
    result = call_gemini_for_match(prompt)
    if not result:
        return f"🔴 ตัดเกรดคะแนนหลังเกม: ลิเวอร์พูล พบ {opponent} ({score})\n\nฟอร์มโดยรวมถือว่าสู้ได้ประทับใจแฟนบอล!"
    return result

def generate_ai_postmatch_report(
    opponent: str,
    score: str = "2-0",
    competition: str = "พรีเมียร์ลีก",
    goals: str = None
) -> str:
    """
    สร้างรายงานผลการแข่งขันฉบับด่วนหลังสิ้นเสียงนกหวีด (Full-time Match Report)
    """
    goal_section = f"\nคนยิงประตูและนาทีที่ยิง: {goals}" if goals else ""

    prompt = f"""
คุณคือนักข่าวและคอลัมนิสต์สายหงส์แดงตัวจริง
กรุณาเขียน "รายงานผลการแข่งขันสดฉบับเต็มหลังจบเกม (Match Report)" เพื่อโพสต์ลง Facebook ทันทีที่เสียงนกหวีดหมดเวลาดัง:

[ข้อมูลแมตช์]
คู่แข่งขัน: ลิเวอร์พูล พบ {opponent}
สกอร์จบเกม: {score}
รายการ: {competition}
{goal_section}

[โครงสร้างบทความ]:
1. 🔴 พาดหัวข่าวผลการแข่งขันฉบับเดือดดาล
2. สรุปรูปเกมครึ่งแรก & ครึ่งหลังแบบกระชับ เห็นภาพ
3. จุดเปลี่ยนสำคัญของเกม (ลูกยิง, ใบแดง, เซฟมหัศจรรย์)
4. สรุปตารางคะแนนและสถานการณ์ลุ้นแชมป์/อันดับ
5. แฮชแท็กประจำเกม

กฎเหล็กเด็ดขาด: ห้ามพิมพ์หรือเอ่ยชื่อ บอ.บู๋ หรือ บอบู๋ โดยเด็ดขาด 100%!
"""
    result = call_gemini_for_match(prompt)
    if not result:
        return f"🔴 ผลการแข่งขัน: ลิเวอร์พูล {score} {opponent}\n\nจบเกม 90 นาที ลิเวอร์พูลคว้าแต้มสำคัญได้สำเร็จ!"
    return result

if __name__ == "__main__":
    print("Testing match_center.py...")
    sched = get_liverpool_schedule()
    print("Latest completed:", sched.get("latest_completed"))
    print("Next upcoming:", sched.get("next_upcoming"))
    standings = get_premier_league_standings()
    print("Standings count:", len(standings))
