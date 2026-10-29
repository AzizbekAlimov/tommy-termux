import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import TelegramError
import uvicorn

# ==========================================
# XAVFSIZLIK QISMI
# ==========================================
TOKEN = os.environ.get("TOKEN")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")

if not TOKEN or not RENDER_EXTERNAL_URL:
    raise ValueError("Xatolik: TOKEN yoki RENDER_EXTERNAL_URL kiritilmagan!")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==========================================
# VIDEOLAR MA'LUMOTLARI
# ==========================================
CHANNEL_USERNAME = "@termux_tutoril" 

LESSONS = {
    1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 8, 7: 9, 8: 10, 9: 11, 10: 12,
    11: 13, 12: 14, 13: 15, 14: 16, 15: 17, 16: 18, 17: 19, 18: 20, 19: 21, 20: 22,
    21: 23, 22: 24, 23: 25, 24: 26, 25: 27, 26: 28, 27: 29, 28: 30, 29: 31, 30: 32,
    31: 33, 32: 34, 33: 35, 34: 36, 35: 37, 36: 38, 37: 39, 38: 40, 39: 41, 40: 42,
    41: 43, 42: 44, 43: 45, 44: 46, 45: 47
}

LUA_LESSONS = {
    1: 93, 2: 94, 3: 97, 4: 98, 5: 99, 6: 100, 7: 101
}

PYTHON_EXTRA_VIDEOS = [96]

# ==========================================
# TILLAR UCHUN LUG'AT
# ==========================================
TEXTS = {
    'uz': {
        'choose_lang': "👋 **Assalomu alaykum!**\n\nIltimos, o'zingizga qulay tilni tanlang:",
        'welcome': "👋 **Assalomu alaykum!**\n\nMen **Termux va Dasturlash** bo'yicha yordamchi botman.\n\n📚 TERMUX UCHUN maxsus video darsliklar tayyor",
        'btn_termux': "📽️ TERMUX VIDEO DARSLIKLAR",
        'btn_lua': "📽️ TERMUX LUA PAK VIDEO DARSLIK",
        'btn_contact': "Murojaat uchun",
        'btn_change_lang': "🌐 Tilni o'zgartirish",
        'btn_back': "🔙 Bosh menyu",
        'btn_prev': "⬅️ Oldingi",
        'btn_next': "Keyingi ➡️",
        'btn_python': "🐍 PYTHON OLISH",
        'btn_lessons_menu': "📚 Darsliklar (Menyu)",
        'text_page': "📚 **Video darsliklar**\n\nSahifa: {page} / 5\nKerakli darslikni tanlang:",
        'text_lua': "📚 **TERMUX LUA PAK DARSLIKLARI**\n\nKerakli darslikni tanlang:",
        'text_python_done': "Mana siz so'ragan Python darsligi! ✅",
        'text_error_vid': "❌ **Xatolik!** Videoni yuklab bo'lmadi.",
        'text_error_py': "❌ **Xatolik!** Python videosini yuklab bo'lmadi."
    },
    'ru': {
        'choose_lang': "👋 **Здравствуйте!**\n\nПожалуйста, выберите удобный для вас язык:",
        'welcome': "👋 **Здравствуйте!**\n\nЯ помощник по **Termux и программированию**.\n\n📚 Подготовлены специальные видеоуроки для TERMUX",
        'btn_termux': "📽️ ВИДЕОУРОКИ TERMUX",
        'btn_lua': "📽️ ВИДЕОУРОКИ TERMUX LUA",
        'btn_contact': "Для обращений",
        'btn_change_lang': "🌐 Изменить язык",
        'btn_back': "🔙 Главное меню",
        'btn_prev': "⬅️ Предыдущий",
        'btn_next': "Следующий ➡️",
        'btn_python': "🐍 ПОЛУЧИТЬ PYTHON",
        'btn_lessons_menu': "📚 Уроки (Меню)",
        'text_page': "📚 **Видеоуроки**\n\nСтраница: {page} / 5\nВыберите нужный урок:",
        'text_lua': "📚 **УРОКИ TERMUX LUA**\n\nВыберите нужный урок:",
        'text_python_done': "Вот запрошенный вами урок Python! ✅",
        'text_error_vid': "❌ **Ошибка!** Не удалось загрузить видео.",
        'text_error_py': "❌ **Ошибка!** Не удалось загрузить видео Python."
    },
    'en': {
        'choose_lang': "👋 **Hello!**\n\nPlease select a convenient language for you:",
        'welcome': "👋 **Hello!**\n\nI am an assistant bot for **Termux and Programming**.\n\n📚 Special video tutorials for TERMUX are ready",
        'btn_termux': "📽️ TERMUX VIDEO LESSONS",
        'btn_lua': "📽️ TERMUX LUA VIDEO LESSONS",
        'btn_contact': "Contact us",
        'btn_change_lang': "🌐 Change language",
        'btn_back': "🔙 Main menu",
        'btn_prev': "⬅️ Previous",
        'btn_next': "Next ➡️",
        'btn_python': "🐍 GET PYTHON",
        'btn_lessons_menu': "📚 Lessons (Menu)",
        'text_page': "📚 **Video lessons**\n\nPage: {page} / 5\nSelect the lesson you need:",
        'text_lua': "📚 **TERMUX LUA LESSONS**\n\nSelect the lesson you need:",
        'text_python_done': "Here is the Python lesson you requested! ✅",
        'text_error_vid': "❌ **Error!** Could not load video.",
        'text_error_py': "❌ **Error!** Could not load Python video."
    },
    'ar': {
        'choose_lang': "👋 **مرحباً!**\n\nالرجاء اختيار اللغة المناسبة لك:",
        'welcome': "👋 **مرحباً!**\n\nأنا مساعد في **Termux والبرمجة**.\n\n📚 دروس فيديو خاصة لـ TERMUX جاهزة",
        'btn_termux': "📽️ دروس فيديو TERMUX",
        'btn_lua': "📽️ دروس فيديو TERMUX LUA",
        'btn_contact': "للتواصل",
        'btn_change_lang': "🌐 تغيير اللغة",
        'btn_back': "🔙 القائمة الرئيسية",
        'btn_prev': "⬅️ السابق",
        'btn_next': "التالي ➡️",
        'btn_python': "🐍 الحصول على PYTHON",
        'btn_lessons_menu': "📚 الدروس (القائمة)",
        'text_page': "📚 **دروس الفيديو**\n\nالصفحة: {page} / 5\nاختر الدرس الذي تحتاجه:",
        'text_lua': "📚 **دروس TERMUX LUA**\n\nاختر الدرس الذي تحتاجه:",
        'text_python_done': "هذا درس Python الذي طلبته! ✅",
        'text_error_vid': "❌ **خطأ!** تعذر تحميل الفيديو.",
        'text_error_py': "❌ **خطأ!** تعذر تحميل فيديو Python."
    }
}

