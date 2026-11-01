import os
import logging
import random
import aiohttp
import re
import asyncio
import asyncpg
import datetime
import hashlib
import base64
import uuid
import secrets
import string
import json as json_lib
from urllib.parse import quote
from io import BytesIO
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    filters, ContextTypes, PreCheckoutQueryHandler
)
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
PENDING_VIDEOS = {}
AUTO_ADD_TIMEOUT = 600

# ==========================================
# YORDAMCHI
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

def get_file_button_info(file_name, file_type):
    name = (file_name or "").lower()
    if name.endswith('.apk'): return "📥 APK YUKLAB OLISH"
    elif name.endswith('.py'): return "🐍 PYTHON OLISH"
    elif name.endswith('.lua'): return "🌙 LUA OLISH"
    elif name.endswith(('.zip', '.rar', '.7z', '.tar.gz')): return "📦 DASTURNI OLISH"
    elif name.endswith('.pdf'): return "📖 KITOB OLISH"
    elif file_type == 'video': return "🎥 VIDEONI OLISH"
    elif file_type == 'photo': return "🖼 RASMNI OLISH"
    return "📥 FAYLNI OLISH"

# ==========================================
# BAZA
# ==========================================
async def init_db():
    global db_pool
    if not DATABASE_URL: return
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
        async with db_pool.acquire() as conn:
            await conn.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY, lang VARCHAR(5) DEFAULT 'uz',
                score INT DEFAULT 0, is_premium BOOLEAN DEFAULT FALSE,
                ai_requests_today INT DEFAULT 0, last_ai_date DATE DEFAULT CURRENT_DATE,
                last_bonus TIMESTAMP DEFAULT '1970-01-01 00:00:00',
                last_challenge_date DATE DEFAULT '1970-01-01',
                streak_days INT DEFAULT 0,
                last_streak_date DATE DEFAULT '1970-01-01',
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            await conn.execute('''CREATE TABLE IF NOT EXISTS files (
                id SERIAL PRIMARY KEY, title VARCHAR(255), file_id VARCHAR(255),
                file_type VARCHAR(20), is_premium BOOLEAN DEFAULT FALSE,
                category_id INT, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            await conn.execute('''CREATE TABLE IF NOT EXISTS file_categories (
                id SERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL UNIQUE,
                icon VARCHAR(10) DEFAULT '📁',
                parent_id INT REFERENCES file_categories(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            await conn.execute("ALTER TABLE files ADD COLUMN IF NOT EXISTS category_id INT")
            await conn.execute("ALTER TABLE file_categories ADD COLUMN IF NOT EXISTS parent_id INT REFERENCES file_categories(id) ON DELETE CASCADE")
            await conn.execute('''CREATE TABLE IF NOT EXISTS updates_history (
                id SERIAL PRIMARY KEY, title VARCHAR(255), description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            await conn.execute('''CREATE TABLE IF NOT EXISTS auto_lessons (
                id SERIAL PRIMARY KEY, lesson_number INT UNIQUE,
                message_id INT, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            await conn.execute('''CREATE TABLE IF NOT EXISTS bot_settings (
                key VARCHAR(50) PRIMARY KEY, value VARCHAR(255)
            )''')
            await conn.execute("INSERT INTO bot_settings (key, value) VALUES ('auto_forward', 'off') ON CONFLICT (key) DO NOTHING")
            await conn.execute('''CREATE TABLE IF NOT EXISTS video_attachments (
                lesson_number INT PRIMARY KEY, file_id VARCHAR(255),
                file_type VARCHAR(20), file_name VARCHAR(255),
                button_text VARCHAR(100) DEFAULT '📥 DASTURNI OLISH',
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
        await ensure_default_categories()
    except Exception as e:
        logging.error(f"Baza xatosi: {e}")

async def ensure_default_categories():
    if not db_pool: return
    async with db_pool.acquire() as conn:
        # Eski avtomatik Python/Lua bo'limlari endi ishlatilmaydi.
        await conn.execute("""DELETE FROM files WHERE category_id IN
            (SELECT id FROM file_categories WHERE name IN ('Lua Fayllar', 'Python Fayllar'))""")
        await conn.execute("DELETE FROM file_categories WHERE name IN ('Lua Fayllar', 'Python Fayllar')")

async def add_user(user_id, lang='uz'):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        await conn.execute('''INSERT INTO users (user_id, lang) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET lang = EXCLUDED.lang''', user_id, lang)

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
        user = await conn.fetchrow('SELECT score, last_bonus, is_premium, last_challenge_date, streak_days FROM users WHERE user_id = $1', user_id)
        if not user: return None
        rank = await conn.fetchval('SELECT COUNT(*) FROM users WHERE score > $1', user['score'])
        return {"score": user['score'], "rank": rank + 1, "last_bonus": user['last_bonus'],
                "is_premium": user['is_premium'], "last_challenge_date": user['last_challenge_date'],
                "streak_days": user['streak_days'] or 0}

async def update_challenge_date(user_id):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        await conn.execute('UPDATE users SET last_challenge_date = $1 WHERE user_id = $2', datetime.date.today(), user_id)

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
        if user['ai_requests_today'] < 5:
            await conn.execute('UPDATE users SET ai_requests_today = ai_requests_today + 1 WHERE user_id = $1', user_id)
            return True, 5 - user['ai_requests_today']
        return False, 0

async def make_premium(user_id):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        await conn.execute('UPDATE users SET is_premium = TRUE WHERE user_id = $1', user_id)

async def get_top_users():
    if not db_pool: return []
    async with db_pool.acquire() as conn:
        return await conn.fetch('SELECT user_id, score FROM users ORDER BY score DESC LIMIT 10')

async def get_all_categories():
    if not db_pool: return []
    async with db_pool.acquire() as conn:
        return await conn.fetch('SELECT id, name, icon, parent_id FROM file_categories WHERE parent_id IS NULL ORDER BY id ASC')

async def get_child_categories(parent_id):
    if not db_pool: return []
    async with db_pool.acquire() as conn:
        return await conn.fetch('SELECT id, name, icon, parent_id FROM file_categories WHERE parent_id = $1 ORDER BY id ASC', parent_id)

async def get_category_by_name(name):
    if not db_pool: return None
    async with db_pool.acquire() as conn:
        return await conn.fetchrow('SELECT id, name, icon, parent_id FROM file_categories WHERE name = $1', name)

async def add_category(name, icon='📁', parent_id=None):
    if not db_pool: return None
    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow('SELECT id FROM file_categories WHERE name = $1 AND parent_id IS NOT DISTINCT FROM $2', name, parent_id)
        if existing:
            return existing['id']
        return await conn.fetchval('INSERT INTO file_categories (name, icon, parent_id) VALUES ($1, $2, $3) RETURNING id', name, icon, parent_id)

async def get_category_by_id(cat_id):
    if not db_pool: return None
    async with db_pool.acquire() as conn:
        return await conn.fetchrow('SELECT id, name, icon, parent_id FROM file_categories WHERE id = $1', cat_id)

async def get_files_by_category(cat_id):
    if not db_pool: return []
    async with db_pool.acquire() as conn:
        return await conn.fetch('SELECT id, title, is_premium, file_type FROM files WHERE category_id = $1 ORDER BY id ASC', cat_id)

async def add_file_db_cat(title, file_id, file_type, category_id, is_premium=False):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        await conn.execute('INSERT INTO files (title, file_id, file_type, category_id, is_premium) VALUES ($1, $2, $3, $4, $5)',
                          title, file_id, file_type, category_id, is_premium)

async def delete_category(cat_id):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        await conn.execute('''WITH RECURSIVE tree AS (
            SELECT id FROM file_categories WHERE id = $1
            UNION ALL SELECT c.id FROM file_categories c JOIN tree t ON c.parent_id = t.id
        ) DELETE FROM files WHERE category_id IN (SELECT id FROM tree)''', cat_id)
        await conn.execute('''WITH RECURSIVE tree AS (
            SELECT id FROM file_categories WHERE id = $1
            UNION ALL SELECT c.id FROM file_categories c JOIN tree t ON c.parent_id = t.id
        ) DELETE FROM file_categories WHERE id IN (SELECT id FROM tree)''', cat_id)

async def delete_file_by_id(file_id):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        await conn.execute('DELETE FROM files WHERE id = $1', file_id)

async def get_file_by_id(file_id):
    if not db_pool: return None
    async with db_pool.acquire() as conn:
        return await conn.fetchrow('SELECT * FROM files WHERE id = $1', file_id)

async def count_files_in_category(cat_id):
    if not db_pool: return 0
    async with db_pool.acquire() as conn:
        return await conn.fetchval('SELECT COUNT(*) FROM files WHERE category_id = $1', cat_id) or 0

async def get_setting(key, default=None):
    if not db_pool: return default
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow('SELECT value FROM bot_settings WHERE key = $1', key)
        return row['value'] if row else default

async def set_setting(key, value):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        await conn.execute('''INSERT INTO bot_settings (key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value''', key, str(value))

async def add_update_db(title, description):
    if not db_pool: return
    async with db_pool.acquire() as conn:
        await conn.execute('INSERT INTO updates_history (title, description) VALUES ($1, $2)', title, description)

async def get_recent_updates(limit=5):
    if not db_pool: return []
    async with db_pool.acquire() as conn:
        return await conn.fetch('SELECT title, description, created_at FROM updates_history ORDER BY id DESC LIMIT $1', limit)

async def get_all_lessons():
    lessons = {i: i+2 for i in range(1, 46)}
    lessons[46] = 103
    lessons[47] = 107
    if db_pool:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch('SELECT lesson_number, message_id FROM auto_lessons')
            for row in rows:
                lessons[row['lesson_number']] = row['message_id']
    return lessons

async def get_max_lesson_number():
    max_num = 47
    if db_pool:
        async with db_pool.acquire() as conn:
            db_max = await conn.fetchval('SELECT MAX(lesson_number) FROM auto_lessons')
            if db_max: max_num = max(max_num, db_max)
    return max_num

def get_level(score):
    if score < 100: return "🥉 Boshlovchi"
    elif score < 300: return "🥈 O'rta"
    elif score < 600: return "🥇 Ilg'or"
    return "💎 Ekspert"

def get_streak_reward(days):
    rewards = {1: 10, 2: 15, 3: 25, 4: 30, 5: 30, 6: 30, 7: 75,
               8: 40, 9: 40, 10: 50, 11: 40, 12: 40, 13: 40, 14: 150,
               15: 50, 16: 50, 17: 50, 18: 50, 19: 50, 20: 60,
               21: 60, 22: 60, 23: 60, 24: 60, 25: 70, 26: 70, 27: 70,
               28: 70, 29: 70, 30: 500}
    return rewards.get(days, 50)

async def claim_streak(user_id):
    if not db_pool: return False, 0, 0, False, False
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow('SELECT streak_days, last_streak_date FROM users WHERE user_id = $1', user_id)
        if not user: return False, 0, 0, False, False
        today = datetime.date.today()
        last_date = user['last_streak_date']
        current_streak = user['streak_days'] or 0
        if last_date == today: return False, current_streak, 0, False, True
        yesterday = today - datetime.timedelta(days=1)
        if last_date == yesterday:
            new_streak = current_streak + 1; is_reset = False
        else:
            new_streak = 1; is_reset = (current_streak > 0)
        reward = get_streak_reward(new_streak)
        await conn.execute('UPDATE users SET streak_days = $1, last_streak_date = $2, score = score + $3 WHERE user_id = $4',
                           new_streak, today, reward, user_id)
        if new_streak == 30:
            await conn.execute('UPDATE users SET is_premium = TRUE WHERE user_id = $1', user_id)
        return True, new_streak, reward, is_reset, False

async def is_subscribed(user_id, context):
    if user_id == ADMIN_ID: return True
    try:
        member = await context.bot.get_chat_member(chat_id=FORCE_SUB_CHANNEL, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception:
        return True

# ==========================================
# MA'LUMOTLAR
# ==========================================
LUA_LESSONS = {1: 93, 2: 94, 3: 97, 4: 98, 5: 99, 6: 100, 7: 101, 8: 104}
PYTHON_EXTRA_VIDEOS = [106]

CHALLENGES_DATA = [
    {"id": 1, "text": "Python yordamida berilgan sonning faktorialini hisoblovchi funksiya yozing."},
    {"id": 2, "text": "Berilgan so'z palindrom ekanligini tekshiruvchi kod yozing."},
    {"id": 3, "text": "1 dan N gacha bo'lgan sonlar yig'indisini hisoblovchi kod yozing."},
    {"id": 4, "text": "Berilgan ro'yxatdagi eng katta sonni topuvchi funksiya yozing."},
    {"id": 5, "text": "FizzBuzz masalasi: 1 dan 100 gacha."}
]

THEMES_DATA = {
    "matrix": {"name": "🟢 Matrix", "bg": "#000000", "fg": "#00ff00", "cursor": "#00ff00"},
    "hacker": {"name": "🔴 Hacker", "bg": "#0a0a0a", "fg": "#ff0000", "cursor": "#ff0000"},
    "cyberpunk": {"name": "🌆 Cyberpunk", "bg": "#1a0033", "fg": "#ffff00", "cursor": "#ff00ff"},
    "dracula": {"name": "🧛 Dracula", "bg": "#282a36", "fg": "#f8f8f2", "cursor": "#50fa7b"},
    "nord": {"name": "❄️ Nord", "bg": "#2e3440", "fg": "#d8dee9", "cursor": "#88c0d0"}
}

SCRIPTS_DATA = {
    "dev": {"name": "💻 Dasturlash", "items": {"python": {"name": "🐍 Python", "pkg": "python", "type": "pkg"}, "git": {"name": "🐙 Git", "pkg": "git", "type": "pkg"}, "node": {"name": "🟢 Node.js", "pkg": "nodejs", "type": "pkg"}, "curl": {"name": "📡 Curl", "pkg": "curl", "type": "pkg"}, "wget": {"name": "📥 Wget", "pkg": "wget", "type": "pkg"}, "nano": {"name": "📝 Nano", "pkg": "nano", "type": "pkg"}, "vim": {"name": "📝 Vim", "pkg": "vim", "type": "pkg"}, "micro": {"name": "📝 Micro", "pkg": "micro", "type": "pkg"}}},
    "hacking": {"name": "🛡️ Kiberxavfsizlik", "items": {"nmap": {"name": "🌐 Nmap", "pkg": "nmap", "type": "pkg"}, "hydra": {"name": "🔑 Hydra", "pkg": "hydra", "type": "pkg"}, "sqlmap": {"name": "💥 SQLmap", "pkg": "sqlmap", "type": "pip"}, "metasploit": {"name": "💀 Metasploit", "pkg": "metasploit", "type": "pkg"}, "john": {"name": "🔓 John The Ripper", "pkg": "john", "type": "pkg"}, "nikto": {"name": "🕵️ Nikto", "pkg": "nikto", "type": "pkg"}, "aircrack": {"name": "📡 Aircrack-ng", "pkg": "aircrack-ng", "type": "pkg"}, "tshark": {"name": "🦈 Tshark", "pkg": "tshark", "type": "pkg"}}},
    "media": {"name": "🎬 Media va Tarmoq", "items": {"ffmpeg": {"name": "🎞️ FFmpeg", "pkg": "ffmpeg", "type": "pkg"}, "ytdlp": {"name": "📥 yt-dlp", "pkg": "yt-dlp", "type": "pip"}, "imagemagick": {"name": "🖼️ ImageMagick", "pkg": "imagemagick", "type": "pkg"}, "openssh": {"name": "🔐 OpenSSH", "pkg": "openssh", "type": "pkg"}, "net-tools": {"name": "🌐 Net-tools", "pkg": "net-tools", "type": "pkg"}, "traceroute": {"name": "🛣️ Traceroute", "pkg": "traceroute", "type": "pkg"}, "dnsutils": {"name": "🔍 DNS Utils", "pkg": "dnsutils", "type": "pkg"}}},
    "style": {"name": "🎨 Chiroyli Termux", "items": {"zsh": {"name": "🐚 Zsh", "pkg": "zsh", "type": "pkg"}, "ohmyzsh": {"name": "✨ Oh-My-Zsh", "pkg": "curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh | bash", "type": "custom"}, "termuxstyle": {"name": "🎨 Termux Styling", "pkg": "termux-styling", "type": "pkg"}, "figlet": {"name": "🔠 Figlet", "pkg": "figlet", "type": "pkg"}, "lolcat": {"name": "🌈 Lolcat", "pkg": "lolcat", "type": "pkg"}, "neofetch": {"name": "💻 Neofetch", "pkg": "neofetch", "type": "pkg"}}}
}

# ==========================================
# MATNLAR
# ==========================================
TEXTS = {
    'uz': {
        'choose_lang': "👋 **Assalomu alaykum!**\n\nIltimos, o'zingizga qulay tilni tanlang:",
        'welcome': "👋 **Assalomu alaykum!**\n\nMen **Termux va Dasturlash** bo'yicha yordamchi botman.",
        'btn_termux': "📽️ TERMUX DARSLIKLAR", 'btn_lua': "📽️ LUA PAK DARSLIK",
        'btn_java': "☕ JAVA DASTURLASH", 'btn_apk': "📥 APK YUKLAB OLISH",
        'btn_ai': "🤖 AI Dasturchi", 'btn_profile': "👤 Mening profilim",
        'btn_top': "🏆 Top 10", 'btn_quiz': "🧠 Test (Ball)", 'btn_security': "🛡️ Kiberxavfsizlik",
        'btn_support': "✉️ Admin", 'btn_tip': "💡 Maslahat", 'btn_cheatsheet': "📜 Buyruqlar",
        'btn_change_lang': "🌐 Til", 'btn_scripts': "📦 Skript Yaratish", 'btn_files': "🗂 Fayllar",
        'btn_premium': "💎 Premium", 'btn_challenge': "🧩 Kunlik Masala", 'btn_theme': "🎨 Termux Temasi",
        'btn_back': "🔙 Bosh menyu", 'btn_prev': "⬅️", 'btn_next': "➡️",
        'btn_python': "🐍 PYTHON OLISH", 'btn_lessons_menu': "📚 Menyu", 'btn_back_cheat': "🔙 Orqaga",
        'btn_updates': "🆕 Yangilanishlar", 'btn_devtools': "🧰 Developer Tools", 'streak_btn': "🔥 Kunlik Streak",
        'force_sub_text': "⚠️ **Diqqat!**\n\nBotdan to'liq foydalanish uchun kanalimizga a'zo bo'ling:",
        'btn_join': "📢 A'zo bo'lish", 'btn_check': "✅ Tekshirish", 'force_sub_error': "❌ Siz hali a'zo bo'lmadingiz!",
        'challenge_menu': "🧩 **Kunlik Masala**",
        'challenge_problem': "📝 **Bugungi masala:**\n\n{text}\n\n💻 *Kodni yuboring:*",
        'challenge_already_done': "✅ Siz bugungi masalani yechdingiz!",
        'challenge_wait': "🤖 AI tekshirilmoqda...",
        'challenge_correct': "✅ **To'g'ri!** 🎉 **+30 ball**",
        'challenge_wrong': "❌ **Xato!**\n\n{feedback}",
        'challenge_no_code': "⚠️ Kod yuboring.",
        'theme_menu': "🎨 **Termux Terminal Dizayni**\n\nRangni tanlang — bot `colors.properties` faylini beradi.",
        'theme_send': "✅ **{theme_name} tayyor!**\n\n**O'rnatish:**\n1. Yuklab olingan `colors.properties` faylini Termux'ning `~/.termux/` papkasiga joylashtiring.\n2. Termux'da `termux-reload-settings` buyrug'ini bering.\n\nMana fayl:",
        'script_cat_menu': "📦 **Skript Yaratuvchi**\n\nBo'limni tanlang:",
        'script_items_menu': "⚙️ **{cat_name}**\n\nDasturlarni tanlang:",
        'btn_generate_script': "🚀 Yaratish", 'btn_clear_scripts': "🗑 Tozalash", 'btn_back_to_cats': "🔙 Orqaga",
        'script_empty': "⚠️ Dastur tanlang!", 'script_done': "✅ **Tayyor!**\n\n`bash install.sh` bilan ishga tushiring.",
        'files_menu': "🗂 **Fayllar Markazi**\n\nPapkani tanlang:",
        'files_empty': "Hozircha papkalar yo'q. Tez orada qo'shiladi!",
        'files_cat_menu': "📂 **{cat_name}**\n\nFaylni tanlang:",
        'files_cat_empty': "Bu papka hozircha bo'sh.",
        'files_back_to_cats': "🔙 Papkalarga qaytish",
        'file_sending': "⏳ Fayl yuborilmoqda...",
        'file_premium_locked': "🔒 Bu fayl faqat Premium obunachilar uchun!",
        'admin_file_choose_cat': "📂 **Qaysi papkaga qo'shmoqchisiz?**\n\nPapka tanlang yoki yangi yarating:",
        'admin_file_no_cats': "📂 **Fayl qo'shish**\n\nHozircha papkalar yo'q.\nBoshlash uchun yangi papka yarating:",
        'admin_file_new_cat_prompt': "➕ **Yangi papka yaratish**\n\nPapka nomini yozing:\n\n_Misol: `Python darsliklar` yoki `APK fayllar`_",
        'admin_file_cat_created': "✅ **Papka yaratildi:** {name}",
        'admin_file_send_to': "📎 **\"{cat_name}\" papkasiga fayl yuboring:**\n\n_(Hujjat, Video yoki Rasm)_",
        'admin_file_title_prompt': "✍️ **Fayl nomini va tavsifini yozing:**\n\n_Misol: `Python 3.12 o'rnatish qo'llanmasi`_",
        'admin_btn_new_cat': "➕ Yangi papka yaratish",
        'admin_btn_del_cat': "🗑 Papkani o'chirish",
        'admin_file_choose_del': "🗑 **Qaysi papkani o'chirmoqchisiz?**",
        'admin_cat_deleted': "✅ Papka va undagi barcha fayllar o'chirildi!",
        'admin_cat_del_confirm': "⚠️ **{cat_name}** papkasini o'chirishni tasdiqlaysizmi?\n\n_(Ichidagi barcha fayllar ham o'chadi)_",
        'admin_file_deleted': "✅ Fayl o'chirildi!",
        'admin_file_saved': "✅ Fayl saqlandi!",
        'premium_menu': "💎 **Premium Obuna**\n\n✅ Cheksiz AI\n✅ Premium fayllar\n\n💰 **50 Stars** — 1 oy",
        'btn_buy_premium': "⭐️ 50 Stars evaziga olish",
        'premium_success': "🎉 **Premium faollashtirildi!**",
        'ai_limit_reached': "⚠️ **Limit tugadi!** Kuniga 5 ta bepul. Premium oling.",
        'btn_go_premium': "💎 Premium olish",
        'admin_panel': "👑 **Admin Panel**",
        'admin_btn_stats': "📊 Statistika", 'admin_btn_bcast': "📢 Xabar",
        'admin_btn_points': "🎁 Ball berish", 'admin_btn_add_file': "➕ Fayl",
        'admin_btn_close': "❌ Yopish",
        'admin_btn_update': "📣 Yangilanish e'lon qilish",
        'admin_btn_auto_fwd_on': "🔛 Auto-forward: YOQILGAN",
        'admin_btn_auto_fwd_off': "🔴 Auto-forward: O'CHIRILGAN",
        'admin_points_prompt': "🎁 **Aksiya!** Ball miqdori:",
        'admin_points_wait': "⏳...",
        'admin_points_done': "✅ **Aksiya!**\n🎁 +{points}\n📩 {success}\n❌ {fail}",
        'admin_file_cancel': "❌ Bekor qilindi.",
        'admin_update_prompt': "📣 **Yangilanish e'lon qilish**\n\nXabar matnini yozing:",
        'admin_update_wait': "⏳ Yuborilmoqda...",
        'admin_update_done': "✅ **Yuborildi!**\n📩 {success}\n❌ {fail}",
        'admin_toggle_on': "✅ **Auto-forward yoqildi!**\n\nEndi kanalga video qo'shsangiz, 10 daqiqa ichida fayl yuboring yoki /done yozing.",
        'admin_toggle_off': "🔴 **Auto-forward o'chirildi.**",
        'text_page': "📚 **Darsliklar**\n\nSahifa: {page} / {total}",
        'text_lua': "📚 **LUA DARSLIKLARI**",
        'text_python_done': "Mana Python darsligi! ✅",
        'text_error_vid': "❌ **Video topilmadi.**\n\nBot kanalda admin ekanligini tekshiring.",
        'tip_header': "💡 **Maslahat:**\n\n",
        'cheatsheet_menu': "📜 **Buyruqlar**\n\nBo'limni tanlang:",
        'cat_files': "📁 Fayllar", 'cat_packages': "📦 Paketlar", 'cat_network': "🌐 Tarmoq", 'cat_system': "⚙️ Tizim",
        'apk_caption': "📱 **Termux APK**", 'apk_file_name': "Termux.apk", 'apk_loading': "⏳...", 'apk_too_big': "⚠️", 'apk_error': "❌ Xatolik!",
        'support_prompt': "✉️ **Admin**\n\nXabaringizni yozing:",
        'support_sent': "✅ Yuborildi!", 'support_reply': "📬 **Admin:**\n\n",
        'profile_text': "👤 **Profil**\n\n⭐ **Ball:** {score}\n🏅 **Daraja:** {level}\n📊 **O'rin:** #{rank}\n💎 **Holat:** {status}",
        'btn_daily_bonus': "🎁 Kunlik bonus", 'bonus_claimed': "✅ +20!", 'bonus_wait': "⏳ Ertaga!",
        'top_text': "🏆 **Top 10:**\n\n{list}",
        'quiz_start': "🧠 **Test!** +10 ball.\n\n❓ *Savol:*",
        'quiz_correct': "✅ **To'g'ri!** (+10)",
        'quiz_wrong': "❌ **Xato!** Javob: **{answer}**",
        'quiz_end': "🎉 Barcha savollar tugadi!",
        'btn_next_quiz': "➡️ Keyingi",
        'sec_menu': "🛡️ **Kiberxavfsizlik**\n\n⚠️ Faqat o'z tizimingizda!",
        'sec_info': "🔍 Ma'lumot", 'sec_pass': "🔑 Parol", 'sec_exploit': "💥 Zaiflik", 'sec_network': "📡 Tarmoq",
        'sec_info_text': "Nmap: `pkg install nmap`", 'sec_pass_text': "Hydra: `pkg install hydra`",
        'sec_exploit_text': "SQLmap: `pip install sqlmap`", 'sec_network_text': "Tshark: `pkg install tshark`",
        'admin_bcast_start': "📢 Xabar yuboring:", 'admin_bcast_wait': "⏳...", 'admin_bcast_done': "✅ {success}, ❌ {fail}", 'admin_bcast_cancel': "❌ Bekor",
        'ai_prompt': "🤖 **AI Dasturchi**\n\nTopshiriq bering yoki kod yuboring.",
        'ai_wait': "🧠...", 'ai_error': "❌ {error}", 'ai_code_found': "✅",
        'ai_no_code': "🤖 **AI:**\n\n{text}",
        'ai_vision_error': "⚠️", 'ai_unsupported_file': "⚠️ Faqat kod.", 'ai_video_error': "🎥",
        'ai_file_too_large': "⚠️ Katta.", 'ai_text_too_long': "⚠️ Uzun.", 'ai_not_coding': "🤖 Faqat dasturlash.",
        'ai_limit_info': "ℹ️ *Qoldi: {limit} ta*",
        'java_info_text': "☕ **Java Termux'da**\n\n**1. O'rnatish:**\n```bash\npkg update && pkg upgrade -y\npkg install openjdk-17 -y\n```\n\n**2. Tekshirish:**\n`java -version`\n\n**3. Fayl yaratish:**\n```bash\nnano Salom.java\n```\n\n**4. Kod:**\n```java\npublic class Salom {\n    public static void main(String[] args) {\n        System.out.println(\"Salom, Termux!\");\n    }\n}\n```\n\n**5. Kompilyatsiya:**\n```bash\njavac Salom.java\njava Salom\n```",
        'devtools_menu': "🧰 **Developer Tools**",
        'devtools_pass': "🔐 Parol", 'devtools_hash': "🔢 Hash",
        'devtools_b64enc': "📝 Base64 Enc", 'devtools_b64dec': "📝 Base64 Dec",
        'devtools_uuid': "🆔 UUID", 'devtools_qr': "📱 QR", 'devtools_json': "📊 JSON",
        'devtools_pass_prompt': "🔐 Uzunlik (8-64):", 'devtools_hash_prompt': "🔢 Matn:",
        'devtools_b64enc_prompt': "📝 Matn:", 'devtools_b64dec_prompt': "📝 Base64:",
        'devtools_json_prompt': "📊 JSON:", 'devtools_qr_prompt': "📱 Matn/havola:",
        'devtools_invalid': "❌ {error}",
        'streak_claimed': "🔥 +{reward}! (Kun: {days})\n\n{extra}",
        'streak_already': "✅ Bugun olgansiz!",
        'streak_reset_info': "⚠️ Streak yangilandi!",
        'streak_7_bonus': "🎉 7 kun!", 'streak_30_bonus': "🎉 30 kun! Premium!",
        'updates_menu': "🆕 **Yangilanishlar tarixi:**\n\n",
        'updates_empty': "Hozircha yangilanishlar yo'q.",
        'new_video_notification': "🆕 **Yangi darslik qo'shildi!**\n\n📚 Darslik: **{num}**\n\n{extra}",
    }
}

for other_lang in ['ru', 'en', 'ar']:
    TEXTS[other_lang] = {k: v for k, v in TEXTS['uz'].items()}
    TEXTS[other_lang]['choose_lang'] = "🌐 Select language" if other_lang == 'en' else ("🌐 Выберите язык" if other_lang == 'ru' else "🌐 اختر اللغة")

TIPS = [{'uz': "**Tezroq kod:**\n`nano` o'rniga `micro` ishlating.", 'ru': "`micro`", 'en': "`micro`", 'ar': "`micro`"}]
COMMANDS_DATA = {'files': [('ls', {'uz': 'Fayllar', 'ru': 'Файлы', 'en': 'Files', 'ar': 'ملفات'})],
                 'packages': [('pkg update', {'uz': 'Yangilash', 'ru': 'Обновить', 'en': 'Update', 'ar': 'تحديث'})],
                 'network': [('ping google.com', {'uz': 'Tekshirish', 'ru': 'Проверить', 'en': 'Check', 'ar': 'فحص'})],
                 'system': [('clear', {'uz': 'Tozalash', 'ru': 'Очистить', 'en': 'Clear', 'ar': 'مسح'})]}

QUIZ_DATA = [
    {'q': {'uz': "Papka yaratish?", 'ru': "Папка?", 'en': "Make folder?", 'ar': "مجلد؟"}, 'options': ['mkdir', 'cd', 'ls', 'rm'], 'answer': 'mkdir'},
    {'q': {'uz': "Fayllar ro'yxati?", 'ru': "Список файлов?", 'en': "List files?", 'ar': "ملفات؟"}, 'options': ['ls', 'pwd', 'cat', 'touch'], 'answer': 'ls'},
    {'q': {'uz': "Termux yangilash?", 'ru': "Обновить Termux?", 'en': "Update Termux?", 'ar': "تحديث؟"}, 'options': ['pkg update', 'apt-get', 'install', 'upgrade'], 'answer': 'pkg update'},
    {'q': {'uz': "Python ishga tushirish?", 'ru': "Запуск Python?", 'en': "Run Python?", 'ar': "تشغيل؟"}, 'options': ['python file.py', 'run file.py', 'py file', 'exec file.py'], 'answer': 'python file.py'},
    {'q': {'uz': "Papkaga kirish?", 'ru': "Войти?", 'en': "Enter folder?", 'ar': "دخول؟"}, 'options': ['cd', 'mv', 'cp', 'dir'], 'answer': 'cd'},
    {'q': {'uz': "Manzilni bilish?", 'ru': "Текущий путь?", 'en': "Current dir?", 'ar': "المسار؟"}, 'options': ['pwd', 'ls', 'cd', 'path'], 'answer': 'pwd'},
    {'q': {'uz': "Faylni o'chirish?", 'ru': "Удалить файл?", 'en': "Delete file?", 'ar': "حذف؟"}, 'options': ['rm', 'del', 'drop', 'erase'], 'answer': 'rm'},
    {'q': {'uz': "Bo'sh fayl yaratish?", 'ru': "Пустой файл?", 'en': "Empty file?", 'ar': "ملف فارغ؟"}, 'options': ['touch', 'nano', 'cat', 'echo'], 'answer': 'touch'},
    {'q': {'uz': "Faylni o'qish?", 'ru': "Прочитать?", 'en': "Read?", 'ar': "قراءة؟"}, 'options': ['cat', 'ls', 'open', 'read'], 'answer': 'cat'},
    {'q': {'uz': "Python kutubxona?", 'ru': "Библиотека?", 'en': "Library?", 'ar': "مكتبة؟"}, 'options': ['pip install', 'pkg install', 'apt install', 'python install'], 'answer': 'pip install'},
    {'q': {'uz': "Matn muharriri?", 'ru': "Редактор?", 'en': "Editor?", 'ar': "محرر؟"}, 'options': ['nano', 'notepad', 'word', 'gedit'], 'answer': 'nano'},
    {'q': {'uz': "Git yuklash?", 'ru': "Git clone?", 'en': "Git clone?", 'ar': "Git؟"}, 'options': ['git clone', 'git pull', 'git fetch', 'git download'], 'answer': 'git clone'},
    {'q': {'uz': "Ping?", 'ru': "Ping?", 'en': "Ping?", 'ar': "Ping؟"}, 'options': ['ping', 'traceroute', 'netstat', 'wget'], 'answer': 'ping'},
    {'q': {'uz': "Bajarish huquqi?", 'ru': "chmod?", 'en': "chmod?", 'ar': "chmod؟"}, 'options': ['chmod +x', 'chmod 777', 'chown', 'chgrp'], 'answer': 'chmod +x'},
    {'q': {'uz': "Ekran tozalash?", 'ru': "Очистить?", 'en': "Clear?", 'ar': "مسح؟"}, 'options': ['clear', 'cls', 'reset', 'erase'], 'answer': 'clear'},
    {'q': {'uz': "CPU/RAM?", 'ru': "CPU?", 'en': "CPU?", 'ar': "CPU؟"}, 'options': ['top', 'ls', 'df', 'free'], 'answer': 'top'},
    {'q': {'uz': "Yuklab olish?", 'ru': "Скачать?", 'en': "Download?", 'ar': "تنزيل؟"}, 'options': ['wget', 'curl', 'download', 'fetch'], 'answer': 'wget'},
    {'q': {'uz': "Port skaner?", 'ru': "Порт?", 'en': "Port scan?", 'ar': "منافذ؟"}, 'options': ['nmap', 'ping', 'netstat', 'ssh'], 'answer': 'nmap'},
    {'q': {'uz': "Ekranga chiqarish?", 'ru': "Вывод?", 'en': "Print?", 'ar': "طباعة؟"}, 'options': ['print()', 'echo()', 'write()', 'log()'], 'answer': 'print()'},
    {'q': {'uz': "Python izoh?", 'ru': "Комментарий?", 'en': "Comment?", 'ar': "تعليق؟"}, 'options': ['# Izoh', '// Izoh', '/* Izoh */', '-- Izoh'], 'answer': '# Izoh'},
    {'q': {'uz': "Chiqish?", 'ru': "Выход?", 'en': "Exit?", 'ar': "خروج؟"}, 'options': ['exit', 'quit', 'close', 'stop'], 'answer': 'exit'},
    {'q': {'uz': "Nom o'zgartirish?", 'ru': "Переименовать?", 'en': "Rename?", 'ar': "إعادة تسمية؟"}, 'options': ['mv', 'cp', 'rm', 'rename'], 'answer': 'mv'},
    {'q': {'uz': "Nusxalash?", 'ru': "Копировать?", 'en': "Copy?", 'ar': "نسخ؟"}, 'options': ['cp', 'mv', 'copy', 'dup'], 'answer': 'cp'},
    {'q': {'uz': "Bo'sh joy?", 'ru': "Свободно?", 'en': "Free space?", 'ar': "مساحة؟"}, 'options': ['df', 'free', 'du', 'ls'], 'answer': 'df'},
    {'q': {'uz': "IP manzil?", 'ru': "IP?", 'en': "IP?", 'ar': "IP؟"}, 'options': ['ifconfig', 'ls', 'ping', 'cat'], 'answer': 'ifconfig'}
]

# ==========================================
# KLAVIATURALAR
# ==========================================
def get_lang_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="lang_uz"), InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")],
                                  [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"), InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar")]])

def get_devtools_keyboard(lang):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t['devtools_pass'], callback_data="dev_pass"), InlineKeyboardButton(t['devtools_hash'], callback_data="dev_hash")],
        [InlineKeyboardButton(t['devtools_b64enc'], callback_data="dev_b64enc"), InlineKeyboardButton(t['devtools_b64dec'], callback_data="dev_b64dec")],
        [InlineKeyboardButton(t['devtools_uuid'], callback_data="dev_uuid"), InlineKeyboardButton(t['devtools_qr'], callback_data="dev_qr")],
        [InlineKeyboardButton(t['devtools_json'], callback_data="dev_json")],
        [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]
    ])

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
        [InlineKeyboardButton(t['btn_profile'], callback_data="my_profile"), InlineKeyboardButton(t['streak_btn'], callback_data="daily_bonus")],
        [InlineKeyboardButton(t['btn_devtools'], callback_data="devtools_menu"), InlineKeyboardButton(t['btn_tip'], callback_data="daily_tip")],
        [InlineKeyboardButton(t['btn_updates'], callback_data="updates_menu"), InlineKeyboardButton(t['btn_change_lang'], callback_data="change_lang")],
        [InlineKeyboardButton(t['btn_support'], callback_data="support_start")]
    ]
    if user_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_theme_keyboard(lang):
    t = TEXTS[lang]
    keyboard, row = [], []
    for key, theme in THEMES_DATA.items():
        row.append(InlineKeyboardButton(theme['name'], callback_data=f"theme_apply_{key}"))
        if len(row) == 2: keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(keyboard)

def get_premium_keyboard(lang):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_buy_premium'], callback_data="buy_premium")],
                                  [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])

def get_script_categories_keyboard(lang):
    t = TEXTS[lang]
    keyboard, row = [], []
    for cat_key, cat_data in SCRIPTS_DATA.items():
        row.append(InlineKeyboardButton(cat_data['name'], callback_data=f"script_cat_{cat_key}"))
        if len(row) == 2: keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(keyboard)

def get_script_items_keyboard(cat_key, lang, selected_scripts):
    t = TEXTS[lang]
    cat_data = SCRIPTS_DATA[cat_key]
    keyboard, row = [], []
    for item_key, item_data in cat_data['items'].items():
        status = "✅ " if f"{cat_key}_{item_key}" in selected_scripts else "⬜ "
        row.append(InlineKeyboardButton(f"{status}{item_data['name']}", callback_data=f"script_toggle_{cat_key}_{item_key}"))
        if len(row) == 2: keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton(t['btn_generate_script'], callback_data="script_generate"), InlineKeyboardButton(t['btn_clear_scripts'], callback_data="script_clear")])
    keyboard.append([InlineKeyboardButton(t['btn_back_to_cats'], callback_data="script_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard(lang, af_status="off"):
    t = TEXTS[lang]
    af_text = t['admin_btn_auto_fwd_on'] if af_status == "on" else t['admin_btn_auto_fwd_off']
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t['admin_btn_stats'], callback_data="admin_stats")],
        [InlineKeyboardButton(t['admin_btn_bcast'], callback_data="admin_bcast")],
        [InlineKeyboardButton(t['admin_btn_update'], callback_data="admin_update")],
        [InlineKeyboardButton(t['admin_btn_points'], callback_data="admin_points")],
        [InlineKeyboardButton(t['admin_btn_add_file'], callback_data="admin_add_file")],
        [InlineKeyboardButton(af_text, callback_data="admin_toggle_autofwd")],
        [InlineKeyboardButton(t['admin_btn_close'], callback_data="admin_close")]
    ])

def get_sub_keyboard(lang):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_join'], url=f"https://t.me/{FORCE_SUB_CHANNEL.replace('@', '')}")],
                                  [InlineKeyboardButton(t['btn_check'], callback_data="check_sub")]])

def get_profile_keyboard(lang):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([[InlineKeyboardButton(t['streak_btn'], callback_data="daily_bonus")],
                                  [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])

def get_sec_menu(lang):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([[InlineKeyboardButton(t['sec_info'], callback_data="sec_cat_info")],
                                  [InlineKeyboardButton(t['sec_pass'], callback_data="sec_cat_pass")],
                                  [InlineKeyboardButton(t['sec_exploit'], callback_data="sec_cat_exploit")],
                                  [InlineKeyboardButton(t['sec_network'], callback_data="sec_cat_network")],
                                  [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])

def get_lessons_keyboard(page, lang, max_lesson=47):
    t = TEXTS[lang]
    keyboard = []
    start_idx = (page - 1) * 10 + 1
    end_idx = min(page * 10, max_lesson)
    row = []
    for i in range(start_idx, end_idx + 1):
        row.append(InlineKeyboardButton(f"🎬 {i}-darslik", callback_data=f"lesson_{i}"))
        if len(row) == 2: keyboard.append(row); row = []
    if row: keyboard.append(row)
    nav_row = []
    if page > 1: nav_row.append(InlineKeyboardButton(t['btn_prev'], callback_data=f"page_{page-1}"))
    if end_idx < max_lesson: nav_row.append(InlineKeyboardButton(t['btn_next'], callback_data=f"page_{page+1}"))
    if nav_row: keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(keyboard)

def get_lua_lessons_keyboard(lang):
    t = TEXTS[lang]
    keyboard, row = [], []
    for i in range(1, 9):
        row.append(InlineKeyboardButton(f"🎬 {i}-darslik", callback_data=f"lua_lesson_{i}"))
        if len(row) == 2: keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(keyboard)

def get_cheatsheet_keyboard(lang):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([[InlineKeyboardButton(t['cat_files'], callback_data="cat_files")],
                                  [InlineKeyboardButton(t['cat_packages'], callback_data="cat_packages")],
                                  [InlineKeyboardButton(t['cat_network'], callback_data="cat_network")],
                                  [InlineKeyboardButton(t['cat_system'], callback_data="cat_system")],
                                  [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])

def get_quiz_keyboard(options, lang):
    t = TEXTS[lang]
    keyboard, row = [], []
    shuffled = options.copy()
    random.shuffle(shuffled)
    for opt in shuffled:
        row.append(InlineKeyboardButton(opt, callback_data=f"quiz_ans_{opt}"))
        if len(row) == 2: keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(keyboard)

def get_files_categories_keyboard(lang, categories):
    t = TEXTS[lang]
    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(f"{cat['icon']} {cat['name']}", callback_data=f"files_cat_{cat['id']}")])
    keyboard.append([InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(keyboard)

def get_category_files_keyboard(lang, files, cat_id, is_admin=False, children=None, parent_id=None):
    t = TEXTS[lang]
    keyboard = []
    for child in (children or []):
        keyboard.append([InlineKeyboardButton(f"📂 {child['name']}", callback_data=(f"admin_open_{child['id']}" if is_admin else f"files_cat_{child['id']}"))])
    for f in files:
        lock = "🔒 " if f['is_premium'] else "📄 "
        if is_admin:
            keyboard.append([InlineKeyboardButton(f"🗑 {lock}{f['title']}", callback_data=f"admin_del_file_{f['id']}")])
        else:
            keyboard.append([InlineKeyboardButton(f"{lock}{f['title']}", callback_data=f"get_file_{f['id']}")])
    if is_admin:
        keyboard.append([InlineKeyboardButton("🗑 Papkani o'chirish", callback_data=f"admin_delcat_confirm_{cat_id}")])
        keyboard.append([InlineKeyboardButton("➕ Ichiga papka yaratish", callback_data=f"admin_new_inside_{cat_id}")])
        keyboard.append([InlineKeyboardButton("🔙 Yuqori papka" if parent_id else "🔙 Papkalar", callback_data=(f"admin_open_{parent_id}" if parent_id else "admin_add_file"))])
        keyboard.append([InlineKeyboardButton(t['admin_btn_close'], callback_data="admin_menu")])
    else:
        keyboard.append([InlineKeyboardButton(t['files_back_to_cats'], callback_data=(f"files_cat_{parent_id}" if parent_id else "files_menu"))])
        keyboard.append([InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(keyboard)

def get_admin_file_categories_keyboard(lang, categories):
    t = TEXTS[lang]
    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(f"📂 {cat['icon']} {cat['name']}", callback_data=f"admin_open_{cat['id']}"),
                         InlineKeyboardButton("➕ Fayl", callback_data=f"admin_file_cat_{cat['id']}")])
    keyboard.append([InlineKeyboardButton(t['admin_btn_new_cat'], callback_data="admin_file_new_cat")])
    if categories:
        keyboard.append([InlineKeyboardButton(t['admin_btn_del_cat'], callback_data="admin_file_delcat_menu")])
    keyboard.append([InlineKeyboardButton(t['btn_back'], callback_data="admin_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_admin_delcat_keyboard(lang, categories):
    t = TEXTS[lang]
    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(f"🗑 {cat['icon']} {cat['name']}", callback_data=f"admin_delcat_confirm_{cat['id']}")])
    keyboard.append([InlineKeyboardButton(t['btn_back'], callback_data="admin_add_file")])
    return InlineKeyboardMarkup(keyboard)

# ==========================================
# START
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.clear()
    lang = 'uz'
    t = TEXTS[lang]
    if not await is_subscribed(user_id, context):
        await update.message.reply_text(t['force_sub_text'], reply_markup=get_sub_keyboard(lang), parse_mode='Markdown')
        return
    await add_user(user_id, lang)
    await update.message.reply_text(TEXTS['uz']['choose_lang'], reply_markup=get_lang_keyboard(), parse_mode='Markdown')

# ==========================================
# CALLBACK HANDLER
# ==========================================
async def button_tap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]

    if data == "check_sub":
        if await is_subscribed(user_id, context):
            await query.answer("✅")
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

    if data.startswith("quick_cat_"):
        cat_name = data.replace("quick_cat_", "")
        cat = await get_category_by_name(cat_name)
        if not cat:
            new_id = await add_category(cat_name, icon='📁')
            cat = await get_category_by_id(new_id) if new_id else None
        if not cat:
            return await query.answer("❌ Papka topilmadi.", show_alert=True)
        files = await get_files_by_category(cat['id'])
        if not files:
            return await query.answer(f"📂 {cat['icon']} {cat['name']} hozircha bo'sh.\n\nAdmin fayl yuklashi mumkin.", show_alert=True)
        text = t['files_cat_menu'].format(cat_name=f"{cat['icon']} {cat['name']}")
        await edit_or_send(query, context, text, get_category_files_keyboard(lang, files, cat['id']))

    elif data == "files_menu":
        categories = await get_all_categories()
        if not categories:
            return await query.answer(t['files_empty'], show_alert=True)
        await edit_or_send(query, context, t['files_menu'], get_files_categories_keyboard(lang, categories))

    elif data.startswith("files_cat_"):
        cat_id = int(data.replace("files_cat_", ""))
        cat = await get_category_by_id(cat_id)
        if not cat:
            return await query.answer("❌ Papka topilmadi", show_alert=True)
        files = await get_files_by_category(cat_id)
        children = await get_child_categories(cat_id)
        if not files and not children:
            return await query.answer(t['files_cat_empty'], show_alert=True)
        text = t['files_cat_menu'].format(cat_name=f"{cat['icon']} {cat['name']}")
        await edit_or_send(query, context, text, get_category_files_keyboard(lang, files, cat_id, children=children, parent_id=cat['parent_id']))

    elif data.startswith("get_file_"):
        file_id = int(data.replace("get_file_", ""))
        file_data = await get_file_by_id(file_id)
        if not file_data: return await query.answer("❌", show_alert=True)
        if file_data['is_premium'] and user_id != ADMIN_ID:
            if not db_pool: return
            async with db_pool.acquire() as conn:
                user = await conn.fetchrow('SELECT is_premium FROM users WHERE user_id = $1', user_id)
            if not user or not user['is_premium']:
                return await query.answer(t['file_premium_locked'], show_alert=True)
        await query.answer(t['file_sending'])
        try:
            if file_data['file_type'] == 'document':
                await context.bot.send_document(chat_id=chat_id, document=file_data['file_id'], caption=f"📂 {file_data['title']}")
            elif file_data['file_type'] == 'video':
                await context.bot.send_video(chat_id=chat_id, video=file_data['file_id'], caption=f"🎬 {file_data['title']}")
            elif file_data['file_type'] == 'photo':
                await context.bot.send_photo(chat_id=chat_id, photo=file_data['file_id'], caption=f"🖼 {file_data['title']}")
            elif file_data['file_type'] == 'audio':
                await context.bot.send_audio(chat_id=chat_id, audio=file_data['file_id'], caption=f"🎵 {file_data['title']}")
            elif file_data['file_type'] == 'voice':
                await context.bot.send_voice(chat_id=chat_id, voice=file_data['file_id'], caption=f"🎙 {file_data['title']}")
            elif file_data['file_type'] == 'animation':
                await context.bot.send_animation(chat_id=chat_id, animation=file_data['file_id'], caption=f"🎞 {file_data['title']}")
        except Exception as e:
            logging.error(f"Fayl yuborishda xato: {e}")
            await context.bot.send_message(chat_id=chat_id, text="❌ Xatolik.")

    elif data == "admin_add_file":
        if user_id != ADMIN_ID: return
        context.user_data.pop('selected_category', None)
        context.user_data.pop('selected_category_name', None)
        context.user_data['current_folder_id'] = None
        context.user_data['state'] = None
        categories = await get_all_categories()
        text = t['admin_file_choose_cat'] if categories else t['admin_file_no_cats']
        await edit_or_send(query, context, text, get_admin_file_categories_keyboard(lang, categories))

    elif data.startswith("admin_file_cat_"):
        if user_id != ADMIN_ID: return
        cat_id = int(data.replace("admin_file_cat_", ""))
        cat = await get_category_by_id(cat_id)
        if not cat:
            return await query.answer("❌ Papka topilmadi", show_alert=True)
        context.user_data['selected_category'] = cat_id
        context.user_data['selected_category_name'] = f"{cat['icon']} {cat['name']}"
        context.user_data['state'] = 'in_add_file'
        text = t['admin_file_send_to'].format(cat_name=f"{cat['icon']} {cat['name']}")
        await edit_or_send(query, context, text, InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="admin_add_file")]]))

    elif data.startswith("admin_open_"):
        if user_id != ADMIN_ID: return
        cat_id = int(data.replace("admin_open_", ""))
        cat = await get_category_by_id(cat_id)
        if not cat: return await query.answer("❌ Papka topilmadi", show_alert=True)
        context.user_data['current_folder_id'] = cat_id
        files = await get_files_by_category(cat_id)
        children = await get_child_categories(cat_id)
        rows = [[InlineKeyboardButton("➕ Fayl qo'shish", callback_data=f"admin_file_cat_{cat_id}")]]
        rows += list(get_category_files_keyboard(lang, files, cat_id, is_admin=True, children=children, parent_id=cat['parent_id']).inline_keyboard)
        await edit_or_send(query, context, f"📂 **{cat['name']}**", InlineKeyboardMarkup(rows))

    elif data.startswith("admin_new_inside_"):
        if user_id != ADMIN_ID: return
        parent_id = int(data.replace("admin_new_inside_", ""))
        context.user_data['current_folder_id'] = parent_id
        context.user_data['state'] = 'in_new_cat_name'
        await edit_or_send(query, context, t['admin_file_new_cat_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data=f"admin_open_{parent_id}")]]))

    elif data == "admin_file_new_cat":
        if user_id != ADMIN_ID: return
        context.user_data['current_folder_id'] = None
        context.user_data['state'] = 'in_new_cat_name'
        await edit_or_send(query, context, t['admin_file_new_cat_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="admin_add_file")]]))

    elif data == "admin_file_delcat_menu":
        if user_id != ADMIN_ID: return
        categories = await get_all_categories()
        if not categories:
            return await query.answer("Papkalar yo'q", show_alert=True)
        await edit_or_send(query, context, t['admin_file_choose_del'], get_admin_delcat_keyboard(lang, categories))

    elif data.startswith("admin_delcat_confirm_"):
        if user_id != ADMIN_ID: return
        cat_id = int(data.replace("admin_delcat_confirm_", ""))
        cat = await get_category_by_id(cat_id)
        if not cat:
            return await query.answer("❌", show_alert=True)
        file_count = await count_files_in_category(cat_id)
        text = t['admin_cat_del_confirm'].format(cat_name=f"{cat['icon']} {cat['name']}") + f"\n\n📄 Fayllar soni: **{file_count}**"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"admin_delcat_final_{cat_id}")],
            [InlineKeyboardButton("❌ Bekor qilish", callback_data="admin_add_file")]
        ])
        await edit_or_send(query, context, text, kb)

    elif data.startswith("admin_delcat_final_"):
        if user_id != ADMIN_ID: return
        cat_id = int(data.replace("admin_delcat_final_", ""))
        await delete_category(cat_id)
        await ensure_default_categories()
        categories = await get_all_categories()
        text = t['admin_cat_deleted'] + "\n\n" + (t['admin_file_choose_cat'] if categories else t['admin_file_no_cats'])
        await edit_or_send(query, context, text, get_admin_file_categories_keyboard(lang, categories))

    elif data.startswith("admin_del_file_"):
        if user_id != ADMIN_ID: return
        file_id = int(data.replace("admin_del_file_", ""))
        file_data = await get_file_by_id(file_id)
        if not file_data:
            return await query.answer("❌ Fayl topilmadi", show_alert=True)
        cat_id = file_data['category_id']
        await delete_file_by_id(file_id)
        cat = await get_category_by_id(cat_id) if cat_id else None
        files = await get_files_by_category(cat_id) if cat_id else []
        cat_name = f"{cat['icon']} {cat['name']}" if cat else "📂 Papka"
        text = f"✅ Fayl o'chirildi!\n\n{t['files_cat_menu'].format(cat_name=cat_name)}"
        await edit_or_send(query, context, text, get_category_files_keyboard(lang, files, cat_id, is_admin=True))

    elif data == "premium_menu":
        await edit_or_send(query, context, t['premium_menu'], get_premium_keyboard(lang))

    elif data == "buy_premium":
        try:
            await context.bot.send_invoice(chat_id=chat_id, title="Premium (1 oy)", description="Cheksiz AI va Premium fayllar.",
                                            payload="premium_sub_payload", provider_token="", currency="XTR",
                                            prices=[LabeledPrice("Premium", 50)], start_parameter="premium-sub")
        except Exception as e:
            logging.error(f"To'lov xatosi: {e}")
            await query.answer("❌ To'lovda xatolik!", show_alert=True)

    elif data == "challenge_start":
        profile = await get_user_profile(user_id)
        if profile and profile['last_challenge_date'] == datetime.date.today() and user_id != ADMIN_ID:
            return await query.answer(t['challenge_already_done'], show_alert=True)
        challenge = random.choice(CHALLENGES_DATA)
        context.user_data['current_challenge'] = challenge['text']
        context.user_data['state'] = 'in_challenge'
        text = t['challenge_problem'].format(text=challenge['text'])
        await edit_or_send(query, context, text, InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]))

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
        text = t['script_items_menu'].format(cat_name=SCRIPTS_DATA[cat_key]['name'])
        await edit_or_send(query, context, text, get_script_items_keyboard(cat_key, lang, context.user_data['selected_scripts']))
    elif data.startswith("script_toggle_"):
        parts = data.replace("script_toggle_", "").split("_", 1)
        cat_key, item_key = parts[0], parts[1]
        script_id = f"{cat_key}_{item_key}"
        selected = context.user_data.get('selected_scripts', [])
        if script_id in selected: selected.remove(script_id)
        else: selected.append(script_id)
        context.user_data['selected_scripts'] = selected
        text = t['script_items_menu'].format(cat_name=SCRIPTS_DATA[cat_key]['name'])
        try: await query.edit_message_reply_markup(reply_markup=get_script_items_keyboard(cat_key, lang, selected))
        except: await edit_or_send(query, context, text, get_script_items_keyboard(cat_key, lang, selected))
    elif data == "script_clear":
        context.user_data['selected_scripts'] = []
        await query.answer("🗑")
        await edit_or_send(query, context, t['script_cat_menu'], get_script_categories_keyboard(lang))
    elif data == "script_generate":
        selected = context.user_data.get('selected_scripts', [])
        if not selected: return await query.answer(t['script_empty'], show_alert=True)
        script_content = "#!/data/data/com.termux/files/usr/bin/bash\n\necho \"🚀 O'rnatish boshlanmoqda...\"\npkg update -y && pkg upgrade -y\n"
        pkg_installs, pip_installs, custom_commands = [], [], []
        for script_id in selected:
            cat_key, item_key = script_id.split("_", 1)
            item_data = SCRIPTS_DATA[cat_key]['items'][item_key]
            if item_data['type'] == 'pkg' and item_data['pkg'] not in pkg_installs: pkg_installs.append(item_data['pkg'])
            elif item_data['type'] == 'pip' and item_data['pkg'] not in pip_installs: pip_installs.append(item_data['pkg'])
            elif item_data['type'] == 'custom': custom_commands.append(item_data['pkg'])
        if pkg_installs: script_content += f"pkg install -y {' '.join(pkg_installs)}\n"
        for cmd in custom_commands: script_content += f"{cmd}\n"
        if pip_installs:
            script_content += "pip install --upgrade pip || true\n"
            script_content += f"pip install {' '.join(pip_installs)}\n"
        script_content += "echo \"✅ TAYYOR!\"\n"
        script_file = BytesIO(script_content.encode('utf-8'))
        script_file.name = "install.sh"
        await context.bot.send_document(chat_id=chat_id, document=script_file, caption=t['script_done'], parse_mode='Markdown')
        context.user_data['selected_scripts'] = []

    elif data == "admin_stats":
        if user_id != ADMIN_ID: return
        if not db_pool: return await query.answer("Baza yo'q", show_alert=True)
        async with db_pool.acquire() as conn:
            total = await conn.fetchval('SELECT COUNT(*) FROM users')
            prem = await conn.fetchval('SELECT COUNT(*) FROM users WHERE is_premium = TRUE')
            top = await conn.fetchval('SELECT MAX(score) FROM users')
            nfiles = await conn.fetchval('SELECT COUNT(*) FROM files')
            ncats = await conn.fetchval('SELECT COUNT(*) FROM file_categories')
        text = f"📊 **Statistika**\n\n👥 Foydalanuvchilar: **{total}**\n💎 Premium: **{prem}**\n🏆 Eng yuqori: **{top}**\n📂 Papkalar: **{ncats}**\n📄 Fayllar: **{nfiles}**"
        await edit_or_send(query, context, text, InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="admin_menu")]]))
    elif data == "admin_update":
        if user_id != ADMIN_ID: return
        context.user_data['state'] = 'in_admin_update'
        await edit_or_send(query, context, t['admin_update_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="admin_menu")]]))
    elif data == "admin_toggle_autofwd":
        if user_id != ADMIN_ID: return
        current = await get_setting('auto_forward', 'off')
        new_val = 'on' if current == 'off' else 'off'
        await set_setting('auto_forward', new_val)
        msg = t['admin_toggle_on'] if new_val == 'on' else t['admin_toggle_off']
        await query.answer("✅")
        await edit_or_send(query, context, msg, InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="admin_menu")]]))
    elif data == "admin_points":
        if user_id != ADMIN_ID: return
        context.user_data['state'] = 'in_admin_points'
        await edit_or_send(query, context, t['admin_points_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="admin_menu")]]))
    elif data == "admin_bcast":
        if user_id != ADMIN_ID: return
        context.user_data['state'] = 'in_broadcast'
        await edit_or_send(query, context, t['admin_bcast_start'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="admin_menu")]]))
    elif data == "admin_menu":
        if user_id != ADMIN_ID: return
        af = await get_setting('auto_forward', 'off')
        await edit_or_send(query, context, t['admin_panel'], get_admin_keyboard(lang, af))
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
    elif data == "updates_menu":
        updates = await get_recent_updates(5)
        if not updates:
            text = t['updates_empty']
        else:
            text = t['updates_menu'] + "\n"
            for u in updates:
                date_str = u['created_at'].strftime('%d.%m.%Y')
                text += f"**{date_str}**\n{u['description']}\n\n"
        await edit_or_send(query, context, text, InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]))
    elif data == "my_profile":
        profile = await get_user_profile(user_id)
        if not profile: return await query.answer("Xatolik")
        level = get_level(profile['score'])
        status = "💎 Premium" if profile['is_premium'] else "🆓 Bepul"
        text = t['profile_text'].format(score=profile['score'], level=level, rank=profile['rank'], status=status)
        text += f"\n🔥 **Streak:** {profile.get('streak_days', 0)} kun"
        await edit_or_send(query, context, text, get_profile_keyboard(lang))
    elif data == "daily_bonus":
        success, streak_days, reward, is_reset, is_already = await claim_streak(user_id)
        if is_already: return await query.answer(t['streak_already'], show_alert=True)
        if not success: return await query.answer("❌", show_alert=True)
        extra = ""
        if streak_days == 7: extra = t['streak_7_bonus']
        elif streak_days == 30: extra = t['streak_30_bonus']
        elif is_reset: extra = t['streak_reset_info']
        await query.answer(f"🔥 +{reward} (Kun: {streak_days})", show_alert=True)
        profile = await get_user_profile(user_id)
        level = get_level(profile['score'])
        status = "💎 Premium" if profile['is_premium'] else "🆓 Bepul"
        text = t['profile_text'].format(score=profile['score'], level=level, rank=profile['rank'], status=status)
        text += f"\n🔥 **Streak:** {streak_days} kun\n🎁 +{reward} ball"
        if extra: text += f"\n\n{extra}"
        await edit_or_send(query, context, text, get_profile_keyboard(lang))
    elif data == "top_users":
        top_users = await get_top_users()
        top_list = ""
        for i, u in enumerate(top_users):
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "🔹"
            top_list += f"{medal} {i+1}. ID: `{u['user_id']}` — **{u['score']}**\n"
        if not top_list: top_list = "..."
        await edit_or_send(query, context, t['top_text'].format(list=top_list), InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]))

    elif data == "quiz_start":
        if 'seen_questions' not in context.user_data: context.user_data['seen_questions'] = []
        if len(context.user_data['seen_questions']) >= len(QUIZ_DATA):
            context.user_data['seen_questions'] = []
            await query.message.reply_text(t['quiz_end'])
        available = [i for i in range(len(QUIZ_DATA)) if i not in context.user_data['seen_questions']]
        chosen = random.choice(available)
        context.user_data['seen_questions'].append(chosen)
        context.user_data['current_quiz'] = QUIZ_DATA[chosen]
        q = QUIZ_DATA[chosen]
        text = t['quiz_start'] + f"\n\n❓ **{q['q'][lang]}**"
        await edit_or_send(query, context, text, get_quiz_keyboard(q['options'], lang))

    elif data.startswith("quiz_ans_"):
        selected_ans = data.replace("quiz_ans_", "")
        q = context.user_data.get('current_quiz')
        if not q: return await query.answer("❌")
        context.user_data['current_quiz'] = None
        if selected_ans == q['answer']:
            text = t['quiz_correct']
            await add_score(user_id, 10)
        else:
            text = t['quiz_wrong'].format(answer=q['answer'])
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_next_quiz'], callback_data="quiz_start")], [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])
        await edit_or_send(query, context, text, kb)

    elif data == "ai_start":
        can_use, limit_left = await check_ai_limit(user_id)
        if not can_use:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_go_premium'], callback_data="premium_menu")], [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])
            return await edit_or_send(query, context, t['ai_limit_reached'], kb)
        context.user_data['state'] = 'in_ai'
        pt = t['ai_prompt']
        if limit_left < 999: pt += "\n\n" + t['ai_limit_info'].format(limit=limit_left)
        await edit_or_send(query, context, pt, InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]))

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
                        apk = await response.read()
                        if len(apk) > 50 * 1024 * 1024:
                            await msg.edit_text(t['apk_too_big'])
                        else:
                            f = BytesIO(apk)
                            f.name = t['apk_file_name']
                            await context.bot.send_document(chat_id=chat_id, document=f, caption=t['apk_caption'], parse_mode='Markdown',
                                                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]))
                            await msg.delete()
                    else: raise Exception()
        except Exception:
            await msg.edit_text(t['apk_error'])

    elif data == "daily_tip":
        await edit_or_send(query, context, t['tip_header'] + random.choice(TIPS)[lang], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]))
    elif data == "cheatsheet":
        await edit_or_send(query, context, t['cheatsheet_menu'], get_cheatsheet_keyboard(lang))
    elif data.startswith("cat_"):
        cat = data.split("_")[1]
        cmds = COMMANDS_DATA.get(cat, [])
        text = f"**{t['cat_'+cat]}**\n\n"
        for cmd, desc in cmds: text += f"• `{cmd}` - {desc[lang]}\n"
        await edit_or_send(query, context, text, InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back_cheat'], callback_data="cheatsheet")], [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]))

    elif data.startswith("page_"):
        page = int(data.split("_")[1])
        max_l = await get_max_lesson_number()
        total_pages = (max_l + 9) // 10
        text = t['text_page'].format(page=page, total=total_pages)
        await edit_or_send(query, context, text, get_lessons_keyboard(page, lang, max_l))

    elif data.startswith("lesson_"):
        lesson_num = int(data.split("_")[1])
        all_lessons = await get_all_lessons()
        message_id = all_lessons.get(lesson_num, lesson_num + 2)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_lessons_menu'], callback_data="page_1")]])
        try:
            await context.bot.copy_message(chat_id=chat_id, from_chat_id=VIDEO_CHANNEL, message_id=message_id, reply_markup=kb)
            await query.message.delete()
        except TelegramError as e:
            logging.error(f"Video xato (ID:{message_id}): {e}")
            await context.bot.send_message(chat_id=chat_id, text=t['text_error_vid'], parse_mode='Markdown')

    elif data == "lua_page_1":
        await edit_or_send(query, context, t['text_lua'], get_lua_lessons_keyboard(lang))
    elif data.startswith("lua_lesson_"):
        lesson_num = int(data.split("_")[2])
        message_id = LUA_LESSONS.get(lesson_num, 93)
        buttons = []
        if lesson_num == 8: buttons.append([InlineKeyboardButton(t['btn_python'], callback_data="python_extra")])
        buttons.append([InlineKeyboardButton(t['btn_lessons_menu'], callback_data="lua_page_1")])
        try:
            await context.bot.copy_message(chat_id=chat_id, from_chat_id=VIDEO_CHANNEL, message_id=message_id, reply_markup=InlineKeyboardMarkup(buttons))
            await query.message.delete()
        except TelegramError as e:
            logging.error(f"Lua xato: {e}")
            await context.bot.send_message(chat_id=chat_id, text=t['text_error_vid'], parse_mode='Markdown')
    elif data == "python_extra":
        try:
            for v in PYTHON_EXTRA_VIDEOS:
                await context.bot.copy_message(chat_id=chat_id, from_chat_id=VIDEO_CHANNEL, message_id=v)
            await context.bot.send_message(chat_id=chat_id, text=t['text_python_done'],
                                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="lua_page_1")]]))
        except TelegramError as e:
            logging.error(f"Python xato: {e}")
            await context.bot.send_message(chat_id=chat_id, text=t['text_error_vid'], parse_mode='Markdown')
    elif data == "back_to_start":
        context.user_data['state'] = None
        await edit_or_send(query, context, t['welcome'], get_main_menu(lang, user_id))

    elif data == "devtools_menu":
        await edit_or_send(query, context, t['devtools_menu'], get_devtools_keyboard(lang))
    elif data == "dev_pass":
        context.user_data['state'] = 'in_dev_pass'
        await edit_or_send(query, context, t['devtools_pass_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="devtools_menu")]]))
    elif data == "dev_hash":
        context.user_data['state'] = 'in_dev_hash'
        await edit_or_send(query, context, t['devtools_hash_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="devtools_menu")]]))
    elif data == "dev_b64enc":
        context.user_data['state'] = 'in_dev_b64enc'
        await edit_or_send(query, context, t['devtools_b64enc_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="devtools_menu")]]))
    elif data == "dev_b64dec":
        context.user_data['state'] = 'in_dev_b64dec'
        await edit_or_send(query, context, t['devtools_b64dec_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="devtools_menu")]]))
    elif data == "dev_uuid":
        new_uuid = str(uuid.uuid4())
        text = f"🆔 **UUID v4:**\n\n`{new_uuid}`"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄", callback_data="dev_uuid")], [InlineKeyboardButton(t['btn_back'], callback_data="devtools_menu")]])
        await edit_or_send(query, context, text, kb)
    elif data == "dev_qr":
        context.user_data['state'] = 'in_dev_qr'
        await edit_or_send(query, context, t['devtools_qr_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="devtools_menu")]]))
    elif data == "dev_json":
        context.user_data['state'] = 'in_dev_json'
        await edit_or_send(query, context, t['devtools_json_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="devtools_menu")]]))

    elif data.startswith("get_attach_"):
        lesson_num = int(data.replace("get_attach_", ""))
        if not db_pool: return await query.answer("❌", show_alert=True)
        async with db_pool.acquire() as conn:
            attach = await conn.fetchrow('SELECT * FROM video_attachments WHERE lesson_number = $1', lesson_num)
        if not attach: return await query.answer("❌ Fayl topilmadi", show_alert=True)
        try:
            await query.answer("⏳")
            if attach['file_type'] == 'document':
                await context.bot.send_document(chat_id=user_id, document=attach['file_id'], caption=f"📥 {attach['file_name']}")
            elif attach['file_type'] == 'video':
                await context.bot.send_video(chat_id=user_id, video=attach['file_id'], caption=f"🎥 {attach['file_name']}")
            elif attach['file_type'] == 'photo':
                await context.bot.send_photo(chat_id=user_id, photo=attach['file_id'], caption=f"🖼 {attach['file_name']}")
            elif attach['file_type'] == 'audio':
                await context.bot.send_audio(chat_id=user_id, audio=attach['file_id'], caption=f"🎵 {attach['file_name']}")
        except Exception as e:
            logging.error(f"Fayl yuborishda xato: {e}")
            await query.answer("❌ /start bering", show_alert=True)

# ==========================================
# TO'LOV
# ==========================================
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.pre_checkout_query
    await q.answer(ok=(q.invoice_payload == "premium_sub_payload"), error_message="Xatolik")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]
    p = update.message.successful_payment
    if p.invoice_payload == "premium_sub_payload":
        await make_premium(user_id)
        await update.message.reply_text(t['premium_success'], parse_mode='Markdown', reply_markup=get_main_menu(lang, user_id))

# ==========================================
# AI
# ==========================================
async def handle_ai_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]
    if not await is_subscribed(user_id, context):
        await update.message.reply_text(t['force_sub_text'], reply_markup=get_sub_keyboard(lang), parse_mode='Markdown')
        return
    if not any([openrouter_client, mistral_client, groq_client, gemini_client]):
        await update.message.reply_text("❌ AI sozlanmagan.")
        return
    msg = await update.message.reply_text(t['ai_wait'])
    try:
        user_query, image_bytes, is_image = "", None, False
        if update.message.text:
            user_query = update.message.text
            if len(user_query) < 15 and user_query.lower() in ['salom', 'assalom', 'hi', 'hello']:
                await msg.edit_text(t['ai_not_coding']); return
            if len(user_query) > 80000: await msg.edit_text(t['ai_text_too_long']); return
        elif update.message.photo:
            f = await update.message.photo[-1].get_file()
            image_bytes = await f.download_as_bytearray()
            is_image = True
            user_query = "Fix this code error from image."
        elif update.message.document:
            doc = update.message.document
            if doc.file_size > 500 * 1024: await msg.edit_text(t['ai_file_too_large']); return
            if doc.file_name.endswith(('.py', '.lua', '.txt', '.js', '.cpp', '.c', '.html', '.java')):
                content = await (await doc.get_file()).download_as_bytearray()
                try:
                    text_content = content.decode('utf-8')
                    if len(text_content) > 80000: await msg.edit_text(t['ai_text_too_long']); return
                    user_query = f"File: {doc.file_name}\n\n{text_content}\n\nFix this code."
                except UnicodeDecodeError: await msg.edit_text(t['ai_unsupported_file']); return
            else: await msg.edit_text(t['ai_unsupported_file']); return
        else: await msg.edit_text(t['ai_video_error']); return

        ai_reply = ""
        sys_prompt = "You are an expert Software Engineer. Write/fix code. Reply in markdown code blocks. Reply in user's language."

        if is_image and gemini_client:
            try:
                r = await gemini_client.aio.models.generate_content(model='gemini-1.5-flash',
                    contents=[types.Part.from_text(text=sys_prompt), types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg')])
                ai_reply = r.text
            except Exception as e: logging.error(f"Gemini V: {e}")

        if not ai_reply and openrouter_client and not is_image:
            try:
                r = await openrouter_client.chat.completions.create(model="qwen/qwen-2.5-coder-32b-instruct:free",
                    messages=[{"role":"system","content":sys_prompt},{"role":"user","content":user_query}], max_tokens=4000)
                ai_reply = r.choices[0].message.content
            except Exception as e: logging.error(f"OR: {e}")

        if not ai_reply and mistral_client and not is_image:
            try:
                r = await mistral_client.chat.completions.create(model="codestral-latest",
                    messages=[{"role":"system","content":sys_prompt},{"role":"user","content":user_query}], max_tokens=4000)
                ai_reply = r.choices[0].message.content
            except Exception as e: logging.error(f"Mistral: {e}")

        if not ai_reply and groq_client and not is_image:
            try:
                r = await groq_client.chat.completions.create(model="llama-3.3-70b-versatile",
                    messages=[{"role":"system","content":sys_prompt},{"role":"user","content":user_query}], max_tokens=4000)
                ai_reply = r.choices[0].message.content
            except Exception as e: logging.error(f"Groq: {e}")

        if not ai_reply and gemini_client and not is_image:
            try:
                r = await gemini_client.aio.models.generate_content(model='gemini-1.5-flash', contents=user_query)
                ai_reply = r.text
            except Exception as e: logging.error(f"Gemini: {e}")

        if not ai_reply:
            await msg.edit_text(t['ai_error'].format(error="AI limit")); return

        code_match = re.search(r'```(?:python|py|lua|javascript|js|cpp|c|java)?\s*(.*?)```', ai_reply, re.DOTALL | re.IGNORECASE)
        if code_match:
            code_text = code_match.group(1).strip()
            if "lua" in user_query.lower(): fn = "code.lua"; ln = "Lua"
            elif "java" in user_query.lower(): fn = "Main.java"; ln = "Java"
            else: fn = "code.py"; ln = "Python"
            cf = BytesIO(code_text.encode('utf-8')); cf.name = fn
            await context.bot.send_document(chat_id=update.message.chat_id, document=cf, caption=f"🤖 {ln}: {fn}")
            expl = ai_reply.replace(code_match.group(0), "").strip()
            if expl: await context.bot.send_message(chat_id=update.message.chat_id, text=f"📝 {expl}")
            await msg.delete()
        else:
            await msg.edit_text(t['ai_no_code'].format(text=ai_reply))
    except Exception as e:
        await msg.edit_text(t['ai_error'].format(error=str(e)[:100]))

# ==========================================
# CHALLENGE
# ==========================================
async def handle_challenge_solution(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]
    ct = context.user_data.get('current_challenge')
    uc = update.message.text or ((await update.message.document.get_file()).file_id if update.message.document else None)
    if not uc: return await update.message.reply_text(t['challenge_no_code'])
    msg = await update.message.reply_text(t['challenge_wait'])
    prompt = f"Task: {ct}\n\nCode:\n{uc}\n\nReply ONLY 'CORRECT' if right, or 'INCORRECT: reason' if wrong."
    ai = ""
    try:
        if openrouter_client:
            r = await openrouter_client.chat.completions.create(model="qwen/qwen-2.5-coder-32b-instruct:free",
                messages=[{"role":"user","content":prompt}], max_tokens=200)
            ai = r.choices[0].message.content.strip()
        elif groq_client:
            r = await groq_client.chat.completions.create(model="llama-3.3-70b-versatile",
                messages=[{"role":"user","content":prompt}], max_tokens=200)
            ai = r.choices[0].message.content.strip()
    except Exception as e: logging.error(f"Ch: {e}")
    if "CORRECT" in ai.upper():
        await add_score(user_id, 30); await update_challenge_date(user_id)
        context.user_data['state'] = None; context.user_data['current_challenge'] = None
        await msg.edit_text(t['challenge_correct'], parse_mode='Markdown')
    else:
        fb = ai.replace("INCORRECT:", "").strip()
        await msg.edit_text(t['challenge_wrong'].format(feedback=fb), parse_mode='Markdown')

# ==========================================
# CHANNEL POST HANDLER
# ==========================================
async def handle_new_channel_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if not message or not message.video: return
    if message.chat.username != VIDEO_CHANNEL.replace('@', ''): return
    enabled = await get_setting('auto_forward', 'off')
    if enabled != 'on': return
    msg_id = message.message_id
    old = PENDING_VIDEOS.get(msg_id)
    if old and old.get('timer_task'):
        old['timer_task'].cancel()
    PENDING_VIDEOS[msg_id] = {'chat_id': message.chat_id, 'file_id': None, 'file_type': None,
                               'file_name': None, 'button_text': None, 'caption': message.caption or ""}
    try:
        await context.bot.send_message(chat_id=ADMIN_ID,
            text=(f"🎬 **Yangi video!** (ID: `{msg_id}`)\n\n"
                  f"📎 **10 daqiqa ichida fayl yuboring** → video ostiga tugma qo'shiladi.\n\n"
                  f"⏱️ **/done** — darhol tarqatish\n"
                  f"❌ **/cancel_pending** — bekor qilish"),
            parse_mode='Markdown')
    except Exception as e: logging.error(f"Admin msg: {e}")
    task = asyncio.create_task(_auto_finalize_after_timeout(context, msg_id))
    PENDING_VIDEOS[msg_id]['timer_task'] = task

async def _auto_finalize_after_timeout(context, msg_id):
    try:
        await asyncio.sleep(AUTO_ADD_TIMEOUT)
        if msg_id in PENDING_VIDEOS:
            await finalize_video_broadcast(context, msg_id, reason="timeout")
    except asyncio.CancelledError: pass

async def finalize_video_broadcast(context, msg_id, reason="manual"):
    data = PENDING_VIDEOS.pop(msg_id, None)
    if not data: return
    if data.get('timer_task'):
        try: data['timer_task'].cancel()
        except Exception: pass
    if not db_pool: return
    async with db_pool.acquire() as conn:
        max_num = await conn.fetchval('SELECT MAX(lesson_number) FROM auto_lessons')
        next_num = (max_num + 1) if max_num else 48
        await conn.execute('INSERT INTO auto_lessons (lesson_number, message_id) VALUES ($1, $2) ON CONFLICT (lesson_number) DO NOTHING', next_num, msg_id)
        if data['file_id']:
            btn_text = data.get('button_text') or get_file_button_info(data['file_name'], data['file_type'])
            await conn.execute('''INSERT INTO video_attachments (lesson_number, file_id, file_type, file_name, button_text)
                VALUES ($1, $2, $3, $4, $5) ON CONFLICT (lesson_number) DO UPDATE SET
                file_id = EXCLUDED.file_id, file_type = EXCLUDED.file_type,
                file_name = EXCLUDED.file_name, button_text = EXCLUDED.button_text''',
                next_num, data['file_id'], data['file_type'], data['file_name'], btn_text)
        users = await conn.fetch('SELECT user_id FROM users')
    reply_markup = None
    if data['file_id']:
        btn_text = data.get('button_text') or get_file_button_info(data['file_name'], data['file_type'])
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(btn_text, callback_data=f"get_attach_{next_num}")]])
        try:
            await context.bot.edit_message_reply_markup(chat_id=data['chat_id'], message_id=msg_id, reply_markup=reply_markup)
        except Exception as e: logging.error(f"Edit post: {e}")
    success, fail = 0, 0
    for u in users:
        if u['user_id'] == ADMIN_ID: continue
        try:
            await context.bot.copy_message(chat_id=u['user_id'], from_chat_id=data['chat_id'], message_id=msg_id, reply_markup=reply_markup)
            success += 1; await asyncio.sleep(0.05)
        except Exception: fail += 1
    file_info = f"📎 `{data['file_name']}`" if data['file_id'] else "📎 Fayl yo'q"
    reason_text = "⏱️ 10 daqiqa o'tdi" if reason == "timeout" else "✅ /done"
    try:
        await context.bot.send_message(chat_id=ADMIN_ID,
            text=f"✅ **{next_num}-darslik tarqatildi!**\n\n📌 {reason_text}\n{file_info}\n\n📩 {success}\n❌ {fail}",
            parse_mode='Markdown')
    except Exception: pass

# ==========================================
# COMMANDS
# ==========================================
async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not PENDING_VIDEOS:
        await update.message.reply_text("ℹ️ Pending video yo'q.")
        return
    count = len(PENDING_VIDEOS)
    for msg_id in list(PENDING_VIDEOS.keys()):
        await finalize_video_broadcast(context, msg_id, reason="manual")
    await update.message.reply_text(f"✅ **{count} ta tarqatildi!**", parse_mode='Markdown')

async def cancel_pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not PENDING_VIDEOS:
        await update.message.reply_text("ℹ️ Pending yo'q.")
        return
    count = len(PENDING_VIDEOS)
    for msg_id, data in list(PENDING_VIDEOS.items()):
        if data.get('timer_task'):
            try: data['timer_task'].cancel()
            except Exception: pass
    PENDING_VIDEOS.clear()
    await update.message.reply_text(f"❌ **{count} ta bekor.**", parse_mode='Markdown')

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    lang = context.user_data.get('lang', 'uz')
    af = await get_setting('auto_forward', 'off')
    await update.message.reply_text(TEXTS[lang]['admin_panel'], reply_markup=get_admin_keyboard(lang, af), parse_mode='Markdown')

# ==========================================
# MESSAGE HANDLER
# ==========================================
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]

    if user.id == ADMIN_ID and PENDING_VIDEOS:
        if update.message.document or update.message.video or update.message.photo or update.message.audio:
            last_msg_id = list(PENDING_VIDEOS.keys())[-1]
            fid, ft, fn = None, None, None
            if update.message.document:
                fid = update.message.document.file_id
                ft = 'document'
                fn = update.message.document.file_name or "file"
            elif update.message.video:
                fid = update.message.video.file_id; ft = 'video'
                fn = update.message.video.file_name or "video.mp4"
            elif update.message.photo:
                fid = update.message.photo[-1].file_id; ft = 'photo'; fn = "photo.jpg"
            elif update.message.audio:
                fid = update.message.audio.file_id; ft = 'audio'
                fn = update.message.audio.file_name or "audio.mp3"
            if fid:
                PENDING_VIDEOS[last_msg_id]['file_id'] = fid
                PENDING_VIDEOS[last_msg_id]['file_type'] = ft
                PENDING_VIDEOS[last_msg_id]['file_name'] = fn
                if update.message.caption:
                    PENDING_VIDEOS[last_msg_id]['button_text'] = update.message.caption.strip()[:80]
                btn = PENDING_VIDEOS[last_msg_id]['button_text'] or get_file_button_info(fn, ft)
                await update.message.reply_text(
                    f"✅ **Biriktirildi!**\n\n📎 `{fn}`\n🔘 **{btn}**\n\n"
                    f"**/done** yoki 10 daqiqa kuting.",
                    parse_mode='Markdown')
                return

    if user.id == ADMIN_ID and context.user_data.get('state') == 'in_new_cat_name':
        if update.message.text == "/cancel":
            context.user_data['state'] = None
            await update.message.reply_text(t['admin_file_cancel']); return
        if update.message.text:
            cat_name = update.message.text.strip()[:100]
            new_id = await add_category(cat_name, icon='📁', parent_id=context.user_data.get('current_folder_id'))
            if new_id:
                context.user_data['selected_category'] = new_id
                context.user_data['selected_category_name'] = f"📁 {cat_name}"
                context.user_data['state'] = 'in_add_file'
                text = t['admin_file_cat_created'].format(name=cat_name) + "\n\n" + t['admin_file_send_to'].format(cat_name=f"📁 {cat_name}")
                await update.message.reply_text(text, parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="admin_add_file")]]))
            else:
                await update.message.reply_text("❌ Xatolik.")
                context.user_data['state'] = None
        return

    if user.id == ADMIN_ID and context.user_data.get('state') == 'in_add_file':
        if update.message.text == "/cancel":
            context.user_data['state'] = None
            context.user_data.pop('selected_category', None)
            await update.message.reply_text(t['admin_file_cancel']); return
        if update.message.document or update.message.video or update.message.photo or update.message.audio or update.message.voice or update.message.animation:
            if update.message.document: file_id = update.message.document.file_id; ftype = 'document'
            elif update.message.video: file_id = update.message.video.file_id; ftype = 'video'
            elif update.message.photo: file_id = update.message.photo[-1].file_id; ftype = 'photo'
            elif update.message.audio: file_id = update.message.audio.file_id; ftype = 'audio'
            elif update.message.voice: file_id = update.message.voice.file_id; ftype = 'voice'
            else: file_id = update.message.animation.file_id; ftype = 'animation'
            context.user_data['temp_file_id'] = file_id
            context.user_data['temp_file_type'] = ftype
            context.user_data['state'] = 'in_file_title'
            cat_name = context.user_data.get('selected_category_name', '📁 Papka')
            await update.message.reply_text(f"📎 Fayl qabul qilindi!\n\n{cat_name}\n\n" + t['admin_file_title_prompt'], parse_mode='Markdown')
        else:
            await update.message.reply_text("⚠️ Fayl yuboring yoki /cancel bosing.")
        return

    if user.id == ADMIN_ID and context.user_data.get('state') == 'in_file_title':
        if update.message.text == "/cancel":
            context.user_data['state'] = None
            context.user_data.pop('selected_category', None)
            await update.message.reply_text(t['admin_file_cancel']); return
        if update.message.text:
            title = update.message.text.strip()[:255]
            file_id = context.user_data.get('temp_file_id')
            ftype = context.user_data.get('temp_file_type')
            cat_id = context.user_data.get('selected_category')
            cat_name = context.user_data.get('selected_category_name', 'Papka')
            if not file_id or not cat_id:
                await update.message.reply_text("❌ Fayl yoki papka topilmadi. Qaytadan urinib ko'ring.")
                context.user_data['state'] = None
                return
            await add_file_db_cat(title, file_id, ftype, cat_id, is_premium=False)
            context.user_data['state'] = None
            for k in ['selected_category', 'selected_category_name', 'temp_file_id', 'temp_file_type']:
                context.user_data.pop(k, None)
            cat = await get_category_by_id(cat_id)
            files = await get_files_by_category(cat_id)
            text = f"✅ **Fayl saqlandi!**\n\n📂 {cat_name}\n📄 {title}\n\nPapkadagi barcha fayllar:"
            await update.message.reply_text(text, parse_mode='Markdown',
                reply_markup=get_category_files_keyboard(lang, files, cat_id, is_admin=True))
        return

    if context.user_data.get('state') == 'in_dev_pass':
        context.user_data['state'] = None
        if not update.message.text or not update.message.text.strip().isdigit():
            return await update.message.reply_text(t['devtools_invalid'].format(error="Raqam."), parse_mode='Markdown')
        length = int(update.message.text.strip())
        if length < 8 or length > 64:
            return await update.message.reply_text(t['devtools_invalid'].format(error="8-64."), parse_mode='Markdown')
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        pwd = ''.join(secrets.choice(alphabet) for _ in range(length))
        strength = "🟢" if length >= 16 else "🟡" if length >= 12 else "🔴"
        text = f"🔐 `{pwd}`\n\n{strength} {length}"
        return await update.message.reply_text(text, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄", callback_data="dev_pass")], [InlineKeyboardButton(t['btn_back'], callback_data="devtools_menu")]]))

    if context.user_data.get('state') == 'in_dev_hash':
        context.user_data['state'] = None
        if not update.message.text: return
        txt = update.message.text
        r = f"**MD5:** `{hashlib.md5(txt.encode()).hexdigest()}`\n**SHA1:** `{hashlib.sha1(txt.encode()).hexdigest()}`\n**SHA256:** `{hashlib.sha256(txt.encode()).hexdigest()}`\n**SHA512:** `{hashlib.sha512(txt.encode()).hexdigest()}`"
        return await update.message.reply_text(r, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="devtools_menu")]]))

    if context.user_data.get('state') == 'in_dev_b64enc':
        context.user_data['state'] = None
        if not update.message.text: return
        e = base64.b64encode(update.message.text.encode()).decode()
        return await update.message.reply_text(f"📝 `{e}`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="devtools_menu")]]))

    if context.user_data.get('state') == 'in_dev_b64dec':
        context.user_data['state'] = None
        if not update.message.text: return
        try:
            d = base64.b64decode(update.message.text.encode()).decode()
            await update.message.reply_text(f"📝 `{d}`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="devtools_menu")]]))
        except Exception:
            await update.message.reply_text(t['devtools_invalid'].format(error="Base64"), parse_mode='Markdown')
        return

    if context.user_data.get('state') == 'in_dev_qr':
        context.user_data['state'] = None
        if not update.message.text: return
        u = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={quote(update.message.text)}"
        try:
            await update.message.reply_photo(photo=u, caption=f"📱 `{update.message.text[:100]}`", parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="devtools_menu")]]))
        except Exception as e: await update.message.reply_text(str(e)[:50])
        return

    if context.user_data.get('state') == 'in_dev_json':
        context.user_data['state'] = None
        if not update.message.text: return
        try:
            p = json_lib.loads(update.message.text)
            f = json_lib.dumps(p, indent=2, ensure_ascii=False)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="devtools_menu")]])
            if len(f) > 3500:
                jf = BytesIO(f.encode('utf-8')); jf.name = "formatted.json"
                await update.message.reply_document(document=jf, caption="📊", reply_markup=kb)
            else:
                await update.message.reply_text(f"📊 `{f}`", parse_mode='Markdown', reply_markup=kb)
        except json_lib.JSONDecodeError as e:
            await update.message.reply_text(str(e)[:80], parse_mode='Markdown')
        return

    if context.user_data.get('state') == 'in_ai':
        await handle_ai_message(update, context); return

    if context.user_data.get('state') == 'in_challenge':
        await handle_challenge_solution(update, context); return

    if user.id == ADMIN_ID and context.user_data.get('state') == 'in_admin_points':
        if update.message.text.isdigit():
            points = int(update.message.text)
            await add_score_all(points)
            msg = await update.message.reply_text(t['admin_points_wait'])
            success, fail = 0, 0
            if db_pool:
                async with db_pool.acquire() as conn:
                    users = await conn.fetch('SELECT user_id FROM users')
                bcast = f"🎁 **Aksiya!** +{points} ball! 🎉"
                for u in users:
                    if u['user_id'] == ADMIN_ID: continue
                    try:
                        await context.bot.send_message(chat_id=u['user_id'], text=bcast, parse_mode='Markdown')
                        success += 1; await asyncio.sleep(0.05)
                    except Exception: fail += 1
            await msg.edit_text(t['admin_points_done'].format(points=points, success=success, fail=fail), parse_mode='Markdown')
            context.user_data['state'] = None
        else:
            await update.message.reply_text("❌ Raqam!")
        return

    if user.id == ADMIN_ID and context.user_data.get('state') == 'in_admin_update':
        if update.message.text == "/cancel":
            context.user_data['state'] = None
            await update.message.reply_text(t['admin_bcast_cancel']); return
        if update.message.text:
            announcement = update.message.text
            await add_update_db("Yangilanish", announcement)
            msg = await update.message.reply_text(t['admin_update_wait'])
            success, fail = 0, 0
            if db_pool:
                async with db_pool.acquire() as conn:
                    users = await conn.fetch('SELECT user_id FROM users')
                bcast = f"📣 **YANGILANISH!**\n\n{announcement}"
                for u in users:
                    if u['user_id'] == ADMIN_ID: continue
                    try:
                        await context.bot.send_message(chat_id=u['user_id'], text=bcast, parse_mode='Markdown')
                        success += 1; await asyncio.sleep(0.05)
                    except Exception: fail += 1
            await msg.edit_text(t['admin_update_done'].format(success=success, fail=fail), parse_mode='Markdown')
            context.user_data['state'] = None
        return

    if user.id == ADMIN_ID and context.user_data.get('state') == 'in_broadcast':
        if update.message.text == "/cancel":
            context.user_data['state'] = None
            await update.message.reply_text(t['admin_bcast_cancel']); return
        await process_broadcast(update, context); return

    if context.user_data.get('state') == 'in_support':
        if update.message.text:
            am = f"📩 Murojaat!\n\n👤 {user.first_name} (@{user.username})\n🆔 {user.id}\n\n💬 {update.message.text}"
            try:
                await context.bot.send_message(chat_id=ADMIN_ID, text=am)
                await update.message.reply_text(t['support_sent'], reply_markup=get_main_menu(lang, user.id))
            except Exception: pass
            context.user_data['state'] = None
        return

    if user.id == ADMIN_ID and update.message.reply_to_message:
        original = update.message.reply_to_message.text or ""
        m = re.search(r'🆔 (\d+)', original)
        if m:
            target = int(m.group(1))
            try:
                await context.bot.send_message(chat_id=target, text=f"{t['support_reply']}{update.message.text}")
                await update.message.reply_text("✅")
            except Exception as e: await update.message.reply_text(f"❌ {e}")

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
    await msg.edit_text(f"✅ {success} | ❌ {fail}")

# ==========================================
# WEB SERVER (TO'LIQ TUZATILGAN)
# ==========================================
application = Application.builder().token(TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("admin", admin_panel))
application.add_handler(CommandHandler("done", done_command))
application.add_handler(CommandHandler("cancel_pending", cancel_pending_command))
application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
application.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, handle_new_channel_video))
application.add_handler(CallbackQueryHandler(button_tap))
application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_messages))

app = FastAPI()

INDEX_HTML = """<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="UTF-8">
<title>Termux Bot</title>
<style>
body{margin:0;font-family:system-ui,-apple-system,sans-serif;background:#0d1117;color:#c9d1d9;display:flex;align-items:center;justify-content:center;min-height:100vh;}
.card{max-width:520px;padding:48px 32px;text-align:center;}
h1{font-size:2.6em;margin:0 0 16px;background:linear-gradient(135deg,#58a6ff,#bc8cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
p{color:#8b949e;line-height:1.7;margin:16px 0;}
.status{display:inline-flex;align-items:center;gap:8px;background:#161b22;border:1px solid #30363d;padding:8px 20px;border-radius:20px;margin-top:24px;font-size:.9em;}
.dot{width:8px;height:8px;background:#3fb950;border-radius:50%;animation:pulse 2s infinite;}
@keyframes pulse{0%,100%{opacity:1;}50%{opacity:.4;}}
a{color:#58a6ff;text-decoration:none;}
</style>
</head>
<body>
<div class="card">
<h1>🤖 Termux Bot</h1>
<p>Termux va Dasturlash bo'yicha yordamchi bot.<br>Python, LUA, AI va boshqa ko'p narsalar.</p>
<div class="status"><span class="dot"></span> Bot faol ishlamoqda</div>
</div>
</body>
</html>"""

@app.on_event("startup")
async def on_startup():
    await init_db()
    await application.initialize()
    if RENDER_EXTERNAL_URL:
        webhook_url = f"{RENDER_EXTERNAL_URL}/webhook/{TOKEN}"
        await application.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
        print(f"✅ Bot ishga tushdi! Webhook: {webhook_url}")
    else:
        print("⚠️ RENDER_EXTERNAL_URL yo'q — webhook o'rnatilmadi")

@app.on_event("shutdown")
async def on_shutdown():
    await application.shutdown()
    if db_pool: await db_pool.close()

@app.post(f"/webhook/{TOKEN}")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
    except Exception as e:
        logging.error(f"Webhook xato: {e}")
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
async def read_root():
    return HTMLResponse(content=INDEX_HTML)

@app.get("/health")
async def health():
    return {"status": "ok", "bot": "running"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
