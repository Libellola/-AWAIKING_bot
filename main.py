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
YOOKASSA_LINK = os.getenv("YOOKASSA_LINK", "https://yookassa.ru/")
DOC_URL = os.getenv("DOC_URL", "https://tilda.cc/")           # страница С PDF на Тильде
TILDA_PAGE_URL = os.getenv("TILDA_PAGE_URL", "https://tilda.cc/")  # страница с видео на Тильде
TILDA_PAGE_PASSWORD = os.getenv("TILDA_PAGE_PASSWORD", "")    # если нет пароля — оставь пусто

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# кто подтвердил оплату — чтобы не слал напоминание
PURCHASED: set[int] = set()

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
    "• Технику активации торсионных полей сердца — сразу меняет энергию и облегчает путь к желаемому.\n"
    "• Практику дыхания «Шамана» — очищает поле от блоков и «мусора», повышает чувствительность и интуицию.\n"
    "• Практическое руководство к врождённым механизмам управления своим квантовым полем — задаёшь задачу подсознанию, и оно создаёт событие.\n\n"
    "Это не магия и не чудеса — это наука квантовых полей человека. Это работает.\n\n"
    "Жми на кнопку и забирай продукт."
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

def kb_buy():
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Купить — 568₽", url=YOOKASSA_LINK)
    kb.button(text="✅ Я оплатила", callback_data="paid_check")
    return kb.as_markup()

# ========= ЛОГИКА ПРОГРЕВА =========
async def schedule_reminder(chat_id: int):
    await asyncio.sleep(60 * 60)  # 1 час
    if chat_id not in PURCHASED:
        try:
            await bot.send_message(chat_id, TEXT_REMINDER, reply_markup=kb_buy())
        except Exception:
            pass

# 1) /start -> длинное приветствие + «ХОЧУ»
@dp.message(CommandStart())
async def on_start(m: Message):
    await m.answer(TEXT_WELCOME, reply_markup=kb_want())

# 2) «ХОЧУ» -> блок подписки (подписаться/проверить)
@dp.callback_query(F.data == "want")
async def on_want(c: CallbackQuery):
    await c.message.edit_text(
        "Шаг 1: подпишись на канал, вернись и нажми «Проверить подписку».",
        reply_markup=kb_sub()
    )
    await c.answer()

# 3) Проверка подписки -> оффер + «Купить 568₽» + запуск таймера напоминания
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
        await c.message.edit_text(TEXT_OFFER, reply_markup=kb_buy())
        asyncio.create_task(schedule_reminder(c.from_user.id))
    else:
        await c.message.edit_text(
            "Похоже, подписки пока нет 🤍\nНажми «💫 Подписаться на канал», затем «✅ Проверить подписку».",
            reply_markup=kb_sub()
        )
    await c.answer()

# 4) «Я оплатила» -> выдаём доступы
@dp.callback_query(F.data == "paid_check")
async def on_paid(c: CallbackQuery):
    PURCHASED.add(c.from_user.id)
    parts = [
        "✨ Благодарю за доверие!\n",
        f"🎥 Видео (на странице):\n{TILDA_PAGE_URL}\n"
    ]
    if TILDA_PAGE_PASSWORD:
        parts.append(f"Пароль к странице: {TILDA_PAGE_PASSWORD}\n")
    parts.append(f"\n📘 Гайд (страница с PDF):\n{DOC_URL}\n\nПусть практика мягко ведёт тебя 🌸")
    await c.message.edit_text("".join(parts))
    await c.answer()

print("AWAIKING BOT starting…")
if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))

