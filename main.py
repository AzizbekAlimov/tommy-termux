import os
import logging
import random
import aiohttp
import re
import asyncio
import asyncpg
from io import BytesIO
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError
import uvicorn

# ==========================================
# SOZLAMALAR VA MA'LUMOTLAR BAZASI
# ==========================================
TOKEN = os.environ.get("TOKEN")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
DATABASE_URL = os.environ.get("DATABASE_URL") # Neon.tech dan olinadigan havola

ADMIN_ID = 7383782449
CHANNEL_USERNAME = "@Tommy_cheat" 
TERMUX_APK_URL = "https://github.com/termux/termux-app/releases/download/v0.118.0/termux-app_v0.118.0+github-debug_arm64-v8a.apk"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Global ma'lumotlar bazasi puli
db_pool = None

async def init_db():
    global db_pool
    if not DATABASE_URL:
        logging.warning("DATABASE_URL kiritilmagan. Xotira rejimida ishlaydi.")
        return
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
        logging.info("Ma'lumotlar bazasi muvaffaqiyatli ulandi!")
    except Exception as e:
        logging.error(f"Ma'lumotlar bazasiga ulanishda xato: {e}")

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
        lang_stats = {r['lang']: r['count'] for r in langs}
        return total, lang_stats

# ==========================================
# VIDEOLAR MA'LUMOTLARI
# ==========================================
LESSONS = {i: i+2 for i in range(1, 46)}
LUA_LESSONS = {1: 93, 2: 94, 3: 97, 4: 98, 5: 99, 6: 100, 7: 101}
PYTHON_EXTRA_VIDEOS = [96]

