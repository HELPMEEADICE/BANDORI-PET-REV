# Settings Navigation Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorder the settings sidebar to the fixed sequence approved in the design without changing navigation styling or behavior.

**Architecture:** Keep the existing `NavButton` construction and lazy-page routing intact. Add a small offscreen Qt regression test that calls the real `_build_sidebar` method through a lightweight harness, then physically reorder the existing button construction blocks so both layout order and `self._nav_buttons` insertion order match the approved sequence.

**Tech Stack:** Python 3.11, PySide6, PySide6-Fluent-Widgets, built-in `unittest`

---

## File Structure

- Create `tests/__init__.py` so the test module can be run with `python -m unittest`.
- Create `tests/test_settings_navigation_order.py` to verify the real sidebar layout and the independently fixed “关于” button.
- Modify `settings_window/settings_window.py` only inside `_build_sidebar` to reorder existing navigation button blocks.

### Task 1: Reorder Settings Navigation

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_settings_navigation_order.py`
- Modify: `settings_window/settings_window.py:1403-1551`

- [ ] **Step 1: Create the test package**

Create an empty `tests/__init__.py`.

- [ ] **Step 2: Write the failing navigation-order test**

Create `tests/test_settings_navigation_order.py`:

```python
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from settings_window.settings_window import SettingsWindow
from settings_window.widgets import NavButton


EXPECTED_NAVIGATION_ORDER = [
    "characters",
    "behavior",
    "memory",
    "relationship_guide",
    "reminders",
    "chat_history",
    "memory_album",
    "statistics",
    "llm",
    "compact_window",
    "quality",
    "screen_awareness",
    "tts",
    "asr",
    "pov",
    "chat_integration",
    "mcp_computer",
    "data_management",
]


class SidebarHarness:
    def __init__(self):
        self._nav_buttons = {}
        self._theme_widgets = []

    def _on_nav_selected(self, _nav_key):
        pass

    def _position_nav_indicator(self, _nav_key):
        pass

    def _update_sidebar_style(self):
        pass

    def _connect_theme_changed(self, _callback):
        pass


class SettingsNavigationOrderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_sidebar_uses_approved_fixed_order(self):
        harness = SidebarHarness()
        sidebar = SettingsWindow._build_sidebar(harness)
        nav_content = sidebar.findChild(QWidget, "sidebarNavContent")

        self.assertIsNotNone(nav_content)
        layout = nav_content.layout()
        actual_order = []
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if isinstance(widget, NavButton):
                actual_order.append(widget._nav_key)

        self.assertEqual(EXPECTED_NAVIGATION_ORDER, actual_order)
        self.assertEqual(EXPECTED_NAVIGATION_ORDER, list(harness._nav_buttons)[:-1])
        self.assertEqual("about", list(harness._nav_buttons)[-1])
        self.assertIs(harness._nav_buttons["about"].parent(), sidebar)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test and verify the current order fails**

Run:

```powershell
python -m unittest tests.test_settings_navigation_order -v
```

Expected: `FAIL` because the current sidebar order places reminders and screen awareness before memory and relationship entries.

- [ ] **Step 4: Reorder the existing button blocks**

In `SettingsWindow._build_sidebar`, move the complete existing blocks without changing each block’s key, icon, text, accent, signal connection, dictionary assignment, or `nav_layout.addWidget` call. The blocks must appear in this exact order:

```python
btn_chars
btn_behavior
btn_memory
btn_relationship_guide
btn_reminders
btn_chat_history
btn_memory_album
btn_statistics
btn_llm
btn_compact
btn_quality
btn_screen_awareness
btn_tts
btn_asr
btn_pov
btn_chat_integration
btn_mcp_computer
btn_data_management
```

Keep `nav_layout.addStretch()` immediately after `btn_data_management`. Leave the independent `btn_about` block after `layout.addWidget(nav_scroll, 1)` so “关于” remains fixed at the bottom.

- [ ] **Step 5: Run the regression test**

Run:

```powershell
python -m unittest tests.test_settings_navigation_order -v
```

Expected: `OK`, with one passing test.

- [ ] **Step 6: Run syntax and diff checks**

Run:

```powershell
python -m py_compile settings_window/settings_window.py tests/test_settings_navigation_order.py
git diff --check
```

Expected: both commands exit successfully with no output.

- [ ] **Step 7: Perform an offscreen UI smoke check**

Run:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m unittest tests.test_settings_navigation_order -v
Remove-Item Env:QT_QPA_PLATFORM
```

Expected: `OK`; this confirms the real Qt sidebar can be constructed and inspected without a display.

- [ ] **Step 8: Review the final diff**

Run:

```powershell
git diff -- settings_window/settings_window.py tests/__init__.py tests/test_settings_navigation_order.py
```

Expected: only the navigation blocks have moved, plus the focused regression test files. No icon, color, translation key, route key, or page logic changes are present.

- [ ] **Step 9: Commit the implementation**

```powershell
git add settings_window/settings_window.py tests/__init__.py tests/test_settings_navigation_order.py
git commit -m "refactor: reorder settings navigation"
```
