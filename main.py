import os
import logging
import random
import aiohttp
import re
from io import BytesIO
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError
import uvicorn

# ==========================================
# XAVFSIZLIK VA SOZLAMALAR
# ==========================================
TOKEN = os.environ.get("TOKEN")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")

# SIZNING TELEGRAM ID RAQAMINGIZ
ADMIN_ID = 7383782449 

if not TOKEN or not RENDER_EXTERNAL_URL:
    raise ValueError("Xatolik: TOKEN yoki RENDER_EXTERNAL_URL kiritilmagan!")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==========================================
# VIDEOLAR VA APK MA'LUMOTLARI
# ==========================================
CHANNEL_USERNAME = "@termux_tutoril" 
TERMUX_APK_URL = "https://github.com/termux/termux-app/releases/download/v0.118.0/termux-app_v0.118.0+github-debug_arm64-v8a.apk"

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
        'welcome': "👋 **Assalomu alaykum!**\n\nMen **Termux va Dasturlash** bo'yicha yordamchi botman.",
        'btn_termux': "📽️ TERMUX VIDEO DARSLIKLAR",
        'btn_lua': "📽️ TERMUX LUA PAK VIDEO DARSLIK",
        'btn_apk': "📥 TERMUX APK YUKLAB OLISH",
        'btn_tip': "💡 Kunlik maslahat",
        'btn_cheatsheet': "📜 Muhim buyruqlar",
        'btn_quiz': "🧠 Bilimingizni sinang (Test)",
        'btn_support': "✉️ Adminga murojaat qilish",
        'btn_another_tip': "🔄 Yana maslahat",
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
        'tip_header': "💡 **Kunlik maslahat:**\n\n",
        'cheatsheet_menu': "📜 **Muhim buyruqlar**\n\nKerakli bo'limni tanlang:",
        'cat_files': "📁 Fayllar bilan ishlash",
        'cat_packages': "📦 Paketlar va dasturlar",
        'cat_network': "🌐 Tarmoq va internet",
        'cat_system': "⚙️ Tizim va boshqalar",
        'btn_back_cheat': "🔙 Orqaga",
        'apk_caption': "📱 **Termux ilovasi (APK)**\n\nMana sizga Termuxning rasmiy versiyasi! \n\n1. Faylni yuklab oling.\n2. Telefoningizga o'rnating.\n3. Darsliklarimizni boshlang! 🚀",
        'apk_file_name': "Termux_Ilovasi.apk",
        'apk_loading': "⏳ Iltimos kuting, Termux APK yuklanmoqda...",
        'apk_too_big': "⚠️ **Diqqat!**\n\nFayl hajmi Telegram cheklovidan katta. Iltimos, havola orqali yuklab oling:\n\n👇 [Termuxni yuklab olish](https://github.com/termux/termux-app/releases/download/v0.118.0/termux-app_v0.118.0+github-debug_universal.apk)",
        'apk_error': "❌ **Xatolik!** APK faylini yuklab bo'lmadi.",
        'support_prompt': "✉️ **Adminga murojaat**\n\nIltimos, savolingiz yoki muammoingizni bitta xabar qilib yozib qoldiring. Tez orada javob beramiz.",
        'support_sent': "✅ **Xabaringiz yuborildi!**\n\nAdmin tez orada siz bilan bog'lanadi.",
        'support_reply': "📬 **Admin javobi:**\n\n",
        'quiz_start': "🧠 **Bilimingizni sinab ko'ring!**\n\nQuyidagi savolga to'g'ri javobni tanlang:",
        'quiz_correct': "✅ **To'g'ri javob! Barakalla!** 🎉",
        'quiz_wrong': "❌ **Xato javob!**\n\nTo'g'ri javob: **{answer}**",
        'btn_next_quiz': "➡️ Keyingi savol"
    },
    # ... (Boshqa tillar avvalgidek qoladi, kodni qisqartirish uchun faqat UZ ni ko'rsatdim, lekin to'liq kodda hammasi bor)
    'ru': {'choose_lang': "👋 **Здравствуйте!**\n\nПожалуйста, выберите удобный для вас язык:", 'welcome': "👋 **Здравствуйте!**\n\nЯ помощник по **Termux и программированию**.", 'btn_termux': "📽️ ВИДЕОУРОКИ TERMUX", 'btn_lua': "📽️ ВИДЕОУРОКИ TERMUX LUA", 'btn_apk': "📥 СКАЧАТЬ TERMUX APK", 'btn_tip': "💡 Совет дня", 'btn_cheatsheet': "📜 Важные команды", 'btn_quiz': "🧠 Проверь себя (Тест)", 'btn_support': "✉️ Написать админу", 'btn_another_tip': "🔄 Ещё совет", 'btn_change_lang': "🌐 Изменить язык", 'btn_back': "🔙 Главное меню", 'btn_prev': "⬅️ Предыдущий", 'btn_next': "Следующий ➡️", 'btn_python': "🐍 ПОЛУЧИТЬ PYTHON", 'btn_lessons_menu': "📚 Уроки (Меню)", 'text_page': "📚 **Видеоуроки**\n\nСтраница: {page} / 5\nВыберите нужный урок:", 'text_lua': "📚 **УРОКИ TERMUX LUA**\n\nВыберите нужный урок:", 'text_python_done': "Вот запрошенный вами урок Python! ✅", 'text_error_vid': "❌ **Ошибка!** Не удалось загрузить видео.", 'text_error_py': "❌ **Ошибка!** Не удалось загрузить видео Python.", 'tip_header': "💡 **Совет дня:**\n\n", 'cheatsheet_menu': "📜 **Важные команды**\n\nВыберите нужный раздел:", 'cat_files': "📁 Работа с файлами", 'cat_packages': "📦 Пакеты и программы", 'cat_network': "🌐 Сеть и интернет", 'cat_system': "⚙️ Система и другое", 'btn_back_cheat': "🔙 Назад", 'apk_caption': "📱 **Приложение Termux (APK)**\n\nВот официальная версия Termux! \n\n1. Скачайте файл.\n2. Установите на свой телефон.\n3. Начинайте уроки! 🚀", 'apk_file_name': "Termux_Prilozhenie.apk", 'apk_loading': "⏳ Пожалуйста, подождите, Termux APK загружается...", 'apk_too_big': "⚠️ **Внимание!**\n\nРазмер файла превышает лимит Telegram. Скачайте по ссылке:\n\n👇 [Скачать Termux](https://github.com/termux/termux-app/releases/download/v0.118.0/termux-app_v0.118.0+github-debug_universal.apk)", 'apk_error': "❌ **Ошибка!** Не удалось загрузить APK файл.", 'support_prompt': "✉️ **Написать админу**\n\nПожалуйста, напишите свой вопрос или проблему одним сообщением. Мы скоро ответим.", 'support_sent': "✅ **Ваше сообщение отправлено!**\n\nАдмин свяжется с вами в ближайшее время.", 'support_reply': "📬 **Ответ админа:**\n\n", 'quiz_start': "🧠 **Проверьте свои знания!**\n\nВыберите правильный ответ на следующий вопрос:", 'quiz_correct': "✅ **Правильный ответ! Молодец!** 🎉", 'quiz_wrong': "❌ **Неправильный ответ!**\n\nПравильный ответ: **{answer}**", 'btn_next_quiz': "➡️ Следующий вопрос"},
    'en': {'choose_lang': "👋 **Hello!**\n\nPlease select a convenient language for you:", 'welcome': "👋 **Hello!**\n\nI am an assistant bot for **Termux and Programming**.", 'btn_termux': "📽️ TERMUX VIDEO LESSONS", 'btn_lua': "📽️ TERMUX LUA VIDEO LESSONS", 'btn_apk': "📥 DOWNLOAD TERMUX APK", 'btn_tip': "💡 Daily Tip", 'btn_cheatsheet': "📜 Important commands", 'btn_quiz': "🧠 Test your knowledge", 'btn_support': "✉️ Contact Admin", 'btn_another_tip': "🔄 Another Tip", 'btn_change_lang': "🌐 Change language", 'btn_back': "🔙 Main menu", 'btn_prev': "⬅️ Previous", 'btn_next': "Next ➡️", 'btn_python': "🐍 GET PYTHON", 'btn_lessons_menu': "📚 Lessons (Menu)", 'text_page': "📚 **Video lessons**\n\nPage: {page} / 5\nSelect the lesson you need:", 'text_lua': "📚 **TERMUX LUA LESSONS**\n\nSelect the lesson you need:", 'text_python_done': "Here is the Python lesson you requested! ✅", 'text_error_vid': "❌ **Error!** Could not load video.", 'text_error_py': "❌ **Error!** Could not load Python video.", 'tip_header': "💡 **Daily Tip:**\n\n", 'cheatsheet_menu': "📜 **Important commands**\n\nSelect the desired category:", 'cat_files': "📁 File Management", 'cat_packages': "📦 Packages & Programs", 'cat_network': "🌐 Network & Internet", 'cat_system': "⚙️ System & Other", 'btn_back_cheat': "🔙 Back", 'apk_caption': "📱 **Termux Application (APK)**\n\nHere is the official version of Termux! \n\n1. Download the file.\n2. Install it on your phone.\n3. Start our lessons! 🚀", 'apk_file_name': "Termux_App.apk", 'apk_loading': "⏳ Please wait, Termux APK is downloading...", 'apk_too_big': "⚠️ **Attention!**\n\nThe file size exceeds the Telegram limit. Please download via the direct link:\n\n👇 [Download Termux](https://github.com/termux/termux-app/releases/download/v0.118.0/termux-app_v0.118.0+github-debug_universal.apk)", 'apk_error': "❌ **Error!** Could not download the APK file.", 'support_prompt': "✉️ **Contact Admin**\n\nPlease write your question or problem in one message. We will reply soon.", 'support_sent': "✅ **Your message has been sent!**\n\nThe admin will contact you shortly.", 'support_reply': "📬 **Admin reply:**\n\n", 'quiz_start': "🧠 **Test your knowledge!**\n\nChoose the correct answer to the following question:", 'quiz_correct': "✅ **Correct answer! Well done!** 🎉", 'quiz_wrong': "❌ **Wrong answer!**\n\nThe correct answer is: **{answer}**", 'btn_next_quiz': "➡️ Next question"},
    'ar': {'choose_lang': "👋 **مرحباً!**\n\nالرجاء اختيار اللغة المناسبة لك:", 'welcome': "👋 **مرحباً!**\n\nأنا مساعد في **Termux والبرمجة**.", 'btn_termux': "📽️ دروس فيديو TERMUX", 'btn_lua': "📽️ دروس فيديو TERMUX LUA", 'btn_apk': "📥 تحميل TERMUX APK", 'btn_tip': "💡 نصيحة اليوم", 'btn_cheatsheet': "📜 أوامر مهمة", 'btn_quiz': "🧠 اختبر معلوماتك", 'btn_support': "✉️ التواصل مع المسؤول", 'btn_another_tip': "🔄 نصيحة أخرى", 'btn_change_lang': "🌐 تغيير اللغة", 'btn_back': "🔙 القائمة الرئيسية", 'btn_prev': "⬅️ السابق", 'btn_next': "التالي ➡️", 'btn_python': "🐍 الحصول على PYTHON", 'btn_lessons_menu': "📚 الدروس (القائمة)", 'text_page': "📚 **دروس الفيديو**\n\nالصفحة: {page} / 5\nاختر الدرس الذي تحتاجه:", 'text_lua': "📚 **دروس TERMUX LUA**\n\nاختر الدرس الذي تحتاجه:", 'text_python_done': "هذا درس Python الذي طلبته! ✅", 'text_error_vid': "❌ **خطأ!** تعذر تحميل الفيديو.", 'text_error_py': "❌ **خطأ!** تعذر تحميل فيديو Python.", 'tip_header': "💡 **نصيحة اليوم:**\n\n", 'cheatsheet_menu': "📜 **أوامر مهمة**\n\nاختر الفئة المطلوبة:", 'cat_files': "📁 إدارة الملفات", 'cat_packages': "📦 الحزم والبرامج", 'cat_network': "🌐 الشبكة والإنترنت", 'cat_system': "⚙️ النظام وأخرى", 'btn_back_cheat': "🔙 رجوع", 'apk_caption': "📱 **تطبيق Termux (APK)**\n\nهذه هي النسخة الرسمية من Termux! \n\n1. قم بتنزيل الملف.\n2. ثبته على هاتفك.\n3. ابدأ دروسنا! 🚀", 'apk_file_name': "Termux_App.apk", 'apk_loading': "⏳ يرجى الانتظار، يتم تنزيل Termux APK...", 'apk_too_big': "⚠️ **انتباه!**\n\nحجم الملف يتجاوز حد Telegram. يرجى تنزيل عبر الرابط المباشر:\n\n👇 [تنزيل Termux](https://github.com/termux/termux-app/releases/download/v0.118.0/termux-app_v0.118.0+github-debug_universal.apk)", 'apk_error': "❌ **خطأ!** تعذر تنزيل ملف APK.", 'support_prompt': "✉️ **التواصل مع المسؤول**\n\nيرجى كتابة سؤالك أو مشكلتك في رسالة واحدة. سنرد قريبا.", 'support_sent': "✅ **تم إرسال رسالتك!**\n\nسيتصل بك المسؤول قريبا.", 'support_reply': "📬 **رد المسؤول:**\n\n", 'quiz_start': "🧠 **اختبر معلوماتك!**\n\nاختر الإجابة الصحيحة للسؤال التالي:", 'quiz_correct': "✅ **إجابة صحيحة! أحسنت!** 🎉", 'quiz_wrong': "❌ **إجابة خاطئة!**\n\nالإجابة الصحيحة هي: **{answer}**", 'btn_next_quiz': "➡️ السؤال التالي"}
}

