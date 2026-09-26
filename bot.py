import logging
import os
import re
import sqlite3
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# ---------- НАЛАШТУВАННЯ ----------
# Токен бота бери у @BotFather. Краще зберігати його в змінній середовища
# BOT_TOKEN, а не прямо в коді — так безпечніше при публікації на GitHub.
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8780497142:AAEMWUevQtduGrvUTwbmTBcdzKDX9R0VFW0")
DB_PATH = os.path.join(os.path.dirname(__file__), "klas_service.db")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Стани для ConversationHandler
REG_NAME, REG_SERVICE, REG_PRICE = range(3)
REQ_DESCRIPTION = 10

# ---------- ТЕКСТИ КНОПОК ГОЛОВНОГО МЕНЮ ----------
BTN_REGISTER = "🧑‍🎓 Стати виконавцем"
BTN_SERVICES = "📋 Список послуг"
BTN_REQUEST = "🆘 Подати заявку"
BTN_REQUESTS = "📌 Відкриті заявки"
BTN_RATE = "⭐ Оцінити виконавця"
BTN_MY = "🗑 Мої оголошення"
BTN_HELP = "❓ Допомога"
BTN_CANCEL = "◀️ Скасувати"

# Усі кнопки головного меню (без "Скасувати") — потрібно для того, щоб
# натискання будь-якої з них переривало поточний діалог (реєстрацію чи
# подачу заявки), а не сприймалось як введений текст.
MAIN_MENU_BUTTONS = [BTN_REGISTER, BTN_SERVICES, BTN_REQUEST, BTN_REQUESTS, BTN_RATE, BTN_MY, BTN_HELP]


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [BTN_REGISTER],
        [BTN_SERVICES],
        [BTN_REQUEST],
        [BTN_REQUESTS],
        [BTN_RATE],
        [BTN_MY],
        [BTN_HELP],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[BTN_CANCEL]], resize_keyboard=True)


def btn(text: str):
    """Точний збіг тексту кнопки (regex-фільтр)."""
    return filters.Regex(f"^{re.escape(text)}$")


def any_main_menu_button_except(*exclude: str):
    """Фільтр, що спрацьовує на будь-яку кнопку головного меню, КРІМ переданих."""
    texts = [t for t in MAIN_MENU_BUTTONS if t not in exclude]
    pattern = "|".join(re.escape(t) for t in texts)
    return filters.Regex(f"^({pattern})$")


# ---------- БАЗА ДАНИХ ----------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS executors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            name TEXT NOT NULL,
            service TEXT NOT NULL,
            price TEXT NOT NULL,
            rating_sum INTEGER DEFAULT 0,
            rating_count INTEGER DEFAULT 0,
            created_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            description TEXT NOT NULL,
            status TEXT DEFAULT 'відкрита',
            created_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


# ---------- СТАРТ / ДОВІДКА ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Привіт! Це бот «Клас-Сервіс» 🎓\n\n"
        "Тут учні пропонують і шукають дрібні послуги одне одному:\n"
        "репетиторство, допомога з домашкою, малюнки, фото та інше.\n\n"
        "Обери дію кнопкою внизу 👇"
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🧑‍🎓 Стати виконавцем — запропонувати свою послугу\n"
        "📋 Список послуг — хто що пропонує\n"
        "🆘 Подати заявку — написати, яка допомога потрібна\n"
        "📌 Відкриті заявки — переглянути чужі заявки\n"
        "⭐ Оцінити виконавця — поставити оцінку 1–5\n"
        "🗑 Мої оголошення — видалити свою послугу або заявку"
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Скасовано.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


# ---------- ПЕРЕМИКАННЯ МІЖ ДІЯМИ ПІД ЧАС ДІАЛОГУ ----------
# Якщо користувач мідь-форми (наприклад, вводить назву послуги) натискає
# іншу кнопку меню, ці функції перервуть поточний діалог і одразу виконають
# нову дію, замість того щоб сприйняти назву кнопки як введені дані.
async def switch_to_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await services(update, context)
    return ConversationHandler.END


