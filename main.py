import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums.chat_member_status import ChatMemberStatus

# ==== ЮKassa SDK ====
from yookassa import Configuration, Payment


# ========= ENV =========
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL = os.getenv("TELEGRAM_CHANNEL_ID")              # пример: @istinnayya или -100...
TILDA_PAGE_URL = os.getenv("TILDA_PAGE_URL")            # закрытая страница с материалами

# --- ключи API ЮKassa (для умной оплаты через API) ---
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")        # Идентификатор магазина (цифры)
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")  # Секретный ключ

# --- резервная платёжная ссылка (если API вдруг не сработал) ---
YOOKASSA_LINK = os.getenv("YOOKASSA_LINK", "https://yookassa.ru/my/i/aPTmMkN3G-E0/l")

# Настройка ЮKassa SDK (если ключей нет, API-платёж не будет использоваться)
if YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY:
    Configuration.account_id = YOOKASSA_SHOP_ID
    Configuration.secret_key = YOOKASSA_SECRET_KEY
    USE_YOOKASSA_API = True
else:
    USE_YOOKASSA_API = False

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# кто подтвердил оплату — чтобы не слал напоминание
PURCHASED: set[int] = set()

# храним, в какую «ветку/продукт» попал пользователь (по deep-link)
SESSIONS: dict[int, str] = {}

# хранение созданных платежей (для проверки статуса)
PAYMENTS: dict[int, str] = {}   # user_id -> payment_id

# ========= ОПРЕДЕЛЕНИЕ ПРОДУКТОВ/ВЕТОК =========
PRODUCTS = {
    "KLYUCH": {
        "title": "Ветка «КЛЮЧ»",
        "tilda_url": TILDA_PAGE_URL,
        "price_rub": 568,
        "description": "Материалы по программе «КЛЮЧ»"
    },
    # Добавлять новые ветки просто:
    # "SECOND": {"title": "Ветка 2", "tilda_url": "https://...", "price_rub": 990, "description": "..."}
}
DEFAULT_PRODUCT_KEY = "KLYUCH"

# ========= ТЕКСТЫ =========
TEXT_WELCOME = (
    "Я рада видеть тебя в моём пространстве. Это значит, что ты на верном пути и готова к кардинальным переменам. "
    "Скорее всего, ты уже пробовала разные инструменты, но не получила стабильного результата. "
    "Ты постоянно упираешься в потолок: отношения не складываются так, как хотелось бы, проблемы доводят до бессилия и бессмысленности, "
    "и иногда хочется послать всё на хрен.\n\n"
    "Я тебя очень хорошо понимаю. Я тоже когда-то была в таких состояниях и не понимала, как выйти из замкнутого круга. "
    "Я винила себя, винила других, родителей, судьбу, обстоятельства, банки, законы — но от этого было только хуже. "
    "Я не представляла, что у меня всегда были и есть инструменты, которые могут очень быстро всё изменить; "
    "я просто о них не знала — как и многие люди. Как и ты.\n\n"
    "Они очень простые и всегда доступны каждому человеку с рождения. Мы просто не знаем, как с ними обращаться, чтобы получать всё, что желаем.\n\n"
    "Хочешь узнать, что это и как это работает? Жми на кнопку ниже (пиши «ХОЧУ»)."
)

TEXT_OFFER = (
    "Мне пришлось пройти немалый путь, набить немало шишек, не раз упасть и подняться, пережить претензии, боль и бессилие — "
    "и понять, как формируется наша реальность и почему у одних всё легко и просто, а другие поминутно мучатся и страдают. "
    "Но когда я поняла, как это работает и что это есть у всех, радости не было конца. Сейчас я легко и быстро получаю всё, что хочу, — "
    "и так же делают мои ученики и клиенты.\n\n"
    "Чем меньше страхов — тем меньше сомнений, перепадов настроения, нервов, претензий и тревожности. "
    "Есть полное понимание, что у нас есть инструменты и чёткая инструкция, которая работает.\n\n"
    f"Если ты готова узнать, как просто ты сможешь каждый день делать новые шаги, жми на кнопку ниже — и я дам тебе инструкцию. "
    f"Это то, что я собирала годами; сейчас — всего за {PRODUCTS[DEFAULT_PRODUCT_KEY]['price_rub']} руб.\n\n"
    "Используй эти инструменты и инструкции — и ты удивишься, с какой скоростью начнут происходить чудеса."
)

