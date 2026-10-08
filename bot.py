import asyncio
import json
import os
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher, F
from aiogram.filters.callback_data import CallbackData
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv
from support import Support
from faq import HELP_WINDOW_URL

from matching import MatchResult, recommend_organizations, validate_matching_config
from quiz_flow import (
    MAX_ROUTE_QUESTIONS,
    MIN_ROUTE_QUESTIONS,
    available_answer_indexes,
    next_question_id,
)


ENV_FILE = Path(__file__).with_name(".env")
ORGANIZATIONS_FILE = Path(__file__).with_name("organizations.json")
QUESTIONS_FILE = Path(__file__).with_name("questions.json")
load_dotenv(ENV_FILE)

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
SUPPORT_CHAT_ID = (os.getenv("SUPPORT_CHAT_ID") or "").strip()

if not BOT_TOKEN:
    raise RuntimeError(f"Не найден BOT_TOKEN в файле {ENV_FILE}")


dp = Dispatcher(
    storage=MemoryStorage(),
    events_isolation=SimpleEventIsolation(),
)
support = Support(
    chat_id=int(SUPPORT_CHAT_ID) if SUPPORT_CHAT_ID else None,
    database=Path(__file__).with_name("support.sqlite3"),
)
dp.include_router(support.router)

WELCOME_TEXT = (
    "👋 Привет!\n\n"
    "Это бот Объединенного Совета Обучающихся НИЯУ МИФИ.\n\n"
    "Здесь ты можешь узнать больше о деятельности нашего студенческого актива, о мероприятиях, об объединениях "
    "или пройти небольшой тест и найти то, что подходит именно тебе."
)

ORGANIZATIONS_MENU_TEXT = (
    "📚 Объединения\n\n"
    "Посмотри все объединения или пройди тест, чтобы подобрать подходящее."
)

HELP_WINDOW_TEXT = (
    "🤝 Единое окно помощи\n\n"
    "Здесь вам всегда помогут и поддержат 🧡\n\n"
    "Появились проблемы, которые вы не можете решить самостоятельно? "
    "Обратитесь в онлайн-приёмную проректора по молодёжной политике НИЯУ МИФИ.\n\n"
    "Сюда также можно написать свои идеи и предложения по улучшению жизни в вузе.\n\n"
    "Нажмите кнопку ниже, чтобы перейти в онлайн-приёмную.\n\n"
    "Как найти её самостоятельно:\n"
    "1. Зайдите на home.mephi.ru.\n"
    "2. Выберите раздел «Сервисы».\n"
    "3. Откройте «Прочее».\n"
    "4. Выберите «Онлайн приемная проректора по молодёжной политике»."
)


CATEGORIES = (
    ("community", "👥 Общественные"),
    ("sport", "🏆 Спорт"),
    ("student_squads", "🦺 Отряды"),
    ("volunteer", "🤝 Добровольчество"),
    ("culture", "🎭 КиТ — культура и творчество"),
    ("career", "💼 Карьерные сообщества"),
    ("media", "🎥 Медиа"),
    ("science", "🔬 Наука"),
    ("kid", "🌍 Клуб интернациональной дружбы"),
)

CATEGORY_NAMES = dict(CATEGORIES)
LEGACY_CATEGORY_ALIASES = {
    "dance": "culture",
    "music": "culture",
    "art": "culture",
    "clubs": "culture",
    "self_government": "community",
    "civic": "community",
    "international": "kid",
}
PAGE_SIZE = 6
QUIZ_STAGES = (
    (
        "Первые ориентиры",
        ("first_invite", "creative_material", "best_aftertaste"),
    ),
    (
        "Роль и смысл",
        (
            "ten_minutes",
            "new_team",
            "spring_growth",
            "campus_change",
            "event_meaning",
        ),
    ),
    (
        "Ритм участия",
        ("rhythm", "starting_point"),
    ),
    (
        "Точное совпадение",
        (
            "music_format",
            "stage_format",
            "small_club",
            "competition_format",
            "impact_target",
            "impact_method",
            "international_format",
            "summer_offer",
            "construction_character",
            "science_or_story",
        ),
    ),
)
MIN_QUIZ_QUESTIONS = MIN_ROUTE_QUESTIONS
MAX_QUIZ_QUESTIONS = MAX_ROUTE_QUESTIONS


