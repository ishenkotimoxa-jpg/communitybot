from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


MIN_ROUTE_QUESTIONS = 13
MAX_ROUTE_QUESTIONS = 16

# The first ten questions deliberately cover different dimensions: interests,
# values, role, audience and preferred pace.  Narrow questions are selected
# afterwards from the evidence already collected.
CORE_QUESTION_ORDER = (
    "first_invite",
    "creative_material",
    "best_aftertaste",
    "ten_minutes",
    "new_team",
    "spring_growth",
    "campus_change",
    "event_meaning",
    "rhythm",
    "starting_point",
)

BRANCH_QUESTION_ORDER = (
    "music_format",
    "stage_format",
    "impact_target",
    "impact_method",
    "competition_format",
    "summer_offer",
    "construction_character",
    "small_club",
    "international_format",
    "science_or_story",
)

QUESTION_ORDER = CORE_QUESTION_ORDER + BRANCH_QUESTION_ORDER

# If the general answers are deliberately neutral, these questions safely
# explore different areas without assuming that the user already likes them.
FALLBACK_QUESTION_ORDER = (
    "impact_target",
    "small_club",
    "competition_format",
    "summer_offer",
    "science_or_story",
)


def _selected_answers(
    answers: Sequence[Mapping[str, str]],
) -> dict[str, str]:
    return {
        str(answer["question_id"]): str(answer["answer_id"])
        for answer in answers
        if answer.get("question_id") and answer.get("answer_id")
    }


def _count_matches(
    selected: Mapping[str, str],
    choices: set[tuple[str, str]],
) -> int:
    return sum(
        selected.get(question_id) == answer_id
        for question_id, answer_id in choices
    )


def question_relevance_score(
    question_id: str,
    answers: Sequence[Mapping[str, str]],
) -> int:
    if question_id in CORE_QUESTION_ORDER:
        return 100

    selected = _selected_answers(answers)

    if question_id == "music_format":
        return 100 if selected.get("creative_material") in {"voice", "instrument"} else 0

    if question_id == "stage_format":
        return 100 if selected.get("creative_material") in {"dance", "character", "mix"} else 0

    if question_id == "impact_method":
        target = selected.get("impact_target")
        return 100 if target is not None and target != "none" else 0

    if question_id == "construction_character":
        return 100 if selected.get("summer_offer") == "construction" else 0

    if question_id == "international_format":
        direct_parent = _count_matches(
            selected,
            {
                ("impact_target", "international"),
                ("small_club", "languages"),
                ("event_meaning", "cultures"),
            },
        )
        broad_interest = _count_matches(
            selected,
            {
                ("campus_change", "introductions"),
                ("first_invite", "help_new"),
            },
        )
        return 90 * direct_parent + 20 * broad_interest

    triggers: dict[str, set[tuple[str, str]]] = {
        "impact_target": {
            ("first_invite", "help_new"),
            ("best_aftertaste", "helped"),
            ("best_aftertaste", "big_thing"),
            ("ten_minutes", "support"),
            ("new_team", "newcomers"),
            ("new_team", "represent"),
            ("campus_change", "freshmen"),
            ("campus_change", "dorm"),
            ("campus_change", "studies"),
            ("campus_change", "introductions"),
            ("event_meaning", "memory"),
            ("event_meaning", "cultures"),
            ("event_meaning", "charity"),
        },
        "competition_format": {
            ("first_invite", "game"),
            ("best_aftertaste", "victory"),
            ("spring_growth", "move"),
            ("campus_change", "movement"),
            ("event_meaning", "sport"),
            ("rhythm", "tournaments"),
            ("starting_point", "strong_team"),
            ("creative_material", "dance"),
        },
        "summer_offer": {
            ("first_invite", "summer_trip"),
            ("spring_growth", "hands"),
            ("rhythm", "summer"),
            ("starting_point", "strong_team"),
        },
        "small_club": {
            ("first_invite", "game"),
            ("first_invite", "topic"),
            ("best_aftertaste", "understood"),
            ("best_aftertaste", "own_people"),
            ("new_team", "one_two"),
            ("new_team", "alone"),
            ("spring_growth", "people"),
            ("rhythm", "calm"),
            ("creative_material", "text"),
        },
        "science_or_story": {
            ("first_invite", "topic"),
            ("first_invite", "campus_story"),
            ("best_aftertaste", "understood"),
            ("ten_minutes", "camera"),
            ("ten_minutes", "troubleshoot"),
            ("spring_growth", "photo_video"),
            ("spring_growth", "research"),
            ("campus_change", "awareness"),
            ("event_meaning", "science"),
        },
    }
    if question_id not in triggers:
        raise ValueError(f"Unknown quiz question: {question_id}")
    return 25 * _count_matches(selected, triggers[question_id])


def question_is_relevant(
    question_id: str,
    answers: Sequence[Mapping[str, str]],
) -> bool:
    return question_relevance_score(question_id, answers) > 0


def next_question_id(answers: Sequence[Mapping[str, str]]) -> str | None:
    selected = _selected_answers(answers)

    for question_id in CORE_QUESTION_ORDER:
        if question_id not in selected:
            return question_id

    if len(selected) >= MAX_ROUTE_QUESTIONS:
        return None

    ranked_branches = sorted(
        (
            (question_relevance_score(question_id, answers), position, question_id)
            for position, question_id in enumerate(BRANCH_QUESTION_ORDER)
            if question_id not in selected
        ),
        key=lambda item: (-item[0], item[1]),
    )
    if ranked_branches and ranked_branches[0][0] > 0:
        return ranked_branches[0][2]

    if len(selected) < MIN_ROUTE_QUESTIONS:
        for question_id in FALLBACK_QUESTION_ORDER:
            if question_id not in selected:
                return question_id

    return None


