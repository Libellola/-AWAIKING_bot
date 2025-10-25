import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums.chat_member_status import ChatMemberStatus
from yookassa import Configuration, Payment

# ---------- ЛОГИ ----------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

# ---------- ENV ----------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL = os.getenv("TELEGRAM_CHANNEL_ID")          # @username или -100...
TILDA_PAGE_URL = os.getenv("TILDA_PAGE_URL")

YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is empty")

USE_YOOKASSA_API = bool(YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY)
if USE_YOOKASSA_API:
    Configuration.account_id = YOOKASSA_SHOP_ID
    Configuration.secret_key = YOOKASSA_SECRET_KEY
    log.info("YooKassa: keys detected, API mode ON")
else:
    log.warning("YooKassa: keys NOT set, API mode OFF")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ---------- STATE ----------
PURCHASED: set[int] = set()
SESSIONS: dict[int, str] = {}
PAYMENTS: dict[int, str] = {}   # user_id -> payment_id

# ---------- PRODUCT ----------
PRODUCTS = {
    "KLYUCH": {
        "title": "Ветка «КЛЮЧ»",
        "tilda_url": TILDA_PAGE_URL,
        "price_rub": 568,
        "description": "Материалы по программе «КЛЮЧ»"
    }
}
DEFAULT_PRODUCT_KEY = "KLYCH" if False else "KLYUCH"  # не трогаем, просто страховка :)

# ---------- TEXTS ----------
TEXT_WELCOME = (
    "Я рада видеть тебя в моём пространстве. Это значит, что ты на верном пути и готова к кардинальным переменам...\n\n"
    "Хочешь узнать, что это и как это работает? Жми на кнопку ниже (пиши «ХОЧУ»)."
)
TEXT_OFFER = (
    "Мне пришлось пройти немалый путь... "
    f"Если ты готова — жми «Купить». Сейчас — всего за {PRODUCTS[DEFAULT_PRODUCT_KEY]['price_rub']} руб."
)
TEXT_REMINDER = (
    "Ты до сих пор не забрала продукты, которые быстро дают рабочие инструменты? "
    "Это не магия — это работает. Жми «Купить»."
)
TEXT_PAY_FIRST = (
    "🔒 Доступ выдаётся только после успешной оплаты.\n"
    "Если уже оплатила, подожди 10–30 сек и нажми «✅ Я оплатила» ещё раз."
)

# ---------- KEYBOARDS ----------
def kb_want():
    kb = InlineKeyboardBuilder()
    kb.button(text="ХОЧУ", callback_data="want")
    return kb.as_markup()

def kb_sub():
    kb = InlineKeyboardBuilder()
    url = f"https://t.me/{CHANNEL.replace('@','')}" if CHANNEL and CHANNEL.startswith("@") else "https://t.me/"
    kb.button(text="💫 Подписаться на канал", url=url)
    kb.button(text="✅ Проверить подписку", callback_data="check_sub")
    kb.adjust(1)
    return kb.as_markup()