class CategoryCallback(CallbackData, prefix="cat"):
    category_id: str
    page: int


class OrganizationCallback(CallbackData, prefix="org"):
    organization_id: str
    page: int


class QuizAnswerCallback(CallbackData, prefix="answer"):
    question_index: int
    answer_index: int


class QuizState(StatesGroup):
    in_progress = State()


def load_organizations() -> tuple[
    tuple[dict[str, Any], ...],
    dict[str, tuple[dict[str, Any], ...]],
]:
    try:
        raw_data = json.loads(ORGANIZATIONS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RuntimeError(f"Не найден файл {ORGANIZATIONS_FILE}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Некорректный JSON в файле {ORGANIZATIONS_FILE}: {error}"
        ) from error

    raw_organizations = raw_data.get("organizations") if isinstance(raw_data, dict) else None
    if not isinstance(raw_organizations, list):
        raise RuntimeError(
            f"В файле {ORGANIZATIONS_FILE} ожидается массив organizations"
        )

    organizations: list[dict[str, Any]] = []
    organizations_by_category: dict[str, list[dict[str, Any]]] = {
        category_id: [] for category_id in CATEGORY_NAMES
    }
    used_ids: set[str] = set()

    for position, item in enumerate(raw_organizations, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(
                f"Объединение №{position} в {ORGANIZATIONS_FILE} должно быть объектом"
            )

        organization_id = item.get("id")
        name = item.get("name")
        category_id = item.get("category")

        if not isinstance(organization_id, str) or not organization_id.strip():
            raise RuntimeError(f"У объединения №{position} отсутствует корректный id")
        if organization_id in used_ids:
            raise RuntimeError(f"Повторяющийся id объединения: {organization_id}")
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError(f"У объединения {organization_id} отсутствует название")
        if category_id not in CATEGORY_NAMES:
            raise RuntimeError(
                f"У объединения {organization_id} неизвестная категория: {category_id}"
            )

        organization: dict[str, Any] = {
            "id": organization_id.strip(),
            "name": name.strip(),
            "category": category_id,
        }

        for field_name in ("description", "how_to_join"):
            field_value = item.get(field_name)
            if field_value is not None and not isinstance(field_value, str):
                raise RuntimeError(
                    f"Поле {field_name} у объединения {organization_id} должно быть строкой"
                )
            if isinstance(field_value, str) and field_value.strip():
                organization[field_name] = field_value.strip()

        activities = item.get("activities", [])
        if not isinstance(activities, list) or not all(
            isinstance(activity, str) and activity.strip() for activity in activities
        ):
            raise RuntimeError(
                f"Поле activities у объединения {organization_id} должно быть массивом строк"
            )
        organization["activities"] = tuple(
            activity.strip() for activity in activities
        )

        links = item.get("links", [])
        if not isinstance(links, list):
            raise RuntimeError(
                f"Поле links у объединения {organization_id} должно быть массивом"
            )
        normalized_links: list[dict[str, str]] = []
        for link in links:
            if not isinstance(link, dict):
                raise RuntimeError(
                    f"Ссылка у объединения {organization_id} должна быть объектом"
                )
            label = link.get("label")
            url = link.get("url")
            if not isinstance(label, str) or not label.strip():
                raise RuntimeError(
                    f"У ссылки объединения {organization_id} отсутствует подпись"
                )
            if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                raise RuntimeError(
                    f"У ссылки объединения {organization_id} некорректный URL"
                )
            normalized_links.append({"label": label.strip(), "url": url.strip()})
        organization["links"] = tuple(normalized_links)

        category_provisional = item.get("category_provisional", False)
        if not isinstance(category_provisional, bool):
            raise RuntimeError(
                f"Поле category_provisional у {organization_id} должно быть логическим"
            )
        organization["category_provisional"] = category_provisional
        used_ids.add(organization["id"])
        organizations.append(organization)
        organizations_by_category[category_id].append(organization)

    return (
        tuple(organizations),
        {
            category_id: tuple(category_organizations)
            for category_id, category_organizations in organizations_by_category.items()
        },
    )


ORGANIZATIONS, ORGANIZATIONS_BY_CATEGORY = load_organizations()
ORGANIZATIONS_BY_ID = {
    organization["id"]: organization for organization in ORGANIZATIONS
}


def load_questions() -> tuple[dict[str, Any], ...]:
    try:
        raw_data = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RuntimeError(f"Не найден файл {QUESTIONS_FILE}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"Некорректный JSON в файле {QUESTIONS_FILE}: {error}"
        ) from error

    raw_questions = raw_data.get("questions") if isinstance(raw_data, dict) else None
    if not isinstance(raw_questions, list) or not raw_questions:
        raise RuntimeError(f"В файле {QUESTIONS_FILE} ожидается массив questions")

    questions: list[dict[str, Any]] = []
    used_question_ids: set[str] = set()

    for question_position, item in enumerate(raw_questions, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"Вопрос №{question_position} должен быть объектом")

        question_id = item.get("id")
        question_text = item.get("text")
        raw_answers = item.get("answers")

        if not isinstance(question_id, str) or not question_id.strip():
            raise RuntimeError(f"У вопроса №{question_position} отсутствует id")
        if question_id in used_question_ids:
            raise RuntimeError(f"Повторяющийся id вопроса: {question_id}")
        if not isinstance(question_text, str) or not question_text.strip():
            raise RuntimeError(f"У вопроса {question_id} отсутствует текст")
        if not isinstance(raw_answers, list) or len(raw_answers) < 2:
            raise RuntimeError(
                f"У вопроса {question_id} должно быть не менее двух ответов"
            )

        answers: list[dict[str, str]] = []
        used_answer_ids: set[str] = set()
        for answer_position, answer in enumerate(raw_answers, start=1):
            if not isinstance(answer, dict):
                raise RuntimeError(
                    f"Ответ №{answer_position} вопроса {question_id} должен быть объектом"
                )
            answer_id = answer.get("id")
            answer_text = answer.get("text")
            if not isinstance(answer_id, str) or not answer_id.strip():
                raise RuntimeError(
                    f"У ответа №{answer_position} вопроса {question_id} отсутствует id"
                )
            if answer_id in used_answer_ids:
                raise RuntimeError(
                    f"Повторяющийся id ответа {answer_id} в вопросе {question_id}"
                )
            if not isinstance(answer_text, str) or not answer_text.strip():
                raise RuntimeError(
                    f"У ответа {answer_id} вопроса {question_id} отсутствует текст"
                )

            used_answer_ids.add(answer_id)
            answers.append({"id": answer_id.strip(), "text": answer_text.strip()})

        used_question_ids.add(question_id)
        questions.append(
            {
                "id": question_id.strip(),
                "text": question_text.strip(),
                "answers": tuple(answers),
            }
        )

    return tuple(questions)


QUESTIONS = load_questions()
QUESTIONS_BY_ID = {question["id"]: question for question in QUESTIONS}
QUESTION_INDEX_BY_ID = {
    question["id"]: index for index, question in enumerate(QUESTIONS)
}
validate_matching_config(QUESTIONS, ORGANIZATIONS)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📚 Объединения",
                    callback_data="organizations",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❓ Часто задаваемые вопросы",
                    callback_data="faq",
                )
            ],
            [InlineKeyboardButton(text="🤝 Единое окно помощи", callback_data="help_window")],
        ]
    )