TEXT_REMINDER = (
    "Ты до сих пор не забрала продукты, которые реально и быстро дают рабочие инструменты для управления твоей жизнью? "
    "То, что я отдаю тебе за 568 руб., на самом деле стоит в десятки раз больше, а главное — никто этого не даёт.\n\n"
    "Я отдаю тебе:\n"
    "• Техника активации торсионных полей сердца.\n"
    "• Практика дыхания «Шамана».\n"
    "• Практическое руководство к врождённым механизмам управления квантовым полем.\n\n"
    "Это не магия — это работает. Жми «Купить»."
)

TEXT_PAY_FIRST = (
    "🔒 Доступ выдаётся **только после успешной оплаты**.\n"
    "Пожалуйста, оплати по ссылке и затем нажми «✅ Я оплатила»."
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

def kb_buy(url: str | None):
    kb = InlineKeyboardBuilder()
    if url:
        kb.button(text="💳 Перейти к оплате", url=url)
    else:
        kb.button(text="💳 Купить", callback_data="buy")  # если URL еще не получили
    kb.button(text="✅ Я оплатила", callback_data="paid_check")
    kb.adjust(1)
    return kb.as_markup()

def kb_access(tilda_url: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎥 Открыть страницу с материалами", url=tilda_url)
    kb.adjust(1)
    return kb.as_markup()

# ========= УТИЛИТЫ =========
def parse_start_payload(text: str | None) -> str | None:
    if not text:
        return None
    parts = text.strip().split(maxsplit=1)
    if len(parts) == 2 and parts[0].startswith("/start"):
        return parts[1]
    if text.startswith("/start") and len(text) > 6:
        return text[6:]
    return None

async def schedule_reminder(chat_id: int, product_key: str):
    await asyncio.sleep(60 * 60)  # 1 час
    if chat_id not in PURCHASED:
        try:
            # даём либо прямую ссылку на платёж (если есть), либо кнопку "Купить"
            pay_url = None
            if USE_YOOKASSA_API:
                try:
                    pay_url = create_payment(chat_id, product_key)
                except Exception as e:
                    print("YOOKASSA CREATE ERROR (reminder):", repr(e))
            if not pay_url:
                pay_url = YOOKASSA_LINK
            await bot.send_message(chat_id, TEXT_REMINDER, reply_markup=kb_buy(pay_url))
        except Exception:
            pass

def create_payment(user_id: int, product_key: str) -> str:
    """
    Создаёт платёж в ЮKassa и возвращает confirmation_url.
    Сохраняет payment_id в PAYMENTS[user_id].
    """
    if not USE_YOOKASSA_API:
        raise RuntimeError("YooKassa API keys are not configured")

    product = PRODUCTS.get(product_key, PRODUCTS[DEFAULT_PRODUCT_KEY])
    amount = product["price_rub"]
    description = (product.get("description") or product["title"])[:128]

    try:
        payment = Payment.create({
            "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
            "capture": True,
            "confirmation": {
                "type": "redirect",
                # можно указать return_url: на страницу “спасибо” или обратно в бота
                # "return_url": f"https://t.me/{(await bot.me()).username}?start=paid"
            },
            "description": f"{description} (user_id={user_id})",
            "metadata": {"user_id": user_id, "product_key": product_key}
        })
    except Exception as e:
        print("YOOKASSA CREATE ERROR:", repr(e))
        raise

    PAYMENTS[user_id] = payment.id
    return payment.confirmation.confirmation_url

def check_payment_succeeded(user_id: int) -> bool:
    """
    Возвращает True, если последний платёж пользователя успешно оплачен.
    """
    payment_id = PAYMENTS.get(user_id)
    if not payment_id:
        return False
    try:
        payment = Payment.find_one(payment_id)
        return payment.status == "succeeded"
    except Exception as e:
        print("YOOKASSA FIND ERROR:", repr(e))
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
    payload = parse_start_payload(m.text)
    key = (payload or DEFAULT_PRODUCT_KEY).upper()
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

        # пытаемся создать платёж через API
        pay_url = None
        if USE_YOOKASSA_API:
            try:
                pay_url = create_payment(c.from_user.id, product_key)
            except Exception:
                pay_url = None

        # если API не сработал — используем резервную платёжную ссылку
        if not pay_url:
            pay_url = YOOKASSA_LINK

        await c.message.edit_text(TEXT_OFFER, reply_markup=kb_buy(pay_url))
        asyncio.create_task(schedule_reminder(c.from_user.id, product_key))
    else:
        await c.message.edit_text(
            "Похоже, подписки пока нет 🤍\nНажми «💫 Подписаться на канал», затем «✅ Проверить подписку».",
            reply_markup=kb_sub()
        )
    await c.answer()

@dp.callback_query(F.data == "buy")
async def on_buy(c: CallbackQuery):
    # Кнопка на случай, если API-ссылка не была выдана ранее
    product_key = SESSIONS.get(c.from_user.id, DEFAULT_PRODUCT_KEY)
    pay_url = None
    if USE_YOOKASSA_API:
        try:
            pay_url = create_payment(c.from_user.id, product_key)
        except Exception:
            pay_url = None
    if not pay_url:
        pay_url = YOOKASSA_LINK

    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Перейти к оплате", url=pay_url)
    kb.button(text="✅ Я оплатила", callback_data="paid_check")
    kb.adjust(1)

    await c.message.edit_text(
        f"К оплате: {PRODUCTS[product_key]['price_rub']} ₽\n\n"
        "Открой ссылку для оплаты и после успешной оплаты вернись и нажми «✅ Я оплатила».",
        reply_markup=kb.as_markup()
    )
    await c.answer()

@dp.callback_query(F.data == "paid_check")
async def on_paid_check(c: CallbackQuery):
    # проверяем статус последнего платежа пользователя (если API используем)
    ok = False
    if USE_YOOKASSA_API:
        ok = check_payment_succeeded(c.from_user.id)

    if ok:
        PURCHASED.add(c.from_user.id)
        try:
            await c.message.delete()
        except Exception:
            pass
        product_key = SESSIONS.get(c.from_user.id, DEFAULT_PRODUCT_KEY)
        await send_access(c.from_user.id, product_key)
    else:
        product_key = SESSIONS.get(c.from_user.id, DEFAULT_PRODUCT_KEY)
        pay_url = None

        if USE_YOOKASSA_API:
            # если платежа ещё нет — создаём новый
            pid = PAYMENTS.get(c.from_user.id)
            if pid:
                try:
                    p = Payment.find_one(pid)
                    pay_url = getattr(getattr(p, "confirmation", None), "confirmation_url", None)
                except Exception:
                    pay_url = None
            if not pay_url:
                try:
                    pay_url = create_payment(c.from_user.id, product_key)
                except Exception:
                    pay_url = None

        if not pay_url:
            pay_url = YOOKASSA_LINK

        kb = InlineKeyboardBuilder()
        kb.button(text="💳 Перейти к оплате", url=pay_url)
        kb.button(text="✅ Я оплатила", callback_data="paid_check")
        kb.adjust(1)

        await c.message.edit_text(
            f"{TEXT_PAY_FIRST}\n\n"
            "Если уже оплатила, подожди 10–30 секунд и нажми «✅ Я оплатила» ещё раз.",
            reply_markup=kb.as_markup()
        )
    await c.answer()

# запасной случай — если человек потерял финальное сообщение
@dp.message(F.text.regexp(r"^/access($|\s)"))
async def on_access(m: Message):
    product_key = SESSIONS.get(m.chat.id, DEFAULT_PRODUCT_KEY)
    await send_access(m.chat.id, product_key)

print("AWAIKING BOT starting… (smart YooKassa)")
if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))