# ==========================================
# TILLAR UCHUN LUG'AT
# ==========================================
TEXTS = {
    'uz': {
        'choose_lang': "👋 **Assalomu alaykum!**\n\nIltimos, o'zingizga qulay tilni tanlang:",
        'welcome': "👋 **Assalomu alaykum!**\n\nMen **Termux va Dasturlash** bo'yicha yordamchi botman.",
        'btn_termux': "📽️ TERMUX VIDEO DARSLIKLAR", 'btn_lua': "📽️ TERMUX LUA PAK VIDEO DARSLIK",
        'btn_apk': "📥 TERMUX APK YUKLAB OLISH", 'btn_tip': "💡 Kunlik maslahat",
        'btn_cheatsheet': "📜 Muhim buyruqlar", 'btn_quiz': "🧠 Bilimingizni sinang (Test)",
        'btn_support': "✉️ Adminga murojaat qilish", 'btn_another_tip': "🔄 Yana maslahat",
        'btn_security': "🛡️ Kiberxavfsizlik", 'btn_change_lang': "🌐 Tilni o'zgartirish", 
        'btn_back': "🔙 Bosh menyu", 'btn_prev': "⬅️ Oldingi", 'btn_next': "Keyingi ➡️", 
        'btn_python': "🐍 PYTHON OLISH", 'btn_lessons_menu': "📚 Darsliklar (Menyu)",
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
        'apk_file_name': "Termux_Ilovasi.apk", 'apk_loading': "⏳ Iltimos kuting...",
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
        'admin_bcast_cancel': "❌ Bekor qilindi."
    },
    'ru': {'choose_lang': "👋 **Здравствуйте!**\n\nВыберите язык:", 'welcome': "👋 Я помощник по **Termux**.", 'btn_termux': "📽️ УРОКИ TERMUX", 'btn_lua': "📽️ УРОКИ LUA", 'btn_apk': "📥 СКАЧАТЬ APK", 'btn_tip': "💡 Совет", 'btn_cheatsheet': "📜 Команды", 'btn_quiz': "🧠 Тест", 'btn_support': "✉️ Админу", 'btn_another_tip': "🔄 Ещё", 'btn_security': "🛡️ Безопасность", 'btn_change_lang': "🌐 Язык", 'btn_back': "🔙 Назад", 'btn_prev': "⬅️ Назад", 'btn_next': "Вперед ➡️", 'btn_python': "🐍 PYTHON", 'btn_lessons_menu': "📚 Меню", 'text_page': "📚 Уроки {page}/5", 'text_lua': "📚 Уроки LUA", 'text_python_done': "Урок Python ✅", 'text_error_vid': "❌ Ошибка видео.", 'text_error_py': "❌ Ошибка Python.", 'tip_header': "💡 **Совет:**\n\n", 'cheatsheet_menu': "📜 Команды", 'cat_files': "📁 Файлы", 'cat_packages': "📦 Пакеты", 'cat_network': "🌐 Сеть", 'cat_system': "⚙️ Система", 'btn_back_cheat': "🔙 Назад", 'apk_caption': "📱 Termux APK", 'apk_file_name': "Termux.apk", 'apk_loading': "⏳ Загрузка...", 'apk_too_big': "⚠️ Файл большой.", 'apk_error': "❌ Ошибка APK.", 'support_prompt': "✉️ Напишите вопрос.", 'support_sent': "✅ Отправлено!", 'support_reply': "📬 Ответ:\n\n", 'quiz_start': "🧠 Тест!", 'quiz_correct': "✅ Верно!", 'quiz_wrong': "❌ Ошибка: **{answer}**", 'btn_next_quiz': "➡️ Далее", 'sec_menu': "🛡️ Безопасность", 'sec_info': "🔍 Инфо", 'sec_pass': "🔑 Пароли", 'sec_exploit': "💥 Уязвимости", 'sec_network': "📡 Сеть", 'sec_info_text': "Nmap: `pkg install nmap`", 'sec_pass_text': "Hydra: `pkg install hydra`", 'sec_exploit_text': "SQLmap: `pip install sqlmap`", 'sec_network_text': "Tshark: `pkg install tshark`", 'admin_bcast_start': "📢 Режим рассылки.", 'admin_bcast_wait': "⏳ Отправка...", 'admin_bcast_done': "✅ Готово! Успех: {success}, Ошибок: {fail}", 'admin_bcast_cancel': "❌ Отменено."},
    'en': {'choose_lang': "👋 **Hello!**\n\nSelect language:", 'welcome': "👋 I am your **Termux** assistant.", 'btn_termux': "📽️ TERMUX LESSONS", 'btn_lua': "📽️ LUA LESSONS", 'btn_apk': "📥 DOWNLOAD APK", 'btn_tip': "💡 Tip", 'btn_cheatsheet': "📜 Commands", 'btn_quiz': "🧠 Quiz", 'btn_support': "✉️ Contact Admin", 'btn_another_tip': "🔄 Another", 'btn_security': "🛡️ Security", 'btn_change_lang': "🌐 Language", 'btn_back': "🔙 Back", 'btn_prev': "⬅️ Prev", 'btn_next': "Next ➡️", 'btn_python': "🐍 GET PYTHON", 'btn_lessons_menu': "📚 Menu", 'text_page': "📚 Lessons {page}/5", 'text_lua': "📚 LUA Lessons", 'text_python_done': "Python Lesson ✅", 'text_error_vid': "❌ Video error.", 'text_error_py': "❌ Python error.", 'tip_header': "💡 **Tip:**\n\n", 'cheatsheet_menu': "📜 Commands", 'cat_files': "📁 Files", 'cat_packages': "📦 Packages", 'cat_network': "🌐 Network", 'cat_system': "⚙️ System", 'btn_back_cheat': "🔙 Back", 'apk_caption': "📱 Termux APK", 'apk_file_name': "Termux.apk", 'apk_loading': "⏳ Loading...", 'apk_too_big': "⚠️ File too big.", 'apk_error': "❌ APK error.", 'support_prompt': "✉️ Write your question.", 'support_sent': "✅ Sent!", 'support_reply': "📬 Reply:\n\n", 'quiz_start': "🧠 Quiz!", 'quiz_correct': "✅ Correct!", 'quiz_wrong': "❌ Wrong: **{answer}**", 'btn_next_quiz': "➡️ Next", 'sec_menu': "🛡️ Security", 'sec_info': "🔍 Info", 'sec_pass': "🔑 Passwords", 'sec_exploit': "💥 Exploits", 'sec_network': "📡 Network", 'sec_info_text': "Nmap: `pkg install nmap`", 'sec_pass_text': "Hydra: `pkg install hydra`", 'sec_exploit_text': "SQLmap: `pip install sqlmap`", 'sec_network_text': "Tshark: `pkg install tshark`", 'admin_bcast_start': "📢 Broadcast mode.", 'admin_bcast_wait': "⏳ Sending...", 'admin_bcast_done': "✅ Done! Success: {success}, Fail: {fail}", 'admin_bcast_cancel': "❌ Cancelled."},
    'ar': {'choose_lang': "👋 **مرحباً!**\n\nاختر اللغة:", 'welcome': "👋 أنا مساعد **Termux**.", 'btn_termux': "📽️ دروس TERMUX", 'btn_lua': "📽️ دروس LUA", 'btn_apk': "📥 تحميل APK", 'btn_tip': "💡 نصيحة", 'btn_cheatsheet': "📜 أوامر", 'btn_quiz': "🧠 اختبار", 'btn_support': "✉️ للمسؤول", 'btn_another_tip': "🔄 أخرى", 'btn_security': "🛡️ الأمن", 'btn_change_lang': "🌐 اللغة", 'btn_back': "🔙 رجوع", 'btn_prev': "⬅️ السابق", 'btn_next': "التالي ➡️", 'btn_python': "🐍 PYTHON", 'btn_lessons_menu': "📚 القائمة", 'text_page': "📚 دروس {page}/5", 'text_lua': "📚 دروس LUA", 'text_python_done': "درس Python ✅", 'text_error_vid': "❌ خطأ في الفيديو.", 'text_error_py': "❌ خطأ في Python.", 'tip_header': "💡 **نصيحة:**\n\n", 'cheatsheet_menu': "📜 أوامر", 'cat_files': "📁 ملفات", 'cat_packages': "📦 حزم", 'cat_network': "🌐 شبكة", 'cat_system': "⚙️ نظام", 'btn_back_cheat': "🔙 رجوع", 'apk_caption': "📱 Termux APK", 'apk_file_name': "Termux.apk", 'apk_loading': "⏳ جاري التحميل...", 'apk_too_big': "⚠️ الملف كبير.", 'apk_error': "❌ خطأ APK.", 'support_prompt': "✉️ اكتب سؤالك.", 'support_sent': "✅ تم الإرسال!", 'support_reply': "📬 الرد:\n\n", 'quiz_start': "🧠 اختبار!", 'quiz_correct': "✅ صحيح!", 'quiz_wrong': "❌ خطأ: **{answer}**", 'btn_next_quiz': "➡️ التالي", 'sec_menu': "🛡️ الأمن", 'sec_info': "🔍 معلومات", 'sec_pass': "🔑 كلمات المرور", 'sec_exploit': "💥 ثغرات", 'sec_network': "📡 شبكة", 'sec_info_text': "Nmap: `pkg install nmap`", 'sec_pass_text': "Hydra: `pkg install hydra`", 'sec_exploit_text': "SQLmap: `pip install sqlmap`", 'sec_network_text': "Tshark: `pkg install tshark`", 'admin_bcast_start': "📢 وضع البث.", 'admin_bcast_wait': "⏳ جاري الإرسال...", 'admin_bcast_done': "✅ تم! النجاح: {success}, الفشل: {fail}", 'admin_bcast_cancel': "❌ تم الإلغاء."}
}

