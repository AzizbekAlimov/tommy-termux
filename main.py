import os
import logging
import random
import aiohttp
import re
import asyncio
import asyncpg
import datetime
import json
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

FORCE_SUB_CHANNEL = "@Tommy_cheat"
VIDEO_CHANNEL = "@termux_tutoril"
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
# YORDAMCHI FUNKSIYA
# ==========================================
async def edit_or_send(query, context, text, reply_markup):
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='Markdown')
    except Exception:
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(chat_id=query.message.chat_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')

# ==========================================
# MA'LUMOTLAR BAZASI
# ==========================================
async def init_db():
    global db_pool
    if not DATABASE_URL: return
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        async with db_pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    lang VARCHAR(5) DEFAULT 'uz',
                    score INT DEFAULT 0,
                    is_premium BOOLEAN DEFAULT FALSE,
                    is_banned BOOLEAN DEFAULT FALSE,
                    ai_requests_today INT DEFAULT 0,
                    last_ai_date DATE DEFAULT CURRENT_DATE,
                    last_bonus TIMESTAMP DEFAULT '1970-01-01 00:00:00',
                    last_challenge_date DATE DEFAULT '1970-01-01',
                    chat_history TEXT DEFAULT '[]',
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS score INT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_bonus TIMESTAMP DEFAULT '1970-01-01 00:00:00';")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_premium BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_requests_today INT DEFAULT 0;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_ai_date DATE DEFAULT CURRENT_DATE;")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_challenge_date DATE DEFAULT '1970-01-01';")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_history TEXT DEFAULT '[]';")
            
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

async def get_user(user_id):
    if not db_pool: return None
    async with db_pool.acquire() as conn:
        return await conn.fetchrow('SELECT * FROM users WHERE user_id = $1', user_id)

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

async def save_chat_history(user_id, history):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        await conn.execute('UPDATE users SET chat_history = $1 WHERE user_id = $2', json.dumps(history), user_id)

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

async def update_challenge_date(user_id):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        today = datetime.date.today()
        await conn.execute('UPDATE users SET last_challenge_date = $1 WHERE user_id = $2', today, user_id)

async def check_ai_limit(user_id):
    if user_id == ADMIN_ID: return True, 999
    if not db_pool: return True, 999
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow('SELECT is_premium, ai_requests_today, last_ai_date FROM users WHERE user_id = $1', user_id)
        today = datetime.date.today()
        
        if user['is_premium']: return True, 999
        
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

async def toggle_ban(user_id, ban_status):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        await conn.execute('UPDATE users SET is_banned = $1 WHERE user_id = $2', ban_status, user_id)

async def get_all_files():
    if not db_pool: return []
    async with db_pool.acquire() as conn:
        return await conn.fetch('SELECT id, title, is_premium FROM files ORDER BY id DESC')

async def add_file_db(title, file_id, file_type, is_premium=False):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        await conn.execute('INSERT INTO files (title, file_id, file_type, is_premium) VALUES ($1, $2, $3, $4)', title, file_id, file_type, is_premium)

async def get_top_users():
    if not db_pool: return []
    async with db_pool.acquire() as conn:
        return await conn.fetch('SELECT user_id, score FROM users ORDER BY score DESC LIMIT 10')

def get_level(score):
    if score < 100: return "🥉 Boshlovchi"
    elif score < 300: return "🥈 O'rta"
    elif score < 600: return "🥇 Ilg'or"
    else: return "💎 Ekspert"

