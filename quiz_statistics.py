import json
import os
import threading
from pathlib import Path
from typing import Mapping, Sequence


_WRITE_LOCK = threading.Lock()


def _empty_statistics() -> dict:
    return {"total_completed_quizzes": 0, "organizations": {}}


def load_statistics(path: Path) -> dict:
    if not path.exists():
        return _empty_statistics()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Не удалось прочитать статистику из {path}") from error

    if not isinstance(data, dict) or not isinstance(data.get("organizations"), dict):
        raise RuntimeError(f"Некорректный формат файла статистики {path}")
    return data


def record_quiz_results(
    path: Path,
    organization_ids: Sequence[str],
    organization_names: Mapping[str, str] | None = None,
) -> None:
    """Record one completed quiz, preserving each result's exact top position."""
    if not organization_ids:
        return

    with _WRITE_LOCK:
        statistics = load_statistics(path)
        statistics["total_completed_quizzes"] = int(
            statistics.get("total_completed_quizzes", 0)
        ) + 1
        organizations = statistics["organizations"]

        for position, organization_id in enumerate(organization_ids[:3], start=1):
            counters = organizations.setdefault(
                organization_id,
                {
                    "name": (
                        organization_names.get(organization_id, organization_id)
                        if organization_names
                        else organization_id
                    ),
                    "top_1": 0,
                    "top_2": 0,
                    "top_3": 0,
                },
            )
            if organization_names and organization_id in organization_names:
                counters["name"] = organization_names[organization_id]
            counter_name = f"top_{position}"
            counters[counter_name] = int(counters.get(counter_name, 0)) + 1

        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f".{path.name}.tmp")
        temporary_path.write_text(
            json.dumps(statistics, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, path)