TIPS = [
    {'uz': "**Tezroq kod yozish:**\n`nano` o'rniga `micro` ishlating.", 'ru': "**Быстрое написание:**\nИспользуйте `micro`.", 'en': "**Faster coding:**\nUse `micro`.", 'ar': "**برمجة أسرع:**\nاستخدم `micro`."},
]

COMMANDS_DATA = {
    'files': [('ls', {'uz': 'Fayllar', 'ru': 'Файлы', 'en': 'Files', 'ar': 'ملفات'}), ('cd papka', {'uz': 'Kirish', 'ru': 'Войти', 'en': 'Enter', 'ar': 'دخول'})],
    'packages': [('pkg update', {'uz': 'Yangilash', 'ru': 'Обновить', 'en': 'Update', 'ar': 'تحديث'})],
    'network': [('ping google.com', {'uz': 'Tekshirish', 'ru': 'Проверить', 'en': 'Check', 'ar': 'فحص'})],
    'system': [('clear', {'uz': 'Tozalash', 'ru': 'Очистить', 'en': 'Clear', 'ar': 'مسح'})]
}

QUIZ_DATA = [
    {'q': {'uz': "Papka yaratish buyrug'i?", 'ru': "Команда для папки?", 'en': "Command for folder?", 'ar': "أمر لإنشاء مجلد؟"}, 'options': ['mkdir', 'cd', 'ls', 'rm'], 'answer': 'mkdir'},
    {'q': {'uz': "Paket o'rnatish?", 'ru': "Установить пакет?", 'en': "Install package?", 'ar': "تثبيت حزمة؟"}, 'options': ['pkg install', 'apt-get', 'pip install', 'install'], 'answer': 'pkg install'},
]

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
        [InlineKeyboardButton(t['btn_quiz'], callback_data="quiz_start")],
        [InlineKeyboardButton(t['btn_security'], callback_data="sec_start")],
        [InlineKeyboardButton(t['btn_support'], callback_data="support_start")],
        [InlineKeyboardButton(t['btn_tip'], callback_data="daily_tip")], 
        [InlineKeyboardButton(t['btn_cheatsheet'], callback_data="cheatsheet")], 
        [InlineKeyboardButton(t['btn_change_lang'], callback_data="change_lang")]
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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t['cat_files'], callback_data="cat_files")],
        [InlineKeyboardButton(t['cat_packages'], callback_data="cat_packages")],
        [InlineKeyboardButton(t['cat_network'], callback_data="cat_network")],
        [InlineKeyboardButton(t['cat_system'], callback_data="cat_system")],
        [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]
    ])

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
    
    # Bazaga qo'shish/yangilash
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
        await add_user(user_id, lang) # Bazada tilni yangilash
        await query.edit_message_text(TEXTS[lang]['welcome'], reply_markup=get_main_menu(lang), parse_mode='Markdown')
        return

    elif data == "change_lang":
        context.user_data.pop('lang', None)
        await query.edit_message_text(TEXTS['uz']['choose_lang'], reply_markup=get_lang_keyboard(), parse_mode='Markdown')
        return

    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]

    if data == "sec_start":
        try:
            await query.edit_message_text(text=t['sec_menu'], reply_markup=get_sec_menu(lang), parse_mode='Markdown')
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=t['sec_menu'], reply_markup=get_sec_menu(lang), parse_mode='Markdown')
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

