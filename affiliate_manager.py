"""
Module: affiliate_manager.py
ระบบจัดการลิงก์ Affiliate (Shopee, Lazada, TikTok Shop) และแทรกท้ายโพสต์อัตโนมัติ
เพื่อสร้างรายได้จากค่าคอมมิชชันสินค้าฟุตบอลและของสะสมลิเวอร์พูล
"""

import os
import json
import random
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
AFFILIATE_FILE = BASE_DIR / "affiliate_products.json"

DEFAULT_PRODUCTS = [
    {
        "id": "lfc_jersey",
        "name": "เสื้อแข่งลิเวอร์พูลของแท้ 2024/25 (เหย้า/เยือน)",
        "url": "https://shope.ee/liverpool-official-jersey",
        "desc": "ของแท้ 100% สกรีนชื่อเบอร์นักเตะได้ พร้อมโค้ดส่งฟรี",
        "is_active": True
    },
    {
        "id": "lfc_boots",
        "name": "รองเท้าสตั๊ด / รองเท้าฟุตบอลรุ่นล่าสุด",
        "url": "https://shope.ee/football-boots-pro",
        "desc": "ลดราคาสูงสุด 40% ใส่สบาย ยึดเกาะสนามเยี่ยม",
        "is_active": True
    },
    {
        "id": "lfc_scarf",
        "name": "ผ้าพันคอ & หมวกสโมสรลิเวอร์พูลของแท้",
        "url": "https://shope.ee/lfc-scarf-collection",
        "desc": "สินค้านำเข้าจากสโมสร ลิขสิทธิ์แท้สำหรับแฟนพันธุ์แท้",
        "is_active": True
    },
    {
        "id": "lfc_tumbler",
        "name": "แก้วน้ำ & กระบอกน้ำเก็บความเย็นลายสโมสร",
        "url": "https://shope.ee/lfc-tumbler-cold",
        "desc": "เก็บความเย็นได้นาน 24 ชม. ลายลิขสิทธิ์ทางการ",
        "is_active": True
    }
]

def load_affiliate_products() -> List[Dict]:
    """โหลดรายการสินค้า Affiliate ทั้งหมด"""
    if not AFFILIATE_FILE.exists():
        save_affiliate_products(DEFAULT_PRODUCTS)
        return DEFAULT_PRODUCTS
    try:
        data = json.loads(AFFILIATE_FILE.read_text(encoding="utf-8"))
        return data
    except Exception as e:
        print(f"[AffiliateManager Error]: {e}")
        return DEFAULT_PRODUCTS

def save_affiliate_products(products: List[Dict]) -> bool:
    """บันทึกรายการสินค้า Affiliate"""
    try:
        AFFILIATE_FILE.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[AffiliateManager Save Error]: {e}")
        return False

def get_affiliate_footer(product_id: Optional[str] = None) -> str:
    """
    สร้างข้อความกล่อง Affiliate ท้ายโพสต์
    หากไม่ระบุ product_id จะสุ่มเลือกจากสินค้าที่เปิดใช้งาน (is_active)
    """
    products = load_affiliate_products()
    active_prods = [p for p in products if p.get("is_active", True)]

    if not active_prods:
        return ""

    selected = None
    if product_id:
        for p in active_prods:
            if p.get("id") == product_id:
                selected = p
                break

    if not selected:
        selected = random.choice(active_prods)

    name = selected.get("name", "สินค้าลิเวอร์พูลของแท้")
    url = selected.get("url", "https://shopee.co.th")
    desc = selected.get("desc", "รับประกันของแท้ 100%")

    footer = f"""
━━━━━━━━━━━━━━━━━━━
🛒 [พิกัดสินค้าแนะนำสำหรับเด็กหงส์]
👉 {name}
🔗 สั่งซื้อคลิก: {url}
({desc})
━━━━━━━━━━━━━━━━━━━"""
    return footer

def attach_affiliate_if_enabled(caption: str, enable_affiliate: bool = False, product_id: Optional[str] = None) -> str:
    """แนบข้อความ Affiliate ท้ายแคปชัน หากผู้ใช้เปิดตัวเลือกไว้"""
    if not enable_affiliate:
        return caption

    # ตรวจสอบว่ามีลิงก์อยู่แล้วหรือไม่ ป้องกันการใส่ซ้ำ
    if "🛒 [พิกัดสินค้าแนะนำสำหรับเด็กหงส์]" in caption:
        return caption

    footer = get_affiliate_footer(product_id)
    return f"{caption.rstrip()}\n{footer}"