TIPS = [
    {'uz': "**Tezroq kod yozish:**\n`nano` o'rniga `micro` matn muharririni ishlatib ko'ring. U yanada qulay va sichqonchani qo'llab-quvvatlaydi.\nO'rnatish: `pkg install micro`", 'ru': "**Быстрое написание кода:**\nПопробуйте использовать текстовый редактор `micro` вместо `nano`. Он более удобен и поддерживает мышь.\nУстановка: `pkg install micro`", 'en': "**Faster coding:**\nTry using the `micro` text editor instead of `nano`. It is more convenient and supports mouse.\nInstall: `pkg install micro`", 'ar': "**برمجة أسرع:**\nجرب استخدام محرر النصوص `micro` بدلاً من `nano`. إنه أكثر ملاءمة ويدعم الماوس.\nالتثبيت: `pkg install micro`"},
    {'uz': "**Termuxni chiroyli qilish:**\nTermuxga kirganda chiqadigan zerikarli yozuvni o'zgartirish mumkin.\nO'rnatish: `pkg install figlet`\nKeyin: `figlet Salom` deb yozing.", 'ru': "**Сделайте Termux красивым:**\nСкучный текст, появляющийся при входе в Termux, можно изменить.\nУстановка: `pkg install figlet`\nЗатем напишите: `figlet Hello`", 'en': "**Make Termux beautiful:**\nYou can change the boring text that appears when you enter Termux.\nInstall: `pkg install figlet`\nThen type: `figlet Hello`", 'ar': "**اجعل Termux جميلاً:**\nيمكنك تغيير النص الممل الذي يظهر عند دخولك إلى Termux.\nالتثبيت: `pkg install figlet`\nثم اكتب: `figlet Hello`"}
]

