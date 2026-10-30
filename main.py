import os
import logging
import random
import aiohttp
import re
import asyncio
import asyncpg
import base64
from io import BytesIO
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
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
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

ADMIN_ID = 7383782449
CHANNEL_USERNAME = "@Tommy_cheat" 
TERMUX_APK_URL = "https://github.com/termux/termux-app/releases/download/v0.118.0/termux-app_v0.118.0+github-debug_arm64-v8a.apk"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# AI Mijozlari
deepseek_client = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY, 
    base_url="https://api.deepseek.com",
    timeout=300.0 
) if DEEPSEEK_API_KEY else None

gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

db_pool = None

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
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

async def get_all_users():
    if not db_pool: return []
    async with db_pool.acquire() as conn:
        records = await conn.fetch('SELECT user_id FROM users')
        return [r['user_id'] for r in records]

async def get_stats():
    if not db_pool: return 0, {}
    async with db_pool.acquire() as conn:
        total = await conn.fetchval('SELECT COUNT(*) FROM users')
        langs = await conn.fetch('SELECT lang, COUNT(*) as count FROM users GROUP BY lang')
        return total, {r['lang']: r['count'] for r in langs}

# ==========================================
# VIDEOLAR
# ==========================================
LESSONS = {i: i+2 for i in range(1, 46)}
LUA_LESSONS = {1: 93, 2: 94, 3: 97, 4: 98, 5: 99, 6: 100, 7: 101}
PYTHON_EXTRA_VIDEOS = [96]

