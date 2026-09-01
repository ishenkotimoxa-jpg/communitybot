import json
import tempfile
import unittest
from pathlib import Path

from quiz_statistics import load_statistics, record_quiz_results


class StatisticsTests(unittest.TestCase):
    def test_each_organization_is_counted_in_its_exact_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "statistics.json"

            names = {
                "press_service": "Пресс-служба",
                "theatre": "Театр",
                "choir": "Хор",
            }
            record_quiz_results(
                path, ["press_service", "theatre", "choir"], names
            )
            record_quiz_results(
                path, ["theatre", "press_service", "choir"], names
            )
            record_quiz_results(
                path, ["press_service", "choir", "theatre"], names
            )

            self.assertEqual(
                load_statistics(path),
                {
                    "total_completed_quizzes": 3,
                    "organizations": {
                        "press_service": {
                            "name": "Пресс-служба",
                            "top_1": 2,
                            "top_2": 1,
                            "top_3": 0,
                        },
                        "theatre": {
                            "name": "Театр",
                            "top_1": 1,
                            "top_2": 1,
                            "top_3": 1,
                        },
                        "choir": {
                            "name": "Хор",
                            "top_1": 0,
                            "top_2": 1,
                            "top_3": 2,
                        },
                    },
                },
            )

    def test_empty_results_are_not_counted_as_completed_quiz(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "statistics.json"
            record_quiz_results(path, [])
            self.assertFalse(path.exists())

    def test_statistics_file_is_valid_utf8_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "statistics.json"
            record_quiz_results(path, ["пресс-служба"])
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["organizations"],
                {
                    "пресс-служба": {
                        "name": "пресс-служба",
                        "top_1": 1,
                        "top_2": 0,
                        "top_3": 0,
                    }
                },
            )


if __name__ == "__main__":
    unittest.main()
