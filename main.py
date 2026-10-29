import os
import logging
from fastapi import FastAPI, Request, Response
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
    raise ValueError("Xatolik: TOKEN yoki RENDER_EXTERNAL_URL Render'dagi Environment'da kiritilmagan!")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==========================================
# VIDEOLAR MA'LUMOTLARI
# ==========================================
CHANNEL_USERNAME = "@termux_tutoril" 

# Asosiy Termux darsliklari (45 ta)
LESSONS = {
    1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 8, 7: 9, 8: 10, 9: 11, 10: 12,
    11: 13, 12: 14, 13: 15, 14: 16, 15: 17, 16: 18, 17: 19, 18: 20, 19: 21, 20: 22,
    21: 23, 22: 24, 23: 25, 24: 26, 25: 27, 26: 28, 27: 29, 28: 30, 29: 31, 30: 32,
    31: 33, 32: 34, 33: 35, 34: 36, 35: 37, 36: 38, 37: 39, 38: 40, 39: 41, 40: 42,
    41: 43, 42: 44, 43: 45, 44: 46, 45: 47
}

# Yangi Lua darsliklari
LUA_LESSONS = {
    1: 93, 
    2: 94, 
    3: 97, 
    4: 98, 
    5: 99, 
    6: 100, 
    7: 101
}

# "PYTHON OLISH" tugmasi uchun videolar (95 olib tashlandi)
PYTHON_EXTRA_VIDEOS = [96]

# /start buyrug'i
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info_text = (
        "👋 **Assalomu alaykum!**\n\n"
        "Men **Termux va Dasturlash** bo'yicha yordamchi botman.\n\n"
        "📚 TERMUX UCHUN maxsus video darsliklar tayyor"
    )
    keyboard = [
        [InlineKeyboardButton("📽️ TERMUX VIDEO DARSLIKLAR", callback_data="page_1")],
        [InlineKeyboardButton("📽️ TERMUX LUA PAK VIDEO DARSLIK", callback_data="lua_page_1")],
        [InlineKeyboardButton("Murojaat uchun", url="https://t.me/Tommy_1727")]
    ]
    await update.message.reply_text(info_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# Asosiy darsliklar menyusi
def get_lessons_keyboard(page=1):
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
    if page > 1: nav_row.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"page_{page-1}"))
    if end_idx < 45: nav_row.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_{page+1}"))
    if nav_row: keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton("🔙 Bosh menyu", callback_data="back_to_start")])
    return InlineKeyboardMarkup(keyboard)

# Lua darsliklar menyusi
def get_lua_lessons_keyboard():
    keyboard = []
    row = []
    for i in range(1, 8):
        row.append(InlineKeyboardButton(f"🎬 {i}-darslik", callback_data=f"lua_lesson_{i}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("🔙 Bosh menyu", callback_data="back_to_start")])
    return InlineKeyboardMarkup(keyboard)


# Tugmalar bosilganda
async def button_tap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id
    
    # 1. ASOSIY DARSLIKLAR
    if data.startswith("page_"):
        page = int(data.split("_")[1])
        text = f"📚 **Video darsliklar**\n\nSahifa: {page} / 5\nO'zingizga kerakli darslikni tanlang:"
        try:
            await query.edit_message_text(text=text, reply_markup=get_lessons_keyboard(page), parse_mode='Markdown')
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=get_lessons_keyboard(page), parse_mode='Markdown')
            
    elif data.startswith("lesson_"):
        lesson_num = int(data.split("_")[1])
        message_id = LESSONS[lesson_num]
        video_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📚 Darsliklar (Menyu)", callback_data="page_1")]])
        try:
            await context.bot.copy_message(chat_id=chat_id, from_chat_id=CHANNEL_USERNAME, message_id=message_id, reply_markup=video_keyboard)
            await query.message.delete()
        except TelegramError:
            await context.bot.send_message(chat_id=chat_id, text="❌ **Xatolik!** Videoni yuklab bo'lmadi.", parse_mode='Markdown')

    # 2. LUA DARSLIKLARI
    elif data == "lua_page_1":
        text = "📚 **TERMUX LUA PAK DARSLIKLARI**\n\nKerakli darslikni tanlang:"
        try:
            await query.edit_message_text(text=text, reply_markup=get_lua_lessons_keyboard(), parse_mode='Markdown')
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=get_lua_lessons_keyboard(), parse_mode='Markdown')

    elif data.startswith("lua_lesson_"):
        lesson_num = int(data.split("_")[2])
        message_id = LUA_LESSONS[lesson_num]
        buttons = []
        
        # 2-darslik bo'lsa "PYTHON OLISH" tugmasini qo'shamiz
        if lesson_num == 2:
            buttons.append([InlineKeyboardButton("🐍 PYTHON OLISH", callback_data="python_extra")])
            
        buttons.append([InlineKeyboardButton("📚 Darsliklar (Menyu)", callback_data="lua_page_1")])
        video_keyboard = InlineKeyboardMarkup(buttons)
        
        try:
            await context.bot.copy_message(chat_id=chat_id, from_chat_id=CHANNEL_USERNAME, message_id=message_id, reply_markup=video_keyboard)
            await query.message.delete()
        except TelegramError:
            await context.bot.send_message(chat_id=chat_id, text="❌ **Xatolik!** Videoni yuklab bo'lmadi.", parse_mode='Markdown')

    # 3. PYTHON MAXSUS VIDEOLARI
    elif data == "python_extra":
        try:
            # Faqat 96-videoni tashlaymiz
            for v_id in PYTHON_EXTRA_VIDEOS:
                await context.bot.copy_message(chat_id=chat_id, from_chat_id=CHANNEL_USERNAME, message_id=v_id)
            
            back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Lua darsliklariga qaytish", callback_data="lua_page_1")]])
            await context.bot.send_message(chat_id=chat_id, text="Mana siz so'ragan Python darsligi! ✅", reply_markup=back_kb)
            
        except TelegramError:
            # Agar video o'chirilgan yoki bot ko'chira olmasa, shu xabar chiqadi
            back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga qaytish", callback_data="lua_page_1")]])
            await context.bot.send_message(chat_id=chat_id, text="❌ **Xatolik!** Python videosini yuklab bo'lmadi. U kanaldan o'chirilgan yoki botga ruxsat berilmagan bo'lishi mumkin.", reply_markup=back_kb)
        
    # 4. BOSH MENYU
    elif data == "back_to_start":
        info_text = (
            "👋 **Assalomu alaykum!**\n\n"
            "Men **Termux va Dasturlash** bo'yicha yordamchi botman.\n\n"
            "📚 TERMUX UCHUN maxsus video darsliklar tayyor"
        )
        keyboard = [
            [InlineKeyboardButton("📽️ TERMUX VIDEO DARSLIKLAR", callback_data="page_1")],
            [InlineKeyboardButton("📽️ TERMUX LUA PAK VIDEO DARSLIK", callback_data="lua_page_1")],
            [InlineKeyboardButton("Murojaat uchun", url="https://t.me/Tommy_1727")]
        ]
        try:
            await query.edit_message_text(text=info_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=info_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

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
