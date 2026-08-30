import unittest

import bot
from matching import MatchResult
from quiz_flow import available_answer_indexes


class MobileQuizUiTests(unittest.TestCase):
    def test_results_do_not_show_internal_quiz_details(self) -> None:
        text = bot.quiz_results_text(
            (
                MatchResult(
                    organization_id="sno",
                    score=10,
                    reasons=("Интерес к науке",),
                ),
            )
        )
        self.assertNotIn("вопрос", text.lower())
        self.assertNotIn("ветк", text.lower())
        self.assertNotIn("адаптив", text.lower())
        self.assertNotIn("Интерес к науке", text)
        self.assertNotIn("Почему подходит", text)
        self.assertIn("Выбери объединение", text)
        self.assertFalse(text.endswith("\n"))

    def test_question_text_only_shows_counter_stage_tracker_and_question(self) -> None:
        scenarios = (
            (
                "first_invite",
                0,
                "Вопрос 1 · всего 13–16",
                "Этап 1 из 4 · Первые ориентиры",
                "▰▱▱▱",
            ),
            (
                "ten_minutes",
                3,
                "Вопрос 4 · всего 13–16",
                "Этап 2 из 4 · Роль и смысл",
                "▰▰▱▱",
            ),
            (
                "rhythm",
                8,
                "Вопрос 9 · всего 13–16",
                "Этап 3 из 4 · Ритм участия",
                "▰▰▰▱",
            ),
            (
                "music_format",
                10,
                "Вопрос 11 · всего 13–16",
                "Этап 4 из 4 · Точное совпадение",
                "▰▰▰▰",
            ),
            (
                "science_or_story",
                15,
                "Вопрос 16 из 16",
                "Этап 4 из 4 · Точное совпадение",
                "▰▰▰▰",
            ),
        )
        for question_id, answered_count, counter, stage, tracker in scenarios:
            question_index = bot.QUESTION_INDEX_BY_ID[question_id]
            text = bot.quiz_question_text(question_index, answered_count)
            with self.subTest(question=question_id):
                self.assertIn(counter, text)
                self.assertIn(stage, text)
                self.assertIn(tracker, text)
                self.assertIn(bot.QUESTIONS[question_index]["text"], text)
                self.assertNotIn("адаптив", text.lower())
                self.assertNotIn("Следующие вопросы", text)

    def test_quiz_stages_cover_every_question_once(self) -> None:
        staged_question_ids = [
            question_id
            for _, question_ids in bot.QUIZ_STAGES
            for question_id in question_ids
        ]
        self.assertEqual(len(staged_question_ids), len(set(staged_question_ids)))
        self.assertEqual(set(staged_question_ids), set(bot.QUESTIONS_BY_ID))

    def test_answer_buttons_are_short_full_width_rows(self) -> None:
        for question_index, question in enumerate(bot.QUESTIONS):
            menu = bot.quiz_question_menu(question_index, [])
            available = available_answer_indexes(question, [])
            answer_rows = menu.inline_keyboard[:-1]

            with self.subTest(question=question["id"]):
                self.assertEqual(len(answer_rows), len(available))
                self.assertTrue(all(len(row) == 1 for row in answer_rows))

                for answer_index, row in zip(available, answer_rows, strict=True):
                    answer = question["answers"][answer_index]
                    button = row[0]
                    self.assertEqual(button.text, answer["text"])
                    self.assertLessEqual(len(button.text), 30)
                    callback = bot.QuizAnswerCallback.unpack(button.callback_data)
                    self.assertEqual(callback.question_index, question_index)
                    self.assertEqual(callback.answer_index, answer_index)

    def test_creativity_refusal_shortens_later_answer_lists(self) -> None:
        answers = [
            {"question_id": "first_invite", "answer_id": "topic"},
            {"question_id": "creative_material", "answer_id": "none"},
        ]
        question_index = bot.QUESTION_INDEX_BY_ID["event_meaning"]
        question = bot.QUESTIONS[question_index]
        menu = bot.quiz_question_menu(question_index, answers)
        answer_buttons = [button for row in menu.inline_keyboard[:-1] for button in row]
        callback_indexes = [
            bot.QuizAnswerCallback.unpack(button.callback_data).answer_index
            for button in answer_buttons
        ]

        self.assertEqual(callback_indexes, [0, 2, 3, 4, 5, 7])
        self.assertNotIn(question["answers"][1]["text"], [b.text for b in answer_buttons])
        self.assertNotIn(question["answers"][6]["text"], [b.text for b in answer_buttons])


if __name__ == "__main__":
    unittest.main()
