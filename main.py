import os
import logging
import threading
import uvicorn
import asyncio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Render'dagi Environment Variables'dan tokenni oladi
TOKEN = os.environ.get("TOKEN", "SIZNING_TOKENINGIZNI_SHU_YERGA_YOZING")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==========================================
# 1. VEB SERVER QISMI (FastAPI - HTML uchun)
# ==========================================
app = FastAPI()

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

# ==========================================
# 2. TELEGRAM BOT QISMI
# ==========================================
LESSONS = {
    1: "https://t.me/termux_tutoril/3", 2: "https://t.me/termux_tutoril/4", 3: "https://t.me/termux_tutoril/5",
    4: "https://t.me/termux_tutoril/6", 5: "https://t.me/termux_tutoril/7", 6: "https://t.me/termux_tutoril/8",
    7: "https://t.me/termux_tutoril/9", 8: "https://t.me/termux_tutoril/10", 9: "https://t.me/termux_tutoril/11",
    10: "https://t.me/termux_tutoril/12", 11: "https://t.me/termux_tutoril/13", 12: "https://t.me/termux_tutoril/14",
    13: "https://t.me/termux_tutoril/15", 14: "https://t.me/termux_tutoril/16", 15: "https://t.me/termux_tutoril/17",
    16: "https://t.me/termux_tutoril/18", 17: "https://t.me/termux_tutoril/19", 18: "https://t.me/termux_tutoril/20",
    19: "https://t.me/termux_tutoril/21", 20: "https://t.me/termux_tutoril/22", 21: "https://t.me/termux_tutoril/23",
    22: "https://t.me/termux_tutoril/24", 23: "https://t.me/termux_tutoril/25", 24: "https://t.me/termux_tutoril/26",
    25: "https://t.me/termux_tutoril/27", 26: "https://t.me/termux_tutoril/28", 27: "https://t.me/termux_tutoril/29",
    28: "https://t.me/termux_tutoril/30", 29: "https://t.me/termux_tutoril/31", 30: "https://t.me/termux_tutoril/32",
    31: "https://t.me/termux_tutoril/33", 32: "https://t.me/termux_tutoril/34", 33: "https://t.me/termux_tutoril/35",
    34: "https://t.me/termux_tutoril/36", 35: "https://t.me/termux_tutoril/37", 36: "https://t.me/termux_tutoril/38",
    37: "https://t.me/termux_tutoril/39", 38: "https://t.me/termux_tutoril/40", 39: "https://t.me/termux_tutoril/41",
    40: "https://t.me/termux_tutoril/42", 41: "https://t.me/termux_tutoril/43", 42: "https://t.me/termux_tutoril/44",
    43: "https://t.me/termux_tutoril/45", 44: "https://t.me/termux_tutoril/46", 45: "https://t.me/termux_tutoril/47",
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info_text = (
        "👋 **Assalomu alaykum!**\n\n"
        "Men **Termux va Dasturlash** bo'yicha yordamchi botman.\n\n"
        "📚 **45 ta video darslik** tayyor. Ko'rish uchun pastdagi tugmani bosing:"
    )
    keyboard = [
        [InlineKeyboardButton("🎥 Videodarsliklarni ko'rish", callback_data="page_1")],
        [InlineKeyboardButton("📢 Bizning kanal", url="https://t.me/termux_tutoril")]
    ]
    await update.message.reply_text(info_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def get_lessons_keyboard(page=1):
    keyboard = []
    start_idx = (page - 1) * 10 + 1
    end_idx = min(page * 10, 45)
    row = []
    for i in range(start_idx, end_idx + 1):
        row.append(InlineKeyboardButton(f"🎬 {i}-darslik", url=LESSONS[i]))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    nav_row = []
    if page > 1: nav_row.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"page_{page-1}"))
    if end_idx < 45: nav_row.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_{page+1}"))
    if nav_row: keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton("🔙 Bosh menyu", callback_data="back_to_start")])
    return InlineKeyboardMarkup(keyboard)

async def button_tap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("page_"):
        page = int(query.data.split("_")[1])
        text = f"📚 **Videodarsliklar**\n\nSahifa: {page} / 5"
        await query.edit_message_text(text=text, reply_markup=get_lessons_keyboard(page), parse_mode='Markdown')
    elif query.data == "back_to_start":
        await start(update, context)

def run_telegram_bot():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_tap))
    
    # ENG MUHIM QISM: Eski webhook va xabarlarni majburiy tozalash
    try:
        print("Eski webhook tozalanmoqda...")
        asyncio.run(application.bot.delete_webhook(drop_pending_updates=True))
    except Exception as e:
        print(f"Webhook tozalashda xatolik: {e}")

    print("Telegram bot ishga tushdi...")
    application.run_polling()

# ==========================================
# 3. ASOSIY ISHGA TUSHIRISH
# ==========================================
if __name__ == "__main__":
    # Botni orqa fonda ishga tushirish
    threading.Thread(target=run_telegram_bot, daemon=True).start()
    
    # Veb-serverni Render portida ishga tushirish
    port = int(os.environ.get("PORT", 8080))
    print(f"Veb-server {port}-portda ishga tushdi...")
    uvicorn.run(app, host="0.0.0.0", port=port)