COMMANDS_DATA = {
    'files': [('ls', {'uz': 'Fayllar ro\'yxati', 'ru': 'Список файлов', 'en': 'List files', 'ar': 'قائمة الملفات'}), ('cd papka', {'uz': 'Papkaga kirish', 'ru': 'Войти в папку', 'en': 'Enter folder', 'ar': 'الدخول إلى مجلد'}), ('mkdir name', {'uz': 'Papka yaratish', 'ru': 'Создать папку', 'en': 'Create folder', 'ar': 'إنشاء مجلد'})],
    'packages': [('pkg update', {'uz': 'Yangilanishlarni tekshirish', 'ru': 'Проверить обновления', 'en': 'Check updates', 'ar': 'التحقق من التحديثات'}), ('pkg install nom', {'uz': 'Dastur o\'rnatish', 'ru': 'Установить программу', 'en': 'Install package', 'ar': 'تثبيت حزمة'})],
    'network': [('ping google.com', {'uz': 'Internetni tekshirish', 'ru': 'Проверить интернет', 'en': 'Check internet', 'ar': 'فحص الإنترنت'})],
    'system': [('clear', {'uz': 'Ekranni tozalash', 'ru': 'Очистить экран', 'en': 'Clear screen', 'ar': 'مسح الشاشة'})]
}