def help_window_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧡 Перейти в онлайн-приёмную", url=HELP_WINDOW_URL)],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back_to_main")],
    ])


def organizations_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎯 Подобрать объединение",
                    callback_data="start_quiz",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📚 Все объединения",
                    callback_data="catalog",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Главное меню",
                    callback_data="back_to_main",
                )
            ],
        ]
    )


def categories_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(
                text=category_name,
                callback_data=CategoryCallback(
                    category_id=category_id,
                    page=0,
                ).pack(),
            )
        ]
        for category_id, category_name in CATEGORIES
    ]
    keyboard.append(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="organizations")]
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def category_page_count(category_id: str) -> int:
    organization_count = len(ORGANIZATIONS_BY_CATEGORY[category_id])
    return max(1, (organization_count + PAGE_SIZE - 1) // PAGE_SIZE)


def organization_category_page(organization: dict[str, Any]) -> int:
    organizations = ORGANIZATIONS_BY_CATEGORY[organization["category"]]
    organization_index = next(
        index
        for index, candidate in enumerate(organizations)
        if candidate["id"] == organization["id"]
    )
    return organization_index // PAGE_SIZE


def category_text(category_id: str, page: int) -> str:
    category_name = CATEGORY_NAMES[category_id]
    page_count = category_page_count(category_id)
    organization_count = len(ORGANIZATIONS_BY_CATEGORY[category_id])
    if organization_count == 0:
        return (
            f"{category_name}\n\n"
            "В этой категории пока нет объединений в каталоге."
        )
    text = (
        f"{category_name}\n\n"
        f"Выберите объединение ({organization_count}):"
    )
    if page_count > 1:
        text += f"\n\nСтраница {page + 1} из {page_count}"
    return text


def category_menu(category_id: str, page: int) -> InlineKeyboardMarkup:
    organizations = ORGANIZATIONS_BY_CATEGORY[category_id]
    page_count = category_page_count(category_id)
    start = page * PAGE_SIZE
    page_organizations = organizations[start : start + PAGE_SIZE]

    keyboard = [
        [
            InlineKeyboardButton(
                text=organization["name"],
                callback_data=OrganizationCallback(
                    organization_id=organization["id"],
                    page=page,
                ).pack(),
            )
        ]
        for organization in page_organizations
    ]

    pagination_row: list[InlineKeyboardButton] = []
    if page > 0:
        pagination_row.append(
            InlineKeyboardButton(
                text="◀️",
                callback_data=CategoryCallback(
                    category_id=category_id,
                    page=page - 1,
                ).pack(),
            )
        )
    if page + 1 < page_count:
        pagination_row.append(
            InlineKeyboardButton(
                text="▶️",
                callback_data=CategoryCallback(
                    category_id=category_id,
                    page=page + 1,
                ).pack(),
            )
        )
    if pagination_row:
        keyboard.append(pagination_row)

    keyboard.append(
        [InlineKeyboardButton(text="⬅️ К категориям", callback_data="catalog")]
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def organization_card_text(organization: dict[str, Any]) -> str:
    description = organization.get("description", "Информация уточняется.")
    activities = organization.get("activities", ())
    links = organization.get("links", ())
    how_to_join = organization.get(
        "how_to_join",
        "Используйте контактные кнопки ниже."
        if links
        else "Информация уточняется.",
    )

    if activities:
        activity_text = "\n".join(f"• {activity}" for activity in activities)
    else:
        activity_text = "• Информация уточняется."

    contact_text = "Кнопки под карточкой." if links else "Информация уточняется."
    text = (
        f"📌 {organization['name']}\n\n"
        f"Направление: {CATEGORY_NAMES[organization['category']]}\n\n"
        f"{description}\n\n"
        f"Что ты будешь делать:\n{activity_text}\n\n"
        f"Как вступить: {how_to_join}\n\n"
        f"Контакты: {contact_text}"
    )
    if organization.get("category_provisional"):
        text += "\n\n⚠️ Направление объединения пока уточняется."
    return text


def organization_menu(
    organization: dict[str, Any],
    page: int,
) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text=link["label"], url=link["url"])]
        for link in organization.get("links", ())
    ]
    keyboard.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад к списку",
                callback_data=CategoryCallback(
                    category_id=organization["category"],
                    page=page,
                ).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def quiz_question_text(
    question_index: int,
    answered_count: int,
) -> str:
    current = answered_count + 1
    question = QUESTIONS[question_index]
    question_id = question["id"]
    stage_index, (stage_name, _) = next(
        (index, stage)
        for index, stage in enumerate(QUIZ_STAGES, start=1)
        if question_id in stage[1]
    )
    stage_tracker = "▰" * stage_index + "▱" * (len(QUIZ_STAGES) - stage_index)

    minimum_total = max(MIN_QUIZ_QUESTIONS, current)
    if minimum_total == MAX_QUIZ_QUESTIONS:
        question_counter = f"Вопрос {current} из {MAX_QUIZ_QUESTIONS}"
    else:
        question_counter = (
            f"Вопрос {current} · всего {minimum_total}–{MAX_QUIZ_QUESTIONS}"
        )

    return (
        f"{question_counter}\n"
        f"Этап {stage_index} из {len(QUIZ_STAGES)} · {stage_name}\n"
        f"{stage_tracker}\n\n"
        f"{question['text']}"
    )


