import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
from aiogram.methods import CopyMessage, SendMessage
from aiogram.types import Message, Update

from support import FAQ_TEXT, QuestionStore, Support, SupportState


def message(chat_id=123, message_id=10, text="Как вступить?"):
    result = AsyncMock(spec=Message)
    result.chat = SimpleNamespace(id=chat_id, type="private" if chat_id > 0 else "supergroup")
    result.message_id = message_id
    result.text = text
    result.reply_to_message = None
    result.from_user = SimpleNamespace(is_bot=False)
    result.sender_chat = None
    result.answer = AsyncMock()
    result.reply = AsyncMock()
    result.edit_text = AsyncMock()
    return result


class SupportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "support.sqlite3"
        self.support = Support(-100123, self.path)
        self.bot = AsyncMock(spec=Bot)
        self.bot.send_message.return_value = SimpleNamespace(message_id=77)
        self.state = AsyncMock(spec=FSMContext)

    async def test_question_and_reply_remain_linked_after_restart(self):
        incoming = message()
        await self.support.receive_question(incoming, self.state, self.bot)
        self.assertIn(incoming.text, self.bot.send_message.call_args.kwargs["text"])
        self.assertEqual(self.bot.send_message.call_args.kwargs["chat_id"], -100123)
        self.state.clear.assert_awaited_once()
        restarted = Support(-100123, self.path)
        answer = message(-100123, 88, "Напиши организаторам")
        answer.reply_to_message = SimpleNamespace(message_id=77)
        await restarted.send_answer(answer, self.bot)
        data = self.bot.copy_message.call_args.kwargs
        self.assertEqual((data["chat_id"], data["message_id"]), (123, 88))
        self.assertEqual(data["reply_parameters"].message_id, 10)
        self.assertTrue(data["reply_parameters"].allow_sending_without_reply)
        answer.reply.assert_awaited_once_with("✅ Ответ отправлен пользователю.")

    async def test_different_users_get_their_own_answers(self):
        self.support.store.save(-100123, 77, 123, 10)
        self.support.store.save(-100123, 78, 456, 11)
        for staff_id, user_id, original_id in ((78, 456, 11), (77, 123, 10)):
            answer = message(-100123)
            answer.reply_to_message = SimpleNamespace(message_id=staff_id)
            await self.support.send_answer(answer, self.bot)
            data = self.bot.copy_message.call_args.kwargs
            self.assertEqual(data["chat_id"], user_id)
            self.assertEqual(data["reply_parameters"].message_id, original_id)

    async def test_unrelated_messages_and_other_chats_cannot_send_answers(self):
        self.support.store.save(-100123, 77, 123, 10)
        for chat_id, reply_id in ((-999, 77), (-100123, 999), (-100123, None)):
            answer = message(chat_id)
            if reply_id:
                answer.reply_to_message = SimpleNamespace(message_id=reply_id)
            await self.support.send_answer(answer, self.bot)
        self.bot.copy_message.assert_not_awaited()

    async def test_failed_question_can_be_retried(self):
        self.bot.send_message.side_effect = TelegramForbiddenError(
            method=SendMessage(chat_id=-100123, text="question"), message="Forbidden",
        )
        incoming = message()
        with self.assertLogs("support", level="ERROR"):
            await self.support.receive_question(incoming, self.state, self.bot)
        self.state.clear.assert_not_awaited()
        incoming.reply.assert_not_awaited()
        self.assertIsNone(self.support.store.find(-100123, 77))

    async def test_blocked_user_does_not_receive_false_success(self):
        self.support.store.save(-100123, 77, 123, 10)
        self.bot.copy_message.side_effect = TelegramForbiddenError(
            method=CopyMessage(chat_id=123, from_chat_id=-100123, message_id=88),
            message="Forbidden",
        )
        answer = message(-100123, 88)
        answer.reply_to_message = SimpleNamespace(message_id=77)
        with self.assertLogs("support", level="ERROR"):
            await self.support.send_answer(answer, self.bot)
        self.assertIn("Ответ не доставлен", answer.reply.call_args.args[0])

    async def test_invalid_questions_do_not_reach_staff(self):
        for text in (None, "   ", "x" * 3001, "/unknown"):
            await self.support.receive_question(message(text=text), self.state, self.bot)
        self.bot.send_message.assert_not_awaited()
        self.state.clear.assert_not_awaited()

    async def test_missing_configuration_does_not_start_question(self):
        support = Support(None, self.path)
        callback = AsyncMock()
        callback.message = message()
        await support.ask_question(callback, self.state)
        self.state.set_state.assert_not_awaited()
        self.assertTrue(callback.answer.call_args.kwargs["show_alert"])

    async def test_faq_cancels_question_and_has_ask_button(self):
        callback = AsyncMock()
        callback.message = message()
        await self.support.show_faq(callback, self.state)
        self.state.clear.assert_awaited_once()
        args = callback.message.edit_text.call_args
        self.assertEqual(args.args[0], FAQ_TEXT)
        self.assertEqual(args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data, "ask_question")

    async def test_asking_question_enters_waiting_state(self):
        callback = AsyncMock()
        callback.message = message()
        await self.support.ask_question(callback, self.state)
        self.state.set_state.assert_awaited_once_with(SupportState.waiting_for_question)

    async def test_dispatcher_routes_private_question_and_group_answer(self):
        from unittest.mock import patch

        dispatcher = Dispatcher(storage=MemoryStorage())
        dispatcher.include_router(self.support.router)
        telegram_bot = Bot("123456:TEST_TOKEN")
        self.addAsyncCleanup(telegram_bot.session.close)
        state = FSMContext(
            storage=dispatcher.storage,
            key=StorageKey(bot_id=telegram_bot.id, chat_id=123, user_id=123),
        )
        await state.set_state(SupportState.waiting_for_question)
        base = {"date": 1, "from": {"id": 123, "is_bot": False, "first_name": "User"}}
        incoming = Update.model_validate({"update_id": 1, "message": {
            **base, "message_id": 10, "chat": {"id": 123, "type": "private"}, "text": "Question",
        }})
        answer = Update.model_validate({"update_id": 2, "message": {
            **base, "message_id": 88, "chat": {"id": -100123, "type": "supergroup", "title": "Staff"},
            "text": "Answer", "reply_to_message": {
                **base, "message_id": 77,
                "chat": {"id": -100123, "type": "supergroup", "title": "Staff"}, "text": "Question",
            },
        }})
        with patch.object(Bot, "__call__", new_callable=AsyncMock) as api:
            api.return_value = SimpleNamespace(message_id=77)
            await dispatcher.feed_update(telegram_bot, incoming)
            await dispatcher.feed_update(telegram_bot, answer)
        copies = [call.args[0] for call in api.await_args_list if isinstance(call.args[0], CopyMessage)]
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].chat_id, 123)
        self.assertEqual(copies[0].reply_parameters.message_id, 10)
        self.assertIsNone(await state.get_state())


if __name__ == "__main__":
    unittest.main()
