import os
import sys
import uuid
from typing import Callable

from process_utils import app_base_dir, debug_logging_enabled


def available() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        import AppKit  # noqa: F401
        import Foundation  # noqa: F401
        import objc  # noqa: F401
        return True
    except Exception:
        return False


if sys.platform == "darwin":
    try:
        import objc
        from AppKit import (
            NSBezierPath,
            NSColor,
            NSFont,
            NSFontAttributeName,
            NSForegroundColorAttributeName,
            NSImage,
            NSMenu,
            NSMenuItem,
            NSSquareStatusItemLength,
            NSStatusBar,
        )
        from Foundation import NSObject, NSMakeRect, NSMakeSize, NSString
    except Exception:
        objc = None
        NSObject = object
else:
    objc = None
    NSObject = object


class _StatusItemTarget(NSObject):
    def initWithCallbacks_(self, callbacks):  # noqa: N802 - Objective-C selector
        self = objc.super(_StatusItemTarget, self).init()
        if self is None:
            return None
        self._callbacks = callbacks
        return self

    def handleMenuItem_(self, sender):  # noqa: N802 - Objective-C selector
        key = str(sender.representedObject())
        callback = self._callbacks.get(key)
        if callback is not None:
            callback()


class MacOSStatusItem:
    def __init__(self, tooltip: str, entries: list[dict]):
        if not available() or objc is None:
            raise RuntimeError("macOS native status item is not available")
        self._callbacks: dict[str, Callable[[], None]] = {}
        self._target = _StatusItemTarget.alloc().initWithCallbacks_(self._callbacks)
        self._status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSSquareStatusItemLength)
        self._menu = self._build_menu(entries)
        self._status_item.setMenu_(self._menu)
        self.setToolTip(tooltip)
        button = self._status_item.button()
        if button is not None:
            button.setImage_(_status_image())
            button.setImagePosition_(1)
            button.setEnabled_(True)
        if debug_logging_enabled():
            print(
                f"Native macOS status item created: button={button is not None}",
                file=sys.stderr,
                flush=True,
            )

    def _build_menu(self, entries: list[dict]):
        menu = NSMenu.alloc().init()
        for entry in entries:
            if entry.get("separator"):
                menu.addItem_(NSMenuItem.separatorItem())
                continue
            title = str(entry.get("title", ""))
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            submenu_entries = entry.get("submenu")
            if submenu_entries:
                item.setSubmenu_(self._build_menu(submenu_entries))
            else:
                callback = entry.get("callback")
                if callback is not None:
                    key = uuid.uuid4().hex
                    self._callbacks[key] = callback
                    item.setTarget_(self._target)
                    item.setAction_("handleMenuItem:")
                    item.setRepresentedObject_(key)
            menu.addItem_(item)
        return menu

    def setToolTip(self, tooltip: str):
        button = self._status_item.button()
        if button is not None:
            button.setToolTip_(str(tooltip or ""))

    def setIcon(self, _icon):
        button = self._status_item.button()
        if button is not None:
            button.setImage_(_status_image())

    def icon(self):
        return None

    def setContextMenu(self, _menu):
        pass

    def activated(self):
        return None

    def setVisible(self, visible: bool):
        if visible:
            return
        self.hide()

    def show(self):
        pass

    def showMessage(self, *_args):
        pass

    def hide(self):
        if self._status_item is not None:
            NSStatusBar.systemStatusBar().removeStatusItem_(self._status_item)
            self._status_item = None


def _status_image():
    image = _load_bundle_icon()
    if image is not None:
        image.setSize_(NSMakeSize(18, 18))
        image.setTemplate_(False)
        return image
    return _fallback_image()


def _load_bundle_icon():
    base_dir = str(app_base_dir())
    candidates = [
        os.path.join(base_dir, "..", "Resources", "icon.icns"),
        os.path.join(base_dir, "logo.png"),
        os.path.join(base_dir, "logo.icns"),
        os.path.join(base_dir, "logo.ico"),
    ]
    for path in candidates:
        path = os.path.abspath(path)
        if not os.path.exists(path):
            continue
        image = NSImage.alloc().initWithContentsOfFile_(path)
        if image is not None and image.isValid():
            return image
    return None


def _fallback_image():
    image = NSImage.alloc().initWithSize_(NSMakeSize(18, 18))
    image.lockFocus()
    NSColor.colorWithCalibratedRed_green_blue_alpha_(0.91, 0.23, 0.49, 1.0).set()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(1, 2, 16, 14),
        4,
        4,
    ).fill()
    attrs = {
        NSFontAttributeName: NSFont.boldSystemFontOfSize_(10),
        NSForegroundColorAttributeName: NSColor.whiteColor(),
    }
    NSString.stringWithString_("B").drawInRect_withAttributes_(NSMakeRect(5, 3, 9, 12), attrs)
    image.unlockFocus()
    image.setTemplate_(False)
    return image
