import os
import logging
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import uvicorn

# ==========================================
# XAVFSIZLIK QISMI: Barcha maxfiy ma'lumotlar faqat Render'dan olinadi
# ==========================================
TOKEN = os.environ.get("TOKEN")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")

if not TOKEN or not RENDER_EXTERNAL_URL:
    raise ValueError("Xatolik: TOKEN yoki RENDER_EXTERNAL_URL Render'dagi Environment'da kiritilmagan!")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==========================================
# TELEGRAM BOT QISMI (Handlers)
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
        [InlineKeyboardButton("📽️ Video darsliklarni koʻrish", callback_data="page_1")],
        [InlineKeyboardButton("Murojaat uchun", url="https://t.me/Tommy_1727")]
    ]
    await update.message.reply_text(info_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def get_lessons_keyboard(page=1):
    keyboard = []
    start_idx = (page - 1) * 10 + 1
    end_idx = min(page * 10, 45)
    row = []
    for i in range(start_idx, end_idx + 1):
        # BU YERDA url O'RNIGA callback_data ISHLATILDI
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

async def button_tap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    # Sahifalarni almashtirish
    if data.startswith("page_"):
        page = int(data.split("_")[1])
        text = f"📚 **Video darsliklar**\n\nSahifa: {page} / 5\nO'zingizga kerakli darslikni tanlang:"
        await query.edit_message_text(text=text, reply_markup=get_lessons_keyboard(page), parse_mode='Markdown')
        
    # Darslik tanlanganda
    elif data.startswith("lesson_"):
        lesson_num = int(data.split("_")[1])
        link = LESSONS[lesson_num]
        
        # 1. Bot chatiga darslik havolasini yuborish
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"🎬 **{lesson_num}-darslik**\n\n👉 [Videoni ko'rish uchun shu yerni bosing]({link})",
            parse_mode='Markdown'
        )
        
        # 2. Qaysi sahifada turgan bo'lsa, o'sha sahifadagi menyuni qaytadan ochish
        page = ((lesson_num - 1) // 10) + 1
        text = f"📚 **Video darsliklar**\n\nSahifa: {page} / 5\nO'zingizga kerakli darslikni tanlang:"
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=text,
            reply_markup=get_lessons_keyboard(page),
            parse_mode='Markdown'
        )
        
    # Bosh menyuga qaytish
    elif data == "back_to_start":
        info_text = (
            "👋 **Assalomu alaykum!**\n\n"
            "Men **Termux va Dasturlash** bo'yicha yordamchi botman.\n\n"
            "📚 **45 ta video darslik** tayyor. Ko'rish uchun pastdagi tugmani bosing:"
        )
        keyboard = [
            [InlineKeyboardButton("📽️ Video darsliklarni koʻrish", callback_data="page_1")],
            [InlineKeyboardButton("Murojaat uchun", url="https://t.me/Tommy_1727")]
        ]
        await query.edit_message_text(text=info_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# Telegram Application-ni yaratish
application = Application.builder().token(TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(button_tap))

# ==========================================
# VEB SERVER VA WEBHOOK QISMI (FastAPI)
# ==========================================
app = FastAPI()

@app.on_event("startup")
async def on_startup():
    await application.initialize()
    webhook_url = f"{RENDER_EXTERNAL_URL}/webhook/{TOKEN}"
    await application.bot.set_webhook(url=webhook_url)
    print(f"✅ Webhook muvaffaqiyatli o'rnatildi.")

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
    return "<h1 style='color:green; font-family:sans-serif;'>Bot va API muvaffaqiyatli ishlayapti!</h1>"

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