def quiz_question_menu(
    question_index: int,
    answers: list[dict[str, str]],
) -> InlineKeyboardMarkup:
    question = QUESTIONS[question_index]
    keyboard = [
        [
            InlineKeyboardButton(
                text=question["answers"][answer_index]["text"],
                callback_data=QuizAnswerCallback(
                    question_index=question_index,
                    answer_index=answer_index,
                ).pack(),
            )
        ]
        for answer_index in available_answer_indexes(question, answers)
    ]
    keyboard.append(
        [
            InlineKeyboardButton(
                text="✖️ Отменить тест",
                callback_data="quiz_cancel",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def quiz_results_text(results: tuple[MatchResult, ...]) -> str:
    lines = [
        "✨ Твои рекомендации",
        "",
    ]
    for position, result in enumerate(results, start=1):
        organization = ORGANIZATIONS_BY_ID[result.organization_id]
        lines.append(f"{position}. {organization['name']}")

    lines.extend(
        (
            "",
            "Выбери объединение, чтобы открыть подробную карточку.",
        )
    )

    return "\n".join(lines)


def quiz_complete_menu(results: tuple[MatchResult, ...]) -> InlineKeyboardMarkup:
    result_buttons = [
        [
            InlineKeyboardButton(
                text=f"{position}. {ORGANIZATIONS_BY_ID[result.organization_id]['name']}",
                callback_data=OrganizationCallback(
                    organization_id=result.organization_id,
                    page=organization_category_page(
                        ORGANIZATIONS_BY_ID[result.organization_id]
                    ),
                ).pack(),
            )
        ]
        for position, result in enumerate(results, start=1)
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=result_buttons
        + [
            [
                InlineKeyboardButton(
                    text="🔄 Пройти ещё раз",
                    callback_data="start_quiz",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Главное меню",
                    callback_data="back_to_main",
                )
            ],
        ]
    )


@dp.message(CommandStart(), F.chat.type == "private")
async def start_handler(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        WELCOME_TEXT,
        reply_markup=main_menu(),
    )


@dp.callback_query(F.data == "help_window")
async def help_window_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_text(HELP_WINDOW_TEXT, reply_markup=help_window_menu())


@dp.callback_query(F.data == "organizations")
async def organizations_button_handler(
    callback: CallbackQuery, state: FSMContext
) -> None:
    await state.clear()
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            ORGANIZATIONS_MENU_TEXT,
            reply_markup=organizations_menu(),
        )


@dp.callback_query(F.data == "start_quiz")
async def quiz_button_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        first_question_id = next_question_id([])
        if first_question_id is None:
            raise RuntimeError("В адаптивном опросе нет первого вопроса")
        first_question_index = QUESTION_INDEX_BY_ID[first_question_id]
        await state.set_state(QuizState.in_progress)
        await state.set_data(
            {"question_index": first_question_index, "answers": []}
        )
        await callback.message.edit_text(
            quiz_question_text(first_question_index, 0),
            reply_markup=quiz_question_menu(first_question_index, []),
        )


@dp.callback_query(
    StateFilter(QuizState.in_progress),
    QuizAnswerCallback.filter(),
)
async def quiz_answer_handler(
    callback: CallbackQuery,
    callback_data: QuizAnswerCallback,
    state: FSMContext,
) -> None:
    state_data = await state.get_data()
    current_question_index = state_data.get("question_index")

    if current_question_index != callback_data.question_index:
        await callback.answer("Этот вопрос уже отвечен", show_alert=True)
        return
    if not 0 <= callback_data.question_index < len(QUESTIONS):
        await callback.answer("Вопрос не найден", show_alert=True)
        return

    question = QUESTIONS[callback_data.question_index]
    if not 0 <= callback_data.answer_index < len(question["answers"]):
        await callback.answer("Ответ не найден", show_alert=True)
        return

    answers = list(state_data.get("answers", []))
    if callback_data.answer_index not in available_answer_indexes(question, answers):
        await callback.answer("Этот вариант больше не подходит", show_alert=True)
        return

    answer = question["answers"][callback_data.answer_index]
    answers.append(
        {
            "question_id": question["id"],
            "answer_id": answer["id"],
        }
    )
    next_question = next_question_id(answers)

    await callback.answer()
    if next_question is None:
        results = recommend_organizations(
            answers,
            QUESTIONS,
            ORGANIZATIONS,
            user_id=callback.from_user.id,
        )
        await state.clear()
        if isinstance(callback.message, Message):
            await callback.message.edit_text(
                quiz_results_text(results),
                reply_markup=quiz_complete_menu(results),
            )
        return

    next_question_index = QUESTION_INDEX_BY_ID[next_question]
    await state.update_data(
        question_index=next_question_index,
        answers=answers,
    )
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            quiz_question_text(next_question_index, len(answers)),
            reply_markup=quiz_question_menu(next_question_index, answers),
        )


@dp.callback_query(QuizAnswerCallback.filter())
async def stale_quiz_answer_handler(callback: CallbackQuery) -> None:
    await callback.answer(
        "Этот опрос уже завершён. Запусти новый из главного меню.",
        show_alert=True,
    )


@dp.callback_query(F.data == "quiz_cancel")
async def quiz_cancel_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Опрос отменён")
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            ORGANIZATIONS_MENU_TEXT,
            reply_markup=organizations_menu(),
        )


