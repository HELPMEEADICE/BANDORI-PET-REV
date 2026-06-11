from datetime import datetime, timedelta
import unittest

from proactive_care_policy import (
    CARE_DESKTOP_STATES,
    evaluate_proactive_care,
    mark_proactive_care_result,
    normalize_proactive_care_policy,
)


class ProactiveCarePolicyTest(unittest.TestCase):
    def test_default_policy_has_all_state_rules(self):
        policy = normalize_proactive_care_policy({})

        self.assertTrue(policy["enabled"])
        self.assertEqual(30, policy["global_cooldown_minutes"])
        self.assertEqual(set(CARE_DESKTOP_STATES), set(policy["state_rules"]))

    def test_quiet_hours_wrap_midnight(self):
        policy = normalize_proactive_care_policy({
            "quiet_hours_enabled": True,
            "quiet_start": "23:30",
            "quiet_end": "08:00",
        })

        decision = evaluate_proactive_care(
            policy,
            kind="proactive_companion",
            proactive_kind="water",
            desktop_state={"state": "web"},
            now=datetime(2026, 6, 9, 0, 30, 0),
        )

        self.assertFalse(decision["allow"])
        self.assertEqual("quiet_hours", decision["reason"])

    def test_gaming_media_and_chatting_allow_lifestyle_by_default(self):
        for state in ("gaming", "media", "chatting"):
            with self.subTest(state=state):
                decision = evaluate_proactive_care(
                    {},
                    kind="proactive_companion",
                    proactive_kind="water",
                    desktop_state={"state": state},
                    now=datetime(2026, 6, 9, 12, 0, 0),
                )
                self.assertTrue(decision["allow"])

    def test_idle_allows_after_cooldown(self):
        now = datetime(2026, 6, 9, 12, 0, 0)
        policy = mark_proactive_care_result({}, kind="proactive_companion", now=now - timedelta(hours=1))

        decision = evaluate_proactive_care(
            policy,
            kind="proactive_companion",
            proactive_kind="water",
            desktop_state={"state": "idle"},
            now=now,
        )

        self.assertTrue(decision["allow"])

    def test_coding_uses_cooldown_multiplier(self):
        now = datetime(2026, 6, 9, 12, 0, 0)
        policy = mark_proactive_care_result({}, kind="proactive_companion", now=now - timedelta(minutes=40))

        decision = evaluate_proactive_care(
            policy,
            kind="proactive_companion",
            proactive_kind="water",
            desktop_state={"state": "coding"},
            now=now,
        )

        self.assertFalse(decision["allow"])
        self.assertEqual("cooldown", decision["reason"])

    def test_screen_awareness_can_ignore_policy(self):
        policy = normalize_proactive_care_policy({
            "screen_awareness_respect_policy": False,
        })

        decision = evaluate_proactive_care(
            policy,
            kind="screen_awareness",
            desktop_state={"state": "gaming"},
            now=datetime(2026, 6, 9, 12, 0, 0),
        )

        self.assertTrue(decision["allow"])


if __name__ == "__main__":
    unittest.main()