# ==========================================
# TILLAR LUG'ATI (O'zbekcha qismi, qolganlari oldingidek)
# ==========================================
TEXTS = {
    'uz': {
        'choose_lang': "👋 **Assalomu alaykum!**\n\nIltimos, o'zingizga qulay tilni tanlang:",
        'welcome': "👋 **Assalomu alaykum!**\n\nMen **Termux va Dasturlash** bo'yicha yordamchi botman.",
        'btn_termux': "📽️ TERMUX VIDEO DARSLIKLAR", 'btn_lua': "📽️ TERMUX LUA PAK VIDEO DARSLIK",
        'btn_apk': "📥 TERMUX APK YUKLAB OLISH", 'btn_tip': "💡 Kunlik maslahat",
        'btn_cheatsheet': "📜 Muhim buyruqlar", 'btn_quiz': "🧠 Bilimingizni sinang (Test)",
        'btn_support': "✉️ Adminga murojaat qilish", 'btn_another_tip': "🔄 Yana maslahat",
        'btn_security': "🛡️ Kiberxavfsizlik", 'btn_ai': "🤖 AI Dasturchi (Super)",
        'btn_change_lang': "🌐 Tilni o'zgartirish", 'btn_back': "🔙 Bosh menyu",
        'btn_prev': "⬅️ Oldingi", 'btn_next': "Keyingi ➡️", 'btn_python': "🐍 PYTHON OLISH",
        'btn_lessons_menu': "📚 Darsliklar (Menyu)",
        'text_page': "📚 **Video darsliklar**\n\nSahifa: {page} / 5\nKerakli darslikni tanlang:",
        'text_lua': "📚 **TERMUX LUA PAK DARSLIKLARI**\n\nKerakli darslikni tanlang:",
        'text_python_done': "Mana siz so'ragan Python darsligi! ✅",
        'text_error_vid': "❌ **Xatolik!** Videoni yuklab bo'lmadi.",
        'text_error_py': "❌ **Xatolik!** Python videosini yuklab bo'lmadi.",
        'tip_header': "💡 **Kunlik maslahat:**\n\n",
        'cheatsheet_menu': "📜 **Muhim buyruqlar**\n\nKerakli bo'limni tanlang:",
        'cat_files': "📁 Fayllar bilan ishlash", 'cat_packages': "📦 Paketlar va dasturlar",
        'cat_network': "🌐 Tarmoq va internet", 'cat_system': "⚙️ Tizim va boshqalar",
        'btn_back_cheat': "🔙 Orqaga",
        'apk_caption': "📱 **Termux ilovasi (APK)**\n\n1. Faylni yuklab oling.\n2. Telefoningizga o'rnating.\n3. Darsliklarimizni boshlang! 🚀",
        'apk_file_name': "Termux_Ilovasi.apk", 'apk_loading': "⏳ Iltimos kuting, yuklanmoqda...",
        'apk_too_big': "⚠️ Fayl hajmi katta. Havola orqali yuklab oling:\n[Yuklab olish](https://github.com/termux/termux-app/releases)",
        'apk_error': "❌ **Xatolik!** APK yuklab bo'lmadi.",
        'support_prompt': "✉️ **Adminga murojaat**\n\nSavolingizni bitta xabar qilib yozib qoldiring.",
        'support_sent': "✅ **Xabaringiz yuborildi!**", 'support_reply': "📬 **Admin javobi:**\n\n",
        'quiz_start': "🧠 **Bilimingizni sinab ko'ring!**", 'quiz_correct': "✅ **To'g'ri javob!** 🎉",
        'quiz_wrong': "❌ **Xato!** To'g'ri javob: **{answer}**", 'btn_next_quiz': "➡️ Keyingi savol",
        'sec_menu': "🛡️ **Kiberxavfsizlik Asboblari**\n\n⚠️ Faqat o'z tizimlaringizni tekshirish uchun!",
        'sec_info': "🔍 Ma'lumot yig'ish", 'sec_pass': "🔑 Parol hujumlari",
        'sec_exploit': "💥 Zaifliklar", 'sec_network': "📡 Tarmoq tahlili",
        'sec_info_text': "🔍 **Ma'lumot yig'ish**\n\nNmap: `pkg install nmap`\nWhois: `pkg install whois`",
        'sec_pass_text': "🔑 **Parol hujumlari**\n\nHydra: `pkg install hydra`\nJohn: `pkg install john`",
        'sec_exploit_text': "💥 **Zaifliklar**\n\nSQLmap: `pip install sqlmap`\nMetasploit: `pkg install metasploit`",
        'sec_network_text': "📡 **Tarmoq tahlili**\n\nTshark: `pkg install tshark`\nAircrack: `pkg install aircrack-ng`",
        'admin_bcast_start': "📢 **Ommaviy xabar rejimi.**\n\nBarchaga yubormoqchi bo'lgan xabarni yuboring:",
        'admin_bcast_wait': "⏳ Xabar yuborilmoqda...", 'admin_bcast_done': "✅ **Yakunlandi!**\nYuborildi: {success}\nXatolik: {fail}",
        'admin_bcast_cancel': "❌ Bekor qilindi.",
        'ai_prompt': "🤖 **Super AI Dasturchi (DeepSeek + Gemini)**\n\nMenga savolingizni yozing, kod faylini (.py, .lua) tashlang yoki xatolik chiqqan rasmni yuboring.\n\nMen kodingizni tahlil qilib, xatolarini topaman va tuzatilgan kodni fayl qilib qaytaraman!",
        'ai_wait': "🧠 AI o'ylamoqda va kodingizni tahlil qilmoqda. Iltimos kuting...",
        'ai_error': "❌ **Xatolik!** AI bilan bog'lanishda muammo yuz berdi.",
        'ai_code_found': "✅ **Tuzatilgan kod tayyor!**\n\nMana siz so'ragan kod fayli.",
        'ai_no_code': "🤖 **AI Javobi:**\n\n{text}",
        'ai_vision_error': "⚠️ **Diqqat:** Hozircha AI rasmlarni to'liq tahlil qila olmaydi. Iltimos, rasmdagi kodni matn ko'rinishida nusxalab yuboring yoki kod faylini (.py) tashlang.",
        'ai_unsupported_file': "⚠️ Iltimos, faqat matnli kod fayllarini (.py, .lua, .txt) yuboring. Boshqa fayllarni o'qiy olmayman.",
        'ai_video_error': "🎥 **Videoni tahlil qila olmayman.**\n\nIltimos, videodan xatolik ko'ringan joyni skrinshot (rasm) qilib yuboring yoki xato matnini yozib yuboring.",
        'ai_file_too_large': "⚠️ **Fayl juda katta (500 KB dan oshdi)!**\n\nIltimos, kichikroq fayl yuboring.",
        'ai_text_too_long': "⚠️ **Kod juda uzun!**\n\nSun'iy intellekt bir martada buncha kodni o'qiy olmaydi. Iltimos, faqat xatolik yuz bergan qismini (funksiyani) ajratib yuboring."
    },
    # RU, EN, AR tillari oldingi kod bilan bir xil, joy tejash uchun qisqartirildi. 
    # To'liq kodda ularni ham qo'shishingiz mumkin.
}

