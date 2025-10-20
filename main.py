import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums.chat_member_status import ChatMemberStatus
from yookassa import Configuration, Payment

# ========= ENV =========
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

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

PURCHASED: set[int] = set()
SESSIONS: dict[int, str] = {}
PAYMENTS: dict[int, str] = {}   # user_id -> payment_id

# ========= ПРОДУКТ =========
PRODUCTS = {
    "KLYUCH": {
        "title": "Ветка «КЛЮЧ»",
        "tilda_url": TILDA_PAGE_URL,
        "price_rub": 568,
        "description": "Материалы по программе «КЛЮЧ»"
    }
}
DEFAULT_PRODUCT_KEY = "KLYUCH"

# ========= ТЕКСТЫ =========
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

# ========= КЛАВИАТУРЫ =========
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

# ========= ЮKassa helpers =========
def create_payment(user_id: int, product_key: str) -> str:
    if not USE_YOOKASSA_API:
        raise RuntimeError("YooKassa API keys are not configured")

    product = PRODUCTS.get(product_key, PRODUCTS[DEFAULT_PRODUCT_KEY])
    amount = product["price_rub"]
    description = (product.get("description") or product["title"])[:128]

    payment = Payment.create({
        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
        "capture": True,
        "confirmation": {
            "type": "redirect",
            # необязательно, но можно вернуть в бота
            # "return_url": "https://t.me/AWAIKING_bot?start=paid"
        },
        "description": f"{description} (user_id={user_id})",
        "metadata": {"user_id": user_id, "product_key": product_key}
    })
    PAYMENTS[user_id] = payment.id
    return payment.confirmation.confirmation_url

async def wait_payment_succeeded(user_id: int, retries: int = 6, delay_sec: float = 5.0) -> bool:
    """Опрашиваем статус платежа несколько раз (до ~30 сек суммарно)."""
    pid = PAYMENTS.get(user_id)
    if not pid:
        return False
    for _ in range(retries):
        try:
            p = Payment.find_one(pid)
            if p.status == "succeeded":
                return True
            if p.status in ("canceled", "waiting_for_capture"):
                # canceled — точно нет; waiting_for_capture — редкий случай, но подождём
                pass
        except Exception as e:
            print("YOOKASSA FIND ERROR:", repr(e))
        await asyncio.sleep(delay_sec)
    return False

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

# ========= ХЭНДЛЕРЫ =========
@dp.message(CommandStart())
async def on_start(m: Message):
    payload = (m.text or "").split(maxsplit=1)
    key = (payload[1] if len(payload) == 2 else DEFAULT_PRODUCT_KEY).upper()
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
            await c.message.edit_text(
                "Платёжный модуль пока не настроен. Свяжись, пожалуйста, с поддержкой.",
            )
        else:
            # создаём персональную ссылку оплаты
            try:
                pay_url = create_payment(c.from_user.id, product_key)
                await c.message.edit_text(TEXT_OFFER, reply_markup=kb_pay(pay_url))
            except Exception as e:
                print("YOOKASSA CREATE ERROR:", repr(e))
                await c.message.edit_text("Что-то пошло не так при создании платежа. Попробуй ещё раз позже.")
        # напоминание через час
        asyncio.create_task(asyncio.sleep(0))  # просто, чтобы не ругался линтер :)
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
        await c.message.edit_text("Платёжный модуль пока не настроен. Свяжись, пожалуйста, с поддержкой.")
        await c.answer()
        return

    # если пользователь не создавал платёж — создадим прямо сейчас
    if c.from_user.id not in PAYMENTS:
        try:
            pay_url = create_payment(c.from_user.id, product_key)
            await c.message.edit_text(
                TEXT_PAY_FIRST, reply_markup=kb_pay(pay_url)
            )
            await c.answer()
            return
        except Exception as e:
            print("YOOKASSA CREATE ERROR (from paid_check):", repr(e))
            await c.message.edit_text("Не получилось создать платёж. Попробуй «Купить» ещё раз.")
            await c.answer()
            return

    # ждём подтверждение (короткий опрос статуса)
    ok = await wait_payment_succeeded(c.from_user.id, retries=6, delay_sec=5.0)
    if ok:
        PURCHASED.add(c.from_user.id)
        try:
            await c.message.delete()
        except Exception:
            pass
        await send_access(c.from_user.id, product_key)
    else:
        # пока не прошёл — снова выдаём кнопку на уже созданный платёж
        pid = PAYMENTS.get(c.from_user.id)
        pay_url = None
        try:
            p = Payment.find_one(pid)
            pay_url = getattr(getattr(p, "confirmation", None), "confirmation_url", None)
        except Exception as e:
            print("YOOKASSA FIND ERROR 2:", repr(e))
        if not pay_url:
            try:
                pay_url = create_payment(c.from_user.id, product_key)
            except Exception as e:
                print("YOOKASSA CREATE ERROR 2:", repr(e))
        await c.message.edit_text(
            TEXT_PAY_FIRST,
            reply_markup=kb_pay(pay_url) if pay_url else None
        )
    await c.answer()

# запасной: если потерял финальное сообщение
@dp.message(F.text.regexp(r"^/access($|\s)"))
async def on_access(m: Message):
    product_key = SESSIONS.get(m.chat.id, DEFAULT_PRODUCT_KEY)
    await send_access(m.chat.id, product_key)

print("AWAIKING BOT starting… (smart YooKassa, per-user invoices)")
if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))






