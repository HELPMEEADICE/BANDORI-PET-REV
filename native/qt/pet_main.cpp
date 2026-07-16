#include "live2d_gl_widget.h"
#include "native_radial_menu.h"
#include "pet_ipc_client.h"

#include <QApplication>
#include <QColor>
#include <QCommandLineOption>
#include <QCommandLineParser>
#include <QCursor>
#include <QDir>
#include <QFileInfo>
#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QPoint>
#include <QEasingCurve>
#include <QRect>
#include <QScreen>
#include <QSet>
#include <QSize>
#include <QStandardPaths>
#include <QStringList>
#include <QTimer>
#include <QUuid>
#include <QVariantAnimation>

#include <algorithm>
#include <cmath>
#include <limits>

#ifdef Q_OS_WIN
#define NOMINMAX
#include <windows.h>
#else
#include <cerrno>
#include <csignal>
#endif

namespace {

bool isProcessAlive(qint64 processId) {
    if (processId <= 0) {
        return true;
    }
#ifdef Q_OS_WIN
    const HANDLE process = OpenProcess(SYNCHRONIZE, FALSE, static_cast<DWORD>(processId));
    if (process == nullptr) {
        return false;
    }
    const bool alive = WaitForSingleObject(process, 0) == WAIT_TIMEOUT;
    CloseHandle(process);
    return alive;
#else
    const int result = kill(static_cast<pid_t>(processId), 0);
    return result == 0 || errno == EPERM;
#endif
}

bool optionBool(const QString& value, bool fallback = false) {
    const QString normalized = value.trimmed().toLower();
    if (normalized == QStringLiteral("1") || normalized == QStringLiteral("true")
        || normalized == QStringLiteral("yes") || normalized == QStringLiteral("on")) {
        return true;
    }
    if (normalized == QStringLiteral("0") || normalized == QStringLiteral("false")
        || normalized == QStringLiteral("no") || normalized == QStringLiteral("off")) {
        return false;
    }
    return fallback;
}

QString normalizedOverlayColor(const QString& value, const QString& fallback) {
    const QString normalized = value.trimmed().toLower();
    if (!normalized.startsWith(u'#')
        || (normalized.size() != 4 && normalized.size() != 7 && normalized.size() != 9)) {
        return fallback;
    }
    for (qsizetype index = 1; index < normalized.size(); ++index) {
        const QChar character = normalized.at(index);
        const bool asciiDigit = character >= u'0' && character <= u'9';
        const bool asciiHex = character >= u'a' && character <= u'f';
        if (!asciiDigit && !asciiHex) {
            return fallback;
        }
    }
    return normalized;
}

QString compactOverlayStyle(
    int opacityPercent,
    int fontSize,
    const QString& background,
    const QString& foreground) {
    QColor backgroundColor(
        normalizedOverlayColor(background, QStringLiteral("#fb7299")));
    backgroundColor.setAlphaF(std::clamp(opacityPercent, 10, 100) / 100.0);
    const QString textColor =
        normalizedOverlayColor(foreground, QStringLiteral("#24242a"));
    return QStringLiteral(
               "QLabel { color: %1; background: rgba(%2, %3, %4, %5); "
               "border: 1px solid rgba(255, 255, 255, 72); border-radius: 12px; "
               "font-size: %6px; }")
        .arg(textColor)
        .arg(backgroundColor.red())
        .arg(backgroundColor.green())
        .arg(backgroundColor.blue())
        .arg(backgroundColor.alpha())
        .arg(std::clamp(fontSize, 8, 36));
}

void applyObsWindowCaptureStyle(QWidget& widget, bool enabled) {
#ifdef Q_OS_WIN
    const HWND handle = reinterpret_cast<HWND>(widget.winId());
    if (handle == nullptr) {
        return;
    }
    const LONG_PTR current = GetWindowLongPtrW(handle, GWL_EXSTYLE);
    const LONG_PTR next = enabled
        ? ((current & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW)
        : ((current & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW);
    if (next != current) {
        SetWindowLongPtrW(handle, GWL_EXSTYLE, next);
        SetWindowPos(
            handle,
            nullptr,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
    }
#else
    Q_UNUSED(widget);
    Q_UNUSED(enabled);
#endif
}

void enforceGameTopmost(QWidget& widget, bool enabled) {
    if (!enabled || !widget.isVisible()) {
        return;
    }
#ifdef Q_OS_WIN
    SetWindowPos(
        reinterpret_cast<HWND>(widget.winId()),
        HWND_TOPMOST,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
#else
    widget.raise();
#endif
}

bool earlyBooleanOption(
    int argc,
    char* argv[],
    const QString& option,
    bool fallback) {
    const QString assignmentPrefix = option + QStringLiteral("=");
    for (int index = 1; index < argc; ++index) {
        const QString argument = QString::fromLocal8Bit(argv[index]);
        if (argument.startsWith(assignmentPrefix)) {
            return optionBool(argument.mid(assignmentPrefix.size()), fallback);
        }
        if (argument == option && index + 1 < argc) {
            return optionBool(QString::fromLocal8Bit(argv[index + 1]), fallback);
        }
    }
    return fallback;
}

int normalizedLive2dScale(int value) {
    return value <= 0 ? 100 : std::clamp(value, 25, 500);
}

QSize scaledLive2dSize(bandori::Live2dGlWidget::ModelFormat format, int scale) {
    scale = normalizedLive2dScale(scale);
    const int baseHeight = format == bandori::Live2dGlWidget::ModelFormat::Moc3 ? 800 : 500;
    return {
        std::max(1, (400 * scale + 50) / 100),
        std::max(1, (baseHeight * scale + 50) / 100),
    };
}

QJsonObject ipcJsonPayload(const QString& line) {
    const qsizetype separator = line.indexOf(u'\t');
    if (separator < 0) {
        return {};
    }
    const QJsonDocument document = QJsonDocument::fromJson(line.mid(separator + 1).toUtf8());
    return document.isObject() ? document.object() : QJsonObject {};
}

QString compactJson(const QJsonObject& value) {
    return QString::fromUtf8(QJsonDocument(value).toJson(QJsonDocument::Compact));
}

QString pixelSpritePath(const QString& pixelsRoot, const QString& character) {
    const QString normalized = character.trimmed();
    if (normalized.isEmpty() || normalized.size() > 128
        || normalized.contains(u'/') || normalized.contains(u'\\')
        || normalized.contains(QChar(u'\0'))) {
        return {};
    }
    return QDir(pixelsRoot).filePath(normalized + QStringLiteral(".webp"));
}

struct PeerDragState {
    QString dragId;
    QPoint origin;
};

struct InteractionFeedback {
    QString motion;
    QString expression;
};

const QString kWindowShakeObjectName = QStringLiteral("bandori-window-shake");

QString interactionRegion(double x, double y, int width, int height) {
    const double xRatio = std::clamp(x / std::max(width, 1), 0.0, 1.0);
    const double yRatio = std::clamp(y / std::max(height, 1), 0.0, 1.0);
    if (yRatio < 0.38) {
        return QStringLiteral("head");
    }
    const QString vertical = yRatio < 0.64
        ? QStringLiteral("upper_body")
        : QStringLiteral("lower_body");
    const QString horizontal = xRatio < 0.38
        ? QStringLiteral("left")
        : (xRatio > 0.62 ? QStringLiteral("right") : QStringLiteral("center"));
    return vertical + u'_' + horizontal;
}

InteractionFeedback feedbackForRegion(const QJsonObject& actions, const QString& region) {
    const QJsonValue raw = actions.value(region);
    if (raw.isString()) {
        return {raw.toString().trimmed(), {}};
    }
    if (!raw.isObject()) {
        return {};
    }
    const QJsonObject value = raw.toObject();
    return {
        value.value(QStringLiteral("motion")).toString().trimmed(),
        value.value(QStringLiteral("expression")).toString().trimmed(),
    };
}

void settleWindowShake(QWidget& widget) {
    auto* animation = widget.findChild<QVariantAnimation*>(kWindowShakeObjectName);
    if (animation == nullptr) {
        return;
    }
    const QPoint origin = animation->property("bandori-origin").toPoint();
    animation->stop();
    animation->setObjectName(QString {});
    widget.move(origin);
    animation->deleteLater();
}

void shakeWindow(QWidget& widget, int intensity) {
    settleWindowShake(widget);
    const QPoint origin = widget.pos();
    const int amplitude = std::clamp(6 + intensity / 5, 8, 26);
    auto* animation = new QVariantAnimation(&widget);
    animation->setObjectName(kWindowShakeObjectName);
    animation->setProperty("bandori-origin", origin);
    animation->setDuration(360);
    animation->setEasingCurve(QEasingCurve::OutCubic);
    animation->setKeyValueAt(0.0, origin);
    animation->setKeyValueAt(0.18, origin + QPoint(-amplitude, 0));
    animation->setKeyValueAt(0.36, origin + QPoint(amplitude, 0));
    animation->setKeyValueAt(0.55, origin + QPoint(-amplitude / 2, 0));
    animation->setKeyValueAt(0.74, origin + QPoint(amplitude / 2, 0));
    animation->setKeyValueAt(1.0, origin);
    QObject::connect(
        animation,
        &QVariantAnimation::valueChanged,
        &widget,
        [&widget](const QVariant& value) { widget.move(value.toPoint()); });
    QObject::connect(animation, &QVariantAnimation::finished, &widget, [&widget, animation, origin]() {
        animation->setObjectName(QString {});
        widget.move(origin);
        animation->deleteLater();
    });
    animation->start();
}

QPoint constrainedWindowPoint(const QWidget& widget, const QPoint& requested) {
    const QScreen* screen = widget.screen();
    if (screen == nullptr) {
        screen = QGuiApplication::screenAt(widget.frameGeometry().center());
    }
    if (screen == nullptr) {
        return requested;
    }
    const QRect available = screen->availableGeometry();
    return {
        std::clamp(requested.x(), available.left(),
                   std::max(available.left(), available.right() - widget.width() + 1)),
        std::clamp(requested.y(), available.top(),
                   std::max(available.top(), available.bottom() - widget.height() + 1)),
    };
}

void playEmotionWindowFeedback(
    QWidget& widget,
    const QString& rawKind,
    int intensity,
    bool dragLocked) {
    const QString kind = rawKind.trimmed().toLower();
    if (kind.isEmpty() || kind == QStringLiteral("none")
        || ((kind == QStringLiteral("forward") || kind == QStringLiteral("back"))
            && dragLocked)) {
        return;
    }
    if (kind != QStringLiteral("forward") && kind != QStringLiteral("back")
        && kind != QStringLiteral("hop") && kind != QStringLiteral("shake")
        && kind != QStringLiteral("wobble") && kind != QStringLiteral("settle")) {
        return;
    }

    if (auto* active = widget.findChild<QVariantAnimation*>(kWindowShakeObjectName)) {
        active->stop();
        active->setObjectName(QString {});
        active->deleteLater();
    }
    const QPoint origin = widget.pos();
    auto* animation = new QVariantAnimation(&widget);
    animation->setObjectName(kWindowShakeObjectName);
    animation->setProperty("bandori-origin", origin);
    animation->setEasingCurve(QEasingCurve::OutCubic);

    QPoint finalPoint = origin;
    if (kind == QStringLiteral("forward") || kind == QStringLiteral("back")) {
        const QPoint cursor = QCursor::pos();
        const QPoint center = widget.frameGeometry().center();
        const double dx = static_cast<double>(cursor.x() - center.x());
        const double dy = static_cast<double>(cursor.y() - center.y());
        const double length = std::hypot(dx, dy);
        const double direction = kind == QStringLiteral("back") ? -1.0 : 1.0;
        const int distance = std::clamp(10 + intensity * 8 / 25, 8, 42);
        const QPoint delta = length >= 8.0
            ? QPoint(
                  qRound(direction * distance * dx / length),
                  qRound(direction * distance * dy / length))
            : QPoint(0, qRound(-direction * distance));
        finalPoint = constrainedWindowPoint(widget, origin + delta);
        animation->setDuration(300);
        animation->setKeyValueAt(0.0, origin);
        animation->setKeyValueAt(1.0, finalPoint);
    } else if (kind == QStringLiteral("hop")) {
        const int lift = std::clamp(8 + intensity * 6 / 25, 10, 34);
        animation->setDuration(420);
        animation->setKeyValueAt(0.0, origin);
        animation->setKeyValueAt(0.38, constrainedWindowPoint(widget, origin + QPoint(0, -lift)));
        animation->setKeyValueAt(
            0.72,
            constrainedWindowPoint(widget, origin + QPoint(0, std::max(2, lift / 5))));
        animation->setKeyValueAt(1.0, origin);
    } else if (kind == QStringLiteral("settle")) {
        const int drop = std::clamp(2 + intensity * 2 / 25, 3, 10);
        animation->setDuration(340);
        animation->setKeyValueAt(0.0, origin);
        animation->setKeyValueAt(0.45, constrainedWindowPoint(widget, origin + QPoint(0, drop)));
        animation->setKeyValueAt(1.0, origin);
    } else if (kind == QStringLiteral("shake")) {
        const int amplitude = std::clamp(6 + intensity / 5, 8, 26);
        animation->setDuration(360);
        animation->setKeyValueAt(0.0, origin);
        animation->setKeyValueAt(0.18, constrainedWindowPoint(widget, origin + QPoint(-amplitude, 0)));
        animation->setKeyValueAt(0.36, constrainedWindowPoint(widget, origin + QPoint(amplitude, 0)));
        animation->setKeyValueAt(0.55, constrainedWindowPoint(widget, origin + QPoint(-amplitude / 2, 0)));
        animation->setKeyValueAt(0.74, constrainedWindowPoint(widget, origin + QPoint(amplitude / 2, 0)));
        animation->setKeyValueAt(1.0, origin);
    } else {
        const int amplitude = std::clamp(4 + intensity * 3 / 25, 5, 16);
        animation->setDuration(420);
        animation->setKeyValueAt(0.0, origin);
        animation->setKeyValueAt(
            0.25,
            constrainedWindowPoint(widget, origin + QPoint(amplitude, 2)));
        animation->setKeyValueAt(
            0.50,
            constrainedWindowPoint(widget, origin + QPoint(-amplitude, -1)));
        animation->setKeyValueAt(
            0.75,
            constrainedWindowPoint(widget, origin + QPoint(amplitude / 2, 0)));
        animation->setKeyValueAt(1.0, origin);
    }
    QObject::connect(
        animation,
        &QVariantAnimation::valueChanged,
        &widget,
        [&widget](const QVariant& value) { widget.move(value.toPoint()); });
    QObject::connect(
        animation,
        &QVariantAnimation::finished,
        &widget,
        [&widget, animation, finalPoint]() {
            animation->setObjectName(QString {});
            widget.move(finalPoint);
            animation->deleteLater();
        });
    animation->start();
}

QJsonArray rectangleJson(const QRect& rectangle) {
    return {rectangle.left(), rectangle.top(), rectangle.width(), rectangle.height()};
}

QJsonObject petWindowState(
    const bandori::Live2dGlWidget& widget,
    const QString& character,
    const QString& modelPath) {
    const QRect geometry = widget.geometry();
    QJsonObject placement;
    if (const QScreen* screen = widget.screen()) {
        const QRect available = screen->availableGeometry();
        const int spanX = std::max(1, available.width() - geometry.width());
        const int spanY = std::max(1, available.height() - geometry.height());
        placement = {
            {QStringLiteral("screen_name"), screen->name()},
            {QStringLiteral("screen_serial"), screen->serialNumber()},
            {QStringLiteral("screen_manufacturer"), screen->manufacturer()},
            {QStringLiteral("screen_model"), screen->model()},
            {QStringLiteral("screen_geometry"), rectangleJson(screen->geometry())},
            {QStringLiteral("screen_available_geometry"), rectangleJson(available)},
            {QStringLiteral("relative_x"),
             static_cast<double>(geometry.left() - available.left()) / spanX},
            {QStringLiteral("relative_y"),
             static_cast<double>(geometry.top() - available.top()) / spanY},
            {QStringLiteral("right_offset"), available.right() - geometry.right()},
            {QStringLiteral("bottom_offset"), available.bottom() - geometry.bottom()},
            {QStringLiteral("device_pixel_ratio"), screen->devicePixelRatio()},
        };
    }
    return {
        {QStringLiteral("character"), character},
        {QStringLiteral("model_path"), modelPath},
        {QStringLiteral("x"), geometry.x()},
        {QStringLiteral("y"), geometry.y()},
        {QStringLiteral("width"), geometry.width()},
        {QStringLiteral("height"), geometry.height()},
        {QStringLiteral("drag_locked"), widget.dragLocked()},
        {QStringLiteral("pet_mode"),
         widget.pixelMode() ? QStringLiteral("pixel") : QStringLiteral("live2d")},
        {QStringLiteral("placement"), placement},
    };
}

bool publishPetWindowState(
    bandori::PetIpcClient* client,
    const bandori::Live2dGlWidget& widget,
    const QString& character,
    const QString& modelPath) {
    return client != nullptr
        && client->publishLine(
            QStringLiteral("PET_STATE\t")
                + compactJson(petWindowState(widget, character, modelPath)),
            true);
}

} // namespace

int main(int argc, char* argv[]) {
    const bool initialVsync = earlyBooleanOption(argc, argv, QStringLiteral("--vsync"), true);
    bandori::Live2dGlWidget::configureDefaultSurfaceFormat(initialVsync);
    QApplication app(argc, argv);
    QApplication::setApplicationName(QStringLiteral("BandoriPetRenderer"));
    QApplication::setOrganizationName(QStringLiteral("BandoriPet"));
    QApplication::setQuitOnLastWindowClosed(true);

    QCommandLineParser parser;
    parser.setApplicationDescription(
        QStringLiteral("Isolated Rust + LuaJIT + Qt pet renderer"));
    parser.addHelpOption();
    QCommandLineOption projectRoot(
        QStringLiteral("project-root"),
        QStringLiteral("BandoriPet installation root"),
        QStringLiteral("path"),
        QDir::currentPath());
    QCommandLineOption userModels(
        QStringLiteral("user-models"),
        QStringLiteral("Writable user model directory"),
        QStringLiteral("path"),
        QStandardPaths::writableLocation(QStandardPaths::AppDataLocation) + QStringLiteral("/models"));
    QCommandLineOption model(
        QStringLiteral("model"),
        QStringLiteral("Model manifest path"),
        QStringLiteral("path"));
    QCommandLineOption character(
        QStringLiteral("character"),
        QStringLiteral("Character identifier used for IPC registration"),
        QStringLiteral("id"));
    QCommandLineOption language(
        QStringLiteral("language"),
        QStringLiteral("Language used by native pet controls"),
        QStringLiteral("locale"));
    QCommandLineOption format(
        QStringLiteral("format"),
        QStringLiteral("Model format: moc or moc3"),
        QStringLiteral("format"),
        QStringLiteral("moc3"));
    QCommandLineOption petMode(
        QStringLiteral("pet-mode"),
        QStringLiteral("Pet renderer mode: live2d or pixel"),
        QStringLiteral("mode"),
        QStringLiteral("live2d"));
    QCommandLineOption width(
        QStringLiteral("width"), QStringLiteral("Pet width"), QStringLiteral("pixels"), QStringLiteral("400"));
    QCommandLineOption height(
        QStringLiteral("height"), QStringLiteral("Pet height"), QStringLiteral("pixels"), QStringLiteral("650"));
    QCommandLineOption positionX(
        QStringLiteral("x"), QStringLiteral("Initial global X position"), QStringLiteral("x"), QStringLiteral("-1"));
    QCommandLineOption positionY(
        QStringLiteral("y"), QStringLiteral("Initial global Y position"), QStringLiteral("y"), QStringLiteral("-1"));
    QCommandLineOption fps(
        QStringLiteral("fps"), QStringLiteral("Render frame rate"), QStringLiteral("fps"), QStringLiteral("120"));
    QCommandLineOption opacity(
        QStringLiteral("opacity"),
        QStringLiteral("Window opacity"),
        QStringLiteral("opacity"),
        QStringLiteral("1.0"));
    QCommandLineOption gameTopmost(
        QStringLiteral("game-topmost"),
        QStringLiteral("Continuously restore the pet above games and full-screen windows"),
        QStringLiteral("bool"),
        QStringLiteral("false"));
    QCommandLineOption obsWindowCaptureCompatible(
        QStringLiteral("obs-window-capture-compatible"),
        QStringLiteral("Expose the native pet as an application window for OBS capture"),
        QStringLiteral("bool"),
        QStringLiteral("false"));
    QCommandLineOption hideLive2dModel(
        QStringLiteral("hide-live2d-model"),
        QStringLiteral("Keep the pet process active without showing its model window"),
        QStringLiteral("bool"),
        QStringLiteral("false"));
    QCommandLineOption vsync(
        QStringLiteral("vsync"),
        QStringLiteral("Enable the OpenGL swap interval before QApplication starts"),
        QStringLiteral("bool"),
        initialVsync ? QStringLiteral("true") : QStringLiteral("false"));
    QCommandLineOption quality(
        QStringLiteral("quality"),
        QStringLiteral("Live2D texture and Cubism 3 SSAA quality: performance or balanced"),
        QStringLiteral("quality"),
        QStringLiteral("balanced"));
    QCommandLineOption live2dScale(
        QStringLiteral("scale"),
        QStringLiteral("Live2D window scale percentage (25-500)"),
        QStringLiteral("percent"),
        QStringLiteral("100"));
    QCommandLineOption lipSyncMaxOpen(
        QStringLiteral("lip-sync-max-open"),
        QStringLiteral("Maximum mouth-open parameter used by lip sync"),
        QStringLiteral("value"),
        QStringLiteral("0.55"));
    QCommandLineOption hitAlphaThreshold(
        QStringLiteral("hit-alpha-threshold"),
        QStringLiteral("Alpha threshold used for transparent input passthrough"),
        QStringLiteral("alpha"),
        QStringLiteral("8"));
    QCommandLineOption clickMotionActions(
        QStringLiteral("click-motion-actions"),
        QStringLiteral("Per-region click motion feedback JSON"),
        QStringLiteral("json"),
        QStringLiteral("{}"));
    QCommandLineOption pokeMotion(
        QStringLiteral("poke-motion"),
        QStringLiteral("Motion used for user poke feedback"),
        QStringLiteral("motion"));
    QCommandLineOption pokeExpression(
        QStringLiteral("poke-expression"),
        QStringLiteral("Expression used for user poke feedback"),
        QStringLiteral("expression"));
    QCommandLineOption defaultMotion(
        QStringLiteral("default-motion"),
        QStringLiteral("Configured looping startup motion"),
        QStringLiteral("motion"));
    QCommandLineOption defaultExpression(
        QStringLiteral("default-expression"),
        QStringLiteral("Configured persistent startup expression"),
        QStringLiteral("expression"));
    QCommandLineOption idleActionsEnabled(
        QStringLiteral("idle-actions-enabled"),
        QStringLiteral("Run a configured or discovered looping idle motion"),
        QStringLiteral("bool"),
        QStringLiteral("true"));
    QCommandLineOption randomActionsEnabled(
        QStringLiteral("random-actions-enabled"),
        QStringLiteral("Rotate among discovered idle motions"),
        QStringLiteral("bool"),
        QStringLiteral("true"));
    QCommandLineOption dragLocked(
        QStringLiteral("drag-locked"),
        QStringLiteral("Whether direct pet-window dragging is locked"),
        QStringLiteral("bool"),
        QStringLiteral("false"));
    QCommandLineOption moveAllRolesTogether(
        QStringLiteral("move-all-roles-together"),
        QStringLiteral("Mirror drag sessions across all active pet processes"),
        QStringLiteral("bool"),
        QStringLiteral("false"));
    QCommandLineOption headTrackingEnabled(
        QStringLiteral("head-tracking-enabled"),
        QStringLiteral("Track the global mouse cursor when mutual gaze is disabled"),
        QStringLiteral("bool"),
        QStringLiteral("true"));
    QCommandLineOption mutualGazeEnabled(
        QStringLiteral("mutual-gaze-enabled"),
        QStringLiteral("Look toward the nearest active pet process"),
        QStringLiteral("bool"),
        QStringLiteral("false"));
    QCommandLineOption emotionBehaviorEnabled(
        QStringLiteral("emotion-behavior-enabled"),
        QStringLiteral("Apply inferred expression, motion, window and voice feedback"),
        QStringLiteral("bool"),
        QStringLiteral("true"));
    QCommandLineOption compactAiWindowEnabled(
        QStringLiteral("compact-ai-window-enabled"),
        QStringLiteral("Show compact native event bubbles"),
        QStringLiteral("bool"),
        QStringLiteral("false"));
    QCommandLineOption compactAiWindowOpacity(
        QStringLiteral("compact-ai-window-opacity"),
        QStringLiteral("Compact event bubble background opacity (10-100)"),
        QStringLiteral("percent"),
        QStringLiteral("44"));
    QCommandLineOption compactAiWindowFontSize(
        QStringLiteral("compact-ai-window-font-size"),
        QStringLiteral("Compact event bubble font size (8-36)"),
        QStringLiteral("pixels"),
        QStringLiteral("12"));
    QCommandLineOption compactAiWindowBackgroundColor(
        QStringLiteral("compact-ai-window-background-color"),
        QStringLiteral("Compact event bubble background color"),
        QStringLiteral("color"),
        QStringLiteral("#fb7299"));
    QCommandLineOption compactAiWindowTextColor(
        QStringLiteral("compact-ai-window-text-color"),
        QStringLiteral("Compact event bubble text color"),
        QStringLiteral("color"),
        QStringLiteral("#24242a"));
    QCommandLineOption aiEventOverlayEnabled(
        QStringLiteral("ai-event-overlay-enabled"),
        QStringLiteral("Accept AI status overlay events"),
        QStringLiteral("bool"),
        QStringLiteral("false"));
    QCommandLineOption chatIntegrationOverlayEnabled(
        QStringLiteral("chat-integration-overlay-enabled"),
        QStringLiteral("Accept external chat overlay events"),
        QStringLiteral("bool"),
        QStringLiteral("true"));
    QCommandLineOption parentPid(
        QStringLiteral("parent-pid"),
        QStringLiteral("Quit when this supervisor process exits"),
        QStringLiteral("pid"),
        QStringLiteral("0"));
    QCommandLineOption ipcSession(
        QStringLiteral("ipc-session"),
        QStringLiteral("Bandori shared-memory IPC session name"),
        QStringLiteral("name"));
    parser.addOptions(
        {projectRoot,
         userModels,
         model,
         character,
         language,
         format,
         petMode,
         width,
         height,
         positionX,
         positionY,
         fps,
         opacity,
         gameTopmost,
         obsWindowCaptureCompatible,
         hideLive2dModel,
         vsync,
         quality,
         live2dScale,
         lipSyncMaxOpen,
         hitAlphaThreshold,
         clickMotionActions,
         pokeMotion,
         pokeExpression,
         defaultMotion,
         defaultExpression,
         idleActionsEnabled,
         randomActionsEnabled,
         dragLocked,
         moveAllRolesTogether,
         headTrackingEnabled,
         mutualGazeEnabled,
         emotionBehaviorEnabled,
         compactAiWindowEnabled,
         compactAiWindowOpacity,
         compactAiWindowFontSize,
         compactAiWindowBackgroundColor,
         compactAiWindowTextColor,
         aiEventOverlayEnabled,
         chatIntegrationOverlayEnabled,
         parentPid,
         ipcSession});
    parser.process(app);

    if (!parser.isSet(model)) {
        parser.showHelp(2);
    }
    const auto modelFormat = parser.value(format).compare(QStringLiteral("moc"), Qt::CaseInsensitive) == 0
        ? bandori::Live2dGlWidget::ModelFormat::Moc
        : bandori::Live2dGlWidget::ModelFormat::Moc3;
    const QString modelPath = parser.value(model);
    QString characterId = parser.value(character).trimmed();
    if (characterId.isEmpty()) {
        characterId = QFileInfo(modelPath).completeBaseName();
    }
    const bool requestedPixel =
        parser.value(petMode).compare(QStringLiteral("pixel"), Qt::CaseInsensitive) == 0;
    bandori::Live2dGlWidget widget(
        parser.value(projectRoot),
        parser.value(userModels),
        modelPath,
        modelFormat);
    widget.setRenderQuality(parser.value(quality));
    widget.setFramesPerSecond(parser.value(fps).toInt());
    widget.setHitAlphaThreshold(parser.value(hitAlphaThreshold).toInt());
    widget.setDragLocked(optionBool(parser.value(dragLocked)));
    bool headTracking = optionBool(parser.value(headTrackingEnabled), true);
    bool mutualGaze = optionBool(parser.value(mutualGazeEnabled));
    bool emotionBehavior = optionBool(parser.value(emotionBehaviorEnabled), true);
    bool compactAiWindow = optionBool(parser.value(compactAiWindowEnabled));
    int compactOverlayOpacity =
        std::clamp(parser.value(compactAiWindowOpacity).toInt(), 10, 100);
    int compactOverlayFontSize =
        std::clamp(parser.value(compactAiWindowFontSize).toInt(), 8, 36);
    QString compactOverlayBackground = normalizedOverlayColor(
        parser.value(compactAiWindowBackgroundColor), QStringLiteral("#fb7299"));
    QString compactOverlayForeground = normalizedOverlayColor(
        parser.value(compactAiWindowTextColor), QStringLiteral("#24242a"));
    bool gameTopmostEnabled = optionBool(parser.value(gameTopmost));
    bool obsCaptureCompatible = optionBool(parser.value(obsWindowCaptureCompatible));
    bool modelHidden = optionBool(parser.value(hideLive2dModel));
    bool aiEventOverlay = optionBool(parser.value(aiEventOverlayEnabled));
    bool chatIntegrationOverlay =
        optionBool(parser.value(chatIntegrationOverlayEnabled), true);
    widget.setHeadTrackingEnabled(headTracking && !mutualGaze);
    widget.setLipSyncMaxOpen(parser.value(lipSyncMaxOpen).toDouble());
    widget.setWindowOpacity(std::clamp(parser.value(opacity).toDouble(), 0.05, 1.0));
    widget.setWindowFlags(Qt::Tool | Qt::FramelessWindowHint | Qt::WindowStaysOnTopHint);
    widget.setAttribute(Qt::WA_TranslucentBackground, true);
    int currentScale = normalizedLive2dScale(parser.value(live2dScale).toInt());
    widget.setLive2dWindowSize(scaledLive2dSize(modelFormat, currentScale));
    const QString pixelsRoot =
        QDir(parser.value(projectRoot)).filePath(QStringLiteral("pixels"));
    const bool pixelLoaded = widget.loadPixelSprite(
        pixelSpritePath(pixelsRoot, characterId),
        QDir(pixelsRoot).filePath(QStringLiteral("frames.json")));
    if (requestedPixel && (!pixelLoaded || !widget.setPixelMode(true))) {
        qWarning().noquote()
            << "Pixel pet assets are unavailable for" << characterId
            << "; using Live2D renderer";
    }
    const int initialX = parser.value(positionX).toInt();
    const int initialY = parser.value(positionY).toInt();
    const QRect requestedGeometry(initialX, initialY, widget.width(), widget.height());
    bool restoredPosition = initialX != -1 || initialY != -1;
    if (restoredPosition) {
        const QList<QScreen*> screens = QGuiApplication::screens();
        restoredPosition = std::any_of(
            screens.cbegin(),
            screens.cend(),
            [&requestedGeometry](const QScreen* screen) {
                return screen != nullptr && screen->availableGeometry().intersects(requestedGeometry);
            });
    }
    if (restoredPosition) {
        widget.move(initialX, initialY);
    } else if (QScreen* screen = QGuiApplication::primaryScreen()) {
        const QRect available = screen->availableGeometry();
        widget.move(
            available.left() + (available.width() - widget.width()) / 2,
            available.top() + (available.height() - widget.height()) / 2);
    }
    QLabel reminderBubble(&widget);
    reminderBubble.setAttribute(Qt::WA_TransparentForMouseEvents, true);
    reminderBubble.setAlignment(Qt::AlignCenter);
    reminderBubble.setWordWrap(true);
    reminderBubble.setMargin(10);
    reminderBubble.setStyleSheet(compactOverlayStyle(
        compactOverlayOpacity,
        compactOverlayFontSize,
        compactOverlayBackground,
        compactOverlayForeground));
    reminderBubble.hide();
    int reminderBubbleGeneration = 0;
    QTimer gameTopmostTimer;
    gameTopmostTimer.setInterval(750);
    QObject::connect(&gameTopmostTimer, &QTimer::timeout, &widget, [&widget, &gameTopmostEnabled]() {
        enforceGameTopmost(widget, gameTopmostEnabled);
    });
    gameTopmostTimer.start();
    bandori::NativeRadialMenu radialMenu;
    radialMenu.setLocked(widget.dragLocked());
    radialMenu.setLanguage(parser.value(language));
    radialMenu.setPixelAvailable(widget.pixelAvailable());
    radialMenu.setPixelActive(widget.pixelMode());

    QTimer parentWatch;
    const qint64 supervisorPid = parser.value(parentPid).toLongLong();
    if (supervisorPid > 0) {
        parentWatch.setInterval(1'000);
        QObject::connect(&parentWatch, &QTimer::timeout, &app, [&app, supervisorPid]() {
            if (!isProcessAlive(supervisorPid)) {
                app.quit();
            }
        });
        parentWatch.start();
    }

    const QJsonDocument clickActionsDocument =
        QJsonDocument::fromJson(parser.value(clickMotionActions).toUtf8());
    QJsonObject configuredClickActions = clickActionsDocument.isObject()
        ? clickActionsDocument.object()
        : QJsonObject {};
    QString configuredPokeMotion = parser.value(pokeMotion).trimmed();
    QString configuredPokeExpression = parser.value(pokeExpression).trimmed();
    const QString configuredDefaultMotion = parser.value(defaultMotion).trimmed();
    const QString configuredDefaultExpression = parser.value(defaultExpression).trimmed();
    bool idleActions = optionBool(parser.value(idleActionsEnabled), true);
    bool randomActions = optionBool(parser.value(randomActionsEnabled), true);
    QObject::connect(
        &widget,
        &bandori::Live2dGlWidget::runtimeReady,
        &widget,
        [&widget,
         characterId,
         configuredDefaultMotion,
         configuredDefaultExpression,
         &idleActions,
         &randomActions]() {
            widget.applyDefaultState(
                configuredDefaultMotion,
                configuredDefaultExpression,
                characterId,
                idleActions,
                randomActions);
        });
    QString ipcSessionName = parser.value(ipcSession).trimmed();
    if (ipcSessionName.isEmpty()) {
        ipcSessionName = qEnvironmentVariable("BANDORI_PET_IPC_SERVER_NAME").trimmed();
    }
    auto* ipcClient = new bandori::PetIpcClient(ipcSessionName, characterId, &app);
    bool moveAllRoles = optionBool(parser.value(moveAllRolesTogether));
    QString activeDragId;
    QHash<QString, PeerDragState> peerDragStates;
    QSet<QString> completedPeerDragIds;
    QStringList completedPeerDragOrder;
    QHash<QString, QPoint> peerPositions;
    QPoint lastPublishedCenter;
    bool lastPublishedCenterValid = false;
    auto triggerPokeFeedback = [&widget,
                                &configuredClickActions,
                                &configuredPokeMotion,
                                &configuredPokeExpression,
                                characterId]() {
        InteractionFeedback feedback {
            configuredPokeMotion,
            configuredPokeExpression,
        };
        if (feedback.motion.isEmpty() && feedback.expression.isEmpty()) {
            feedback = feedbackForRegion(configuredClickActions, QStringLiteral("head"));
        }
        return widget.triggerInteraction(
            QStringLiteral("head"),
            feedback.motion,
            feedback.expression,
            characterId);
    };
    auto updateMutualGaze = [&widget, &mutualGaze, &peerPositions]() {
        if (!mutualGaze || peerPositions.isEmpty()) {
            widget.clearGazeTarget();
            return;
        }
        const QPoint ownCenter = widget.geometry().center();
        QPoint nearest;
        qint64 nearestDistance = std::numeric_limits<qint64>::max();
        for (auto iterator = peerPositions.cbegin(); iterator != peerPositions.cend(); ++iterator) {
            const qint64 dx = static_cast<qint64>(iterator.value().x()) - ownCenter.x();
            const qint64 dy = static_cast<qint64>(iterator.value().y()) - ownCenter.y();
            const qint64 distance = dx * dx + dy * dy;
            if (distance < nearestDistance) {
                nearestDistance = distance;
                nearest = iterator.value();
            }
        }
        widget.setGazeTargetGlobal(nearest);
    };
    QTimer peerPositionTimer;
    peerPositionTimer.setInterval(200);
    QObject::connect(
        &peerPositionTimer,
        &QTimer::timeout,
        ipcClient,
        [ipcClient,
         &widget,
         &mutualGaze,
         &lastPublishedCenter,
         &lastPublishedCenterValid,
         characterId]() {
            if (!mutualGaze) {
                return;
            }
            const QPoint center = widget.geometry().center();
            if (lastPublishedCenterValid && center == lastPublishedCenter) {
                return;
            }
            if (ipcClient->publishLine(
                    QStringLiteral("PEER_POS\t")
                    + compactJson({
                        {QStringLiteral("character"), characterId},
                        {QStringLiteral("x"), center.x()},
                        {QStringLiteral("y"), center.y()},
                    }))) {
                lastPublishedCenter = center;
                lastPublishedCenterValid = true;
            }
        });
    peerPositionTimer.start();
    QObject::connect(
        &widget,
        &bandori::Live2dGlWidget::rightClicked,
        &radialMenu,
        [&radialMenu](int globalX, int globalY) {
            radialMenu.showAt(QPoint(globalX, globalY));
        });
    QObject::connect(
        &radialMenu,
        &bandori::NativeRadialMenu::opened,
        ipcClient,
        [ipcClient, characterId]() {
            ipcClient->publishLine(
                QStringLiteral("RADIAL_MENU_OPEN\t")
                    + compactJson({{QStringLiteral("character"), characterId}}),
                true);
        });
    QObject::connect(
        &radialMenu,
        &bandori::NativeRadialMenu::closed,
        ipcClient,
        [ipcClient, characterId]() {
            ipcClient->publishLine(
                QStringLiteral("RADIAL_MENU_CLOSED\t")
                    + compactJson({{QStringLiteral("character"), characterId}}),
                true);
        });
    QObject::connect(
        &radialMenu,
        &bandori::NativeRadialMenu::lockToggled,
        &widget,
        [ipcClient, &widget, characterId, modelPath](bool locked) {
            widget.setDragLocked(locked);
            publishPetWindowState(ipcClient, widget, characterId, modelPath);
        });
    QObject::connect(
        &radialMenu,
        &bandori::NativeRadialMenu::actionTriggered,
        &widget,
        [ipcClient, &widget, &radialMenu, characterId, modelPath](const QString& action) {
            if (action == QStringLiteral("chat")) {
                const QRect geometry = widget.geometry();
                ipcClient->publishLine(
                    QStringLiteral("OPEN_CHAT_NATIVE\t")
                        + compactJson({
                            {QStringLiteral("character"), characterId},
                            {QStringLiteral("x"), geometry.x()},
                            {QStringLiteral("y"), geometry.y()},
                            {QStringLiteral("width"), geometry.width()},
                            {QStringLiteral("height"), geometry.height()},
                        }),
                    true);
            } else if (action == QStringLiteral("costume")) {
                ipcClient->publishLine(
                    QStringLiteral("OPEN_SETTINGS\tcostumes\t") + characterId,
                    true);
            } else if (action == QStringLiteral("motion")) {
                widget.triggerInteraction(
                    QStringLiteral("head"),
                    QStringLiteral("__random__"),
                    {},
                    characterId);
            } else if (action == QStringLiteral("pixel")) {
                publishPetWindowState(ipcClient, widget, characterId, modelPath);
                if (widget.setPixelMode(!widget.pixelMode())) {
                    radialMenu.setPixelActive(widget.pixelMode());
                    publishPetWindowState(ipcClient, widget, characterId, modelPath);
                }
            }
        });
    QObject::connect(
        &widget,
        &bandori::Live2dGlWidget::clicked,
        &widget,
        [&widget, &configuredClickActions, characterId](double x, double y) {
            const QString region = interactionRegion(x, y, widget.width(), widget.height());
            const InteractionFeedback feedback = feedbackForRegion(configuredClickActions, region);
            widget.triggerInteraction(
                region,
                feedback.motion,
                feedback.expression,
                characterId);
        });
    QObject::connect(
        &widget,
        &bandori::Live2dGlWidget::doubleClicked,
        ipcClient,
        [ipcClient, &widget, &triggerPokeFeedback, characterId](double, double) {
            triggerPokeFeedback();
            shakeWindow(widget, 72);
            ipcClient->publishLine(
                QStringLiteral("POKE_USER\t")
                    + compactJson({
                        {QStringLiteral("character"), characterId},
                        {QStringLiteral("source"),
                         widget.pixelMode() ? QStringLiteral("pixel")
                                            : QStringLiteral("live2d")},
                    }),
                true);
        });
    QObject::connect(
        &widget,
        &bandori::Live2dGlWidget::windowDragStarted,
        ipcClient,
        [&widget, &activeDragId]() {
            settleWindowShake(widget);
            activeDragId = QUuid::createUuid()
                               .toString(QUuid::WithoutBraces)
                               .remove(QLatin1Char('-'));
        });
    QObject::connect(
        &widget,
        &bandori::Live2dGlWidget::windowDragMoved,
        ipcClient,
        [ipcClient,
         &widget,
         &moveAllRoles,
         &activeDragId,
         characterId,
         modelPath](int totalDx, int totalDy) {
            if (!moveAllRoles || activeDragId.isEmpty()) {
                return;
            }
            ipcClient->publishLine(
                QStringLiteral("PEER_DRAG\t")
                + compactJson({
                    {QStringLiteral("character"), characterId},
                    {QStringLiteral("drag_id"), activeDragId},
                    {QStringLiteral("total_dx"), totalDx},
                    {QStringLiteral("total_dy"), totalDy},
                }));
        });
    QObject::connect(
        &widget,
        &bandori::Live2dGlWidget::windowDragFinished,
        ipcClient,
        [ipcClient,
         &widget,
         &moveAllRoles,
         &activeDragId,
         characterId,
         modelPath](int totalDx, int totalDy) {
            if (moveAllRoles && !activeDragId.isEmpty() && (totalDx != 0 || totalDy != 0)) {
                ipcClient->publishLine(
                    QStringLiteral("PEER_DRAG_END\t")
                        + compactJson({
                            {QStringLiteral("character"), characterId},
                            {QStringLiteral("drag_id"), activeDragId},
                            {QStringLiteral("total_dx"), totalDx},
                            {QStringLiteral("total_dy"), totalDy},
                        }),
                    true);
            }
            publishPetWindowState(ipcClient, widget, characterId, modelPath);
            activeDragId.clear();
        });
    QObject::connect(
        ipcClient, &bandori::PetIpcClient::shutdownRequested, &app, &QCoreApplication::quit);
    QObject::connect(
        ipcClient,
        &bandori::PetIpcClient::controlLineReceived,
        &widget,
        [&widget,
         characterId,
         &moveAllRoles,
         &peerDragStates,
         &completedPeerDragIds,
         &completedPeerDragOrder,
         &headTracking,
         &mutualGaze,
         &emotionBehavior,
         &peerPositions,
         &lastPublishedCenterValid,
         &updateMutualGaze,
         &configuredClickActions,
         &configuredPokeMotion,
         &configuredPokeExpression,
         configuredDefaultMotion,
         configuredDefaultExpression,
         &idleActions,
         &randomActions,
         &currentScale,
         modelFormat,
         &triggerPokeFeedback,
         &reminderBubble,
         &reminderBubbleGeneration,
         &compactAiWindow,
         &compactOverlayOpacity,
         &compactOverlayFontSize,
         &compactOverlayBackground,
         &compactOverlayForeground,
         &gameTopmostEnabled,
         &obsCaptureCompatible,
         &modelHidden,
         &aiEventOverlay,
         &chatIntegrationOverlay,
         &radialMenu,
         ipcClient,
         modelPath](const QString& line) {
            const bool peerDragFinished = line.startsWith(QStringLiteral("PEER_DRAG_END\t"));
            if (peerDragFinished || line.startsWith(QStringLiteral("PEER_DRAG\t"))) {
                if (!moveAllRoles) {
                    return;
                }
                const QJsonObject payload = ipcJsonPayload(line);
                const QString peerCharacter = payload.value(QStringLiteral("character")).toString();
                if (peerCharacter.isEmpty() || peerCharacter == characterId) {
                    return;
                }
                const QString dragId = payload.value(QStringLiteral("drag_id")).toString().trimmed();
                QPoint target;
                if (!dragId.isEmpty()) {
                    if (completedPeerDragIds.contains(dragId)) {
                        return;
                    }
                    auto state = peerDragStates.value(peerCharacter);
                    if (state.dragId != dragId) {
                        state = {dragId, widget.pos()};
                        peerDragStates.insert(peerCharacter, state);
                    }
                    target = state.origin
                        + QPoint(
                            payload.value(QStringLiteral("total_dx")).toInt(),
                            payload.value(QStringLiteral("total_dy")).toInt());
                } else {
                    target = widget.pos()
                        + QPoint(
                            payload.value(QStringLiteral("dx")).toInt(),
                            payload.value(QStringLiteral("dy")).toInt());
                }
                widget.move(target);
                if (peerDragFinished && !dragId.isEmpty()) {
                    peerDragStates.remove(peerCharacter);
                    completedPeerDragIds.insert(dragId);
                    completedPeerDragOrder.append(dragId);
                    while (completedPeerDragOrder.size() > 128) {
                        completedPeerDragIds.remove(completedPeerDragOrder.takeFirst());
                    }
                    publishPetWindowState(ipcClient, widget, characterId, modelPath);
                }
                return;
            }
            if (line.startsWith(QStringLiteral("PEER_OFFLINE\t"))) {
                const QString peerCharacter =
                    ipcJsonPayload(line).value(QStringLiteral("character")).toString();
                if (!peerCharacter.isEmpty()) {
                    peerDragStates.remove(peerCharacter);
                    peerPositions.remove(peerCharacter);
                    updateMutualGaze();
                }
                return;
            }
            if (line.startsWith(QStringLiteral("PEER_POS\t"))) {
                const QJsonObject payload = ipcJsonPayload(line);
                const QString peerCharacter = payload.value(QStringLiteral("character")).toString();
                if (!peerCharacter.isEmpty() && peerCharacter != characterId) {
                    peerPositions.insert(
                        peerCharacter,
                        QPoint(
                            payload.value(QStringLiteral("x")).toInt(),
                            payload.value(QStringLiteral("y")).toInt()));
                    updateMutualGaze();
                }
                return;
            }
            if (line.startsWith(QStringLiteral("PREVIEW_MOTION\t"))) {
                const QStringList parts = line.split(u'\t');
                if (parts.size() >= 4 && parts.at(1) == characterId) {
                    if (!parts.at(2).isEmpty()) {
                        widget.triggerAction(parts.at(2), characterId);
                    }
                    if (!parts.at(3).isEmpty()) {
                        widget.triggerAction(parts.at(3), characterId);
                    }
                }
                return;
            }
            const bool aiEvent = line.startsWith(QStringLiteral("AI_EVENT\t"));
            const bool chatEvent = line.startsWith(QStringLiteral("CHAT_EVENT\t"));
            if (aiEvent || chatEvent) {
                if ((aiEvent && !aiEventOverlay)
                    || (chatEvent && !chatIntegrationOverlay)) {
                    return;
                }
                const QJsonObject event = ipcJsonPayload(line);
                const QString target = event
                                           .value(QStringLiteral("character"))
                                           .toString(
                                               event
                                                   .value(QStringLiteral("target_character"))
                                                   .toString())
                                           .trimmed();
                if (!target.isEmpty() && target != characterId) {
                    return;
                }
                const QString state =
                    event.value(QStringLiteral("state")).toString().trimmed().toLower();
                QString action =
                    event.value(QStringLiteral("action")).toString().trimmed();
                if (action.isEmpty() && aiEvent) {
                    if (state == QStringLiteral("thinking")
                        || state == QStringLiteral("tool")) {
                        action = QStringLiteral("thinking");
                    } else if (state == QStringLiteral("error")) {
                        action = QStringLiteral("surprised");
                    } else if (state == QStringLiteral("done")) {
                        action = QStringLiteral("smile");
                    }
                }
                if (!action.isEmpty()) {
                    widget.triggerAction(action, characterId);
                }
                if (state == QStringLiteral("clear")) {
                    ++reminderBubbleGeneration;
                    reminderBubble.hide();
                    return;
                }
                if (!compactAiWindow || !widget.isVisible()) {
                    return;
                }
                const QString title =
                    event.value(QStringLiteral("title")).toString().trimmed();
                QString text = event.value(QStringLiteral("text")).toString().trimmed();
                if (text.isEmpty()) {
                    text = event.value(QStringLiteral("content")).toString().trimmed();
                }
                if (text.isEmpty()) {
                    text = event.value(QStringLiteral("message")).toString().trimmed();
                }
                if (text.isEmpty() && title.isEmpty()) {
                    return;
                }
                if (!title.isEmpty()) {
                    text = text.isEmpty() ? title : title + u'\n' + text;
                }
                reminderBubble.setMaximumWidth(std::max(180, widget.width() - 32));
                reminderBubble.setText(text);
                reminderBubble.adjustSize();
                reminderBubble.move(
                    std::max(8, (widget.width() - reminderBubble.width()) / 2),
                    16);
                reminderBubble.raise();
                reminderBubble.show();
                const int generation = ++reminderBubbleGeneration;
                const int ttl = std::clamp(
                    event.value(QStringLiteral("ttl_ms")).toInt(9'000),
                    1,
                    60'000);
                QTimer::singleShot(
                    ttl,
                    &widget,
                    [&reminderBubble, &reminderBubbleGeneration, generation]() {
                        if (reminderBubbleGeneration == generation) {
                            reminderBubble.hide();
                        }
                    });
                return;
            }
            if (line.startsWith(QStringLiteral("REMINDER_EVENT\t"))) {
                const QJsonObject event = ipcJsonPayload(line);
                const QString target =
                    event.value(QStringLiteral("character")).toString().trimmed();
                if (!target.isEmpty() && target != characterId) {
                    return;
                }
                const QString action =
                    event.value(QStringLiteral("action")).toString().trimmed();
                if (!action.isEmpty()) {
                    widget.triggerAction(action, characterId);
                }
                const QString text = event.value(QStringLiteral("text")).toString().trimmed();
                if (text.isEmpty()) {
                    return;
                }
                if (!compactAiWindow || !widget.isVisible()) {
                    return;
                }
                reminderBubble.setMaximumWidth(std::max(180, widget.width() - 32));
                reminderBubble.setText(text);
                reminderBubble.adjustSize();
                reminderBubble.move(
                    std::max(8, (widget.width() - reminderBubble.width()) / 2),
                    16);
                reminderBubble.raise();
                reminderBubble.show();
                const int generation = ++reminderBubbleGeneration;
                const int ttl = std::clamp(
                    event.value(QStringLiteral("ttl_ms")).toInt(18'000),
                    1'000,
                    60'000);
                QTimer::singleShot(
                    ttl,
                    &widget,
                    [&reminderBubble, &reminderBubbleGeneration, generation]() {
                        if (reminderBubbleGeneration == generation) {
                            reminderBubble.hide();
                        }
                    });
                return;
            }
            if (line.startsWith(QStringLiteral("POKE_USER\t"))) {
                const QJsonObject event = ipcJsonPayload(line);
                const QString target =
                    event.value(QStringLiteral("character")).toString().trimmed();
                if (!target.isEmpty() && target != characterId) {
                    return;
                }
                const QString source =
                    event.value(QStringLiteral("source")).toString().trimmed().toLower();
                if (source == QStringLiteral("live2d")
                    || source == QStringLiteral("pixel")) {
                    return;
                }
                const QString direction =
                    event.value(QStringLiteral("direction")).toString().trimmed().toLower();
                if (direction == QStringLiteral("to_user")) {
                    shakeWindow(widget, 36);
                    return;
                }
                triggerPokeFeedback();
                shakeWindow(widget, 72);
                return;
            }
            if (line.startsWith(QStringLiteral("ACTION\t"))) {
                const QStringList parts = line.split(u'\t');
                if (parts.size() >= 3 && parts.at(1) == characterId) {
                    widget.triggerAction(parts.mid(2).join(u'\t'), characterId);
                } else if (parts.size() == 2) {
                    widget.triggerAction(parts.at(1), characterId);
                }
                return;
            }
            if (line.startsWith(QStringLiteral("EMOTION\t"))) {
                if (!emotionBehavior) {
                    return;
                }
                const QJsonObject behavior = ipcJsonPayload(line);
                const QString target =
                    behavior.value(QStringLiteral("character")).toString().trimmed();
                if (!target.isEmpty() && target != characterId) {
                    return;
                }
                const int intensity =
                    std::clamp(behavior.value(QStringLiteral("intensity")).toInt(64), 20, 100);
                if (!widget.pixelMode()) {
                    const QJsonArray expressions =
                        behavior.value(QStringLiteral("expression_tags")).toArray();
                    for (const QJsonValue& value : expressions) {
                        const QString action = value.toString().trimmed();
                        if (!action.isEmpty()
                            && widget.triggerExpressionTag(
                                action, characterId, 2'600 + intensity * 38)) {
                            break;
                        }
                    }

                    QSet<QString> sourceActions;
                    for (const QJsonValue& value :
                         behavior.value(QStringLiteral("source_actions")).toArray()) {
                        const QString action = value.toString().trimmed().toLower();
                        if (!action.isEmpty()) {
                            sourceActions.insert(action);
                        }
                    }
                    QStringList preferredMotions;
                    QStringList sourceMotions;
                    for (const QJsonValue& value :
                         behavior.value(QStringLiteral("motion_tags")).toArray()) {
                        const QString action = value.toString().trimmed();
                        if (action.isEmpty()) {
                            continue;
                        }
                        if (sourceActions.contains(action.toLower())) {
                            sourceMotions.append(action);
                        } else {
                            preferredMotions.append(action);
                        }
                    }
                    preferredMotions.append(sourceMotions);
                    for (const QString& action : preferredMotions) {
                        if (widget.triggerMotionTag(action, characterId)) {
                            break;
                        }
                    }
                }
                playEmotionWindowFeedback(
                    widget,
                    behavior.value(QStringLiteral("window")).toString(),
                    intensity,
                    widget.dragLocked());
                return;
            }
            if (line.startsWith(QStringLiteral("LIP\t"))) {
                const QStringList parts = line.split(u'\t');
                if (parts.size() < 3 || parts.at(1) != characterId) {
                    return;
                }
                bool levelValid = false;
                bool formValid = true;
                const double level = parts.at(2).toDouble(&levelValid);
                const double form = parts.size() >= 4 ? parts.at(3).toDouble(&formValid) : 0.0;
                if (levelValid && formValid) {
                    widget.setLipSyncPose(level, form);
                }
                return;
            }
            if (!line.startsWith(QStringLiteral("SETTINGS\t"))) {
                return;
            }
            const QByteArray payload = line.mid(9).toUtf8();
            const QJsonDocument document = QJsonDocument::fromJson(payload);
            if (!document.isObject()) {
                return;
            }
            const QJsonObject settings = document.object();
            bool defaultStateChanged = false;
            if (settings.contains(QStringLiteral("fps"))) {
                widget.setFramesPerSecond(settings.value(QStringLiteral("fps")).toInt(120));
            }
            if (settings.contains(QStringLiteral("opacity"))) {
                widget.setWindowOpacity(std::clamp(
                    settings.value(QStringLiteral("opacity")).toDouble(1.0), 0.05, 1.0));
            }
            if (settings.contains(QStringLiteral("game_topmost"))) {
                gameTopmostEnabled =
                    settings.value(QStringLiteral("game_topmost")).toBool(false);
                enforceGameTopmost(widget, gameTopmostEnabled);
            }
            if (settings.contains(QStringLiteral("obs_window_capture_compatible"))) {
                obsCaptureCompatible = settings
                                           .value(QStringLiteral(
                                               "obs_window_capture_compatible"))
                                           .toBool(false);
                applyObsWindowCaptureStyle(widget, obsCaptureCompatible);
            }
            if (settings.contains(QStringLiteral("hide_live2d_model"))) {
                modelHidden =
                    settings.value(QStringLiteral("hide_live2d_model")).toBool(false);
                if (modelHidden) {
                    ++reminderBubbleGeneration;
                    reminderBubble.hide();
                    radialMenu.hide();
                    widget.hide();
                } else if (!widget.isVisible()) {
                    widget.show();
                    applyObsWindowCaptureStyle(widget, obsCaptureCompatible);
                    enforceGameTopmost(widget, gameTopmostEnabled);
                }
            }
            if (settings.contains(QStringLiteral("live2d_lip_sync_max_open"))) {
                widget.setLipSyncMaxOpen(
                    settings.value(QStringLiteral("live2d_lip_sync_max_open")).toDouble(0.55));
            }
            if (settings.contains(QStringLiteral("live2d_hit_alpha_threshold"))) {
                widget.setHitAlphaThreshold(
                    settings.value(QStringLiteral("live2d_hit_alpha_threshold")).toInt(8));
            }
            if (settings.contains(QStringLiteral("live2d_idle_actions_enabled"))) {
                idleActions =
                    settings.value(QStringLiteral("live2d_idle_actions_enabled")).toBool(true);
                defaultStateChanged = true;
            }
            if (settings.contains(QStringLiteral("live2d_random_actions_enabled"))) {
                randomActions =
                    settings.value(QStringLiteral("live2d_random_actions_enabled")).toBool(true);
                defaultStateChanged = true;
            }
            if (settings.contains(QStringLiteral("live2d_scale"))) {
                currentScale = normalizedLive2dScale(
                    settings.value(QStringLiteral("live2d_scale")).toInt(100));
                widget.setLive2dWindowSize(scaledLive2dSize(modelFormat, currentScale));
            }
            if (settings.contains(QStringLiteral("drag_locked"))) {
                const bool locked =
                    settings.value(QStringLiteral("drag_locked")).toBool(false);
                widget.setDragLocked(locked);
                radialMenu.setLocked(locked);
            }
            if (settings.contains(QStringLiteral("move_all_roles_together"))) {
                moveAllRoles =
                    settings.value(QStringLiteral("move_all_roles_together")).toBool(false);
                if (!moveAllRoles) {
                    peerDragStates.clear();
                }
            }
            if (settings.contains(QStringLiteral("live2d_head_tracking_enabled"))) {
                headTracking =
                    settings.value(QStringLiteral("live2d_head_tracking_enabled")).toBool(true);
            }
            if (settings.contains(QStringLiteral("live2d_mutual_gaze_enabled"))) {
                mutualGaze =
                    settings.value(QStringLiteral("live2d_mutual_gaze_enabled")).toBool(false);
                lastPublishedCenterValid = false;
            }
            if (settings.contains(QStringLiteral("emotion_behavior_enabled"))) {
                emotionBehavior =
                    settings.value(QStringLiteral("emotion_behavior_enabled")).toBool(true);
            }
            if (settings.contains(QStringLiteral("compact_ai_window_enabled"))) {
                compactAiWindow =
                    settings.value(QStringLiteral("compact_ai_window_enabled")).toBool(false);
                if (!compactAiWindow) {
                    ++reminderBubbleGeneration;
                    reminderBubble.hide();
                }
            }
            bool compactStyleChanged = false;
            if (settings.contains(QStringLiteral("compact_ai_window_opacity"))) {
                compactOverlayOpacity = std::clamp(
                    settings.value(QStringLiteral("compact_ai_window_opacity")).toInt(44),
                    10,
                    100);
                compactStyleChanged = true;
            }
            if (settings.contains(QStringLiteral("compact_ai_window_font_size"))) {
                compactOverlayFontSize = std::clamp(
                    settings.value(QStringLiteral("compact_ai_window_font_size")).toInt(12),
                    8,
                    36);
                compactStyleChanged = true;
            }
            if (settings.contains(QStringLiteral("compact_ai_window_background_color"))) {
                compactOverlayBackground = normalizedOverlayColor(
                    settings
                        .value(QStringLiteral("compact_ai_window_background_color"))
                        .toString(),
                    QStringLiteral("#fb7299"));
                compactStyleChanged = true;
            }
            if (settings.contains(QStringLiteral("compact_ai_window_text_color"))) {
                compactOverlayForeground = normalizedOverlayColor(
                    settings
                        .value(QStringLiteral("compact_ai_window_text_color"))
                        .toString(),
                    QStringLiteral("#24242a"));
                compactStyleChanged = true;
            }
            if (compactStyleChanged) {
                reminderBubble.setStyleSheet(compactOverlayStyle(
                    compactOverlayOpacity,
                    compactOverlayFontSize,
                    compactOverlayBackground,
                    compactOverlayForeground));
                if (reminderBubble.isVisible()) {
                    reminderBubble.adjustSize();
                    reminderBubble.move(
                        std::max(8, (widget.width() - reminderBubble.width()) / 2),
                        16);
                }
            }
            if (settings.contains(QStringLiteral("ai_event_overlay_enabled"))) {
                aiEventOverlay =
                    settings.value(QStringLiteral("ai_event_overlay_enabled")).toBool(false);
                if (!aiEventOverlay) {
                    ++reminderBubbleGeneration;
                    reminderBubble.hide();
                }
            }
            if (settings.contains(QStringLiteral("chat_integration_overlay_enabled"))) {
                chatIntegrationOverlay = settings
                                             .value(QStringLiteral(
                                                 "chat_integration_overlay_enabled"))
                                             .toBool(true);
                if (!chatIntegrationOverlay) {
                    ++reminderBubbleGeneration;
                    reminderBubble.hide();
                }
            }
            if (settings.contains(QStringLiteral("poke_motion"))) {
                configuredPokeMotion =
                    settings.value(QStringLiteral("poke_motion")).toString().trimmed();
            }
            if (settings.contains(QStringLiteral("poke_expression"))) {
                configuredPokeExpression =
                    settings.value(QStringLiteral("poke_expression")).toString().trimmed();
            }
            if (defaultStateChanged) {
                widget.applyDefaultState(
                    configuredDefaultMotion,
                    configuredDefaultExpression,
                    characterId,
                    idleActions,
                    randomActions);
            }
            if (settings.contains(QStringLiteral("language"))) {
                radialMenu.setLanguage(settings.value(QStringLiteral("language")).toString());
            }
            if (settings.value(QStringLiteral("models")).isArray()) {
                const QJsonArray models = settings.value(QStringLiteral("models")).toArray();
                QJsonObject characterMatch;
                for (const QJsonValue& value : models) {
                    const QJsonObject entry = value.toObject();
                    if (entry.value(QStringLiteral("character")).toString() != characterId) {
                        continue;
                    }
                    if (characterMatch.isEmpty()) {
                        characterMatch = entry;
                    }
                    if (entry.value(QStringLiteral("path")).toString() == modelPath) {
                        characterMatch = entry;
                        break;
                    }
                }
                if (!characterMatch.isEmpty()) {
                    configuredClickActions =
                        characterMatch.value(QStringLiteral("click_motion_actions")).toObject();
                    const bool wantsPixel =
                        characterMatch
                            .value(QStringLiteral("pet_mode"))
                            .toString(QStringLiteral("live2d"))
                            == QStringLiteral("pixel");
                    if (wantsPixel != widget.pixelMode()) {
                        publishPetWindowState(
                            ipcClient, widget, characterId, modelPath);
                        if (widget.setPixelMode(wantsPixel)) {
                            radialMenu.setPixelActive(widget.pixelMode());
                            publishPetWindowState(
                                ipcClient, widget, characterId, modelPath);
                        }
                    }
                }
            }
            widget.setHeadTrackingEnabled(headTracking && !mutualGaze);
            updateMutualGaze();
        });
    QObject::connect(
        &app,
        &QCoreApplication::aboutToQuit,
        &radialMenu,
        &QWidget::hide);
    QObject::connect(
        &app,
        &QCoreApplication::aboutToQuit,
        ipcClient,
        [ipcClient, &widget, characterId, modelPath]() {
            settleWindowShake(widget);
            publishPetWindowState(ipcClient, widget, characterId, modelPath);
        });
    QObject::connect(&app, &QCoreApplication::aboutToQuit, ipcClient, &bandori::PetIpcClient::stop);
    ipcClient->start();
    if (!modelHidden) {
        widget.show();
        applyObsWindowCaptureStyle(widget, obsCaptureCompatible);
        enforceGameTopmost(widget, gameTopmostEnabled);
    }
    return app.exec();
}
