import os, logging, random, aiohttp, re, asyncio, asyncpg, datetime
import hashlib, base64, uuid, secrets, string, json as json_lib
from urllib.parse import quote
from io import BytesIO
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, PreCheckoutQueryHandler)
from telegram.error import TelegramError
from openai import AsyncOpenAI
from google import genai
from google.genai import types
import uvicorn

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
FILES_PER_PAGE = 8
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

openrouter_client = AsyncOpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1", timeout=300.0) if OPENROUTER_API_KEY else None
mistral_client = AsyncOpenAI(api_key=MISTRAL_API_KEY, base_url="https://api.mistral.ai/v1", timeout=300.0) if MISTRAL_API_KEY else None
groq_client = AsyncOpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1", timeout=300.0) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

db_pool = None
PENDING_VIDEOS = {}
AUTO_ADD_TIMEOUT = 600

async def edit_or_send(query, context, text, reply_markup):
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='Markdown')
    except Exception:
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(chat_id=query.message.chat_id, text=text, reply_markup=reply_markup, parse_mode='Markdown')

def get_file_button_info(fn, ft):
    n = (fn or "").lower()
    if n.endswith('.apk'): return "📥 APK YUKLAB OLISH"
    if n.endswith('.py'): return "🐍 PYTHON OLISH"
    if n.endswith('.lua'): return "🌙 LUA OLISH"
    if n.endswith(('.zip', '.rar', '.7z')): return "📦 DASTURNI OLISH"
    if n.endswith('.pdf'): return "📖 KITOB OLISH"
    if ft == 'video': return "🎥 VIDEONI OLISH"
    if ft == 'photo': return "🖼 RASMNI OLISH"
    return "📥 FAYLNI OLISH"

def file_type_icon(ft):
    return {'document':'📄','video':'🎬','photo':'🖼','audio':'🎵','voice':'🎙','animation':'🎞'}.get(ft,'📎')

async def safe_send_file(context, chat_id, fd, reply_markup=None):
    ft, fid, title = fd['file_type'], fd['file_id'], fd['title']
    try:
        if ft == 'document': await context.bot.send_document(chat_id=chat_id, document=fid, caption=f"📄 **{title}**", parse_mode='Markdown', reply_markup=reply_markup)
        elif ft == 'video': await context.bot.send_video(chat_id=chat_id, video=fid, caption=f"🎬 **{title}**", parse_mode='Markdown', reply_markup=reply_markup)
        elif ft == 'photo': await context.bot.send_photo(chat_id=chat_id, photo=fid, caption=f"🖼 **{title}**", parse_mode='Markdown', reply_markup=reply_markup)
        elif ft == 'audio': await context.bot.send_audio(chat_id=chat_id, audio=fid, caption=f"🎵 **{title}**", parse_mode='Markdown', reply_markup=reply_markup)
        elif ft == 'voice': await context.bot.send_voice(chat_id=chat_id, voice=fid, reply_markup=reply_markup)
        elif ft == 'animation': await context.bot.send_animation(chat_id=chat_id, animation=fid, caption=f"🎞 **{title}**", parse_mode='Markdown', reply_markup=reply_markup)
        else: await context.bot.send_document(chat_id=chat_id, document=fid, caption=f"📄 **{title}**", parse_mode='Markdown', reply_markup=reply_markup)
        return True, None
    except Exception as e:
        logging.error(f"file send xato [{ft}]: {e}")
        return False, str(e)

