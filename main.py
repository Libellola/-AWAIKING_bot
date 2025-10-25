import os
import asyncio
import logging
import uuid

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums.chat_member_status import ChatMemberStatus

from yookassa import Configuration, Payment

# ---------- ЛОГИ ----------
logging.basicConfig(level=logging.INFO)

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
    logging.info("YooKassa: keys detected, API mode ON")
else:
    logging.info("YooKassa: keys missing, API mode OFF")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ---------- ХРАНИЛКИ ----------
PURCHASED: set[int] = set()     # кто уже получил доступ
SESSIONS: dict[int, str] = {}   # выбор ветки/продукта
PAYMENTS: dict[int, str] = {}   # user_id -> payment_id

# ---------- ПРОДУКТЫ ----------
PRODUCTS = {
    "KLYUCH": {
        "title": "Ветка «КЛЮЧ»",
        "tilda_url": TILDA_PAGE_URL,
        "price_rub": 568,
        "description": "Материалы по программе «КЛЮЧ»"
    }
}
DEFAULT_PRODUCT_KEY = "KLYUCH"

# ---------- ТЕКСТЫ ----------
TEXT_WELCOME = (
    "Я рада видеть тебя в моём пространстве. Это значит, что ты на верном пути и готова к кардинальным переменам..."
    "\n\nХочешь узнать, что это и как это работает? Жми на кнопку ниже (пиши «ХОЧУ»)."
)
TEXT_OFFER = (
    "Мне пришлось пройти немалый путь... "
    f"Если ты готова — жми «Купить». Сейчас — всего за {PRODUCTS[DEFAULT_PRODUCT_KEY]['price_rub']} руб."
)
TEXT_REMINDER = (
    "Ты до сих пор не забрала продукты... Это не магия — это работает. Жми «Купить»."
)
TEXT_PAY_FIRST = (
    "🔒 Доступ выдаётся только после успешной оплаты.\n"
    "Если уже оплатила, подожди 10–30 сек и нажми «✅ Я оплатила» ещё раз."
)

# ---------- КЛАВИАТУРЫ ----------
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

# ---------- ВСПОМОГАТОРЫ ----------
def parse_start_payload(text: str | None) -> str:
    if not text:
        return DEFAULT_PRODUCT_KEY
    parts = text.strip().split(maxsplit=1)
    if len(parts) == 2 and parts[0].startswith("/start"):
        return (parts[1] or DEFAULT_PRODUCT_KEY).upper()
    if text.startswith("/start") and len(text) > 6:
        return text[6:].upper()
    return DEFAULT_PRODUCT_KEY

def _amount_str(rub: int) -> str:
    return f"{int(rub):.2f}"

def create_payment(user_id: int, product_key: str) -> str:
    """Создаёт платёж в YooKassa и возвращает URL для оплаты."""
    if not USE_YOOKASSA_API:
        raise RuntimeError("YooKassa API keys are not configured")

    product = PRODUCTS.get(product_key, PRODUCTS[DEFAULT_PRODUCT_KEY])
    amount = _amount_str(product["price_rub"])
    description = (product.get("description") or product["title"])[:128]

    data = {
        "amount": {"value": amount, "currency": "RUB"},
        "capture": True,
        "confirmation": {
            "type": "redirect",
            # можно вернуть на страницу «спасибо»; используем твою Tilda
            "return_url": TILDA_PAGE_URL or "https://t.me",
        },
        "description": f"{description} (user_id={user_id})",
        "metadata": {"user_id": user_id, "product_key": product_key},
    }
    idem = str(uuid.uuid4())
    try:
        payment = Payment.create(data, idempotency_key=idem)
    except Exception as e:
        logging.exception(f"YooKassa create payment error: {e}")
        raise

    PAYMENTS[user_id] = payment.id
    return payment.confirmation.confirmation_url

async def wait_payment_succeeded(user_id: int, retries: int = 6, delay_sec: float = 5.0) -> bool:
    """Ожидаем успех платежа (до ~30 сек суммарно)."""
    pid = PAYMENTS.get(user_id)
    if not pid:
        return False
    for _ in range(retries):
        try:
            p = Payment.find_one(pid)
            if p.status == "succeeded":
                return True
            # waiting_for_capture / canceled — продолжаем/завершаем по ситуации
        except Exception as e:
            logging.exception(f"YooKassa find payment error: {e}")
        await asyncio.sleep(delay_sec)
    return False

# ---------- НАПОМИНАНИЕ ----------
async def schedule_reminder(chat_id: int, product_key: str):
    await asyncio.sleep(60 * 60)  # 1 час
    if chat_id in PURCHASED:
        return
    try:
        if USE_YOOKASSA_API:
            pay_url = create_payment(chat_id, product_key)
            await bot.send_message(chat_id, TEXT_REMINDER, reply_markup=kb_pay(pay_url))
        else:
            await bot.send_message(chat_id, TEXT_REMINDER)
    except Exception as e:
        logging.exception(f"REMINDER ERROR: {e}")

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

# ---------- ХЭНДЛЕРЫ ----------
@dp.message(CommandStart())
async def on_start(m: Message):
    key = parse_start_payload(m.text)
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
        ok = member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
    except Exception:
        ok = False

    if ok:
        product_key = SESSIONS.get(c.from_user.id, DEFAULT_PRODUCT_KEY)
        if not USE_YOOKASSA_API:
            await c.message.edit_text("Платёжный модуль пока не настроен. Напиши поддержке.")
        else:
            try:
                pay_url = create_payment(c.from_user.id, product_key)
                await c.message.edit_text(TEXT_OFFER, reply_markup=kb_pay(pay_url))
            except Exception:
                await c.message.edit_text("Что-то пошло не так при создании платежа. Попробуй ещё раз позже.")
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
        await c.message.edit_text("Платёжный модуль пока не настроен. Напиши поддержке.")
        await c.answer()
        return

    # если платёж ещё не создавали — создадим
    if c.from_user.id not in PAYMENTS:
        try:
            pay_url = create_payment(c.from_user.id, product_key)
            await c.message.edit_text(TEXT_PAY_FIRST, reply_markup=kb_pay(pay_url))
            await c.answer()
            return
        except Exception:
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
        # снова даём ссылку на уже созданный (или новый) платёж
        pid = PAYMENTS.get(c.from_user.id)
        pay_url = None
        try:
            p = Payment.find_one(pid)
            pay_url = getattr(getattr(p, "confirmation", None), "confirmation_url", None)
        except Exception:
            pass
        if not pay_url:
            try:
                pay_url = create_payment(c.from_user.id, product_key)
            except Exception:
                pass
        await c.message.edit_text(TEXT_PAY_FIRST, reply_markup=kb_pay(pay_url) if pay_url else None)
    await c.answer()

@dp.message(F.text.in_({"/ping", "ping"}))
async def on_ping(m: Message):
    await m.answer("pong ✅")

# ---------- СТАРТ ----------
async def _main():
    try:
        # убираем possible webhook и прошлые апдейты, пишем лог
        await bot.delete_webhook(drop_pending_updates=True)
        me = await bot.get_me()
        logging.info(f"Bot started as @{me.username} (id={me.id})")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logging.exception(f"FATAL on start: {e}")

if __name__ == "__main__":
    asyncio.run(_main())








