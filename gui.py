import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
import customtkinter as ctk
from PIL import Image, ImageTk

# ปรับ encoding รองรับ UTF-8 บน Windows
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import config
from database import get_recent_articles, is_article_seen, mark_as_posted, update_rewritten, save_article
from news_fetcher import fetch_all_new_articles, download_image
from ai_rewriter import rewrite_article
from fb_poster import post_to_facebook, PREVIEW_HTML_PATH

# กำหนดสไตล์และสี
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

COLOR_LFC_RED = "#C8102E"
COLOR_LFC_DARK_RED = "#9B0014"
COLOR_GOLD = "#F6EB61"
COLOR_BG_CARD = "#1E1E24"
COLOR_BG_DARK = "#121214"
COLOR_TEXT_MUTED = "#8E8E93"
COLOR_SUCCESS = "#28A745"

class LiverpoolNewsApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("🔴 LFC News Auto-Poster - หงส์แดงนิวส์บอท")
        self.geometry("1100;750")
        self.minsize(980, 680)

        # สถานะการทำงานของ Auto-Bot
        self.is_auto_running = False
        self.auto_thread = None

        # Grid Layout (2 คอลัมน์: เมนูด้านซ้าย + หน้าจอหลักด้านขวา)
        self.grid_columnconfigure(0, weight=0, minsize=290)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._create_sidebar()
        self._create_main_content()

        # โหลดประวัติข่าวเข้าสู่หน้าจอ
        self.after(300, self.refresh_news_cards)

    # -------------------------------------------------------------
    # SIDEBAR PANEL (ด้านซ้าย: ควบคุม, สถานะ, ตั้งค่า)
    # -------------------------------------------------------------
    def _create_sidebar(self):
        sidebar = ctk.CTkFrame(self, corner_radius=0, fg_color=COLOR_BG_DARK)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        sidebar.grid_rowconfigure(10, weight=1)

        # โลโก้ & ชื่อโปรแกรม
        title_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        title_frame.pack(fill="x", padx=20, pady=(20, 15))

        lbl_title = ctk.CTkLabel(
            title_frame,
            text="🔴 LFC NEWS BOT",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#FFFFFF"
        )
        lbl_title.pack(anchor="w")

        lbl_subtitle = ctk.CTkLabel(
            title_frame,
            text="ระบบดูดข่าวหงส์แดง & โพสต์อัตโนมัติ",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_MUTED
        )
        lbl_subtitle.pack(anchor="w")

        # สถานะการเชื่อมต่อ
        status_frame = ctk.CTkFrame(sidebar, fg_color=COLOR_BG_CARD, corner_radius=10)
        status_frame.pack(fill="x", padx=15, pady=8)

        lbl_st_title = ctk.CTkLabel(status_frame, text="⚡ สถานะระบบ", font=ctk.CTkFont(size=13, weight="bold"))
        lbl_st_title.pack(anchor="w", padx=12, pady=(10, 4))

        gemini_status = "🟢 พร้อมใช้งาน" if config.GEMINI_API_KEY else "🔴 ยังไม่ใส่คีย์"
        self.lbl_gemini = ctk.CTkLabel(status_frame, text=f"• Gemini AI: {gemini_status}", font=ctk.CTkFont(size=12))
        self.lbl_gemini.pack(anchor="w", padx=12, pady=2)

        fb_status = "🟢 Live (ยิงจริง)" if (not config.DRY_RUN and config.FB_PAGE_ACCESS_TOKEN) else "🟡 Dry-Run (ทดสอบ)"
        self.lbl_fb = ctk.CTkLabel(status_frame, text=f"• Facebook: {fb_status}", font=ctk.CTkFont(size=12))
        self.lbl_fb.pack(anchor="w", padx=12, pady=(2, 10))

        # ปุ่มควบคุมหลัก
        ctrl_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        ctrl_frame.pack(fill="x", padx=15, pady=10)

        self.btn_fetch_once = ctk.CTkButton(
            ctrl_frame,
            text="⚡ ดึงข่าว & เรียบเรียงทันที",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLOR_LFC_RED,
            hover_color=COLOR_LFC_DARK_RED,
            height=40,
            command=self.start_manual_fetch
        )
        self.btn_fetch_once.pack(fill="x", pady=6)

        self.btn_auto_toggle = ctk.CTkButton(
            ctrl_frame,
            text="⏱️ เริ่มรันอัตโนมัติ (Auto-Run)",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1F6AA5",
            hover_color="#144870",
            height=36,
            command=self.toggle_auto_run
        )
        self.btn_auto_toggle.pack(fill="x", pady=6)

        btn_open_preview = ctk.CTkButton(
            ctrl_frame,
            text="🌐 เปิดดูตัวอย่าง HTML",
            font=ctk.CTkFont(size=12),
            fg_color="#333338",
            hover_color="#44444C",
            height=32,
            command=self.open_html_preview
        )
        btn_open_preview.pack(fill="x", pady=6)

        # เมนูตั้งค่า (Settings Accordion/Frame)
        settings_frame = ctk.CTkFrame(sidebar, fg_color=COLOR_BG_CARD, corner_radius=10)
        settings_frame.pack(fill="x", padx=15, pady=10)

        lbl_set = ctk.CTkLabel(settings_frame, text="⚙️ ตั้งค่าระบบ", font=ctk.CTkFont(size=13, weight="bold"))
        lbl_set.pack(anchor="w", padx=12, pady=(8, 4))

        # Switch โหมด Dry-Run
        self.switch_dry_run = ctk.CTkSwitch(
            settings_frame,
            text="Dry-Run (ทดสอบไม่โพสต์จริง)",
            font=ctk.CTkFont(size=12),
            command=self.on_toggle_dry_run
        )
        if config.DRY_RUN:
            self.switch_dry_run.select()
        else:
            self.switch_dry_run.deselect()
        self.switch_dry_run.pack(anchor="w", padx=12, pady=6)

        # Interval เลือกเวลารันวนลูป
        lbl_int = ctk.CTkLabel(settings_frame, text="รอบการตรวจข่าว (นาที):", font=ctk.CTkFont(size=12))
        lbl_int.pack(anchor="w", padx=12, pady=(4, 0))

        self.combo_interval = ctk.CTkComboBox(
            settings_frame,
            values=["15", "30", "60", "120"],
            width=120,
            height=28
        )
        self.combo_interval.set(str(config.CHECK_INTERVAL_MINUTES))
        self.combo_interval.pack(anchor="w", padx=12, pady=(2, 10))

    # -------------------------------------------------------------
    # MAIN CONTENT PANEL (ด้านขวา: แท็บแสดงข่าว + พรีวิว + ล็อก)
    # -------------------------------------------------------------
    def _create_main_content(self):
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(1, weight=1)

        # หัวข้อส่วนบน
        top_bar = ctk.CTkFrame(main_frame, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        top_bar.grid_columnconfigure(0, weight=1)

        self.lbl_main_status = ctk.CTkLabel(
            top_bar,
            text="📌 แดชบอร์ดข่าวลิเวอร์พูล - สำนวนเก๋าแสบคัน (ไม่เอ่ยชื่อต้องห้าม)",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.lbl_main_status.grid(row=0, column=0, sticky="w")

        btn_refresh = ctk.CTkButton(
            top_bar,
            text="🔄 รีเฟรช",
            width=80,
            height=28,
            fg_color="#333338",
            hover_color="#44444C",
            command=self.refresh_news_cards
        )
        btn_refresh.grid(row=0, column=1, sticky="e")

        # แท็บวิว (TabView)
        self.tabview = ctk.CTkTabview(main_frame, fg_color=COLOR_BG_CARD)
        self.tabview.grid(row=1, column=0, sticky="nsew")

        self.tab_cards = self.tabview.add("📰 รายการข่าว & โพสต์")
        self.tab_settings = self.tabview.add("⚙️ ตั้งค่า Facebook & API")
        self.tab_logs = self.tabview.add("📜 บันทึกการทำงาน (Live Logs)")

        # แท็บที่ 1: Scrollable List ของการ์ดข่าว
        self.tab_cards.grid_columnconfigure(0, weight=1)
        self.tab_cards.grid_rowconfigure(0, weight=1)

        self.scroll_cards = ctk.CTkScrollableFrame(self.tab_cards, fg_color="transparent")
        self.scroll_cards.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.scroll_cards.grid_columnconfigure(0, weight=1)

        # แท็บที่ 2: การตั้งค่า Facebook & API
        self._create_settings_view()

        # แท็บที่ 3: Live Logs
        self.tab_logs.grid_columnconfigure(0, weight=1)
        self.tab_logs.grid_rowconfigure(0, weight=1)

        self.txt_logs = ctk.CTkTextbox(
            self.tab_logs,
            wrap="word",
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color="#0F0F12",
            text_color="#E0E0E0"
        )
        self.txt_logs.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    # -------------------------------------------------------------
    # LOGGING & UI HELPERS
    # -------------------------------------------------------------
    def log(self, message: str):
        """แสดงข้อความในกล่อง Logs และพิมพ์ลงคอนโซล"""
        print(message)
        timestamp = time.strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {message}\n"
        self.txt_logs.insert("end", log_line)
        self.txt_logs.see("end")

    def open_html_preview(self):
        """เปิดไฟล์พรีวิวในเบราว์เซอร์เริ่มต้น"""
        if PREVIEW_HTML_PATH.exists():
            webbrowser.open(str(PREVIEW_HTML_PATH.resolve()))
        else:
            self.log("⚠️ ยังไม่มีไฟล์พรีวิว กดปุ่มดึงข่าวก่อนเพื่อสร้างพรีวิว")

    def on_toggle_dry_run(self):
        config.DRY_RUN = self.switch_dry_run.get() == 1
        mode_text = "🟡 Dry-Run (ทดสอบ)" if config.DRY_RUN else "🟢 Live (ยิงจริง)"
        self.lbl_fb.configure(text=f"• Facebook: {mode_text}")
        self.log(f"⚙️ เปลี่ยนโหมดเป็น: {mode_text}")

    # -------------------------------------------------------------
    # REFRESH NEWS CARDS FROM SQLITE
    # -------------------------------------------------------------
    def refresh_news_cards(self):
        """โหลดรายการข่าวจากฐานข้อมูลมาแสดงเป็นการ์ดสวยงาม"""
        # ลบการ์ดเดิมออกก่อน
        for widget in self.scroll_cards.winfo_children():
            widget.destroy()

        articles = get_recent_articles(limit=25)
        if not articles:
            lbl_empty = ctk.CTkLabel(
                self.scroll_cards,
                text="☕ ยังไม่มีข่าวในระบบ กดปุ่ม '⚡ ดึงข่าว & เรียบเรียงทันที' เพื่อเริ่มดึงข่าวล่าสุด!",
                font=ctk.CTkFont(size=14),
                text_color=COLOR_TEXT_MUTED
            )
            lbl_empty.pack(pady=40)
            return

        for art in articles:
            self._render_card(art)

    def _render_card(self, art: dict):
        card = ctk.CTkFrame(self.scroll_cards, fg_color="#18181C", corner_radius=10)
        card.pack(fill="x", padx=10, pady=8)
        card.grid_columnconfigure(1, weight=1)

        source = art.get("source", "LFC")
        title = art.get("title", "")
        rewritten = art.get("rewritten_text") or "ยังไม่ได้เรียบเรียง"
        status = art.get("status", "pending")
        image_url = art.get("image_url")

        # Header ของการ์ด
        header_frame = ctk.CTkFrame(card, fg_color="transparent")
        header_frame.pack(fill="x", padx=14, pady=(10, 4))
        header_frame.grid_columnconfigure(1, weight=1)

        badge = ctk.CTkLabel(
            header_frame,
            text=f" {source} ",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=COLOR_LFC_RED,
            corner_radius=6,
            text_color="#FFFFFF"
        )
        badge.grid(row=0, column=0, sticky="w", padx=(0, 8))

        lbl_card_title = ctk.CTkLabel(
            header_frame,
            text=title,
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
            justify="left"
        )
        lbl_card_title.grid(row=0, column=1, sticky="w")

        # สถานะการโพสต์
        st_color = COLOR_SUCCESS if status == "posted" else "#E5A93C"
        st_text = "✅ โพสต์แล้ว" if status == "posted" else "⏳ รอดำเนินการ"
        lbl_status = ctk.CTkLabel(
            header_frame,
            text=st_text,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=st_color
        )
        lbl_status.grid(row=0, column=2, sticky="e")

        # กล่องเนื้อหาที่ AI เขียนใหม่ (แก้ไขข้อความได้ก่อนโพสต์จริง!)
        txt_box = ctk.CTkTextbox(card, height=120, wrap="word", font=ctk.CTkFont(size=12))
        txt_box.pack(fill="x", padx=14, pady=6)
        txt_box.insert("1.0", rewritten)

        # Action Buttons ท้ายการ์ด
        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(fill="x", padx=14, pady=(4, 10))

        btn_copy = ctk.CTkButton(
            actions,
            text="📋 คัดลอกแคปชัน",
            width=110,
            height=28,
            fg_color="#333338",
            hover_color="#44444C",
            command=lambda t=txt_box: self._copy_to_clipboard(t.get("1.0", "end-1c"))
        )
        btn_copy.pack(side="left", padx=(0, 8))

        btn_save_edit = ctk.CTkButton(
            actions,
            text="💾 บันทึกการแก้ไข",
            width=110,
            height=28,
            fg_color="#2A2A32",
            hover_color="#3A3A44",
            command=lambda u=art["url"], t=txt_box: self._save_edited_text(u, t.get("1.0", "end-1c"))
        )
        btn_save_edit.pack(side="left", padx=(0, 8))

        btn_post_now = ctk.CTkButton(
            actions,
            text="📤 โพสต์ขึ้นเพจทันที",
            width=130,
            height=28,
            fg_color=COLOR_LFC_RED,
            hover_color=COLOR_LFC_DARK_RED,
            command=lambda a=art, t=txt_box: self._post_single_card(a, t.get("1.0", "end-1c"))
        )
        btn_post_now.pack(side="right")

    def _copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.log("📋 คัดลอกข้อความลงคลิปบอร์ดแล้ว!")

    def _save_edited_text(self, url: str, new_text: str):
        update_rewritten(url, new_text)
        self.log(f"💾 บันทึกการแก้ไขข้อความของข่าว {url[:40]}... เรียบร้อยแล้ว")

    def _post_single_card(self, art: dict, text_to_post: str):
        """โพสต์ข่าวการ์ดนี้ขึ้น Facebook ทันที"""
        def worker():
            self.log(f"🚀 กำลังส่งโพสต์ข่าว: '{art.get('title')[:35]}...'")
            image_url = art.get("image_url")
            local_img = None
            if image_url:
                local_img = download_image(image_url, filename_prefix="fb_upload")

            res = post_to_facebook(
                message=text_to_post,
                image_path=local_img,
                image_url=image_url
            )
            if res.get("success"):
                mark_as_posted(art["url"])
                self.log(f"🎉 โพสต์สำเร็จเรียบร้อย! (Mode: {res.get('mode', 'live')})")
                self.after(500, self.refresh_news_cards)
            else:
                self.log(f"❌ โพสต์ล้มเหลว: {res.get('error')}")

        threading.Thread(target=worker, daemon=True).start()

    # -------------------------------------------------------------
    # MANUAL FETCH & REWRITE PIPELINE
    # -------------------------------------------------------------
    def start_manual_fetch(self):
        """เริ่มดึงข่าวใหม่และเขียนสำนวนด้วย AI"""
        self.btn_fetch_once.configure(state="disabled", text="⏳ กำลังดึงข่าว...")
        self.tabview.set("📜 บันทึกการทำงาน (Live Logs)")

        def worker():
            try:
                self.log("🔍 เริ่มต้นตรวจสอบข่าวฟุตบอลลิเวอร์พูลจากทุกสำนัก...")
                articles = fetch_all_new_articles()
                if not articles:
                    self.log("☕ ไม่มีข่าวใหม่ที่ยังไม่เคยโพสต์ในขณะนี้")
                else:
                    self.log(f"📦 พบข่าวใหม่ทั้งหมด {len(articles)} ข่าว (จะประมวลผล 2 ข่าวล่าสุด)")
                    for art in articles[:2]:
                        url = art["url"]
                        title = art["title"]
                        source = art["source"]
                        img = art.get("image_url")
                        summary = art.get("summary", "")
                        pub = art.get("published_at", "")

                        self.log(f"\n📰 กำลังเรียบเรียงข่าว: [{source}] {title}")
                        save_article(url, title, source, img, summary, pub)

                        # ดาวน์โหลดรูป
                        local_img = None
                        if img:
                            local_img = download_image(img, filename_prefix=f"{source}_{title[:20]}")

                        # AI เขียนใหม่
                        rewritten = rewrite_article(art)
                        if rewritten:
                            update_rewritten(url, rewritten)
                            # โพสต์หรือเซฟพรีวิว
                            post_to_facebook(rewritten, local_img, img)
                            mark_as_posted(url)
                            self.log("✅ เรียบเรียงและสร้างโพสต์เรียบร้อย!")
                        
                        time.sleep(2)

            except Exception as e:
                self.log(f"❌ เกิดข้อผิดพลาด: {e}")
            finally:
                self.btn_fetch_once.configure(state="normal", text="⚡ ดึงข่าว & เรียบเรียงทันที")
                self.after(500, self.refresh_news_cards)

        threading.Thread(target=worker, daemon=True).start()

    # -------------------------------------------------------------
    # AUTO-RUN BACKGROUND THREAD
    # -------------------------------------------------------------
    def toggle_auto_run(self):
        if not self.is_auto_running:
            # เริ่ม Auto-Run
            self.is_auto_running = True
            self.btn_auto_toggle.configure(
                text="⏹️ หยุด Auto-Run",
                fg_color=COLOR_LFC_DARK_RED,
                hover_color="#550000"
            )
            interval_mins = int(self.combo_interval.get())
            self.log(f"⏱️ เริ่มต้นระบบ Auto-Bot ทำงานอัตโนมัติทุกๆ {interval_mins} นาที")

            def auto_worker():
                while self.is_auto_running:
                    self.log(f"🔄 [Auto-Bot] กำลังเริ่มรอบตรวจข่าวอัตโนมัติ...")
                    try:
                        articles = fetch_all_new_articles()
                        for art in articles[:2]:
                            if not self.is_auto_running:
                                break
                            if is_article_seen(art["url"]):
                                continue
                            
                            save_article(art["url"], art["title"], art["source"], art.get("image_url"), art.get("summary", ""), art.get("published_at", ""))
                            local_img = download_image(art.get("image_url"), filename_prefix="auto_" + art["title"][:20]) if art.get("image_url") else None
                            rewritten = rewrite_article(art)
                            if rewritten:
                                update_rewritten(art["url"], rewritten)
                                post_to_facebook(rewritten, local_img, art.get("image_url"))
                                mark_as_posted(art["url"])
                            time.sleep(3)
                        
                        self.after(500, self.refresh_news_cards)
                    except Exception as e:
                        self.log(f"⚠️ [Auto-Bot Error]: {e}")

                    # นับถอยหลังรอรอบต่อไป
                    for _ in range(interval_mins * 60):
                        if not self.is_auto_running:
                            break
                        time.sleep(1)

            self.auto_thread = threading.Thread(target=auto_worker, daemon=True)
            self.auto_thread.start()
        else:
            # หยุด Auto-Run
            self.is_auto_running = False
            self.btn_auto_toggle.configure(
                text="⏱️ เริ่มรันอัตโนมัติ (Auto-Run)",
                fg_color="#1F6AA5",
                hover_color="#144870"
            )
            self.log("⏹️ หยุดระบบ Auto-Bot เรียบร้อยแล้ว")

    # -------------------------------------------------------------
    # SETTINGS VIEW & FACEBOOK CONNECTION TEST
    # -------------------------------------------------------------
    def _create_settings_view(self):
        """สร้างหน้าจอตั้งค่า Facebook API และ Gemini API"""
        self.tab_settings.grid_columnconfigure(0, weight=1)
        self.tab_settings.grid_rowconfigure(0, weight=1)

        scroll_settings = ctk.CTkScrollableFrame(self.tab_settings, fg_color="transparent")
        scroll_settings.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        scroll_settings.grid_columnconfigure(0, weight=1)

        # 1. Section: Facebook Page API
        fb_box = ctk.CTkFrame(scroll_settings, fg_color="#18181C", corner_radius=10)
        fb_box.pack(fill="x", padx=10, pady=(0, 15))
        fb_box.grid_columnconfigure(1, weight=1)

        lbl_fb_header = ctk.CTkLabel(
            fb_box,
            text="🔵 Facebook Page Configuration (ตั้งค่าการโพสต์ Facebook)",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#1877F2"
        )
        lbl_fb_header.pack(anchor="w", padx=16, pady=(14, 6))

        # Page ID Entry
        lbl_pid = ctk.CTkLabel(fb_box, text="1. Facebook Page ID (รหัสหน้าเพจ):", font=ctk.CTkFont(size=12, weight="bold"))
        lbl_pid.pack(anchor="w", padx=16, pady=(6, 2))
        self.ent_page_id = ctk.CTkEntry(fb_box, placeholder_text="เช่น 102938475612345", height=34)
        self.ent_page_id.pack(fill="x", padx=16, pady=(0, 10))
        if config.FB_PAGE_ID:
            self.ent_page_id.insert(0, config.FB_PAGE_ID)

        # Page Access Token Entry
        lbl_token = ctk.CTkLabel(fb_box, text="2. Facebook Page Access Token (โทเคนเพจที่ขึ้นต้นด้วย EAAB...):", font=ctk.CTkFont(size=12, weight="bold"))
        lbl_token.pack(anchor="w", padx=16, pady=(6, 2))
        self.ent_page_token = ctk.CTkEntry(fb_box, placeholder_text="วาง Page Access Token ที่นี่...", show="*", height=34)
        self.ent_page_token.pack(fill="x", padx=16, pady=(0, 10))
        if config.FB_PAGE_ACCESS_TOKEN:
            self.ent_page_token.insert(0, config.FB_PAGE_ACCESS_TOKEN)

        # Toggle Show/Hide Token
        self.chk_show_token = ctk.CTkCheckBox(
            fb_box,
            text="แสดง Token",
            font=ctk.CTkFont(size=11),
            command=self._toggle_token_visibility
        )
        self.chk_show_token.pack(anchor="w", padx=16, pady=(0, 10))

        # Test Facebook Button
        btn_test_fb = ctk.CTkButton(
            fb_box,
            text="🔍 ทดสอบการเชื่อมต่อ Facebook Page",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#1877F2",
            hover_color="#0F5FCC",
            height=32,
            command=self.test_facebook_connection
        )
        btn_test_fb.pack(anchor="w", padx=16, pady=(0, 14))

        self.lbl_fb_test_result = ctk.CTkLabel(fb_box, text="", font=ctk.CTkFont(size=12))
        self.lbl_fb_test_result.pack(anchor="w", padx=16, pady=(0, 10))

        # 2. Section: Gemini API
        gemini_box = ctk.CTkFrame(scroll_settings, fg_color="#18181C", corner_radius=10)
        gemini_box.pack(fill="x", padx=10, pady=(0, 15))

        lbl_gem_header = ctk.CTkLabel(
            gemini_box,
            text="✨ Google Gemini API Key (คีย์สำหรับ AI แปลและเขียนข่าว)",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#8AB4F8"
        )
        lbl_gem_header.pack(anchor="w", padx=16, pady=(14, 6))

        self.ent_gemini_key = ctk.CTkEntry(gemini_box, placeholder_text="AQ.Ab8RN... หรือ AIzaSy...", height=34)
        self.ent_gemini_key.pack(fill="x", padx=16, pady=(0, 14))
        if config.GEMINI_API_KEY:
            self.ent_gemini_key.insert(0, config.GEMINI_API_KEY)

        # 3. Action: บันทึกการตั้งค่า
        btn_save_settings = ctk.CTkButton(
            scroll_settings,
            text="💾 บันทึกการตั้งค่าทั้งหมดลงไฟล์ .env",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLOR_SUCCESS,
            hover_color="#1E7E34",
            height=42,
            command=self.save_settings_from_gui
        )
        btn_save_settings.pack(fill="x", padx=10, pady=(5, 15))

        # 4. กล่องแนะนำวิธีขอ Facebook Token
        guide_box = ctk.CTkFrame(scroll_settings, fg_color="#18181C", corner_radius=10)
        guide_box.pack(fill="x", padx=10, pady=(0, 20))

        lbl_guide_title = ctk.CTkLabel(
            guide_box,
            text="📖 วิธีหา Page ID และขอ Page Access Token (ฟรี):",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLOR_GOLD
        )
        lbl_guide_title.pack(anchor="w", padx=16, pady=(12, 6))

        guide_text = (
            "1. เข้าไปที่: https://developers.facebook.com/tools/explorer/\n"
            "2. เลือก Meta App ของคุณ (หากยังไม่มี ให้กดสร้าง App ประเภท 'Business' หรือ 'Other')\n"
            "3. ในช่อง 'User or Page' ➔ ให้คลิกเลือกเป็น 'Facebook Page ของคุณ' (ไม่ใช่ User Token)\n"
            "4. ในช่อง Permissions ➔ เพิ่มสิทธิ์: pages_manage_posts, pages_read_engagement\n"
            "5. กดปุ่ม 'Generate Access Token' แล้วคัดลอกมาวางในช่องด้านบนได้เลย\n"
            "6. Page ID: ดูได้จาก URL หน้าเพจของคุณ หรือในหัวข้อ 'เกี่ยวกับ (About)' ของหน้าเพจ"
        )
        lbl_guide = ctk.CTkLabel(guide_box, text=guide_text, justify="left", font=ctk.CTkFont(size=12), text_color="#C0C0C0")
        lbl_guide.pack(anchor="w", padx=16, pady=(0, 14))

    def _toggle_token_visibility(self):
        if self.chk_show_token.get() == 1:
            self.ent_page_token.configure(show="")
        else:
            self.ent_page_token.configure(show="*")

    def save_settings_from_gui(self):
        """บันทึกค่าจาก GUI กลับลงไฟล์ .env และอัปเดตโมดูล config"""
        page_id = self.ent_page_id.get().strip()
        page_token = self.ent_page_token.get().strip()
        gemini_key = self.ent_gemini_key.get().strip()
        dry_run_str = "true" if self.switch_dry_run.get() == 1 else "false"
        interval = self.combo_interval.get()

        env_path = config.BASE_DIR / ".env"
        env_content = f"""# ==========================================
# LIVERPOOL FC AUTO NEWS BOT CONFIGURATION
# ==========================================

# 1. Google Gemini API Key
GEMINI_API_KEY={gemini_key}

# 2. Facebook Page Configuration
FB_PAGE_ID={page_id}
FB_PAGE_ACCESS_TOKEN={page_token}

# 3. Mode Settings
DRY_RUN={dry_run_str}

# 4. Interval (นาที) สำหรับโหมดรันวนอัตโนมัติ
CHECK_INTERVAL_MINUTES={interval}
"""
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(env_content)

        # อัปเดตตัวแปรใน config module
        config.FB_PAGE_ID = page_id
        config.FB_PAGE_ACCESS_TOKEN = page_token
        config.GEMINI_API_KEY = gemini_key
        config.DRY_RUN = dry_run_str == "true"
        config.CHECK_INTERVAL_MINUTES = int(interval)

        # อัปเดต Label สถานะ
        self.lbl_gemini.configure(text=f"• Gemini AI: {'🟢 พร้อมใช้งาน' if gemini_key else '🔴 ยังไม่ใส่คีย์'}")
        mode_text = "🟡 Dry-Run (ทดสอบ)" if config.DRY_RUN else "🟢 Live (ยิงจริง)"
        self.lbl_fb.configure(text=f"• Facebook: {mode_text}")

        self.log("💾 บันทึกการตั้งค่าลงไฟล์ .env สำเร็จเรียบร้อยแล้ว!")
        self.lbl_fb_test_result.configure(text="✅ บันทึกการตั้งค่าสำเร็จแล้ว!", text_color=COLOR_SUCCESS)

    def test_facebook_connection(self):
        """ทดสอบยิง Meta Graph API เพื่อดูว่า Token และ Page ID ถูกต้องหรือไม่"""
        page_id = self.ent_page_id.get().strip()
        page_token = self.ent_page_token.get().strip()

        if not page_id or not page_token:
            self.lbl_fb_test_result.configure(text="⚠️ กรุณากรอก Page ID และ Page Access Token ให้ครบก่อนทดสอบ", text_color="#FFA500")
            return

        self.lbl_fb_test_result.configure(text="⏳ กำลังตรวจสอบการเชื่อมต่อกับ Meta API...", text_color="#8AB4F8")

        def worker():
            import requests
            try:
                url = f"https://graph.facebook.com/v19.0/{page_id}?fields=name,id,category&access_token={page_token}"
                resp = requests.get(url, timeout=10)
                data = resp.json()

                if resp.status_code == 200 and "name" in data:
                    page_name = data.get("name")
                    msg = f"✅ เชื่อมต่อสำเร็จ! เพจ: '{page_name}' (ID: {data.get('id')})"
                    self.lbl_fb_test_result.configure(text=msg, text_color=COLOR_SUCCESS)
                    self.log(f"🎉 ตรวจสอบ Facebook API สำเร็จ: {msg}")
                else:
                    err = data.get("error", {}).get("message", "Unknown error")
                    msg = f"❌ เชื่อมต่อไม่สำเร็จ: {err}"
                    self.lbl_fb_test_result.configure(text=msg, text_color="#FF4D4D")
                    self.log(f"⚠️ ตรวจสอบ Facebook API ล้มเหลว: {err}")
            except Exception as e:
                self.lbl_fb_test_result.configure(text=f"❌ ข้อผิดพลาด: {e}", text_color="#FF4D4D")
                self.log(f"⚠️ เกิดข้อผิดพลาดขณะเชื่อมต่อ Meta: {e}")

        threading.Thread(target=worker, daemon=True).start()

if __name__ == "__main__":
    app = LiverpoolNewsApp()
    app.mainloop()
