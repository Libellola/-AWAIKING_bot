import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums.chat_member_status import ChatMemberStatus

# ========= ENV =========
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL = os.getenv("TELEGRAM_CHANNEL_ID")  # пример: @istinnayya
YOOKASSA_LINK = os.getenv("YOOKASSA_LINK", "https://yookassa.ru/my/i/aPTmMkN3G-E0/l")  # ← сюда позже поставишь свою ссылку оплаты
# если в ENV не задано — берём твой текущий адрес страницы на Тильде
TILDA_PAGE_URL = os.getenv("TILDA_PAGE_URL", "http://project16434036.tilda.ws")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# кто подтвердил оплату — чтобы не слал напоминание
PURCHASED: set[int] = set()

# храним, в какую «ветку/продукт» попал пользователь (по deep-link)
SESSIONS: dict[int, str] = {}

# ========= ОПРЕДЕЛЕНИЕ ПРОДУКТОВ/ВЕТОК =========
# ключ — это слово в deep-link после ?start=
PRODUCTS = {
    "KLYUCH": {
        "title": "Ветка «КЛЮЧ»",
        "tilda_url": TILDA_PAGE_URL,
        "price_rub": 568,
    },
    # сюда легко добавишь новые продукты:
    # "SECOND": {"title": "Ветка 2", "tilda_url": "https://...", "price_rub": 990}
}

DEFAULT_PRODUCT_KEY = "KLYUCH"  # по умолчанию, если пришли без ключа

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
    "Если ты готова узнать, как просто ты сможешь каждый день делать новые шаги, жми на кнопку ниже — и я дам тебе инструкцию. "
    "Это то, что я собирала годами; сейчас — всего за 568 руб.\n\n"
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

def kb_buy(price: int, pay_url: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=f"💳 Купить — {price}₽", url=pay_url)
    kb.button(text="✅ Я оплатила", callback_data="paid_check")
    return kb.as_markup()

def kb_access(tilda_url: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎥 Открыть страницу с материалами", url=tilda_url)
    kb.adjust(1)
    return kb.as_markup()

# ========= УТИЛИТЫ =========
def parse_start_payload(text: str | None) -> str | None:
    """
    Возвращает payload из /start payload
    """
    if not text:
        return None
    # варианты: "/start", "/start KLYUCH", "/startKLYUCH" (на всякий)
    parts = text.strip().split(maxsplit=1)
    if len(parts) == 2 and parts[0].startswith("/start"):
        return parts[1]
    if text.startswith("/start") and len(text) > 6:
        return text[6:]
    return None

async def schedule_reminder(chat_id: int, product_key: str):
    await asyncio.sleep(60 * 60)  # 1 час
    if chat_id not in PURCHASED:
        product = PRODUCTS.get(product_key, PRODUCTS[DEFAULT_PRODUCT_KEY])
        try:
            await bot.send_message(chat_id, TEXT_REMINDER, reply_markup=kb_buy(product["price_rub"], YOOKASSA_LINK))
        except Exception:
            pass

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
    # читаем payload из deep-link (?start=KLYUCH)
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
        product = PRODUCTS.get(product_key, PRODUCTS[DEFAULT_PRODUCT_KEY])
        await c.message.edit_text(TEXT_OFFER, reply_markup=kb_buy(product["price_rub"], YOOKASSA_LINK))
        asyncio.create_task(schedule_reminder(c.from_user.id, product_key))
    else:
        await c.message.edit_text(
            "Похоже, подписки пока нет 🤍\nНажми «💫 Подписаться на канал», затем «✅ Проверить подписку».",
            reply_markup=kb_sub()
        )
    await c.answer()

@dp.callback_query(F.data == "paid_check")
async def on_paid(c: CallbackQuery):
    PURCHASED.add(c.from_user.id)
    await c.answer()
    try:
        await c.message.delete()  # очищаем экран «покупки»
    except Exception:
        pass
    product_key = SESSIONS.get(c.from_user.id, DEFAULT_PRODUCT_KEY)
    await send_access(c.from_user.id, product_key)

# запасной случай — если человек потерял финальное сообщение
@dp.message(F.text.regexp(r"^/access($|\s)"))
async def on_access(m: Message):
    product_key = SESSIONS.get(m.chat.id, DEFAULT_PRODUCT_KEY)
    await send_access(m.chat.id, product_key)

print("AWAIKING BOT starting…")
if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))