async def is_subscribed(user_id, context):
    if user_id == ADMIN_ID: return True 
    try:
        member = await context.bot.get_chat_member(chat_id=FORCE_SUB_CHANNEL, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']: return True
        return False
    except Exception:
        return True

# ==========================================
# VIDEOLAR ID RATAMLARI
# ==========================================
LESSONS = {i: i+2 for i in range(1, 46)}
LESSONS[46] = 103
LUA_LESSONS = {1: 93, 2: 94, 3: 97, 4: 98, 5: 99, 6: 100, 7: 101}
PYTHON_EXTRA_VIDEOS = [96]

# ==========================================
# KUNLIK MASALALAR VA TEMALAR (KENGAYTIRILGAN)
# ==========================================
CHALLENGES_DATA = [
    {"id": 1, "text": "Python yordamida berilgan sonning faktorialini hisoblovchi funksiya yozing."},
    {"id": 2, "text": "Berilgan so'z palindrom (chapdan ham, o'ngdan ham bir xil o'qiladigan) ekanligini tekshiruvchi kod yozing."},
    {"id": 3, "text": "1 dan N gacha bo'lgan sonlar yig'indisini hisoblovchi kod yozing (sikl yordamida)."},
    {"id": 4, "text": "Berilgan ro'yxatdagi (list) eng katta va eng kichik sonlarni topuvchi funksiya yozing."},
    {"id": 5, "text": "FizzBuzz masalasi: 1 dan 100 gacha. 3 ga bo'linsa 'Fizz', 5 ga bo'linsa 'Buzz', ikkalasiga bo'linsa 'FizzBuzz', aks holda sonni chiqaring."},
    {"id": 6, "text": "Berilgan son tub (prime) yoki tub emasligini aniqlovchi funksiya yozing."},
    {"id": 7, "text": "Ro'yxatdagi takrorlanuvchi elementlarni olib tashlab, faqat unikal (unique) elementlarni qoldiruvchi kod yozing."},
    {"id": 8, "text": "Berilgan satr (string) ichidagi unli harflar sonini sanovchi funksiya yozing."},
    {"id": 9, "text": "Fibonachchi ketma-ketligining birinchi N ta hadini chiqaruvchi kod yozing."},
    {"id": 10, "text": "Berilgan ikki sonning EKUB (Eng Katta Umumiy Bo'luvchi)sini topuvchi kod yozing."}
]

THEMES_DATA = {
    "matrix": {"name": "🟢 Matrix", "bg": "#000000", "fg": "#00ff00", "cursor": "#00ff00"},
    "hacker": {"name": "🔴 Hacker", "bg": "#0a0a0a", "fg": "#ff0000", "cursor": "#ff0000"},
    "cyberpunk": {"name": "🌆 Cyberpunk", "bg": "#1a0033", "fg": "#ffff00", "cursor": "#ff00ff"},
    "dracula": {"name": "🧛 Dracula", "bg": "#282a36", "fg": "#f8f8f2", "cursor": "#50fa7b"},
    "nord": {"name": "❄️ Nord", "bg": "#2e3440", "fg": "#d8dee9", "cursor": "#88c0d0"},
    "solarized": {"name": "☀️ Solarized", "bg": "#002b36", "fg": "#839496", "cursor": "#b58900"},
    "gruvbox": {"name": "🌲 Gruvbox", "bg": "#282828", "fg": "#ebdbb2", "cursor": "#b8bb26"}
}

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
TEXTS = {
    'uz': {
        'choose_lang': "👋 **Assalomu alaykum!**\n\nIltimos, o'zingizga qulay tilni tanlang:",
        'welcome': "👋 **Assalomu alaykum!**\n\nMen **Termux va Dasturlash** bo'yicha eng ilg'or yordamchi botman.",
        'btn_termux': "📽️ TERMUX DARSLIKLAR", 'btn_lua': "📽️ LUA PAK DARSLIK",
        'btn_java': "☕ JAVA DASTURLASH", 'btn_apk': "📥 APK YUKLAB OLISH", 
        'btn_ai': "🤖 AI Dasturchi", 'btn_profile': "👤 Mening profilim",
        'btn_top': "🏆 Top 10", 'btn_quiz': "🧠 Test (Ball)", 'btn_security': "🛡️ Kiberxavfsizlik",
        'btn_support': "✉️ Admin", 'btn_tip': "💡 Maslahat", 'btn_cheatsheet': "📜 Buyruqlar",
        'btn_change_lang': "🌐 Til", 'btn_scripts': "📦 Skript Yaratish", 'btn_files': "🗂 Fayllar",
        'btn_premium': "💎 Premium Obuna", 'btn_challenge': "🧩 Kunlik Masala", 'btn_theme': "🎨 Termux Temasi",
        'btn_back': "🔙 Bosh menyu", 'btn_prev': "⬅️", 'btn_next': "➡️",
        'btn_python': "🐍 PYTHON OLISH", 'btn_lessons_menu': "📚 Menyu", 'btn_back_cheat': "🔙 Orqaga",
        
        'force_sub_text': f"⚠️ **Diqqat!**\n\nBotdan to'liq foydalanish uchun kanalimizga a'zo bo'ling:",
        'btn_join': "📢 A'zo bo'lish", 'btn_check': "✅ Tekshirish", 'force_sub_error': "❌ Siz hali a'zo bo'lmadingiz!",

        'challenge_menu': "🧩 **Kunlik Dasturlash Masalasi**\n\nQuyidagi masalani yeching va kodni yuboring. To'g'ri yechim uchun **+30 ball** beriladi!\n\n*(Kuniga faqat 1 marta)*",
        'challenge_problem': "📝 **Bugungi masala:**\n\n{text}\n\n💻 *Kodni yozib, shu chatga yuboring:*",
        'challenge_already_done': "✅ Siz bugungi masalani allaqachon yechdingiz. Ertaga yangi masala bilan qaytib keling!",
        'challenge_wait': "🤖 AI kodingizni chuqur tahlil qilmoqda, iltimos kuting...",
        'challenge_correct': "✅ **To'g'ri yechim!** 🎉\n\nSizga **+30 ball** qo'shildi!",
        'challenge_wrong': "❌ **Xato!**\n\nAI xulosasi:\n{feedback}\n\nIltimos, kodni to'g'rilab qaytadan yuboring.",
        'challenge_no_code': "⚠️ Iltimos, kodni matn ko'rinishida yoki fayl qilib yuboring.",

        'theme_menu': "🎨 **Termux Terminal Dizayni**\n\nO'zingizga yoqqan rangni tanlang. Bot sizga tayyor `colors.properties` faylini beradi.",
        'theme_send': "✅ **{theme_name} temasi tayyor!**\n\n**O'rnatish yo'riqnomasi:**\n1. Yuklab olingan `colors.properties` faylini yuboring.\n2. Uni Termux'ning `~/.termux/` papkasiga joylashtiring.\n3. Termux'da `termux-reload-settings` buyrug'ini bering.\n\nMana fayl:",

        'script_cat_menu': "📦 **Termux Skript Yaratuvchi (PRO)**\n\nKerakli bo'limni tanlang:",
        'script_items_menu': "⚙️ **{cat_name}**\n\nKerakli dasturlarni tanlang (✅ - tanlandi):",
        'btn_generate_script': "🚀 Skriptni yaratish", 'btn_clear_scripts': "🗑 Tozalash", 'btn_back_to_cats': "🔙 Bo'limlarga qaytish",
        'script_empty': "⚠️ Iltimos, avval kamida bitta dasturni tanlang!",
        'script_done': "✅ **Skriptingiz tayyor!**\n\nUni Termux'da `bash install.sh` bilan ishga tushiring.",

        'files_menu': "🗂 **Fayllar Markazi**\n\nKerakli faylni tanlang va yuklab oling:",
        'files_empty': "Hozircha fayllar yo'q. Tez orada qo'shiladi!",
        'file_sending': "⏳ Fayl yuborilmoqda...",
        'file_premium_locked': "🔒 Bu fayl faqat Premium obunachilar uchun!",

        'premium_menu': "💎 **Premium Obuna**\n\nPremium obuna orqali quyidagi imkoniyatlarga ega bo'lasiz:\n\n✅ **AI Dasturchidan cheksiz foydalanish**\n✅ **Maxsus Premium fayllarni yuklab olish**\n\n💰 **Narxi:** 50 Stars (Yulduzcha) - 1 oyga",
        'btn_buy_premium': "⭐️ 50 Stars evaziga sotib olish",
        'premium_success': "🎉 **To'lov muvaffaqiyatli o'tdi!**\n\nTabriklaymiz, siz Premium obunachi bo'ldingiz.",
        'ai_limit_reached': "⚠️ **Limit tugadi!**\n\nBepul foydalanuvchilar uchun AI limiti kuniga 5 ta. Cheksiz foydalanish uchun Premium obuna sotib oling.",
        'btn_go_premium': "💎 Premium olish",

        'admin_panel': "👑 **Admin Boshqaruv Paneli**\n\nKerakli bo'limni tanlang:",
        'admin_btn_stats': "📊 Statistika", 'admin_btn_bcast': "📢 Xabar yuborish",
        'admin_btn_points': "🎁 Hammaga ball berish", 'admin_btn_add_file': "➕ Fayl qo'shish",
        'admin_btn_ban': "🚫 Ban qilish", 'admin_btn_unban': "✅ Unban qilish",
        'admin_btn_close': "❌ Yopish",
        'admin_points_prompt': "🎁 **Aksiya!**\n\nBarcha foydalanuvchilarga qancha ball qo'shmoqchisiz? (Faqat raqam yozing)",
        'admin_points_wait': "⏳ Ballar qo'shildi. Barchaga xabar yuborilmoqda...",
        'admin_points_done': "✅ **Aksiya yakunlandi!**\n\n🎁 Barchaga {points} ball qo'shildi.\n📩 Xabar yuborildi: {success} ta\n❌ Xatolik: {fail} ta",
        'admin_file_wait': "📂 **Faylni yuboring** (Hujjat, Video, Rasm, APK va h.k.):",
        'admin_file_title': "✍️ Endi ushbu fayl uchun **nomi va tavsifini** yozing:",
        'admin_file_saved': "✅ Fayl muvaffaqiyatli saqlandi!",
        'admin_file_cancel': "❌ Bekor qilindi.",
        'admin_ban_prompt': "🚫 **Ban qilish**\n\nFoydalanuvchining Telegram ID raqamini yuboring:",
        'admin_unban_prompt': "✅ **Unban qilish**\n\nFoydalanuvchining Telegram ID raqamini yuboring:",

        'text_page': "📚 **Darsliklar**\n\nSahifa: {page} / 5", 'text_lua': "📚 **LUA DARSLIKLARI**",
        'text_python_done': "Mana siz so'ragan Python darsligi! ✅", 'text_error_vid': "❌ **Xatolik!** Video topilmadi.\n\nIltimos, admin kanalga botni admin qilganini tekshirsin.",
        'tip_header': "💡 **Maslahat:**\n\n", 'cheatsheet_menu': "📜 **Buyruqlar**\n\nBo'limni tanlang:",
        'cat_files': "📁 Fayllar", 'cat_packages': "📦 Paketlar", 'cat_network': "🌐 Tarmoq", 'cat_system': "⚙️ Tizim",
        'apk_caption': "📱 **Termux APK**", 'apk_file_name': "Termux.apk", 'apk_loading': "⏳...", 'apk_too_big': "⚠️", 'apk_error': "❌ Xatolik!",
        'support_prompt': "✉️ **Admin**\n\nXabaringizni yozib qoldiring:", 'support_sent': "✅ Yuborildi!", 'support_reply': "📬 **Admin:**\n\n",
        
        'profile_text': "👤 **Profil**\n\n⭐ **Ball:** {score}\n🏅 **Daraja:** {level}\n📊 **O'rin:** #{rank}\n💎 **Holat:** {status}",
        'btn_daily_bonus': "🎁 Kunlik bonus (+20)", 'bonus_claimed': "✅ **+20 ball!**", 'bonus_wait': "⏳ Ertaga qayta keling!",
        'top_text': "🏆 **Top 10:**\n\n{list}",
        'quiz_start': "🧠 **Test boshlandi!** To'g'ri javob uchun **+10 ball**.\n\n❓ *Savol:*",
        'quiz_correct': "✅ **To'g'ri javob!** 🎉 (+10 ball)",
        'quiz_wrong': "❌ **Xato!** To'g'ri javob: **{answer}**",
        'quiz_end': "🎉 **Barcha savollarni yechdingiz!**\n\nYangi savollar qo'shildi, yana urinib ko'rishingiz mumkin.",
        'btn_next_quiz': "➡️ Keyingi savol",
        
        'sec_menu': "🛡️ **Kiberxavfsizlik Asboblari**\n\n⚠️ Faqat o'z tizimlaringizni tekshirish uchun!",
        'sec_info': "🔍 Ma'lumot yig'ish", 'sec_pass': "🔑 Parol hujumlari", 'sec_exploit': "💥 Zaifliklar", 'sec_network': "📡 Tarmoq tahlili",
        'sec_info_text': "Nmap: `pkg install nmap`", 'sec_pass_text': "Hydra: `pkg install hydra`", 'sec_exploit_text': "SQLmap: `pip install sqlmap`", 'sec_network_text': "Tshark: `pkg install tshark`",
        
        'admin_bcast_start': "📢 Xabar yuboring:", 'admin_bcast_wait': "⏳...", 'admin_bcast_done': "✅ Yuborildi: {success}, Xato: {fail}", 'admin_bcast_cancel': "❌ Bekor",
        'ai_prompt': "🤖 **AI Dasturchi**\n\nDasturlash bo'yicha topshiriq bering yoki kod faylini tashlang. Men oldingi gaplarni ham eslab qolaman!",
        'ai_wait': "🧠 AI ishlamoqda...", 'ai_error': "❌ Xatolik: {error}", 'ai_code_found': "✅ **Kod!**", 'ai_no_code': "🤖 **AI:**\n\n{text}",
        'ai_vision_error': "⚠️ Rasm xato.", 'ai_unsupported_file': "⚠️ Faqat kod fayllari.", 'ai_video_error': "🎥 Video yo'q.",
        'ai_file_too_large': "⚠️ Katta fayl.", 'ai_text_too_long': "⚠️ Uzun kod.", 'ai_not_coding': "🤖 Faqat dasturlash.",
        'ai_limit_info': "ℹ️ *Bugun uchun qolgan limitingiz: {limit} ta*",
        
        'java_info_text': "☕ **Termux'da Java Dasturlash**\n\nJava — kuchli va keng tarqalgan til. Termux'da buni sozlash juda oson!\n\n**1. Java (JDK) o'rnatish:**\n`pkg install openjdk-17 -y`\n\n**2. Tekshirish:**\n`java -version`\n`javac -version`\n\n**3. Fayl ochish:**\n_(Diqqat: fayl nomi katta harf bilan boshlanadi!)_\n`nano Salom.java`\n\n**4. Ichiga kod yozing:**\n```java\npublic class Salom {\n    public static void main(String[] args) {\n        System.out.println(\"Salom, Termux!\");\n    }\n}\n```\n_(Saqlash: CTRL+X, keyin Y, keyin Enter)_\n\n**5. Kompilyatsiya qilish va ishga tushirish:**\n`javac Salom.java`\n`java Salom`"
    },
    # Qolgan tillar (ru, en, ar) xuddi shu tarzda yangilangan
    'ru': {'choose_lang': "Выберите язык:", 'welcome': "👋 Я помощник **Termux**.", 'btn_termux': "📽️ УРОКИ", 'btn_lua': "📽️ LUA", 'btn_java': "☕ JAVA", 'btn_apk': "📥 APK", 'btn_ai': "🤖 AI Код", 'btn_profile': "👤 Профиль", 'btn_top': "🏆 Топ 10", 'btn_quiz': "🧠 Тест", 'btn_security': "🛡️ Безопасность", 'btn_support': "✉️ Админу", 'btn_tip': "💡 Совет", 'btn_cheatsheet': "📜 Команды", 'btn_change_lang': "🌐 Язык", 'btn_scripts': "📦 Скрипты", 'btn_files': "🗂 Файлы", 'btn_premium': "💎 Премиум", 'btn_challenge': "🧩 Задача дня", 'btn_theme': "🎨 Тема Termux", 'btn_back': "🔙 Назад", 'btn_prev': "⬅️", 'btn_next': "➡️", 'btn_python': "🐍 ПОЛУЧИТЬ PYTHON", 'btn_lessons_menu': "📚", 'btn_back_cheat': "🔙", 'force_sub_text': "⚠️ Подпишитесь:", 'btn_join': "📢 Подписаться", 'btn_check': "✅ Проверить", 'force_sub_error': "❌ Вы не подписались!", 'challenge_menu': "🧩 **Задача дня**\n\nРешите задачу и отправьте код. За правильный ответ **+30 баллов**!", 'challenge_problem': "📝 **Задача:**\n\n{text}\n\n💻 *Отправьте код:*", 'challenge_already_done': "✅ Вы уже решили задачу сегодня.", 'challenge_wait': "🤖 AI проверяет...", 'challenge_correct': "✅ **Верно!** 🎉\n\nВам начислено **+30 баллов**!", 'challenge_wrong': "❌ **Ошибка!**\n\n{feedback}\n\nИсправьте код и отправьте снова.", 'challenge_no_code': "⚠️ Отправьте код текстом или файлом.", 'theme_menu': "🎨 **Темы Termux**\n\nВыберите цвет. Бот пришлет файл `colors.properties`.", 'theme_send': "✅ **Тема {theme_name} готова!**\n\nИнструкция: переместите файл в `~/.termux/` и введите `termux-reload-settings`.", 'script_cat_menu': "📦 **Генератор**", 'script_items_menu': "⚙️ **{cat_name}**", 'btn_generate_script': "🚀 Создать", 'btn_clear_scripts': "🗑 Очистить", 'btn_back_to_cats': "🔙 Назад", 'script_empty': "⚠️ Выберите программу!", 'script_done': "✅ Готово!", 'files_menu': "🗂 **Файлы**", 'files_empty': "Нет файлов.", 'file_sending': "⏳...", 'file_premium_locked': "🔒 Только для Премиум!", 'premium_menu': "💎 **Премиум**\n\n50 Stars за 1 месяц.", 'btn_buy_premium': "⭐️ Купить за 50 Stars", 'premium_success': "🎉 Вы Премиум!", 'ai_limit_reached': "⚠️ Лимит (5/день). Купите Премиум.", 'btn_go_premium': "💎 Купить", 'admin_panel': "👑 **Панель Админа**", 'admin_btn_stats': "📊", 'admin_btn_bcast': "📢", 'admin_btn_points': "🎁", 'admin_btn_add_file': "➕ Файл", 'admin_btn_ban': "🚫 Бан", 'admin_btn_unban': "✅ Разбан", 'admin_btn_close': "❌", 'admin_points_prompt': "🎁 Баллы:", 'admin_points_wait': "⏳ Рассылка...", 'admin_points_done': "✅ Добавлено {points}!\n📩 Отправлено: {success}\n❌ Ошибок: {fail}", 'admin_file_wait': "📂 Отправьте файл:", 'admin_file_title': "✍️ Название:", 'admin_file_saved': "✅ Сохранено!", 'admin_file_cancel': "❌ Отменено.", 'admin_ban_prompt': "🚫 ID для бана:", 'admin_unban_prompt': "✅ ID для разбана:", 'text_page': "📚 {page}/5", 'text_lua': "📚 LUA", 'text_python_done': "✅", 'text_error_vid': "❌ Ошибка! Видео не найдено.", 'tip_header': "💡", 'cheatsheet_menu': "📜", 'cat_files': "📁", 'cat_packages': "📦", 'cat_network': "🌐", 'cat_system': "⚙️", 'apk_caption': "📱", 'apk_file_name': "T.apk", 'apk_loading': "⏳", 'apk_too_big': "⚠️", 'apk_error': "❌", 'support_prompt': "✉️", 'support_sent': "✅", 'support_reply': "📬", 'profile_text': "👤 **Профиль**\n⭐ {score}\n🏅 {level}\n📊 #{rank}\n💎 {status}", 'btn_daily_bonus': "🎁 Бонус (+20)", 'bonus_claimed': "✅ +20!", 'bonus_wait': "⏳ Завтра!", 'top_text': "🏆 **Топ 10:**\n{list}", 'quiz_start': "🧠 **Тест!** +10 очков.\n\n❓ *Вопрос:*", 'quiz_correct': "✅ **Верно!** (+10)", 'quiz_wrong': "❌ **Ошибка!** Ответ: **{answer}**", 'quiz_end': "🎉 Вы ответили на все вопросы! Начинаем заново.", 'btn_next_quiz': "➡️ Следующий", 'sec_menu': "🛡️", 'sec_info': "🔍", 'sec_pass': "🔑", 'sec_exploit': "💥", 'sec_network': "📡", 'sec_info_text': "Nmap", 'sec_pass_text': "Hydra", 'sec_exploit_text': "SQLmap", 'sec_network_text': "Tshark", 'admin_bcast_start': "📢", 'admin_bcast_wait': "⏳", 'admin_bcast_done': "✅ {success}, {fail}", 'admin_bcast_cancel': "❌", 'ai_prompt': "🤖 AI (с памятью)", 'ai_wait': "🧠...", 'ai_error': "❌ {error}", 'ai_code_found': "✅", 'ai_no_code': "🤖 {text}", 'ai_vision_error': "⚠️", 'ai_unsupported_file': "⚠️", 'ai_video_error': "🎥", 'ai_file_too_large': "⚠️", 'ai_text_too_long': "⚠️", 'ai_not_coding': "🤖", 'ai_limit_info': "ℹ️ Лимит: {limit}", 'java_info_text': "☕ **Java в Termux**\n\n1. Установка: `pkg install openjdk-17 -y`\n2. Создание: `nano Salom.java`\n3. Код: `public class Salom { ... }`\n4. Запуск: `javac Salom.java` и `java Salom`"},
    'en': {'choose_lang': "Select language:", 'welcome': "👋 **Termux** assistant.", 'btn_termux': "📽️ LESSONS", 'btn_lua': "📽️ LUA", 'btn_java': "☕ JAVA", 'btn_apk': "📥 APK", 'btn_ai': "🤖 AI Code", 'btn_profile': "👤 Profile", 'btn_top': "🏆 Top 10", 'btn_quiz': "🧠 Quiz", 'btn_security': "🛡️ Security", 'btn_support': "✉️ Admin", 'btn_tip': "💡 Tip", 'btn_cheatsheet': "📜 Commands", 'btn_change_lang': "🌐 Language", 'btn_scripts': "📦 Scripts", 'btn_files': "🗂 File Center", 'btn_premium': "💎 Premium", 'btn_challenge': "🧩 Daily Challenge", 'btn_theme': "🎨 Termux Theme", 'btn_back': "🔙 Back", 'btn_prev': "⬅️", 'btn_next': "➡️", 'btn_python': "🐍 GET PYTHON", 'btn_lessons_menu': "📚", 'btn_back_cheat': "🔙", 'force_sub_text': "⚠️ Join our channel:", 'btn_join': "📢 Join", 'btn_check': "✅ Check", 'force_sub_error': "❌ You haven't joined!", 'challenge_menu': "🧩 **Daily Challenge**\n\nSolve the problem and submit code. Correct answer gets **+30 points**!", 'challenge_problem': "📝 **Problem:**\n\n{text}\n\n💻 *Send your code:*", 'challenge_already_done': "✅ You already solved today's challenge.", 'challenge_wait': "🤖 AI is checking...", 'challenge_correct': "✅ **Correct!** 🎉\n\nYou earned **+30 points**!", 'challenge_wrong': "❌ **Wrong!**\n\n{feedback}\n\nFix the code and send again.", 'challenge_no_code': "⚠️ Send code as text or file.", 'theme_menu': "🎨 **Termux Themes**\n\nSelect a color. Bot sends `colors.properties`.", 'theme_send': "✅ **Theme {theme_name} ready!**\n\nInstructions: move file to `~/.termux/` and run `termux-reload-settings`.", 'script_cat_menu': "📦 **Script Generator**", 'script_items_menu': "⚙️ **{cat_name}**", 'btn_generate_script': "🚀 Generate", 'btn_clear_scripts': "🗑 Clear", 'btn_back_to_cats': "🔙 Back", 'script_empty': "⚠️ Select at least one!", 'script_done': "✅ Done!", 'files_menu': "🗂 **File Center**", 'files_empty': "No files yet.", 'file_sending': "⏳...", 'file_premium_locked': "🔒 Premium only!", 'premium_menu': "💎 **Premium**\n\n50 Stars for 1 month.", 'btn_buy_premium': "⭐️ Buy for 50 Stars", 'premium_success': "🎉 You are Premium!", 'ai_limit_reached': "⚠️ Limit reached (5/day). Buy Premium.", 'btn_go_premium': "💎 Go Premium", 'admin_panel': "👑 **Admin Panel**", 'admin_btn_stats': "📊", 'admin_btn_bcast': "📢", 'admin_btn_points': "🎁", 'admin_btn_add_file': "➕ Add File", 'admin_btn_ban': "🚫 Ban", 'admin_btn_unban': "✅ Unban", 'admin_btn_close': "❌", 'admin_points_prompt': "🎁 Points to add:", 'admin_points_wait': "⏳ Sending...", 'admin_points_done': "✅ Added {points}!\n📩 Sent: {success}\n❌ Failed: {fail}", 'admin_file_wait': "📂 Send file:", 'admin_file_title': "✍️ File title:", 'admin_file_saved': "✅ Saved!", 'admin_file_cancel': "❌ Cancelled.", 'admin_ban_prompt': "🚫 ID to Ban:", 'admin_unban_prompt': "✅ ID to Unban:", 'text_page': "📚 {page}/5", 'text_lua': "📚 LUA", 'text_python_done': "✅", 'text_error_vid': "❌ Error! Video not found.", 'tip_header': "💡", 'cheatsheet_menu': "📜", 'cat_files': "📁", 'cat_packages': "📦", 'cat_network': "🌐", 'cat_system': "⚙️", 'apk_caption': "📱", 'apk_file_name': "T.apk", 'apk_loading': "⏳", 'apk_too_big': "⚠️", 'apk_error': "❌", 'support_prompt': "✉️", 'support_sent': "✅", 'support_reply': "📬", 'profile_text': "👤 **Profile**\n⭐ {score}\n🏅 {level}\n📊 #{rank}\n💎 {status}", 'btn_daily_bonus': "🎁 Bonus (+20)", 'bonus_claimed': "✅ +20!", 'bonus_wait': "⏳ Tomorrow!", 'top_text': "🏆 **Top 10:**\n{list}", 'quiz_start': "🧠 **Quiz!** +10 points.\n\n❓ *Question:*", 'quiz_correct': "✅ **Correct!** (+10)", 'quiz_wrong': "❌ **Wrong!** Answer: **{answer}**", 'quiz_end': "🎉 You've answered all questions! Starting over.", 'btn_next_quiz': "➡️ Next", 'sec_menu': "🛡️", 'sec_info': "🔍", 'sec_pass': "🔑", 'sec_exploit': "💥", 'sec_network': "📡", 'sec_info_text': "Nmap", 'sec_pass_text': "Hydra", 'sec_exploit_text': "SQLmap", 'sec_network_text': "Tshark", 'admin_bcast_start': "📢", 'admin_bcast_wait': "⏳", 'admin_bcast_done': "✅ {success}, {fail}", 'admin_bcast_cancel': "❌", 'ai_prompt': "🤖 AI (with Memory)", 'ai_wait': "🧠...", 'ai_error': "❌ {error}", 'ai_code_found': "✅", 'ai_no_code': "🤖 {text}", 'ai_vision_error': "⚠️", 'ai_unsupported_file': "⚠️", 'ai_video_error': "🎥", 'ai_file_too_large': "⚠️", 'ai_text_too_long': "⚠️", 'ai_not_coding': "🤖", 'ai_limit_info': "ℹ️ Remaining: {limit}", 'java_info_text': "☕ **Java in Termux**\n\n1. Install: `pkg install openjdk-17 -y`\n2. Create: `nano Salom.java`\n3. Code: `public class Salom { ... }`\n4. Run: `javac Salom.java` and `java Salom`"},
    'ar': {'choose_lang': "اختر اللغة:", 'welcome': "👋 مساعد **Termux**.", 'btn_termux': "📽️ دروس", 'btn_lua': "📽️ LUA", 'btn_java': "☕ JAVA", 'btn_apk': "📥 APK", 'btn_ai': "🤖 AI", 'btn_profile': "👤 الملف", 'btn_top': "🏆 أفضل 10", 'btn_quiz': "🧠 اختبار", 'btn_security': "🛡️ الأمن", 'btn_support': "✉️ المسؤول", 'btn_tip': "💡 نصيحة", 'btn_cheatsheet': "📜 أوامر", 'btn_change_lang': "🌐 اللغة", 'btn_scripts': "📦 سكريبتات", 'btn_files': "🗂 الملفات", 'btn_premium': "💎 بريميوم", 'btn_challenge': "🧩 تحدي يومي", 'btn_theme': "🎨 ثيم Termux", 'btn_back': "🔙 رجوع", 'btn_prev': "⬅️", 'btn_next': "➡️", 'btn_python': "🐍 الحصول على PYTHON", 'btn_lessons_menu': "📚", 'btn_back_cheat': "🔙", 'force_sub_text': "⚠️ انضم إلى قناتنا:", 'btn_join': "📢 انضم", 'btn_check': "✅ تحقق", 'force_sub_error': "❌ لم تنضم بعد!", 'challenge_menu': "🧩 **تحدي يومي**\n\nحل المشكلة وأرسل الكود. الإجابة الصحيحة تعطيك **+30 نقطة**!", 'challenge_problem': "📝 **المشكلة:**\n\n{text}\n\n💻 *أرسل الكود:*", 'challenge_already_done': "✅ لقد قمت بحل التحدي اليوم بالفعل.", 'challenge_wait': "🤖 AI يتحقق...", 'challenge_correct': "✅ **صحيح!** 🎉\n\nلقد حصلت على **+30 نقطة**!", 'challenge_wrong': "❌ **خطأ!**\n\n{feedback}\n\nصحح الكود وأرسله مرة أخرى.", 'challenge_no_code': "⚠️ أرسل الكود كنص أو ملف.", 'theme_menu': "🎨 **ثيمات Termux**\n\nاختر لوناً. سيرسل البوت ملف `colors.properties`.", 'theme_send': "✅ **الثيم {theme_name} جاهز!**\n\nالتعليمات: انقل الملف إلى `~/.termux/` ثم اكتب `termux-reload-settings`.", 'script_cat_menu': "📦 **مولد**", 'script_items_menu': "⚙️ **{cat_name}**", 'btn_generate_script': "🚀 إنشاء", 'btn_clear_scripts': "🗑 مسح", 'btn_back_to_cats': "🔙 رجوع", 'script_empty': "⚠️ اختر برنامجاً!", 'script_done': "✅ جاهز!", 'files_menu': "🗂 **الملفات**", 'files_empty': "لا توجد ملفات.", 'file_sending': "⏳...", 'file_premium_locked': "🔒 بريميوم فقط!", 'premium_menu': "💎 **بريميوم**\n\n50 نجمة لمدة شهر.", 'btn_buy_premium': "⭐️ شراء بـ 50 نجمة", 'premium_success': "🎉 أنت بريميوم!", 'ai_limit_reached': "⚠️ الحد (5/يوم). اشتري بريميوم.", 'btn_go_premium': "💎 اشتري", 'admin_panel': "👑 **لوحة المسؤول**", 'admin_btn_stats': "📊", 'admin_btn_bcast': "📢", 'admin_btn_points': "🎁", 'admin_btn_add_file': "➕ ملف", 'admin_btn_ban': "🚫 حظر", 'admin_btn_unban': "✅ إلغاء الحظر", 'admin_btn_close': "❌", 'admin_points_prompt': "🎁 نقاط:", 'admin_points_wait': "⏳ جاري الإرسال...", 'admin_points_done': "✅ أضيفت {points}!\n📩 المرسل: {success}\n❌ الفشل: {fail}", 'admin_file_wait': "📂 أرسل ملفاً:", 'admin_file_title': "✍️ اسم الملف:", 'admin_file_saved': "✅ تم الحفظ!", 'admin_file_cancel': "❌ ملغي.", 'admin_ban_prompt': "🚫 ID للحظر:", 'admin_unban_prompt': "✅ ID لإلغاء الحظر:", 'text_page': "📚 {page}/5", 'text_lua': "📚 LUA", 'text_python_done': "✅", 'text_error_vid': "❌ خطأ! الفيديو غير موجود.", 'tip_header': "💡", 'cheatsheet_menu': "📜", 'cat_files': "📁", 'cat_packages': "📦", 'cat_network': "🌐", 'cat_system': "⚙️", 'apk_caption': "📱", 'apk_file_name': "T.apk", 'apk_loading': "⏳", 'apk_too_big': "⚠️", 'apk_error': "❌", 'support_prompt': "✉️", 'support_sent': "✅", 'support_reply': "📬", 'profile_text': "👤 **الملف**\n⭐ {score}\n🏅 {level}\n📊 #{rank}\n💎 {status}", 'btn_daily_bonus': "🎁 مكافأة (+20)", 'bonus_claimed': "✅ +20!", 'bonus_wait': "⏳ غداً!", 'top_text': "🏆 **أفضل 10:**\n{list}", 'quiz_start': "🧠 **اختبار!** +10 نقاط.\n\n❓ *سؤال:*", 'quiz_correct': "✅ **صحيح!** (+10)", 'quiz_wrong': "❌ **خطأ!** الجواب: **{answer}**", 'quiz_end': "🎉 أجبت على جميع الأسئلة! نبدأ من جديد.", 'btn_next_quiz': "➡️ التالي", 'sec_menu': "🛡️", 'sec_info': "🔍", 'sec_pass': "🔑", 'sec_exploit': "💥", 'sec_network': "📡", 'sec_info_text': "Nmap", 'sec_pass_text': "Hydra", 'sec_exploit_text': "SQLmap", 'sec_network_text': "Tshark", 'admin_bcast_start': "📢", 'admin_bcast_wait': "⏳", 'admin_bcast_done': "✅ {success}, {fail}", 'admin_bcast_cancel': "❌", 'ai_prompt': "🤖 AI (مع الذاكرة)", 'ai_wait': "🧠...", 'ai_error': "❌ {error}", 'ai_code_found': "✅", 'ai_no_code': "🤖 {text}", 'ai_vision_error': "⚠️", 'ai_unsupported_file': "⚠️", 'ai_video_error': "🎥", 'ai_file_too_large': "⚠️", 'ai_text_too_long': "⚠️", 'ai_not_coding': "🤖", 'ai_limit_info': "ℹ️ المتبقي: {limit}", 'java_info_text': "☕ **Java في Termux**\n\n1. التثبيت: `pkg install openjdk-17 -y`\n2. إنشاء: `nano Salom.java`\n3. الكود: `public class Salom { ... }`\n4. التشغيل: `javac Salom.java` و `java Salom`"}
}

TIPS = [{'uz': "**Tezroq kod yozish:**\n`nano` o'rniga `micro` ishlating.", 'ru': "**Быстрое написание:**\nИспользуйте `micro`.", 'en': "**Faster coding:**\nUse `micro`.", 'ar': "**برمجة أسرع:**\nاستخدم `micro`."}]
COMMANDS_DATA = {'files': [('ls', {'uz': 'Fayllar', 'ru': 'Файлы', 'en': 'Files', 'ar': 'ملفات'})], 'packages': [('pkg update', {'uz': 'Yangilash', 'ru': 'Обновить', 'en': 'Update', 'ar': 'تحديث'})], 'network': [('ping google.com', {'uz': 'Tekshirish', 'ru': 'Проверить', 'en': 'Check', 'ar': 'فحص'})], 'system': [('clear', {'uz': 'Tozalash', 'ru': 'Очистить', 'en': 'Clear', 'ar': 'مسح'})]}

# ==========================================
# 50 TA KENGAYTIRILGAN TEST SAVOLLARI
# ==========================================
QUIZ_DATA = [
    {'q': {'uz': "Papka yaratish uchun qaysi buyruq ishlatiladi?", 'ru': "Какая команда создает папку?", 'en': "Which command creates a folder?", 'ar': "أي أمر ينشئ مجلداً؟"}, 'options': ['mkdir', 'cd', 'ls', 'rm'], 'answer': 'mkdir'},
    {'q': {'uz': "Fayllar ro'yxatini ko'rish uchun?", 'ru': "Показать список файлов?", 'en': "List files?", 'ar': "عرض الملفات؟"}, 'options': ['ls', 'pwd', 'cat', 'touch'], 'answer': 'ls'},
    {'q': {'uz': "Termux paketlarini yangilash?", 'ru': "Обновить пакеты Termux?", 'en': "Update Termux packages?", 'ar': "تحديث حزم Termux؟"}, 'options': ['pkg update', 'apt-get', 'install', 'upgrade'], 'answer': 'pkg update'},
    {'q': {'uz': "Python faylini ishga tushirish?", 'ru': "Запустить Python файл?", 'en': "Run Python file?", 'ar': "تشغيل ملف بايثون؟"}, 'options': ['python file.py', 'run file.py', 'py file', 'exec file.py'], 'answer': 'python file.py'},
    {'q': {'uz': "Katalogga (papkaga) kirish?", 'ru': "Войти в папку?", 'en': "Enter folder?", 'ar': "الدخول إلى مجلد؟"}, 'options': ['cd', 'mv', 'cp', 'dir'], 'answer': 'cd'},
    {'q': {'uz': "Hozirgi turgan manzilni (yo'lni) bilish?", 'ru': "Узнать текущий путь?", 'en': "Print current directory?", 'ar': "طباعة المسار الحالي؟"}, 'options': ['pwd', 'ls', 'cd', 'path'], 'answer': 'pwd'},
    {'q': {'uz': "Faylni o'chirish uchun?", 'ru': "Удалить файл?", 'en': "Delete a file?", 'ar': "حذف ملف؟"}, 'options': ['rm', 'del', 'drop', 'erase'], 'answer': 'rm'},
    {'q': {'uz': "Bo'sh fayl yaratish uchun?", 'ru': "Создать пустой файл?", 'en': "Create an empty file?", 'ar': "إنشاء ملف فارغ؟"}, 'options': ['touch', 'nano', 'cat', 'echo'], 'answer': 'touch'},
    {'q': {'uz': "Faylning ichini o'qish (ko'rish) uchun?", 'ru': "Прочитать содержимое файла?", 'en': "Read file contents?", 'ar': "قراءة محتويات الملف؟"}, 'options': ['cat', 'ls', 'open', 'read'], 'answer': 'cat'},
    {'q': {'uz': "Python'da kutubxona o'rnatish?", 'ru': "Установить библиотеку Python?", 'en': "Install Python library?", 'ar': "تثبيت مكتبة بايثون؟"}, 'options': ['pip install', 'pkg install', 'apt install', 'python install'], 'answer': 'pip install'},
    {'q': {'uz': "Termux'da qaysi matn muharriri mavjud?", 'ru': "Какой текстовый редактор есть в Termux?", 'en': "Which text editor is in Termux?", 'ar': "أي محرر نصوص موجود في Termux؟"}, 'options': ['nano', 'notepad', 'word', 'gedit'], 'answer': 'nano'},
    {'q': {'uz': "Git orqali loyihani yuklab olish?", 'ru': "Скачать проект через Git?", 'en': "Download project via Git?", 'ar': "تنزيل مشروع عبر Git؟"}, 'options': ['git clone', 'git pull', 'git fetch', 'git download'], 'answer': 'git clone'},
    {'q': {'uz': "Tarmoq ulanishini tekshirish (Ping)?", 'ru': "Проверка сети (Ping)?", 'en': "Check network (Ping)?", 'ar': "فحص الشبكة (Ping)؟"}, 'options': ['ping', 'traceroute', 'netstat', 'wget'], 'answer': 'ping'},
    {'q': {'uz': "Faylga bajarish (ishlash) huquqini berish?", 'ru': "Дать файлу права на выполнение?", 'en': "Give file execute permissions?", 'ar': "منح الملف أذونات التنفيذ؟"}, 'options': ['chmod +x', 'chmod 777', 'chown', 'chgrp'], 'answer': 'chmod +x'},
    {'q': {'uz': "Ekrandagi yozuvlarni tozalash?", 'ru': "Очистить экран?", 'en': "Clear the screen?", 'ar': "مسح الشاشة؟"}, 'options': ['clear', 'cls', 'reset', 'erase'], 'answer': 'clear'},
    {'q': {'uz': "Tizim resurslarini (CPU, RAM) kuzatish?", 'ru': "Мониторинг ресурсов (CPU, RAM)?", 'en': "Monitor system resources?", 'ar': "مراقبة موارد النظام؟"}, 'options': ['top', 'ls', 'df', 'free'], 'answer': 'top'},
    {'q': {'uz': "Internetdan fayl yuklab olish?", 'ru': "Скачать файл из интернета?", 'en': "Download file from internet?", 'ar': "تنزيل ملف من الإنترنت؟"}, 'options': ['wget', 'curl', 'download', 'fetch'], 'answer': 'wget'},
    {'q': {'uz': "Kiberxavfsizlikda portlarni skanerlash asbobi?", 'ru': "Инструмент сканирования портов?", 'en': "Port scanning tool?", 'ar': "أداة فحص المنافذ؟"}, 'options': ['nmap', 'ping', 'netstat', 'ssh'], 'answer': 'nmap'},
    {'q': {'uz': "Python'da ekranga yozuv chiqarish?", 'ru': "Вывод текста в Python?", 'en': "Print text in Python?", 'ar': "طباعة نص في بايثون؟"}, 'options': ['print()', 'echo()', 'write()', 'log()'], 'answer': 'print()'},
    {'q': {'uz': "Python'da izoh (comment) qanday yoziladi?", 'ru': "Как пишется комментарий в Python?", 'en': "How to write a comment in Python?", 'ar': "كيف تكتب تعليقاً في بايثون؟"}, 'options': ['# Izoh', '// Izoh', '/* Izoh */', '-- Izoh'], 'answer': '# Izoh'},
    {'q': {'uz': "Termux'ni yopish (chiqish) buyrug'i?", 'ru': "Команда выхода из Termux?", 'en': "Command to exit Termux?", 'ar': "أمر الخروج من Termux؟"}, 'options': ['exit', 'quit', 'close', 'stop'], 'answer': 'exit'},
    {'q': {'uz': "Fayl nomini o'zgartirish yoki ko'chirish?", 'ru': "Переименовать или переместить файл?", 'en': "Rename or move file?", 'ar': "إعادة تسمية أو نقل ملف؟"}, 'options': ['mv', 'cp', 'rm', 'rename'], 'answer': 'mv'},
    {'q': {'uz': "Faylni nusxalash (copy)?", 'ru': "Копировать файл?", 'en': "Copy file?", 'ar': "نسخ ملف؟"}, 'options': ['cp', 'mv', 'copy', 'dup'], 'answer': 'cp'},
    {'q': {'uz': "Diskdagi bo'sh joyni tekshirish?", 'ru': "Проверить свободное место?", 'en': "Check free disk space?", 'ar': "فحص المساحة الفارغة؟"}, 'options': ['df', 'free', 'du', 'ls'], 'answer': 'df'},
    {'q': {'uz': "Qaysi biri IP manzilni ko'rsatadi?", 'ru': "Какая команда показывает IP-адрес?", 'en': "Which command shows IP address?", 'ar': "أي أمر يظهر عنوان IP؟"}, 'options': ['ifconfig', 'ls', 'ping', 'cat'], 'answer': 'ifconfig'},
    {'q': {'uz': "Python'da ro'yxat (list) yaratish?", 'ru': "Создать список в Python?", 'en': "Create a list in Python?", 'ar': "إنشاء قائمة في بايثون؟"}, 'options': ['[]', '{}', '()', '<>'], 'answer': '[]'},
    {'q': {'uz': "Python'da lug'at (dictionary) yaratish?", 'ru': "Создать словарь в Python?", 'en': "Create a dictionary in Python?", 'ar': "إنشاء قاموس في بايثون؟"}, 'options': ['{}', '[]', '()', '<>'], 'answer': '{}'},
    {'q': {'uz': "Python'da mantiqiy 'VA' operatori?", 'ru': "Логическое 'И' в Python?", 'en': "Logical 'AND' in Python?", 'ar': "المنطقي 'و' في بايثون؟"}, 'options': ['and', '&&', '&', 'AND'], 'answer': 'and'},
    {'q': {'uz': "Python'da mantiqiy 'YOKI' operatori?", 'ru': "Логическое 'ИЛИ' в Python?", 'en': "Logical 'OR' in Python?", 'ar': "المنطقي 'أو' في بايثون؟"}, 'options': ['or', '||', '|', 'OR'], 'answer': 'or'},
    {'q': {'uz': "Python'da mantiqiy 'EMAS' operatori?", 'ru': "Логическое 'НЕ' в Python?", 'en': "Logical 'NOT' in Python?", 'ar': "المنطقي 'ليس' في بايثون؟"}, 'options': ['not', '!', '~', 'NOT'], 'answer': 'not'},
    {'q': {'uz': "Faylni tahrirlash uchun eng oson muharrir?", 'ru': "Самый простой редактор для файлов?", 'en': "Easiest editor for files?", 'ar': "أسهل محرر للملفات؟"}, 'options': ['nano', 'vim', 'emacs', 'code'], 'answer': 'nano'},
    {'q': {'uz': "SSH orqali ulanish buyrug'i?", 'ru': "Команда подключения по SSH?", 'en': "SSH connection command?", 'ar': "أمر اتصال SSH؟"}, 'options': ['ssh', 'telnet', 'ftp', 'http'], 'answer': 'ssh'},
    {'q': {'uz': "Qaysi buyruq fayl ichidan ma'lum so'zni qidiradi?", 'ru': "Какая команда ищет слово в файле?", 'en': "Which command searches text in a file?", 'ar': "أي أمر يبحث عن نص في ملف؟"}, 'options': ['grep', 'find', 'search', 'locate'], 'answer': 'grep'},
    {'q': {'uz': "Faylni arxivlash (zip) buyrug'i?", 'ru': "Команда архивации (zip)?", 'en': "Archive (zip) command?", 'ar': "أمر الأرشفة (zip)؟"}, 'options': ['zip', 'tar', 'gzip', 'rar'], 'answer': 'zip'},
    {'q': {'uz': "Qaysi buyruq joriy foydalanuvchini ko'rsatadi?", 'ru': "Какая команда показывает текущего пользователя?", 'en': "Which command shows current user?", 'ar': "أي أمر يظهر المستخدم الحالي؟"}, 'options': ['whoami', 'id', 'user', 'who'], 'answer': 'whoami'},
    {'q': {'uz': "Tizimni qayta ishga tushirish buyrug'i (Linux)?", 'ru': "Команда перезагрузки (Linux)?", 'en': "Reboot command (Linux)?", 'ar': "أمر إعادة التشغيل (Linux)؟"}, 'options': ['reboot', 'shutdown', 'restart', 'poweroff'], 'answer': 'reboot'},
    {'q': {'uz': "Tarmoq interfeyslarini ko'rish buyrug'i?", 'ru': "Команда просмотра сетевых интерфейсов?", 'en': "Command to view network interfaces?", 'ar': "أمر عرض واجهات الشبكة؟"}, 'options': ['ifconfig', 'ip addr', 'netstat', 'iwconfig'], 'answer': 'ifconfig'},
    {'q': {'uz': "Python'da kodni to'xtatish (break) nima qiladi?", 'ru': "Что делает break в Python?", 'en': "What does break do in Python?", 'ar': "ماذا يفعل break في بايثون؟"}, 'options': ['Siklni to\'xtatadi', 'Kodni davom ettiradi', 'Xato beradi', 'Kutadi'], 'answer': 'Siklni to\'xtatadi'},
    {'q': {'uz': "Git'da o'zgarishlarni saqlash?", 'ru': "Сохранить изменения в Git?", 'en': "Save changes in Git?", 'ar': "حفظ التغييرات في Git؟"}, 'options': ['git commit', 'git save', 'git push', 'git add'], 'answer': 'git commit'},
    {'q': {'uz': "Git'da masofaviy repoga yuborish?", 'ru': "Отправить в удаленный репозиторий?", 'en': "Push to remote repo?", 'ar': "دفع إلى المستودع البعيد؟"}, 'options': ['git push', 'git pull', 'git commit', 'git remote'], 'answer': 'git push'},
    {'q': {'uz': "Termux'da APK o'rnatish buyrug'i?", 'ru': "Команда установки APK в Termux?", 'en': "Command to install APK in Termux?", 'ar': "أمر تثبيت APK في Termux؟"}, 'options': ['pkg install', 'apt install', 'install', 'apk install'], 'answer': 'pkg install'},
    {'q': {'uz': "Python'da qaysi operator qoldiqni topadi?", 'ru': "Какой оператор находит остаток в Python?", 'en': "Which operator finds remainder in Python?", 'ar': "أي عامل يجد الباقي في بايثون؟"}, 'options': ['%', '//', '/', '*'], 'answer': '%'},
    {'q': {'uz': "Python'da butun bo'lish operatori?", 'ru': "Оператор целочисленного деления в Python?", 'en': "Integer division operator in Python?", 'ar': "عامل القسمة الصحيحة في بايثون؟"}, 'options': ['//', '/', '%', '**'], 'answer': '//'},
    {'q': {'uz': "Python'da darajaga ko'tarish operatori?", 'ru': "Оператор возведения в степень в Python?", 'en': "Exponentiation operator in Python?", 'ar': "عامل الأس في بايثون؟"}, 'options': ['**', '^', '^^', 'pow'], 'answer': '**'},
    {'q': {'uz': "Faylning ruxsatlarini o'zgartirish buyrug'i?", 'ru': "Команда изменения прав файла?", 'en': "Command to change file permissions?", 'ar': "أمر تغيير أذونات الملف؟"}, 'options': ['chmod', 'chown', 'chgrp', 'umask'], 'answer': 'chmod'},
    {'q': {'uz': "Katalogni o'chirish (ichidagi fayllar bilan)?", 'ru': "Удалить папку (с файлами)?", 'en': "Delete folder (with files)?", 'ar': "حذف مجلد (مع الملفات)؟"}, 'options': ['rm -rf', 'rmdir', 'rm', 'del'], 'answer': 'rm -rf'},
    {'q': {'uz': "Python'da kutubxonalarni ko'rish buyrug'i?", 'ru': "Команда просмотра библиотек Python?", 'en': "Command to view Python libraries?", 'ar': "أمر عرض مكتبات بايثون؟"}, 'options': ['pip list', 'pip show', 'pip freeze', 'pip view'], 'answer': 'pip list'},
    {'q': {'uz': "Tizimni o'chirish buyrug'i (Linux)?", 'ru': "Команда выключения (Linux)?", 'en': "Shutdown command (Linux)?", 'ar': "أمر إيقاف التشغيل (Linux)؟"}, 'options': ['poweroff', 'shutdown -h now', 'halt', 'stop'], 'answer': 'poweroff'},
    {'q': {'uz': "Hozirgi vaqtni ko'rsatish buyrug'i?", 'ru': "Команда показа текущего времени?", 'en': "Command to show current time?", 'ar': "أمر عرض الوقت الحالي؟"}, 'options': ['date', 'time', 'clock', 'now'], 'answer': 'date'},
    {'q': {'uz': "Python'da faylni ochish funksiyasi?", 'ru': "Функция открытия файла в Python?", 'en': "File open function in Python?", 'ar': "دالة فتح الملف في بايثون؟"}, 'options': ['open()', 'file()', 'read()', 'load()'], 'answer': 'open()'},
    {'q': {'uz': "Python'da satrni butun songa aylantirish?", 'ru': "Преобразовать строку в число в Python?", 'en': "Convert string to integer in Python?", 'ar': "تحويل سلسلة إلى عدد صحيح في بايثون؟"}, 'options': ['int()', 'str()', 'float()', 'num()'], 'answer': 'int()'}
]

# ==========================================
# KLAVIATURALAR
# ==========================================
def get_lang_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="lang_uz"), InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")], [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"), InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar")]])