QUIZ_DATA = [
    {'q': {'uz': "Linux'da papka yaratish buyrug'i qaysi?", 'ru': "Какая команда создает папку в Linux?", 'en': "Which command creates a folder in Linux?", 'ar': "ما هو الأمر الذي ينشئ مجلدًا في Linux؟"}, 'options': ['mkdir', 'cd', 'ls', 'rm'], 'answer': 'mkdir'},
    {'q': {'uz': "Termux'da paketlarni o'rnatish uchun qaysi buyruq ishlatiladi?", 'ru': "Какая команда используется для установки пакетов в Termux?", 'en': "Which command is used to install packages in Termux?", 'ar': "ما هو الأمر المستخدم لتثبيت الحزم في Termux؟"}, 'options': ['pkg install', 'apt-get', 'pip install', 'install'], 'answer': 'pkg install'},
    {'q': {'uz': "Ekranni tozalash uchun qaysi buyruq beriladi?", 'ru': "Какая команда очищает экран?", 'en': "Which command clears the screen?", 'ar': "ما هو الأمر الذي يمسح الشاشة؟"}, 'options': ['clear', 'cls', 'clean', 'wipe'], 'answer': 'clear'},
    {'q': {'uz': "Python'da matn chiqarish uchun nima ishlatiladi?", 'ru': "Что используется для вывода текста в Python?", 'en': "What is used to print text in Python?", 'ar': "ماذا يستخدم لطباعة النص في Python؟"}, 'options': ['print()', 'echo()', 'display()', 'output()'], 'answer': 'print()'},
    {'q': {'uz': "Faylni o'chirish uchun qaysi buyruq ishlatiladi?", 'ru': "Какая команда удаляет файл?", 'en': "Which command deletes a file?", 'ar': "ما هو الأمر الذي يحذف ملفًا؟"}, 'options': ['rm', 'del', 'delete', 'erase'], 'answer': 'rm'}
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
        [InlineKeyboardButton(t['btn_support'], callback_data="support_start")],
        [InlineKeyboardButton(t['btn_tip'], callback_data="daily_tip")], 
        [InlineKeyboardButton(t['btn_cheatsheet'], callback_data="cheatsheet")], 
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
    
    if data.startswith("lang_"):
        lang = data.split("_")[1]
        context.user_data['lang'] = lang
        await query.edit_message_text(TEXTS[lang]['welcome'], reply_markup=get_main_menu(lang), parse_mode='Markdown')
        return

    elif data == "change_lang":
        context.user_data.pop('lang', None)
        await query.edit_message_text(TEXTS['uz']['choose_lang'], reply_markup=get_lang_keyboard(), parse_mode='Markdown')
        return

    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]

    if data == "quiz_start":
        question_data = random.choice(QUIZ_DATA)
        context.user_data['current_quiz'] = question_data
        text = t['quiz_start'] + f"\n\n❓ **{question_data['q'][lang]}**"
        keyboard = get_quiz_keyboard(question_data['options'], question_data['answer'], lang)
        try:
            await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='Markdown')
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode='Markdown')

    elif data.startswith("quiz_ans_"):
        selected_ans = data.replace("quiz_ans_", "")
        question_data = context.user_data.get('current_quiz')
        if not question_data:
            return await query.answer("Xatolik yuz berdi. Qaytadan urinib ko'ring.")
        correct_ans = question_data['answer']
        if selected_ans == correct_ans:
            text = t['quiz_correct']
        else:
            text = t['quiz_wrong'].format(answer=correct_ans)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t['btn_next_quiz'], callback_data="quiz_start")],
            [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]
        ])
        try:
            await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='Markdown')
        except Exception:
            pass

    elif data == "support_start":
        context.user_data['state'] = 'in_support'
        text = t['support_prompt']
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])
        try:
            await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='Markdown')
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode='Markdown')

    elif data == "send_apk":
        msg = await context.bot.send_message(chat_id=chat_id, text=t['apk_loading'])
        await query.message.delete()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(TERMUX_APK_URL) as response:
                    if response.status == 200:
                        apk_content = await response.read()
                        if len(apk_content) > 50 * 1024 * 1024:
                            await msg.edit_text(t['apk_too_big'], parse_mode='Markdown', disable_web_page_preview=False)
                        else:
                            apk_file = BytesIO(apk_content)
                            apk_file.name = t['apk_file_name']
                            await context.bot.send_document(
                                chat_id=chat_id, document=apk_file, caption=t['apk_caption'],
                                parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]])
                            )
                            await msg.delete()
                    else:
                        raise Exception(f"HTTP xatosi: {response.status}")
        except Exception as e:
            logging.error(f"APK xatosi: {e}")
            await msg.edit_text(t['apk_error'])
        return

    elif data == "daily_tip":
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

    elif data == "cheatsheet":
        try:
            await query.edit_message_text(text=t['cheatsheet_menu'], reply_markup=get_cheatsheet_keyboard(lang), parse_mode='Markdown')
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=t['cheatsheet_menu'], reply_markup=get_cheatsheet_keyboard(lang), parse_mode='Markdown')

    elif data.startswith("cat_"):
        category = data.split("_")[1]
        commands = COMMANDS_DATA.get(category, [])
        text = f"**{t['cat_'+category]}**\n\n"
        for cmd, desc in commands:
            text += f"• `{cmd}` - {desc[lang]}\n"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t['btn_back_cheat'], callback_data="cheatsheet")],
            [InlineKeyboardButton(t['btn_back'], callback_data="back_to_start")]
        ])
        try:
            await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='Markdown')
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode='Markdown')

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

    elif data == "python_extra":
        try:
            for v_id in PYTHON_EXTRA_VIDEOS:
                await context.bot.copy_message(chat_id=chat_id, from_chat_id=CHANNEL_USERNAME, message_id=v_id)
            back_kb = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="lua_page_1")]])
            await context.bot.send_message(chat_id=chat_id, text=t['text_python_done'], reply_markup=back_kb)
        except TelegramError:
            back_kb = InlineKeyboardMarkup([[InlineKeyboardButton(t['btn_back'], callback_data="lua_page_1")]])
            await context.bot.send_message(chat_id=chat_id, text=t['text_error_py'], reply_markup=back_kb)
        
    elif data == "back_to_start":
        context.user_data['state'] = None
        try:
            await query.edit_message_text(text=t['welcome'], reply_markup=get_main_menu(lang), parse_mode='Markdown')
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=t['welcome'], reply_markup=get_main_menu(lang), parse_mode='Markdown')


