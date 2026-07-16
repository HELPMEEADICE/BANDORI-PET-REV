#include "native_computer_input.h"

#include <QByteArray>
#include <QCursor>
#include <QPair>
#include <QRegularExpression>
#include <QStringList>
#include <QtGlobal>

#include <algorithm>
#include <cstdlib>
#include <limits>
#include <vector>

#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#elif defined(Q_OS_MACOS)
#include <ApplicationServices/ApplicationServices.h>
#elif defined(Q_OS_UNIX)
#include <X11/XKBlib.h>
#include <X11/Xlib.h>
#include <X11/extensions/XTest.h>
#include <X11/keysym.h>
#endif

namespace bandori {

namespace {

void setInputError(QString* error, const QString& message) {
    if (error != nullptr) {
        *error = message;
    }
}

#ifdef Q_OS_WIN
WORD windowsVirtualKey(const QString& key) {
    const QString normalized = key.trimmed().toLower();
    if (normalized.size() == 1) {
        const QChar character = normalized.front().toUpper();
        if (character.isLetterOrNumber()) {
            return static_cast<WORD>(character.unicode());
        }
    }
    if (normalized == QStringLiteral("enter") || normalized == QStringLiteral("return")) {
        return VK_RETURN;
    }
    if (normalized == QStringLiteral("esc") || normalized == QStringLiteral("escape")) {
        return VK_ESCAPE;
    }
    if (normalized == QStringLiteral("tab")) return VK_TAB;
    if (normalized == QStringLiteral("space")) return VK_SPACE;
    if (normalized == QStringLiteral("backspace")) return VK_BACK;
    if (normalized == QStringLiteral("delete") || normalized == QStringLiteral("del")) {
        return VK_DELETE;
    }
    if (normalized == QStringLiteral("insert")) return VK_INSERT;
    if (normalized == QStringLiteral("home")) return VK_HOME;
    if (normalized == QStringLiteral("end")) return VK_END;
    if (normalized == QStringLiteral("pageup") || normalized == QStringLiteral("pgup")) {
        return VK_PRIOR;
    }
    if (normalized == QStringLiteral("pagedown") || normalized == QStringLiteral("pgdn")) {
        return VK_NEXT;
    }
    if (normalized == QStringLiteral("left")) return VK_LEFT;
    if (normalized == QStringLiteral("right")) return VK_RIGHT;
    if (normalized == QStringLiteral("up")) return VK_UP;
    if (normalized == QStringLiteral("down")) return VK_DOWN;
    if (normalized.size() >= 2 && normalized.front() == QLatin1Char('f')) {
        bool ok = false;
        const int function = normalized.mid(1).toInt(&ok);
        if (ok && function >= 1 && function <= 24) {
            return static_cast<WORD>(VK_F1 + function - 1);
        }
    }
    return 0;
}

INPUT windowsKeyInput(WORD key, bool release, bool unicode = false) {
    INPUT input {};
    input.type = INPUT_KEYBOARD;
    if (unicode) {
        input.ki.wScan = key;
        input.ki.dwFlags = KEYEVENTF_UNICODE | (release ? KEYEVENTF_KEYUP : 0);
    } else {
        input.ki.wVk = key;
        input.ki.dwFlags = release ? KEYEVENTF_KEYUP : 0;
    }
    return input;
}
#elif defined(Q_OS_MACOS)
bool macosAccessibilityAllowed(QString* error) {
    if (AXIsProcessTrusted()) {
        return true;
    }
    setInputError(
        error,
        QStringLiteral(
            "macOS Accessibility permission is required for global mouse and keyboard control"));
    return false;
}

CGKeyCode macosVirtualKey(const QString& key) {
    const QString normalized = key.trimmed().toLower();
    if (normalized.size() == 1) {
        switch (normalized.front().unicode()) {
        case 'a': return 0x00;
        case 's': return 0x01;
        case 'd': return 0x02;
        case 'f': return 0x03;
        case 'h': return 0x04;
        case 'g': return 0x05;
        case 'z': return 0x06;
        case 'x': return 0x07;
        case 'c': return 0x08;
        case 'v': return 0x09;
        case 'b': return 0x0b;
        case 'q': return 0x0c;
        case 'w': return 0x0d;
        case 'e': return 0x0e;
        case 'r': return 0x0f;
        case 'y': return 0x10;
        case 't': return 0x11;
        case '1': return 0x12;
        case '2': return 0x13;
        case '3': return 0x14;
        case '4': return 0x15;
        case '6': return 0x16;
        case '5': return 0x17;
        case '=': return 0x18;
        case '9': return 0x19;
        case '7': return 0x1a;
        case '-': return 0x1b;
        case '8': return 0x1c;
        case '0': return 0x1d;
        case ']': return 0x1e;
        case 'o': return 0x1f;
        case 'u': return 0x20;
        case '[': return 0x21;
        case 'i': return 0x22;
        case 'p': return 0x23;
        case 'l': return 0x25;
        case 'j': return 0x26;
        case '\'': return 0x27;
        case 'k': return 0x28;
        case ';': return 0x29;
        case '\\': return 0x2a;
        case ',': return 0x2b;
        case '/': return 0x2c;
        case 'n': return 0x2d;
        case 'm': return 0x2e;
        case '.': return 0x2f;
        case '`': return 0x32;
        default: break;
        }
    }
    if (normalized == QStringLiteral("enter") || normalized == QStringLiteral("return")) {
        return 0x24;
    }
    if (normalized == QStringLiteral("tab")) return 0x30;
    if (normalized == QStringLiteral("space")) return 0x31;
    if (normalized == QStringLiteral("backspace")) return 0x33;
    if (normalized == QStringLiteral("esc") || normalized == QStringLiteral("escape")) {
        return 0x35;
    }
    if (normalized == QStringLiteral("left")) return 0x7b;
    if (normalized == QStringLiteral("right")) return 0x7c;
    if (normalized == QStringLiteral("down")) return 0x7d;
    if (normalized == QStringLiteral("up")) return 0x7e;
    if (normalized == QStringLiteral("delete") || normalized == QStringLiteral("del")) {
        return 0x75;
    }
    if (normalized == QStringLiteral("home")) return 0x73;
    if (normalized == QStringLiteral("end")) return 0x77;
    if (normalized == QStringLiteral("pageup") || normalized == QStringLiteral("pgup")) {
        return 0x74;
    }
    if (normalized == QStringLiteral("pagedown") || normalized == QStringLiteral("pgdn")) {
        return 0x79;
    }
    if (normalized.size() >= 2 && normalized.front() == QLatin1Char('f')) {
        bool ok = false;
        const int function = normalized.mid(1).toInt(&ok);
        static constexpr CGKeyCode functionKeys[] = {
            0x7a, 0x78, 0x63, 0x76, 0x60, 0x61, 0x62, 0x64, 0x65, 0x6d, 0x67, 0x6f,
        };
        if (ok && function >= 1 && function <= 12) {
            return functionKeys[function - 1];
        }
    }
    return std::numeric_limits<CGKeyCode>::max();
}

void postMacosKey(CGKeyCode key, bool down) {
    CGEventRef event = CGEventCreateKeyboardEvent(nullptr, key, down);
    if (event != nullptr) {
        CGEventPost(kCGHIDEventTap, event);
        CFRelease(event);
    }
}
#elif defined(Q_OS_UNIX)
class X11InputContext {
public:
    explicit X11InputContext(QString* error) {
        if (qEnvironmentVariable("XDG_SESSION_TYPE").compare(
                QStringLiteral("wayland"),
                Qt::CaseInsensitive)
            == 0) {
            setInputError(
                error,
                QStringLiteral(
                    "Wayland does not permit portable global input injection; use an X11 session"));
            return;
        }
        display_ = XOpenDisplay(nullptr);
        if (display_ == nullptr) {
            setInputError(error, QStringLiteral("Could not open the X11 display"));
            return;
        }
        int eventBase = 0;
        int errorBase = 0;
        int major = 0;
        int minor = 0;
        if (!XTestQueryExtension(display_, &eventBase, &errorBase, &major, &minor)) {
            setInputError(error, QStringLiteral("The X11 XTest extension is unavailable"));
            XCloseDisplay(display_);
            display_ = nullptr;
        }
    }