async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    lang = context.user_data.get('lang', 'uz')
    context.user_data['state'] = 'in_broadcast'
    await update.message.reply_text(TEXTS[lang]['admin_bcast_start'], parse_mode='Markdown')

async def process_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('lang', 'uz')
    msg = await update.message.reply_text(TEXTS[lang]['admin_bcast_wait'])
    
    # Bazadan barcha foydalanuvchilarni olish
    users = await get_all_users()
    success, fail = 0, 0
    
    for uid in users:
        if uid == ADMIN_ID: continue
        try:
            await context.bot.copy_message(chat_id=uid, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
            success += 1
            await asyncio.sleep(0.05) # Limitga tushmaslik uchun
        except Exception: fail += 1
            
    context.user_data['state'] = None
    await msg.edit_text(TEXTS[lang]['admin_bcast_done'].format(success=success, fail=fail), parse_mode='Markdown')

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    # Bazadan statistikani olish
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

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]
    
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
# VEB SERVER VA WEBHOOK
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
    await init_db() # Bazani ishga tushirish
    await application.initialize()
    webhook_url = f"{RENDER_EXTERNAL_URL}/webhook/{TOKEN}"
    await application.bot.set_webhook(url=webhook_url)
    print(f"✅ Webhook o'rnatildi va Baza tekshirildi.")

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
async def read_root(): return "<h1 style='color:green;'>Bot va Baza ishlayapti!</h1>"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