async def init_db():
    global db_pool
    if not DATABASE_URL: return
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
        async with db_pool.acquire() as conn:
            await conn.execute('''CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, lang VARCHAR(5) DEFAULT 'uz', score INT DEFAULT 0, is_premium BOOLEAN DEFAULT FALSE, ai_requests_today INT DEFAULT 0, last_ai_date DATE DEFAULT CURRENT_DATE, last_bonus TIMESTAMP DEFAULT '1970-01-01 00:00:00', last_challenge_date DATE DEFAULT '1970-01-01', streak_days INT DEFAULT 0, last_streak_date DATE DEFAULT '1970-01-01', joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            await conn.execute('''CREATE TABLE IF NOT EXISTS files (id SERIAL PRIMARY KEY, title VARCHAR(255), file_id VARCHAR(255), file_type VARCHAR(20), is_premium BOOLEAN DEFAULT FALSE, category_id INT, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            await conn.execute('''CREATE TABLE IF NOT EXISTS file_categories (id SERIAL PRIMARY KEY, name VARCHAR(255) NOT NULL UNIQUE, icon VARCHAR(10) DEFAULT '📁', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            await conn.execute("ALTER TABLE files ADD COLUMN IF NOT EXISTS category_id INT")
            await conn.execute('''CREATE TABLE IF NOT EXISTS updates_history (id SERIAL PRIMARY KEY, title VARCHAR(255), description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            await conn.execute('''CREATE TABLE IF NOT EXISTS auto_lessons (id SERIAL PRIMARY KEY, lesson_number INT UNIQUE, message_id INT, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            await conn.execute('''CREATE TABLE IF NOT EXISTS bot_settings (key VARCHAR(50) PRIMARY KEY, value VARCHAR(255))''')
            await conn.execute("INSERT INTO bot_settings (key, value) VALUES ('auto_forward', 'off') ON CONFLICT (key) DO NOTHING")
            await conn.execute('''CREATE TABLE IF NOT EXISTS video_attachments (lesson_number INT PRIMARY KEY, file_id VARCHAR(255), file_type VARCHAR(20), file_name VARCHAR(255), button_text VARCHAR(100) DEFAULT '📥 DASTURNI OLISH', added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_files_category ON files(category_id)')
        await ensure_default_categories()
        logging.info("✅ Baza tayyor")
    except Exception as e:
        logging.error(f"Baza xatosi: {e}")

async def ensure_default_categories():
    if not db_pool: return
    for name, icon in [("Lua Fayllar", "📙"), ("Python Fayllar", "🐍")]:
        try:
            async with db_pool.acquire() as conn:
                await conn.execute('INSERT INTO file_categories (name, icon) VALUES ($1, $2) ON CONFLICT (name) DO NOTHING', name, icon)
        except Exception as e: logging.error(f"Default cat xato: {e}")

async def add_user(uid, lang='uz'):
    if not db_pool: return
    async with db_pool.acquire() as c:
        await c.execute('INSERT INTO users (user_id, lang) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET lang = EXCLUDED.lang', uid, lang)

async def add_score(uid, pts):
    if not db_pool: return
    async with db_pool.acquire() as c: await c.execute('UPDATE users SET score = score + $1 WHERE user_id = $2', pts, uid)

async def add_score_all(pts):
    if not db_pool: return
    async with db_pool.acquire() as c: await c.execute('UPDATE users SET score = score + $1', pts)

async def get_user_profile(uid):
    if not db_pool: return None
    async with db_pool.acquire() as c:
        u = await c.fetchrow('SELECT score, last_bonus, is_premium, last_challenge_date, streak_days FROM users WHERE user_id = $1', uid)
        if not u: return None
        rank = await c.fetchval('SELECT COUNT(*) FROM users WHERE score > $1', u['score'])
        return {"score": u['score'], "rank": rank + 1, "is_premium": u['is_premium'], "last_challenge_date": u['last_challenge_date'], "streak_days": u['streak_days'] or 0}

async def update_challenge_date(uid):
    if not db_pool: return
    async with db_pool.acquire() as c: await c.execute('UPDATE users SET last_challenge_date = $1 WHERE user_id = $2', datetime.date.today(), uid)

async def check_ai_limit(uid):
    if uid == ADMIN_ID or not db_pool: return True, 999
    async with db_pool.acquire() as c:
        u = await c.fetchrow('SELECT is_premium, ai_requests_today, last_ai_date FROM users WHERE user_id = $1', uid)
        today = datetime.date.today()
        if u['is_premium']: return True, 999
        if u['last_ai_date'] < today:
            await c.execute('UPDATE users SET ai_requests_today = 1, last_ai_date = $1 WHERE user_id = $2', today, uid)
            return True, 4
        if u['ai_requests_today'] < 5:
            await c.execute('UPDATE users SET ai_requests_today = ai_requests_today + 1 WHERE user_id = $1', uid)
            return True, 5 - u['ai_requests_today']
        return False, 0

async def make_premium(uid):
    if not db_pool: return
    async with db_pool.acquire() as c: await c.execute('UPDATE users SET is_premium = TRUE WHERE user_id = $1', uid)

async def get_top_users():
    if not db_pool: return []
    async with db_pool.acquire() as c: return await c.fetch('SELECT user_id, score FROM users ORDER BY score DESC LIMIT 10')

async def get_all_categories():
    if not db_pool: return []
    async with db_pool.acquire() as c: return await c.fetch('SELECT id, name, icon FROM file_categories ORDER BY id ASC')

async def get_categories_with_counts():
    if not db_pool: return []
    async with db_pool.acquire() as c:
        return await c.fetch('''SELECT c.id, c.name, c.icon, COUNT(f.id) AS file_count FROM file_categories c LEFT JOIN files f ON f.category_id = c.id GROUP BY c.id, c.name, c.icon ORDER BY c.id ASC''')

async def get_category_by_id(cat_id):
    if not db_pool: return None
    async with db_pool.acquire() as c: return await c.fetchrow('SELECT id, name, icon FROM file_categories WHERE id = $1', cat_id)

async def add_category(name, icon='📁'):
    if not db_pool: return None
    async with db_pool.acquire() as c:
        e = await c.fetchrow('SELECT id FROM file_categories WHERE name = $1', name)
        if e: return e['id']
        return await c.fetchval('INSERT INTO file_categories (name, icon) VALUES ($1, $2) RETURNING id', name, icon)

async def get_files_by_category_paginated(cat_id, page=0, pp=FILES_PER_PAGE):
    if not db_pool: return []
    async with db_pool.acquire() as c:
        return await c.fetch('SELECT id, title, is_premium, file_type FROM files WHERE category_id = $1 ORDER BY id DESC LIMIT $2 OFFSET $3', cat_id, pp, page*pp)

async def count_files_in_category(cat_id):
    if not db_pool: return 0
    async with db_pool.acquire() as c: return await c.fetchval('SELECT COUNT(*) FROM files WHERE category_id = $1', cat_id) or 0

async def count_all_files():
    if not db_pool: return 0
    async with db_pool.acquire() as c: return await c.fetchval('SELECT COUNT(*) FROM files') or 0

async def count_all_categories():
    if not db_pool: return 0
    async with db_pool.acquire() as c: return await c.fetchval('SELECT COUNT(*) FROM file_categories') or 0

async def add_file_db_cat(title, fid, ft, cat_id, is_prem=False):
    if not db_pool: return None
    async with db_pool.acquire() as c:
        return await c.fetchval('INSERT INTO files (title, file_id, file_type, category_id, is_premium) VALUES ($1, $2, $3, $4, $5) RETURNING id', title, fid, ft, cat_id, is_prem)

async def delete_category(cat_id):
    if not db_pool: return
    async with db_pool.acquire() as c:
        await c.execute('DELETE FROM files WHERE category_id = $1', cat_id)
        await c.execute('DELETE FROM file_categories WHERE id = $1', cat_id)

async def delete_file_by_id(fid):
    if not db_pool: return
    async with db_pool.acquire() as c: await c.execute('DELETE FROM files WHERE id = $1', fid)

async def get_file_by_id(fid):
    if not db_pool: return None
    async with db_pool.acquire() as c: return await c.fetchrow('SELECT * FROM files WHERE id = $1', fid)

async def search_files(q):
    if not db_pool: return []
    async with db_pool.acquire() as c:
        return await c.fetch('''SELECT f.id, f.title, f.is_premium, f.file_type, c.name AS cat_name, c.icon AS cat_icon FROM files f LEFT JOIN file_categories c ON f.category_id = c.id WHERE f.title ILIKE $1 ORDER BY f.id DESC LIMIT 30''', f'%{q}%')

async def get_recent_files(limit=10):
    if not db_pool: return []
    async with db_pool.acquire() as c:
        return await c.fetch('''SELECT f.id, f.title, f.is_premium, f.file_type, c.name AS cat_name, c.icon AS cat_icon FROM files f LEFT JOIN file_categories c ON f.category_id = c.id ORDER BY f.id DESC LIMIT $1''', limit)

async def update_file_title(fid, title):
    if not db_pool: return
    async with db_pool.acquire() as c: await c.execute('UPDATE files SET title = $1 WHERE id = $2', title, fid)

async def move_file_to_category(fid, cat_id):
    if not db_pool: return
    async with db_pool.acquire() as c: await c.execute('UPDATE files SET category_id = $1 WHERE id = $2', cat_id, fid)

async def toggle_file_premium(fid):
    if not db_pool: return
    async with db_pool.acquire() as c: await c.execute('UPDATE files SET is_premium = NOT is_premium WHERE id = $1', fid)

async def get_setting(key, default=None):
    if not db_pool: return default
    async with db_pool.acquire() as c:
        r = await c.fetchrow('SELECT value FROM bot_settings WHERE key = $1', key)
        return r['value'] if r else default

async def set_setting(key, val):
    if not db_pool: return
    async with db_pool.acquire() as c:
        await c.execute('INSERT INTO bot_settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value', key, str(val))

async def add_update_db(title, desc):
    if not db_pool: return
    async with db_pool.acquire() as c: await c.execute('INSERT INTO updates_history (title, description) VALUES ($1, $2)', title, desc)

async def get_recent_updates(limit=5):
    if not db_pool: return []
    async with db_pool.acquire() as c: return await c.fetch('SELECT title, description, created_at FROM updates_history ORDER BY id DESC LIMIT $1', limit)

async def get_all_lessons():
    lessons = {i: i+2 for i in range(1, 46)}
    lessons[46] = 103; lessons[47] = 107
    if db_pool:
        async with db_pool.acquire() as c:
            for r in await c.fetch('SELECT lesson_number, message_id FROM auto_lessons'):
                lessons[r['lesson_number']] = r['message_id']
    return lessons

async def get_max_lesson_number():
    m = 47
    if db_pool:
        async with db_pool.acquire() as c:
            d = await c.fetchval('SELECT MAX(lesson_number) FROM auto_lessons')
            if d: m = max(m, d)
    return m

def get_level(s):
    if s < 100: return "🥉 Boshlovchi"
    if s < 300: return "🥈 O'rta"
    if s < 600: return "🥇 Ilg'or"
    return "💎 Ekspert"

def get_streak_reward(d):
    r = {1:10,2:15,3:25,4:30,5:30,6:30,7:75,8:40,9:40,10:50,11:40,12:40,13:40,14:150,15:50,16:50,17:50,18:50,19:50,20:60,21:60,22:60,23:60,24:60,25:70,26:70,27:70,28:70,29:70,30:500}
    return r.get(d, 50)

async def claim_streak(uid):
    if not db_pool: return False, 0, 0, False, False
    async with db_pool.acquire() as c:
        u = await c.fetchrow('SELECT streak_days, last_streak_date FROM users WHERE user_id = $1', uid)
        if not u: return False, 0, 0, False, False
        today = datetime.date.today()
        last = u['last_streak_date']; cur = u['streak_days'] or 0
        if last == today: return False, cur, 0, False, True
        if last == today - datetime.timedelta(days=1):
            ns = cur + 1; reset = False
        else:
            ns = 1; reset = (cur > 0)
        rw = get_streak_reward(ns)
        await c.execute('UPDATE users SET streak_days = $1, last_streak_date = $2, score = score + $3 WHERE user_id = $4', ns, today, rw, uid)
        if ns == 30: await c.execute('UPDATE users SET is_premium = TRUE WHERE user_id = $1', uid)
        return True, ns, rw, reset, False

async def is_subscribed(uid, ctx):
    if uid == ADMIN_ID: return True
    try:
        m = await ctx.bot.get_chat_member(chat_id=FORCE_SUB_CHANNEL, user_id=uid)
        return m.status in ['member', 'administrator', 'creator']
    except: return True

LUA_LESSONS = {1:93,2:94,3:97,4:98,5:99,6:100,7:101,8:104}
PYTHON_EXTRA_VIDEOS = [106]

CHALLENGES_DATA = [
    {"text": "Python yordamida berilgan sonning faktorialini hisoblovchi funksiya yozing."},
    {"text": "Berilgan so'z palindrom ekanligini tekshiruvchi kod yozing."},
    {"text": "1 dan N gacha bo'lgan sonlar yig'indisini hisoblovchi kod yozing."},
    {"text": "Berilgan ro'yxatdagi eng katta sonni topuvchi funksiya yozing."},
    {"text": "FizzBuzz masalasi: 1 dan 100 gacha."}
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
    "hacking": {"name": "🛡️ Kiberxavfsizlik", "items": {"nmap": {"name": "🌐 Nmap", "pkg": "nmap", "type": "pkg"}, "hydra": {"name": "🔑 Hydra", "pkg": "hydra", "type": "pkg"}, "sqlmap": {"name": "💥 SQLmap", "pkg": "sqlmap", "type": "pip"}, "metasploit": {"name": "💀 Metasploit", "pkg": "metasploit", "type": "pkg"}, "john": {"name": "🔓 John", "pkg": "john", "type": "pkg"}, "nikto": {"name": "🕵️ Nikto", "pkg": "nikto", "type": "pkg"}, "aircrack": {"name": "📡 Aircrack-ng", "pkg": "aircrack-ng", "type": "pkg"}, "tshark": {"name": "🦈 Tshark", "pkg": "tshark", "type": "pkg"}}},
    "media": {"name": "🎬 Media", "items": {"ffmpeg": {"name": "🎞️ FFmpeg", "pkg": "ffmpeg", "type": "pkg"}, "ytdlp": {"name": "📥 yt-dlp", "pkg": "yt-dlp", "type": "pip"}, "imagemagick": {"name": "🖼️ ImageMagick", "pkg": "imagemagick", "type": "pkg"}, "openssh": {"name": "🔐 OpenSSH", "pkg": "openssh", "type": "pkg"}, "net-tools": {"name": "🌐 Net-tools", "pkg": "net-tools", "type": "pkg"}, "traceroute": {"name": "🛣️ Traceroute", "pkg": "traceroute", "type": "pkg"}, "dnsutils": {"name": "🔍 DNS Utils", "pkg": "dnsutils", "type": "pkg"}}},
    "style": {"name": "🎨 Chiroyli", "items": {"zsh": {"name": "🐚 Zsh", "pkg": "zsh", "type": "pkg"}, "ohmyzsh": {"name": "✨ Oh-My-Zsh", "pkg": "curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh | bash", "type": "custom"}, "termuxstyle": {"name": "🎨 Termux Styling", "pkg": "termux-styling", "type": "pkg"}, "figlet": {"name": "🔠 Figlet", "pkg": "figlet", "type": "pkg"}, "lolcat": {"name": "🌈 Lolcat", "pkg": "lolcat", "type": "pkg"}, "neofetch": {"name": "💻 Neofetch", "pkg": "neofetch", "type": "pkg"}}}
}

T = {
    'choose_lang': "👋 **Assalomu alaykum!**\n\nTilni tanlang:",
    'welcome': "👋 **Assalomu alaykum!**\n\nMen **Termux va Dasturlash** bo'yicha yordamchi botman.",
    'btn_termux': "📽️ TERMUX DARSLIKLAR", 'btn_lua': "📽️ LUA PAK DARSLIK",
    'btn_java': "☕ JAVA", 'btn_apk': "📥 APK YUKLAB OLISH",
    'btn_ai': "🤖 AI Dasturchi", 'btn_profile': "👤 Profil", 'btn_top': "🏆 Top 10",
    'btn_quiz': "🧠 Test", 'btn_security': "🛡️ Kiberxavfsizlik",
    'btn_support': "✉️ Admin", 'btn_tip': "💡 Maslahat", 'btn_cheatsheet': "📜 Buyruqlar",
    'btn_change_lang': "🌐 Til", 'btn_scripts': "📦 Skript", 'btn_files': "🗂️ Fayllar",
    'btn_premium': "💎 Premium", 'btn_challenge': "🧩 Masala", 'btn_theme': "🎨 Tema",
    'btn_back': "🔙 Bosh menyu", 'btn_prev': "⬅️", 'btn_next': "➡️",
    'btn_python': "🐍 PYTHON OLISH", 'btn_lessons_menu': "📚 Menyu", 'btn_back_cheat': "🔙 Orqaga",
    'btn_updates': "🆕 Yangilanishlar", 'btn_devtools': "🧰 DevTools", 'streak_btn': "🔥 Streak",
    'force_sub_text': "⚠️ **Diqqat!**\n\nBotdan foydalanish uchun kanalga a'zo bo'ling:",
    'btn_join': "📢 A'zo bo'lish", 'btn_check': "✅ Tekshirish", 'force_sub_error': "❌ A'zo bo'lmadingiz!",
    'challenge_problem': "📝 **Masala:**\n\n{text}\n\n💻 *Kod yuboring:*",
    'challenge_already_done': "✅ Bugun yechdingiz!",
    'challenge_wait': "🤖 Tekshirilmoqda...",
    'challenge_correct': "✅ **To'g'ri!** +30 ball",
    'challenge_wrong': "❌ **Xato!**\n\n{feedback}",
    'challenge_no_code': "⚠️ Kod yuboring.",
    'theme_menu': "🎨 **Termux Terminal Dizayni**",
    'theme_send': "✅ **{theme_name} tayyor!**\n\n`colors.properties` ni `~/.termux/` ga joylashtiring va `termux-reload-settings` bering.",
    'script_cat_menu': "📦 **Skript Yaratuvchi**",
    'script_items_menu': "⚙️ **{cat_name}**",
    'btn_generate_script': "🚀 Yaratish", 'btn_clear_scripts': "🗑 Tozalash", 'btn_back_to_cats': "🔙 Orqaga",
    'script_empty': "⚠️ Dastur tanlang!", 'script_done': "✅ **Tayyor!**\n\n`bash install.sh`",
    'files_title': "🗂️ **Fayllar Markazi**",
    'files_stats': "📊 Jami: **{total_files}** fayl, **{total_cats}** papka",
    'files_empty': "📭 Hozircha fayllar yo'q.",
    'files_cat_title': "📂 **{cat_name}**\n\n📄 Sahifa {page}/{total_pages} • Jami: **{count}**",
    'files_cat_empty': "📭 Bu papka bo'sh.",
    'files_back_to_cats': "🔙 Papkalarga",
    'files_btn_search': "🔍 Qidirish", 'files_btn_recent': "🆕 Yangi",
    'file_sending': "⏳ Yuborilmoqda...",
    'file_premium_locked': "🔒 Premium fayl!",
    'file_not_found': "❌ Fayl topilmadi",
    'file_download_error': "❌ Yuklab bo'lmadi",
    'file_view_title': "📄 **{title}**",
    'file_view_info': "📁 {cat_name}\n{icon} **{ftype}**\n💎 **{premium}**",
    'file_btn_download': "📥 Yuklab olish", 'file_btn_back_cat': "🔙 Papkaga",
    'files_search_prompt': "🔍 **Fayl qidirish**\n\nNom yozing:",
    'files_search_empty': "🔍 **\"{query}\"** topilmadi.",
    'files_search_results': "🔍 **\"{query}\"** — {count} ta:",
    'files_recent_title': "🆕 **Yangi fayllar:**",
    'files_recent_empty': "📭 Yangi fayllar yo'q.",
    'admin_files_title': "🗂️ **Fayllar Boshqaruvi**\n\nJami: **{total_files}** fayl, **{total_cats}** papka",
    'admin_files_empty': "📭 Papkalar yo'q. Yangi yarating:",
    'admin_btn_new_cat': "➕ Yangi papka", 'admin_btn_del_cat': "🗑 Papkani o'chirish",
    'admin_btn_stats': "📊 Statistika", 'admin_btn_all_files': "📋 Barcha fayllar",
    'admin_file_new_cat_prompt': "➕ **Yangi papka**\n\nNomini yozing:",
    'admin_file_cat_created': "✅ **Yaratildi:** {name}",
    'admin_file_send_to': "📎 **\"{cat_name}\"** ga fayl yuboring:",
    'admin_file_title_prompt': "✍️ **Fayl nomini yozing:**",
    'admin_file_choose_del': "🗑 **Qaysi papkani o'chirish?**",
    'admin_cat_deleted': "✅ Papka o'chirildi!",
    'admin_cat_del_confirm': "⚠️ **{cat_name}** papkasini o'chirish?\n\n_Ichida **{count}** ta fayl bor!_",
    'admin_file_deleted': "✅ Fayl o'chirildi!",
    'admin_file_saved': "✅ Fayl saqlandi!",
    'admin_file_cancel': "❌ Bekor qilindi.",
    'admin_files_cat_title': "🗂️ **{cat_name}** — Admin\n\n📄 Sahifa {page}/{total_pages} • Jami: **{count}**",
    'admin_btn_add_here': "➕ Fayl qo'shish",
    'admin_file_view_title': "📄 **{title}** (Admin)",
    'admin_file_view_info': "📁 {cat_name}\n{icon} **{ftype}**\n💎 **{premium}**\n🆔 `{fid}`",
    'admin_btn_edit_title': "✏️ Nom o'zgartirish",
    'admin_btn_move': "📁 Ko'chirish",
    'admin_btn_toggle_premium': "💎 Premium: {status}",
    'admin_btn_delete_file': "🗑 O'chirish",
    'admin_btn_back_to_cat': "🔙 Papkaga",
    'admin_edit_title_prompt': "✏️ **Yangi nom:**\n\n_Hozirgi: `{old}`_",
    'admin_move_prompt': "📁 **Qaysi papkaga?**\n\n`{title}`",
    'admin_file_moved': "✅ **Ko'chirildi!**\n\n`{title}` → **{cat_name}**",
    'admin_premium_on': "✅ Premium YOQILDI",
    'admin_premium_off': "🔓 Premium O'CHIRILDI",
    'admin_delete_yes': "🗑 Ha, o'chirish", 'admin_cancel': "❌ Bekor",
    'admin_all_files_title': "📋 **Barcha fayllar** (jami **{count}** ta):",
    'premium_menu': "💎 **Premium**\n\n✅ Cheksiz AI\n✅ Premium fayllar\n\n💰 **50 Stars** — 1 oy",
    'btn_buy_premium': "⭐️ 50 Stars",
    'premium_success': "🎉 **Premium faollashtirildi!**",
    'ai_limit_reached': "⚠️ **Limit tugadi!** Premium oling.",
    'btn_go_premium': "💎 Premium",
    'admin_panel': "👑 **Admin Panel**",
    'admin_btn_bcast': "📢 Xabar", 'admin_btn_points': "🎁 Ball", 'admin_btn_add_file': "🗂️ Fayllar",
    'admin_btn_close': "❌ Yopish", 'admin_btn_update': "📣 Yangilanish",
    'admin_btn_auto_fwd_on': "🔛 Auto-forward: ON", 'admin_btn_auto_fwd_off': "🔴 Auto-forward: OFF",
    'admin_points_prompt': "🎁 **Ball miqdori:**", 'admin_points_wait': "⏳...",
    'admin_points_done': "✅ +{points}\n📩 {success}\n❌ {fail}",
    'admin_update_prompt': "📣 **Yangilanish matni:**", 'admin_update_wait': "⏳...",
    'admin_update_done': "✅ {success} | ❌ {fail}",
    'admin_toggle_on': "✅ Auto-forward yoqildi!",
    'admin_toggle_off': "🔴 Auto-forward o'chirildi.",
    'text_page': "📚 **Darsliklar**\n\nSahifa: {page}/{total}",
    'text_lua': "📚 **LUA DARSLIKLARI**",
    'text_python_done': "Python darsligi ✅",
    'text_error_vid': "❌ **Video topilmadi.**",
    'tip_header': "💡 **Maslahat:**\n\n",
    'cheatsheet_menu': "📜 **Buyruqlar**",
    'cat_files': "📁 Fayllar", 'cat_packages': "📦 Paketlar", 'cat_network': "🌐 Tarmoq", 'cat_system': "⚙️ Tizim",
    'apk_caption': "📱 **Termux APK**", 'apk_file_name': "Termux.apk",
    'apk_loading': "⏳...", 'apk_too_big': "⚠️ Katta", 'apk_error': "❌ Xatolik",
    'support_prompt': "✉️ **Admin**\n\nXabar yozing:", 'support_sent': "✅ Yuborildi!",
    'support_reply': "📬 **Admin:**\n\n",
    'profile_text': "👤 **Profil**\n\n⭐ Ball: **{score}**\n🏅 {level}\n📊 #{rank}\n💎 {status}",
    'top_text': "🏆 **Top 10:**\n\n{list}",
    'quiz_start': "🧠 **Test!** +10 ball\n\n❓",
    'quiz_correct': "✅ **To'g'ri!** +10",
    'quiz_wrong': "❌ **Xato!** Javob: **{answer}**",
    'quiz_end': "🎉 Tugadi!", 'btn_next_quiz': "➡️ Keyingi",
    'sec_menu': "🛡️ **Kiberxavfsizlik**",
    'sec_info': "🔍 Ma'lumot", 'sec_pass': "🔑 Parol", 'sec_exploit': "💥 Zaiflik", 'sec_network': "📡 Tarmoq",
    'sec_info_text': "Nmap: `pkg install nmap`", 'sec_pass_text': "Hydra: `pkg install hydra`",
    'sec_exploit_text': "SQLmap: `pip install sqlmap`", 'sec_network_text': "Tshark: `pkg install tshark`",
    'admin_bcast_start': "📢 Xabar:", 'admin_bcast_wait': "⏳...", 'admin_bcast_cancel': "❌ Bekor",
    'ai_prompt': "🤖 **AI Dasturchi**\n\nTopshiriq bering:",
    'ai_wait': "🧠...", 'ai_error': "❌ {error}", 'ai_no_code': "🤖\n\n{text}",
    'ai_unsupported_file': "⚠️ Faqat kod", 'ai_video_error': "🎥",
    'ai_file_too_large': "⚠️ Katta", 'ai_text_too_long': "⚠️ Uzun", 'ai_not_coding': "🤖 Faqat dasturlash",
    'ai_limit_info': "ℹ️ Qoldi: {limit}",
    'java_info_text': "☕ **Java Termux'da**\n\n```bash\npkg install openjdk-17 -y\n```\n\n`javac Salom.java && java Salom`",
    'devtools_menu': "🧰 **Developer Tools**",
    'devtools_pass': "🔐 Parol", 'devtools_hash': "🔢 Hash",
    'devtools_b64enc': "📝 B64 Enc", 'devtools_b64dec': "📝 B64 Dec",
    'devtools_uuid': "🆔 UUID", 'devtools_qr': "📱 QR", 'devtools_json': "📊 JSON",
    'devtools_pass_prompt': "🔐 Uzunlik (8-64):", 'devtools_hash_prompt': "🔢 Matn:",
    'devtools_b64enc_prompt': "📝 Matn:", 'devtools_b64dec_prompt': "📝 Base64:",
    'devtools_json_prompt': "📊 JSON:", 'devtools_qr_prompt': "📱 Matn/havola:",
    'devtools_invalid': "❌ {error}",
    'streak_already': "✅ Bugun olgansiz!",
    'streak_reset_info': "⚠️ Streak yangilandi!",
    'streak_7_bonus': "🎉 7 kun!", 'streak_30_bonus': "🎉 30 kun! Premium!",
    'updates_menu': "🆕 **Yangilanishlar:**\n\n", 'updates_empty': "Yangilanish yo'q."
}

TIPS = ["**Tezroq kod:**\n`nano` o'rniga `micro` ishlating."]
COMMANDS_DATA = {'files': [('ls', 'Fayllar'), ('cd', 'Papkaga kirish'), ('pwd', 'Manzil'), ('mkdir', 'Papka yaratish')],
    'packages': [('pkg update', 'Yangilash'), ('pkg install', 'Ornatish'), ('pip install', 'Python paket')],
    'network': [('ping google.com', 'Tekshirish'), ('curl', 'Yuklab olish'), ('wget', 'Yuklab olish')],
    'system': [('clear', 'Tozalash'), ('top', 'Jarayonlar'), ('df', 'Disk'), ('free', 'RAM')]}

QUIZ_DATA = [
    {'q': "Papka yaratish?", 'options': ['mkdir', 'cd', 'ls', 'rm'], 'answer': 'mkdir'},
    {'q': "Fayllar ro'yxati?", 'options': ['ls', 'pwd', 'cat', 'touch'], 'answer': 'ls'},
    {'q': "Termux yangilash?", 'options': ['pkg update', 'apt-get', 'install', 'upgrade'], 'answer': 'pkg update'},
    {'q': "Python ishga tushirish?", 'options': ['python file.py', 'run file.py', 'py file', 'exec file.py'], 'answer': 'python file.py'},
    {'q': "Papkaga kirish?", 'options': ['cd', 'mv', 'cp', 'dir'], 'answer': 'cd'},
    {'q': "Manzilni bilish?", 'options': ['pwd', 'ls', 'cd', 'path'], 'answer': 'pwd'},
    {'q': "Faylni o'chirish?", 'options': ['rm', 'del', 'drop', 'erase'], 'answer': 'rm'},
    {'q': "Bo'sh fayl yaratish?", 'options': ['touch', 'nano', 'cat', 'echo'], 'answer': 'touch'},
    {'q': "Faylni o'qish?", 'options': ['cat', 'ls', 'open', 'read'], 'answer': 'cat'},
    {'q': "Python kutubxona?", 'options': ['pip install', 'pkg install', 'apt install', 'python install'], 'answer': 'pip install'},
    {'q': "Matn muharriri?", 'options': ['nano', 'notepad', 'word', 'gedit'], 'answer': 'nano'},
    {'q': "Git yuklash?", 'options': ['git clone', 'git pull', 'git fetch', 'git download'], 'answer': 'git clone'},
    {'q': "Ping?", 'options': ['ping', 'traceroute', 'netstat', 'wget'], 'answer': 'ping'},
    {'q': "Bajarish huquqi?", 'options': ['chmod +x', 'chmod 777', 'chown', 'chgrp'], 'answer': 'chmod +x'},
    {'q': "Ekran tozalash?", 'options': ['clear', 'cls', 'reset', 'erase'], 'answer': 'clear'},
    {'q': "CPU/RAM?", 'options': ['top', 'ls', 'df', 'free'], 'answer': 'top'},
    {'q': "Yuklab olish?", 'options': ['wget', 'curl', 'download', 'fetch'], 'answer': 'wget'},
    {'q': "Port skaner?", 'options': ['nmap', 'ping', 'netstat', 'ssh'], 'answer': 'nmap'},
    {'q': "Chiqish?", 'options': ['exit', 'quit', 'close', 'stop'], 'answer': 'exit'},
    {'q': "Nusxalash?", 'options': ['cp', 'mv', 'copy', 'dup'], 'answer': 'cp'}
]

def kb_lang():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="lang_uz"), InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")]])

def kb_devtools():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(T['devtools_pass'], callback_data="dev_pass"), InlineKeyboardButton(T['devtools_hash'], callback_data="dev_hash")],
        [InlineKeyboardButton(T['devtools_b64enc'], callback_data="dev_b64enc"), InlineKeyboardButton(T['devtools_b64dec'], callback_data="dev_b64dec")],
        [InlineKeyboardButton(T['devtools_uuid'], callback_data="dev_uuid"), InlineKeyboardButton(T['devtools_qr'], callback_data="dev_qr")],
        [InlineKeyboardButton(T['devtools_json'], callback_data="dev_json")],
        [InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")]
    ])

def kb_main(uid):
    k = [
        [InlineKeyboardButton(T['btn_termux'], callback_data="page_1"), InlineKeyboardButton(T['btn_lua'], callback_data="lua_page_1")],
        [InlineKeyboardButton(T['btn_java'], callback_data="java_info"), InlineKeyboardButton(T['btn_ai'], callback_data="ai_start")],
        [InlineKeyboardButton(T['btn_security'], callback_data="sec_start"), InlineKeyboardButton(T['btn_scripts'], callback_data="script_menu")],
        [InlineKeyboardButton(T['btn_files'], callback_data="files_menu"), InlineKeyboardButton(T['btn_theme'], callback_data="theme_menu")],
        [InlineKeyboardButton(T['btn_cheatsheet'], callback_data="cheatsheet"), InlineKeyboardButton(T['btn_apk'], callback_data="send_apk")],
        [InlineKeyboardButton(T['btn_challenge'], callback_data="challenge_start"), InlineKeyboardButton(T['btn_quiz'], callback_data="quiz_start")],
        [InlineKeyboardButton(T['btn_top'], callback_data="top_users"), InlineKeyboardButton(T['btn_premium'], callback_data="premium_menu")],
        [InlineKeyboardButton(T['btn_profile'], callback_data="my_profile"), InlineKeyboardButton(T['streak_btn'], callback_data="daily_bonus")],
        [InlineKeyboardButton(T['btn_devtools'], callback_data="devtools_menu"), InlineKeyboardButton(T['btn_tip'], callback_data="daily_tip")],
        [InlineKeyboardButton(T['btn_updates'], callback_data="updates_menu"), InlineKeyboardButton(T['btn_change_lang'], callback_data="change_lang")],
        [InlineKeyboardButton(T['btn_support'], callback_data="support_start")]
    ]
    if uid == ADMIN_ID: k.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin_menu")])
    return InlineKeyboardMarkup(k)

def kb_theme():
    k, row = [], []
    for key, th in THEMES_DATA.items():
        row.append(InlineKeyboardButton(th['name'], callback_data=f"theme_apply_{key}"))
        if len(row) == 2: k.append(row); row = []
    if row: k.append(row)
    k.append([InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(k)

def kb_premium():
    return InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_buy_premium'], callback_data="buy_premium")],
        [InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")]])

def kb_script_cats():
    k, row = [], []
    for ck, cd in SCRIPTS_DATA.items():
        row.append(InlineKeyboardButton(cd['name'], callback_data=f"script_cat_{ck}"))
        if len(row) == 2: k.append(row); row = []
    if row: k.append(row)
    k.append([InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(k)

def kb_script_items(ck, selected):
    k, row = [], []
    for ik, id in SCRIPTS_DATA[ck]['items'].items():
        s = "✅ " if f"{ck}_{ik}" in selected else "⬜ "
        row.append(InlineKeyboardButton(f"{s}{id['name']}", callback_data=f"script_toggle_{ck}_{ik}"))
        if len(row) == 2: k.append(row); row = []
    if row: k.append(row)
    k.append([InlineKeyboardButton(T['btn_generate_script'], callback_data="script_generate"), InlineKeyboardButton(T['btn_clear_scripts'], callback_data="script_clear")])
    k.append([InlineKeyboardButton(T['btn_back_to_cats'], callback_data="script_menu")])
    return InlineKeyboardMarkup(k)

def kb_admin(af="off"):
    a = T['admin_btn_auto_fwd_on'] if af == "on" else T['admin_btn_auto_fwd_off']
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(T['admin_btn_stats'], callback_data="admin_stats")],
        [InlineKeyboardButton(T['admin_btn_bcast'], callback_data="admin_bcast")],
        [InlineKeyboardButton(T['admin_btn_update'], callback_data="admin_update")],
        [InlineKeyboardButton(T['admin_btn_points'], callback_data="admin_points")],
        [InlineKeyboardButton(T['admin_btn_add_file'], callback_data="admin_files_menu")],
        [InlineKeyboardButton(a, callback_data="admin_toggle_autofwd")],
        [InlineKeyboardButton(T['admin_btn_close'], callback_data="admin_close")]
    ])

def kb_sub():
    return InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_join'], url=f"https://t.me/{FORCE_SUB_CHANNEL.replace('@', '')}")],
        [InlineKeyboardButton(T['btn_check'], callback_data="check_sub")]])

def kb_profile():
    return InlineKeyboardMarkup([[InlineKeyboardButton(T['streak_btn'], callback_data="daily_bonus")],
        [InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")]])

def kb_sec():
    return InlineKeyboardMarkup([[InlineKeyboardButton(T['sec_info'], callback_data="sec_cat_info")],
        [InlineKeyboardButton(T['sec_pass'], callback_data="sec_cat_pass")],
        [InlineKeyboardButton(T['sec_exploit'], callback_data="sec_cat_exploit")],
        [InlineKeyboardButton(T['sec_network'], callback_data="sec_cat_network")],
        [InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")]])

def kb_lessons(page, max_lesson=47):
    k = []
    s = (page - 1) * 10 + 1
    e = min(page * 10, max_lesson)
    row = []
    for i in range(s, e + 1):
        row.append(InlineKeyboardButton(f"🎬 {i}", callback_data=f"lesson_{i}"))
        if len(row) == 2: k.append(row); row = []
    if row: k.append(row)
    nav = []
    if page > 1: nav.append(InlineKeyboardButton(T['btn_prev'], callback_data=f"page_{page-1}"))
    if e < max_lesson: nav.append(InlineKeyboardButton(T['btn_next'], callback_data=f"page_{page+1}"))
    if nav: k.append(nav)
    k.append([InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(k)

def kb_lua_lessons():
    k, row = [], []
    for i in range(1, 9):
        row.append(InlineKeyboardButton(f"🎬 {i}", callback_data=f"lua_lesson_{i}"))
        if len(row) == 2: k.append(row); row = []
    if row: k.append(row)
    k.append([InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(k)

def kb_cheatsheet():
    return InlineKeyboardMarkup([[InlineKeyboardButton(T['cat_files'], callback_data="cat_files")],
        [InlineKeyboardButton(T['cat_packages'], callback_data="cat_packages")],
        [InlineKeyboardButton(T['cat_network'], callback_data="cat_network")],
        [InlineKeyboardButton(T['cat_system'], callback_data="cat_system")],
        [InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")]])

def kb_quiz(options):
    k, row = [], []
    sh = options.copy(); random.shuffle(sh)
    for o in sh:
        row.append(InlineKeyboardButton(o, callback_data=f"quiz_ans_{o}"))
        if len(row) == 2: k.append(row); row = []
    if row: k.append(row)
    k.append([InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(k)

def kb_files_menu(cats):
    k = []
    for c in cats:
        k.append([InlineKeyboardButton(f"{c['icon']} {c['name']} — {c['file_count']} ta", callback_data=f"files_cat_{c['id']}_0")])
    k.append([InlineKeyboardButton(T['files_btn_search'], callback_data="files_search"), InlineKeyboardButton(T['files_btn_recent'], callback_data="files_recent")])
    k.append([InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(k)

def kb_files_cat(files, cat_id, page, tp):
    k = []
    for f in files:
        icon = "🔒" if f['is_premium'] else file_type_icon(f['file_type'])
        k.append([InlineKeyboardButton(f"{icon} {f['title']}", callback_data=f"file_view_{f['id']}")])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(T['btn_prev'], callback_data=f"files_cat_{cat_id}_{page-1}"))
    if page < tp - 1: nav.append(InlineKeyboardButton(T['btn_next'], callback_data=f"files_cat_{cat_id}_{page+1}"))
    if nav: k.append(nav)
    k.append([InlineKeyboardButton(T['files_back_to_cats'], callback_data="files_menu")])
    return InlineKeyboardMarkup(k)

def kb_file_view(fid, cat_id):
    return InlineKeyboardMarkup([[InlineKeyboardButton(T['file_btn_download'], callback_data=f"file_dl_{fid}")],
        [InlineKeyboardButton(T['file_btn_back_cat'], callback_data=f"files_cat_{cat_id}_0")],
        [InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")]])

def kb_search_results(results):
    k = []
    for f in results:
        icon = "🔒" if f['is_premium'] else file_type_icon(f['file_type'])
        k.append([InlineKeyboardButton(f"{icon} {f['title']}", callback_data=f"file_view_{f['id']}")])
    k.append([InlineKeyboardButton(T['files_back_to_cats'], callback_data="files_menu")])
    return InlineKeyboardMarkup(k)

def kb_admin_files_menu(cats):
    k = []
    for c in cats:
        k.append([InlineKeyboardButton(f"{c['icon']} {c['name']} — {c['file_count']} ta", callback_data=f"admin_files_cat_{c['id']}_0")])
    k.append([InlineKeyboardButton(T['admin_btn_new_cat'], callback_data="admin_file_new_cat"), InlineKeyboardButton(T['admin_btn_all_files'], callback_data="admin_all_files_0")])
    if cats: k.append([InlineKeyboardButton(T['admin_btn_del_cat'], callback_data="admin_file_delcat_menu")])
    k.append([InlineKeyboardButton(T['btn_back'], callback_data="admin_menu")])
    return InlineKeyboardMarkup(k)

def kb_admin_files_cat(files, cat_id, page, tp):
    k = []
    for f in files:
        icon = "🔒" if f['is_premium'] else file_type_icon(f['file_type'])
        k.append([InlineKeyboardButton(f"{icon} {f['title']}", callback_data=f"admin_file_view_{f['id']}")])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(T['btn_prev'], callback_data=f"admin_files_cat_{cat_id}_{page-1}"))
    if page < tp - 1: nav.append(InlineKeyboardButton(T['btn_next'], callback_data=f"admin_files_cat_{cat_id}_{page+1}"))
    if nav: k.append(nav)
    k.append([InlineKeyboardButton(T['admin_btn_add_here'], callback_data=f"admin_file_cat_{cat_id}")])
    k.append([InlineKeyboardButton(T['admin_btn_del_cat'], callback_data=f"admin_delcat_confirm_{cat_id}")])
    k.append([InlineKeyboardButton(T['btn_back'], callback_data="admin_files_menu")])
    return InlineKeyboardMarkup(k)

def kb_admin_file_view(fid, is_prem, cat_id):
    s = "🔒 ON" if is_prem else "🔓 OFF"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(T['admin_btn_edit_title'], callback_data=f"admin_file_edit_{fid}")],
        [InlineKeyboardButton(T['admin_btn_move'], callback_data=f"admin_file_move_{fid}")],
        [InlineKeyboardButton(T['admin_btn_toggle_premium'].format(status=s), callback_data=f"admin_file_premium_{fid}")],
        [InlineKeyboardButton(T['admin_btn_delete_file'], callback_data=f"admin_file_del_{fid}")],
        [InlineKeyboardButton(T['admin_btn_back_to_cat'], callback_data=f"admin_files_cat_{cat_id}_0")],
        [InlineKeyboardButton(T['btn_back'], callback_data="admin_files_menu")]
    ])

def kb_admin_move(fid, cats):
    k = []
    for c in cats:
        k.append([InlineKeyboardButton(f"{c['icon']} {c['name']}", callback_data=f"admin_file_move_do_{fid}_{c['id']}")])
    k.append([InlineKeyboardButton(T['admin_cancel'], callback_data=f"admin_file_view_{fid}")])
    return InlineKeyboardMarkup(k)

def kb_admin_delcat(cats):
    k = []
    for c in cats:
        k.append([InlineKeyboardButton(f"🗑 {c['icon']} {c['name']}", callback_data=f"admin_delcat_confirm_{c['id']}")])
    k.append([InlineKeyboardButton(T['btn_back'], callback_data="admin_files_menu")])
    return InlineKeyboardMarkup(k)

def kb_admin_all_files(files, page, tp):
    k = []
    for f in files:
        icon = "🔒" if f['is_premium'] else file_type_icon(f['file_type'])
        k.append([InlineKeyboardButton(f"{icon} {f['title']}", callback_data=f"admin_file_view_{f['id']}")])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(T['btn_prev'], callback_data=f"admin_all_files_{page-1}"))
    if page < tp - 1: nav.append(InlineKeyboardButton(T['btn_next'], callback_data=f"admin_all_files_{page+1}"))
    if nav: k.append(nav)
    k.append([InlineKeyboardButton(T['btn_back'], callback_data="admin_files_menu")])
    return InlineKeyboardMarkup(k)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    context.user_data.clear()
    if not await is_subscribed(uid, context):
        await update.message.reply_text(T['force_sub_text'], reply_markup=kb_sub(), parse_mode='Markdown'); return
    await add_user(uid, 'uz')
    await update.message.reply_text(T['choose_lang'], reply_markup=kb_lang(), parse_mode='Markdown')

async def button_tap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    chat_id = q.message.chat_id
    uid = q.from_user.id

    if data == "check_sub":
        if await is_subscribed(uid, context):
            await q.answer("✅"); await q.message.delete()
            await add_user(uid, 'uz')
            await context.bot.send_message(chat_id=chat_id, text=T['choose_lang'], reply_markup=kb_lang(), parse_mode='Markdown')
        else: await q.answer(T['force_sub_error'], show_alert=True)
        return

    if not await is_subscribed(uid, context):
        await q.message.reply_text(T['force_sub_text'], reply_markup=kb_sub(), parse_mode='Markdown'); return
    await q.answer()

    try:
        if data == "files_menu":
            cats = await get_categories_with_counts()
            tf = await count_all_files(); tc = await count_all_categories()
            if not cats:
                return await edit_or_send(q, context, T['files_empty'], InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")]]))
            text = T['files_title'] + "\n\n" + T['files_stats'].format(total_files=tf, total_cats=tc)
            await edit_or_send(q, context, text, kb_files_menu(cats))

        elif data.startswith("files_cat_"):
            p = data.replace("files_cat_", "").split("_")
            cat_id = int(p[0]); page = int(p[1]) if len(p) > 1 else 0
            cat = await get_category_by_id(cat_id)
            if not cat: return await q.answer("❌", show_alert=True)
            total = await count_files_in_category(cat_id)
            tp = max(1, (total + FILES_PER_PAGE - 1) // FILES_PER_PAGE)
            page = max(0, min(page, tp - 1))
            files = await get_files_by_category_paginated(cat_id, page)
            if not files: return await q.answer(T['files_cat_empty'], show_alert=True)
            text = T['files_cat_title'].format(cat_name=f"{cat['icon']} {cat['name']}", page=page+1, total_pages=tp, count=total)
            await edit_or_send(q, context, text, kb_files_cat(files, cat_id, page, tp))

        elif data.startswith("file_view_"):
            fid = int(data.replace("file_view_", ""))
            fd = await get_file_by_id(fid)
            if not fd: return await q.answer(T['file_not_found'], show_alert=True)
            cat = await get_category_by_id(fd['category_id']) if fd['category_id'] else None
            cn = f"{cat['icon']} {cat['name']}" if cat else "—"
            pr = "🔒 Premium" if fd['is_premium'] else "🆓 Bepul"
            text = T['file_view_title'].format(title=fd['title']) + "\n\n" + T['file_view_info'].format(cat_name=cn, icon=file_type_icon(fd['file_type']), ftype=fd['file_type'], premium=pr)
            await edit_or_send(q, context, text, kb_file_view(fid, fd['category_id'] or 0))

        elif data.startswith("file_dl_"):
            fid = int(data.replace("file_dl_", ""))
            fd = await get_file_by_id(fid)
            if not fd: return await q.answer(T['file_not_found'], show_alert=True)
            if fd['is_premium'] and uid != ADMIN_ID:
                is_p = False
                if db_pool:
                    async with db_pool.acquire() as c:
                        u = await c.fetchrow('SELECT is_premium FROM users WHERE user_id = $1', uid)
                        is_p = u['is_premium'] if u else False
                if not is_p: return await q.answer(T['file_premium_locked'], show_alert=True)
            await q.answer(T['file_sending'])
            ok, err = await safe_send_file(context, chat_id, fd)
            if not ok: await context.bot.send_message(chat_id=chat_id, text=T['file_download_error'], parse_mode='Markdown')

        elif data == "files_search":
            context.user_data['state'] = 'in_file_search'
            await edit_or_send(q, context, T['files_search_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(T['files_back_to_cats'], callback_data="files_menu")]]))

        elif data == "files_recent":
            files = await get_recent_files(10)
            if not files: return await q.answer(T['files_recent_empty'], show_alert=True)
            await edit_or_send(q, context, T['files_recent_title'], kb_search_results(files))

        elif data == "admin_files_menu":
            if uid != ADMIN_ID: return
            cats = await get_categories_with_counts()
            tf = await count_all_files(); tc = await count_all_categories()
            if not cats:
                return await edit_or_send(q, context, T['admin_files_empty'],
                    InlineKeyboardMarkup([[InlineKeyboardButton(T['admin_btn_new_cat'], callback_data="admin_file_new_cat")],
                        [InlineKeyboardButton(T['btn_back'], callback_data="admin_menu")]]))
            text = T['admin_files_title'].format(total_files=tf, total_cats=tc)
            await edit_or_send(q, context, text, kb_admin_files_menu(cats))

        elif data.startswith("admin_files_cat_"):
            if uid != ADMIN_ID: return
            p = data.replace("admin_files_cat_", "").split("_")
            cat_id = int(p[0]); page = int(p[1]) if len(p) > 1 else 0
            cat = await get_category_by_id(cat_id)
            if not cat: return await q.answer("❌", show_alert=True)
            total = await count_files_in_category(cat_id)
            tp = max(1, (total + FILES_PER_PAGE - 1) // FILES_PER_PAGE)
            page = max(0, min(page, tp - 1))
            files = await get_files_by_category_paginated(cat_id, page)
            text = T['admin_files_cat_title'].format(cat_name=f"{cat['icon']} {cat['name']}", page=page+1, total_pages=tp, count=total)
            await edit_or_send(q, context, text, kb_admin_files_cat(files, cat_id, page, tp))

        elif data.startswith("admin_file_view_"):
            if uid != ADMIN_ID: return
            fid = int(data.replace("admin_file_view_", ""))
            fd = await get_file_by_id(fid)
            if not fd: return await q.answer(T['file_not_found'], show_alert=True)
            cat = await get_category_by_id(fd['category_id']) if fd['category_id'] else None
            cn = f"{cat['icon']} {cat['name']}" if cat else "—"
            pr = "🔒 Yoqilgan" if fd['is_premium'] else "🔓 O'chirilgan"
            text = T['admin_file_view_title'].format(title=fd['title']) + "\n\n" + T['admin_file_view_info'].format(cat_name=cn, icon=file_type_icon(fd['file_type']), ftype=fd['file_type'], premium=pr, fid=fid)
            await edit_or_send(q, context, text, kb_admin_file_view(fid, fd['is_premium'], fd['category_id'] or 0))

        elif data.startswith("admin_file_edit_"):
            if uid != ADMIN_ID: return
            fid = int(data.replace("admin_file_edit_", ""))
            fd = await get_file_by_id(fid)
            if not fd: return await q.answer("❌", show_alert=True)
            context.user_data['state'] = 'in_file_title_edit'
            context.user_data['edit_file_id'] = fid
            await edit_or_send(q, context, T['admin_edit_title_prompt'].format(old=fd['title']),
                InlineKeyboardMarkup([[InlineKeyboardButton(T['admin_cancel'], callback_data=f"admin_file_view_{fid}")]]))

        elif data.startswith("admin_file_move_do_"):
            if uid != ADMIN_ID: return
            p = data.replace("admin_file_move_do_", "").split("_")
            fid = int(p[0]); nc = int(p[1])
            fd = await get_file_by_id(fid); cat = await get_category_by_id(nc)
            if not fd or not cat: return await q.answer("❌", show_alert=True)
            await move_file_to_category(fid, nc); await q.answer("✅")
            await edit_or_send(q, context, T['admin_file_moved'].format(title=fd['title'], cat_name=f"{cat['icon']} {cat['name']}"),
                InlineKeyboardMarkup([[InlineKeyboardButton(T['admin_btn_back_to_cat'], callback_data=f"admin_files_cat_{nc}_0")]]))

        elif data.startswith("admin_file_move_"):
            if uid != ADMIN_ID: return
            fid = int(data.replace("admin_file_move_", ""))
            fd = await get_file_by_id(fid)
            if not fd: return await q.answer("❌", show_alert=True)
            cats = await get_all_categories()
            if not cats: return await q.answer("Papka yo'q", show_alert=True)
            await edit_or_send(q, context, T['admin_move_prompt'].format(title=fd['title']), kb_admin_move(fid, cats))

        elif data.startswith("admin_file_premium_"):
            if uid != ADMIN_ID: return
            fid = int(data.replace("admin_file_premium_", ""))
            await toggle_file_premium(fid)
            fd = await get_file_by_id(fid)
            if not fd: return await q.answer("❌", show_alert=True)
            msg = T['admin_premium_on'] if fd['is_premium'] else T['admin_premium_off']
            await q.answer(msg, show_alert=True)
            cat = await get_category_by_id(fd['category_id']) if fd['category_id'] else None
            cn = f"{cat['icon']} {cat['name']}" if cat else "—"
            pr = "🔒 Yoqilgan" if fd['is_premium'] else "🔓 O'chirilgan"
            text = T['admin_file_view_title'].format(title=fd['title']) + "\n\n" + T['admin_file_view_info'].format(cat_name=cn, icon=file_type_icon(fd['file_type']), ftype=fd['file_type'], premium=pr, fid=fid)
            await edit_or_send(q, context, text, kb_admin_file_view(fid, fd['is_premium'], fd['category_id'] or 0))

        elif data.startswith("admin_file_del_"):
            if uid != ADMIN_ID: return
            fid = int(data.replace("admin_file_del_", ""))
            fd = await get_file_by_id(fid)
            if not fd: return await q.answer("❌", show_alert=True)
            cat_id = fd['category_id'] or 0
            await delete_file_by_id(fid); await q.answer(T['admin_file_deleted'], show_alert=True)
            cat = await get_category_by_id(cat_id) if cat_id else None
            if cat:
                total = await count_files_in_category(cat_id)
                tp = max(1, (total + FILES_PER_PAGE - 1) // FILES_PER_PAGE)
                files = await get_files_by_category_paginated(cat_id, 0)
                text = T['admin_files_cat_title'].format(cat_name=f"{cat['icon']} {cat['name']}", page=1, total_pages=tp, count=total)
                await edit_or_send(q, context, text, kb_admin_files_cat(files, cat_id, 0, tp))
            else:
                cats = await get_categories_with_counts()
                await edit_or_send(q, context, T['admin_files_title'].format(total_files=await count_all_files(), total_cats=await count_all_categories()), kb_admin_files_menu(cats))

        elif data == "admin_all_files_0" or data.startswith("admin_all_files_"):
            if uid != ADMIN_ID: return
            page = 0 if data == "admin_all_files_0" else int(data.replace("admin_all_files_", ""))
            total = await count_all_files()
            if total == 0: return await q.answer("📭 Fayllar yo'q", show_alert=True)
            tp = max(1, (total + FILES_PER_PAGE - 1) // FILES_PER_PAGE)
            page = max(0, min(page, tp - 1))
            async with db_pool.acquire() as c:
                files = await c.fetch('SELECT id, title, is_premium, file_type FROM files ORDER BY id DESC LIMIT $1 OFFSET $2', FILES_PER_PAGE, page*FILES_PER_PAGE)
            text = T['admin_all_files_title'].format(count=total) + f"\n\n📄 {page+1}/{tp}"
            await edit_or_send(q, context, text, kb_admin_all_files(files, page, tp))

        elif data == "admin_file_new_cat":
            if uid != ADMIN_ID: return
            context.user_data['state'] = 'in_new_cat_name'
            await edit_or_send(q, context, T['admin_file_new_cat_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="admin_files_menu")]]))

        elif data == "admin_file_delcat_menu":
            if uid != ADMIN_ID: return
            cats = await get_all_categories()
            if not cats: return await q.answer("Papka yo'q", show_alert=True)
            await edit_or_send(q, context, T['admin_file_choose_del'], kb_admin_delcat(cats))

        elif data.startswith("admin_delcat_confirm_"):
            if uid != ADMIN_ID: return
            cat_id = int(data.replace("admin_delcat_confirm_", ""))
            cat = await get_category_by_id(cat_id)
            if not cat: return await q.answer("❌", show_alert=True)
            fc = await count_files_in_category(cat_id)
            text = T['admin_cat_del_confirm'].format(cat_name=f"{cat['icon']} {cat['name']}", count=fc)
            await edit_or_send(q, context, text, InlineKeyboardMarkup([
                [InlineKeyboardButton(T['admin_delete_yes'], callback_data=f"admin_delcat_final_{cat_id}")],
                [InlineKeyboardButton(T['admin_cancel'], callback_data="admin_files_menu")]]))

        elif data.startswith("admin_delcat_final_"):
            if uid != ADMIN_ID: return
            cat_id = int(data.replace("admin_delcat_final_", ""))
            await delete_category(cat_id); await ensure_default_categories()
            await q.answer("✅", show_alert=True)
            cats = await get_categories_with_counts()
            text = T['admin_cat_deleted'] + "\n\n" + T['admin_files_title'].format(total_files=await count_all_files(), total_cats=await count_all_categories())
            await edit_or_send(q, context, text, kb_admin_files_menu(cats))

        elif data.startswith("admin_file_cat_"):
            if uid != ADMIN_ID: return
            cat_id = int(data.replace("admin_file_cat_", ""))
            cat = await get_category_by_id(cat_id)
            if not cat: return await q.answer("❌", show_alert=True)
            context.user_data['selected_category'] = cat_id
            context.user_data['selected_category_name'] = f"{cat['icon']} {cat['name']}"
            context.user_data['state'] = 'in_add_file'
            await edit_or_send(q, context, T['admin_file_send_to'].format(cat_name=f"{cat['icon']} {cat['name']}"),
                InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="admin_files_menu")]]))

        elif data == "premium_menu":
            await edit_or_send(q, context, T['premium_menu'], kb_premium())
        elif data == "buy_premium":
            try:
                await context.bot.send_invoice(chat_id=chat_id, title="Premium (1 oy)", description="Cheksiz AI va Premium fayllar.",
                    payload="premium_sub_payload", provider_token="", currency="XTR", prices=[LabeledPrice("Premium", 50)], start_parameter="premium-sub")
            except Exception as e:
                logging.error(f"To'lov: {e}"); await q.answer("❌ To'lov xatosi!", show_alert=True)

        elif data == "challenge_start":
            p = await get_user_profile(uid)
            if p and p['last_challenge_date'] == datetime.date.today() and uid != ADMIN_ID:
                return await q.answer(T['challenge_already_done'], show_alert=True)
            ch = random.choice(CHALLENGES_DATA)
            context.user_data['current_challenge'] = ch['text']
            context.user_data['state'] = 'in_challenge'
            await edit_or_send(q, context, T['challenge_problem'].format(text=ch['text']),
                InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")]]))

        elif data == "theme_menu":
            await edit_or_send(q, context, T['theme_menu'], kb_theme())
        elif data.startswith("theme_apply_"):
            tk = data.replace("theme_apply_", "")
            th = THEMES_DATA.get(tk)
            if not th: return
            content = f"background={th['bg']}\nforeground={th['fg']}\ncursor={th['cursor']}\ncolor0={th['bg']}\ncolor8=#555555\ncolor1=#ff0000\ncolor9=#ff5555\ncolor2=#00ff00\ncolor10=#55ff55\ncolor3=#ffff00\ncolor11=#ffff55\ncolor4=#0000ff\ncolor12=#5555ff\ncolor5=#ff00ff\ncolor13=#ff55ff\ncolor6=#00ffff\ncolor14=#55ffff\ncolor7={th['fg']}\ncolor15=#ffffff\n"
            f = BytesIO(content.encode()); f.name = "colors.properties"
            await context.bot.send_document(chat_id=chat_id, document=f, caption=T['theme_send'].format(theme_name=th['name']), parse_mode='Markdown')

        elif data == "java_info":
            await edit_or_send(q, context, T['java_info_text'], InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")]]))

        elif data == "script_menu":
            await edit_or_send(q, context, T['script_cat_menu'], kb_script_cats())
        elif data.startswith("script_cat_"):
            ck = data.replace("script_cat_", "")
            if 'selected_scripts' not in context.user_data: context.user_data['selected_scripts'] = []
            await edit_or_send(q, context, T['script_items_menu'].format(cat_name=SCRIPTS_DATA[ck]['name']), kb_script_items(ck, context.user_data['selected_scripts']))
        elif data.startswith("script_toggle_"):
            parts = data.replace("script_toggle_", "").split("_", 1)
            ck, ik = parts[0], parts[1]
            sid = f"{ck}_{ik}"
            sel = context.user_data.get('selected_scripts', [])
            if sid in sel: sel.remove(sid)
            else: sel.append(sid)
            context.user_data['selected_scripts'] = sel
            try: await q.edit_message_reply_markup(reply_markup=kb_script_items(ck, sel))
            except: await edit_or_send(q, context, T['script_items_menu'].format(cat_name=SCRIPTS_DATA[ck]['name']), kb_script_items(ck, sel))
        elif data == "script_clear":
            context.user_data['selected_scripts'] = []
            await q.answer("🗑")
            await edit_or_send(q, context, T['script_cat_menu'], kb_script_cats())
        elif data == "script_generate":
            sel = context.user_data.get('selected_scripts', [])
            if not sel: return await q.answer(T['script_empty'], show_alert=True)
            content = "#!/data/data/com.termux/files/usr/bin/bash\n\necho \"🚀 O'rnatish...\"\npkg update -y && pkg upgrade -y\n"
            pkgs, pips, customs = [], [], []
            for sid in sel:
                ck, ik = sid.split("_", 1)
                it = SCRIPTS_DATA[ck]['items'][ik]
                if it['type'] == 'pkg' and it['pkg'] not in pkgs: pkgs.append(it['pkg'])
                elif it['type'] == 'pip' and it['pkg'] not in pips: pips.append(it['pkg'])
                elif it['type'] == 'custom': customs.append(it['pkg'])
            if pkgs: content += f"pkg install -y {' '.join(pkgs)}\n"
            for c in customs: content += f"{c}\n"
            if pips:
                content += "pip install --upgrade pip || true\n"
                content += f"pip install {' '.join(pips)}\n"
            content += "echo \"✅ TAYYOR!\"\n"
            f = BytesIO(content.encode()); f.name = "install.sh"
            await context.bot.send_document(chat_id=chat_id, document=f, caption=T['script_done'], parse_mode='Markdown')
            context.user_data['selected_scripts'] = []

        elif data == "admin_stats":
            if uid != ADMIN_ID: return
            if not db_pool: return await q.answer("Baza yo'q", show_alert=True)
            async with db_pool.acquire() as c:
                t1 = await c.fetchval('SELECT COUNT(*) FROM users')
                t2 = await c.fetchval('SELECT COUNT(*) FROM users WHERE is_premium = TRUE')
                t3 = await c.fetchval('SELECT MAX(score) FROM users')
                t4 = await c.fetchval('SELECT COUNT(*) FROM files')
                t5 = await c.fetchval('SELECT COUNT(*) FROM file_categories')
            await edit_or_send(q, context, f"📊 **Stat**\n\n👥 {t1}\n💎 {t2}\n🏆 {t3 or 0}\n📂 {t5}\n📄 {t4}",
                InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="admin_menu")]]))
        elif data == "admin_update":
            if uid != ADMIN_ID: return
            context.user_data['state'] = 'in_admin_update'
            await edit_or_send(q, context, T['admin_update_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="admin_menu")]]))
        elif data == "admin_toggle_autofwd":
            if uid != ADMIN_ID: return
            cur = await get_setting('auto_forward', 'off')
            nv = 'on' if cur == 'off' else 'off'
            await set_setting('auto_forward', nv)
            msg = T['admin_toggle_on'] if nv == 'on' else T['admin_toggle_off']
            await q.answer("✅")
            await edit_or_send(q, context, msg, InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="admin_menu")]]))
        elif data == "admin_points":
            if uid != ADMIN_ID: return
            context.user_data['state'] = 'in_admin_points'
            await edit_or_send(q, context, T['admin_points_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="admin_menu")]]))
        elif data == "admin_bcast":
            if uid != ADMIN_ID: return
            context.user_data['state'] = 'in_broadcast'
            await edit_or_send(q, context, T['admin_bcast_start'], InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="admin_menu")]]))
        elif data == "admin_menu":
            if uid != ADMIN_ID: return
            af = await get_setting('auto_forward', 'off')
            await edit_or_send(q, context, T['admin_panel'], kb_admin(af))
        elif data == "admin_close":
            if uid != ADMIN_ID: return
            await q.message.delete()

        elif data.startswith("lang_"):
            lang = data.split("_")[1]
            context.user_data['lang'] = lang
            await add_user(uid, lang)
            await edit_or_send(q, context, T['welcome'], kb_main(uid))
        elif data == "change_lang":
            context.user_data.pop('lang', None)
            await edit_or_send(q, context, T['choose_lang'], kb_lang())
        elif data == "updates_menu":
            ups = await get_recent_updates(5)
            if not ups: text = T['updates_empty']
            else:
                text = T['updates_menu'] + "\n"
                for u in ups:
                    text += f"**{u['created_at'].strftime('%d.%m.%Y')}**\n{u['description']}\n\n"
            await edit_or_send(q, context, text, InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")]]))
        elif data == "my_profile":
            p = await get_user_profile(uid)
            if not p: return await q.answer("Xatolik")
            lvl = get_level(p['score'])
            st = "💎 Premium" if p['is_premium'] else "🆓 Bepul"
            text = T['profile_text'].format(score=p['score'], level=lvl, rank=p['rank'], status=st)
            text += f"\n🔥 Streak: {p.get('streak_days', 0)} kun"
            await edit_or_send(q, context, text, kb_profile())
        elif data == "daily_bonus":
            ok, sd, rw, reset, done = await claim_streak(uid)
            if done: return await q.answer(T['streak_already'], show_alert=True)
            if not ok: return await q.answer("❌", show_alert=True)
            extra = ""
            if sd == 7: extra = T['streak_7_bonus']
            elif sd == 30: extra = T['streak_30_bonus']
            elif reset: extra = T['streak_reset_info']
            await q.answer(f"🔥 +{rw} (Kun: {sd})", show_alert=True)
            p = await get_user_profile(uid)
            lvl = get_level(p['score']); st = "💎 Premium" if p['is_premium'] else "🆓 Bepul"
            text = T['profile_text'].format(score=p['score'], level=lvl, rank=p['rank'], status=st)
            text += f"\n🔥 Streak: {sd} kun\n🎁 +{rw} ball"
            if extra: text += f"\n\n{extra}"
            await edit_or_send(q, context, text, kb_profile())
        elif data == "top_users":
            tu = await get_top_users(); tl = ""
            for i, u in enumerate(tu):
                m = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "🔹"
                tl += f"{m} {i+1}. ID: `{u['user_id']}` — **{u['score']}**\n"
            if not tl: tl = "..."
            await edit_or_send(q, context, T['top_text'].format(list=tl), InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")]]))

        elif data == "quiz_start":
            if 'seen_questions' not in context.user_data: context.user_data['seen_questions'] = []
            if len(context.user_data['seen_questions']) >= len(QUIZ_DATA):
                context.user_data['seen_questions'] = []
                await q.message.reply_text(T['quiz_end'])
            avail = [i for i in range(len(QUIZ_DATA)) if i not in context.user_data['seen_questions']]
            chosen = random.choice(avail)
            context.user_data['seen_questions'].append(chosen)
            context.user_data['current_quiz'] = QUIZ_DATA[chosen]
            qz = QUIZ_DATA[chosen]
            await edit_or_send(q, context, T['quiz_start'] + f"\n\n❓ **{qz['q']}**", kb_quiz(qz['options']))
        elif data.startswith("quiz_ans_"):
            ans = data.replace("quiz_ans_", "")
            qz = context.user_data.get('current_quiz')
            if not qz: return await q.answer("❌")
            context.user_data['current_quiz'] = None
            if ans == qz['answer']:
                text = T['quiz_correct']; await add_score(uid, 10)
            else: text = T['quiz_wrong'].format(answer=qz['answer'])
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_next_quiz'], callback_data="quiz_start")], [InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")]])
            await edit_or_send(q, context, text, kb)

        elif data == "ai_start":
            ok, lim = await check_ai_limit(uid)
            if not ok:
                return await edit_or_send(q, context, T['ai_limit_reached'],
                    InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_go_premium'], callback_data="premium_menu")], [InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")]]))
            context.user_data['state'] = 'in_ai'
            pt = T['ai_prompt']
            if lim < 999: pt += "\n\n" + T['ai_limit_info'].format(limit=lim)
            await edit_or_send(q, context, pt, InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")]]))

        elif data == "sec_start":
            await edit_or_send(q, context, T['sec_menu'], kb_sec())
        elif data == "sec_cat_info":
            await edit_or_send(q, context, T['sec_info_text'], InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back_cheat'], callback_data="sec_start")]]))
        elif data == "sec_cat_pass":
            await edit_or_send(q, context, T['sec_pass_text'], InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back_cheat'], callback_data="sec_start")]]))
        elif data == "sec_cat_exploit":
            await edit_or_send(q, context, T['sec_exploit_text'], InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back_cheat'], callback_data="sec_start")]]))
        elif data == "sec_cat_network":
            await edit_or_send(q, context, T['sec_network_text'], InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back_cheat'], callback_data="sec_start")]]))

        elif data == "support_start":
            context.user_data['state'] = 'in_support'
            await edit_or_send(q, context, T['support_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")]]))

        elif data == "send_apk":
            msg = await context.bot.send_message(chat_id=chat_id, text=T['apk_loading'])
            await q.message.delete()
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(TERMUX_APK_URL) as r:
                        if r.status == 200:
                            apk = await r.read()
                            if len(apk) > 50*1024*1024: await msg.edit_text(T['apk_too_big'])
                            else:
                                f = BytesIO(apk); f.name = T['apk_file_name']
                                await context.bot.send_document(chat_id=chat_id, document=f, caption=T['apk_caption'], parse_mode='Markdown',
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")]]))
                                await msg.delete()
                        else: raise Exception()
            except: await msg.edit_text(T['apk_error'])

        elif data == "daily_tip":
            await edit_or_send(q, context, T['tip_header'] + random.choice(TIPS), InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")]]))
        elif data == "cheatsheet":
            await edit_or_send(q, context, T['cheatsheet_menu'], kb_cheatsheet())
        elif data.startswith("cat_"):
            cat = data.split("_")[1]
            cmds = COMMANDS_DATA.get(cat, [])
            text = f"**{T['cat_'+cat]}**\n\n"
            for cmd, desc in cmds: text += f"• `{cmd}` — {desc}\n"
            await edit_or_send(q, context, text, InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back_cheat'], callback_data="cheatsheet")], [InlineKeyboardButton(T['btn_back'], callback_data="back_to_start")]]))

        elif data.startswith("page_"):
            page = int(data.split("_")[1])
            ml = await get_max_lesson_number(); tp = (ml + 9) // 10
            await edit_or_send(q, context, T['text_page'].format(page=page, total=tp), kb_lessons(page, ml))

        elif data.startswith("lesson_"):
            ln = int(data.split("_")[1])
            al = await get_all_lessons(); mid = al.get(ln, ln + 2)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_lessons_menu'], callback_data="page_1")]])
            try:
                await context.bot.copy_message(chat_id=chat_id, from_chat_id=VIDEO_CHANNEL, message_id=mid, reply_markup=kb)
                await q.message.delete()
            except TelegramError as e:
                logging.error(f"Video xato {mid}: {e}")
                await context.bot.send_message(chat_id=chat_id, text=T['text_error_vid'], parse_mode='Markdown')

        elif data == "lua_page_1":
            await edit_or_send(q, context, T['text_lua'], kb_lua_lessons())
        elif data.startswith("lua_lesson_"):
            ln = int(data.split("_")[2]); mid = LUA_LESSONS.get(ln, 93)
            btns = []
            if ln == 8: btns.append([InlineKeyboardButton(T['btn_python'], callback_data="python_extra")])
            btns.append([InlineKeyboardButton(T['btn_lessons_menu'], callback_data="lua_page_1")])
            try:
                await context.bot.copy_message(chat_id=chat_id, from_chat_id=VIDEO_CHANNEL, message_id=mid, reply_markup=InlineKeyboardMarkup(btns))
                await q.message.delete()
            except TelegramError as e:
                logging.error(f"Lua xato: {e}")
                await context.bot.send_message(chat_id=chat_id, text=T['text_error_vid'], parse_mode='Markdown')
        elif data == "python_extra":
            try:
                for v in PYTHON_EXTRA_VIDEOS:
                    await context.bot.copy_message(chat_id=chat_id, from_chat_id=VIDEO_CHANNEL, message_id=v)
                await context.bot.send_message(chat_id=chat_id, text=T['text_python_done'],
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="lua_page_1")]]))
            except TelegramError as e: logging.error(f"Py: {e}")
        elif data == "back_to_start":
            context.user_data['state'] = None
            await edit_or_send(q, context, T['welcome'], kb_main(uid))

        elif data == "devtools_menu":
            await edit_or_send(q, context, T['devtools_menu'], kb_devtools())
        elif data == "dev_pass":
            context.user_data['state'] = 'in_dev_pass'
            await edit_or_send(q, context, T['devtools_pass_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="devtools_menu")]]))
        elif data == "dev_hash":
            context.user_data['state'] = 'in_dev_hash'
            await edit_or_send(q, context, T['devtools_hash_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="devtools_menu")]]))
        elif data == "dev_b64enc":
            context.user_data['state'] = 'in_dev_b64enc'
            await edit_or_send(q, context, T['devtools_b64enc_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="devtools_menu")]]))
        elif data == "dev_b64dec":
            context.user_data['state'] = 'in_dev_b64dec'
            await edit_or_send(q, context, T['devtools_b64dec_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="devtools_menu")]]))
        elif data == "dev_uuid":
            nu = str(uuid.uuid4())
            await edit_or_send(q, context, f"🆔 **UUID v4:**\n\n`{nu}`",
                InlineKeyboardMarkup([[InlineKeyboardButton("🔄", callback_data="dev_uuid")], [InlineKeyboardButton(T['btn_back'], callback_data="devtools_menu")]]))
        elif data == "dev_qr":
            context.user_data['state'] = 'in_dev_qr'
            await edit_or_send(q, context, T['devtools_qr_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="devtools_menu")]]))
        elif data == "dev_json":
            context.user_data['state'] = 'in_dev_json'
            await edit_or_send(q, context, T['devtools_json_prompt'], InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="devtools_menu")]]))

        elif data.startswith("get_attach_"):
            ln = int(data.replace("get_attach_", ""))
            if not db_pool: return await q.answer("❌", show_alert=True)
            async with db_pool.acquire() as c:
                at = await c.fetchrow('SELECT * FROM video_attachments WHERE lesson_number = $1', ln)
            if not at: return await q.answer("❌", show_alert=True)
            await q.answer("⏳")
            fd = {'file_type': at['file_type'], 'file_id': at['file_id'], 'title': at['file_name']}
            await safe_send_file(context, uid, fd)
    except Exception as e:
        logging.error(f"callback xato {data}: {e}")
        try: await q.answer(f"❌ {str(e)[:50]}", show_alert=True)
        except: pass

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.pre_checkout_query
    await q.answer(ok=(q.invoice_payload == "premium_sub_payload"), error_message="Xatolik")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    p = update.message.successful_payment
    if p.invoice_payload == "premium_sub_payload":
        await make_premium(uid)
        await update.message.reply_text(T['premium_success'], parse_mode='Markdown', reply_markup=kb_main(uid))

async def handle_ai_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_subscribed(uid, context):
        await update.message.reply_text(T['force_sub_text'], reply_markup=kb_sub(), parse_mode='Markdown'); return
    if not any([openrouter_client, mistral_client, groq_client, gemini_client]):
        await update.message.reply_text("❌ AI sozlanmagan."); return
    msg = await update.message.reply_text(T['ai_wait'])
    try:
        uq, img, is_img = "", None, False
        if update.message.text:
            uq = update.message.text
            if len(uq) < 15 and uq.lower() in ['salom', 'assalom', 'hi', 'hello']:
                await msg.edit_text(T['ai_not_coding']); return
            if len(uq) > 80000: await msg.edit_text(T['ai_text_too_long']); return
        elif update.message.photo:
            f = await update.message.photo[-1].get_file(); img = await f.download_as_bytearray()
            is_img = True; uq = "Fix this code error from image."
        elif update.message.document:
            d = update.message.document
            if d.file_size > 500*1024: await msg.edit_text(T['ai_file_too_large']); return
            if d.file_name.endswith(('.py', '.lua', '.txt', '.js', '.cpp', '.c', '.html', '.java')):
                content = await (await d.get_file()).download_as_bytearray()
                try:
                    tc = content.decode('utf-8')
                    if len(tc) > 80000: await msg.edit_text(T['ai_text_too_long']); return
                    uq = f"File: {d.file_name}\n\n{tc}\n\nFix this code."
                except: await msg.edit_text(T['ai_unsupported_file']); return
            else: await msg.edit_text(T['ai_unsupported_file']); return
        else: await msg.edit_text(T['ai_video_error']); return

        reply = ""
        sp = "You are an expert Software Engineer. Write/fix code. Reply in markdown code blocks. Reply in user's language."
        if is_img and gemini_client:
            try:
                r = await gemini_client.aio.models.generate_content(model='gemini-1.5-flash',
                    contents=[types.Part.from_text(text=sp), types.Part.from_bytes(data=img, mime_type='image/jpeg')])
                reply = r.text
            except Exception as e: logging.error(f"GemV: {e}")
        if not reply and openrouter_client and not is_img:
            try:
                r = await openrouter_client.chat.completions.create(model="qwen/qwen-2.5-coder-32b-instruct:free",
                    messages=[{"role":"system","content":sp},{"role":"user","content":uq}], max_tokens=4000)
                reply = r.choices[0].message.content
            except Exception as e: logging.error(f"OR: {e}")
        if not reply and mistral_client and not is_img:
            try:
                r = await mistral_client.chat.completions.create(model="codestral-latest",
                    messages=[{"role":"system","content":sp},{"role":"user","content":uq}], max_tokens=4000)
                reply = r.choices[0].message.content
            except Exception as e: logging.error(f"M: {e}")
        if not reply and groq_client and not is_img:
            try:
                r = await groq_client.chat.completions.create(model="llama-3.3-70b-versatile",
                    messages=[{"role":"system","content":sp},{"role":"user","content":uq}], max_tokens=4000)
                reply = r.choices[0].message.content
            except Exception as e: logging.error(f"G: {e}")
        if not reply and gemini_client and not is_img:
            try:
                r = await gemini_client.aio.models.generate_content(model='gemini-1.5-flash', contents=uq)
                reply = r.text
            except Exception as e: logging.error(f"Gem: {e}")
        if not reply:
            await msg.edit_text(T['ai_error'].format(error="Limit")); return
        cm = re.search(r'```(?:python|py|lua|javascript|js|cpp|c|java)?\s*(.*?)```', reply, re.DOTALL | re.IGNORECASE)
        if cm:
            ct = cm.group(1).strip()
            if "lua" in uq.lower(): fn = "code.lua"; ln = "Lua"
            elif "java" in uq.lower(): fn = "Main.java"; ln = "Java"
            else: fn = "code.py"; ln = "Python"
            cf = BytesIO(ct.encode()); cf.name = fn
            await context.bot.send_document(chat_id=update.message.chat_id, document=cf, caption=f"🤖 {ln}: {fn}")
            ex = reply.replace(cm.group(0), "").strip()
            if ex: await context.bot.send_message(chat_id=update.message.chat_id, text=f"📝 {ex}")
            await msg.delete()
        else: await msg.edit_text(T['ai_no_code'].format(text=reply))
    except Exception as e: await msg.edit_text(T['ai_error'].format(error=str(e)[:100]))

async def handle_challenge_solution(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ct = context.user_data.get('current_challenge')
    uc = update.message.text or ((await update.message.document.get_file()).file_id if update.message.document else None)
    if not uc: return await update.message.reply_text(T['challenge_no_code'])
    msg = await update.message.reply_text(T['challenge_wait'])
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
        await add_score(uid, 30); await update_challenge_date(uid)
        context.user_data['state'] = None; context.user_data['current_challenge'] = None
        await msg.edit_text(T['challenge_correct'], parse_mode='Markdown')
    else:
        fb = ai.replace("INCORRECT:", "").strip()
        await msg.edit_text(T['challenge_wrong'].format(feedback=fb), parse_mode='Markdown')

async def handle_new_channel_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.channel_post
    if not m or not m.video: return
    if m.chat.username != VIDEO_CHANNEL.replace('@', ''): return
    if await get_setting('auto_forward', 'off') != 'on': return
    mid = m.message_id
    old = PENDING_VIDEOS.get(mid)
    if old and old.get('timer_task'): old['timer_task'].cancel()
    PENDING_VIDEOS[mid] = {'chat_id': m.chat_id, 'file_id': None, 'file_type': None, 'file_name': None, 'button_text': None, 'caption': m.caption or ""}
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"🎬 **Yangi video!** (ID: `{mid}`)\n\n📎 10 daqiqa ichida fayl yuboring yoki **/done**\n❌ **/cancel_pending** — bekor", parse_mode='Markdown')
    except Exception as e: logging.error(f"Admin msg: {e}")
    task = asyncio.create_task(_auto_finalize_after_timeout(context, mid))
    PENDING_VIDEOS[mid]['timer_task'] = task

async def _auto_finalize_after_timeout(context, mid):
    try:
        await asyncio.sleep(AUTO_ADD_TIMEOUT)
        if mid in PENDING_VIDEOS: await finalize_video_broadcast(context, mid, reason="timeout")
    except asyncio.CancelledError: pass

async def finalize_video_broadcast(context, mid, reason="manual"):
    data = PENDING_VIDEOS.pop(mid, None)
    if not data: return
    if data.get('timer_task'):
        try: data['timer_task'].cancel()
        except: pass
    if not db_pool: return
    async with db_pool.acquire() as c:
        mx = await c.fetchval('SELECT MAX(lesson_number) FROM auto_lessons')
        nn = (mx + 1) if mx else 48
        await c.execute('INSERT INTO auto_lessons (lesson_number, message_id) VALUES ($1, $2) ON CONFLICT (lesson_number) DO NOTHING', nn, mid)
        if data['file_id']:
            bt = data.get('button_text') or get_file_button_info(data['file_name'], data['file_type'])
            await c.execute('INSERT INTO video_attachments (lesson_number, file_id, file_type, file_name, button_text) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (lesson_number) DO UPDATE SET file_id = EXCLUDED.file_id, file_type = EXCLUDED.file_type, file_name = EXCLUDED.file_name, button_text = EXCLUDED.button_text', nn, data['file_id'], data['file_type'], data['file_name'], bt)
        users = await c.fetch('SELECT user_id FROM users')
    rm = None
    if data['file_id']:
        bt = data.get('button_text') or get_file_button_info(data['file_name'], data['file_type'])
        rm = InlineKeyboardMarkup([[InlineKeyboardButton(bt, callback_data=f"get_attach_{nn}")]])
        try: await context.bot.edit_message_reply_markup(chat_id=data['chat_id'], message_id=mid, reply_markup=rm)
        except: pass
    s, f = 0, 0
    for u in users:
        if u['user_id'] == ADMIN_ID: continue
        try:
            await context.bot.copy_message(chat_id=u['user_id'], from_chat_id=data['chat_id'], message_id=mid, reply_markup=rm)
            s += 1; await asyncio.sleep(0.05)
        except: f += 1
    fi = f"📎 `{data['file_name']}`" if data['file_id'] else "Fayl yo'q"
    rt = "⏱️ 10 daqiqa" if reason == "timeout" else "✅ /done"
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"✅ **{nn}-darslik tarqatildi!**\n\n{rt}\n{fi}\n📩 {s}\n❌ {f}", parse_mode='Markdown')
    except: pass

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not PENDING_VIDEOS:
        await update.message.reply_text("ℹ️ Pending yo'q"); return
    cnt = len(PENDING_VIDEOS)
    for mid in list(PENDING_VIDEOS.keys()): await finalize_video_broadcast(context, mid, reason="manual")
    await update.message.reply_text(f"✅ {cnt} ta tarqatildi!", parse_mode='Markdown')

async def cancel_pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not PENDING_VIDEOS:
        await update.message.reply_text("ℹ️ Pending yo'q"); return
    cnt = len(PENDING_VIDEOS)
    for mid, d in list(PENDING_VIDEOS.items()):
        if d.get('timer_task'):
            try: d['timer_task'].cancel()
            except: pass
    PENDING_VIDEOS.clear()
    await update.message.reply_text(f"❌ {cnt} ta bekor", parse_mode='Markdown')

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    af = await get_setting('auto_forward', 'off')
    await update.message.reply_text(T['admin_panel'], reply_markup=kb_admin(af), parse_mode='Markdown')

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    st = context.user_data.get('state')

    if st == 'in_file_search':
        if update.message.text == "/cancel":
            context.user_data['state'] = None
            await update.message.reply_text(T['admin_cancel'], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(T['files_back_to_cats'], callback_data="files_menu")]]))
            return
        if update.message.text:
            q = update.message.text.strip()[:100]
            try:
                results = await search_files(q)
                context.user_data['state'] = None
                if not results:
                    await update.message.reply_text(T['files_search_empty'].format(query=q),
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(T['files_back_to_cats'], callback_data="files_menu")]]), parse_mode='Markdown')
                    return
                await update.message.reply_text(T['files_search_results'].format(query=q, count=len(results)),
                    reply_markup=kb_search_results(results), parse_mode='Markdown')
            except Exception as e:
                logging.error(f"Search: {e}"); context.user_data['state'] = None
        return

    if user.id == ADMIN_ID and st == 'in_file_title_edit':
        if update.message.text == "/cancel":
            fid = context.user_data.get('edit_file_id')
            context.user_data['state'] = None; context.user_data.pop('edit_file_id', None)
            await update.message.reply_text(T['admin_cancel'])
            if fid:
                fd = await get_file_by_id(fid)
                if fd:
                    cat = await get_category_by_id(fd['category_id']) if fd['category_id'] else None
                    cn = f"{cat['icon']} {cat['name']}" if cat else "—"
                    pr = "🔒 Yoqilgan" if fd['is_premium'] else "🔓 O'chirilgan"
                    text = T['admin_file_view_title'].format(title=fd['title']) + "\n\n" + T['admin_file_view_info'].format(cat_name=cn, icon=file_type_icon(fd['file_type']), ftype=fd['file_type'], premium=pr, fid=fid)
                    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=kb_admin_file_view(fid, fd['is_premium'], fd['category_id'] or 0))
            return
        if update.message.text:
            fid = context.user_data.get('edit_file_id')
            nt = update.message.text.strip()[:255]
            if not fid or not nt:
                context.user_data['state'] = None; return await update.message.reply_text("❌")
            await update_file_title(fid, nt)
            context.user_data['state'] = None; context.user_data.pop('edit_file_id', None)
            fd = await get_file_by_id(fid)
            if fd:
                cat = await get_category_by_id(fd['category_id']) if fd['category_id'] else None
                cn = f"{cat['icon']} {cat['name']}" if cat else "—"
                pr = "🔒 Yoqilgan" if fd['is_premium'] else "🔓 O'chirilgan"
                text = T['admin_file_view_title'].format(title=fd['title']) + "\n\n" + T['admin_file_view_info'].format(cat_name=cn, icon=file_type_icon(fd['file_type']), ftype=fd['file_type'], premium=pr, fid=fid)
                await update.message.reply_text(text, parse_mode='Markdown', reply_markup=kb_admin_file_view(fid, fd['is_premium'], fd['category_id'] or 0))
        return

    if user.id == ADMIN_ID and PENDING_VIDEOS:
        if update.message.document or update.message.video or update.message.photo or update.message.audio:
            lid = list(PENDING_VIDEOS.keys())[-1]
            fid, ft, fn = None, None, None
            if update.message.document: fid = update.message.document.file_id; ft = 'document'; fn = update.message.document.file_name or "file"
            elif update.message.video: fid = update.message.video.file_id; ft = 'video'; fn = update.message.video.file_name or "video.mp4"
            elif update.message.photo: fid = update.message.photo[-1].file_id; ft = 'photo'; fn = "photo.jpg"
            elif update.message.audio: fid = update.message.audio.file_id; ft = 'audio'; fn = update.message.audio.file_name or "audio.mp3"
            if fid:
                PENDING_VIDEOS[lid]['file_id'] = fid; PENDING_VIDEOS[lid]['file_type'] = ft; PENDING_VIDEOS[lid]['file_name'] = fn
                if update.message.caption: PENDING_VIDEOS[lid]['button_text'] = update.message.caption.strip()[:80]
                btn = PENDING_VIDEOS[lid]['button_text'] or get_file_button_info(fn, ft)
                await update.message.reply_text(f"✅ **Biriktirildi!**\n\n📎 `{fn}`\n🔘 **{btn}**\n\n**/done** yoki 10 daqiqa", parse_mode='Markdown')
                return

    if user.id == ADMIN_ID and st == 'in_new_cat_name':
        if update.message.text == "/cancel":
            context.user_data['state'] = None
            await update.message.reply_text(T['admin_file_cancel']); return
        if update.message.text:
            cn = update.message.text.strip()[:100]
            nid = await add_category(cn, icon='📁')
            if nid:
                context.user_data['selected_category'] = nid
                context.user_data['selected_category_name'] = f"📁 {cn}"
                context.user_data['state'] = 'in_add_file'
                text = T['admin_file_cat_created'].format(name=cn) + "\n\n" + T['admin_file_send_to'].format(cat_name=f"📁 {cn}")
                await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="admin_files_menu")]]))
            else:
                await update.message.reply_text("❌"); context.user_data['state'] = None
        return

    if user.id == ADMIN_ID and st == 'in_add_file':
        if update.message.text == "/cancel":
            context.user_data['state'] = None
            context.user_data.pop('selected_category', None)
            context.user_data.pop('selected_category_name', None)
            await update.message.reply_text(T['admin_file_cancel']); return
        if update.message.document or update.message.video or update.message.photo or update.message.audio:
            if update.message.document: fid = update.message.document.file_id; ft = 'document'
            elif update.message.video: fid = update.message.video.file_id; ft = 'video'
            elif update.message.audio: fid = update.message.audio.file_id; ft = 'audio'
            else: fid = update.message.photo[-1].file_id; ft = 'photo'
            context.user_data['temp_file_id'] = fid
            context.user_data['temp_file_type'] = ft
            context.user_data['state'] = 'in_file_title'
            cn = context.user_data.get('selected_category_name', '📁 Papka')
            await update.message.reply_text(f"📎 Qabul!\n\n{cn}\n\n" + T['admin_file_title_prompt'], parse_mode='Markdown')
        else: await update.message.reply_text("⚠️ Fayl yuboring yoki /cancel")
        return

    if user.id == ADMIN_ID and st == 'in_file_title':
        if update.message.text == "/cancel":
            context.user_data['state'] = None
            context.user_data.pop('selected_category', None)
            context.user_data.pop('selected_category_name', None)
            await update.message.reply_text(T['admin_file_cancel']); return
        if update.message.text:
            title = update.message.text.strip()[:255]
            fid = context.user_data.get('temp_file_id'); ft = context.user_data.get('temp_file_type')
            cid = context.user_data.get('selected_category'); cn = context.user_data.get('selected_category_name', 'Papka')
            await add_file_db_cat(title, fid, ft, cid, is_prem=False)
            context.user_data['state'] = None
            for k in ['selected_category', 'selected_category_name', 'temp_file_id', 'temp_file_type']: context.user_data.pop(k, None)
            total = await count_files_in_category(cid)
            tp = max(1, (total + FILES_PER_PAGE - 1) // FILES_PER_PAGE)
            files = await get_files_by_category_paginated(cid, 0)
            text = f"✅ **Saqlandi!**\n\n📂 {cn}\n📄 **{title}**\n\n📊 Jami: **{total}** ta"
            await update.message.reply_text(text, parse_mode='Markdown', reply_markup=kb_admin_files_cat(files, cid, 0, tp))
        return

    if st == 'in_dev_pass':
        context.user_data['state'] = None
        if not update.message.text or not update.message.text.strip().isdigit():
            return await update.message.reply_text(T['devtools_invalid'].format(error="Raqam"), parse_mode='Markdown')
        ln = int(update.message.text.strip())
        if ln < 8 or ln > 64: return await update.message.reply_text(T['devtools_invalid'].format(error="8-64"), parse_mode='Markdown')
        pwd = ''.join(secrets.choice(string.ascii_letters + string.digits + "!@#$%^&*") for _ in range(ln))
        st_r = "🟢" if ln >= 16 else "🟡" if ln >= 12 else "🔴"
        return await update.message.reply_text(f"🔐 `{pwd}`\n\n{st_r} {ln}", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄", callback_data="dev_pass")], [InlineKeyboardButton(T['btn_back'], callback_data="devtools_menu")]]))

    if st == 'in_dev_hash':
        context.user_data['state'] = None
        if not update.message.text: return
        t = update.message.text
        r = f"**MD5:** `{hashlib.md5(t.encode()).hexdigest()}`\n**SHA1:** `{hashlib.sha1(t.encode()).hexdigest()}`\n**SHA256:** `{hashlib.sha256(t.encode()).hexdigest()}`\n**SHA512:** `{hashlib.sha512(t.encode()).hexdigest()}`"
        return await update.message.reply_text(r, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="devtools_menu")]]))

    if st == 'in_dev_b64enc':
        context.user_data['state'] = None
        if not update.message.text: return
        e = base64.b64encode(update.message.text.encode()).decode()
        return await update.message.reply_text(f"📝 `{e}`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="devtools_menu")]]))

    if st == 'in_dev_b64dec':
        context.user_data['state'] = None
        if not update.message.text: return
        try:
            d = base64.b64decode(update.message.text.encode()).decode()
            await update.message.reply_text(f"📝 `{d}`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="devtools_menu")]]))
        except: await update.message.reply_text(T['devtools_invalid'].format(error="Base64"), parse_mode='Markdown')
        return

    if st == 'in_dev_qr':
        context.user_data['state'] = None
        if not update.message.text: return
        u = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={quote(update.message.text)}"
        try:
            await update.message.reply_photo(photo=u, caption=f"📱 `{update.message.text[:100]}`", parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="devtools_menu")]]))
        except Exception as e: await update.message.reply_text(str(e)[:50])
        return

    if st == 'in_dev_json':
        context.user_data['state'] = None
        if not update.message.text: return
        try:
            p = json_lib.loads(update.message.text); f = json_lib.dumps(p, indent=2, ensure_ascii=False)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(T['btn_back'], callback_data="devtools_menu")]])
            if len(f) > 3500:
                jf = BytesIO(f.encode()); jf.name = "formatted.json"
                await update.message.reply_document(document=jf, caption="📊", reply_markup=kb)
            else: await update.message.reply_text(f"📊 `{f}`", parse_mode='Markdown', reply_markup=kb)
        except json_lib.JSONDecodeError as e: await update.message.reply_text(str(e)[:80], parse_mode='Markdown')
        return

    if st == 'in_ai': await handle_ai_message(update, context); return
    if st == 'in_challenge': await handle_challenge_solution(update, context); return

    if user.id == ADMIN_ID and st == 'in_admin_points':
        if update.message.text and update.message.text.isdigit():
            pts = int(update.message.text)
            await add_score_all(pts)
            msg = await update.message.reply_text(T['admin_points_wait'])
            s, f = 0, 0
            if db_pool:
                async with db_pool.acquire() as c: us = await c.fetch('SELECT user_id FROM users')
                bc = f"🎁 **Aksiya!** +{pts} ball! 🎉"
                for u in us:
                    if u['user_id'] == ADMIN_ID: continue
                    try:
                        await context.bot.send_message(chat_id=u['user_id'], text=bc, parse_mode='Markdown')
                        s += 1; await asyncio.sleep(0.05)
                    except: f += 1
            await msg.edit_text(T['admin_points_done'].format(points=pts, success=s, fail=f), parse_mode='Markdown')
            context.user_data['state'] = None
        else: await update.message.reply_text("❌ Raqam!")
        return

    if user.id == ADMIN_ID and st == 'in_admin_update':
        if update.message.text == "/cancel":
            context.user_data['state'] = None
            await update.message.reply_text(T['admin_bcast_cancel']); return
        if update.message.text:
            ann = update.message.text
            await add_update_db("Yangilanish", ann)
            msg = await update.message.reply_text(T['admin_update_wait'])
            s, f = 0, 0
            if db_pool:
                async with db_pool.acquire() as c: us = await c.fetch('SELECT user_id FROM users')
                bc = f"📣 **YANGILANISH!**\n\n{ann}"
                for u in us:
                    if u['user_id'] == ADMIN_ID: continue
                    try:
                        await context.bot.send_message(chat_id=u['user_id'], text=bc, parse_mode='Markdown')
                        s += 1; await asyncio.sleep(0.05)
                    except: f += 1
            await msg.edit_text(T['admin_update_done'].format(success=s, fail=f), parse_mode='Markdown')
            context.user_data['state'] = None
        return

    if user.id == ADMIN_ID and st == 'in_broadcast':
        if update.message.text == "/cancel":
            context.user_data['state'] = None
            await update.message.reply_text(T['admin_bcast_cancel']); return
        await process_broadcast(update, context); return

    if st == 'in_support':
        if update.message.text:
            am = f"📩 Murojaat!\n\n👤 {user.first_name} (@{user.username})\n🆔 {user.id}\n\n💬 {update.message.text}"
            try:
                await context.bot.send_message(chat_id=ADMIN_ID, text=am)
                await update.message.reply_text(T['support_sent'], reply_markup=kb_main(user.id))
            except: pass
            context.user_data['state'] = None
        return

    if user.id == ADMIN_ID and update.message.reply_to_message:
        o = update.message.reply_to_message.text or ""
        m = re.search(r'🆔 (\d+)', o)
        if m:
            tgt = int(m.group(1))
            try:
                await context.bot.send_message(chat_id=tgt, text=f"{T['support_reply']}{update.message.text}")
                await update.message.reply_text("✅")
            except Exception as e: await update.message.reply_text(f"❌ {e}")

async def process_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text(T['admin_bcast_wait'])
    if not db_pool: return
    async with db_pool.acquire() as c: us = await c.fetch('SELECT user_id FROM users')
    s, f = 0, 0
    for u in us:
        if u['user_id'] == ADMIN_ID: continue
        try:
            await context.bot.copy_message(chat_id=u['user_id'], from_chat_id=update.message.chat_id, message_id=update.message.message_id)
            s += 1; await asyncio.sleep(0.05)
        except: f += 1
    context.user_data['state'] = None
    await msg.edit_text(f"✅ {s} | ❌ {f}")

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
INDEX_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Bot</title><style>body{margin:0;font-family:sans-serif;background:#0d1117;color:#c9d1d9;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center}h1{background:linear-gradient(135deg,#58a6ff,#bc8cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-size:2.5em}</style></head><body><div><h1>🤖 Bot ishlayapti</h1><p>Termux Bot</p></div></body></html>"""

@app.on_event("startup")
async def on_startup():
    await init_db()
    await application.initialize()
    if RENDER_EXTERNAL_URL:
        try:
            await application.bot.set_webhook(url=f"{RENDER_EXTERNAL_URL}/webhook/{TOKEN}", drop_pending_updates=True)
            print(f"✅ Bot ishga tushdi!")
        except Exception as e: logging.error(f"Webhook: {e}")

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
    except Exception as e: logging.error(f"Webhook xato: {e}")
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
async def read_root(): return HTMLResponse(content=INDEX_HTML)

@app.get("/health")
async def health(): return {"status": "ok"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
