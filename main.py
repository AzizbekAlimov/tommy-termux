import os
import logging
import random
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
        'welcome': "👋 **Assalomu alaykum!**\n\nMen **Termux va Dasturlash** bo'yicha yordamchi botman.\n\n📚 TERMUX UCHUN maxsus video darsliklar tayyor\n📚 PAK LUA UCHUN maxsus video darsliklar tayyor",
        'btn_termux': "📽️ TERMUX VIDEO DARSLIKLAR",
        'btn_lua': "📽️ TERMUX LUA PAK VIDEO DARSLIK",
        'btn_tip': "💡 Kunlik maslahat",
        'btn_another_tip': "🔄 Yana maslahat",
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
        'text_error_py': "❌ **Xatolik!** Python videosini yuklab bo'lmadi.",
        'tip_header': "💡 **Kunlik maslahat:**\n\n"
    },
    'ru': {
        'choose_lang': "👋 **Здравствуйте!**\n\nПожалуйста, выберите удобный для вас язык:",
        'welcome': "👋 **Здравствуйте!**\n\nЯ помощник по **Termux и программированию**.\n\n📚 Подготовлены специальные видеоуроки для TERMUX\n📚 Подготовлены специальные видеоуроки для PAK LUA",
        'btn_termux': "📽️ ВИДЕОУРОКИ TERMUX",
        'btn_lua': "📽️ ВИДЕОУРОКИ TERMUX LUA",
        'btn_tip': "💡 Совет дня",
        'btn_another_tip': "🔄 Ещё совет",
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
        'text_error_py': "❌ **Ошибка!** Не удалось загрузить видео Python.",
        'tip_header': "💡 **Совет дня:**\n\n"
    },
    'en': {
        'choose_lang': "👋 **Hello!**\n\nPlease select a convenient language for you:",
        'welcome': "👋 **Hello!**\n\nI am an assistant bot for **Termux and Programming**.\n\n📚 Special video tutorials for TERMUX are ready\n📚 Special video tutorials for PAK LUA are ready",
        'btn_termux': "📽️ TERMUX VIDEO LESSONS",
        'btn_lua': "📽️ TERMUX LUA VIDEO LESSONS",
        'btn_tip': "💡 Daily Tip",
        'btn_another_tip': "🔄 Another Tip",
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
        'text_error_py': "❌ **Error!** Could not load Python video.",
        'tip_header': "💡 **Daily Tip:**\n\n"
    },
    'ar': {
        'choose_lang': "👋 **مرحباً!**\n\nالرجاء اختيار اللغة المناسبة لك:",
        'welcome': "👋 **مرحباً!**\n\nأنا مساعد في **Termux والبرمجة**.\n\n📚 دروس فيديو خاصة لـ TERMUX جاهزة\n📚 دروس فيديو خاصة لـ PAK LUA جاهزة",
        'btn_termux': "📽️ دروس فيديو TERMUX",
        'btn_lua': "📽️ دروس فيديو TERMUX LUA",
        'btn_tip': "💡 نصيحة اليوم",
        'btn_another_tip': "🔄 نصيحة أخرى",
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
        'text_error_py': "❌ **خطأ!** تعذر تحميل فيديو Python.",
        'tip_header': "💡 **نصيحة اليوم:**\n\n"
    }
}

