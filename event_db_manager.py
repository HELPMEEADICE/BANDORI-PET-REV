import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional


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
    keywords: List[str] = None

    def __post_init__(self):
        if self.keywords is None:
            self.keywords = []


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
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Warning: Failed to load {filename}: {e}")
            return {}

    def _is_date_in_range(self, month: int, day: int, duration_days: int, today: date) -> bool:
        start_date = date(today.year, month, day)
        end_date = start_date + timedelta(days=duration_days - 1)
        return start_date <= today <= end_date

    def get_today_events(self) -> List[SpecialEvent]:
        today = date.today()
        events = []

        # 检查生日事件
        if self.birthdays and "birthdays" in self.birthdays:
            for band, characters in self.birthdays["birthdays"].items():
                for char_name, char_data in characters.items():
                    if (char_data.get("month") == today.month and
                            char_data.get("day") == today.day):
                        events.append(SpecialEvent(
                            event_type="birthday",
                            name={"zh": f"{char_data['name_zh']}的生日"},
                            month=char_data["month"],
                            day=char_data["day"],
                            duration_days=1,
                            prompt_template="今天是{name_zh}！你可以祝福她生日快乐，或者讨论她的故事。",
                            character=char_name,
                            band=band
                        ))

        # 检查节日事件
        if self.festivals and "festivals" in self.festivals:
            for festival_id, festival_data in self.festivals["festivals"].items():
                if self._is_date_in_range(
                        festival_data.get("month", 0),
                        festival_data.get("day", 0),
                        festival_data.get("duration_days", 1),
                        today):
                    events.append(SpecialEvent(
                        event_type="festival",
                        name={"zh": festival_data["name_zh"]},
                        month=festival_data["month"],
                        day=festival_data["day"],
                        duration_days=festival_data.get("duration_days", 1),
                        prompt_template=festival_data.get("prompt_template", ""),
                        keywords=festival_data.get("keywords", [])
                    ))

        return events

    def get_upcoming_events(self, days: int = 7) -> List[SpecialEvent]:
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
                            upcoming.append(SpecialEvent(
                                event_type="birthday",
                                name={"zh": f"{char_data['name_zh']}的生日"},
                                month=char_data["month"],
                                day=char_data["day"],
                                duration_days=1,
                                prompt_template="今天是{name_zh}！你可以祝福她生日快乐，或者讨论她的故事。",
                                character=char_name,
                                band=band
                            ))

            # 检查节日
            if self.festivals and "festivals" in self.festivals:
                for festival_id, festival_data in self.festivals["festivals"].items():
                    if self._is_date_in_range(
                            festival_data.get("month", 0),
                            festival_data.get("day", 0),
                            festival_data.get("duration_days", 1),
                            future_date):
                        upcoming.append(SpecialEvent(
                            event_type="festival",
                            name={"zh": festival_data["name_zh"]},
                            month=festival_data["month"],
                            day=festival_data["day"],
                            duration_days=festival_data.get("duration_days", 1),
                            prompt_template=festival_data.get("prompt_template", ""),
                            keywords=festival_data.get("keywords", [])
                        ))

        return upcoming

    def get_character_band(self, character_name: str) -> Optional[str]:
        if not self.birthdays or "birthdays" not in self.birthdays:
            return None
        for band, characters in self.birthdays["birthdays"].items():
            if character_name in characters:
                return band
        return None