async def switch_to_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await requests_list(update, context)
    return ConversationHandler.END


async def switch_to_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await rate_start(update, context)
    return ConversationHandler.END


async def switch_to_my(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await my_listings(update, context)
    return ConversationHandler.END


async def switch_to_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await help_cmd(update, context)
    return ConversationHandler.END


async def switch_hint_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        f"Скасовано поточну дію. Натисни «{BTN_REGISTER}» ще раз, щоб почати реєстрацію.",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def switch_hint_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        f"Скасовано поточну дію. Натисни «{BTN_REQUEST}» ще раз, щоб подати заявку.",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


def menu_switch_fallbacks(exclude_own: str):
    """Список fallback-хендлерів для активного діалогу (реєстрація або заявка).

    Кнопки, що не запускають інший діалог (список, заявки, рейтинг, мої
    оголошення, довідка), одразу виконують свою дію і закривають поточний
    діалог. Кнопки "Стати виконавцем" і "Подати заявку" належать до ІНШОГО
    ConversationHandler, тому напряму передати керування туди небезпечно
    (стани двох різних діалогів переплутаються) — замість цього поточний
    діалог просто скасовується з підказкою натиснути кнопку ще раз.
    """
    simple_actions = {
        BTN_SERVICES: switch_to_services,
        BTN_REQUESTS: switch_to_requests,
        BTN_RATE: switch_to_rate,
        BTN_MY: switch_to_my,
        BTN_HELP: switch_to_help,
    }
    other_dialog_hints = {
        BTN_REGISTER: switch_hint_register,
        BTN_REQUEST: switch_hint_request,
    }

    handlers = [CommandHandler("cancel", cancel), MessageHandler(btn(BTN_CANCEL), cancel)]
    for text, func in simple_actions.items():
        if text != exclude_own:
            handlers.append(MessageHandler(btn(text), func))
    for text, func in other_dialog_hints.items():
        if text != exclude_own:
            handlers.append(MessageHandler(btn(text), func))
    return handlers


# ---------- РЕЄСТРАЦІЯ ВИКОНАВЦЯ ----------
async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Як тебе звати? (ім'я, яке бачитимуть інші)",
        reply_markup=cancel_keyboard(),
    )
    return REG_NAME


async def register_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["reg_name"] = update.message.text.strip()
    await update.message.reply_text(
        "Яку послугу пропонуєш? (наприклад: репетитор з математики)",
        reply_markup=cancel_keyboard(),
    )
    return REG_SERVICE


async def register_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["reg_service"] = update.message.text.strip()
    await update.message.reply_text(
        "Яка ціна? (можна словами, напр. '50 грн/год' або 'домовимось')",
        reply_markup=cancel_keyboard(),
    )
    return REG_PRICE


async def register_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price = update.message.text.strip()
    name = context.user_data.get("reg_name")
    service = context.user_data.get("reg_service")
    user = update.effective_user

    conn = get_db()
    conn.execute(
        "INSERT INTO executors (user_id, username, name, service, price, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user.id, user.username, name, service, price, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"Готово! Тебе додано до списку виконавців ✅\n\n"
        f"Ім'я: {name}\nПослуга: {service}\nЦіна: {price}\n\n"
        f"Тепер твою пропозицію видно в «{BTN_SERVICES}»",
        reply_markup=main_menu_keyboard(),
    )
    context.user_data.clear()
    return ConversationHandler.END


# ---------- СПИСОК ВИКОНАВЦІВ ----------
async def services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    rows = conn.execute("SELECT * FROM executors ORDER BY created_at DESC").fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text(
            f"Поки немає жодного виконавця. Стань першим — «{BTN_REGISTER}»",
            reply_markup=main_menu_keyboard(),
        )
        return

    lines = ["📋 Список виконавців:\n"]
    for r in rows:
        avg = (r["rating_sum"] / r["rating_count"]) if r["rating_count"] else None
        rating_text = f"⭐ {avg:.1f} ({r['rating_count']})" if avg else "без оцінок"
        contact = f"@{r['username']}" if r["username"] else "написати особисто в школі"
        lines.append(
            f"#{r['id']} — {r['name']}\n"
            f"   Послуга: {r['service']}\n"
            f"   Ціна: {r['price']} | Рейтинг: {rating_text}\n"
            f"   Контакт: {contact}\n"
        )
    await update.message.reply_text("\n".join(lines), reply_markup=main_menu_keyboard())


# ---------- ПОДАЧА ЗАЯВКИ ----------
async def request_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Опиши, яка допомога потрібна (наприклад: 'потрібна допомога з фізикою до четверга')",
        reply_markup=cancel_keyboard(),
    )
    return REQ_DESCRIPTION