TIPS = [{'uz': "**Tezroq kod yozish:**\n`nano` o'rniga `micro` ishlating.", 'ru': "**Быстрое написание:**\nИспользуйте `micro`.", 'en': "**Faster coding:**\nUse `micro`.", 'ar': "**برمجة أسرع:**\nاستخدم `micro`."}]
COMMANDS_DATA = {'files': [('ls', {'uz': 'Fayllar', 'ru': 'Файлы', 'en': 'Files', 'ar': 'ملفات'})], 'packages': [('pkg update', {'uz': 'Yangilash', 'ru': 'Обновить', 'en': 'Update', 'ar': 'تحديث'})], 'network': [('ping google.com', {'uz': 'Tekshirish', 'ru': 'Проверить', 'en': 'Check', 'ar': 'فحص'})], 'system': [('clear', {'uz': 'Tozalash', 'ru': 'Очистить', 'en': 'Clear', 'ar': 'مسح'})]}
QUIZ_DATA = [{'q': {'uz': "Papka yaratish?", 'ru': "Команда для папки?", 'en': "Command for folder?", 'ar': "أمر لإنشاء مجلد؟"}, 'options': ['mkdir', 'cd', 'ls', 'rm'], 'answer': 'mkdir'}]

# ==========================================
# KLAVIATURALAR
# ==========================================
def get_lang_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="lang_uz"), InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")], [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"), InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar")]])

def get_main_menu(lang):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t['btn_termux'], callback_data="page_1")],
        [InlineKeyboardButton(t['btn_lua'], callback_data="lua_page_1")],
        [InlineKeyboardButton(t['btn_apk'], callback_data="send_apk")], 
        [InlineKeyboardButton(t['btn_ai'], callback_data="ai_start")],
        [InlineKeyboardButton(t['btn_quiz'], callback_data="quiz_start")],
        [InlineKeyboardButton(t['btn_security'], callback_data="sec_start")],
        [InlineKeyboardButton(t['btn_support'], callback_data="support_start")],
        [InlineKeyboardButton(t['btn_tip'], callback_data="daily_tip")], 
        [InlineKeyboardButton(t['btn_cheatsheet'], callback_data="cheatsheet")], 
        [InlineKeyboardButton(t['btn_change_lang'], callback_data="change_lang")]
    ])