@dp.callback_query(F.data == "catalog")
async def catalog_button_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            "📚 Каталог студенческих объединений\n\n"
            "Выберите направление:",
            reply_markup=categories_menu(),
        )


async def open_category(
    callback: CallbackQuery,
    category_id: str,
    page: int,
) -> None:
    category_id = LEGACY_CATEGORY_ALIASES.get(category_id, category_id)
    if category_id not in CATEGORY_NAMES:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    if page < 0 or page >= category_page_count(category_id):
        await callback.answer("Страница не найдена", show_alert=True)
        return

    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            category_text(category_id, page),
            reply_markup=category_menu(category_id, page),
        )


@dp.callback_query(CategoryCallback.filter())
async def category_button_handler(
    callback: CallbackQuery,
    callback_data: CategoryCallback,
) -> None:
    await open_category(
        callback,
        callback_data.category_id,
        callback_data.page,
    )


@dp.callback_query(F.data.startswith("category:"))
async def legacy_category_button_handler(callback: CallbackQuery) -> None:
    category_id = (callback.data or "").removeprefix("category:")
    await open_category(callback, category_id, 0)


@dp.callback_query(OrganizationCallback.filter())
async def organization_button_handler(
    callback: CallbackQuery,
    callback_data: OrganizationCallback,
) -> None:
    organization = ORGANIZATIONS_BY_ID.get(callback_data.organization_id)
    if not organization:
        await callback.answer("Объединение не найдено", show_alert=True)
        return

    category_id = organization["category"]
    if callback_data.page < 0 or callback_data.page >= category_page_count(category_id):
        await callback.answer("Страница не найдена", show_alert=True)
        return

    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            organization_card_text(organization),
            reply_markup=organization_menu(organization, callback_data.page),
        )


@dp.callback_query(F.data == "back_to_main")
async def back_to_main_handler(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            WELCOME_TEXT,
            reply_markup=main_menu(),
        )


async def main() -> None:
    bot = Bot(token=BOT_TOKEN)

    try:
        bot_info = await bot.get_me()
        print(f"Бот @{bot_info.username} запущен и подключён к Telegram!")
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
