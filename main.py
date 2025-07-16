import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, BufferedInputFile
from aiogram.filters import Command
from aiogram.utils.webhook import set_webhook
from datetime import datetime, timedelta
from app.database import (
    add_user_subscription,
    get_user,
    remove_user_subscription,
    get_all_users,
)
from app.utils import is_admin, get_env
from app.scheduler import scheduler
from app.keep_alive import keep_alive

# Load ENV variables
BOT_TOKEN = get_env("BOT_TOKEN")
ADMIN_ID = int(get_env("ADMIN_ID"))
GROUP_ID = int(get_env("GROUP_ID"))
WEBHOOK_URL = get_env("WEBHOOK_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

SUBSCRIPTIONS = {
    "1 Oy": 20000,
    "3 Oy": 55000,
    "6 Oy": 110000,
    "12 Oy": 200000
}

# --- START ---
@dp.message(Command("start"))
async def start(message: Message):
    if await bot.get_chat_member(GROUP_ID, message.from_user.id):
        await message.answer("✅ Siz premium obunaga allaqachon qo‘shilgansiz!")
        return

    buttons = [
        [f"💳 {duration} - {price} so‘m"] for duration, price in SUBSCRIPTIONS.items()
    ]
    keyboard = [[{"text": btn[0]}] for btn in buttons]

    await message.answer(
        "👋 Salom! Premium kanalga kirish uchun to‘lov qilishingiz kerak.\n\n"
        "💳 *Humo karta*: 9860 0866 0355 0863\n"
        "👤 Egasi: Rahimberganov Xushnudbek\n\n"
        "✅ Pastdagi obunalardan birini tanlab to‘lov qilib, chekni yuboring.\n"
        "Admin tekshiradi va tasdiqlasa sizga kanal linki keladi.",
        reply_markup={"keyboard": keyboard, "resize_keyboard": True},
        parse_mode="Markdown"
    )

# --- HANDLE SUBSCRIPTION SELECTION ---
@dp.message(F.text.in_(SUBSCRIPTIONS.keys()))
async def choose_subscription(message: Message):
    duration = message.text
    await message.answer(
        f"✅ Siz {duration} muddatli obunani tanladingiz.\n"
        f"💵 To‘lov summasi: {SUBSCRIPTIONS[duration]} so‘m\n"
        "🧾 Endi to‘lov kvitansiyasini rasm yoki PDF ko‘rinishida yuboring."
    )
    # Save choice to user state
    user = await get_user(message.from_user.id)
    user['selected_duration'] = duration

# --- HANDLE RECEIPT (Image or PDF) ---
@dp.message(F.content_type.in_(["photo", "document"]))
async def handle_receipt(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)

    if user is None or "selected_duration" not in user:
        await message.answer("❌ Avval obuna muddatini tanlang.")
        return

    receipt_file = await message.bot.get_file(message.photo[-1].file_id if message.photo else message.document.file_id)
    receipt_link = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{receipt_file.file_path}"

    # Send to admin
    await bot.send_message(
        ADMIN_ID,
        f"🧾 Yangi kvitansiya!\n👤 {message.from_user.full_name} ({user_id})\n"
        f"📅 Obuna: {user['selected_duration']}\n"
        "Tasdiqlaysizmi?"
    )
    await bot.send_photo(ADMIN_ID, receipt_link)
    await bot.send_message(
        ADMIN_ID,
        f"/confirm {user_id} ✅\n/reject {user_id} ❌",
    )
    await message.answer("✅ To‘lov kvitansiyasi yuborildi. Admin tasdiqlashini kuting.")

# --- ADMIN CONFIRMATION ---
@dp.message(Command("confirm"))
async def confirm_subscription(message: Message):
    if not is_admin(message.from_user.id, ADMIN_ID):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ User ID-ni kiriting: /confirm USER_ID")
        return

    user_id = int(args[1])
    user = await get_user(user_id)
    if user is None:
        await message.answer("❌ Foydalanuvchi topilmadi.")
        return

    duration = user['selected_duration']
    months = int(duration.split()[0])
    expire_date = datetime.now() + timedelta(days=30 * months)

    await add_user_subscription(user_id, user['selected_duration'], expire_date)
    await bot.add_chat_members(GROUP_ID, [user_id])
    await message.answer(f"✅ {user_id} foydalanuvchi {duration} muddatga qo‘shildi.")
    await bot.send_message(user_id, "🎉 Siz premium obunaga qo‘shildingiz!")

# --- ADMIN REJECTION ---
@dp.message(Command("reject"))
async def reject_subscription(message: Message):
    if not is_admin(message.from_user.id, ADMIN_ID):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ User ID-ni kiriting: /reject USER_ID")
        return

    user_id = int(args[1])
    await bot.send_message(user_id, "❌ To‘lov kvitansiyangiz rad etildi.")
    await message.answer(f"⛔ {user_id} foydalanuvchining so‘rovi rad etildi.")

# --- ADMIN REMOVE USER ---
@dp.message(Command("remove"))
async def remove_user(message: Message):
    if not is_admin(message.from_user.id, ADMIN_ID):
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ User ID-ni kiriting: /remove USER_ID")
        return

    user_id = int(args[1])
    await remove_user_subscription(user_id)
    await bot.ban_chat_member(GROUP_ID, user_id)
    await bot.unban_chat_member(GROUP_ID, user_id)
    await message.answer(f"❌ {user_id} foydalanuvchi obunadan chiqarildi.")
    await bot.send_message(user_id, "❌ Siz premium obunadan chiqarildingiz.")

# --- ADMIN VIEW USERS ---
@dp.message(Command("users"))
async def list_users(message: Message):
    if not is_admin(message.from_user.id, ADMIN_ID):
        return

    users = await get_all_users()
    if not users:
        await message.answer("👥 Hech qanday foydalanuvchi obuna bo‘lmagan.")
        return

    response = "📜 Obunachilar:\n"
    for user in users:
        response += (
            f"👤 ID: {user['user_id']}, "
            f"Username: {user['username']}\n"
            f"📅 Tugash: {user['expire_date']}\n\n"
        )
    await message.answer(response)

# Start Webhook
async def on_startup(dispatcher):
    await set_webhook(bot=bot, url=WEBHOOK_URL)
    print("✅ Webhook o‘rnatildi.")

keep_alive()
dp.start_polling(bot, on_startup=on_startup)