def get_sec_menu(lang):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([[InlineKeyboardButton(t['sec_info'], callback_data="sec_cat_info")], [InlineKeyboardButton(t['sec_pass'], callback_data="sec_cat_pass")], [InlineKeyboardButton(t['sec_exploit'], callback_data="sec_cat_exploit")], [InlineKeyboardButton(t['sec_network'], callback_data="sec_cat_network")], [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])

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
    keyboard = []
    row = []
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
    keyboard = []
    row = []
    for opt in options:
        row.append(InlineKeyboardButton(opt, callback_data=f"quiz_ans_{opt}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton(t['btn_next_quiz'], callback_data="quiz_start")])
    keyboard.append([InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")])
    return InlineKeyboardMarkup(keyboard)

# ==========================================
# HANDLERLAR
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = context.user_data.get('lang', 'uz')
    await add_user(user_id, lang)
    if 'lang' in context.user_data:
        await update.message.reply_text(TEXTS[lang]['welcome'], reply_markup=get_main_menu(lang), parse_mode='Markdown')
    else:
        await update.message.reply_text(TEXTS['uz']['choose_lang'], reply_markup=get_lang_keyboard(), parse_mode='Markdown')

async def button_tap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    
    if data.startswith("lang_"):
        lang = data.split("_")[1]
        context.user_data['lang'] = lang
        await add_user(user_id, lang)
        await query.edit_message_text(TEXTS[lang]['welcome'], reply_markup=get_main_menu(lang), parse_mode='Markdown')
        return
    elif data == "change_lang":
        context.user_data.pop('lang', None)
        await query.edit_message_text(TEXTS['uz']['choose_lang'], reply_markup=get_lang_keyboard(), parse_mode='Markdown')
        return

    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]

    if data == "ai_start":
        context.user_data['state'] = 'in_ai'
        await query.edit_message_text(t['ai_prompt'], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]), parse_mode='Markdown')
        return
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
        correct_ans = question_data['answer']
        text = t['quiz_correct'] if selected_ans == correct_ans else t['quiz_wrong'].format(answer=correct_ans)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_next_quiz'], callback_data="quiz_start")], [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])
        try: await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='Markdown')
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
                        if len(apk_content) > 50 * 1024 * 1024:
                            await msg.edit_text(t['apk_too_big'], parse_mode='Markdown')
                        else:
                            apk_file = BytesIO(apk_content)
                            apk_file.name = t['apk_file_name']
                            await context.bot.send_document(chat_id=chat_id, document=apk_file, caption=t['apk_caption'], parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]]))
                            await msg.delete()
                    else: raise Exception("HTTP Error")
        except Exception: await msg.edit_text(t['apk_error'])
        return
    elif data == "daily_tip":
        random_tip = random.choice(TIPS)[lang]
        text = t['tip_header'] + random_tip
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_another_tip'], callback_data="daily_tip")], [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])
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
# SUPER AI LOGIKASI (DeepSeek + Gemini)
# ==========================================
async def handle_ai_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not deepseek_client and not gemini_client:
        await update.message.reply_text("❌ AI xizmatlari sozlanmagan.")
        return

    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]
    msg = await update.message.reply_text(t['ai_wait'])

    try:
        user_query = ""
        image_bytes = None
        is_image = False
        file_content = None

        # 1. Matn
        if update.message.text:
            user_query = update.message.text
            if len(user_query) > 80000:
                await msg.edit_text(t['ai_text_too_long'])
                return
        # 2. Rasm
        elif update.message.photo:
            photo_file = await update.message.photo[-1].get_file()
            image_bytes = await photo_file.download_as_bytearray()
            is_image = True
            user_query = "Iltimos, ushbu rasmdagi kod yoki xatoni tahlil qilib, tuzatilgan kodni yozib ber."
        # 3. Fayl
        elif update.message.document:
            doc = update.message.document
            if doc.file_size > 500 * 1024:
                await msg.edit_text(t['ai_file_too_large'])
                return
            if doc.file_name.endswith(('.py', '.lua', '.txt', '.js', '.cpp', '.c', '.html')):
                file_content = await (await doc.get_file()).download_as_bytearray()
                try:
                    text_content = file_content.decode('utf-8')
                    if len(text_content) > 80000:
                        await msg.edit_text(t['ai_text_too_long'])
                        return
                    user_query = f"Fayl nomi: {doc.file_name}\n\nKod:\n{text_content}\n\nIltimos, ushbu kodni tahlil qilib, xatolarini tuzatib, tayyor ishlaydigan holatga keltiring."
                except UnicodeDecodeError:
                    await msg.edit_text(t['ai_unsupported_file'])
                    return
            else:
                await msg.edit_text(t['ai_unsupported_file'])
                return
        else:
            await msg.edit_text(t['ai_video_error'])
            return

        ai_reply = ""

        # --- 1-QADAM: RASM BO'LSA, AVVAL GEMINI (VISION) ISHLATAMIZ ---
        if is_image and gemini_client:
            try:
                # Gemini'ga rasm va matnni yuborish
                response = gemini_client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=[
                        types.Part.from_text(text=user_query),
                        types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg')
                    ]
                )
                ai_reply = response.text
            except Exception as e:
                logging.error(f"Gemini Vision xatosi: {e}")
                # Agar Gemini rasmni o'qiy olmasa, DeepSeek'ga o'tamiz (rasmsiz)
                ai_reply = ""

        # --- 2-QADAM: MATN YOKI KOD BO'LSA (YOKI RASM GEMINI'DA ISHLAMASA), DEEPSEEK ISHLATAMIZ ---
        if not ai_reply and deepseek_client:
            try:
                content = [{"type": "text", "text": user_query}]
                if is_image and image_bytes:
                    # DeepSeek rasmsiz ishlaydi, shuning uchun faqat matn yuboramiz
                    content = [{"type": "text", "text": user_query + "\n\n(Eslatma: Rasm yuborildi, lekin DeepSeek rasmni ko'ra olmaydi. Iltimos, kodni matn ko'rinishida yuboring.)"}]
                
                response = await deepseek_client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": "You are an expert Senior Software Engineer. Analyze the code. Find all bugs. Fix them. Provide the full, working, corrected code. Always wrap the final code in markdown blocks (```python ... ``` or ```lua ... ```)."},
                        {"role": "user", "content": content}
                    ],
                    max_tokens=4000
                )
                ai_reply = response.choices[0].message.content
            except Exception as e:
                logging.error(f"DeepSeek xatosi: {e}")

        # --- 3-QADAM: AGAR IKKALASI HAM ISHLAMASA ---
        if not ai_reply:
            await msg.edit_text(t['ai_error'])
            return

        # Kod blokini qidirish
        code_match = re.search(r'```(?:python|py|lua|javascript|js|cpp|c)?\s*(.*?)```', ai_reply, re.DOTALL | re.IGNORECASE)
        
        if code_match:
            code_text = code_match.group(1).strip()
            if "lua" in user_query.lower() or (update.message.document and update.message.document.file_name.endswith('.lua')):
                filename = "fixed_code.lua"
                lang_name = "Lua"
            else:
                filename = "fixed_code.py"
                lang_name = "Python"
            
            code_file = BytesIO(code_text.encode('utf-8'))
            code_file.name = filename
            
            await context.bot.send_document(
                chat_id=update.message.chat_id,
                document=code_file,
                caption=f"🤖 **Tuzatilgan kod ({lang_name})**\n\nFayl: `{filename}`\n\n{t['ai_code_found']}",
                parse_mode='Markdown'
            )
            
            explanation = ai_reply.replace(code_match.group(0), "").strip()
            if explanation:
                await context.bot.send_message(chat_id=update.message.chat_id, text=f"📝 **AI Tushuntirmasi:**\n\n{explanation}", parse_mode='Markdown')
                
            await msg.delete()
        else:
            await msg.edit_text(t['ai_no_code'].format(text=ai_reply), parse_mode='Markdown')

    except Exception as e:
        logging.error(f"AI xatosi: {e}")
        await msg.edit_text(t['ai_error'], parse_mode='Markdown')

