import json
import random
import unittest
from pathlib import Path

from matching import (
    AXIS_BUDGETS,
    DISABLED_ORGANIZATION_IDS,
    ORGANIZATION_PROFILES,
    recommend_organizations,
    validate_matching_config,
)
from quiz_flow import (
    ANSWER_DOMAINS,
    MAX_ROUTE_QUESTIONS,
    MIN_ROUTE_QUESTIONS,
    available_answer_indexes,
    next_question_id,
)


ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = tuple(
    json.loads((ROOT / "questions.json").read_text(encoding="utf-8"))["questions"]
)
ORGANIZATIONS = tuple(
    json.loads((ROOT / "organizations.json").read_text(encoding="utf-8"))[
        "organizations"
    ]
)
QUESTIONS_BY_ID = {question["id"]: question for question in QUESTIONS}


def answer(question_id: str, answer_id: str) -> dict[str, str]:
    return {"question_id": question_id, "answer_id": answer_id}


NEUTRAL_ANSWERS = (
    "look_all",
    "different",
    "any",
    "depends",
    "all",
    "create",
    "none",
    "flexible",
    "observe",
)


def complete_route(preferred: dict[str, str]) -> list[dict[str, str]]:
    answers: list[dict[str, str]] = []
    while (question_id := next_question_id(answers)) is not None:
        question = QUESTIONS_BY_ID[question_id]
        available = available_answer_indexes(question, answers)
        preferred_ids = (preferred.get(question_id), *NEUTRAL_ANSWERS)
        selected_index = next(
            (
                index
                for candidate_id in preferred_ids
                if candidate_id is not None
                for index in available
                if question["answers"][index]["id"] == candidate_id
            ),
            available[0],
        )
        answers.append(answer(question_id, question["answers"][selected_index]["id"]))
    return answers


def recommend(selected: dict[str, str], user_id: int = 1):
    return recommend_organizations(
        [answer(question_id, answer_id) for question_id, answer_id in selected.items()],
        QUESTIONS,
        ORGANIZATIONS,
        user_id=user_id,
    )