# ==========================================
# KLAVIATURALAR
# ==========================================
def get_lang_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇺🇿 O'zbekcha", callback_data="lang_uz"), InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")],
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"), InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar")]
    ])

def get_main_menu(lang):
    t = TEXTS[lang]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t['btn_termux'], callback_data="page_1")],
        [InlineKeyboardButton(t['btn_lua'], callback_data="lua_page_1")],
        [InlineKeyboardButton(t['btn_contact'], url="https://t.me/Tommy_1727")],
        [InlineKeyboardButton(t['btn_change_lang'], callback_data="change_lang")] # TILNI O'ZGARTIRISH TUGMASI
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

# ==========================================
# HANDLERLAR
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Agar foydalanuvchi til tanlagan bo'lsa, to'g'ridan-to'g'ri menyuga o'tadi
    if 'lang' in context.user_data:
        lang = context.user_data['lang']
        await update.message.reply_text(TEXTS[lang]['welcome'], reply_markup=get_main_menu(lang), parse_mode='Markdown')
    else:
        # Agar yangi foydalanuvchi bo'lsa yoki xotira tozalangan bo'lsa, til so'raydi
        await update.message.reply_text(TEXTS['uz']['choose_lang'], reply_markup=get_lang_keyboard(), parse_mode='Markdown')