    ~X11InputContext() {
        if (display_ != nullptr) {
            XFlush(display_);
            XCloseDisplay(display_);
        }
    }

    Display* display() const { return display_; }
    explicit operator bool() const { return display_ != nullptr; }

private:
    Display* display_ = nullptr;
};

KeySym x11NamedKey(const QString& key) {
    const QString normalized = key.trimmed().toLower();
    if (normalized.size() == 1) {
        const char32_t value = normalized.front().unicode();
        return value <= 0xff ? static_cast<KeySym>(value)
                             : static_cast<KeySym>(0x01000000U | value);
    }
    if (normalized == QStringLiteral("enter") || normalized == QStringLiteral("return")) {
        return XK_Return;
    }
    if (normalized == QStringLiteral("esc") || normalized == QStringLiteral("escape")) {
        return XK_Escape;
    }
    if (normalized == QStringLiteral("tab")) return XK_Tab;
    if (normalized == QStringLiteral("space")) return XK_space;
    if (normalized == QStringLiteral("backspace")) return XK_BackSpace;
    if (normalized == QStringLiteral("delete") || normalized == QStringLiteral("del")) {
        return XK_Delete;
    }
    if (normalized == QStringLiteral("insert")) return XK_Insert;
    if (normalized == QStringLiteral("home")) return XK_Home;
    if (normalized == QStringLiteral("end")) return XK_End;
    if (normalized == QStringLiteral("pageup") || normalized == QStringLiteral("pgup")) {
        return XK_Page_Up;
    }
    if (normalized == QStringLiteral("pagedown") || normalized == QStringLiteral("pgdn")) {
        return XK_Page_Down;
    }
    if (normalized == QStringLiteral("left")) return XK_Left;
    if (normalized == QStringLiteral("right")) return XK_Right;
    if (normalized == QStringLiteral("up")) return XK_Up;
    if (normalized == QStringLiteral("down")) return XK_Down;
    if (normalized.size() >= 2 && normalized.front() == QLatin1Char('f')) {
        bool ok = false;
        const int function = normalized.mid(1).toInt(&ok);
        if (ok && function >= 1 && function <= 24) {
            return static_cast<KeySym>(XK_F1 + function - 1);
        }
    }
    return NoSymbol;
}

bool x11TapKeysym(Display* display, KeySym keysym, QString* error) {
    const KeyCode keycode = XKeysymToKeycode(display, keysym);
    if (keycode == 0) {
        setInputError(error, QStringLiteral("The active X11 keyboard layout cannot type this key"));
        return false;
    }
    const KeySym base = XkbKeycodeToKeysym(display, keycode, 0, 0);
    const KeySym shifted = XkbKeycodeToKeysym(display, keycode, 0, 1);
    const bool needsShift = shifted == keysym && base != keysym;
    if (base != keysym && shifted != keysym) {
        setInputError(error, QStringLiteral("The active X11 keyboard layout cannot type this symbol"));
        return false;
    }
    const KeyCode shift = XKeysymToKeycode(display, XK_Shift_L);
    if (needsShift && shift != 0) {
        XTestFakeKeyEvent(display, shift, True, CurrentTime);
    }
    XTestFakeKeyEvent(display, keycode, True, CurrentTime);
    XTestFakeKeyEvent(display, keycode, False, CurrentTime);
    if (needsShift && shift != 0) {
        XTestFakeKeyEvent(display, shift, False, CurrentTime);
    }
    return true;
}
#endif

}  // namespace

QString nativeComputerInputBackend() {
#ifdef Q_OS_WIN
    return QStringLiteral("windows_send_input");
#elif defined(Q_OS_MACOS)
    return QStringLiteral("macos_quartz");
#elif defined(Q_OS_UNIX)
    if (qEnvironmentVariable("XDG_SESSION_TYPE").compare(
            QStringLiteral("wayland"),
            Qt::CaseInsensitive)
        == 0) {
        return QStringLiteral("linux_wayland_unsupported");
    }
    return QStringLiteral("linux_x11_xtest");
#else
    return QStringLiteral("unsupported");
#endif
}

bool nativeComputerMouseAction(
    const QString& action,
    const QPoint& position,
    const QString& button,
    int delta,
    QString* error) {
#ifdef Q_OS_WIN
    QCursor::setPos(position);
    if (action == QStringLiteral("move")) {
        return true;
    }
    if (action == QStringLiteral("scroll")) {
        const int boundedDelta = std::clamp(delta, -100, 100);
        mouse_event(MOUSEEVENTF_WHEEL, 0, 0, boundedDelta * WHEEL_DELTA, 0);
        return true;
    }
    const QPair<DWORD, DWORD> flags =
        button == QStringLiteral("right")
        ? qMakePair<DWORD, DWORD>(MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)
        : button == QStringLiteral("middle")
        ? qMakePair<DWORD, DWORD>(MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP)
        : qMakePair<DWORD, DWORD>(MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP);
    const int clicks = action == QStringLiteral("double_click") ? 2 : 1;
    for (int index = 0; index < clicks; ++index) {
        mouse_event(flags.first, 0, 0, 0, 0);
        mouse_event(flags.second, 0, 0, 0, 0);
    }
    return true;
#elif defined(Q_OS_MACOS)
    if (!macosAccessibilityAllowed(error)) {
        return false;
    }
    const CGPoint point = CGPointMake(position.x(), position.y());
    if (action == QStringLiteral("move")) {
        CGEventRef event =
            CGEventCreateMouseEvent(nullptr, kCGEventMouseMoved, point, kCGMouseButtonLeft);
        if (event == nullptr) {
            setInputError(error, QStringLiteral("Quartz could not create a pointer move event"));
            return false;
        }
        CGEventPost(kCGHIDEventTap, event);
        CFRelease(event);
        return true;
    }
    if (action == QStringLiteral("scroll")) {
        CGEventRef event = CGEventCreateScrollWheelEvent(
            nullptr,
            kCGScrollEventUnitLine,
            1,
            std::clamp(delta, -100, 100));
        if (event == nullptr) {
            setInputError(error, QStringLiteral("Quartz could not create a scroll event"));
            return false;
        }
        CGEventPost(kCGHIDEventTap, event);
        CFRelease(event);
        return true;
    }
    const CGMouseButton mouseButton = button == QStringLiteral("right")
        ? kCGMouseButtonRight
        : button == QStringLiteral("middle") ? kCGMouseButtonCenter : kCGMouseButtonLeft;
    const CGEventType down = mouseButton == kCGMouseButtonRight
        ? kCGEventRightMouseDown
        : mouseButton == kCGMouseButtonCenter ? kCGEventOtherMouseDown : kCGEventLeftMouseDown;
    const CGEventType up = mouseButton == kCGMouseButtonRight
        ? kCGEventRightMouseUp
        : mouseButton == kCGMouseButtonCenter ? kCGEventOtherMouseUp : kCGEventLeftMouseUp;
    const int clicks = action == QStringLiteral("double_click") ? 2 : 1;
    for (int index = 0; index < clicks; ++index) {
        CGEventRef press = CGEventCreateMouseEvent(nullptr, down, point, mouseButton);
        CGEventRef release = CGEventCreateMouseEvent(nullptr, up, point, mouseButton);
        if (press == nullptr || release == nullptr) {
            if (press != nullptr) CFRelease(press);
            if (release != nullptr) CFRelease(release);
            setInputError(error, QStringLiteral("Quartz could not create a mouse event"));
            return false;
        }
        CGEventSetIntegerValueField(press, kCGMouseEventClickState, index + 1);
        CGEventSetIntegerValueField(release, kCGMouseEventClickState, index + 1);
        CGEventPost(kCGHIDEventTap, press);
        CGEventPost(kCGHIDEventTap, release);
        CFRelease(press);
        CFRelease(release);
    }
    return true;
#elif defined(Q_OS_UNIX)
    X11InputContext context(error);
    if (!context) {
        return false;
    }
    XTestFakeMotionEvent(context.display(), -1, position.x(), position.y(), CurrentTime);
    if (action == QStringLiteral("move")) {
        return true;
    }
    if (action == QStringLiteral("scroll")) {
        const int bounded = std::clamp(delta, -20, 20);
        if (bounded == 0) {
            return true;
        }
        const unsigned int wheelButton = bounded >= 0 ? 4U : 5U;
        for (int index = 0; index < std::abs(bounded); ++index) {
            XTestFakeButtonEvent(context.display(), wheelButton, True, CurrentTime);
            XTestFakeButtonEvent(context.display(), wheelButton, False, CurrentTime);
        }
        return true;
    }
    const unsigned int mouseButton = button == QStringLiteral("right")
        ? 3U
        : button == QStringLiteral("middle") ? 2U : 1U;
    const int clicks = action == QStringLiteral("double_click") ? 2 : 1;
    for (int index = 0; index < clicks; ++index) {
        XTestFakeButtonEvent(context.display(), mouseButton, True, CurrentTime);
        XTestFakeButtonEvent(context.display(), mouseButton, False, CurrentTime);
    }
    return true;
#else
    Q_UNUSED(position);
    Q_UNUSED(button);
    Q_UNUSED(delta);
    setInputError(error, QStringLiteral("Global mouse injection is unavailable on this platform"));
    return false;
#endif
}

bool nativeComputerTypeText(const QString& text, QString* error) {
    const QString bounded = text.left(2'000);
#ifdef Q_OS_WIN
    std::vector<INPUT> inputs;
    inputs.reserve(static_cast<size_t>(bounded.size()) * 2);
    for (const QChar character : bounded) {
        inputs.push_back(windowsKeyInput(character.unicode(), false, true));
        inputs.push_back(windowsKeyInput(character.unicode(), true, true));
    }
    if (inputs.empty()) {
        return true;
    }
    const UINT sent = SendInput(
        static_cast<UINT>(inputs.size()),
        inputs.data(),
        sizeof(INPUT));
    if (sent == inputs.size()) {
        return true;
    }
    setInputError(error, QStringLiteral("Windows SendInput could not type the complete text"));
    return false;
#elif defined(Q_OS_MACOS)
    if (!macosAccessibilityAllowed(error)) {
        return false;
    }
    for (qsizetype offset = 0; offset < bounded.size(); offset += 20) {
        const QString chunk = bounded.mid(offset, 20);
        CGEventRef press = CGEventCreateKeyboardEvent(nullptr, 0, true);
        CGEventRef release = CGEventCreateKeyboardEvent(nullptr, 0, false);
        if (press == nullptr || release == nullptr) {
            if (press != nullptr) CFRelease(press);
            if (release != nullptr) CFRelease(release);
            setInputError(error, QStringLiteral("Quartz could not create a Unicode key event"));
            return false;
        }
        CGEventKeyboardSetUnicodeString(
            press,
            static_cast<UniCharCount>(chunk.size()),
            reinterpret_cast<const UniChar*>(chunk.utf16()));
        CGEventKeyboardSetUnicodeString(
            release,
            static_cast<UniCharCount>(chunk.size()),
            reinterpret_cast<const UniChar*>(chunk.utf16()));
        CGEventPost(kCGHIDEventTap, press);
        CGEventPost(kCGHIDEventTap, release);
        CFRelease(press);
        CFRelease(release);
    }
    return true;
#elif defined(Q_OS_UNIX)
    X11InputContext context(error);
    if (!context) {
        return false;
    }
    for (const char32_t codepoint : bounded.toUcs4()) {
        const KeySym keysym = codepoint <= 0xff
            ? static_cast<KeySym>(codepoint)
            : static_cast<KeySym>(0x01000000U | codepoint);
        if (!x11TapKeysym(context.display(), keysym, error)) {
            return false;
        }
    }
    return true;
#else
    Q_UNUSED(bounded);
    setInputError(error, QStringLiteral("Global keyboard injection is unavailable on this platform"));
    return false;
#endif
}

bool nativeComputerPressKeys(const QString& keys, QString* error) {
    const QStringList parts = keys.toLower().split(
        QRegularExpression(QStringLiteral("\\s*\\+\\s*|\\s+")),
        Qt::SkipEmptyParts);
#ifdef Q_OS_WIN
    std::vector<WORD> modifiers;
    WORD mainKey = 0;
    for (const QString& part : parts) {
        WORD modifier = 0;
        if (part == QStringLiteral("ctrl") || part == QStringLiteral("control")) {
            modifier = VK_CONTROL;
        } else if (part == QStringLiteral("shift")) {
            modifier = VK_SHIFT;
        } else if (part == QStringLiteral("alt")) {
            modifier = VK_MENU;
        } else if (part == QStringLiteral("win") || part == QStringLiteral("meta")) {
            modifier = VK_LWIN;
        }
        if (modifier != 0) {
            modifiers.push_back(modifier);
            continue;
        }
        if (mainKey != 0) {
            setInputError(error, QStringLiteral("A shortcut may contain only one non-modifier key"));
            return false;
        }
        mainKey = windowsVirtualKey(part);
    }
    if (mainKey == 0) {
        setInputError(error, QStringLiteral("The requested key or shortcut is unsupported"));
        return false;
    }
    std::vector<INPUT> inputs;
    for (const WORD modifier : modifiers) {
        inputs.push_back(windowsKeyInput(modifier, false));
    }
    inputs.push_back(windowsKeyInput(mainKey, false));
    inputs.push_back(windowsKeyInput(mainKey, true));
    for (auto iterator = modifiers.rbegin(); iterator != modifiers.rend(); ++iterator) {
        inputs.push_back(windowsKeyInput(*iterator, true));
    }
    const UINT sent = SendInput(
        static_cast<UINT>(inputs.size()),
        inputs.data(),
        sizeof(INPUT));
    if (sent == inputs.size()) {
        return true;
    }
    setInputError(error, QStringLiteral("Windows SendInput could not press the complete shortcut"));
    return false;
#elif defined(Q_OS_MACOS)
    if (!macosAccessibilityAllowed(error)) {
        return false;
    }
    std::vector<CGKeyCode> modifiers;
    CGKeyCode mainKey = std::numeric_limits<CGKeyCode>::max();
    for (const QString& part : parts) {
        CGKeyCode modifier = std::numeric_limits<CGKeyCode>::max();
        if (part == QStringLiteral("ctrl") || part == QStringLiteral("control")) {
            modifier = 0x3b;
        } else if (part == QStringLiteral("shift")) {
            modifier = 0x38;
        } else if (part == QStringLiteral("alt") || part == QStringLiteral("option")) {
            modifier = 0x3a;
        } else if (part == QStringLiteral("win") || part == QStringLiteral("meta")
                   || part == QStringLiteral("cmd") || part == QStringLiteral("command")) {
            modifier = 0x37;
        }
        if (modifier != std::numeric_limits<CGKeyCode>::max()) {
            modifiers.push_back(modifier);
            continue;
        }
        if (mainKey != std::numeric_limits<CGKeyCode>::max()) {
            setInputError(error, QStringLiteral("A shortcut may contain only one non-modifier key"));
            return false;
        }
        mainKey = macosVirtualKey(part);
    }
    if (mainKey == std::numeric_limits<CGKeyCode>::max()) {
        setInputError(error, QStringLiteral("The requested key or shortcut is unsupported"));
        return false;
    }
    for (const CGKeyCode modifier : modifiers) postMacosKey(modifier, true);
    postMacosKey(mainKey, true);
    postMacosKey(mainKey, false);
    for (auto iterator = modifiers.rbegin(); iterator != modifiers.rend(); ++iterator) {
        postMacosKey(*iterator, false);
    }
    return true;
#elif defined(Q_OS_UNIX)
    X11InputContext context(error);
    if (!context) {
        return false;
    }
    std::vector<KeyCode> modifiers;
    KeyCode mainKey = 0;
    for (const QString& part : parts) {
        KeySym modifier = NoSymbol;
        if (part == QStringLiteral("ctrl") || part == QStringLiteral("control")) {
            modifier = XK_Control_L;
        } else if (part == QStringLiteral("shift")) {
            modifier = XK_Shift_L;
        } else if (part == QStringLiteral("alt")) {
            modifier = XK_Alt_L;
        } else if (part == QStringLiteral("win") || part == QStringLiteral("meta")) {
            modifier = XK_Super_L;
        }
        if (modifier != NoSymbol) {
            const KeyCode code = XKeysymToKeycode(context.display(), modifier);
            if (code == 0) {
                setInputError(error, QStringLiteral("The active X11 layout lacks a modifier key"));
                return false;
            }
            modifiers.push_back(code);
            continue;
        }
        if (mainKey != 0) {
            setInputError(error, QStringLiteral("A shortcut may contain only one non-modifier key"));
            return false;
        }
        mainKey = XKeysymToKeycode(context.display(), x11NamedKey(part));
    }
    if (mainKey == 0) {
        setInputError(error, QStringLiteral("The requested key or shortcut is unsupported"));
        return false;
    }
    for (const KeyCode modifier : modifiers) {
        XTestFakeKeyEvent(context.display(), modifier, True, CurrentTime);
    }
    XTestFakeKeyEvent(context.display(), mainKey, True, CurrentTime);
    XTestFakeKeyEvent(context.display(), mainKey, False, CurrentTime);
    for (auto iterator = modifiers.rbegin(); iterator != modifiers.rend(); ++iterator) {
        XTestFakeKeyEvent(context.display(), *iterator, False, CurrentTime);
    }
    return true;
#else
    Q_UNUSED(parts);
    setInputError(error, QStringLiteral("Global keyboard injection is unavailable on this platform"));
    return false;
#endif
}

}  // namespace bandori