def get_main_menu(lang, user_id):
    t = TEXTS[lang]
    keyboard = [
        [InlineKeyboardButton(t['btn_termux'], callback_data="page_1"), InlineKeyboardButton(t['btn_lua'], callback_data="lua_page_1")],
        [InlineKeyboardButton(t['btn_java'], callback_data="java_info"), InlineKeyboardButton(t['btn_ai'], callback_data="ai_start")],
        [InlineKeyboardButton(t['btn_security'], callback_data="sec_start"), InlineKeyboardButton(t['btn_scripts'], callback_data="script_menu")],
        [InlineKeyboardButton(t['btn_files'], callback_data="files_menu"), InlineKeyboardButton(t['btn_theme'], callback_data="theme_menu")],
        [InlineKeyboardButton(t['btn_cheatsheet'], callback_data="cheatsheet"), InlineKeyboardButton(t['btn_apk'], callback_data="send_apk")],
        [InlineKeyboardButton(t['btn_challenge'], callback_data="challenge_start"), InlineKeyboardButton(t['btn_quiz'], callback_data="quiz_start")],
        [InlineKeyboardButton(t['btn_top'], callback_data="top_users"), InlineKeyboardButton(t['btn_premium'], callback_data="premium_menu")],
        [InlineKeyboardButton(t['btn_profile'], callback_data="my_profile"), InlineKeyboardButton(t['btn_tip'], callback_data="daily_tip")],
        [InlineKeyboardButton(t['btn_support'], callback_data="support_start"), InlineKeyboardButton(t['btn_change_lang'], callback_data="change_lang")]
    ]
    
    if user_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin_menu")])
        
    return InlineKeyboardMarkup(keyboard)