async def request_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    description = update.message.text.strip()
    user = update.effective_user

    conn = get_db()
    conn.execute(
        "INSERT INTO requests (user_id, username, description, created_at) VALUES (?, ?, ?, ?)",
        (user.id, user.username, description, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"Заявку додано ✅ Її тепер видно всім у «{BTN_REQUESTS}»",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def requests_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM requests WHERE status = 'відкрита' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text(
            "Наразі немає відкритих заявок.", reply_markup=main_menu_keyboard()
        )
        return

    lines = ["📝 Відкриті заявки:\n"]
    for r in rows:
        contact = f"@{r['username']}" if r["username"] else "написати особисто в школі"
        lines.append(f"#{r['id']} — {r['description']}\n   Від: {contact}\n")
    await update.message.reply_text("\n".join(lines), reply_markup=main_menu_keyboard())


# ---------- РЕЙТИНГ ----------
async def rate_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    rows = conn.execute("SELECT id, name FROM executors ORDER BY id DESC LIMIT 10").fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text(
            "Поки немає виконавців для оцінки.", reply_markup=main_menu_keyboard()
        )
        return

    keyboard = [
        [InlineKeyboardButton(f"#{r['id']} {r['name']}", callback_data=f"rate_pick_{r['id']}")]
        for r in rows
    ]
    await update.message.reply_text(
        "Кого оцінюємо? (показані останні 10)",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def rate_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    executor_id = query.data.split("_")[-1]

    keyboard = [
        [
            InlineKeyboardButton(str(n), callback_data=f"rate_star_{executor_id}_{n}")
            for n in range(1, 6)
        ]
    ]
    await query.edit_message_text(
        "Скільки зірок ставимо? (1–5)",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def rate_star(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, _, executor_id, stars = query.data.split("_")
    stars = int(stars)

    conn = get_db()
    conn.execute(
        "UPDATE executors SET rating_sum = rating_sum + ?, rating_count = rating_count + 1 WHERE id = ?",
        (stars, executor_id),
    )
    conn.commit()
    conn.close()

    await query.edit_message_text(f"Дякую! Оцінку {stars}⭐ враховано.")


# ---------- МОЇ ОГОЛОШЕННЯ / ВИДАЛЕННЯ ----------
async def my_listings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db()
    my_services = conn.execute(
        "SELECT * FROM executors WHERE user_id = ? ORDER BY created_at DESC", (user.id,)
    ).fetchall()
    my_requests = conn.execute(
        "SELECT * FROM requests WHERE user_id = ? AND status = 'відкрита' ORDER BY created_at DESC",
        (user.id,),
    ).fetchall()
    conn.close()

    if not my_services and not my_requests:
        await update.message.reply_text(
            "У тебе поки немає власних послуг чи заявок.",
            reply_markup=main_menu_keyboard(),
        )
        return

    keyboard = []
    lines = ["🗑 Твої оголошення. Натисни, щоб видалити:\n"]

    if my_services:
        lines.append("Послуги:")
        for r in my_services:
            lines.append(f"#{r['id']} — {r['service']} ({r['price']})")
            keyboard.append(
                [InlineKeyboardButton(f"❌ Видалити послугу #{r['id']}", callback_data=f"del_service_{r['id']}")]
            )

    if my_requests:
        lines.append("\nЗаявки:")
        for r in my_requests:
            lines.append(f"#{r['id']} — {r['description']}")
            keyboard.append(
                [InlineKeyboardButton(f"❌ Видалити заявку #{r['id']}", callback_data=f"del_request_{r['id']}")]
            )

    await update.message.reply_text(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def delete_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    executor_id = query.data.split("_")[-1]
    user = update.effective_user

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM executors WHERE id = ? AND user_id = ?", (executor_id, user.id)
    ).fetchone()
    if not row:
        conn.close()
        await query.edit_message_text("Цю послугу вже видалено або вона тобі не належить.")
        return

    conn.execute("DELETE FROM executors WHERE id = ?", (executor_id,))
    conn.commit()
    conn.close()
    await query.edit_message_text(f"Послугу #{executor_id} видалено ✅")


async def delete_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    request_id = query.data.split("_")[-1]
    user = update.effective_user

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM requests WHERE id = ? AND user_id = ?", (request_id, user.id)
    ).fetchone()
    if not row:
        conn.close()
        await query.edit_message_text("Цю заявку вже видалено або вона тобі не належить.")
        return

    conn.execute("DELETE FROM requests WHERE id = ?", (request_id,))
    conn.commit()
    conn.close()
    await query.edit_message_text(f"Заявку #{request_id} видалено ✅")


# ---------- ЗАПУСК ----------
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    reg_conv = ConversationHandler(
        entry_points=[
            CommandHandler("register", register_start),
            MessageHandler(btn(BTN_REGISTER), register_start),
        ],
        states={
            REG_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & ~any_main_menu_button_except() & ~btn(BTN_CANCEL),
                    register_name,
                )
            ],
            REG_SERVICE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & ~any_main_menu_button_except() & ~btn(BTN_CANCEL),
                    register_service,
                )
            ],
            REG_PRICE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & ~any_main_menu_button_except() & ~btn(BTN_CANCEL),
                    register_price,
                )
            ],
        },
        fallbacks=menu_switch_fallbacks(exclude_own=BTN_REGISTER),
        allow_reentry=True,
    )

    req_conv = ConversationHandler(
        entry_points=[
            CommandHandler("request", request_start),
            MessageHandler(btn(BTN_REQUEST), request_start),
        ],
        states={
            REQ_DESCRIPTION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & ~any_main_menu_button_except() & ~btn(BTN_CANCEL),
                    request_save,
                )
            ],
        },
        fallbacks=menu_switch_fallbacks(exclude_own=BTN_REQUEST),
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(btn(BTN_HELP), help_cmd))
    app.add_handler(reg_conv)
    app.add_handler(req_conv)
    app.add_handler(CommandHandler("services", services))
    app.add_handler(MessageHandler(btn(BTN_SERVICES), services))
    app.add_handler(CommandHandler("requests", requests_list))
    app.add_handler(MessageHandler(btn(BTN_REQUESTS), requests_list))
    app.add_handler(CommandHandler("rate", rate_start))
    app.add_handler(MessageHandler(btn(BTN_RATE), rate_start))
    app.add_handler(CommandHandler("my", my_listings))
    app.add_handler(MessageHandler(btn(BTN_MY), my_listings))
    app.add_handler(CallbackQueryHandler(rate_pick, pattern=r"^rate_pick_\d+$"))
    app.add_handler(CallbackQueryHandler(rate_star, pattern=r"^rate_star_\d+_\d+$"))
    app.add_handler(CallbackQueryHandler(delete_service, pattern=r"^del_service_\d+$"))
    app.add_handler(CallbackQueryHandler(delete_request, pattern=r"^del_request_\d+$"))

    logger.info("Бот запущено...")
    app.run_polling()


if __name__ == "__main__":
    main()