# ==========================================
# KUNLIK MASLAHATLAR BAZASI (4 tilda)
# ==========================================
TIPS = [
    {
        'uz': "**Tezroq kod yozish:**\n`nano` o'rniga `micro` matn muharririni ishlatib ko'ring. U yanada qulay va sichqonchani qo'llab-quvvatlaydi.\nO'rnatish: `pkg install micro`",
        'ru': "**Быстрое написание кода:**\nПопробуйте использовать текстовый редактор `micro` вместо `nano`. Он более удобен и поддерживает мышь.\nУстановка: `pkg install micro`",
        'en': "**Faster coding:**\nTry using the `micro` text editor instead of `nano`. It is more convenient and supports mouse.\nInstall: `pkg install micro`",
        'ar': "**برمجة أسرع:**\nجرب استخدام محرر النصوص `micro` بدلاً من `nano`. إنه أكثر ملاءمة ويدعم الماوس.\nالتثبيت: `pkg install micro`"
    },
    {
        'uz': "**Termuxni chiroyli qilish:**\nTermuxga kirganda chiqadigan zerikarli yozuvni o'zgartirish mumkin.\nO'rnatish: `pkg install figlet`\nKeyin: `figlet Salom` deb yozing.",
        'ru': "**Сделайте Termux красивым:**\nСкучный текст, появляющийся при входе в Termux, можно изменить.\nУстановка: `pkg install figlet`\nЗатем напишите: `figlet Hello`",
        'en': "**Make Termux beautiful:**\nYou can change the boring text that appears when you enter Termux.\nInstall: `pkg install figlet`\nThen type: `figlet Hello`",
        'ar': "**اجعل Termux جميلاً:**\nيمكنك تغيير النص الممل الذي يظهر عند دخولك إلى Termux.\nالتثبيت: `pkg install figlet`\nثم اكتب: `figlet Hello`"
    },
    {
        'uz': "**Fayllarni ko'chirish (Download):**\nInternetdan fayl yuklash uchun `wget` buyrug'idan foydalaning.\nMisol: `wget https://example.com/file.zip`",
        'ru': "**Скачивание файлов:**\nИспользуйте команду `wget` для скачивания файлов из интернета.\nПример: `wget https://example.com/file.zip`",
        'en': "**Downloading files:**\nUse the `wget` command to download files from the internet.\nExample: `wget https://example.com/file.zip`",
        'ar': "**تنزيل الملفات:**\nاستخدم الأمر `wget` لتنزيل الملفات من الإنترنت.\nمثال: `wget https://example.com/file.zip`"
    },
    {
        'uz': "**Ekran tozaligi:**\nTermuxda juda ko'p yozuvlar yig'ilib qolsa, ekranni tozalash uchun `clear` buyrug'ini bosing yoki klaviaturada `CTRL + L` ni bosing.",
        'ru': "**Чистота экрана:**\nЕсли в Termux накопилось много текста, используйте команду `clear` или нажмите `CTRL + L` на клавиатуре.",
        'en': "**Screen cleanliness:**\nIf too much text accumulates in Termux, press the `clear` command or press `CTRL + L` on the keyboard.",
        'ar': "**نظافة الشاشة:**\nإذا تراكم الكثير من النصوص في Termux، فاضغط على الأمر `clear` أو اضغط على `CTRL + L` على لوحة المفاتيح."
    },
    {
        'uz': "**Python veb-server:**\nTelefoningizda 1 soniyada veb-serverni ishga tushirishingiz mumkin. Buning uchun papkada turib: `python -m http.server 8080` deb yozing.",
        'ru': "**Веб-сервер Python:**\nВы можете запустить веб-сервер на телефоне за 1 секунду. Для этого в папке напишите: `python -m http.server 8080`",
        'en': "**Python web server:**\nYou can start a web server on your phone in 1 second. To do this, in the folder type: `python -m http.server 8080`",
        'ar': "**خادم ويب Python:**\nيمكنك بدء خادم ويب على هاتفك في ثانية واحدة. للقيام بذلك، في المجلد اكتب: `python -m http.server 8080`"
    },
    {
        'uz': "**Tezkor klaviatura:**\nTermux'da nusxalash (Copy) uchun matnni bosib turing, joylashtirish (Paste) uchun esa ekranga uzoqroq bosib turing.",
        'ru': "**Быстрая клавиатура:**\nЧтобы скопировать текст в Termux, нажмите и удерживайте его, а чтобы вставить — долго нажмите на экран.",
        'en': "**Quick keyboard:**\nTo copy text in Termux, press and hold it, and to paste, long press on the screen.",
        'ar': "**لوحة مفاتيح سريعة:**\nلنسخ النص في Termux، اضغط مع الاستمرار عليه، وللصق، اضغط لفترة طويلة على الشاشة."
    }
]

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
        [InlineKeyboardButton(t['btn_tip'], callback_data="daily_tip")], 
        [InlineKeyboardButton(t['btn_contact'], url="https://t.me/Tommy_1727")],
        [InlineKeyboardButton(t['btn_change_lang'], callback_data="change_lang")]
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
    if 'lang' in context.user_data:
        lang = context.user_data['lang']
        await update.message.reply_text(TEXTS[lang]['welcome'], reply_markup=get_main_menu(lang), parse_mode='Markdown')
    else:
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

    # 2. TILNI O'ZGARTIRISH
    elif data == "change_lang":
        context.user_data.pop('lang', None)
        await query.edit_message_text(TEXTS['uz']['choose_lang'], reply_markup=get_lang_keyboard(), parse_mode='Markdown')
        return

    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]

    # 3. KUNLIK MASLAHAT
    if data == "daily_tip":
        random_tip = random.choice(TIPS)[lang]
        text = t['tip_header'] + random_tip
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t['btn_another_tip'], callback_data="daily_tip")],
            [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]
        ])
        try:
            await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='Markdown')
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode='Markdown')

    # 4. ASOSIY DARSLIKLAR
    elif data.startswith("page_"):
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

    # 5. LUA DARSLIKLARI
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

    # 6. PYTHON MAXSUS VIDEOLARI
    elif data == "python_extra":
        try:
            for v_id in PYTHON_EXTRA_VIDEOS:
                await context.bot.copy_message(chat_id=chat_id, from_chat_id=CHANNEL_USERNAME, message_id=v_id)
            back_kb = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="lua_page_1")]])
            await context.bot.send_message(chat_id=chat_id, text=t['text_python_done'], reply_markup=back_kb)
        except TelegramError:
            back_kb = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="lua_page_1")]])
            await context.bot.send_message(chat_id=chat_id, text=t['text_error_py'], reply_markup=back_kb)
        
    # 7. BOSH MENYUGA QAYTISH
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
