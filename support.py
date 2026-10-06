import logging
import sqlite3
from contextlib import closing
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyParameters,
)


logger = logging.getLogger(__name__)

FAQ_TEXT = (
    "❓ Часто задаваемые вопросы\n\n"
    "1. Как выбрать студенческое объединение?\n"
    "Открой «Объединения»: там можно посмотреть каталог по направлениям "
    "или пройти тест и получить рекомендации по своим интересам.\n\n"
    "2. Как вступить в объединение?\n"
    "Открой его карточку в каталоге. Посмотри описание, информацию о вступлении "
    "и ссылки. Если информации не хватает, нажми «Задать вопрос» — команда ОСО поможет разобраться.\n\n"
    "3. Нужен ли опыт для участия?\n"
    "Требования зависят от объединения и выбранной деятельности. "
    "Уточни у его команды, есть ли занятия для начинающих и нужен ли отбор.\n\n"
    "4. Где узнать о встречах и мероприятиях?\n"
    "Посмотри ссылки в карточке интересующего объединения: в его сообществах "
    "можно искать анонсы и уточнять расписание у организаторов.\n\n"
    "5. Как связаться с командой ОСО?\n"
    "Нажми «Задать вопрос» и отправь сообщение. Мы передадим его команде, "
    "а ответ придёт сюда, в бот, ответом на твой вопрос."
)


def faq_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Задать вопрос", callback_data="ask_question")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back_to_main")],
    ])


def cancel_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад к вопросам", callback_data="faq")],
    ])


class SupportState(StatesGroup):
    waiting_for_question = State()


class QuestionStore:
    """Keep routing metadata across restarts without storing question contents."""

    def __init__(self, path: Path):
        self.path = path
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS support_questions (
                    staff_chat_id INTEGER NOT NULL,
                    staff_message_id INTEGER NOT NULL,
                    user_chat_id INTEGER NOT NULL,
                    user_message_id INTEGER NOT NULL,
                    PRIMARY KEY (staff_chat_id, staff_message_id)
                )
            """)

    def save(self, staff_chat_id: int, staff_message_id: int,
             user_chat_id: int, user_message_id: int) -> None:
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "INSERT INTO support_questions VALUES (?, ?, ?, ?)",
                (staff_chat_id, staff_message_id, user_chat_id, user_message_id),
            )

    def find(self, staff_chat_id: int, staff_message_id: int) -> tuple[int, int] | None:
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute(
                "SELECT user_chat_id, user_message_id FROM support_questions "
                "WHERE staff_chat_id = ? AND staff_message_id = ?",
                (staff_chat_id, staff_message_id),
            ).fetchone()


class Support:
    def __init__(self, chat_id: int | None, database: Path):
        if chat_id is not None and chat_id >= 0:
            raise ValueError("SUPPORT_CHAT_ID должен быть ID группы (отрицательное число)")
        self.chat_id = chat_id
        self.store = QuestionStore(database) if chat_id is not None else None
        self.router = Router(name="support")
        self.router.callback_query.register(self.show_faq, F.data == "faq")
        self.router.callback_query.register(self.ask_question, F.data == "ask_question")
        self.router.message.register(
            self.show_chat_id, Command("chat_id"), F.chat.type.in_({"group", "supergroup"}),
        )
        self.router.message.register(
            self.receive_question, SupportState.waiting_for_question, F.chat.type == "private",
        )
        if chat_id is not None:
            self.router.message.register(
                self.send_answer, F.chat.id == chat_id, F.reply_to_message,
            )

    async def show_chat_id(self, message: Message) -> None:
        await message.reply(f"ID этого чата: {message.chat.id}")

    async def show_faq(self, callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await callback.answer()
        if isinstance(callback.message, Message):
            await callback.message.edit_text(FAQ_TEXT, reply_markup=faq_menu())

    async def ask_question(self, callback: CallbackQuery, state: FSMContext) -> None:
        if not isinstance(callback.message, Message):
            await callback.answer()
            return
        if callback.message.chat.type != "private":
            await callback.answer("Задай вопрос в личном чате с ботом.", show_alert=True)
            return
        if self.chat_id is None:
            await callback.answer(
                "Приём вопросов пока не подключён. Попробуй позже.", show_alert=True,
            )
            return
        await callback.answer()
        await callback.message.edit_text(
            "✍️ Напиши свой вопрос одним текстовым сообщением (до 3000 символов).\n\n"
            "Текст вопроса получит команда ОСО. Ответ придёт сюда, в бот.",
            reply_markup=cancel_menu(),
        )
        await state.set_state(SupportState.waiting_for_question)

    async def receive_question(self, message: Message, state: FSMContext, bot: Bot) -> None:
        if self.chat_id is None or self.store is None:
            await state.clear()
            await message.answer("Приём вопросов пока не подключён.", reply_markup=faq_menu())
            return
        question = (message.text or "").strip()
        if not question or len(question) > 3000 or question.startswith("/"):
            await message.answer(
                "Отправь вопрос текстом, от 1 до 3000 символов.", reply_markup=cancel_menu(),
            )
            return
        try:
            staff_message = await bot.send_message(
                chat_id=self.chat_id,
                text="📩 Новый вопрос\n\n" + question + "\n\n"
                "Чтобы отправить ответ пользователю, ответьте на это сообщение "
                "через «Ответить» в Telegram.",
                parse_mode=None,
            )
        except TelegramAPIError:
            logger.exception("Could not send question to support chat")
            await message.answer(
                "Не удалось отправить вопрос. Попробуй ещё раз чуть позже.",
                reply_markup=cancel_menu(),
            )
            return
        try:
            self.store.save(self.chat_id, staff_message.message_id, message.chat.id, message.message_id)
        except sqlite3.Error:
            logger.exception("Could not save question routing")
            await bot.send_message(
                chat_id=self.chat_id,
                text="⚠️ Вопрос не зарегистрирован из-за ошибки. Ответ через бота недоступен.",
                reply_parameters=ReplyParameters(message_id=staff_message.message_id),
            )
            await message.answer("Не удалось зарегистрировать вопрос. Попробуй позже.")
            return
        await state.clear()
        await message.reply(
            "✅ Вопрос отправлен команде ОСО. Ответ придёт в этот чат.",
            reply_markup=faq_menu(),
        )

    async def send_answer(self, message: Message, bot: Bot) -> None:
        if message.chat.id != self.chat_id or self.store is None or not message.reply_to_message:
            return
        # Ignore bot messages; anonymous group administrators have sender_chat set.
        if message.from_user and message.from_user.is_bot and not message.sender_chat:
            return
        target = self.store.find(message.chat.id, message.reply_to_message.message_id)
        if target is None:
            return
        user_chat_id, user_message_id = target
        try:
            await bot.copy_message(
                chat_id=user_chat_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
                reply_parameters=ReplyParameters(
                    message_id=user_message_id, allow_sending_without_reply=True,
                ),
            )
        except TelegramAPIError:
            logger.exception("Could not deliver support reply")
            await message.reply(
                "❌ Ответ не доставлен. Возможно, пользователь заблокировал бота "
                "или этот тип сообщения нельзя отправить. Попробуйте ответить текстом ещё раз.",
            )
            return
        await message.reply("✅ Ответ отправлен пользователю.")