async def button_tap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id
    
    # 1. TILNI TANLASH
    if data.startswith("lang_"):
        lang = data.split("_")[1]
        context.user_data['lang'] = lang
        await query.edit_message_text(TEXTS[lang]['welcome'], reply_markup=get_main_menu(lang), parse_mode='Markdown')
        return

    # 2. TILNI O'ZGARTIRISH (Tugma orqali)
    elif data == "change_lang":
        # Tilni xotiradan o'chirib yuboramiz
        context.user_data.pop('lang', None)
        await query.edit_message_text(TEXTS['uz']['choose_lang'], reply_markup=get_lang_keyboard(), parse_mode='Markdown')
        return

    # Qolgan barcha amallar uchun foydalanuvchi tilini olamiz (default: uz)
    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]

    # 3. ASOSIY DARSLIKLAR
    if data.startswith("page_"):
        page = int(data.split("_")[1])
        text = t['text_page'].format(page=page)
        try:
            await query.edit_message_text(text=text, reply_markup=get_lessons_keyboard(page, lang), parse_mode='Markdown')
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=get_lessons_keyboard(page, lang), parse_mode='Markdown')
            
    elif data.startswith("lesson_"):
        lesson_num = int(data.split("_")[1])
        message_id = LESSONS[lesson_num]
        video_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_lessons_menu'], callback_data="page_1")]])
        try:
            await context.bot.copy_message(chat_id=chat_id, from_chat_id=CHANNEL_USERNAME, message_id=message_id, reply_markup=video_keyboard)
            await query.message.delete()
        except TelegramError:
            await context.bot.send_message(chat_id=chat_id, text=t['text_error_vid'], parse_mode='Markdown')

    # 4. LUA DARSLIKLARI
    elif data == "lua_page_1":
        try:
            await query.edit_message_text(text=t['text_lua'], reply_markup=get_lua_lessons_keyboard(lang), parse_mode='Markdown')
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=t['text_lua'], reply_markup=get_lua_lessons_keyboard(lang), parse_mode='Markdown')

    elif data.startswith("lua_lesson_"):
        lesson_num = int(data.split("_")[2])
        message_id = LUA_LESSONS[lesson_num]
        buttons = []
        
        if lesson_num == 2:
            buttons.append([InlineKeyboardButton(t['btn_python'], callback_data="python_extra")])
            
        buttons.append([InlineKeyboardButton(t['btn_lessons_menu'], callback_data="lua_page_1")])
        video_keyboard = InlineKeyboardMarkup(buttons)
        
        try:
            await context.bot.copy_message(chat_id=chat_id, from_chat_id=CHANNEL_USERNAME, message_id=message_id, reply_markup=video_keyboard)
            await query.message.delete()
        except TelegramError:
            await context.bot.send_message(chat_id=chat_id, text=t['text_error_vid'], parse_mode='Markdown')

    # 5. PYTHON MAXSUS VIDEOLARI
    elif data == "python_extra":
        try:
            for v_id in PYTHON_EXTRA_VIDEOS:
                await context.bot.copy_message(chat_id=chat_id, from_chat_id=CHANNEL_USERNAME, message_id=v_id)
            
            back_kb = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="lua_page_1")]])
            await context.bot.send_message(chat_id=chat_id, text=t['text_python_done'], reply_markup=back_kb)
        except TelegramError:
            back_kb = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="lua_page_1")]])
            await context.bot.send_message(chat_id=chat_id, text=t['text_error_py'], reply_markup=back_kb)
        
    # 6. BOSH MENYUGA QAYTISH
    elif data == "back_to_start":
        try:
            await query.edit_message_text(text=t['welcome'], reply_markup=get_main_menu(lang), parse_mode='Markdown')
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=t['welcome'], reply_markup=get_main_menu(lang), parse_mode='Markdown')

# ==========================================
# VEB SERVER VA WEBHOOK QISMI
# ==========================================
application = Application.builder().token(TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(button_tap))

app = FastAPI()

@app.on_event("startup")
async def on_startup():
    await application.initialize()
    webhook_url = f"{RENDER_EXTERNAL_URL}/webhook/{TOKEN}"
    await application.bot.set_webhook(url=webhook_url)
    print(f"✅ Webhook o'rnatildi.")

@app.on_event("shutdown")
async def on_shutdown():
    await application.shutdown()

@app.post(f"/webhook/{TOKEN}")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
async def read_root():
    return "<h1 style='color:green; font-family:sans-serif;'>Bot muvaffaqiyatli ishlayapti!</h1>"

@app.get("/tutorial", response_class=HTMLResponse)
async def get_tutorial():
    try:
        with open("tutorial.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1 style='color:red;'>Xatolik: tutorial.html topilmadi!</h1>"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
