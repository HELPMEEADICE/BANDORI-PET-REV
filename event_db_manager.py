from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache


@dataclass
class SpecialEvent:
    event_type: str  # "birthday" or "festival"
    name: dict  # {"zh": "..."}
    month: int
    day: int
    duration_days: int = 1
    prompt_template: str = ""
    character: str = ""
    band: str = ""
    keywords: list[str] = None

    def __post_init__(self):
        if self.keywords is None:
            self.keywords = []


@lru_cache(maxsize=8)
def _load_json_file(filepath: str, mtime_ns: int, size: int) -> dict:
    del mtime_ns, size
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


class EventDbManager:
    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = os.path.join(os.path.dirname(__file__), "events")
        self.data_dir = data_dir
        self.birthdays = self._load_json("birthday_db.json")
        self.festivals = self._load_json("festival_db.json")

    def _load_json(self, filename: str) -> dict:
        filepath = os.path.join(self.data_dir, filename)
        try:
            stat = os.stat(filepath)
            return _load_json_file(filepath, stat.st_mtime_ns, stat.st_size)
        except (FileNotFoundError, OSError, json.JSONDecodeError) as e:
            print(f"Warning: Failed to load {filename}: {e}")
            return {}

    def _is_date_in_range(self, month: int, day: int, duration_days: int, today: date) -> bool:
        try:
            start_date = date(today.year, month, day)
        except ValueError:
            return False
        end_date = start_date + timedelta(days=duration_days - 1)
        return start_date <= today <= end_date

    def _birthday_event(self, band: str, char_name: str, char_data: dict) -> SpecialEvent:
        return SpecialEvent(
            event_type="birthday",
            name={"zh": f"{char_data['name_zh']}的生日"},
            month=char_data["month"],
            day=char_data["day"],
            duration_days=1,
            prompt_template="今天是{name_zh}！你可以祝福她生日快乐，或者讨论她的故事。",
            character=char_name,
            band=band
        )

    def _festival_event(self, festival_data: dict) -> SpecialEvent:
        return SpecialEvent(
            event_type="festival",
            name={"zh": festival_data["name_zh"]},
            month=festival_data["month"],
            day=festival_data["day"],
            duration_days=festival_data.get("duration_days", 1),
            prompt_template=festival_data.get("prompt_template", ""),
            keywords=festival_data.get("keywords", [])
        )

    def get_today_events(self) -> list[SpecialEvent]:
        today = date.today()
        events = []

        # 检查生日事件
        if self.birthdays and "birthdays" in self.birthdays:
            for band, characters in self.birthdays["birthdays"].items():
                for char_name, char_data in characters.items():
                    if (char_data.get("month") == today.month and
                            char_data.get("day") == today.day):
                        events.append(self._birthday_event(band, char_name, char_data))

        # 检查节日事件
        if self.festivals and "festivals" in self.festivals:
            events.extend(
                self._festival_event(festival_data)
                for festival_data in self.festivals["festivals"].values()
                if self._is_date_in_range(
                        festival_data.get("month", 0),
                        festival_data.get("day", 0),
                        festival_data.get("duration_days", 1),
                        today)
            )

        return events

    def get_upcoming_events(self, days: int = 7) -> list[SpecialEvent]:
        today = date.today()
        upcoming = []

        for i in range(1, days + 1):
            future_date = today + timedelta(days=i)
            # 检查生日
            if self.birthdays and "birthdays" in self.birthdays:
                for band, characters in self.birthdays["birthdays"].items():
                    for char_name, char_data in characters.items():
                        if (char_data.get("month") == future_date.month and
                                char_data.get("day") == future_date.day):
                            upcoming.append(self._birthday_event(band, char_name, char_data))

            # 检查节日
            if self.festivals and "festivals" in self.festivals:
                upcoming.extend(
                    self._festival_event(festival_data)
                    for festival_data in self.festivals["festivals"].values()
                    if self._is_date_in_range(
                            festival_data.get("month", 0),
                            festival_data.get("day", 0),
                            festival_data.get("duration_days", 1),
                            future_date)
                )

        return upcoming

    def get_character_band(self, character_name: str) -> str | None:
        if not self.birthdays or "birthdays" not in self.birthdays:
            return None
        for band, characters in self.birthdays["birthdays"].items():
            if character_name in characters:
                return band
        return None