# A rejection closes only that subject. Neutral answers such as "пока посмотрю"
# intentionally do not close anything.
REJECTED_DOMAINS: dict[tuple[str, str], frozenset[str]] = {
    ("creative_material", "none"): frozenset({"creative"}),
    ("music_format", "none"): frozenset({"music"}),
    ("stage_format", "none"): frozenset({"stage"}),
    ("event_meaning", "none"): frozenset({"large_event"}),
    ("small_club", "none"): frozenset({"small_club"}),
    ("competition_format", "none"): frozenset({"competition"}),
    ("impact_target", "none"): frozenset({"social_impact"}),
    ("impact_method", "none"): frozenset({"organizing"}),
    ("international_format", "none"): frozenset({"international"}),
    ("summer_offer", "none"): frozenset({"student_squad"}),
    ("construction_character", "none"): frozenset({"construction"}),
    ("science_or_story", "none"): frozenset({"science_media"}),
}


ANSWER_DOMAINS: dict[tuple[str, str], frozenset[str]] = {
    ("best_aftertaste", "beautiful"): frozenset({"creative"}),
    ("ten_minutes", "decorate"): frozenset({"creative"}),
    ("event_meaning", "ball"): frozenset({"creative", "large_event"}),
    ("event_meaning", "sport"): frozenset({"large_event"}),
    ("event_meaning", "cultures"): frozenset({"large_event", "international"}),
    ("event_meaning", "charity"): frozenset({"large_event", "social_impact"}),
    ("event_meaning", "science"): frozenset({"large_event", "science_media"}),
    ("event_meaning", "festival"): frozenset({"creative", "large_event"}),
    ("music_format", "solo"): frozenset({"creative", "music"}),
    ("music_format", "chamber"): frozenset({"creative", "music"}),
    ("music_format", "male_academic"): frozenset({"creative", "music"}),
    ("music_format", "piano"): frozenset({"creative", "music"}),
    ("music_format", "orchestra"): frozenset({"creative", "music"}),
    ("music_format", "band"): frozenset({"creative", "music"}),
    ("stage_format", "ballroom"): frozenset({"creative", "stage"}),
    ("stage_format", "hiphop"): frozenset({"creative", "stage"}),
    ("stage_format", "contemporary"): frozenset({"creative", "stage"}),
    ("stage_format", "ball"): frozenset({"creative", "stage"}),
    ("stage_format", "comedy"): frozenset({"creative", "stage"}),
    ("stage_format", "mixed"): frozenset({"creative", "stage"}),
    ("small_club", "poetry"): frozenset({"creative", "small_club"}),
    ("small_club", "languages"): frozenset({"small_club", "international"}),
    ("competition_format", "dance"): frozenset({"creative", "competition"}),
    ("competition_format", "varsity"): frozenset({"competition"}),
    ("competition_format", "sport_event"): frozenset({"competition"}),
    ("competition_format", "esport_player"): frozenset({"competition"}),
    ("competition_format", "esport_event"): frozenset({"competition"}),
    ("competition_format", "debates"): frozenset({"competition"}),
    ("competition_format", "tabletop"): frozenset({"competition"}),
    ("impact_method", "meeting"): frozenset({"organizing", "large_event"}),
    ("international_format", "one_culture"): frozenset({"international"}),
    ("international_format", "many_cultures"): frozenset({"international"}),
    ("international_format", "help_guests"): frozenset({"international"}),
    ("international_format", "language"): frozenset({"international"}),
    ("international_format", "event"): frozenset({"international", "large_event"}),
    ("summer_offer", "children"): frozenset({"student_squad"}),
    ("summer_offer", "construction"): frozenset({"student_squad"}),
    ("summer_offer", "train"): frozenset({"student_squad"}),
    ("summer_offer", "restoration"): frozenset({"student_squad"}),
    ("summer_offer", "fishery"): frozenset({"student_squad"}),
    ("construction_character", "large_object"): frozenset({"construction"}),
    ("construction_character", "trip"): frozenset({"construction"}),
    ("construction_character", "creative"): frozenset({"construction", "creative"}),
    ("construction_character", "sport"): frozenset({"construction"}),
    ("construction_character", "team"): frozenset({"construction"}),
}


def rejected_domains(answers: Sequence[Mapping[str, str]]) -> frozenset[str]:
    selected = _selected_answers(answers)
    domains: set[str] = set()
    for question_id, answer_id in selected.items():
        domains.update(REJECTED_DOMAINS.get((question_id, answer_id), ()))
    return frozenset(domains)


def available_answer_indexes(
    question: Mapping[str, Any],
    answers: Sequence[Mapping[str, str]],
) -> tuple[int, ...]:
    excluded = rejected_domains(answers)
    indexes = tuple(
        index
        for index, answer in enumerate(question["answers"])
        if not (
            ANSWER_DOMAINS.get(
                (str(question["id"]), str(answer["id"])),
                frozenset(),
            )
            & excluded
        )
    )

    if len(indexes) < 2 and question_is_relevant(str(question["id"]), answers):
        raise RuntimeError(
            f"Adaptive filtering left fewer than two answers for {question['id']}"
        )
    return indexes