# ==========================================
# XABARLARNI QABUL QILISH (SUPPORT VA ADMIN JAVOBI)
# ==========================================
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = context.user_data.get('lang', 'uz')
    t = TEXTS[lang]
    
    if context.user_data.get('state') == 'in_support':
        if update.message.text:
            # Maxsus formatda xabar yuborish (backticksiz)
            admin_msg = f"📩 Yangi murojaat!\n\n👤 Kimdan: {user.first_name} (@{user.username})\n🆔 ID: {user.id}\n\n💬 Xabar: {update.message.text}"
            try:
                await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg)
                await update.message.reply_text(t['support_sent'], reply_markup=get_main_menu(lang))
            except Exception as e:
                logging.error(f"Admin ga xabar yuborishda xato: {e}")
                await update.message.reply_text("❌ Xatolik yuz berdi. Iltimos keyinroq urinib ko'ring.")
            context.user_data['state'] = None
        return

    if user.id == ADMIN_ID and update.message.reply_to_message:
        original_text = update.message.reply_to_message.text or ""
        
        # Endi faqat ID: dan keyingi raqamlarni qidiramiz (backticksiz va xavfsiz usul)
        match = re.search(r'🆔 ID:\s*(\d+)', original_text)
        
        if match:
            target_user_id = int(match.group(1))
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"{t['support_reply']}{update.message.text}"
                )
                await update.message.reply_text("✅ Javobingiz foydalanuvchiga yuborildi!")
            except Exception as e:
                await update.message.reply_text(f"❌ Xatolik: {e}")
        else:
            await update.message.reply_text("❌ Foydalanuvchi ID sini aniqlab bo'lmadi.")


# ==========================================
# VEB SERVER VA WEBHOOK QISMI
# ==========================================
application = Application.builder().token(TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(button_tap))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))

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
