import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums.chat_member_status import ChatMemberStatus

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL = os.getenv("TELEGRAM_CHANNEL_ID")  # @username или -100...

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

WELCOME = (
    "Добро пожаловать 🌙\n\n"
    "Это проводник AWAIKING BOT — здесь практики, мягкая сила и пробуждение.\n"
    "Шаг 1: подпишись на наш канал ниже, вернись и нажми «Проверить подписку».\n"
    "Шаг 2: выбери продукт — 📘 Гайд или 🎥 Видео+Гайд.\n"
)

def kb_sub():
    kb = InlineKeyboardBuilder()
    url = f"https://t.me/{CHANNEL.replace('@','')}" if CHANNEL and CHANNEL.startswith('@') else "https://t.me/"
    kb.button(text="Подписаться на канал", url=url)
    kb.button(text="Проверить подписку", callback_data="check_sub")
    kb.button(text="Открыть меню", callback_data="open_menu")
    kb.adjust(1)
    return kb.as_markup()

def kb_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="📘 Гайд — 490₽", callback_data="buy:guide")
    kb.button(text="🎥 Видео+Гайд — 990₽", callback_data="buy:video")
    kb.adjust(1)
    return kb.as_markup()

def kb_pay(link: str | None = None):
    kb = InlineKeyboardBuilder()
    if link:
        kb.button(text="Оплатить", url=link)
    kb.button(text="Я оплатила", callback_data="paid_check")
    kb.button(text="Назад в меню", callback_data="open_menu")
    kb.adjust(1)
    return kb.as_markup()

@dp.message(CommandStart())
async def start(m: Message):
    await m.answer(WELCOME, reply_markup=kb_sub())

@dp.callback_query(F.data == "check_sub")
async def check_sub(c: CallbackQuery):
    try:
        member = await bot.get_chat_member(CHANNEL, c.from_user.id)
        ok = member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
    except Exception:
        ok = False
    if ok:
        await c.message.edit_text("Подписка есть ✅\nВыбери продукт:", reply_markup=kb_menu())
    else:
        await c.message.edit_text("Похоже, подписки пока нет 🤍\nНажми «Подписаться», затем «Проверить подписку».", reply_markup=kb_sub())
    await c.answer()

@dp.callback_query(F.data == "open_menu")
async def open_menu(c: CallbackQuery):
    await c.message.edit_text("Выбери продукт:", reply_markup=kb_menu())
    await c.answer()

@dp.callback_query(F.data.startswith("buy:"))
async def buy(c: CallbackQuery):
    product = c.data.split(":")[1]
    price = 490 if product == "guide" else 990
    fake_url = "https://yookassa.ru/"   # заглушка, подключим позже
    await c.message.edit_text(
        f"К оплате: {'📘 Гайд' if product=='guide' else '🎥 Видео+Гайд'} — {price}₽\n\n"
        "Открой ссылку для оплаты и вернись сюда, затем нажми «Я оплатила».",
        reply_markup=kb_pay(fake_url)
    )
    await c.answer()

@dp.callback_query(F.data == "paid_check")
async def paid_check(c: CallbackQuery):
    doc = os.getenv("DOC_URL", "https://docs.google.com/")
    tilda = os.getenv("TILDA_PAGE_URL", "https://tilda.cc/")
    pwd = os.getenv("TILDA_PAGE_PASSWORD", "PASSWORD")
    await c.message.edit_text(
        "✨ Благодарю за доверие!\n\n"
        f"🎥 Видео (под паролем):\n{tilda}\nПароль: {pwd}\n\n"
        f"📘 Гайд (только просмотр):\n{doc}\n\n"
        "Пусть практика мягко ведёт тебя 🌸"
    )
    await c.answer()

if __name__ == "__main__":
    import asyncio
    dp.run_polling(bot)