# ==========================================
# XABARLARNI QABUL QILISH
# ==========================================
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]
    
    if context.user_data.get('state') == 'in_ai':
        await handle_ai_message(update, context)
        return

    if user.id == ADMIN_ID and context.user_data.get('state') == 'in_broadcast':
        if update.message.text == "/cancel":
            context.user_data['state'] = None
            await update.message.reply_text(t['admin_bcast_cancel'])
            return
        await process_broadcast(update, context)
        return

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
                await update.message.reply_text("✅ Javobingiz yuborildi!")
            except Exception as e: await update.message.reply_text(f"❌ Xatolik: {e}")

# ==========================================
# ADMIN BROADCAST
# ==========================================
async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    lang = context.user_data.get('lang', 'uz')
    context.user_data['state'] = 'in_broadcast'
    await update.message.reply_text(TEXTS[lang]['admin_bcast_start'], parse_mode='Markdown')

async def process_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('lang', 'uz')
    msg = await update.message.reply_text(TEXTS[lang]['admin_bcast_wait'])
    users = await get_all_users()
    success, fail = 0, 0
    for uid in users:
        if uid == ADMIN_ID: continue
        try:
            await context.bot.copy_message(chat_id=uid, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
            success += 1
            await asyncio.sleep(0.05)
        except Exception: fail += 1
    context.user_data['state'] = None
    await msg.edit_text(TEXTS[lang]['admin_bcast_done'].format(success=success, fail=fail), parse_mode='Markdown')

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    total, lang_stats = await get_stats()
    uz = lang_stats.get('uz', 0)
    ru = lang_stats.get('ru', 0)
    en = lang_stats.get('en', 0)
    ar = lang_stats.get('ar', 0)
    stats_text = (
        "📊 **BOT STATISTIKASI (DATABASE)**\n\n"
        f"👥 **Jami foydalanuvchilar:** {total} ta\n\n"
        "🌐 **Tillar bo'yicha:**\n"
        f"🇺🇿 O'zbekcha: {uz} ta\n"
        f"🇷🇺 Русский: {ru} ta\n"
        f"🇬🇧 English: {en} ta\n"
        f"🇸🇦 العربية: {ar} ta\n\n"
        "*Ma'lumotlar bazasi muvaffaqiyatli ulangan!*"
    )
    await update.message.reply_text(stats_text, parse_mode='Markdown')

# ==========================================
# VEB SERVER
# ==========================================
application = Application.builder().token(TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("send", send_broadcast))
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
    print(f"✅ Bot, Super AI (DeepSeek+Gemini) va Baza muvaffaqiyatli ishga tushdi!")

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
async def read_root(): return "<h1 style='color:green;'>Super AI Bot ishlayapti!</h1>"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