def get_theme_keyboard(lang):
    t = TEXTS[lang]
    keyboard = []
    row = []
    for key, theme in THEMES_DATA.items():
        row.append(InlineKeyboardButton(theme['name'], callback_data=f"theme_apply_{key}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(keyboard)

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
        [InlineKeyboardButton(t['admin_btn_add_file'], callback_data="admin_add_file")],
        [InlineKeyboardButton(t['admin_btn_ban'], callback_data="admin_ban"), InlineKeyboardButton(t['admin_btn_unban'], callback_data="admin_unban")],
        [InlineKeyboardButton(t['admin_btn_close'], callback_data="admin_close")]
    ])

def get_sub_keyboard(lang):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t['btn_join'], url=f"https://t.me/{FORCE_SUB_CHANNEL.replace('@', '')}")],
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
    end_idx = min(page * 10, 46)
    row = []
    for i in range(start_idx, end_idx + 1):
        row.append(InlineKeyboardButton(f"🎬 {i}-darslik", callback_data=f"lesson_{i}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    nav_row = []
    if page > 1: nav_row.append(InlineKeyboardButton(t['btn_prev'], callback_data=f"page_{page-1}"))
    if end_idx < 46: nav_row.append(InlineKeyboardButton(t['btn_next'], callback_data=f"page_{page+1}"))
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
    shuffled_options = options.copy()
    random.shuffle(shuffled_options)
    
    for opt in shuffled_options:
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
    
    user_info = await get_user(user_id)
    if user_info and user_info.get('is_banned') and user_id != ADMIN_ID:
        await update.message.reply_text("🚫 Siz botdan bloklangansiz.")
        return
    
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

    user_info = await get_user(user_id)
    if user_info and user_info.get('is_banned') and user_id != ADMIN_ID:
        return await query.answer("🚫 Siz bloklangansiz.", show_alert=True)

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

    if data == "files_menu":
        files = await get_all_files()
        if not files:
            return await query.answer(t['files_empty'], show_alert=True)
        
        keyboard = []
        for f in files:
            lock = "🔒 " if f['is_premium'] else "📄 "
            keyboard.append([InlineKeyboardButton(f"{lock}{f['title']}", callback_data=f"get_file_{f['id']}")])
        keyboard.append([InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")])
        
        await edit_or_send(query, context, t['files_menu'], InlineKeyboardMarkup(keyboard))

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

    elif data == "premium_menu":
        await edit_or_send(query, context, t['premium_menu'], get_premium_keyboard(lang))

    elif data == "buy_premium":
        title = "Premium Obuna (1 oy)"
        description = "AI Dasturchidan cheksiz foydalanish va maxsus fayllarga kirish."
        payload = "premium_sub_payload"
        currency = "XTR"
        prices = [LabeledPrice("Premium Obuna", 50)]
        
        try:
            await context.bot.send_invoice(
                chat_id=chat_id,
                title=title,
                description=description,
                payload=payload,
                provider_token="",
                currency=currency,
                prices=prices,
                start_parameter="premium-subscription"
            )
        except Exception as e:
            logging.error(f"To'lov yuborishda xatolik: {e}")
            await query.answer("❌ To'lov tizimida xatolik! Iltimos BotFather orqali Stars to'lovini yoqing.", show_alert=True)

    elif data == "challenge_start":
        profile = await get_user(user_id)
        today = datetime.date.today()
        
        if profile['last_challenge_date'] == today and user_id != ADMIN_ID:
            return await query.answer(t['challenge_already_done'], show_alert=True)
            
        challenge = random.choice(CHALLENGES_DATA)
        context.user_data['current_challenge'] = challenge['text']
        context.user_data['state'] = 'in_challenge'
        
        text = t['challenge_problem'].format(text=challenge['text'])
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])
        
        await edit_or_send(query, context, text, keyboard)

    elif data == "theme_menu":
        await edit_or_send(query, context, t['theme_menu'], get_theme_keyboard(lang))

    elif data.startswith("theme_apply_"):
        theme_key = data.replace("theme_apply_", "")
        theme = THEMES_DATA.get(theme_key)
        if not theme: return
        
        properties_content = f"""background={theme['bg']}
foreground={theme['fg']}
cursor={theme['cursor']}
color0={theme['bg']}
color8=#555555
color1=#ff0000
color9=#ff5555
color2=#00ff00
color10=#55ff55
color3=#ffff00
color11=#ffff55
color4=#0000ff
color12=#5555ff
color5=#ff00ff
color13=#ff55ff
color6=#00ffff
color14=#55ffff
color7={theme['fg']}
color15=#ffffff
"""
        prop_file = BytesIO(properties_content.encode('utf-8'))
        prop_file.name = "colors.properties"
        
        text = t['theme_send'].format(theme_name=theme['name'])
        await context.bot.send_document(chat_id=chat_id, document=prop_file, caption=text, parse_mode='Markdown')

    elif data == "java_info":
        await edit_or_send(query, context, t['java_info_text'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]))

    elif data == "script_menu":
        await edit_or_send(query, context, t['script_cat_menu'], get_script_categories_keyboard(lang))
    elif data.startswith("script_cat_"):
        cat_key = data.replace("script_cat_", "")
        if 'selected_scripts' not in context.user_data: context.user_data['selected_scripts'] = []
        cat_name = SCRIPTS_DATA[cat_key]['name']
        text = t['script_items_menu'].format(cat_name=cat_name)
        await edit_or_send(query, context, text, get_script_items_keyboard(cat_key, lang, context.user_data['selected_scripts']))
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
        try: await query.edit_message_reply_markup(reply_markup=get_script_items_keyboard(cat_key, lang, selected))
        except: await edit_or_send(query, context, text, get_script_items_keyboard(cat_key, lang, selected))
    elif data == "script_clear":
        context.user_data['selected_scripts'] = []
        await query.answer("🗑 Barcha tanlovlar tozalandi!")
        await edit_or_send(query, context, t['script_cat_menu'], get_script_categories_keyboard(lang))
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

    elif data == "admin_stats":
        if user_id != ADMIN_ID: return
        if not db_pool: return await query.answer("Baza yo'q", show_alert=True)
        async with db_pool.acquire() as conn:
            total = await conn.fetchval('SELECT COUNT(*) FROM users')
            prem_users = await conn.fetchval('SELECT COUNT(*) FROM users WHERE is_premium = TRUE')
            top_score = await conn.fetchval('SELECT MAX(score) FROM users')
        text = f"📊 **Statistika**\n\n👥 Jami: {total} ta\n💎 Premium: {prem_users} ta\n🏆 Eng yuqori: {top_score}"
        await edit_or_send(query, context, text, InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="admin_menu")]]))
    elif data == "admin_points":
        if user_id != ADMIN_ID: return
        context.user_data['state'] = 'in_admin_points'
        await edit_or_send(query, context, t['admin_points_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="admin_menu")]]))
    elif data == "admin_bcast":
        if user_id != ADMIN_ID: return
        context.user_data['state'] = 'in_broadcast'
        await edit_or_send(query, context, t['admin_bcast_start'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="admin_menu")]]))
    elif data == "admin_add_file":
        if user_id != ADMIN_ID: return
        context.user_data['state'] = 'in_add_file'
        await edit_or_send(query, context, t['admin_file_wait'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="admin_menu")]]))
    elif data == "admin_ban":
        if user_id != ADMIN_ID: return
        context.user_data['state'] = 'in_ban_user'
        await edit_or_send(query, context, t['admin_ban_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="admin_menu")]]))
    elif data == "admin_unban":
        if user_id != ADMIN_ID: return
        context.user_data['state'] = 'in_unban_user'
        await edit_or_send(query, context, t['admin_unban_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="admin_menu")]]))
    elif data == "admin_menu":
        if user_id != ADMIN_ID: return
        await edit_or_send(query, context, t['admin_panel'], get_admin_keyboard(lang))
    elif data == "admin_close":
        if user_id != ADMIN_ID: return
        await query.message.delete()

    elif data.startswith("lang_"):
        lang = data.split("_")[1]
        context.user_data['lang'] = lang
        await add_user(user_id, lang)
        await edit_or_send(query, context, TEXTS[lang]['welcome'], get_main_menu(lang, user_id))
    elif data == "change_lang":
        context.user_data.pop('lang', None)
        await edit_or_send(query, context, TEXTS['uz']['choose_lang'], get_lang_keyboard())
    elif data == "my_profile":
        profile = await get_user(user_id)
        if not profile: return await query.answer("Xatolik: /start bosing.")
        level = get_level(profile['score'])
        status = "💎 Premium" if profile['is_premium'] else "🆓 Bepul"
        text = t['profile_text'].format(score=profile['score'], level=level, rank=0, status=status) # Rank logic simplified for now
        await edit_or_send(query, context, text, get_profile_keyboard(lang))
    elif data == "daily_bonus":
        success = await claim_daily_bonus(user_id)
        if success:
            await query.answer(t['bonus_claimed'], show_alert=True)
            profile = await get_user(user_id)
            level = get_level(profile['score'])
            status = "💎 Premium" if profile['is_premium'] else "🆓 Bepul"
            text = t['profile_text'].format(score=profile['score'], level=level, rank=0, status=status)
            await edit_or_send(query, context, text, get_profile_keyboard(lang))
        else:
            await query.answer(t['bonus_wait'], show_alert=True)
    elif data == "top_users":
        top_users = await get_top_users() 
        top_list = ""
        for i, u in enumerate(top_users):
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "🔹"
            top_list += f"{medal} {i+1}. ID: `{u['user_id']}` — **{u['score']}** ball\n"
        if not top_list: top_list = "Hozircha bo'sh."
        await edit_or_send(query, context, t['top_text'].format(list=top_list), InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]))

    elif data == "quiz_start":
        if 'seen_questions' not in context.user_data:
            context.user_data['seen_questions'] = []
            
        if len(context.user_data['seen_questions']) >= len(QUIZ_DATA):
            context.user_data['seen_questions'] = []
            await query.message.reply_text(t['quiz_end'])
            
        available_indices = [i for i in range(len(QUIZ_DATA)) if i not in context.user_data['seen_questions']]
        
        chosen_idx = random.choice(available_indices)
        context.user_data['seen_questions'].append(chosen_idx)
        context.user_data['current_quiz'] = QUIZ_DATA[chosen_idx]
        
        question_data = QUIZ_DATA[chosen_idx]
        text = t['quiz_start'] + f"\n\n❓ **{question_data['q'][lang]}**"
        await edit_or_send(query, context, text, get_quiz_keyboard(question_data['options'], question_data['answer'], lang))

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
            
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_next_quiz'], callback_data="quiz_start")], [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])
        await edit_or_send(query, context, text, keyboard)

    elif data == "ai_start":
        can_use, limit_left = await check_ai_limit(user_id)
        if not can_use:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_go_premium'], callback_data="premium_menu")], [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])
            return await edit_or_send(query, context, t['ai_limit_reached'], keyboard)
            
        context.user_data['state'] = 'in_ai'
        context.user_data['ai_history'] = [] # Reset history for new session
        prompt_text = t['ai_prompt']
        if limit_left < 999:
            prompt_text += "\n\n" + t['ai_limit_info'].format(limit=limit_left)
        await edit_or_send(query, context, prompt_text, InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]))
    elif data == "sec_start":
        await edit_or_send(query, context, t['sec_menu'], get_sec_menu(lang))
    elif data == "sec_cat_info": 
        await edit_or_send(query, context, t['sec_info_text'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back_cheat'], callback_data="sec_start")]]))
    elif data == "sec_cat_pass": 
        await edit_or_send(query, context, t['sec_pass_text'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back_cheat'], callback_data="sec_start")]]))
    elif data == "sec_cat_exploit": 
        await edit_or_send(query, context, t['sec_exploit_text'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back_cheat'], callback_data="sec_start")]]))
    elif data == "sec_cat_network": 
        await edit_or_send(query, context, t['sec_network_text'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back_cheat'], callback_data="sec_start")]]))
    elif data == "support_start":
        context.user_data['state'] = 'in_support'
        await edit_or_send(query, context, t['support_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]))
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
        await edit_or_send(query, context, text, InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]))
    elif data == "cheatsheet":
        await edit_or_send(query, context, t['cheatsheet_menu'], get_cheatsheet_keyboard(lang))
    elif data.startswith("cat_"):
        category = data.split("_")[1]
        commands = COMMANDS_DATA.get(category, [])
        text = f"**{t['cat_'+category]}**\n\n"
        for cmd, desc in commands: text += f"• `{cmd}` - {desc[lang]}\n"
        await edit_or_send(query, context, text, InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back_cheat'], callback_data="cheatsheet")], [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]))
    elif data.startswith("page_"):
        page = int(data.split("_")[1])
        text = t['text_page'].format(page=page)
        await edit_or_send(query, context, text, get_lessons_keyboard(page, lang))
        
    elif data.startswith("lesson_"):
        lesson_num = int(data.split("_")[1])
        message_id = LESSONS.get(lesson_num, lesson_num + 2)
        video_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_lessons_menu'], callback_data="page_1")]])
        try:
            await context.bot.copy_message(chat_id=chat_id, from_chat_id=VIDEO_CHANNEL, message_id=message_id, reply_markup=video_keyboard)
            await query.message.delete()
        except TelegramError as e:
            logging.error(f"Video nusxalashda xatolik (ID: {message_id}): {e}")
            await context.bot.send_message(chat_id=chat_id, text=t['text_error_vid'], parse_mode='Markdown')
            
    elif data == "lua_page_1":
        await edit_or_send(query, context, t['text_lua'], get_lua_lessons_keyboard(lang))
    elif data.startswith("lua_lesson_"):
        lesson_num = int(data.split("_")[2])
        message_id = LUA_LESSONS.get(lesson_num, 93)
        buttons = []
        if lesson_num == 2: buttons.append([InlineKeyboardButton(t['btn_python'], callback_data="python_extra")])
        buttons.append([InlineKeyboardButton(t['btn_lessons_menu'], callback_data="lua_page_1")])
        video_keyboard = InlineKeyboardMarkup(buttons)
        try:
            await context.bot.copy_message(chat_id=chat_id, from_chat_id=VIDEO_CHANNEL, message_id=message_id, reply_markup=video_keyboard)
            await query.message.delete()
        except TelegramError as e: 
            logging.error(f"Lua video xatosi (ID: {message_id}): {e}")
            await context.bot.send_message(chat_id=chat_id, text=t['text_error_vid'], parse_mode='Markdown')
    elif data == "python_extra":
        try:
            for v_id in PYTHON_EXTRA_VIDEOS: 
                await context.bot.copy_message(chat_id=chat_id, from_chat_id=VIDEO_CHANNEL, message_id=v_id)
            back_kb = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="lua_page_1")]])
            await context.bot.send_message(chat_id=chat_id, text=t['text_python_done'], reply_markup=back_kb)
        except TelegramError as e: 
            logging.error(f"Python video xatosi: {e}")
            await context.bot.send_message(chat_id=chat_id, text=t['text_error_vid'], parse_mode='Markdown')
    elif data == "back_to_start":
        context.user_data['state'] = None
        await edit_or_send(query, context, t['welcome'], get_main_menu(lang, user_id))

# ==========================================
# PRE-CHECKOUT VA TO'LOVNI QABUL QILISH
# ==========================================
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload == "premium_sub_payload":
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Xatolik yuz berdi.")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]
    
    payment_info = update.message.successful_payment
    if payment_info.invoice_payload == "premium_sub_payload":
        await make_premium(user_id)
        await update.message.reply_text(t['premium_success'], parse_mode='Markdown', reply_markup=get_main_menu(lang, user_id))

# ==========================================
# AI LOGIKASI (XOTIRA BILAN)
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
            if doc.file_name.endswith(('.py', '.lua', '.txt', '.js', '.cpp', '.c', '.html', '.java')):
                file_content = await (await doc.get_file()).download_as_bytearray()
                try:
                    text_content = file_content.decode('utf-8')
                    if len(text_content) > 80000: await msg.edit_text(t['ai_text_too_long']); return
                    user_query = f"Fayl nomi: {doc.file_name}\n\nKod:\n{text_content}\n\nIltimos, ushbu kodni tahlil qilib, xatolarini tuzatib, tayyor ishlaydigan holatga keltiring."
                except UnicodeDecodeError: await msg.edit_text(t['ai_unsupported_file']); return
            else: await msg.edit_text(t['ai_unsupported_file']); return
        else: await msg.edit_text(t['ai_video_error']); return

        ai_reply, error_logs = "", []
        
        # Xotirani olish
        if 'ai_history' not in context.user_data:
            user_db = await get_user(user_id)
            history_str = user_db['chat_history'] if user_db else '[]'
            try: context.user_data['ai_history'] = json.loads(history_str)
            except: context.user_data['ai_history'] = []
            
        history = context.user_data['ai_history']
        
        # Xotira to'lib ketmasligi uchun faqat oxirgi 10 ta xabarni saqlash
        if len(history) > 10:
            history = history[-10:]
            
        history.append({"role": "user", "content": user_query})

        system_prompt = """You are an elite Senior Software Engineer and an expert in Termux, Linux, Python, Lua, Java, and Cybersecurity. 
Your goal is to provide PERFECT, production-ready, fully working code. 
Never leave placeholders. Explain your code clearly and concisely.
Always format code inside markdown blocks (```python, ```lua, ```java, etc.).
If the user asks a casual question, answer briefly but pivot back to coding.
Reply in the user's language (Uzbek, Russian, English, or Arabic)."""

        messages = [{"role": "system", "content": system_prompt}] + history

        if is_image and gemini_client:
            try:
                response = await gemini_client.aio.models.generate_content(model='gemini-1.5-flash', contents=[types.Part.from_text(text=system_prompt + " Look at this image and fix the code error."), types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg')])
                ai_reply = response.text
            except Exception as e: error_logs.append(f"Gemini Vision: {str(e)}")

        if not ai_reply and openrouter_client and not is_image:
            try:
                response = await openrouter_client.chat.completions.create(model="qwen/qwen-2.5-coder-32b-instruct:free", messages=messages, max_tokens=4000)
                ai_reply = response.choices[0].message.content
            except Exception as e: error_logs.append(f"OpenRouter: {str(e)}")

        if not ai_reply and mistral_client and not is_image:
            try:
                response = await mistral_client.chat.completions.create(model="codestral-latest", messages=messages, max_tokens=4000)
                ai_reply = response.choices[0].message.content
            except Exception as e: error_logs.append(f"Mistral: {str(e)}")

        if not ai_reply and groq_client and not is_image:
            try:
                response = await groq_client.chat.completions.create(model="llama-3.3-70b-versatile", messages=messages, max_tokens=4000)
                ai_reply = response.choices[0].message.content
            except Exception as e: error_logs.append(f"Groq: {str(e)}")

        if not ai_reply and gemini_client and not is_image:
            try:
                response = await gemini_client.aio.models.generate_content(model='gemini-1.5-flash', contents=user_query)
                ai_reply = response.text
            except Exception as e: error_logs.append(f"Gemini Text: {str(e)}")

        if not ai_reply:
            await msg.edit_text(t['ai_error'].format(error="Barcha AI limitlari band.")); return

        # AI javobini xotiraga qo'shish va saqlash
        history.append({"role": "assistant", "content": ai_reply})
        context.user_data['ai_history'] = history
        await save_chat_history(user_id, history)

        code_match = re.search(r'```(?:python|py|lua|javascript|js|cpp|c|java)?\s*(.*?)```', ai_reply, re.DOTALL | re.IGNORECASE)
        if code_match:
            code_text = code_match.group(1).strip()
            if "lua" in user_query.lower() or (update.message.document and update.message.document.file_name.endswith('.lua')):
                filename = "code.lua"
                lang_name = "Lua"
            elif "java" in user_query.lower() or (update.message.document and update.message.document.file_name.endswith('.java')):
                filename = "Main.java"
                lang_name = "Java"
            else:
                filename = "code.py"
                lang_name = "Python"
                
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
# KUNLIK MASALANI QABUL QILISH (CHALLENGE)
# ==========================================
async def handle_challenge_solution(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]
    challenge_text = context.user_data.get('current_challenge')
    
    user_code = update.message.text or (await update.message.document.get_file()).file_id if update.message.document else None
    if not user_code:
        return await update.message.reply_text(t['challenge_no_code'])

    msg = await update.message.reply_text(t['challenge_wait'])
    
    eval_prompt = f"""Foydalanuvchi quyidagi masalani yechish uchun kod yubordi:
Masala: {challenge_text}

Kod:
{user_code}

Vazifangiz: Ushbu kodni qat'iy tekshiring. 
Agar kod masalani to'liq va xatosiz yechsa, faqat 'CORRECT' deb javob bering.
Agar kodda xatolik bo'lsa yoki to'liq bo'lmasa, 'INCORRECT: [xatolik sababi yoki yechim yo'li]' deb javob bering. 
Boshqa hech qanday qo'shimcha gap yozmang."""

    ai_reply = ""
    try:
        if openrouter_client:
            response = await openrouter_client.chat.completions.create(model="qwen/qwen-2.5-coder-32b-instruct:free", messages=[{"role": "user", "content": eval_prompt}], max_tokens=300)
            ai_reply = response.choices[0].message.content.strip()
        elif groq_client:
            response = await groq_client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": eval_prompt}], max_tokens=300)
            ai_reply = response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Challenge eval error: {e}")

    if "CORRECT" in ai_reply.upper():
        await add_score(user_id, 30)
        await update_challenge_date(user_id)
        context.user_data['state'] = None
        context.user_data['current_challenge'] = None
        await msg.edit_text(t['challenge_correct'], parse_mode='Markdown')
    else:
        feedback = ai_reply.replace("INCORRECT:", "").strip()
        await msg.edit_text(t['challenge_wrong'].format(feedback=feedback), parse_mode='Markdown')

# ==========================================
# XABARLARNI QABUL QILISH VA ADMIN
# ==========================================
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]
    
    if context.user_data.get('state') == 'in_ai':
        await handle_ai_message(update, context); return

    if context.user_data.get('state') == 'in_challenge':
        await handle_challenge_solution(update, context); return

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
            await add_file_db(title, file_id, ftype, is_premium=False) 
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
            
            msg = await update.message.reply_text(t['admin_points_wait'], parse_mode='Markdown')
            
            success, fail = 0, 0
            total_users = 0
            if db_pool:
                async with db_pool.acquire() as conn:
                    users = await conn.fetch('SELECT user_id FROM users')
                    total_users = len(users)
                
                broadcast_text = f"🎁 **Aksiya!**\n\nAdmin tomonidan barcha foydalanuvchilarga **+{points} ball** qo'shildi! 🎉\n\nProfilingizga kirib tekshirishingiz mumkin."
                
                for u in users:
                    if u['user_id'] == ADMIN_ID: continue
                    try:
                        await context.bot.send_message(chat_id=u['user_id'], text=broadcast_text, parse_mode='Markdown')
                        success += 1
                        await asyncio.sleep(0.05) 
                    except Exception:
                        fail += 1
                        
            await msg.edit_text(t['admin_points_done'].format(points=points, success=success, fail=fail), parse_mode='Markdown')
            context.user_data['state'] = None
        else:
            await update.message.reply_text("❌ Iltimos faqat raqam kiriting!")
        return

    if user.id == ADMIN_ID and context.user_data.get('state') == 'in_ban_user':
        if update.message.text.isdigit():
            target_id = int(update.message.text)
            await toggle_ban(target_id, True)
            await update.message.reply_text(f"✅ {target_id} muvaffaqiyatli ban qilindi.")
            context.user_data['state'] = None
        else:
            await update.message.reply_text("❌ Iltimos faqat ID raqamini kiriting!")
        return
        
    if user.id == ADMIN_ID and context.user_data.get('state') == 'in_unban_user':
        if update.message.text.isdigit():
            target_id = int(update.message.text)
            await toggle_ban(target_id, False)
            await update.message.reply_text(f"✅ {target_id} muvaffaqiyatli unban qilindi.")
            context.user_data['state'] = None
        else:
            await update.message.reply_text("❌ Iltimos faqat ID raqamini kiriting!")
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
                await update.message.reply_text(t['support_sent'], reply_markup=get_main_menu(lang, user.id))
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
        total_users = len(users)
        
    success, fail = 0, 0
    for u in users:
        if u['user_id'] == ADMIN_ID: continue
        try:
            await context.bot.copy_message(chat_id=u['user_id'], from_chat_id=update.message.chat_id, message_id=update.message.message_id)
            success += 1; await asyncio.sleep(0.05)
        except Exception: fail += 1
        
    context.user_data['state'] = None
    await msg.edit_text(f"✅ Yakunlandi!\nBazada jami: {total_users} ta\nYuborildi: {success}\nXatolik: {fail}")

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
application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
application.add_handler(CallbackQueryHandler(button_tap))
application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_messages))

app = FastAPI()

@app.on_event("startup")
async def on_startup():
    await init
