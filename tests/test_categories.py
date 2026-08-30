import unittest

import bot
from matching import ORGANIZATION_DIVERSITY_GROUP, recommend_organizations


EXPECTED_CATEGORIES = {
    "community": {"curators", "dorm_council", "starostat", "vernost"},
    "sport": {"reactor", "cyber_reactor", "explosion", "paradox"},
    "student_squads": {
        "altavista",
        "mayak",
        "sleipnir",
        "energy_creators",
        "triumph",
        "resonance",
        "gamma",
        "kraken",
    },
    "volunteer": {"volunteer_center", "ecomephi"},
    "culture": {
        "esta",
        "quanto",
        "vto",
        "izo",
        "carpe_diem",
        "virm",
        "poetry_club",
        "male_choir",
        "psychology_club",
        "hlam",
        "nestor",
        "deutschverein",
        "sound_lab",
        "book_club",
        "mephi_ball",
        "pianists",
        "board_games",
        "orchestra_mif",
        "pharaoh",
    },
    "career": set(),
    "media": {"oso_press"},
    "science": {"sno"},
    "kid": {"friendship_club"},
}


class CategoryTests(unittest.TestCase):
    def test_catalog_uses_the_requested_nine_categories(self) -> None:
        self.assertEqual(
            [category_id for category_id, _ in bot.CATEGORIES],
            list(EXPECTED_CATEGORIES),
        )
        actual = {
            category_id: {
                organization["id"]
                for organization in bot.ORGANIZATIONS_BY_CATEGORY[category_id]
            }
            for category_id in EXPECTED_CATEGORIES
        }
        self.assertEqual(actual, EXPECTED_CATEGORIES)

    def test_every_organization_is_assigned_exactly_once(self) -> None:
        assigned_ids = [
            organization_id
            for organization_ids in EXPECTED_CATEGORIES.values()
            for organization_id in organization_ids
        ]
        self.assertEqual(len(assigned_ids), len(set(assigned_ids)))
        self.assertEqual(set(assigned_ids), set(bot.ORGANIZATIONS_BY_ID))

    def test_empty_career_category_has_a_clear_message(self) -> None:
        self.assertIn("пока нет объединений", bot.category_text("career", 0))
        self.assertEqual(len(bot.category_menu("career", 0).inline_keyboard), 1)

    def test_old_category_buttons_have_migration_targets(self) -> None:
        expected = {
            "dance": "culture",
            "music": "culture",
            "art": "culture",
            "clubs": "culture",
            "self_government": "community",
            "civic": "community",
            "international": "kid",
        }
        self.assertEqual(bot.LEGACY_CATEGORY_ALIASES, expected)
        self.assertTrue(set(expected.values()) <= set(EXPECTED_CATEGORIES))

    def test_result_card_returns_to_the_organizations_actual_page(self) -> None:
        for category_id, organizations in bot.ORGANIZATIONS_BY_CATEGORY.items():
            for index, organization in enumerate(organizations):
                with self.subTest(category=category_id, organization=organization["id"]):
                    self.assertEqual(
                        bot.organization_category_page(organization),
                        index // bot.PAGE_SIZE,
                    )

    def test_recommendation_diversity_is_decoupled_from_catalog_categories(self) -> None:
        self.assertEqual(set(ORGANIZATION_DIVERSITY_GROUP), set(bot.ORGANIZATIONS_BY_ID))
        self.assertNotEqual(
            ORGANIZATION_DIVERSITY_GROUP["quanto"],
            ORGANIZATION_DIVERSITY_GROUP["vto"],
        )
        self.assertEqual(
            bot.ORGANIZATIONS_BY_ID["quanto"]["category"],
            bot.ORGANIZATIONS_BY_ID["vto"]["category"],
        )

    def test_broad_culture_category_does_not_reshuffle_creative_top_three(self) -> None:
        scenarios = (
            (
                42,
                {
                    "creative_material": "voice",
                    "music_format": "solo",
                    "rhythm": "weekly",
                    "starting_point": "beginner",
                },
                ["quanto", "carpe_diem", "sound_lab"],
            ),
            (
                45,
                {
                    "creative_material": "dance",
                    "stage_format": "hiphop",
                    "competition_format": "dance",
                    "rhythm": "tournaments",
                },
                ["explosion", "paradox", "esta"],
            ),
        )
        for user_id, selected, expected_ids in scenarios:
            answers = [
                {"question_id": question_id, "answer_id": answer_id}
                for question_id, answer_id in selected.items()
            ]
            results = recommend_organizations(
                answers,
                bot.QUESTIONS,
                bot.ORGANIZATIONS,
                user_id=user_id,
            )
            with self.subTest(user_id=user_id):
                self.assertEqual(
                    [result.organization_id for result in results],
                    expected_ids,
                )


if __name__ == "__main__":
    unittest.main()