def kb_pay(url: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Перейти к оплате", url=url)
    kb.button(text="✅ Я оплатила", callback_data="paid_check")
    kb.adjust(1)
    return kb.as_markup()

def kb_access(tilda_url: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎥 Открыть страницу с материалами", url=tilda_url)
    kb.adjust(1)
    return kb.as_markup()

# ---------- HELPERS ----------
def parse_payload(text: str | None) -> str:
    text = (text or "").strip()
    parts = text.split(maxsplit=1)
    if len(parts) == 2 and parts[0].startswith("/start"):
        return parts[1].upper()
    if text.startswith("/start") and len(text) > 6:
        return text[6:].upper()
    return DEFAULT_PRODUCT_KEY

async def schedule_reminder(chat_id: int, product_key: str):
    """Через 1 час напомним, если не оплатила."""
    try:
        await asyncio.sleep(60 * 60)
        if chat_id not in PURCHASED:
            await bot.send_message(chat_id, TEXT_REMINDER)
    except Exception as e:
        log.warning("Reminder error: %r", e)

def create_payment(user_id: int, product_key: str) -> str:
    """Создать платёж в YooKassa и вернуть confirmation_url."""
    if not USE_YOOKASSA_API:
        raise RuntimeError("YooKassa API keys are not configured")

    product = PRODUCTS.get(product_key, PRODUCTS[DEFAULT_PRODUCT_KEY])
    amount = product["price_rub"]
    description = (product.get("description") or product["title"])[:128]

    payment = Payment.create({
        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
        "capture": True,
        "confirmation": {"type": "redirect"},
        "description": f"{description} (user_id={user_id})",
        "metadata": {"user_id": user_id, "product_key": product_key}
    })
    PAYMENTS[user_id] = payment.id
    return payment.confirmation.confirmation_url

async def wait_payment_succeeded(user_id: int, retries: int = 6, delay_sec: float = 5.0) -> bool:
    """Опрос статуса платежа до ~30 сек."""
    pid = PAYMENTS.get(user_id)
    if not pid:
        return False
    for _ in range(retries):
        try:
            p = Payment.find_one(pid)
            if p.status == "succeeded":
                return True
            if p.status in ("canceled",):
                return False
        except Exception as e:
            log.warning("YooKassa find_one error: %r", e)
        await asyncio.sleep(delay_sec)
    return False
# ========= Напоминание об оплате =========
async def schedule_reminder(chat_id: int, product_key: str):
    # через 1 час напомним, если пользователь ещё не оплатил
    await asyncio.sleep(60 * 60)
    if chat_id in PURCHASED:
        return
    try:
        await bot.send_message(
            chat_id,
            TEXT_REMINDER,
            reply_markup=kb_pay(create_payment(chat_id, product_key)) if USE_YOOKASSA_API else None
        )
    except Exception as e:
        print("REMINDER ERROR:", repr(e))

async def send_access(chat_id: int, product_key: str):
    product = PRODUCTS.get(product_key, PRODUCTS[DEFAULT_PRODUCT_KEY])
    await bot.send_message(
        chat_id,
        "✨ Благодарю за доверие!\n\n"
        "Нажми кнопку ниже, чтобы открыть доступ.\n\n"
        "Пусть практика мягко ведёт тебя 🌸",
        reply_markup=kb_access(product["tilda_url"]),
        disable_web_page_preview=True
    )

# ---------- HANDLERS ----------
@dp.message(CommandStart())
async def on_start(m: Message):
    key = parse_payload(m.text)
    if key not in PRODUCTS:
        key = DEFAULT_PRODUCT_KEY
    SESSIONS[m.chat.id] = key
    await m.answer(TEXT_WELCOME, reply_markup=kb_want())

@dp.callback_query(F.data == "want")
async def on_want(c: CallbackQuery):
    await c.message.edit_text(
        "Шаг 1: подпишись на канал, вернись и нажми «Проверить подписку».",
        reply_markup=kb_sub()
    )
    await c.answer()

@dp.callback_query(F.data == "check_sub")
async def on_check_sub(c: CallbackQuery):
    ok = False
    try:
        member = await bot.get_chat_member(CHANNEL, c.from_user.id)
        ok = member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR
        )
    except Exception:
        ok = False

    if ok:
        product_key = SESSIONS.get(c.from_user.id, DEFAULT_PRODUCT_KEY)
        if not USE_YOOKASSA_API:
            await c.message.edit_text("Платёжный модуль пока не настроен.")
        else:
            try:
                pay_url = create_payment(c.from_user.id, product_key)
                await c.message.edit_text(TEXT_OFFER, reply_markup=kb_pay(pay_url))
            except Exception as e:
                log.error("YooKassa create error: %r", e)
                await c.message.edit_text("Что-то пошло не так при создании платежа. Попробуй ещё раз позже.")
        # ВАЖНО: теперь функция реально существует
        asyncio.create_task(schedule_reminder(c.from_user.id, product_key))
    else:
        await c.message.edit_text(
            "Похоже, подписки пока нет 🤍\nНажми «💫 Подписаться на канал», затем «✅ Проверить подписку».",
            reply_markup=kb_sub()
        )
    await c.answer()

@dp.callback_query(F.data == "paid_check")
async def on_paid_check(c: CallbackQuery):
    product_key = SESSIONS.get(c.from_user.id, DEFAULT_PRODUCT_KEY)

    if not USE_YOOKASSA_API:
        await c.message.edit_text("Платёжный модуль пока не настроен.")
        await c.answer()
        return

    if c.from_user.id not in PAYMENTS:
        # не создавали платёж — создадим сейчас
        try:
            pay_url = create_payment(c.from_user.id, product_key)
            await c.message.edit_text(TEXT_PAY_FIRST, reply_markup=kb_pay(pay_url))
            await c.answer()
            return
        except Exception as e:
            log.error("YooKassa create (from paid_check) error: %r", e)
            await c.message.edit_text("Не получилось создать платёж. Нажми «Купить» ещё раз.")
            await c.answer()
            return

    ok = await wait_payment_succeeded(c.from_user.id, retries=6, delay_sec=5.0)
    if ok:
        PURCHASED.add(c.from_user.id)
        try:
            await c.message.delete()
        except Exception:
            pass
        await send_access(c.from_user.id, product_key)
    else:
        # ещё не оплачен — снова кнопка оплаты на этот же платёж
        pid = PAY







