import os
import logging
import random
import aiohttp
import re
import asyncio
import asyncpg
import datetime
from io import BytesIO
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, PreCheckoutQueryHandler
from telegram.error import TelegramError
from openai import AsyncOpenAI
from google import genai
from google.genai import types
import uvicorn

# ==========================================
# SOZLAMALAR
# ==========================================
TOKEN = os.environ.get("TOKEN")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
DATABASE_URL = os.environ.get("DATABASE_URL")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")

ADMIN_ID = 7383782449
CHANNEL_USERNAME = "@Tommy_cheat" 
TERMUX_APK_URL = "https://github.com/termux/termux-app/releases/download/v0.118.0/termux-app_v0.118.0+github-debug_arm64-v8a.apk"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==========================================
# AI MIJOZLARI
# ==========================================
openrouter_client = AsyncOpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1", timeout=300.0) if OPENROUTER_API_KEY else None
mistral_client = AsyncOpenAI(api_key=MISTRAL_API_KEY, base_url="https://api.mistral.ai/v1", timeout=300.0) if MISTRAL_API_KEY else None
groq_client = AsyncOpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1", timeout=300.0) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

db_pool = None

# ==========================================
# MA'LUMOTLAR BAZASI (PULLIK VA FAYLLAR BILAN)
# ==========================================
async def init_db():
    global db_pool
    if not DATABASE_URL: return
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        async with db_pool.acquire() as conn:
            # Foydalanuvchilar jadvali (Premium va AI limit qo'shildi)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    lang VARCHAR(5) DEFAULT 'uz',
                    score INT DEFAULT 0,
                    is_premium BOOLEAN DEFAULT FALSE,
                    ai_requests_today INT DEFAULT 0,
                    last_ai_date DATE DEFAULT CURRENT_DATE,
                    last_bonus TIMESTAMP DEFAULT '1970-01-01 00:00:00',
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS score INT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_bonus TIMESTAMP DEFAULT '1970-01-01 00:00:00';")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_requests_today INT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_ai_date DATE DEFAULT CURRENT_DATE;")
            
            # Fayllar Markazi jadvali
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS files (
                    id SERIAL PRIMARY KEY,
                    title VARCHAR(255),
                    file_id VARCHAR(255),
                    file_type VARCHAR(20),
                    is_premium BOOLEAN DEFAULT FALSE,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
    except Exception as e:
        logging.error(f"Baza xatosi: {e}")

async def add_user(user_id, lang='uz'):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO users (user_id, lang) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET lang = EXCLUDED.lang
        ''', user_id, lang)

async def add_score(user_id, points):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        await conn.execute('UPDATE users SET score = score + $1 WHERE user_id = $2', points, user_id)

async def add_score_all(points):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        await conn.execute('UPDATE users SET score = score + $1', points)

async def get_user_profile(user_id):
    if not db_pool: return None
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow('SELECT score, last_bonus, is_premium FROM users WHERE user_id = $1', user_id)
        if not user: return None
        rank = await conn.fetchval('SELECT COUNT(*) FROM users WHERE score > $1', user['score'])
        return {"score": user['score'], "rank": rank + 1, "last_bonus": user['last_bonus'], "is_premium": user['is_premium']}

async def claim_daily_bonus(user_id):
    if not db_pool: return False
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow('SELECT last_bonus FROM users WHERE user_id = $1', user_id)
        now = datetime.datetime.now(datetime.timezone.utc)
        if user:
            if (now - user['last_bonus']).total_seconds() >= 86400:
                await conn.execute('UPDATE users SET score = score + 20, last_bonus = $1 WHERE user_id = $2', now, user_id)
                return True
        return False

# Yangi funksiyalar (Fayllar va Premium)
async def check_ai_limit(user_id):
    if user_id == ADMIN_ID: return True, 999
    if not db_pool: return True, 999
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow('SELECT is_premium, ai_requests_today, last_ai_date FROM users WHERE user_id = $1', user_id)
        today = datetime.date.today()
        
        if user['is_premium']: return True, 999
        
        # Agar kun o'zgargan bo'lsa, limitni tozalash
        if user['last_ai_date'] < today:
            await conn.execute('UPDATE users SET ai_requests_today = 1, last_ai_date = $1 WHERE user_id = $2', today, user_id)
            return True, 4
        else:
            if user['ai_requests_today'] < 5:
                await conn.execute('UPDATE users SET ai_requests_today = ai_requests_today + 1 WHERE user_id = $1', user_id)
                return True, 5 - user['ai_requests_today']
            else:
                return False, 0

async def make_premium(user_id):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        await conn.execute('UPDATE users SET is_premium = TRUE WHERE user_id = $1', user_id)

async def get_all_files():
    if not db_pool: return []
    async with db_pool.acquire() as conn:
        return await conn.fetch('SELECT id, title, is_premium FROM files ORDER BY id DESC')

async def add_file_db(title, file_id, file_type, is_premium=False):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        await conn.execute('INSERT INTO files (title, file_id, file_type, is_premium) VALUES ($1, $2, $3, $4)', title, file_id, file_type, is_premium)

def get_level(score):
    if score < 100: return "🥉 Boshlovchi"
    elif score < 300: return "🥈 O'rta"
    elif score < 600: return "🥇 Ilg'or"
    else: return "💎 Ekspert"

async def is_subscribed(user_id, context):
    if user_id == ADMIN_ID: return True 
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']: return True
        return False
    except Exception:
        return True

# ==========================================
# SUPER SKRIPTLAR BAZASI
# ==========================================
SCRIPTS_DATA = {
    "dev": {"name": "💻 Dasturlash", "items": {"python": {"name": "🐍 Python", "pkg": "python", "type": "pkg"}, "git": {"name": "🐙 Git", "pkg": "git", "type": "pkg"}, "node": {"name": "🟢 Node.js", "pkg": "nodejs", "type": "pkg"}, "curl": {"name": "📡 Curl", "pkg": "curl", "type": "pkg"}, "wget": {"name": "📥 Wget", "pkg": "wget", "type": "pkg"}, "nano": {"name": "📝 Nano", "pkg": "nano", "type": "pkg"}, "vim": {"name": "📝 Vim", "pkg": "vim", "type": "pkg"}, "micro": {"name": "📝 Micro", "pkg": "micro", "type": "pkg"}}},
    "hacking": {"name": "🛡️ Kiberxavfsizlik", "items": {"nmap": {"name": "🌐 Nmap", "pkg": "nmap", "type": "pkg"}, "hydra": {"name": "🔑 Hydra", "pkg": "hydra", "type": "pkg"}, "sqlmap": {"name": "💥 SQLmap", "pkg": "sqlmap", "type": "pip"}, "metasploit": {"name": "💀 Metasploit", "pkg": "metasploit", "type": "pkg"}, "john": {"name": "🔓 John The Ripper", "pkg": "john", "type": "pkg"}, "nikto": {"name": "🕵️ Nikto", "pkg": "nikto", "type": "pkg"}, "aircrack": {"name": "📡 Aircrack-ng", "pkg": "aircrack-ng", "type": "pkg"}, "tshark": {"name": "🦈 Tshark", "pkg": "tshark", "type": "pkg"}}},
    "media": {"name": "🎬 Media va Tarmoq", "items": {"ffmpeg": {"name": "🎞️ FFmpeg", "pkg": "ffmpeg", "type": "pkg"}, "ytdlp": {"name": "📥 yt-dlp", "pkg": "yt-dlp", "type": "pip"}, "imagemagick": {"name": "🖼️ ImageMagick", "pkg": "imagemagick", "type": "pkg"}, "openssh": {"name": "🔐 OpenSSH", "pkg": "openssh", "type": "pkg"}, "net-tools": {"name": "🌐 Net-tools", "pkg": "net-tools", "type": "pkg"}, "traceroute": {"name": "🛣️ Traceroute", "pkg": "traceroute", "type": "pkg"}, "dnsutils": {"name": "🔍 DNS Utils", "pkg": "dnsutils", "type": "pkg"}}},
    "style": {"name": "🎨 Termuxni Chiroyli Qilish", "items": {"zsh": {"name": "🐚 Zsh", "pkg": "zsh", "type": "pkg"}, "ohmyzsh": {"name": "✨ Oh-My-Zsh", "pkg": "curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh | bash", "type": "custom"}, "termuxstyle": {"name": "🎨 Termux Styling", "pkg": "termux-styling", "type": "pkg"}, "figlet": {"name": "🔠 Figlet", "pkg": "figlet", "type": "pkg"}, "lolcat": {"name": "🌈 Lolcat", "pkg": "lolcat", "type": "pkg"}, "neofetch": {"name": "💻 Neofetch", "pkg": "neofetch", "type": "pkg"}}}
}

# ==========================================
# MATNLAR LUG'ATI
# ==========================================
LESSONS = {i: i+2 for i in range(1, 46)}
LUA_LESSONS = {1: 93, 2: 94, 3: 97, 4: 98, 5: 99, 6: 100, 7: 101}
PYTHON_EXTRA_VIDEOS = [96]

TEXTS = {
    'uz': {
        'choose_lang': "👋 **Assalomu alaykum!**\n\nIltimos, o'zingizga qulay tilni tanlang:",
        'welcome': "👋 **Assalomu alaykum!**\n\nMen **Termux va Dasturlash** bo'yicha yordamchi botman.",
        'btn_termux': "📽️ TERMUX VIDEO DARSLIKLAR", 'btn_lua': "📽️ LUA PAK DARSLIK",
        'btn_apk': "📥 APK YUKLAB OLISH", 'btn_ai': "🤖 AI Dasturchi (Kod)",
        'btn_profile': "👤 Mening profilim", 'btn_top': "🏆 Top 10",
        'btn_quiz': "🧠 Test (Ball)", 'btn_security': "🛡️ Kiberxavfsizlik",
        'btn_support': "✉️ Admin", 'btn_tip': "💡 Maslahat",
        'btn_cheatsheet': "📜 Buyruqlar", 'btn_change_lang': "🌐 Til",
        'btn_scripts': "📦 Skript Yaratish", 'btn_files': "🗂 Fayllar Markazi", 'btn_premium': "💎 Premium Obuna",
        'btn_back': "🔙 Bosh menyu", 'btn_prev': "⬅️", 'btn_next': "➡️",
        'btn_python': "🐍 PYTHON", 'btn_lessons_menu': "📚 Menyu", 'btn_back_cheat': "🔙 Orqaga",
        
        'force_sub_text': f"⚠️ **Diqqat!**\n\nBotdan to'liq foydalanish uchun kanalimizga a'zo bo'ling:",
        'btn_join': "📢 A'zo bo'lish", 'btn_check': "✅ Tekshirish", 'force_sub_error': "❌ Siz hali a'zo bo'lmadingiz!",
        
        'script_cat_menu': "📦 **Termux Skript Yaratuvchi (PRO)**\n\nKerakli bo'limni tanlang:",
        'script_items_menu': "⚙️ **{cat_name}**\n\nKerakli dasturlarni tanlang (✅ - tanlandi):",
        'btn_generate_script': "🚀 Skriptni yaratish", 'btn_clear_scripts': "🗑 Tozalash", 'btn_back_to_cats': "🔙 Bo'limlarga qaytish",
        'script_empty': "⚠️ Iltimos, avval kamida bitta dasturni tanlang!",
        'script_done': "✅ **Skriptingiz tayyor!**\n\nUni Termux'da `bash install.sh` bilan ishga tushiring.",

        # Fayllar Markazi
        'files_menu': "🗂 **Fayllar Markazi**\n\nKerakli faylni tanlang va yuklab oling:",
        'files_empty': "Hozircha fayllar yo'q. Tez orada qo'shiladi!",
        'file_sending': "⏳ Fayl yuborilmoqda...",
        'file_premium_locked': "🔒 Bu fayl faqat Premium obunachilar uchun!",

        # Premium Obuna
        'premium_menu': "💎 **Premium Obuna**\n\nPremium obuna orqali quyidagi imkoniyatlarga ega bo'lasiz:\n\n✅ **AI Dasturchidan cheksiz foydalanish** (Bepul foydalanuvchilar uchun kuniga 5 ta limit bor)\n✅ **Maxsus Premium fayllarni yuklab olish**\n✅ **Tezroq va ustuvor javob olish**\n\n💰 **Narxi:** Hozircha BEPUL!",
        'btn_buy_premium': "⭐️ Premium olish (Bepul)",
        'premium_success': "🎉 **Tabriklaymiz!** Siz Premium obunachi bo'ldingiz. Endi barcha imkoniyatlar ochiq!",
        'ai_limit_reached': "⚠️ **Limit tugadi!**\n\nBepul foydalanuvchilar uchun AI limiti kuniga 5 ta. Cheksiz foydalanish uchun Premium obuna sotib oling.",
        'btn_go_premium': "💎 Premium olish",

        # Admin Panel
        'admin_panel': "👑 **Admin Boshqaruv Paneli**\n\nKerakli bo'limni tanlang:",
        'admin_btn_stats': "📊 Statistika", 'admin_btn_bcast': "📢 Xabar yuborish",
        'admin_btn_points': "🎁 Hammaga ball berish", 'admin_btn_add_file': "➕ Fayl qo'shish",
        'admin_btn_close': "❌ Yopish",
        'admin_points_prompt': "🎁 **Aksiya!**\n\nBarcha foydalanuvchilarga qancha ball qo'shmoqchisiz? (Faqat raqam yozing)",
        'admin_points_done': "✅ Barcha foydalanuvchilarga {points} ball qo'shildi!",
        'admin_file_wait': "📂 **Faylni yuboring** (Hujjat, Video, Rasm, APK va h.k.):",
        'admin_file_title': "✍️ Endi ushbu fayl uchun **nomi va tavsifini** yozing:",
        'admin_file_saved': "✅ Fayl muvaffaqiyatli saqlandi!",
        'admin_file_cancel': "❌ Bekor qilindi.",

        'text_page': "📚 **Darsliklar**\n\nSahifa: {page} / 5", 'text_lua': "📚 **LUA DARSLIKLARI**",
        'text_python_done': "Mana Python darsligi! ✅", 'text_error_vid': "❌ Xatolik!",
        'tip_header': "💡 **Maslahat:**\n\n", 'cheatsheet_menu': "📜 **Buyruqlar**\n\nBo'limni tanlang:",
        'cat_files': "📁 Fayllar", 'cat_packages': "📦 Paketlar", 'cat_network': "🌐 Tarmoq", 'cat_system': "⚙️ Tizim",
        'apk_caption': "📱 **Termux APK**", 'apk_file_name': "Termux.apk", 'apk_loading': "⏳...", 'apk_too_big': "⚠️", 'apk_error': "❌ Xatolik!",
        'support_prompt': "✉️ **Admin**\n\nXabaringizni yozib qoldiring:", 'support_sent': "✅ Yuborildi!", 'support_reply': "📬 **Admin:**\n\n",
        
        'profile_text': "👤 **Profil**\n\n⭐ **Ball:** {score}\n🏅 **Daraja:** {level}\n📊 **O'rin:** #{rank}\n💎 **Holat:** {status}",
        'btn_daily_bonus': "🎁 Kunlik bonus (+20)", 'bonus_claimed': "✅ **+20 ball!**", 'bonus_wait': "⏳ Ertaga qayta keling!",
        'top_text': "🏆 **Top 10:**\n\n{list}",
        'quiz_start': "🧠 **Test!** To'g'ri javob: **+10 ball**.",
        'quiz_correct': "✅ **To'g'ri!** 🎉 (+10 ball)", 'quiz_wrong': "❌ **Xato!** Javob: **{answer}**",
        
        'sec_menu': "🛡️ **Kiberxavfsizlik Asboblari**\n\n⚠️ Faqat o'z tizimlaringizni tekshirish uchun!",
        'sec_info': "🔍 Ma'lumot yig'ish", 'sec_pass': "🔑 Parol hujumlari", 'sec_exploit': "💥 Zaifliklar", 'sec_network': "📡 Tarmoq tahlili",
        'sec_info_text': "Nmap: `pkg install nmap`", 'sec_pass_text': "Hydra: `pkg install hydra`", 'sec_exploit_text': "SQLmap: `pip install sqlmap`", 'sec_network_text': "Tshark: `pkg install tshark`",
        
        'admin_bcast_start': "📢 Xabar yuboring:", 'admin_bcast_wait': "⏳...", 'admin_bcast_done': "✅ Yuborildi: {success}, Xato: {fail}", 'admin_bcast_cancel': "❌ Bekor",
        'ai_prompt': "🤖 **AI Dasturchi**\n\nDasturlash bo'yicha topshiriq bering yoki kod faylini tashlang.",
        'ai_wait': "🧠 AI ishlamoqda...", 'ai_error': "❌ Xatolik: {error}", 'ai_code_found': "✅ **Kod!**", 'ai_no_code': "🤖 **AI:**\n\n{text}",
        'ai_vision_error': "⚠️ Rasm xato.", 'ai_unsupported_file': "⚠️ Faqat kod fayllari.", 'ai_video_error': "🎥 Video yo'q.",
        'ai_file_too_large': "⚠️ Katta fayl.", 'ai_text_too_long': "⚠️ Uzun kod.", 'ai_not_coding': "🤖 Faqat dasturlash.",
        'ai_limit_info': "ℹ️ *Bugun uchun qolgan limitingiz: {limit} ta*"
    },
    'ru': {'choose_lang': "Выберите язык:", 'welcome': "👋 Я помощник **Termux**.", 'btn_termux': "📽️ УРОКИ", 'btn_lua': "📽️ LUA", 'btn_apk': "📥 APK", 'btn_ai': "🤖 AI Код", 'btn_profile': "👤 Профиль", 'btn_top': "🏆 Топ 10", 'btn_quiz': "🧠 Тест", 'btn_security': "🛡️ Безопасность", 'btn_support': "✉️ Админу", 'btn_tip': "💡 Совет", 'btn_cheatsheet': "📜 Команды", 'btn_change_lang': "🌐 Язык", 'btn_scripts': "📦 Скрипты", 'btn_files': "🗂 Файлы", 'btn_premium': "💎 Премиум", 'btn_back': "🔙 Назад", 'btn_prev': "⬅️", 'btn_next': "➡️", 'btn_python': "🐍 PYTHON", 'btn_lessons_menu': "📚", 'btn_back_cheat': "🔙", 'force_sub_text': "⚠️ Подпишитесь:", 'btn_join': "📢 Подписаться", 'btn_check': "✅ Проверить", 'force_sub_error': "❌ Вы не подписались!", 'script_cat_menu': "📦 **Генератор**", 'script_items_menu': "⚙️ **{cat_name}**", 'btn_generate_script': "🚀 Создать", 'btn_clear_scripts': "🗑 Очистить", 'btn_back_to_cats': "🔙 Назад", 'script_empty': "⚠️ Выберите программу!", 'script_done': "✅ Готово!", 'files_menu': "🗂 **Файлы**", 'files_empty': "Нет файлов.", 'file_sending': "⏳...", 'file_premium_locked': "🔒 Только для Премиум!", 'premium_menu': "💎 **Премиум**", 'btn_buy_premium': "⭐️ Получить Премиум (Бесплатно)", 'premium_success': "🎉 Вы Премиум!", 'ai_limit_reached': "⚠️ Лимит (5/день). Купите Премиум.", 'btn_go_premium': "💎 Купить", 'admin_panel': "👑 **Панель Админа**", 'admin_btn_stats': "📊", 'admin_btn_bcast': "📢", 'admin_btn_points': "🎁", 'admin_btn_add_file': "➕ Файл", 'admin_btn_close': "❌", 'admin_points_prompt': "🎁 Баллы:", 'admin_points_done': "✅ {points} добавлено!", 'admin_file_wait': "📂 Отправьте файл:", 'admin_file_title': "✍️ Название:", 'admin_file_saved': "✅ Сохранено!", 'admin_file_cancel': "❌ Отменено.", 'text_page': "📚 {page}/5", 'text_lua': "📚 LUA", 'text_python_done': "✅", 'text_error_vid': "❌", 'tip_header': "💡", 'cheatsheet_menu': "📜", 'cat_files': "📁", 'cat_packages': "📦", 'cat_network': "🌐", 'cat_system': "⚙️", 'apk_caption': "📱", 'apk_file_name': "T.apk", 'apk_loading': "⏳", 'apk_too_big': "⚠️", 'apk_error': "❌", 'support_prompt': "✉️", 'support_sent': "✅", 'support_reply': "📬", 'profile_text': "👤 **Профиль**\n⭐ {score}\n🏅 {level}\n📊 #{rank}\n💎 {status}", 'btn_daily_bonus': "🎁 Бонус (+20)", 'bonus_claimed': "✅ +20!", 'bonus_wait': "⏳ Завтра!", 'top_text': "🏆 **Топ 10:**\n{list}", 'quiz_start': "🧠 Тест", 'quiz_correct': "✅ +10!", 'quiz_wrong': "❌ {answer}", 'sec_menu': "🛡️", 'sec_info': "🔍", 'sec_pass': "🔑", 'sec_exploit': "💥", 'sec_network': "📡", 'sec_info_text': "Nmap", 'sec_pass_text': "Hydra", 'sec_exploit_text': "SQLmap", 'sec_network_text': "Tshark", 'admin_bcast_start': "📢", 'admin_bcast_wait': "⏳", 'admin_bcast_done': "✅ {success}, {fail}", 'admin_bcast_cancel': "❌", 'ai_prompt': "🤖 AI", 'ai_wait': "🧠...", 'ai_error': "❌ {error}", 'ai_code_found': "✅", 'ai_no_code': "🤖 {text}", 'ai_vision_error': "⚠️", 'ai_unsupported_file': "⚠️", 'ai_video_error': "🎥", 'ai_file_too_large': "⚠️", 'ai_text_too_long': "⚠️", 'ai_not_coding': "🤖", 'ai_limit_info': "ℹ️ Лимит: {limit}"},
    'en': {'choose_lang': "Select language:", 'welcome': "👋 **Termux** assistant.", 'btn_termux': "📽️ LESSONS", 'btn_lua': "📽️ LUA", 'btn_apk': "📥 APK", 'btn_ai': "🤖 AI Code", 'btn_profile': "👤 Profile", 'btn_top': "🏆 Top 10", 'btn_quiz': "🧠 Quiz", 'btn_security': "🛡️ Security", 'btn_support': "✉️ Admin", 'btn_tip': "💡 Tip", 'btn_cheatsheet': "📜 Commands", 'btn_change_lang': "🌐 Language", 'btn_scripts': "📦 Scripts", 'btn_files': "🗂 File Center", 'btn_premium': "💎 Premium", 'btn_back': "🔙 Back", 'btn_prev': "⬅️", 'btn_next': "➡️", 'btn_python': "🐍 PYTHON", 'btn_lessons_menu': "📚", 'btn_back_cheat': "🔙", 'force_sub_text': "⚠️ Join our channel:", 'btn_join': "📢 Join", 'btn_check': "✅ Check", 'force_sub_error': "❌ You haven't joined!", 'script_cat_menu': "📦 **Script Generator**", 'script_items_menu': "⚙️ **{cat_name}**", 'btn_generate_script': "🚀 Generate", 'btn_clear_scripts': "🗑 Clear", 'btn_back_to_cats': "🔙 Back", 'script_empty': "⚠️ Select at least one!", 'script_done': "✅ Done!", 'files_menu': "🗂 **File Center**", 'files_empty': "No files yet.", 'file_sending': "⏳...", 'file_premium_locked': "🔒 Premium only!", 'premium_menu': "💎 **Premium**", 'btn_buy_premium': "⭐️ Get Premium (Free)", 'premium_success': "🎉 You are Premium!", 'ai_limit_reached': "⚠️ Limit reached (5/day). Buy Premium.", 'btn_go_premium': "💎 Go Premium", 'admin_panel': "👑 **Admin Panel**", 'admin_btn_stats': "📊", 'admin_btn_bcast': "📢", 'admin_btn_points': "🎁", 'admin_btn_add_file': "➕ Add File", 'admin_btn_close': "❌", 'admin_points_prompt': "🎁 Points to add:", 'admin_points_done': "✅ Added {points}!", 'admin_file_wait': "📂 Send file:", 'admin_file_title': "✍️ File title:", 'admin_file_saved': "✅ Saved!", 'admin_file_cancel': "❌ Cancelled.", 'text_page': "📚 {page}/5", 'text_lua': "📚 LUA", 'text_python_done': "✅", 'text_error_vid': "❌", 'tip_header': "💡", 'cheatsheet_menu': "📜", 'cat_files': "📁", 'cat_packages': "📦", 'cat_network': "🌐", 'cat_system': "⚙️", 'apk_caption': "📱", 'apk_file_name': "T.apk", 'apk_loading': "⏳", 'apk_too_big': "⚠️", 'apk_error': "❌", 'support_prompt': "✉️", 'support_sent': "✅", 'support_reply': "📬", 'profile_text': "👤 **Profile**\n⭐ {score}\n🏅 {level}\n📊 #{rank}\n💎 {status}", 'btn_daily_bonus': "🎁 Bonus (+20)", 'bonus_claimed': "✅ +20!", 'bonus_wait': "⏳ Tomorrow!", 'top_text': "🏆 **Top 10:**\n{list}", 'quiz_start': "🧠 Quiz", 'quiz_correct': "✅ +10!", 'quiz_wrong': "❌ {answer}", 'sec_menu': "🛡️", 'sec_info': "🔍", 'sec_pass': "🔑", 'sec_exploit': "💥", 'sec_network': "📡", 'sec_info_text': "Nmap", 'sec_pass_text': "Hydra", 'sec_exploit_text': "SQLmap", 'sec_network_text': "Tshark", 'admin_bcast_start': "📢", 'admin_bcast_wait': "⏳", 'admin_bcast_done': "✅ {success}, {fail}", 'admin_bcast_cancel': "❌", 'ai_prompt': "🤖 AI", 'ai_wait': "🧠...", 'ai_error': "❌ {error}", 'ai_code_found': "✅", 'ai_no_code': "🤖 {text}", 'ai_vision_error': "⚠️", 'ai_unsupported_file': "⚠️", 'ai_video_error': "🎥", 'ai_file_too_large': "⚠️", 'ai_text_too_long': "⚠️", 'ai_not_coding': "🤖", 'ai_limit_info': "ℹ️ Remaining: {limit}"},
    'ar': {'choose_lang': "اختر اللغة:", 'welcome': "👋 مساعد **Termux**.", 'btn_termux': "📽️ دروس", 'btn_lua': "📽️ LUA", 'btn_apk': "📥 APK", 'btn_ai': "🤖 AI", 'btn_profile': "👤 الملف", 'btn_top': "🏆 أفضل 10", 'btn_quiz': "🧠 اختبار", 'btn_security': "🛡️ الأمن", 'btn_support': "✉️ المسؤول", 'btn_tip': "💡 نصيحة", 'btn_cheatsheet': "📜 أوامر", 'btn_change_lang': "🌐 اللغة", 'btn_scripts': "📦 سكريبتات", 'btn_files': "🗂 الملفات", 'btn_premium': "💎 بريميوم", 'btn_back': "🔙 رجوع", 'btn_prev': "⬅️", 'btn_next': "➡️", 'btn_python': "🐍 PYTHON", 'btn_lessons_menu': "📚", 'btn_back_cheat': "🔙", 'force_sub_text': "⚠️ انضم إلى قناتنا:", 'btn_join': "📢 انضم", 'btn_check': "✅ تحقق", 'force_sub_error': "❌ لم تنضم بعد!", 'script_cat_menu': "📦 **مولد**", 'script_items_menu': "⚙️ **{cat_name}**", 'btn_generate_script': "🚀 إنشاء", 'btn_clear_scripts': "🗑 مسح", 'btn_back_to_cats': "🔙 رجوع", 'script_empty': "⚠️ اختر برنامجاً!", 'script_done': "✅ جاهز!", 'files_menu': "🗂 **الملفات**", 'files_empty': "لا توجد ملفات.", 'file_sending': "⏳...", 'file_premium_locked': "🔒 بريميوم فقط!", 'premium_menu': "💎 **بريميوم**", 'btn_buy_premium': "⭐️ احصل عليه (مجاناً)", 'premium_success': "🎉 أنت بريميوم!", 'ai_limit_reached': "⚠️ الحد (5/يوم). اشتري بريميوم.", 'btn_go_premium': "💎 اشتري", 'admin_panel': "👑 **لوحة المسؤول**", 'admin_btn_stats': "📊", 'admin_btn_bcast': "📢", 'admin_btn_points': "🎁", 'admin_btn_add_file': "➕ ملف", 'admin_btn_close': "❌", 'admin_points_prompt': "🎁 نقاط:", 'admin_points_done': "✅ أضيفت {points}!", 'admin_file_wait': "📂 أرسل ملفاً:", 'admin_file_title': "✍️ اسم الملف:", 'admin_file_saved': "✅ تم الحفظ!", 'admin_file_cancel': "❌ ملغي.", 'text_page': "📚 {page}/5", 'text_lua': "📚 LUA", 'text_python_done': "✅", 'text_error_vid': "❌", 'tip_header': "💡", 'cheatsheet_menu': "📜", 'cat_files': "📁", 'cat_packages': "📦", 'cat_network': "🌐", 'cat_system': "⚙️", 'apk_caption': "📱", 'apk_file_name': "T.apk", 'apk_loading': "⏳", 'apk_too_big': "⚠️", 'apk_error': "❌", 'support_prompt': "✉️", 'support_sent': "✅", 'support_reply': "📬", 'profile_text': "👤 **الملف**\n⭐ {score}\n🏅 {level}\n📊 #{rank}\n💎 {status}", 'btn_daily_bonus': "🎁 مكافأة (+20)", 'bonus_claimed': "✅ +20!", 'bonus_wait': "⏳ غداً!", 'top_text': "🏆 **أفضل 10:**\n{list}", 'quiz_start': "🧠 اختبار", 'quiz_correct': "✅ +10!", 'quiz_wrong': "❌ {answer}", 'sec_menu': "🛡️", 'sec_info': "🔍", 'sec_pass': "🔑", 'sec_exploit': "💥", 'sec_network': "📡", 'sec_info_text': "Nmap", 'sec_pass_text': "Hydra", 'sec_exploit_text': "SQLmap", 'sec_network_text': "Tshark", 'admin_bcast_start': "📢", 'admin_bcast_wait': "⏳", 'admin_bcast_done': "✅ {success}, {fail}", 'admin_bcast_cancel': "❌", 'ai_prompt': "🤖 AI", 'ai_wait': "🧠...", 'ai_error': "❌ {error}", 'ai_code_found': "✅", 'ai_no_code': "🤖 {text}", 'ai_vision_error': "⚠️", 'ai_unsupported_file': "⚠️", 'ai_video_error': "🎥", 'ai_file_too_large': "⚠️", 'ai_text_too_long': "⚠️", 'ai_not_coding': "🤖", 'ai_limit_info': "ℹ️ المتبقي: {limit}"}
}

TIPS = [{'uz': "**Tezroq kod yozish:**\n`nano` o'rniga `micro` ishlating.", 'ru': "**Быстрое написание:**\nИспользуйте `micro`.", 'en': "**Faster coding:**\nUse `micro`.", 'ar': "**برمجة أسرع:**\nاستخدم `micro`."}]
COMMANDS_DATA = {'files': [('ls', {'uz': 'Fayllar', 'ru': 'Файлы', 'en': 'Files', 'ar': 'ملفات'})], 'packages': [('pkg update', {'uz': 'Yangilash', 'ru': 'Обновить', 'en': 'Update', 'ar': 'تحديث'})], 'network': [('ping google.com', {'uz': 'Tekshirish', 'ru': 'Проверить', 'en': 'Check', 'ar': 'فحص'})], 'system': [('clear', {'uz': 'Tozalash', 'ru': 'Очистить', 'en': 'Clear', 'ar': 'مسح'})]}
QUIZ_DATA = [
    {'q': {'uz': "Papka yaratish?", 'ru': "Команда для папки?", 'en': "Command for folder?", 'ar': "أمر لإنشاء مجلد؟"}, 'options': ['mkdir', 'cd', 'ls', 'rm'], 'answer': 'mkdir'},
    {'q': {'uz': "Fayllarni ko'rish?", 'ru': "Список файлов?", 'en': "List files?", 'ar': "عرض الملفات؟"}, 'options': ['ls', 'pwd', 'cat', 'touch'], 'answer': 'ls'},
    {'q': {'uz': "Termuxni yangilash?", 'ru': "Обновить Termux?", 'en': "Update Termux?", 'ar': "تحديث Termux؟"}, 'options': ['pkg update', 'apt-get', 'install', 'upgrade'], 'answer': 'pkg update'},
    {'q': {'uz': "Python faylini ishga tushirish?", 'ru': "Запустить Python файл?", 'en': "Run Python file?", 'ar': "تشغيل ملف بايثون؟"}, 'options': ['python file.py', 'run file.py', 'py file', 'exec file.py'], 'answer': 'python file.py'},
    {'q': {'uz': "Katalogga kirish?", 'ru': "Войти в папку?", 'en': "Enter folder?", 'ar': "الدخول إلى مجلد؟"}, 'options': ['cd', 'mv', 'cp', 'dir'], 'answer': 'cd'}
]

# ==========================================
# KLAVIATURALAR
# ==========================================
def get_lang_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="lang_uz"), InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")], [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"), InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar")]])

def get_main_menu(lang):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t['btn_termux'], callback_data="page_1"), InlineKeyboardButton(t['btn_lua'], callback_data="lua_page_1")],
        [InlineKeyboardButton(t['btn_ai'], callback_data="ai_start"), InlineKeyboardButton(t['btn_scripts'], callback_data="script_menu")],
        [InlineKeyboardButton(t['btn_files'], callback_data="files_menu"), InlineKeyboardButton(t['btn_premium'], callback_data="premium_menu")], # Yangi tugmalar
        [InlineKeyboardButton(t['btn_quiz'], callback_data="quiz_start"), InlineKeyboardButton(t['btn_top'], callback_data="top_users")],
        [InlineKeyboardButton(t['btn_profile'], callback_data="my_profile"), InlineKeyboardButton(t['btn_apk'], callback_data="send_apk")],
        [InlineKeyboardButton(t['btn_cheatsheet'], callback_data="cheatsheet"), InlineKeyboardButton(t['btn_security'], callback_data="sec_start")],
        [InlineKeyboardButton(t['btn_tip'], callback_data="daily_tip"), InlineKeyboardButton(t['btn_support'], callback_data="support_start")],
        [InlineKeyboardButton(t['btn_change_lang'], callback_data="change_lang")]
    ])

def get_premium_keyboard(lang):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t['btn_buy_premium'], callback_data="buy_premium")],
        [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]
    ])

def get_script_categories_keyboard(lang):
    t = TEXTS[lang]
    keyboard = []
    row = []
    for cat_key, cat_data in SCRIPTS_DATA.items():
        row.append(InlineKeyboardButton(cat_data['name'], callback_data=f"script_cat_{cat_key}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(keyboard)

def get_script_items_keyboard(cat_key, lang, selected_scripts):
    t = TEXTS[lang]
    cat_data = SCRIPTS_DATA[cat_key]
    keyboard = []
    row = []
    for item_key, item_data in cat_data['items'].items():
        status = "✅ " if f"{cat_key}_{item_key}" in selected_scripts else "⬜ "
        row.append(InlineKeyboardButton(f"{status}{item_data['name']}", callback_data=f"script_toggle_{cat_key}_{item_key}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton(t['btn_generate_script'], callback_data="script_generate"), InlineKeyboardButton(t['btn_clear_scripts'], callback_data="script_clear")])
    keyboard.append([InlineKeyboardButton(t['btn_back_to_cats'], callback_data="script_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard(lang):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t['admin_btn_stats'], callback_data="admin_stats")],
        [InlineKeyboardButton(t['admin_btn_bcast'], callback_data="admin_bcast")],
        [InlineKeyboardButton(t['admin_btn_points'], callback_data="admin_points")],
        [InlineKeyboardButton(t['admin_btn_add_file'], callback_data="admin_add_file")], # Yangi
        [InlineKeyboardButton(t['admin_btn_close'], callback_data="admin_close")]
    ])

def get_sub_keyboard(lang):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t['btn_join'], url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
        [InlineKeyboardButton(t['btn_check'], callback_data="check_sub")]
    ])

def get_profile_keyboard(lang):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t['btn_daily_bonus'], callback_data="daily_bonus")],
        [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]
    ])

def get_sec_menu(lang):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t['sec_info'], callback_data="sec_cat_info")], 
        [InlineKeyboardButton(t['sec_pass'], callback_data="sec_cat_pass")], 
        [InlineKeyboardButton(t['sec_exploit'], callback_data="sec_cat_exploit")], 
        [InlineKeyboardButton(t['sec_network'], callback_data="sec_cat_network")], 
        [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]
    ])

def get_lessons_keyboard(page, lang):
    t = TEXTS[lang]
    keyboard = []
    start_idx = (page - 1) * 10 + 1
    end_idx = min(page * 10, 45)
    row = []
    for i in range(start_idx, end_idx + 1):
        row.append(InlineKeyboardButton(f"🎬 {i}-darslik", callback_data=f"lesson_{i}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    nav_row = []
    if page > 1: nav_row.append(InlineKeyboardButton(t['btn_prev'], callback_data=f"page_{page-1}"))
    if end_idx < 45: nav_row.append(InlineKeyboardButton(t['btn_next'], callback_data=f"page_{page+1}"))
    if nav_row: keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(keyboard)

def get_lua_lessons_keyboard(lang):
    t = TEXTS[lang]
    keyboard, row = [], []
    for i in range(1, 8):
        row.append(InlineKeyboardButton(f"🎬 {i}-darslik", callback_data=f"lua_lesson_{i}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(keyboard)

def get_cheatsheet_keyboard(lang):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([[InlineKeyboardButton(t['cat_files'], callback_data="cat_files")], [InlineKeyboardButton(t['cat_packages'], callback_data="cat_packages")], [InlineKeyboardButton(t['cat_network'], callback_data="cat_network")], [InlineKeyboardButton(t['cat_system'], callback_data="cat_system")], [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])

def get_quiz_keyboard(options, correct_answer, lang):
    t = TEXTS[lang]
    keyboard, row = [], []
    for opt in options:
        row.append(InlineKeyboardButton(opt, callback_data=f"quiz_ans_{opt}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(keyboard)

# ==========================================
# HANDLERLAR
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.clear()
    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]
    
    if not await is_subscribed(user_id, context):
        await update.message.reply_text(t['force_sub_text'], reply_markup=get_sub_keyboard(lang), parse_mode='Markdown')
        return

    await add_user(user_id, lang)
    await update.message.reply_text(TEXTS['uz']['choose_lang'], reply_markup=get_lang_keyboard(), parse_mode='Markdown')

async def button_tap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]

    if data == "check_sub":
        if await is_subscribed(user_id, context):
            await query.answer("✅ A'zolik tasdiqlandi.")
            await query.message.delete()
            await add_user(user_id, lang)
            await context.bot.send_message(chat_id=chat_id, text=TEXTS['uz']['choose_lang'], reply_markup=get_lang_keyboard(), parse_mode='Markdown')
        else:
            await query.answer(t['force_sub_error'], show_alert=True)
        return

    if not await is_subscribed(user_id, context):
        await query.message.reply_text(t['force_sub_text'], reply_markup=get_sub_keyboard(lang), parse_mode='Markdown')
        return

    await query.answer()

    # --- FAYLLAR MARKAZI ---
    if data == "files_menu":
        files = await get_all_files()
        if not files:
            return await query.answer(t['files_empty'], show_alert=True)
        
        keyboard = []
        for f in files:
            lock = "🔒 " if f['is_premium'] else "📄 "
            keyboard.append([InlineKeyboardButton(f"{lock}{f['title']}", callback_data=f"get_file_{f['id']}")])
        keyboard.append([InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")])
        
        await query.edit_message_text(t['files_menu'], reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif data.startswith("get_file_"):
        file_id = int(data.replace("get_file_", ""))
        if not db_pool: return
        async with db_pool.acquire() as conn:
            file_data = await conn.fetchrow('SELECT * FROM files WHERE id = $1', file_id)
            user = await conn.fetchrow('SELECT is_premium FROM users WHERE user_id = $1', user_id)
        
        if file_data['is_premium'] and not user['is_premium'] and user_id != ADMIN_ID:
            return await query.answer(t['file_premium_locked'], show_alert=True)
            
        await query.answer(t['file_sending'])
        try:
            if file_data['file_type'] == 'document':
                await context.bot.send_document(chat_id=chat_id, document=file_data['file_id'], caption=f"📂 {file_data['title']}")
            elif file_data['file_type'] == 'video':
                await context.bot.send_video(chat_id=chat_id, video=file_data['file_id'], caption=f"🎬 {file_data['title']}")
            elif file_data['file_type'] == 'photo':
                await context.bot.send_photo(chat_id=chat_id, photo=file_data['file_id'], caption=f"🖼 {file_data['title']}")
        except Exception as e:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Xatolik: Faylni yuborib bo'lmadi.")

    # --- PREMIUM OBUNA ---
    elif data == "premium_menu":
        await query.edit_message_text(t['premium_menu'], reply_markup=get_premium_keyboard(lang), parse_mode='Markdown')

    elif data == "buy_premium":
        # TEST REJIMI: To'lovsiz Premium berish
        await make_premium(user_id)
        await query.edit_message_text(t['premium_success'], parse_mode='Markdown', reply_markup=get_main_menu(lang))

    # --- SKRIPT YARATISH ---
    elif data == "script_menu":
        await query.edit_message_text(t['script_cat_menu'], reply_markup=get_script_categories_keyboard(lang), parse_mode='Markdown')
    elif data.startswith("script_cat_"):
        cat_key = data.replace("script_cat_", "")
        if 'selected_scripts' not in context.user_data: context.user_data['selected_scripts'] = []
        cat_name = SCRIPTS_DATA[cat_key]['name']
        text = t['script_items_menu'].format(cat_name=cat_name)
        await query.edit_message_text(text, reply_markup=get_script_items_keyboard(cat_key, lang, context.user_data['selected_scripts']), parse_mode='Markdown')
    elif data.startswith("script_toggle_"):
        parts = data.replace("script_toggle_", "").split("_", 1)
        cat_key, item_key = parts[0], parts[1]
        script_id = f"{cat_key}_{item_key}"
        selected = context.user_data.get('selected_scripts', [])
        if script_id in selected: selected.remove(script_id)
        else: selected.append(script_id)
        context.user_data['selected_scripts'] = selected
        cat_name = SCRIPTS_DATA[cat_key]['name']
        text = t['script_items_menu'].format(cat_name=cat_name)
        await query.edit_message_reply_markup(reply_markup=get_script_items_keyboard(cat_key, lang, selected))
    elif data == "script_clear":
        context.user_data['selected_scripts'] = []
        await query.answer("🗑 Barcha tanlovlar tozalandi!")
        await query.edit_message_text(t['script_cat_menu'], reply_markup=get_script_categories_keyboard(lang), parse_mode='Markdown')
    elif data == "script_generate":
        selected = context.user_data.get('selected_scripts', [])
        if not selected: return await query.answer(t['script_empty'], show_alert=True)
        
        script_content = "#!/data/data/com.termux/files/usr/bin/bash\n\n# Ranglar\nGREEN='\\033[0;32m'\nCYAN='\\033[0;36m'\nRED='\\033[0;31m'\nYELLOW='\\033[1;33m'\nNC='\\033[0m'\n\nclear\necho -e \"${CYAN}========================================${NC}\"\necho -e \"${GREEN}🚀 TERMUX SUPER AVTOMATIK O'RNATUVCHI 🚀${NC}\"\necho -e \"${CYAN}========================================${NC}\"\necho -e \"${YELLOW}Yaratuvchi: @Tommy_1727${NC}\"\necho -e \"\"\n\necho -e \"${GREEN}[1/3] Tizim yangilanmoqda...${NC}\"\npkg update -y && pkg upgrade -y || { echo -e \"${RED}❌ Yangilashda xatolik!${NC}\"; exit 1; }\n\necho -e \"${GREEN}[2/3] Kerakli paketlar o'rnatilmoqda...${NC}\"\n"
        
        pkg_installs, pip_installs, custom_commands = [], [], []
        for script_id in selected:
            cat_key, item_key = script_id.split("_", 1)
            item_data = SCRIPTS_DATA[cat_key]['items'][item_key]
            if item_data['type'] == 'pkg' and item_data['pkg'] not in pkg_installs: pkg_installs.append(item_data['pkg'])
            elif item_data['type'] == 'pip' and item_data['pkg'] not in pip_installs: pip_installs.append(item_data['pkg'])
            elif item_data['type'] == 'custom': custom_commands.append(item_data['pkg'])

        if pkg_installs: script_content += f"pkg install -y {' '.join(pkg_installs)}\n"
        if custom_commands:
            script_content += "\necho -e \"${GREEN}[*] Qo'shimcha sozlamalar...${NC}\"\n"
            for cmd in custom_commands: script_content += f"{cmd}\n"
        if pip_installs:
            script_content += f"\necho -e \"${{GREEN}}[3/3] Python kutubxonalari...${{NC}}\"\n"
            script_content += "pip install --upgrade pip || true\n"
            script_content += f"pip install {' '.join(pip_installs)}\n"

        script_content += "\necho -e \"${CYAN}========================================${NC}\"\necho -e \"${GREEN}✅ BARCHA DASTURLAR O'RNATILDI!${NC}\"\necho -e \"${CYAN}========================================${NC}\"\n"
        
        script_file = BytesIO(script_content.encode('utf-8'))
        script_file.name = "install.sh"
        await context.bot.send_document(chat_id=chat_id, document=script_file, caption=t['script_done'], parse_mode='Markdown')
        context.user_data['selected_scripts'] = []

    # --- ADMIN PANEL ---
    elif data == "admin_stats":
        if user_id != ADMIN_ID: return
        if not db_pool: return await query.answer("Baza yo'q", show_alert=True)
        async with db_pool.acquire() as conn:
            total = await conn.fetchval('SELECT COUNT(*) FROM users')
            prem_users = await conn.fetchval('SELECT COUNT(*) FROM users WHERE is_premium = TRUE')
            top_score = await conn.fetchval('SELECT MAX(score) FROM users')
        text = f"📊 **Statistika**\n\n👥 Jami: {total} ta\n💎 Premium: {prem_users} ta\n🏆 Eng yuqori: {top_score}"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="admin_menu")]]), parse_mode='Markdown')
    elif data == "admin_points":
        if user_id != ADMIN_ID: return
        context.user_data['state'] = 'in_admin_points'
        await query.edit_message_text(t['admin_points_prompt'], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="admin_menu")]]), parse_mode='Markdown')
    elif data == "admin_bcast":
        if user_id != ADMIN_ID: return
        context.user_data['state'] = 'in_broadcast'
        await query.edit_message_text(t['admin_bcast_start'], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="admin_menu")]]), parse_mode='Markdown')
    elif data == "admin_add_file":
        if user_id != ADMIN_ID: return
        context.user_data['state'] = 'in_add_file'
        await query.edit_message_text(t['admin_file_wait'], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="admin_menu")]]), parse_mode='Markdown')
    elif data == "admin_menu":
        if user_id != ADMIN_ID: return
        await query.edit_message_text(t['admin_panel'], reply_markup=get_admin_keyboard(lang), parse_mode='Markdown')
    elif data == "admin_close":
        if user_id != ADMIN_ID: return
        await query.message.delete()

    # --- QOLGAN HANDLERLAR ---
    elif data.startswith("lang_"):
        lang = data.split("_")[1]
        context.user_data['lang'] = lang
        await add_user(user_id, lang)
        await query.edit_message_text(TEXTS[lang]['welcome'], reply_markup=get_main_menu(lang), parse_mode='Markdown')
    elif data == "change_lang":
        context.user_data.pop('lang', None)
        await query.edit_message_text(TEXTS['uz']['choose_lang'], reply_markup=get_lang_keyboard(), parse_mode='Markdown')
    elif data == "my_profile":
        profile = await get_user_profile(user_id)
        if not profile: return await query.answer("Xatolik: /start bosing.")
        level = get_level(profile['score'])
        status = "💎 Premium" if profile['is_premium'] else "🆓 Bepul"
        text = t['profile_text'].format(score=profile['score'], level=level, rank=profile['rank'], status=status)
        await query.edit_message_text(text, reply_markup=get_profile_keyboard(lang), parse_mode='Markdown')
    elif data == "daily_bonus":
        success = await claim_daily_bonus(user_id)
        if success:
            await query.answer(t['bonus_claimed'], show_alert=True)
            profile = await get_user_profile(user_id)
            level = get_level(profile['score'])
            status = "💎 Premium" if profile['is_premium'] else "🆓 Bepul"
            text = t['profile_text'].format(score=profile['score'], level=level, rank=profile['rank'], status=status)
            await query.edit_message_text(text, reply_markup=get_profile_keyboard(lang), parse_mode='Markdown')
        else:
            await query.answer(t['bonus_wait'], show_alert=True)
    elif data == "top_users":
        top_users = await get_top_users() # Bu funksiya qolgan kodda bor
        top_list = ""
        for i, u in enumerate(top_users):
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "🔹"
            top_list += f"{medal} {i+1}. ID: `{u['user_id']}` — **{u['score']}** ball\n"
        if not top_list: top_list = "Hozircha bo'sh."
        await query.edit_message_text(t['top_text'].format(list=top_list), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]), parse_mode='Markdown')
    elif data == "quiz_start":
        question_data = random.choice(QUIZ_DATA)
        context.user_data['current_quiz'] = question_data
        text = t['quiz_start'] + f"\n\n❓ **{question_data['q'][lang]}**"
        keyboard = get_quiz_keyboard(question_data['options'], question_data['answer'], lang)
        try: await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='Markdown')
        except: await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode='Markdown')
    elif data.startswith("quiz_ans_"):
        selected_ans = data.replace("quiz_ans_", "")
        question_data = context.user_data.get('current_quiz')
        if not question_data: return await query.answer("Xatolik.")
        context.user_data['current_quiz'] = None 
        correct_ans = question_data['answer']
        if selected_ans == correct_ans:
            text = t['quiz_correct']
            await add_score(user_id, 10)
        else:
            text = t['quiz_wrong'].format(answer=correct_ans)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_quiz'], callback_data="quiz_start")], [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])
        try: await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='Markdown')
        except: pass
    elif data == "ai_start":
        can_use, limit_left = await check_ai_limit(user_id)
        if not can_use:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_go_premium'], callback_data="premium_menu")], [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])
            return await query.edit_message_text(t['ai_limit_reached'], reply_markup=keyboard, parse_mode='Markdown')
            
        context.user_data['state'] = 'in_ai'
        prompt_text = t['ai_prompt']
        if limit_left < 999:
            prompt_text += "\n\n" + t['ai_limit_info'].format(limit=limit_left)
        await query.edit_message_text(prompt_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]), parse_mode='Markdown')
    elif data == "sec_start":
        try: await query.edit_message_text(text=t['sec_menu'], reply_markup=get_sec_menu(lang), parse_mode='Markdown')
        except: pass
    elif data == "sec_cat_info": 
        try: await query.edit_message_text(text=t['sec_info_text'], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back_cheat'], callback_data="sec_start")]]), parse_mode='Markdown')
        except: pass
    elif data == "sec_cat_pass": 
        try: await query.edit_message_text(text=t['sec_pass_text'], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back_cheat'], callback_data="sec_start")]]), parse_mode='Markdown')
        except: pass
    elif data == "sec_cat_exploit": 
        try: await query.edit_message_text(text=t['sec_exploit_text'], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back_cheat'], callback_data="sec_start")]]), parse_mode='Markdown')
        except: pass
    elif data == "sec_cat_network": 
        try: await query.edit_message_text(text=t['sec_network_text'], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back_cheat'], callback_data="sec_start")]]), parse_mode='Markdown')
        except: pass
    elif data == "support_start":
        context.user_data['state'] = 'in_support'
        try: await query.edit_message_text(text=t['support_prompt'], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]), parse_mode='Markdown')
        except: pass
    elif data == "send_apk":
        msg = await context.bot.send_message(chat_id=chat_id, text=t['apk_loading'])
        await query.message.delete()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(TERMUX_APK_URL) as response:
                    if response.status == 200:
                        apk_content = await response.read()
                        if len(apk_content) > 50 * 1024 * 1024: await msg.edit_text(t['apk_too_big'], parse_mode='Markdown')
                        else:
                            apk_file = BytesIO(apk_content)
                            apk_file.name = t['apk_file_name']
                            await context.bot.send_document(chat_id=chat_id, document=apk_file, caption=t['apk_caption'], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]))
                            await msg.delete()
                    else: raise Exception("HTTP Error")
        except Exception: await msg.edit_text(t['apk_error'])
    elif data == "daily_tip":
        random_tip = random.choice(TIPS)[lang]
        text = t['tip_header'] + random_tip
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])
        try: await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='Markdown')
        except: pass
    elif data == "cheatsheet":
        try: await query.edit_message_text(text=t['cheatsheet_menu'], reply_markup=get_cheatsheet_keyboard(lang), parse_mode='Markdown')
        except: pass
    elif data.startswith("cat_"):
        category = data.split("_")[1]
        commands = COMMANDS_DATA.get(category, [])
        text = f"**{t['cat_'+category]}**\n\n"
        for cmd, desc in commands: text += f"• `{cmd}` - {desc[lang]}\n"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back_cheat'], callback_data="cheatsheet")], [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])
        try: await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='Markdown')
        except: pass
    elif data.startswith("page_"):
        page = int(data.split("_")[1])
        text = t['text_page'].format(page=page)
        try: await query.edit_message_text(text=text, reply_markup=get_lessons_keyboard(page, lang), parse_mode='Markdown')
        except: pass
    elif data.startswith("lesson_"):
        lesson_num = int(data.split("_")[1])
        message_id = LESSONS[lesson_num]
        video_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_lessons_menu'], callback_data="page_1")]])
        try:
            await context.bot.copy_message(chat_id=chat_id, from_chat_id=CHANNEL_USERNAME, message_id=message_id, reply_markup=video_keyboard)
            await query.message.delete()
        except TelegramError: await context.bot.send_message(chat_id=chat_id, text=t['text_error_vid'], parse_mode='Markdown')
    elif data == "lua_page_1":
        try: await query.edit_message_text(text=t['text_lua'], reply_markup=get_lua_lessons_keyboard(lang), parse_mode='Markdown')
        except: pass
    elif data.startswith("lua_lesson_"):
        lesson_num = int(data.split("_")[2])
        message_id = LUA_LESSONS[lesson_num]
        buttons = []
        if lesson_num == 2: buttons.append([InlineKeyboardButton(t['btn_python'], callback_data="python_extra")])
        buttons.append([InlineKeyboardButton(t['btn_lessons_menu'], callback_data="lua_page_1")])
        video_keyboard = InlineKeyboardMarkup(buttons)
        try:
            await context.bot.copy_message(chat_id=chat_id, from_chat_id=CHANNEL_USERNAME, message_id=message_id, reply_markup=video_keyboard)
            await query.message.delete()
        except TelegramError: await context.bot.send_message(chat_id=chat_id, text=t['text_error_vid'], parse_mode='Markdown')
    elif data == "python_extra":
        try:
            for v_id in PYTHON_EXTRA_VIDEOS: await context.bot.copy_message(chat_id=chat_id, from_chat_id=CHANNEL_USERNAME, message_id=v_id)
            back_kb = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="lua_page_1")]])
            await context.bot.send_message(chat_id=chat_id, text=t['text_python_done'], reply_markup=back_kb)
        except TelegramError: pass
    elif data == "back_to_start":
        context.user_data['state'] = None
        try: await query.edit_message_text(text=t['welcome'], reply_markup=get_main_menu(lang), parse_mode='Markdown')
        except: pass

# ==========================================
# AI LOGIKASI
# ==========================================
async def handle_ai_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]

    if not await is_subscribed(user_id, context):
        await update.message.reply_text(t['force_sub_text'], reply_markup=get_sub_keyboard(lang), parse_mode='Markdown')
        return

    if not any([openrouter_client, mistral_client, groq_client, gemini_client]):
        await update.message.reply_text("❌ AI xizmatlari sozlanmagan.")
        return
    
    msg = await update.message.reply_text(t['ai_wait'])

    try:
        user_query, image_bytes, is_image = "", None, False
        if update.message.text:
            user_query = update.message.text
            if len(user_query) < 15 and user_query.lower() in ['salom', 'assalom', 'qalesan', 'nima gap', 'qalaysan', 'hi', 'hello']:
                await msg.edit_text(t['ai_not_coding']); return
            if len(user_query) > 80000: await msg.edit_text(t['ai_text_too_long']); return
        elif update.message.photo:
            photo_file = await update.message.photo[-1].get_file()
            image_bytes = await photo_file.download_as_bytearray()
            is_image = True
            user_query = "Iltimos, ushbu rasmdagi kod yoki xatoni tahlil qilib, tuzatilgan kodni yozib ber."
        elif update.message.document:
            doc = update.message.document
            if doc.file_size > 500 * 1024: await msg.edit_text(t['ai_file_too_large']); return
            if doc.file_name.endswith(('.py', '.lua', '.txt', '.js', '.cpp', '.c', '.html')):
                file_content = await (await doc.get_file()).download_as_bytearray()
                try:
                    text_content = file_content.decode('utf-8')
                    if len(text_content) > 80000: await msg.edit_text(t['ai_text_too_long']); return
                    user_query = f"Fayl nomi: {doc.file_name}\n\nKod:\n{text_content}\n\nIltimos, ushbu kodni tahlil qilib, xatolarini tuzatib, tayyor ishlaydigan holatga keltiring."
                except UnicodeDecodeError: await msg.edit_text(t['ai_unsupported_file']); return
            else: await msg.edit_text(t['ai_unsupported_file']); return
        else: await msg.edit_text(t['ai_video_error']); return

        ai_reply, error_logs = "", []
        system_prompt = "You are an expert Senior Software Engineer. Your ONLY task is to write, fix, and analyze code. Do NOT engage in casual conversation. Always provide the FULL working code inside markdown blocks (```python ... ``` or ```lua ... ```). Reply in the language the user asked in."

        if is_image and gemini_client:
            try:
                response = await gemini_client.aio.models.generate_content(model='gemini-1.5-flash', contents=[types.Part.from_text(text=system_prompt + " Look at this image and fix the code error."), types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg')])
                ai_reply = response.text
            except Exception as e: error_logs.append(f"Gemini Vision: {str(e)}")

        if not ai_reply and openrouter_client and not is_image:
            try:
                response = await openrouter_client.chat.completions.create(model="qwen/qwen-2.5-coder-32b-instruct:free", messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_query}], max_tokens=4000)
                ai_reply = response.choices[0].message.content
            except Exception as e: error_logs.append(f"OpenRouter: {str(e)}")

        if not ai_reply and mistral_client and not is_image:
            try:
                response = await mistral_client.chat.completions.create(model="codestral-latest", messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_query}], max_tokens=4000)
                ai_reply = response.choices[0].message.content
            except Exception as e: error_logs.append(f"Mistral: {str(e)}")

        if not ai_reply and groq_client and not is_image:
            try:
                response = await groq_client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_query}], max_tokens=4000)
                ai_reply = response.choices[0].message.content
            except Exception as e: error_logs.append(f"Groq: {str(e)}")

        if not ai_reply and gemini_client and not is_image:
            try:
                response = await gemini_client.aio.models.generate_content(model='gemini-1.5-flash', contents=user_query)
                ai_reply = response.text
            except Exception as e: error_logs.append(f"Gemini Text: {str(e)}")

        if not ai_reply:
            await msg.edit_text(t['ai_error'].format(error="Barcha AI limitlari band.")); return

        code_match = re.search(r'```(?:python|py|lua|javascript|js|cpp|c)?\s*(.*?)```', ai_reply, re.DOTALL | re.IGNORECASE)
        if code_match:
            code_text = code_match.group(1).strip()
            filename = "code.lua" if ("lua" in user_query.lower() or (update.message.document and update.message.document.file_name.endswith('.lua'))) else "code.py"
            lang_name = "Lua" if filename == "code.lua" else "Python"
            code_file = BytesIO(code_text.encode('utf-8'))
            code_file.name = filename
            await context.bot.send_document(chat_id=update.message.chat_id, document=code_file, caption=f"🤖 Kod fayli ({lang_name})\n\nFayl: {filename}\n\n{t['ai_code_found']}")
            explanation = ai_reply.replace(code_match.group(0), "").strip()
            if explanation: await context.bot.send_message(chat_id=update.message.chat_id, text=f"📝 AI Tushuntirmasi:\n\n{explanation}")
            await msg.delete()
        else:
            await msg.edit_text(t['ai_no_code'].format(text=ai_reply))

    except Exception as e:
        await msg.edit_text(t['ai_error'].format(error=str(e)[:100]))

# ==========================================
# XABARLAR VA ADMIN
# ==========================================
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]
    
    if context.user_data.get('state') == 'in_ai':
        await handle_ai_message(update, context); return

    if user.id == ADMIN_ID and context.user_data.get('state') == 'in_add_file':
        if update.message.document or update.message.video or update.message.photo:
            if update.message.document: file_id = update.message.document.file_id; ftype = 'document'
            elif update.message.video: file_id = update.message.video.file_id; ftype = 'video'
            else: file_id = update.message.photo[-1].file_id; ftype = 'photo'
            
            context.user_data['temp_file_id'] = file_id
            context.user_data['temp_file_type'] = ftype
            context.user_data['state'] = 'in_file_title'
            await update.message.reply_text(t['admin_file_title'], parse_mode='Markdown')
        elif update.message.text == "/cancel":
            context.user_data['state'] = None
            await update.message.reply_text(t['admin_file_cancel'])
        else:
            await update.message.reply_text("⚠️ Iltimos fayl yuboring yoki /cancel bosing.")
        return

    if user.id == ADMIN_ID and context.user_data.get('state') == 'in_file_title':
        if update.message.text:
            title = update.message.text
            file_id = context.user_data.get('temp_file_id')
            ftype = context.user_data.get('temp_file_type')
            await add_file_db(title, file_id, ftype, is_premium=False) # Bepul fayl sifatida saqlanadi
            await update.message.reply_text(t['admin_file_saved'])
            context.user_data['state'] = None
        elif update.message.text == "/cancel":
            context.user_data['state'] = None
            await update.message.reply_text(t['admin_file_cancel'])
        return

    if user.id == ADMIN_ID and context.user_data.get('state') == 'in_admin_points':
        if update.message.text.isdigit():
            points = int(update.message.text)
            await add_score_all(points)
            await update.message.reply_text(t['admin_points_done'].format(points=points), parse_mode='Markdown')
            context.user_data['state'] = None
        else:
            await update.message.reply_text("❌ Iltimos faqat raqam kiriting!")
        return

    if user.id == ADMIN_ID and context.user_data.get('state') == 'in_broadcast':
        if update.message.text == "/cancel":
            context.user_data['state'] = None
            await update.message.reply_text(t['admin_bcast_cancel']); return
        await process_broadcast(update, context); return

    if context.user_data.get('state') == 'in_support':
        if update.message.text:
            admin_msg = f"📩 Yangi murojaat!\n\n👤 Kimdan: {user.first_name} (@{user.username})\n🆔 ID: {user.id}\n\n💬 Xabar: {update.message.text}"
            try:
                await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg)
                await update.message.reply_text(t['support_sent'], reply_markup=get_main_menu(lang))
            except Exception: pass
            context.user_data['state'] = None
        return

    if user.id == ADMIN_ID and update.message.reply_to_message:
        original_text = update.message.reply_to_message.text or ""
        match = re.search(r'🆔 ID:\s*(\d+)', original_text)
        if match:
            target_user_id = int(match.group(1))
            try:
                await context.bot.send_message(chat_id=target_user_id, text=f"{t['support_reply']}{update.message.text}")
                await update.message.reply_text("✅ Javob yuborildi!")
            except Exception as e: await update.message.reply_text(f"❌ Xatolik: {e}")

async def process_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(TEXTS[context.user_data.get('lang', 'uz')]['admin_bcast_wait'])
    if not db_pool: return
    async with db_pool.acquire() as conn:
        users = await conn.fetch('SELECT user_id FROM users')
    success, fail = 0, 0
    for u in users:
        if u['user_id'] == ADMIN_ID: continue
        try:
            await context.bot.copy_message(chat_id=u['user_id'], from_chat_id=update.message.chat_id, message_id=update.message.message_id)
            success += 1; await asyncio.sleep(0.05)
        except Exception: fail += 1
    context.user_data['state'] = None
    await msg.edit_text(f"✅ Yakunlandi!\nYuborildi: {success}\nXatolik: {fail}")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    lang = context.user_data.get('lang', 'uz')
    await update.message.reply_text(TEXTS[lang]['admin_panel'], reply_markup=get_admin_keyboard(lang), parse_mode='Markdown')

# ==========================================
# VEB SERVER
# ==========================================
application = Application.builder().token(TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("admin", admin_panel)) 
application.add_handler(CallbackQueryHandler(button_tap))
application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_messages))

app = FastAPI()

@app.on_event("startup")
async def on_startup():
    await init_db()
    await application.initialize()
    webhook_url = f"{RENDER_EXTERNAL_URL}/webhook/{TOKEN}"
    await application.bot.set_webhook(url=webhook_url)
    print(f"✅ Bot, Files, Premium (FREE), va AI muvaffaqiyatli ishga tushdi!")

@app.on_event("shutdown")
async def on_shutdown():
    await application.shutdown()
    if db_pool: await db_pool.close()

@app.post(f"/webhook/{TOKEN}")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
async def read_root(): 
    return FileResponse("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