class AdaptiveQuizTests(unittest.TestCase):
    def test_configuration_uses_separate_limited_axes(self) -> None:
        validate_matching_config(QUESTIONS, ORGANIZATIONS)
        self.assertEqual(sum(AXIS_BUDGETS.values()), 100)
        self.assertEqual(AXIS_BUDGETS["role"] + AXIS_BUDGETS["format"], 21)
        self.assertGreater(
            AXIS_BUDGETS["domain"] + AXIS_BUDGETS["anchor"],
            AXIS_BUDGETS["role"] + AXIS_BUDGETS["format"],
        )

    def test_history_and_ball_anchors_split_generic_organizers(self) -> None:
        generic = {
            "first_invite": "build",
            "best_aftertaste": "big_thing",
            "ten_minutes": "organize",
        }
        memory = recommend({**generic, "event_meaning": "memory"})
        ball = recommend({**generic, "event_meaning": "ball"})

        self.assertEqual(memory[0].organization_id, "vernost")
        self.assertEqual(ball[0].organization_id, "mephi_ball")
        self.assertGreater(memory[0].score, memory[1].score)
        self.assertGreater(ball[0].score, ball[1].score)

    def test_media_anchor_beats_generic_event_work(self) -> None:
        media = recommend(
            {
                "creative_material": "none",
                "first_invite": "campus_story",
                "ten_minutes": "camera",
                "spring_growth": "photo_video",
                "campus_change": "awareness",
                "science_or_story": "video",
            }
        )
        sport = recommend(
            {
                "creative_material": "none",
                "first_invite": "game",
                "best_aftertaste": "victory",
                "campus_change": "movement",
                "event_meaning": "sport",
                "competition_format": "sport_event",
            }
        )

        self.assertEqual(media[0].organization_id, "oso_press")
        self.assertEqual(sport[0].organization_id, "reactor")

    def test_creativity_refusal_removes_all_later_creative_answers(self) -> None:
        answers = [
            answer("first_invite", "topic"),
            answer("creative_material", "none"),
        ]
        self.assertEqual(next_question_id(answers), "best_aftertaste")

        for question in QUESTIONS:
            visible_indexes = set(available_answer_indexes(question, answers))
            for index, candidate in enumerate(question["answers"]):
                domains = ANSWER_DOMAINS.get(
                    (question["id"], candidate["id"]), frozenset()
                )
                if "creative" in domains:
                    self.assertNotIn(index, visible_indexes)

    def test_explicit_creativity_refusal_excludes_creative_specialists(self) -> None:
        results = recommend(
            {
                "creative_material": "none",
                "first_invite": "topic",
                "best_aftertaste": "understood",
                "small_club": "books",
                "science_or_story": "research",
            }
        )
        creative_domains = {
            "music",
            "dance",
            "theatre",
            "visual_art",
            "multidisciplinary_art",
            "performing_arts",
        }
        for result in results:
            profile_domains = set(
                ORGANIZATION_PROFILES[result.organization_id].facets["domain"]
            )
            self.assertFalse(profile_domains & creative_domains)

    def test_routes_are_adaptive_bounded_and_do_not_repeat_questions(self) -> None:
        media = complete_route(
            {
                "first_invite": "campus_story",
                "creative_material": "none",
                "spring_growth": "photo_video",
                "campus_change": "awareness",
                "science_or_story": "video",
            }
        )
        squads = complete_route(
            {
                "first_invite": "summer_trip",
                "creative_material": "none",
                "spring_growth": "hands",
                "rhythm": "summer",
                "summer_offer": "construction",
                "construction_character": "sport",
            }
        )

        for route in (media, squads):
            ids = [item["question_id"] for item in route]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertGreaterEqual(len(ids), MIN_ROUTE_QUESTIONS)
            self.assertLessEqual(len(ids), MAX_ROUTE_QUESTIONS)
            self.assertIsNone(next_question_id(route))
        self.assertNotEqual(
            [item["question_id"] for item in media],
            [item["question_id"] for item in squads],
        )

    def test_every_enabled_organization_has_a_winning_specific_persona(self) -> None:
        personas = {
            "sno": {"event_meaning": "science", "science_or_story": "research", "spring_growth": "research"},
            "oso_press": {"first_invite": "campus_story", "spring_growth": "photo_video", "science_or_story": "person"},
            "curators": {"campus_change": "freshmen", "impact_target": "freshmen", "impact_method": "nearby", "new_team": "newcomers"},
            "reactor": {"campus_change": "movement", "event_meaning": "sport", "competition_format": "sport_event"},
            "dorm_council": {"campus_change": "dorm", "impact_target": "dorm", "impact_method": "negotiate"},
            "esta": {"creative_material": "dance", "stage_format": "ballroom", "rhythm": "weekly"},
            "volunteer_center": {"event_meaning": "charity", "impact_target": "good_action", "impact_method": "action", "rhythm": "flexible"},
            "quanto": {"creative_material": "voice", "music_format": "solo", "starting_point": "beginner"},
            "vto": {"creative_material": "character", "stage_format": "comedy", "event_meaning": "festival"},
            "izo": {"creative_material": "visual", "rhythm": "calm", "starting_point": "beginner"},
            "cyber_reactor": {"first_invite": "game", "competition_format": "esport_player", "rhythm": "tournaments"},
            "carpe_diem": {"creative_material": "voice", "music_format": "chamber", "rhythm": "weekly"},
            "virm": {"small_club": "history", "spring_growth": "hands", "rhythm": "calm"},
            "poetry_club": {"creative_material": "text", "small_club": "poetry", "rhythm": "calm"},
            "vernost": {"event_meaning": "memory", "impact_target": "memory", "best_aftertaste": "big_thing"},
            "altavista": {"first_invite": "summer_trip", "summer_offer": "children", "rhythm": "summer"},
            "mayak": {"first_invite": "summer_trip", "summer_offer": "construction", "construction_character": "large_object"},
            "sleipnir": {"first_invite": "summer_trip", "summer_offer": "construction", "construction_character": "trip"},
            "energy_creators": {"first_invite": "summer_trip", "summer_offer": "construction", "construction_character": "creative"},
            "triumph": {"first_invite": "summer_trip", "summer_offer": "construction", "construction_character": "sport"},
            "starostat": {"campus_change": "studies", "impact_target": "academic", "impact_method": "rules", "new_team": "represent"},
            "explosion": {"creative_material": "dance", "stage_format": "hiphop", "competition_format": "dance"},
            "ecomephi": {"impact_target": "ecology", "impact_method": "tell", "rhythm": "flexible"},
            "paradox": {"creative_material": "dance", "stage_format": "contemporary", "competition_format": "dance"},
            "male_choir": {"creative_material": "voice", "music_format": "male_academic", "starting_point": "continue"},
            "psychology_club": {"spring_growth": "people", "small_club": "psychology", "rhythm": "calm"},
            "resonance": {"first_invite": "summer_trip", "summer_offer": "restoration", "spring_growth": "hands"},
            "gamma": {"first_invite": "summer_trip", "summer_offer": "train", "rhythm": "summer"},
            "hlam": {"creative_material": "mix", "stage_format": "mixed", "starting_point": "beginner"},
            "nestor": {"small_club": "debates", "competition_format": "debates", "spring_growth": "speak"},
            "deutschverein": {"small_club": "languages", "international_format": "language", "rhythm": "calm"},
            "friendship_club": {"event_meaning": "cultures", "impact_target": "international", "international_format": "many_cultures"},
            "sound_lab": {"creative_material": "instrument", "music_format": "band", "first_invite": "build"},
            "book_club": {"first_invite": "topic", "small_club": "books", "rhythm": "calm"},
            "mephi_ball": {"creative_material": "dance", "event_meaning": "ball", "stage_format": "ball"},
            "pianists": {"creative_material": "instrument", "music_format": "piano", "rhythm": "calm"},
            "board_games": {"first_invite": "game", "small_club": "games", "competition_format": "tabletop"},
            "orchestra_mif": {"creative_material": "instrument", "music_format": "orchestra", "rhythm": "weekly"},
            "kraken": {"first_invite": "summer_trip", "summer_offer": "fishery", "spring_growth": "hands"},
        }
        enabled_ids = {
            organization["id"]
            for organization in ORGANIZATIONS
            if organization["id"] not in DISABLED_ORGANIZATION_IDS
        }
        self.assertEqual(set(personas), enabled_ids)

        for organization_id, selected in personas.items():
            with self.subTest(organization=organization_id):
                self.assertEqual(
                    recommend(selected, user_id=7)[0].organization_id,
                    organization_id,
                )

    def test_many_random_routes_finish_and_return_deterministic_top_three(self) -> None:
        generator = random.Random(20260829)
        for user_id in range(1, 1001):
            answers: list[dict[str, str]] = []
            while (question_id := next_question_id(answers)) is not None:
                question = QUESTIONS_BY_ID[question_id]
                available = available_answer_indexes(question, answers)
                self.assertGreaterEqual(len(available), 2)
                selected_index = generator.choice(available)
                answers.append(
                    answer(question_id, question["answers"][selected_index]["id"])
                )

            self.assertGreaterEqual(len(answers), MIN_ROUTE_QUESTIONS)
            self.assertLessEqual(len(answers), MAX_ROUTE_QUESTIONS)
            results = recommend_organizations(
                answers, QUESTIONS, ORGANIZATIONS, user_id=user_id
            )
            repeated = recommend_organizations(
                list(reversed(answers)), QUESTIONS, ORGANIZATIONS, user_id=user_id
            )
            self.assertEqual(results, repeated)
            self.assertEqual(len(results), 3)
            self.assertEqual(len({result.organization_id for result in results}), 3)
            self.assertTrue(all(result.reasons for result in results))
            self.assertEqual(
                [result.score for result in results],
                sorted((result.score for result in results), reverse=True),
            )
            self.assertTrue(all(0 <= result.score <= 100 for result in results))

    def test_invalid_partial_answer_sets_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            recommend_organizations([], QUESTIONS, ORGANIZATIONS, user_id=1)
        with self.assertRaises(ValueError):
            recommend_organizations(
                [answer("unknown", "answer")], QUESTIONS, ORGANIZATIONS, user_id=1
            )
        with self.assertRaises(ValueError):
            recommend_organizations(
                [
                    answer("first_invite", "topic"),
                    answer("first_invite", "game"),
                ],
                QUESTIONS,
                ORGANIZATIONS,
                user_id=1,
            )


if __name__ == "__main__":
    unittest.main()
