#ifdef _WIN32
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0601
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#endif

#include "native_main_window.h"

#include "native_autostart.h"

#include <QAbstractItemView>
#include <QAction>
#include <QApplication>
#include <QAudioDevice>
#include <QAudioOutput>
#include <QAudioSource>
#include <QBuffer>
#include <QCloseEvent>
#include <QClipboard>
#include <QCursor>
#include <QDate>
#include <QDateTime>
#include <QDebug>
#include <QDir>
#include <QFileDialog>
#include <QFile>
#include <QFileInfo>
#include <QHeaderView>
#include <QHash>
#include <QHBoxLayout>
#include <QImage>
#include <QIcon>
#include <QInputDialog>
#include <QJsonArray>
#include <QJsonDocument>
#include <QKeySequence>
#include <QLineEdit>
#include <QListWidgetItem>
#include <QMap>
#include <QMenu>
#include <QMediaPlayer>
#include <QMediaDevices>
#include <QMessageBox>
#include <QMoveEvent>
#include <QNetworkRequest>
#include <QPainter>
#include <QPixmap>
#include <QRandomGenerator>
#include <QRegularExpression>
#include <QResizeEvent>
#include <QScrollArea>
#include <QScrollBar>
#include <QScreen>
#include <QShortcut>
#include <QSignalBlocker>
#include <QSplitter>
#include <QSystemTrayIcon>
#include <QTemporaryFile>
#include <QTextBrowser>
#include <QTextCursor>
#include <QTableWidget>
#include <QTime>
#include <QVariant>
#include <QVBoxLayout>
#include <QUuid>
#include <QUrl>
#include <QUrlQuery>
#include <QtWebSockets/QWebSocket>

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <utility>
#include <vector>

#ifdef Q_OS_WIN
#include <windows.h>
#endif

namespace bandori {

namespace {

constexpr int kPathRole = Qt::UserRole;
constexpr int kCharacterRole = Qt::UserRole + 1;
constexpr int kCostumeRole = Qt::UserRole + 2;
constexpr int kFormatRole = Qt::UserRole + 3;
constexpr int kReminderKindRole = Qt::UserRole + 10;
constexpr int kReminderIdRole = Qt::UserRole + 11;
constexpr int kReminderEnabledRole = Qt::UserRole + 12;
constexpr int kMemoryIdRole = Qt::UserRole + 20;
constexpr int kMemoryKindRole = Qt::UserRole + 21;
constexpr int kMemoryContentRole = Qt::UserRole + 22;
constexpr int kMemoryImportanceRole = Qt::UserRole + 23;
constexpr int kChatMessagePageSize = 200;
constexpr int kChatMessageLimit = 1000;
constexpr int kMaximumConcurrentNapcatReplies = 4;
constexpr qsizetype kMaximumAsrAudioBytes = 64 * 1024 * 1024;

QByteArray encodeWaveAudio(const QByteArray& pcm, const QAudioFormat& format) {
    if (pcm.isEmpty() || format.sampleRate() <= 0 || format.channelCount() <= 0
        || format.bytesPerSample() <= 0 || format.bytesPerFrame() <= 0
        || pcm.size() > std::numeric_limits<quint32>::max() - 36) {
        return {};
    }
    const bool floatingPoint = format.sampleFormat() == QAudioFormat::Float;
    if (!floatingPoint && format.sampleFormat() != QAudioFormat::UInt8
        && format.sampleFormat() != QAudioFormat::Int16
        && format.sampleFormat() != QAudioFormat::Int32) {
        return {};
    }
    QByteArray wave;
    wave.reserve(pcm.size() + 44);
    auto append16 = [&wave](quint16 value) {
        wave.append(static_cast<char>(value & 0xff));
        wave.append(static_cast<char>((value >> 8) & 0xff));
    };
    auto append32 = [&wave](quint32 value) {
        wave.append(static_cast<char>(value & 0xff));
        wave.append(static_cast<char>((value >> 8) & 0xff));
        wave.append(static_cast<char>((value >> 16) & 0xff));
        wave.append(static_cast<char>((value >> 24) & 0xff));
    };
    wave.append("RIFF", 4);
    append32(static_cast<quint32>(36 + pcm.size()));
    wave.append("WAVEfmt ", 8);
    append32(16);
    append16(floatingPoint ? 3 : 1);
    append16(static_cast<quint16>(format.channelCount()));
    append32(static_cast<quint32>(format.sampleRate()));
    append32(static_cast<quint32>(format.sampleRate() * format.bytesPerFrame()));
    append16(static_cast<quint16>(format.bytesPerFrame()));
    append16(static_cast<quint16>(format.bytesPerSample() * 8));
    wave.append("data", 4);
    append32(static_cast<quint32>(pcm.size()));
    wave.append(pcm);
    return wave;
}

QString currentLocalDateTime() {
    return QDateTime::currentDateTime().toString(QStringLiteral("yyyy-MM-dd'T'HH:mm:ss"));
}

bool isBuiltinClickMotionProfile(const QString& name) {
    static const QSet<QString> names {
        QStringLiteral("auto"),
        QStringLiteral("genki"),
        QStringLiteral("tsundere"),
        QStringLiteral("shy"),
        QStringLiteral("cool"),
        QStringLiteral("surprised"),
        QStringLiteral("random"),
    };
    return names.contains(name);
}

QString repeatDaysLabel(const QJsonArray& source) {
    QList<int> days;
    for (const QJsonValue& value : source) {
        const int day = value.toInt(-1);
        if (day >= 0 && day <= 6 && !days.contains(day)) {
            days.append(day);
        }
    }
    std::sort(days.begin(), days.end());
    if (days.isEmpty()) {
        return QStringLiteral("不重复");
    }
    if (days == QList<int>({0, 1, 2, 3, 4, 5, 6})) {
        return QStringLiteral("每天");
    }
    if (days == QList<int>({0, 1, 2, 3, 4})) {
        return QStringLiteral("工作日");
    }
    if (days == QList<int>({5, 6})) {
        return QStringLiteral("周末");
    }
    const QStringList labels {
        QStringLiteral("周一"),
        QStringLiteral("周二"),
        QStringLiteral("周三"),
        QStringLiteral("周四"),
        QStringLiteral("周五"),
        QStringLiteral("周六"),
        QStringLiteral("周日"),
    };
    QStringList selected;
    for (const int day : days) {
        selected.append(labels.at(day));
    }
    return selected.join(QStringLiteral("、"));
}

QString durationLabel(qint64 seconds) {
    seconds = std::max<qint64>(0, seconds);
    const qint64 hours = seconds / 3600;
    const qint64 minutes = (seconds % 3600) / 60;
    if (hours > 0) {
        return QStringLiteral("%1 h %2 min").arg(hours).arg(minutes);
    }
    if (minutes > 0) {
        return QStringLiteral("%1 min").arg(minutes);
    }
    return seconds > 0 ? QStringLiteral("< 1 min") : QStringLiteral("0 min");
}

QString currentTimeInstruction() {
    const QDateTime now = QDateTime::currentDateTime();
    const int hour = now.time().hour();
    const QString period = hour < 5   ? QStringLiteral("凌晨")
        : hour < 9                    ? QStringLiteral("早上")
        : hour < 12                   ? QStringLiteral("上午")
        : hour < 14                   ? QStringLiteral("中午")
        : hour < 18                   ? QStringLiteral("下午")
                                      : QStringLiteral("晚上");
    return QStringLiteral(
               "当前时间：%1（%2）\n"
               "现在的时间判断只以上面这条为准。历史消息、长期记忆或引用内容里如果提到晚上、"
               "凌晨、昨天等，都只代表当时情境，不代表现在。")
        .arg(now.toString(QStringLiteral("yyyy-MM-dd HH:mm")), period);
}

QString stripActionTags(QString text) {
    static const QRegularExpression pattern(
        QStringLiteral("\\[(?:DONE|[A-Za-z0-9_.\\-]+)\\]"),
        QRegularExpression::CaseInsensitiveOption);
    text.remove(pattern);
    return text.trimmed();
}

QJsonObject parseObject(const QString& json) {
    QJsonParseError error;
    const QJsonDocument document = QJsonDocument::fromJson(json.toUtf8(), &error);
    if (error.error != QJsonParseError::NoError || !document.isObject()) {
        return {};
    }
    return document.object();
}

QJsonArray parseArray(const QString& json) {
    QJsonParseError error;
    const QJsonDocument document = QJsonDocument::fromJson(json.toUtf8(), &error);
    if (error.error != QJsonParseError::NoError || !document.isArray()) {
        return {};
    }
    return document.array();
}

QString formatAttachmentSize(qint64 size) {
    if (size < 0) {
        return {};
    }
    if (size < 1024) {
        return QStringLiteral("%1 B").arg(size);
    }
    if (size < 1024 * 1024) {
        return QStringLiteral("%1 KB").arg(QString::number(size / 1024.0, 'f', 1));
    }
    if (size < 1024LL * 1024 * 1024) {
        return QStringLiteral("%1 MB").arg(QString::number(size / (1024.0 * 1024.0), 'f', 1));
    }
    return QStringLiteral("%1 GB")
        .arg(QString::number(size / (1024.0 * 1024.0 * 1024.0), 'f', 2));
}

QStringList attachmentSummaries(const QString& json) {
    QStringList summaries;
    for (const QJsonValue& value : parseArray(json)) {
        if (!value.isObject()) {
            continue;
        }
        const QJsonObject attachment = value.toObject();
        const QString type = attachment.value(QStringLiteral("type")).toString().trimmed().toLower();
        if (type != QStringLiteral("image") && type != QStringLiteral("file")) {
            continue;
        }
        QString name = attachment.value(QStringLiteral("name")).toString().trimmed();
        if (name.isEmpty()) {
            name = QFileInfo(attachment.value(QStringLiteral("path")).toString()).fileName();
        }
        if (name.isEmpty()) {
            name = QStringLiteral("unnamed attachment");
        }
        const QString size = formatAttachmentSize(
            attachment.value(QStringLiteral("size")).toInteger(-1));
        summaries.append(
            QStringLiteral("  [%1] %2%3")
                .arg(
                    type == QStringLiteral("image") ? QStringLiteral("Image")
                                                     : QStringLiteral("File"),
                    name,
                    size.isEmpty() ? QString() : QStringLiteral(" · ") + size));
    }
    return summaries;
}

QString compactJson(const QJsonObject& object) {
    return QString::fromUtf8(QJsonDocument(object).toJson(QJsonDocument::Compact));
}

QString reminderFallbackText(const QJsonObject& event, QString displayName) {
    if (displayName.trimmed().isEmpty()) {
        displayName = QStringLiteral("BandoriPet");
    }
    const QString description = event.value(QStringLiteral("description")).toString().trimmed();
    const QString kind = event.value(QStringLiteral("kind")).toString();
    if (kind == QStringLiteral("alarm")) {
        const QString purpose = description.isEmpty() ? QStringLiteral("时间到了") : description;
        return QStringLiteral("%1：%2，该准备啦。").arg(displayName, purpose);
    }
    if (kind == QStringLiteral("pomodoro_break")) {
        const QString purpose = description.isEmpty()
            ? QStringLiteral("这轮专注")
            : QStringLiteral("“%1”").arg(description);
        const QString phase = event.value(QStringLiteral("phase")).toString()
                == QStringLiteral("long_break")
            ? QStringLiteral("长休息")
            : QStringLiteral("短休息");
        return QStringLiteral("%1：%2结束了，进入%3。").arg(displayName, purpose, phase);
    }
    if (kind == QStringLiteral("pomodoro_focus")) {
        const QString purpose = description.isEmpty()
            ? QStringLiteral("下一轮")
            : QStringLiteral("“%1”").arg(description);
        return QStringLiteral("%1：休息结束，%2开始专注吧。").arg(displayName, purpose);
    }
    if (kind == QStringLiteral("pomodoro_done")) {
        const QString purpose = description.isEmpty()
            ? QStringLiteral("番茄钟")
            : QStringLiteral("“%1”").arg(description);
        return QStringLiteral("%1：%2完成了，辛苦啦。").arg(displayName, purpose);
    }
    return QStringLiteral("%1：提醒时间到了。").arg(displayName);
}

QString modelTitle(const ModelCatalogItem& model) {
    const QString character =
        model.characterDisplay.isEmpty() ? model.character : model.characterDisplay;
    const QString costume = model.costumeDisplay.isEmpty() ? model.costume : model.costumeDisplay;
    return QStringLiteral("%1 · %2").arg(character, costume);
}

ModelCatalogItem modelFromJson(const QJsonObject& object) {
    return {
        object.value(QStringLiteral("character")).toString(),
        object.value(QStringLiteral("character_display")).toString(),
        object.value(QStringLiteral("costume")).toString(),
        object.value(QStringLiteral("costume_display")).toString(),
        object.value(QStringLiteral("path")).toString(),
        object.value(QStringLiteral("format")).toString(QStringLiteral("moc3")),
        object.value(QStringLiteral("is_default")).toBool(),
    };
}

bool nativeComputerMouseAction(
    const QString& action,
    const QPoint& position,
    const QString& button,
    int delta,
    QString* error) {
    if (action == QStringLiteral("move")) {
        QCursor::setPos(position);
        return true;
    }
#ifdef Q_OS_WIN
    QCursor::setPos(position);
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
#else
    if (error != nullptr) {
        *error = QObject::tr(
            "Global click and scroll injection is unavailable in this native build; screenshot, pointer move, clipboard and wait remain available");
    }
    return false;
#endif
}

#ifdef Q_OS_WIN
WORD nativeComputerVirtualKey(const QString& key) {
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

INPUT nativeComputerKeyInput(WORD key, bool release, bool unicode = false) {
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
#endif

bool nativeComputerTypeText(const QString& text, QString* error) {
#ifdef Q_OS_WIN
    const QString bounded = text.left(2'000);
    std::vector<INPUT> inputs;
    inputs.reserve(static_cast<size_t>(bounded.size()) * 2);
    for (const QChar character : bounded) {
        inputs.push_back(nativeComputerKeyInput(character.unicode(), false, true));
        inputs.push_back(nativeComputerKeyInput(character.unicode(), true, true));
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
    if (error != nullptr) {
        *error = QObject::tr("Windows SendInput could not type the complete text");
    }
    return false;
#else
    Q_UNUSED(text);
    if (error != nullptr) {
        *error = QObject::tr("Global keyboard injection is unavailable in this native build");
    }
    return false;
#endif
}

bool nativeComputerPressKeys(const QString& keys, QString* error) {
#ifdef Q_OS_WIN
    const QStringList parts = keys.toLower().split(
        QRegularExpression(QStringLiteral("\\s*\\+\\s*|\\s+")),
        Qt::SkipEmptyParts);
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
            if (error != nullptr) {
                *error = QObject::tr("A shortcut may contain only one non-modifier key");
            }
            return false;
        }
        mainKey = nativeComputerVirtualKey(part);
    }
    if (mainKey == 0) {
        if (error != nullptr) {
            *error = QObject::tr("The requested key or shortcut is unsupported");
        }
        return false;
    }
    std::vector<INPUT> inputs;
    for (const WORD modifier : modifiers) {
        inputs.push_back(nativeComputerKeyInput(modifier, false));
    }
    inputs.push_back(nativeComputerKeyInput(mainKey, false));
    inputs.push_back(nativeComputerKeyInput(mainKey, true));
    for (auto iterator = modifiers.rbegin(); iterator != modifiers.rend(); ++iterator) {
        inputs.push_back(nativeComputerKeyInput(*iterator, true));
    }
    const UINT sent = SendInput(
        static_cast<UINT>(inputs.size()),
        inputs.data(),
        sizeof(INPUT));
    if (sent == inputs.size()) {
        return true;
    }
    if (error != nullptr) {
        *error = QObject::tr("Windows SendInput could not press the complete shortcut");
    }
    return false;
#else
    Q_UNUSED(keys);
    if (error != nullptr) {
        *error = QObject::tr("Global keyboard injection is unavailable in this native build");
    }
    return false;
#endif
}

}  // namespace

NativeMainWindow::NativeMainWindow(
    QString projectRoot,
    QString userModelsRoot,
    QString dataRoot,
    QString configPath,
    QWidget* parent)
    : qfw::FluentWindow(parent),
      projectRoot_(QDir(std::move(projectRoot)).absolutePath()),
      userModelsRoot_(QDir(std::move(userModelsRoot)).absolutePath()),
      dataRoot_(QDir(std::move(dataRoot)).absolutePath()),
      configPath_(QDir::cleanPath(std::move(configPath))),
      supervisor_(this) {
    chatLayoutSaveTimer_.setSingleShot(true);
    chatLayoutSaveTimer_.setInterval(350);
    connect(&chatLayoutSaveTimer_, &QTimer::timeout, this, [this]() {
        if (chatGroupSplitter_ == nullptr || !isGroupChatMode()) {
            return;
        }
        const QList<int> sizes = chatGroupSplitter_->sizes();
        const int total = std::accumulate(sizes.cbegin(), sizes.cend(), 0);
        if (sizes.size() < 2 || total <= 0) {
            return;
        }
        saveChatPresentationSettings({
            {QStringLiteral("group_chat_sidebar_ratio"),
             std::clamp(static_cast<double>(sizes.first()) / total, 0.18, 0.46)},
        });
    });
    nativeWindowGeometryTimer_.setSingleShot(true);
    nativeWindowGeometryTimer_.setInterval(350);
    connect(
        &nativeWindowGeometryTimer_,
        &QTimer::timeout,
        this,
        [this]() { persistNativeWindowGeometry(); });
    setupUi();
    connect(
        &backend_,
        &Backend::chatStreamEvent,
        this,
        [this](const QString& payloadJson) { handleChatStreamEvent(payloadJson); });
    connect(
        &backend_,
        &Backend::computerToolRequest,
        this,
        [this](qint64 requestId, const QString& toolName, const QString& argumentsJson) {
            handleNativeComputerTool(requestId, toolName, argumentsJson);
        });
    connect(
        &backend_,
        &Backend::computerToolCancel,
        this,
        [this](qint64 requestId) { pendingComputerWaitRequests_.remove(requestId); });
    connect(
        &backend_,
        &Backend::chatMemoryEvent,
        this,
        [this](const QString& payloadJson) { handleChatMemoryEvent(payloadJson); });
    connect(
        &backend_,
        &Backend::providerOperationEvent,
        this,
        [this](const QString& payloadJson) { handleNativeProviderOperation(payloadJson); });
    connect(
        &backend_,
        &Backend::ttsAudioEvent,
        this,
        [this](const QString& payloadJson, const QByteArray& audio) {
            handleNativeTtsAudio(payloadJson, audio);
        });
    connect(
        &backend_,
        &Backend::asrTranscriptionEvent,
        this,
        [this](const QString& payloadJson) { handleNativeAsrEvent(payloadJson); });
    connect(
        &backend_,
        &Backend::screenAwarenessEvent,
        this,
        [this](const QString& payloadJson) {
            handleNativeScreenAwarenessEvent(payloadJson);
        });
    connect(
        &backend_,
        &Backend::integrationEvent,
        this,
        [this](const QString& payloadJson) {
            handleNativeIntegrationEvent(payloadJson);
        });
    connect(
        &backend_,
        &Backend::napcatReplyEvent,
        this,
        [this](const QString& payloadJson) { handleNativeNapcatReply(payloadJson); });
    napcatReconnectTimer_.setSingleShot(true);
    napcatReconnectTimer_.setInterval(3'000);
    connect(&napcatReconnectTimer_, &QTimer::timeout, this, [this]() {
        connectNativeNapcat();
    });
    screenAwarenessTimer_.setSingleShot(true);
    connect(&screenAwarenessTimer_, &QTimer::timeout, this, [this]() {
        triggerNativeScreenAwareness(false);
    });
    specialEventTimer_.setSingleShot(true);
    connect(&specialEventTimer_, &QTimer::timeout, this, [this]() {
        pollNativeSpecialEvents();
    });
    reloadBackendState();
    restoreNativeWindowGeometry();
    setupTray();
    QTimer::singleShot(0, this, [this]() { pollNativeSpecialEvents(); });
    reminderTimer_.setInterval(15'000);
    connect(&reminderTimer_, &QTimer::timeout, this, [this]() { pollNativeReminders(); });
    reminderTimer_.start();
    QTimer::singleShot(1'200, this, [this]() { pollNativeReminders(); });

    connect(
        &supervisor_,
        &PetProcessSupervisor::statusChanged,
        this,
        [this](const QString& status) {
            rendererStatusLabel_->setText(status);
            runtimeCard_->setContent(status);
            restartButton_->setEnabled(!activeSpecs_.isEmpty());
            stopButton_->setEnabled(supervisor_.isRunning());
            if (startTrayAction_ != nullptr) {
                startTrayAction_->setEnabled(!supervisor_.isRunning());
                stopTrayAction_->setEnabled(supervisor_.isRunning());
            }
        });
    connect(
        &supervisor_,
        &PetProcessSupervisor::rendererLog,
        this,
        [](const QString& message) { qWarning().noquote() << message; });
    connect(
        &supervisor_,
        &PetProcessSupervisor::controlRequest,
        this,
        [this](const QString& line) {
            if (line.startsWith(QStringLiteral("OPEN_SETTINGS\tcostumes\t"))) {
                if (QWidget* models = findChild<QWidget*>(QStringLiteral("modelsPage"))) {
                    switchTo(models);
                }
            } else if (line.startsWith(QStringLiteral("OPEN_CHAT_NATIVE\t"))) {
                const qsizetype separator = line.indexOf(u'\t');
                const QJsonObject request = parseObject(line.mid(separator + 1));
                openNativeChat(request.value(QStringLiteral("character")).toString());
            }
        });
}

void NativeMainWindow::setupTray() {
    const QString iconPath = QDir(projectRoot_).filePath(QStringLiteral("logo.ico"));
    const QIcon icon(iconPath);
    if (!icon.isNull()) {
        setWindowIcon(icon);
        QApplication::setWindowIcon(icon);
    }
    if (!QSystemTrayIcon::isSystemTrayAvailable()) {
        return;
    }

    trayIcon_ = new QSystemTrayIcon(icon.isNull() ? windowIcon() : icon, this);
    trayIcon_->setToolTip(QStringLiteral("BandoriPet Rust + Qt"));
    auto* menu = new QMenu(this);
    QAction* openAction = menu->addAction(tr("Open control center"));
    startTrayAction_ = menu->addAction(tr("Start configured pets"));
    stopTrayAction_ = menu->addAction(tr("Stop active pets"));
    menu->addSeparator();
    QAction* quitAction = menu->addAction(tr("Exit BandoriPet"));
    trayIcon_->setContextMenu(menu);
    stopTrayAction_->setEnabled(supervisor_.isRunning());

    connect(openAction, &QAction::triggered, this, [this]() { showControlCenter(); });
    connect(startTrayAction_, &QAction::triggered, this, [this]() {
        startConfiguredPets();
    });
    connect(stopTrayAction_, &QAction::triggered, &supervisor_, &PetProcessSupervisor::stop);
    connect(quitAction, &QAction::triggered, this, [this]() { quitFromTray(); });
    connect(
        trayIcon_,
        &QSystemTrayIcon::activated,
        this,
        [this](QSystemTrayIcon::ActivationReason reason) {
            if (reason == QSystemTrayIcon::Trigger
                || reason == QSystemTrayIcon::DoubleClick) {
                showControlCenter();
            }
        });
    connect(QApplication::instance(), &QCoreApplication::aboutToQuit, this, [this]() {
        if (trayIcon_ != nullptr) {
            trayIcon_->hide();
        }
    });
    trayIcon_->show();
}

void NativeMainWindow::showControlCenter() {
    showNormal();
    raise();
    activateWindow();
}

void NativeMainWindow::applyChatWindowPolicy() {
    const bool alwaysOnTop = runtime_
                                 .value(QStringLiteral("chat_window_always_on_top"))
                                 .toBool(false);
    if (windowFlags().testFlag(Qt::WindowStaysOnTopHint) == alwaysOnTop) {
        return;
    }
    const bool wasVisible = isVisible();
    setWindowFlag(Qt::WindowStaysOnTopHint, alwaysOnTop);
    if (wasVisible) {
        showControlCenter();
    }
}

void NativeMainWindow::quitFromTray() {
    if (exitRequested_) {
        return;
    }
    exitRequested_ = true;
    nativeWindowGeometryTimer_.stop();
    persistNativeWindowGeometry();
    stopNativeTts();
    stopNativeAsr();
    stopNativeScreenAwareness();
    stopNativeIntegrationServices();
    specialEventTimer_.stop();
    clearPendingChatAttachments();
    if (trayIcon_ != nullptr) {
        trayIcon_->hide();
    }
    const bool waitForPets = supervisor_.isRunning();
    supervisor_.stop();
    QTimer::singleShot(waitForPets ? 700 : 0, QApplication::instance(), []() {
        QCoreApplication::quit();
    });
}

void NativeMainWindow::closeEvent(QCloseEvent* event) {
    nativeWindowGeometryTimer_.stop();
    persistNativeWindowGeometry();
    if (!exitRequested_ && trayIcon_ != nullptr && trayIcon_->isVisible()) {
        event->ignore();
        hide();
        if (!trayHintShown_) {
            trayHintShown_ = true;
            trayIcon_->showMessage(
                tr("BandoriPet is still running"),
                tr("Use the tray icon to restore the control center or exit."),
                QSystemTrayIcon::Information,
                2'500);
        }
        return;
    }
    clearPendingChatAttachments();
    stopNativeTts();
    stopNativeAsr();
    stopNativeScreenAwareness();
    stopNativeIntegrationServices();
    specialEventTimer_.stop();
    qfw::FluentWindow::closeEvent(event);
    if (trayIcon_ == nullptr) {
        QCoreApplication::quit();
    }
}

void NativeMainWindow::moveEvent(QMoveEvent* event) {
    qfw::FluentWindow::moveEvent(event);
    scheduleNativeWindowGeometrySave();
}

void NativeMainWindow::resizeEvent(QResizeEvent* event) {
    qfw::FluentWindow::resizeEvent(event);
    scheduleNativeWindowGeometrySave();
}

void NativeMainWindow::setupUi() {
    setWindowTitle(QStringLiteral("BandoriPet Rust + Qt"));
    resize(920, 640);
    setMinimumSize(760, 520);

    QWidget* dashboard = createDashboardPage();
    QWidget* models = createModelsPage();
    chatPage_ = createChatPage();
    QWidget* history = createHistorySearchPage();
    QWidget* statistics = createStatisticsPage();
    QWidget* dataManagement = createDataManagementPage();
    QWidget* memory = createMemoryPage();
    QWidget* userProfiles = createUserProfilesPage();
    QWidget* personas = createPersonaPage();
    QWidget* llmSettings = createLlmSettingsPage();
    QWidget* ttsSettings = createTtsSettingsPage();
    QWidget* asrSettings = createAsrSettingsPage();
    QWidget* screenAwareness = createScreenAwarenessPage();
    QWidget* integrations = createIntegrationPage();
    QWidget* settings = createSettingsPage();
    dashboard->setObjectName(QStringLiteral("dashboardPage"));
    models->setObjectName(QStringLiteral("modelsPage"));
    chatPage_->setObjectName(QStringLiteral("chatPage"));
    history->setObjectName(QStringLiteral("historySearchPage"));
    statistics->setObjectName(QStringLiteral("statisticsPage"));
    dataManagement->setObjectName(QStringLiteral("dataManagementPage"));
    memory->setObjectName(QStringLiteral("memoryPage"));
    userProfiles->setObjectName(QStringLiteral("userProfilesPage"));
    personas->setObjectName(QStringLiteral("personasPage"));
    llmSettings->setObjectName(QStringLiteral("llmSettingsPage"));
    ttsSettings->setObjectName(QStringLiteral("ttsSettingsPage"));
    asrSettings->setObjectName(QStringLiteral("asrSettingsPage"));
    screenAwareness->setObjectName(QStringLiteral("screenAwarenessPage"));
    integrations->setObjectName(QStringLiteral("integrationsPage"));
    settings->setObjectName(QStringLiteral("settingsPage"));
    addSubInterface(dashboard, qfw::FluentIconEnum::Home, tr("Overview"));
    addSubInterface(models, qfw::FluentIconEnum::People, tr("Models"));
    addSubInterface(chatPage_, qfw::FluentIconEnum::Chat, tr("Chat history"));
    addSubInterface(history, qfw::FluentIconEnum::Search, tr("History search"));
    addSubInterface(statistics, qfw::FluentIconEnum::Market, tr("Statistics"));
    addSubInterface(dataManagement, qfw::FluentIconEnum::Folder, tr("Data management"));
    addSubInterface(memory, qfw::FluentIconEnum::LibraryFill, tr("Memory"));
    addSubInterface(userProfiles, qfw::FluentIconEnum::Person, tr("User profiles"));
    addSubInterface(personas, qfw::FluentIconEnum::Heart, tr("Personas"));
    addSubInterface(llmSettings, qfw::FluentIconEnum::Robot, tr("LLM settings"));
    addSubInterface(ttsSettings, qfw::FluentIconEnum::Volume, tr("TTS settings"));
    addSubInterface(asrSettings, qfw::FluentIconEnum::Microphone, tr("ASR voice input"));
    addSubInterface(
        screenAwareness,
        qfw::FluentIconEnum::View,
        tr("Screen awareness"));
    addSubInterface(
        integrations,
        qfw::FluentIconEnum::Code,
        tr("Local integrations"));
    addSubInterface(
        settings,
        qfw::FluentIconEnum::Setting,
        tr("Settings"),
        qfw::NavigationItemPosition::Bottom);
}

QWidget* NativeMainWindow::createDashboardPage() {
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    layout->setContentsMargins(40, 52, 40, 40);
    layout->setSpacing(14);

    auto* title = new qfw::TitleLabel(QStringLiteral("BandoriPet Rust + Qt"), page);
    serviceStatusLabel_ = new qfw::BodyLabel(QStringLiteral("Loading Rust services…"), page);
    configSummaryLabel_ = new qfw::CaptionLabel(page);
    rendererStatusLabel_ =
        new qfw::CaptionLabel(QStringLiteral("Pet renderer is not started"), page);
    startConfiguredButton_ =
        new qfw::PrimaryPushButton(tr("Start configured pets"), page);
    restartButton_ = new qfw::PushButton(tr("Restart active pets"), page);
    stopButton_ = new qfw::PushButton(tr("Stop active pets"), page);
    auto* reloadButton = new qfw::PushButton(tr("Reload configuration and models"), page);

    auto* buttons = new QHBoxLayout();
    buttons->setSpacing(10);
    buttons->addWidget(startConfiguredButton_);
    buttons->addWidget(restartButton_);
    buttons->addWidget(stopButton_);
    buttons->addWidget(reloadButton);
    buttons->addStretch(1);

    layout->addWidget(title);
    layout->addWidget(serviceStatusLabel_);
    layout->addWidget(configSummaryLabel_);
    layout->addSpacing(10);
    layout->addWidget(rendererStatusLabel_);
    layout->addLayout(buttons);
    layout->addStretch(1);

    restartButton_->setEnabled(false);
    stopButton_->setEnabled(false);
    connect(startConfiguredButton_, &QPushButton::clicked, this, [this]() {
        startConfiguredPets();
    });
    connect(restartButton_, &QPushButton::clicked, this, [this]() {
        if (!activeSpecs_.isEmpty()) {
            supervisor_.startAll(activeSpecs_);
        }
    });
    connect(stopButton_, &QPushButton::clicked, &supervisor_, &PetProcessSupervisor::stop);
    connect(reloadButton, &QPushButton::clicked, this, [this]() { reloadBackendState(); });
    return page;
}

QWidget* NativeMainWindow::createModelsPage() {
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    layout->setContentsMargins(40, 52, 40, 40);
    layout->setSpacing(12);

    auto* title = new qfw::TitleLabel(tr("Available pet models"), page);
    modelCountLabel_ = new qfw::CaptionLabel(page);
    modelList_ = new qfw::ListWidget(page);
    modelList_->setSelectionMode(QAbstractItemView::SingleSelection);
    modelList_->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    modelDetailsLabel_ = new qfw::BodyLabel(tr("Select a costume to inspect it"), page);
    modelDetailsLabel_->setWordWrap(true);
    auto* clickProfiles = new qfw::GroupHeaderCardWidget(tr("Click behavior profile"), page);
    auto* profileSelector = new QWidget(clickProfiles);
    auto* profileSelectorLayout = new QHBoxLayout(profileSelector);
    profileSelectorLayout->setContentsMargins(0, 0, 0, 0);
    profileSelectorLayout->setSpacing(8);
    clickMotionProfileComboBox_ = new qfw::ComboBox(profileSelector);
    clickMotionProfileComboBox_->setMinimumWidth(220);
    clickMotionApplyButton_ = new qfw::PushButton(tr("Apply to selected costume"), profileSelector);
    profileSelectorLayout->addWidget(clickMotionProfileComboBox_, 1);
    profileSelectorLayout->addWidget(clickMotionApplyButton_);

    auto* customProfileEditor = new QWidget(clickProfiles);
    auto* customProfileLayout = new QHBoxLayout(customProfileEditor);
    customProfileLayout->setContentsMargins(0, 0, 0, 0);
    customProfileLayout->setSpacing(8);
    clickMotionProfileNameEdit_ = new qfw::LineEdit(customProfileEditor);
    clickMotionProfileNameEdit_->setPlaceholderText(tr("Custom profile name"));
    clickMotionProfileNameEdit_->setMaxLength(80);
    clickMotionSaveButton_ = new qfw::PushButton(tr("Save current"), customProfileEditor);
    clickMotionDeleteButton_ = new qfw::PushButton(tr("Delete custom"), customProfileEditor);
    customProfileLayout->addWidget(clickMotionProfileNameEdit_, 1);
    customProfileLayout->addWidget(clickMotionSaveButton_);
    customProfileLayout->addWidget(clickMotionDeleteButton_);
    clickMotionStatusLabel_ = new qfw::CaptionLabel(
        tr("Choose a configured costume to manage click feedback"), clickProfiles);
    clickMotionStatusLabel_->setWordWrap(true);
    clickProfiles->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Play),
        tr("Active profile"),
        tr("Built-in presets are resolved against this model's motions and expressions in Rust"),
        profileSelector);
    clickProfiles->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Save),
        tr("Custom profiles"),
        tr("Save the selected costume's current click map or remove a custom profile"),
        customProfileEditor);
    clickProfiles->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Info),
        tr("Profile status"),
        tr("Running pets receive the updated map through the shared Rust IPC session"),
        clickMotionStatusLabel_);
    launchSelectedButton_ = new qfw::PrimaryPushButton(tr("Start selected model"), page);
    auto* reloadButton = new qfw::PushButton(tr("Rescan models"), page);

    auto* buttons = new QHBoxLayout();
    buttons->setSpacing(10);
    buttons->addWidget(launchSelectedButton_);
    buttons->addWidget(reloadButton);
    buttons->addStretch(1);

    layout->addWidget(title);
    layout->addWidget(modelCountLabel_);
    layout->addWidget(modelList_, 1);
    layout->addWidget(modelDetailsLabel_);
    layout->addWidget(clickProfiles);
    layout->addLayout(buttons);

    launchSelectedButton_->setEnabled(false);
    connect(
        modelList_,
        &QListWidget::currentItemChanged,
        this,
        [this](QListWidgetItem*, QListWidgetItem*) { updateModelDetails(); });
    connect(launchSelectedButton_, &QPushButton::clicked, this, [this]() { startSelectedPet(); });
    connect(
        clickMotionProfileComboBox_,
        &qfw::ComboBox::currentIndexChanged,
        this,
        [this](int) { syncClickMotionProfileControls(); });
    connect(clickMotionApplyButton_, &QPushButton::clicked, this, [this]() {
        applySelectedClickMotionProfile();
    });
    connect(clickMotionSaveButton_, &QPushButton::clicked, this, [this]() {
        saveCurrentClickMotionProfile();
    });
    connect(clickMotionDeleteButton_, &QPushButton::clicked, this, [this]() {
        deleteSelectedClickMotionProfile();
    });
    connect(reloadButton, &QPushButton::clicked, this, [this]() { reloadBackendState(); });
    return page;
}

QWidget* NativeMainWindow::createChatPage() {
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    layout->setContentsMargins(40, 42, 40, 40);
    layout->setSpacing(12);

    auto* title = new qfw::TitleLabel(tr("Native chat"), page);
    auto* explanation = new qfw::CaptionLabel(
        tr("Rust owns private/group prompts, safe attachments, cancellable speaker streams, transactional data.db history, web/MCP tools and permission-gated Computer Use."),
        page);
    explanation->setWordWrap(true);
    chatModeComboBox_ = new qfw::ComboBox(page);
    chatModeComboBox_->addItem(tr("Private"), QVariant(), QStringLiteral("private"));
    chatModeComboBox_->addItem(tr("Group"), QVariant(), QStringLiteral("group"));
    chatPrivateSelector_ = new QWidget(page);
    auto* privateSelectorLayout = new QHBoxLayout(chatPrivateSelector_);
    privateSelectorLayout->setContentsMargins(0, 0, 0, 0);
    privateSelectorLayout->setSpacing(8);
    privateSelectorLayout->addWidget(new qfw::BodyLabel(tr("Character"), chatPrivateSelector_));
    chatCharacterComboBox_ = new qfw::ComboBox(chatPrivateSelector_);
    chatCharacterComboBox_->setMinimumWidth(160);
    privateSelectorLayout->addWidget(chatCharacterComboBox_);

    chatGroupSelector_ = new QWidget(page);
    chatGroupSelector_->setMinimumWidth(180);
    chatGroupSelector_->setMaximumWidth(460);
    auto* groupSelectorLayout = new QVBoxLayout(chatGroupSelector_);
    groupSelectorLayout->setContentsMargins(0, 0, 0, 0);
    groupSelectorLayout->setSpacing(6);
    auto* savedGroupRow = new QHBoxLayout();
    savedGroupRow->setSpacing(8);
    savedGroupRow->addWidget(new qfw::BodyLabel(tr("Saved group"), chatGroupSelector_));
    chatGroupComboBox_ = new qfw::ComboBox(chatGroupSelector_);
    chatGroupComboBox_->setMinimumWidth(260);
    savedGroupRow->addWidget(chatGroupComboBox_, 1);
    groupSelectorLayout->addLayout(savedGroupRow);
    groupSelectorLayout->addWidget(new qfw::CaptionLabel(
        tr("Members · select at least two characters"), chatGroupSelector_));
    chatGroupMembersList_ = new qfw::ListWidget(chatGroupSelector_);
    chatGroupMembersList_->setSelectionMode(QAbstractItemView::MultiSelection);
    chatGroupMembersList_->setMaximumHeight(112);
    groupSelectorLayout->addWidget(chatGroupMembersList_);
    chatGroupSelector_->setVisible(false);

    chatConversationComboBox_ = new qfw::ComboBox(page);
    chatConversationComboBox_->setMinimumWidth(280);
    chatRefreshButton_ = new qfw::PushButton(tr("Refresh"), page);
    chatPinButton_ = new qfw::PushButton(tr("Pin chat"), page);
    chatRenameButton_ = new qfw::PushButton(tr("Rename"), page);
    chatAvatarButton_ = new qfw::PushButton(tr("Avatar"), page);
    chatResetAvatarButton_ = new qfw::PushButton(tr("Reset avatar"), page);
    chatGroupSidebarToggleButton_ = new qfw::PushButton(tr("Hide members"), page);
    chatNewConversationButton_ = new qfw::PushButton(tr("New"), page);
    chatDeleteConversationButton_ = new qfw::PushButton(tr("Delete"), page);
    chatLoadOlderButton_ = new qfw::PushButton(tr("Load older"), page);
    chatLoadOlderButton_->setEnabled(false);
    auto* controls = new QHBoxLayout();
    controls->addWidget(new qfw::BodyLabel(tr("Mode"), page));
    controls->addWidget(chatModeComboBox_);
    controls->addWidget(chatPrivateSelector_);
    controls->addSpacing(8);
    controls->addWidget(new qfw::BodyLabel(tr("Conversation"), page));
    controls->addWidget(chatConversationComboBox_, 1);
    controls->addWidget(chatLoadOlderButton_);
    controls->addWidget(chatNewConversationButton_);
    controls->addWidget(chatDeleteConversationButton_);
    controls->addWidget(chatRefreshButton_);
    auto* presentationControls = new QHBoxLayout();
    presentationControls->setSpacing(8);
    presentationControls->addWidget(chatPinButton_);
    presentationControls->addWidget(chatRenameButton_);
    presentationControls->addWidget(chatAvatarButton_);
    presentationControls->addWidget(chatResetAvatarButton_);
    presentationControls->addWidget(chatGroupSidebarToggleButton_);
    presentationControls->addStretch(1);

    chatStatusLabel_ = new qfw::CaptionLabel(tr("Choose a character to load chat history"), page);
    chatTranscript_ = new QTextBrowser(page);
    chatTranscript_->setOpenExternalLinks(false);
    chatTranscript_->setReadOnly(true);
    chatInput_ = new qfw::PlainTextEdit(page);
    chatInput_->setPlaceholderText(tr("Write a message · Ctrl+Enter to send"));
    chatInput_->setMinimumHeight(72);
    chatInput_->setMaximumHeight(120);
    chatSendButton_ = new qfw::PrimaryPushButton(tr("Send"), page);
    chatCancelButton_ = new qfw::PushButton(tr("Cancel"), page);
    chatAttachButton_ = new qfw::PushButton(tr("Attach"), page);
    chatAsrButton_ = new qfw::PushButton(tr("Voice"), page);
    chatClearAttachmentsButton_ = new qfw::PushButton(tr("Clear attachments"), page);
    chatAttachmentLabel_ = new qfw::CaptionLabel(tr("No pending attachments"), page);
    chatAttachmentLabel_->setWordWrap(true);
    chatSendButton_->setEnabled(false);
    chatCancelButton_->setEnabled(false);
    auto* composerButtons = new QVBoxLayout();
    composerButtons->setSpacing(8);
    composerButtons->addWidget(chatSendButton_);
    composerButtons->addWidget(chatCancelButton_);
    composerButtons->addStretch(1);
    auto* attachmentControls = new QHBoxLayout();
    attachmentControls->setSpacing(8);
    attachmentControls->addWidget(chatAsrButton_);
    attachmentControls->addWidget(chatAttachButton_);
    attachmentControls->addWidget(chatClearAttachmentsButton_);
    attachmentControls->addWidget(chatAttachmentLabel_, 1);
    auto* composer = new QHBoxLayout();
    composer->setSpacing(10);
    composer->addWidget(chatInput_, 1);
    composer->addLayout(composerButtons);

    auto* conversationPane = new QWidget(page);
    auto* conversationLayout = new QVBoxLayout(conversationPane);
    conversationLayout->setContentsMargins(0, 0, 0, 0);
    conversationLayout->setSpacing(10);
    conversationLayout->addWidget(chatStatusLabel_);
    conversationLayout->addWidget(chatTranscript_, 1);
    conversationLayout->addLayout(attachmentControls);
    conversationLayout->addLayout(composer);
    chatGroupSplitter_ = new QSplitter(Qt::Horizontal, page);
    chatGroupSplitter_->setChildrenCollapsible(false);
    chatGroupSplitter_->addWidget(chatGroupSelector_);
    chatGroupSplitter_->addWidget(conversationPane);
    chatGroupSplitter_->setStretchFactor(0, 0);
    chatGroupSplitter_->setStretchFactor(1, 1);

    layout->addWidget(title);
    layout->addWidget(explanation);
    layout->addLayout(controls);
    layout->addLayout(presentationControls);
    layout->addWidget(chatGroupSplitter_, 1);

    connect(chatRefreshButton_, &QPushButton::clicked, this, [this]() {
        refreshChatState(chatConversationComboBox_->currentData().toString());
    });
    connect(chatPinButton_, &QPushButton::clicked, this, [this]() {
        toggleCurrentChatPin();
    });
    connect(chatRenameButton_, &QPushButton::clicked, this, [this]() {
        renameCurrentPrivateChat();
    });
    connect(chatAvatarButton_, &QPushButton::clicked, this, [this]() {
        chooseCurrentChatAvatar();
    });
    connect(chatResetAvatarButton_, &QPushButton::clicked, this, [this]() {
        resetCurrentChatAvatar();
    });
    connect(chatGroupSidebarToggleButton_, &QPushButton::clicked, this, [this]() {
        toggleGroupChatSidebar();
    });
    connect(chatGroupSplitter_, &QSplitter::splitterMoved, this, [this](int, int) {
        scheduleGroupChatLayoutSave();
    });
    connect(
        chatNewConversationButton_,
        &QPushButton::clicked,
        this,
        [this]() { startNewChatConversation(); });
    connect(
        chatDeleteConversationButton_,
        &QPushButton::clicked,
        this,
        [this]() { deleteSelectedChatConversation(); });
    connect(chatLoadOlderButton_, &QPushButton::clicked, this, [this]() {
        chatMessageLimit_ = std::min(chatMessageLimit_ + kChatMessagePageSize, kChatMessageLimit);
        refreshChatState(chatConversationComboBox_->currentData().toString());
    });
    connect(
        chatModeComboBox_,
        &qfw::ComboBox::currentIndexChanged,
        this,
        [this](int) {
            if (updatingChatControls_) {
                return;
            }
            const bool group = isGroupChatMode();
            chatPrivateSelector_->setVisible(!group);
            syncChatPresentationControls();
            refreshChatState({}, true);
        });
    connect(
        chatCharacterComboBox_,
        &qfw::ComboBox::currentIndexChanged,
        this,
        [this](int) {
            if (!updatingChatControls_) {
                refreshChatState({}, true);
            }
        });
    connect(
        chatGroupComboBox_,
        &qfw::ComboBox::currentIndexChanged,
        this,
        [this](int) {
            if (updatingChatControls_) {
                return;
            }
            const QString groupKey = chatGroupComboBox_->currentData().toString();
            if (!groupKey.isEmpty()) {
                selectGroupKeyMembers(groupKey);
                refreshChatState({}, true);
            }
        });
    connect(
        chatGroupMembersList_,
        &QListWidget::itemSelectionChanged,
        this,
        [this]() {
            if (!updatingChatControls_ && selectedGroupMembers().size() >= 2) {
                refreshChatState({}, true);
            } else {
                setChatBusy(activeChatRequestId_ != 0 || groupSequenceActive_);
            }
        });
    connect(
        chatConversationComboBox_,
        &qfw::ComboBox::currentIndexChanged,
        this,
        [this](int) {
            if (!updatingChatControls_) {
                refreshChatState(chatConversationComboBox_->currentData().toString(), true);
            }
        });
    connect(chatInput_, &QPlainTextEdit::textChanged, this, [this]() {
        setChatBusy(activeChatRequestId_ != 0);
    });
    connect(chatSendButton_, &QPushButton::clicked, this, [this]() { sendNativeChat(); });
    connect(chatCancelButton_, &QPushButton::clicked, this, [this]() { cancelNativeChat(); });
    connect(chatAttachButton_, &QPushButton::clicked, this, [this]() { chooseChatAttachments(); });
    connect(chatAsrButton_, &QPushButton::clicked, this, [this]() {
        toggleNativeAsrRecording(false);
    });
    connect(
        chatClearAttachmentsButton_,
        &QPushButton::clicked,
        this,
        [this]() { clearPendingChatAttachments(); });
    auto* sendShortcut = new QShortcut(QKeySequence(QStringLiteral("Ctrl+Return")), chatInput_);
    connect(sendShortcut, &QShortcut::activated, this, [this]() { sendNativeChat(); });
    updatePendingChatAttachments();
    syncChatPresentationControls();
    return page;
}

QWidget* NativeMainWindow::createHistorySearchPage() {
    auto* page = new QWidget(this);
    auto* layout = new QVBoxLayout(page);
    layout->setContentsMargins(40, 34, 40, 40);
    layout->setSpacing(16);

    auto* title = new qfw::TitleLabel(tr("Search all chat history"), page);
    auto* subtitle = new qfw::BodyLabel(
        tr("Search private and group messages through one Rust-owned query with bounded filters and pagination."),
        page);
    subtitle->setWordWrap(true);
    auto* filters = new qfw::GroupHeaderCardWidget(tr("History filters"), page);

    historyKeywordEdit_ = new qfw::LineEdit(filters);
    historyKeywordEdit_->setPlaceholderText(tr("Message keyword (literal matching)"));
    historySearchButton_ = new qfw::PrimaryPushButton(tr("Search"), filters);
    historyResetButton_ = new qfw::PushButton(tr("Reset"), filters);
    auto* keywordEditor = new QWidget(filters);
    auto* keywordLayout = new QHBoxLayout(keywordEditor);
    keywordLayout->setContentsMargins(0, 0, 0, 0);
    keywordLayout->setSpacing(8);
    keywordLayout->addWidget(historyKeywordEdit_, 1);
    keywordLayout->addWidget(historySearchButton_);
    keywordLayout->addWidget(historyResetButton_);

    historyDateFromEdit_ = new qfw::LineEdit(filters);
    historyDateToEdit_ = new qfw::LineEdit(filters);
    historyDateFromEdit_->setPlaceholderText(QStringLiteral("yyyy-MM-dd"));
    historyDateToEdit_->setPlaceholderText(QStringLiteral("yyyy-MM-dd"));
    historyDateFromEdit_->setMaxLength(10);
    historyDateToEdit_->setMaxLength(10);
    auto* dateEditor = new QWidget(filters);
    auto* dateLayout = new QHBoxLayout(dateEditor);
    dateLayout->setContentsMargins(0, 0, 0, 0);
    dateLayout->setSpacing(8);
    dateLayout->addWidget(historyDateFromEdit_);
    dateLayout->addWidget(new qfw::CaptionLabel(tr("through"), dateEditor));
    dateLayout->addWidget(historyDateToEdit_);

    historyCharacterComboBox_ = new qfw::ComboBox(filters);
    historyUserComboBox_ = new qfw::ComboBox(filters);
    historyRoleComboBox_ = new qfw::ComboBox(filters);
    historyRoleComboBox_->addItem(tr("All speakers"), QVariant(), QString());
    historyRoleComboBox_->addItem(tr("User"), QVariant(), QStringLiteral("user"));
    historyRoleComboBox_->addItem(tr("Character"), QVariant(), QStringLiteral("assistant"));
    historyRoleComboBox_->addItem(tr("System"), QVariant(), QStringLiteral("system"));
    historySourceComboBox_ = new qfw::ComboBox(filters);
    historySourceComboBox_->addItem(tr("Private and group chats"), QVariant(), QString());
    historySourceComboBox_->addItem(tr("Private chats"), QVariant(), QStringLiteral("private"));
    historySourceComboBox_->addItem(tr("Group chats"), QVariant(), QStringLiteral("group"));

    filters->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Search),
        tr("Keyword"),
        tr("Percent and underscore are treated as literal characters"),
        keywordEditor);
    filters->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Calendar),
        tr("Date range"),
        tr("Leave both fields blank to search every date"),
        dateEditor);
    filters->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::People),
        tr("Character"),
        tr("Group chats match any member in the canonical group key"),
        historyCharacterComboBox_);
    filters->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Person),
        tr("User partition"),
        tr("Includes normal user profiles and role-POV partitions found in the database"),
        historyUserComboBox_);
    filters->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Chat),
        tr("Speaker"),
        tr("Filter user, character, or system messages"),
        historyRoleComboBox_);
    filters->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Document),
        tr("Chat type"),
        tr("Search private chats, group chats, or both"),
        historySourceComboBox_);

    historyList_ = new qfw::ListWidget(page);
    historyList_->setSelectionMode(QAbstractItemView::NoSelection);
    historyList_->setWordWrap(true);
    historyList_->setAlternatingRowColors(false);
    historyLoadMoreButton_ = new qfw::PushButton(tr("Load more"), page);
    historyStatusLabel_ = new qfw::CaptionLabel(tr("History filters have not loaded"), page);
    auto* resultActions = new QWidget(page);
    auto* resultActionsLayout = new QHBoxLayout(resultActions);
    resultActionsLayout->setContentsMargins(0, 0, 0, 0);
    resultActionsLayout->setSpacing(8);
    resultActionsLayout->addWidget(historyStatusLabel_, 1);
    resultActionsLayout->addWidget(historyLoadMoreButton_);

    layout->addWidget(title);
    layout->addWidget(subtitle);
    layout->addWidget(filters);
    layout->addWidget(historyList_, 1);
    layout->addWidget(resultActions);

    connect(historySearchButton_, &QPushButton::clicked, this, [this]() {
        searchNativeHistory(false);
    });
    connect(historyResetButton_, &QPushButton::clicked, this, [this]() {
        resetNativeHistoryFilters();
    });
    connect(historyLoadMoreButton_, &QPushButton::clicked, this, [this]() {
        searchNativeHistory(true);
    });
    connect(historyKeywordEdit_, &QLineEdit::returnPressed, this, [this]() {
        searchNativeHistory(false);
    });
    historyLoadMoreButton_->setEnabled(false);
    return page;
}

QWidget* NativeMainWindow::createStatisticsPage() {
    auto* page = new qfw::ScrollArea(this);
    auto* content = new QWidget(page);
    auto* layout = new QVBoxLayout(content);
    layout->setContentsMargins(40, 34, 40, 40);
    layout->setSpacing(24);

    auto* title = new qfw::TitleLabel(tr("Native statistics"), content);
    auto* subtitle = new qfw::BodyLabel(
        tr("Relationship trends and message activity are scoped to the selected user partition; overview usage remains application-wide."),
        content);
    subtitle->setWordWrap(true);

    auto* filters = new qfw::GroupHeaderCardWidget(tr("Statistics filters"), content);
    statisticsRangeComboBox_ = new qfw::ComboBox(filters);
    statisticsRangeComboBox_->addItem(tr("Last 7 days"), QVariant(), 7);
    statisticsRangeComboBox_->addItem(tr("Last 30 days"), QVariant(), 30);
    statisticsRangeComboBox_->addItem(tr("All time"), QVariant(), 0);
    statisticsRangeComboBox_->setCurrentIndex(1);
    statisticsCharacterComboBox_ = new qfw::ComboBox(filters);
    statisticsRefreshButton_ = new qfw::PushButton(tr("Refresh"), filters);
    statisticsStatusLabel_ = new qfw::CaptionLabel(tr("Statistics have not loaded"), filters);
    auto* statisticsActions = new QWidget(filters);
    auto* statisticsActionsLayout = new QHBoxLayout(statisticsActions);
    statisticsActionsLayout->setContentsMargins(0, 0, 0, 0);
    statisticsActionsLayout->setSpacing(8);
    statisticsActionsLayout->addWidget(statisticsStatusLabel_, 1);
    statisticsActionsLayout->addWidget(statisticsRefreshButton_);
    filters->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::DateTime),
        tr("Time range"),
        tr("All-time mode uses the latest 30 days for daily messages and 14 days for usage"),
        statisticsRangeComboBox_);
    filters->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::People),
        tr("Relationship character"),
        tr("Only the relationship trend uses this character selector"),
        statisticsCharacterComboBox_);
    filters->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Sync),
        tr("Refresh snapshot"),
        tr("Reads the current active user or role-POV partition from Rust runtime state"),
        statisticsActions);

    auto* overview = new qfw::GroupHeaderCardWidget(tr("Overview"), content);
    statisticsMessagesLabel_ = new qfw::BodyLabel(overview);
    statisticsUsageTodayLabel_ = new qfw::BodyLabel(overview);
    statisticsUsageWeekLabel_ = new qfw::BodyLabel(overview);
    statisticsUsageAllLabel_ = new qfw::BodyLabel(overview);
    overview->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Chat),
        tr("Messages"),
        tr("Private and group messages across the database"),
        statisticsMessagesLabel_);
    overview->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Clock),
        tr("Usage today"),
        tr("Tracked application usage for today"),
        statisticsUsageTodayLabel_);
    overview->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Calendar),
        tr("Usage this week"),
        tr("Tracked application usage over the last seven days"),
        statisticsUsageWeekLabel_);
    overview->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::History),
        tr("Usage all time"),
        tr("All completed and active usage sessions"),
        statisticsUsageAllLabel_);

    auto setupTable = [](qfw::TableWidget* table, const QStringList& headers, int height) {
        table->setColumnCount(headers.size());
        table->setHorizontalHeaderLabels(headers);
        table->setEditTriggers(QAbstractItemView::NoEditTriggers);
        table->setSelectionMode(QAbstractItemView::NoSelection);
        table->setAlternatingRowColors(true);
        table->setMinimumHeight(height);
        table->horizontalHeader()->setStretchLastSection(true);
        table->verticalHeader()->setVisible(false);
    };

    auto* relationship = new qfw::GroupHeaderCardWidget(tr("Relationship trend"), content);
    statisticsRelationshipTable_ = new qfw::TableWidget(relationship);
    setupTable(
        statisticsRelationshipTable_,
        {tr("Time"), tr("Affection"), tr("Trust"), tr("Familiarity")},
        210);
    relationship->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Heart),
        tr("Relationship events"),
        tr("Latest saved state per day, capped to the most recent 366 days"),
        statisticsRelationshipTable_);

    auto* messages = new qfw::GroupHeaderCardWidget(tr("Message activity"), content);
    statisticsCharacterTable_ = new qfw::TableWidget(messages);
    setupTable(statisticsCharacterTable_, {tr("Character"), tr("Messages")}, 220);
    statisticsDailyTable_ = new qfw::TableWidget(messages);
    setupTable(
        statisticsDailyTable_,
        {tr("Date"), tr("Messages"), tr("Usage")},
        260);
    messages->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::People),
        tr("Messages per character"),
        tr("Group assistant messages are attributed to the detected speaker"),
        statisticsCharacterTable_);
    messages->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Market),
        tr("Daily activity"),
        tr("Message count and tracked usage by day"),
        statisticsDailyTable_);

    auto* heatmap = new qfw::GroupHeaderCardWidget(tr("Seven-day hourly heatmap"), content);
    statisticsHeatmapTable_ = new qfw::TableWidget(heatmap);
    QStringList hourLabels;
    for (int hour = 0; hour < 24; ++hour) {
        hourLabels.append(QString::number(hour));
    }
    setupTable(statisticsHeatmapTable_, hourLabels, 250);
    statisticsHeatmapTable_->verticalHeader()->setVisible(true);
    statisticsHeatmapTable_->horizontalHeader()->setSectionResizeMode(QHeaderView::ResizeToContents);
    heatmap->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::DateTime),
        tr("Messages by weekday and hour"),
        tr("Rows use Monday through Sunday; columns use local hour 0 through 23"),
        statisticsHeatmapTable_);

    layout->addWidget(title);
    layout->addWidget(subtitle);
    layout->addWidget(filters);
    layout->addWidget(overview);
    layout->addWidget(relationship);
    layout->addWidget(messages);
    layout->addWidget(heatmap);
    layout->addStretch(1);
    content->setMinimumWidth(680);
    page->setWidget(content);
    page->setWidgetResizable(true);
    page->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);

    connect(statisticsRangeComboBox_, &qfw::ComboBox::currentIndexChanged, this, [this](int) {
        refreshNativeStatistics();
    });
    connect(
        statisticsCharacterComboBox_,
        &qfw::ComboBox::currentIndexChanged,
        this,
        [this](int) { refreshNativeStatistics(); });
    connect(statisticsRefreshButton_, &QPushButton::clicked, this, [this]() {
        refreshNativeStatistics();
    });
    return page;
}

QWidget* NativeMainWindow::createDataManagementPage() {
    auto* page = new qfw::ScrollArea(this);
    auto* content = new QWidget(page);
    auto* layout = new QVBoxLayout(content);
    layout->setContentsMargins(40, 34, 40, 40);
    layout->setSpacing(24);

    auto* title = new qfw::TitleLabel(tr("Native data management"), content);
    auto* subtitle = new qfw::BodyLabel(
        tr("Move whitelisted settings and relationship memory between installations, or create and restore a complete chat database backup."),
        content);
    subtitle->setWordWrap(true);

    auto* packageCard =
        new qfw::GroupHeaderCardWidget(tr("Portable settings package"), content);
    dataCategoryComboBox_ = new qfw::ComboBox(packageCard);
    const QList<QPair<QString, QString>> categories {
        {tr("All migratable settings"), QStringLiteral("all")},
        {tr("Live2D models and actions"), QStringLiteral("live2d_models")},
        {tr("Click motion profiles"), QStringLiteral("click_motion_profiles")},
        {tr("LLM settings"), QStringLiteral("llm")},
        {tr("TTS settings"), QStringLiteral("tts")},
        {tr("ASR settings"), QStringLiteral("asr")},
        {tr("POV settings"), QStringLiteral("pov")},
        {tr("Character personas"), QStringLiteral("character_persona")},
        {tr("Relationship and memory"), QStringLiteral("relationship")},
        {tr("Reminders"), QStringLiteral("reminders")},
        {tr("Screen awareness"), QStringLiteral("screen_awareness")},
        {tr("Compact window"), QStringLiteral("compact_window")},
        {tr("Chat integrations"), QStringLiteral("chat_integration")},
        {tr("MCP and computer use"), QStringLiteral("mcp_computer")},
        {tr("Quality and miscellaneous"), QStringLiteral("misc")},
    };
    for (const auto& category : categories) {
        dataCategoryComboBox_->addItem(category.first, QVariant(), category.second);
    }
    auto* packageActions = new QWidget(packageCard);
    auto* packageActionsLayout = new QHBoxLayout(packageActions);
    packageActionsLayout->setContentsMargins(0, 0, 0, 0);
    packageActionsLayout->setSpacing(8);
    dataExportButton_ = new qfw::PrimaryPushButton(tr("Export JSON"), packageActions);
    dataImportButton_ = new qfw::PushButton(tr("Import JSON"), packageActions);
    packageActionsLayout->addWidget(dataExportButton_);
    packageActionsLayout->addWidget(dataImportButton_);
    packageActionsLayout->addStretch(1);
    packageCard->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Document),
        tr("Data category"),
        tr("Choose one category or export every migratable section"),
        dataCategoryComboBox_);
    packageCard->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Save),
        tr("Import or export package"),
        tr("API keys, ASR keys, status tokens and chat integration tokens are never exported or overwritten"),
        packageActions);

    auto* databaseCard =
        new qfw::GroupHeaderCardWidget(tr("Complete chat database"), content);
    auto* databaseActions = new QWidget(databaseCard);
    auto* databaseActionsLayout = new QHBoxLayout(databaseActions);
    databaseActionsLayout->setContentsMargins(0, 0, 0, 0);
    databaseActionsLayout->setSpacing(8);
    databaseExportButton_ = new qfw::PushButton(tr("Create backup"), databaseActions);
    databaseImportButton_ = new qfw::PushButton(tr("Restore backup"), databaseActions);
    databaseActionsLayout->addWidget(databaseExportButton_);
    databaseActionsLayout->addWidget(databaseImportButton_);
    databaseActionsLayout->addStretch(1);
    databaseCard->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::SaveCopy),
        tr("SQLite backup"),
        tr("Includes private chats, group chats, relationships, memories and usage history"),
        databaseActions);
    databaseCard->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::History),
        tr("Restore safety"),
        tr("Restore replaces the current database, requires confirmation and is blocked while a chat response is active"),
        new qfw::BodyLabel(tr("Keep a recent backup before restoring."), databaseCard));

    auto* attachmentCard =
        new qfw::GroupHeaderCardWidget(tr("Chat attachment files"), content);
    auto* attachmentPolicy = new QWidget(attachmentCard);
    auto* attachmentPolicyLayout = new QHBoxLayout(attachmentPolicy);
    attachmentPolicyLayout->setContentsMargins(0, 0, 0, 0);
    attachmentPolicyLayout->setSpacing(8);
    attachmentAutoCleanupSwitch_ = new qfw::SwitchButton(attachmentPolicy);
    attachmentRetentionDaysSpinBox_ = new qfw::SpinBox(attachmentPolicy);
    attachmentRetentionDaysSpinBox_->setRange(1, 3650);
    attachmentRetentionDaysSpinBox_->setSuffix(tr(" days"));
    attachmentRetentionDaysSpinBox_->setValue(30);
    attachmentSavePolicyButton_ = new qfw::PushButton(tr("Save policy"), attachmentPolicy);
    attachmentPolicyLayout->addWidget(attachmentAutoCleanupSwitch_);
    attachmentPolicyLayout->addWidget(attachmentRetentionDaysSpinBox_);
    attachmentPolicyLayout->addWidget(attachmentSavePolicyButton_);
    attachmentPolicyLayout->addStretch(1);

    auto* attachmentActions = new QWidget(attachmentCard);
    auto* attachmentActionsLayout = new QHBoxLayout(attachmentActions);
    attachmentActionsLayout->setContentsMargins(0, 0, 0, 0);
    attachmentActionsLayout->setSpacing(8);
    attachmentStatsLabel_ = new qfw::BodyLabel(tr("Loading attachment statistics…"), attachmentActions);
    attachmentRefreshButton_ = new qfw::PushButton(tr("Refresh"), attachmentActions);
    attachmentCleanupOldButton_ = new qfw::PushButton(tr("Clean expired"), attachmentActions);
    attachmentClearAllButton_ = new qfw::PushButton(tr("Clear all"), attachmentActions);
    attachmentActionsLayout->addWidget(attachmentStatsLabel_, 1);
    attachmentActionsLayout->addWidget(attachmentRefreshButton_);
    attachmentActionsLayout->addWidget(attachmentCleanupOldButton_);
    attachmentActionsLayout->addWidget(attachmentClearAllButton_);
    attachmentCard->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::History),
        tr("Automatic retention"),
        tr("When enabled, Rust removes files older than the selected age at native startup and after saving this policy"),
        attachmentPolicy);
    attachmentCard->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Broom),
        tr("Storage cleanup"),
        tr("Cleanup is scoped to chat_attachments beside data.db and removes broken database references"),
        attachmentActions);

    auto* statusCard = new qfw::GroupHeaderCardWidget(tr("Last operation"), content);
    dataStatusLabel_ = new qfw::CaptionLabel(tr("No data operation has run"), statusCard);
    dataStatusLabel_->setWordWrap(true);
    statusCard->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Info),
        tr("Status"),
        tr("Rust validates package format, size, category and field ownership"),
        dataStatusLabel_);

    layout->addWidget(title);
    layout->addWidget(subtitle);
    layout->addWidget(packageCard);
    layout->addWidget(databaseCard);
    layout->addWidget(attachmentCard);
    layout->addWidget(statusCard);
    layout->addStretch(1);
    content->setMinimumWidth(620);
    page->setWidget(content);
    page->setWidgetResizable(true);
    page->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);

    connect(dataExportButton_, &QPushButton::clicked, this, [this]() {
        exportNativeSettingsPackage();
    });
    connect(dataImportButton_, &QPushButton::clicked, this, [this]() {
        importNativeSettingsPackage();
    });
    connect(databaseExportButton_, &QPushButton::clicked, this, [this]() {
        exportNativeChatDatabase();
    });
    connect(databaseImportButton_, &QPushButton::clicked, this, [this]() {
        importNativeChatDatabase();
    });
    connect(attachmentSavePolicyButton_, &QPushButton::clicked, this, [this]() {
        saveNativeAttachmentSettings();
    });
    connect(attachmentRefreshButton_, &QPushButton::clicked, this, [this]() {
        refreshNativeAttachmentStats();
    });
    connect(attachmentCleanupOldButton_, &QPushButton::clicked, this, [this]() {
        cleanupNativeChatAttachments(false);
    });
    connect(attachmentClearAllButton_, &QPushButton::clicked, this, [this]() {
        cleanupNativeChatAttachments(true);
    });
    return page;
}

QWidget* NativeMainWindow::createMemoryPage() {
    auto* page = new qfw::ScrollArea(this);
    auto* content = new QWidget(page);
    auto* layout = new QVBoxLayout(content);
    layout->setContentsMargins(40, 34, 40, 40);
    layout->setSpacing(24);

    auto* title = new qfw::TitleLabel(tr("Relationship and long-term memory"), content);
    auto* subtitle = new qfw::BodyLabel(
        tr("Every operation stays inside the selected character and active user profile."),
        content);
    subtitle->setWordWrap(true);

    auto* target = new qfw::GroupHeaderCardWidget(tr("Memory target"), content);
    memoryCharacterComboBox_ = new qfw::ComboBox(target);
    memoryCharacterComboBox_->setMinimumWidth(280);
    target->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::People),
        tr("Character or global profile"),
        tr("Global memories describe the user and apply to every character"),
        memoryCharacterComboBox_);

    auto* relationship = new qfw::GroupHeaderCardWidget(tr("Relationship state"), content);
    memoryRelationshipCard_ = relationship;
    memoryAffectionLabel_ = new qfw::BodyLabel(relationship);
    memoryTrustLabel_ = new qfw::BodyLabel(relationship);
    memoryFamiliarityLabel_ = new qfw::BodyLabel(relationship);
    memoryMoodLabel_ = new qfw::BodyLabel(relationship);
    relationship->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Heart),
        tr("Affection"),
        tr("Character relationship score from 0 to 100"),
        memoryAffectionLabel_);
    relationship->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Certificate),
        tr("Trust"),
        tr("Accumulated conversational trust"),
        memoryTrustLabel_);
    relationship->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::History),
        tr("Familiarity"),
        tr("How well the character knows this user profile"),
        memoryFamiliarityLabel_);
    relationship->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::EmojiTabSymbols),
        tr("Mood"),
        tr("Current relationship mood and intensity"),
        memoryMoodLabel_);

    auto* memories = new qfw::GroupHeaderCardWidget(tr("Long-term memories"), content);
    memoryList_ = new qfw::ListWidget(memories);
    memoryList_->setSelectionMode(QAbstractItemView::ExtendedSelection);
    memoryList_->setMinimumHeight(230);

    auto* editor = new QWidget(memories);
    auto* editorLayout = new QVBoxLayout(editor);
    editorLayout->setContentsMargins(0, 0, 0, 0);
    editorLayout->setSpacing(8);
    auto* metadataRow = new QHBoxLayout();
    metadataRow->setContentsMargins(0, 0, 0, 0);
    metadataRow->setSpacing(8);
    memoryKindComboBox_ = new qfw::ComboBox(editor);
    memoryKindComboBox_->addItem(tr("Manual"), QVariant(), QStringLiteral("manual"));
    memoryKindComboBox_->addItem(tr("Favorite quote"), QVariant(), QStringLiteral("favorite"));
    memoryKindComboBox_->addItem(tr("User profile"), QVariant(), QStringLiteral("profile"));
    memoryKindComboBox_->addItem(tr("Preference"), QVariant(), QStringLiteral("preference"));
    memoryKindComboBox_->addItem(
        tr("Relationship fact"), QVariant(), QStringLiteral("relationship"));
    memoryKindComboBox_->addItem(tr("Note"), QVariant(), QStringLiteral("note"));
    memoryKindComboBox_->setFixedWidth(180);
    memoryImportanceSpinBox_ = new qfw::SpinBox(editor);
    memoryImportanceSpinBox_->setRange(1, 100);
    memoryImportanceSpinBox_->setValue(70);
    memoryImportanceSpinBox_->setPrefix(tr("Importance "));
    memoryImportanceSpinBox_->setFixedWidth(150);
    metadataRow->addWidget(memoryKindComboBox_);
    metadataRow->addWidget(memoryImportanceSpinBox_);
    metadataRow->addStretch(1);
    memoryContentEdit_ = new qfw::PlainTextEdit(editor);
    memoryContentEdit_->setPlaceholderText(tr("Durable fact, preference, boundary, or favorite quote"));
    memoryContentEdit_->setMinimumHeight(90);
    memoryContentEdit_->setMaximumHeight(150);
    editorLayout->addLayout(metadataRow);
    editorLayout->addWidget(memoryContentEdit_);

    auto* actions = new QWidget(memories);
    auto* actionsLayout = new QHBoxLayout(actions);
    actionsLayout->setContentsMargins(0, 0, 0, 0);
    actionsLayout->setSpacing(8);
    memoryStatusLabel_ = new qfw::CaptionLabel(tr("Select a target to load memories"), actions);
    memoryNewButton_ = new qfw::PushButton(tr("New"), actions);
    memorySaveButton_ = new qfw::PrimaryPushButton(tr("Save"), actions);
    memoryDeleteButton_ = new qfw::PushButton(tr("Delete selected"), actions);
    actionsLayout->addWidget(memoryStatusLabel_, 1);
    actionsLayout->addWidget(memoryNewButton_);
    actionsLayout->addWidget(memorySaveButton_);
    actionsLayout->addWidget(memoryDeleteButton_);

    memories->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::LibraryFill),
        tr("Saved memories"),
        tr("Ordered by importance and update time; Ctrl/Shift selects multiple rows"),
        memoryList_);
    memories->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Edit),
        tr("Memory editor"),
        tr("Editing is scoped to the selected character and current user"),
        editor);
    memories->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Save),
        tr("Actions"),
        tr("Deletion requires an explicit selection"),
        actions);

    layout->addWidget(title);
    layout->addWidget(subtitle);
    layout->addWidget(target);
    layout->addWidget(relationship);
    layout->addWidget(memories);
    layout->addStretch(1);
    content->setMinimumWidth(600);
    page->setWidget(content);
    page->setWidgetResizable(true);
    page->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);

    connect(
        memoryCharacterComboBox_,
        &qfw::ComboBox::currentIndexChanged,
        this,
        [this](int) {
            if (!updatingMemoryControls_) {
                refreshNativeMemoryState();
            }
        });
    connect(
        memoryList_,
        &QListWidget::currentItemChanged,
        this,
        [this](QListWidgetItem*, QListWidgetItem*) { loadSelectedNativeMemory(); });
    connect(
        memoryList_,
        &QListWidget::itemSelectionChanged,
        this,
        [this]() {
            memoryDeleteButton_->setEnabled(!memoryList_->selectedItems().isEmpty());
        });
    connect(memoryNewButton_, &QPushButton::clicked, this, [this]() {
        startNewNativeMemory();
    });
    connect(memorySaveButton_, &QPushButton::clicked, this, [this]() {
        saveNativeMemory();
    });
    connect(memoryDeleteButton_, &QPushButton::clicked, this, [this]() {
        deleteSelectedNativeMemories();
    });
    memoryDeleteButton_->setEnabled(false);
    return page;
}

QWidget* NativeMainWindow::createUserProfilesPage() {
    auto* page = new qfw::ScrollArea(this);
    auto* content = new QWidget(page);
    auto* layout = new QVBoxLayout(content);
    layout->setContentsMargins(40, 34, 40, 40);
    layout->setSpacing(24);

    auto* title = new qfw::TitleLabel(tr("User profiles"), content);
    auto* subtitle = new qfw::BodyLabel(
        tr("Each profile owns a separate private chat, group chat, relationship, and memory partition."),
        content);
    subtitle->setWordWrap(true);

    auto* profiles = new qfw::GroupHeaderCardWidget(tr("Profile identity"), content);
    userProfileComboBox_ = new qfw::ComboBox(profiles);
    userProfileComboBox_->setMinimumWidth(280);
    userProfileNameEdit_ = new qfw::LineEdit(profiles);
    userProfileNameEdit_->setPlaceholderText(tr("Display name"));
    userProfileColorEdit_ = new qfw::LineEdit(profiles);
    userProfileColorEdit_->setPlaceholderText(QStringLiteral("#e4004f"));
    userProfileColorEdit_->setMaxLength(7);
    userProfileColorEdit_->setFixedWidth(120);

    auto* avatarEditor = new QWidget(profiles);
    auto* avatarLayout = new QHBoxLayout(avatarEditor);
    avatarLayout->setContentsMargins(0, 0, 0, 0);
    avatarLayout->setSpacing(8);
    userProfileAvatarPathEdit_ = new qfw::LineEdit(avatarEditor);
    userProfileAvatarPathEdit_->setPlaceholderText(tr("Optional avatar image path"));
    userProfileChooseAvatarButton_ = new qfw::PushButton(tr("Choose image"), avatarEditor);
    avatarLayout->addWidget(userProfileAvatarPathEdit_, 1);
    avatarLayout->addWidget(userProfileChooseAvatarButton_);

    profiles->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::People),
        tr("Saved profile"),
        tr("Selecting previews a profile; activation is explicit"),
        userProfileComboBox_);
    profiles->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Person),
        tr("Display name"),
        tr("Used as the user's name in compatible prompts and chat UI"),
        userProfileNameEdit_);
    profiles->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Palette),
        tr("Avatar color"),
        tr("Six-digit #RRGGBB color"),
        userProfileColorEdit_);
    profiles->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Photo),
        tr("Avatar image"),
        tr("Optional local image retained for chat-surface compatibility"),
        avatarEditor);

    auto* actions = new qfw::GroupHeaderCardWidget(tr("Profile actions"), content);
    auto* actionEditor = new QWidget(actions);
    auto* actionLayout = new QHBoxLayout(actionEditor);
    actionLayout->setContentsMargins(0, 0, 0, 0);
    actionLayout->setSpacing(8);
    userProfileStatusLabel_ = new qfw::CaptionLabel(tr("Loading profiles"), actionEditor);
    userProfileActivateButton_ = new qfw::PushButton(tr("Set current"), actionEditor);
    userProfileNewButton_ = new qfw::PushButton(tr("Create new"), actionEditor);
    userProfileSaveButton_ = new qfw::PrimaryPushButton(tr("Save selected"), actionEditor);
    userProfileDeleteButton_ = new qfw::PushButton(tr("Delete"), actionEditor);
    actionLayout->addWidget(userProfileStatusLabel_, 1);
    actionLayout->addWidget(userProfileActivateButton_);
    actionLayout->addWidget(userProfileNewButton_);
    actionLayout->addWidget(userProfileSaveButton_);
    actionLayout->addWidget(userProfileDeleteButton_);
    actions->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Save),
        tr("Manage profiles"),
        tr("Changing the current profile refreshes chat and memory ownership immediately"),
        actionEditor);

    layout->addWidget(title);
    layout->addWidget(subtitle);
    layout->addWidget(profiles);
    layout->addWidget(actions);
    layout->addStretch(1);
    content->setMinimumWidth(600);
    page->setWidget(content);
    page->setWidgetResizable(true);
    page->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);

    connect(
        userProfileComboBox_,
        &qfw::ComboBox::currentIndexChanged,
        this,
        [this](int) {
            if (!updatingUserProfileControls_) {
                loadSelectedNativeUserProfile();
            }
        });
    connect(
        userProfileChooseAvatarButton_,
        &QPushButton::clicked,
        this,
        [this]() { chooseNativeUserAvatar(); });
    connect(
        userProfileActivateButton_,
        &QPushButton::clicked,
        this,
        [this]() { activateSelectedNativeUserProfile(); });
    connect(userProfileNewButton_, &QPushButton::clicked, this, [this]() {
        createNativeUserProfile();
    });
    connect(userProfileSaveButton_, &QPushButton::clicked, this, [this]() {
        saveSelectedNativeUserProfile();
    });
    connect(userProfileDeleteButton_, &QPushButton::clicked, this, [this]() {
        deleteSelectedNativeUserProfile();
    });
    return page;
}

QWidget* NativeMainWindow::createPersonaPage() {
    auto* page = new qfw::ScrollArea(this);
    auto* content = new QWidget(page);
    auto* layout = new QVBoxLayout(content);
    layout->setContentsMargins(40, 34, 40, 40);
    layout->setSpacing(24);

    auto* title = new qfw::TitleLabel(tr("POV and character personas"), content);
    auto* subtitle = new qfw::BodyLabel(
        tr("Rust owns preset normalization, activation and atomic persistence. Character personas replace the default characters-directory dossier."),
        content);
    subtitle->setWordWrap(true);

    auto* pov = new qfw::GroupHeaderCardWidget(tr("User point of view"), content);
    povModeComboBox_ = new qfw::ComboBox(pov);
    povModeComboBox_->addItem(tr("Off"), QVariant(), QStringLiteral("off"));
    povModeComboBox_->addItem(tr("Who I am (custom prompt)"), QVariant(), QStringLiteral("custom"));
    povModeComboBox_->addItem(tr("Character POV"), QVariant(), QStringLiteral("role"));
    povCustomPromptEdit_ = new qfw::PlainTextEdit(pov);
    povCustomPromptEdit_->setPlaceholderText(
        tr("Describe who the user is, their background, and how the character should understand them."));
    povCustomPromptEdit_->setFixedHeight(96);
    povPersonaComboBox_ = new qfw::ComboBox(pov);
    povSavePersonaButton_ = new qfw::PushButton(tr("Save preset"), pov);
    povDeletePersonaButton_ = new qfw::PushButton(tr("Delete preset"), pov);
    auto* povPresetEditor = new QWidget(pov);
    auto* povPresetLayout = new QHBoxLayout(povPresetEditor);
    povPresetLayout->setContentsMargins(0, 0, 0, 0);
    povPresetLayout->setSpacing(8);
    povPresetLayout->addWidget(povPersonaComboBox_, 1);
    povPresetLayout->addWidget(povSavePersonaButton_);
    povPresetLayout->addWidget(povDeletePersonaButton_);
    povRoleCharacterComboBox_ = new qfw::ComboBox(pov);
    povSaveButton_ = new qfw::PrimaryPushButton(tr("Save POV settings"), pov);
    personaStatusLabel_ = new qfw::CaptionLabel(tr("Loading persona settings"), pov);
    auto* povActions = new QWidget(pov);
    auto* povActionsLayout = new QHBoxLayout(povActions);
    povActionsLayout->setContentsMargins(0, 0, 0, 0);
    povActionsLayout->setSpacing(8);
    povActionsLayout->addWidget(personaStatusLabel_, 1);
    povActionsLayout->addWidget(povSaveButton_);
    pov->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::View),
        tr("POV mode"),
        tr("Choose whether the user is unnamed, custom-defined, or role-playing a character"),
        povModeComboBox_);
    pov->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Edit),
        tr("Custom user prompt"),
        tr("Used only by custom POV mode"),
        povCustomPromptEdit_);
    pov->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Save),
        tr("Saved custom POV presets"),
        tr("Selecting a preset fills the editor; Save POV settings applies the mode"),
        povPresetEditor);
    pov->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::People),
        tr("Role character"),
        tr("The character dossier is injected as the user-side role without replacing the assistant identity"),
        povRoleCharacterComboBox_);
    pov->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Save),
        tr("Apply POV"),
        tr("New chat requests read the saved mode immediately"),
        povActions);

    auto* character = new qfw::GroupHeaderCardWidget(tr("Character persona presets"), content);
    characterPersonaCharacterComboBox_ = new qfw::ComboBox(character);
    characterPersonaPresetComboBox_ = new qfw::ComboBox(character);
    characterPersonaImportButton_ = new qfw::PushButton(tr("Import documents"), character);
    auto* characterPresetEditor = new QWidget(character);
    auto* characterPresetLayout = new QHBoxLayout(characterPresetEditor);
    characterPresetLayout->setContentsMargins(0, 0, 0, 0);
    characterPresetLayout->setSpacing(8);
    characterPresetLayout->addWidget(characterPersonaPresetComboBox_, 1);
    characterPresetLayout->addWidget(characterPersonaImportButton_);
    characterPersonaTitleEdit_ = new qfw::LineEdit(character);
    characterPersonaTitleEdit_->setPlaceholderText(tr("Preset name (derived from the first line when blank)"));
    characterPersonaPromptEdit_ = new qfw::PlainTextEdit(character);
    characterPersonaPromptEdit_->setPlaceholderText(
        tr("Describe this character's personality, history, speech style, and behavior rules."));
    characterPersonaPromptEdit_->setMinimumHeight(180);
    characterPersonaDefaultPreview_ = new qfw::PlainTextEdit(character);
    characterPersonaDefaultPreview_->setReadOnly(true);
    characterPersonaDefaultPreview_->setMinimumHeight(110);
    characterPersonaDefaultPreview_->setPlaceholderText(
        tr("No characters-directory Markdown dossier is available for this character."));
    characterPersonaSaveNewButton_ = new qfw::PushButton(tr("Save as new"), character);
    characterPersonaSaveButton_ = new qfw::PrimaryPushButton(tr("Save and activate"), character);
    characterPersonaDeleteButton_ = new qfw::PushButton(tr("Delete preset"), character);
    auto* characterActions = new QWidget(character);
    auto* characterActionsLayout = new QHBoxLayout(characterActions);
    characterActionsLayout->setContentsMargins(0, 0, 0, 0);
    characterActionsLayout->setSpacing(8);
    characterActionsLayout->addWidget(characterPersonaSaveNewButton_);
    characterActionsLayout->addWidget(characterPersonaSaveButton_);
    characterActionsLayout->addWidget(characterPersonaDeleteButton_);
    characterActionsLayout->addStretch(1);
    character->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::People),
        tr("Character"),
        tr("Each character owns an independent preset list"),
        characterPersonaCharacterComboBox_);
    character->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Document),
        tr("Active preset"),
        tr("Selecting Use default restores the characters-directory persona"),
        characterPresetEditor);
    character->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Edit),
        tr("Preset name"),
        tr("A short label for the preset list"),
        characterPersonaTitleEdit_);
    character->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Edit),
        tr("Persona prompt"),
        tr("An active custom prompt replaces the default dossier"),
        characterPersonaPromptEdit_);
    character->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Document),
        tr("Default persona preview"),
        tr("Read-only Markdown loaded by Rust from the characters directory"),
        characterPersonaDefaultPreview_);
    character->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Save),
        tr("Preset actions"),
        tr("Saving always activates the resulting preset; deleting an active preset falls back to default"),
        characterActions);

    layout->addWidget(title);
    layout->addWidget(subtitle);
    layout->addWidget(pov);
    layout->addWidget(character);
    layout->addStretch(1);
    content->setMinimumWidth(620);
    page->setWidget(content);
    page->setWidgetResizable(true);
    page->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);

    connect(povModeComboBox_, &qfw::ComboBox::currentIndexChanged, this, [this](int) {
        updateNativePovModeControls();
    });
    connect(povPersonaComboBox_, &qfw::ComboBox::currentIndexChanged, this, [this](int) {
        if (updatingPersonaControls_) {
            return;
        }
        const QString prompt = povPersonaComboBox_->currentData().toString();
        povCustomPromptEdit_->setPlainText(prompt);
        const int modeIndex = povModeComboBox_->findData(QStringLiteral("custom"));
        povModeComboBox_->setCurrentIndex(std::max(0, modeIndex));
        updateNativePovModeControls();
    });
    connect(povSavePersonaButton_, &QPushButton::clicked, this, [this]() {
        saveNativePovPersona();
    });
    connect(povDeletePersonaButton_, &QPushButton::clicked, this, [this]() {
        deleteSelectedNativePovPersona();
    });
    connect(povSaveButton_, &QPushButton::clicked, this, [this]() { saveNativePov(); });
    connect(
        characterPersonaCharacterComboBox_,
        &qfw::ComboBox::currentIndexChanged,
        this,
        [this](int) {
            if (!updatingPersonaControls_) {
                syncSelectedNativeCharacterPersona();
            }
        });
    connect(
        characterPersonaPresetComboBox_,
        &qfw::ComboBox::currentIndexChanged,
        this,
        [this](int) {
            if (updatingPersonaControls_) {
                return;
            }
            const QString characterKey =
                characterPersonaCharacterComboBox_->currentData().toString();
            if (characterKey.isEmpty()) {
                return;
            }
            mutateNativePersona({
                {QStringLiteral("op"), QStringLiteral("activate_character_persona")},
                {QStringLiteral("character"), characterKey},
                {QStringLiteral("preset_id"),
                 characterPersonaPresetComboBox_->currentData().toString()},
                {QStringLiteral("now"), currentLocalDateTime()},
            });
        });
    connect(characterPersonaImportButton_, &QPushButton::clicked, this, [this]() {
        importNativeCharacterPersonaDocuments();
    });
    connect(characterPersonaSaveNewButton_, &QPushButton::clicked, this, [this]() {
        saveNativeCharacterPersona(true);
    });
    connect(characterPersonaSaveButton_, &QPushButton::clicked, this, [this]() {
        saveNativeCharacterPersona(false);
    });
    connect(characterPersonaDeleteButton_, &QPushButton::clicked, this, [this]() {
        deleteSelectedNativeCharacterPersona();
    });
    return page;
}

QWidget* NativeMainWindow::createLlmSettingsPage() {
    auto* page = new qfw::ScrollArea(this);
    auto* content = new QWidget(page);
    auto* layout = new QVBoxLayout(content);
    layout->setContentsMargins(40, 34, 40, 40);
    layout->setSpacing(24);

    auto* title = new qfw::TitleLabel(tr("Native LLM settings"), content);
    auto* subtitle = new qfw::BodyLabel(
        tr("API keys are write-only in this page. Leave a password field blank to keep its saved value."),
        content);
    subtitle->setWordWrap(true);

    auto addThinkingItems = [this](qfw::ComboBox* combo) {
        combo->addItem(tr("Provider default"), QVariant(), QStringLiteral("default"));
        combo->addItem(tr("Enabled"), QVariant(), QStringLiteral("on"));
        combo->addItem(tr("Disabled"), QVariant(), QStringLiteral("off"));
        combo->setFixedWidth(178);
    };

    auto* profiles = new qfw::GroupHeaderCardWidget(tr("API profiles"), content);
    auto* profileEditor = new QWidget(profiles);
    auto* profileEditorLayout = new QHBoxLayout(profileEditor);
    profileEditorLayout->setContentsMargins(0, 0, 0, 0);
    profileEditorLayout->setSpacing(8);
    llmProfileComboBox_ = new qfw::ComboBox(profileEditor);
    llmProfileComboBox_->setMinimumWidth(180);
    llmProfileNameEdit_ = new qfw::LineEdit(profileEditor);
    llmProfileNameEdit_->setPlaceholderText(tr("Profile name"));
    llmApplyProfileButton_ = new qfw::PushButton(tr("Apply"), profileEditor);
    llmSaveProfileButton_ = new qfw::PrimaryPushButton(tr("Save current"), profileEditor);
    llmDeleteProfileButton_ = new qfw::PushButton(tr("Delete"), profileEditor);
    profileEditorLayout->addWidget(llmProfileComboBox_);
    profileEditorLayout->addWidget(llmProfileNameEdit_, 1);
    profileEditorLayout->addWidget(llmApplyProfileButton_);
    profileEditorLayout->addWidget(llmSaveProfileButton_);
    profileEditorLayout->addWidget(llmDeleteProfileButton_);
    profiles->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Save),
        tr("Saved profiles"),
        tr("Profile secrets are applied inside Rust and never returned to Qt"),
        profileEditor);

    auto* primary = new qfw::GroupHeaderCardWidget(tr("Primary model"), content);
    llmApiUrlEdit_ = new qfw::LineEdit(primary);
    llmApiUrlEdit_->setPlaceholderText(
        QStringLiteral("https://api.example.com/v1/chat/completions"));
    llmApiUrlEdit_->setMinimumWidth(380);
    llmModelIdEdit_ = new qfw::LineEdit(primary);
    llmModelIdEdit_->setPlaceholderText(tr("Model ID"));
    auto* primaryProviderActions = new QWidget(primary);
    auto* primaryProviderLayout = new QHBoxLayout(primaryProviderActions);
    primaryProviderLayout->setContentsMargins(0, 0, 0, 0);
    primaryProviderLayout->setSpacing(8);
    llmPrimaryDiscoveredModelsComboBox_ = new qfw::ComboBox(primaryProviderActions);
    llmPrimaryDiscoveredModelsComboBox_->addItem(
        tr("No discovered models"), QVariant(), QString());
    llmPrimaryDiscoveredModelsComboBox_->setEnabled(false);
    llmPrimaryFetchModelsButton_ =
        new qfw::PushButton(tr("Fetch models"), primaryProviderActions);
    llmPrimaryTestButton_ = new qfw::PushButton(tr("Test connection"), primaryProviderActions);
    primaryProviderLayout->addWidget(llmPrimaryDiscoveredModelsComboBox_, 1);
    primaryProviderLayout->addWidget(llmPrimaryFetchModelsButton_);
    primaryProviderLayout->addWidget(llmPrimaryTestButton_);
    llmApiModeComboBox_ = new qfw::ComboBox(primary);
    llmApiModeComboBox_->addItem(
        tr("Chat Completions compatible"), QVariant(), QStringLiteral("chat_completions"));
    llmApiModeComboBox_->addItem(
        tr("OpenAI Responses"), QVariant(), QStringLiteral("responses"));
    llmApiModeComboBox_->setFixedWidth(220);
    llmThinkingComboBox_ = new qfw::ComboBox(primary);
    addThinkingItems(llmThinkingComboBox_);

    auto* primaryKeyEditor = new QWidget(primary);
    auto* primaryKeyLayout = new QHBoxLayout(primaryKeyEditor);
    primaryKeyLayout->setContentsMargins(0, 0, 0, 0);
    primaryKeyLayout->setSpacing(8);
    llmApiKeyEdit_ = new qfw::LineEdit(primaryKeyEditor);
    llmApiKeyEdit_->setEchoMode(QLineEdit::Password);
    llmApiKeyEdit_->setPlaceholderText(tr("Leave blank to keep the saved key"));
    llmClearApiKeyCheckBox_ = new qfw::CheckBox(tr("Clear saved key"), primaryKeyEditor);
    primaryKeyLayout->addWidget(llmApiKeyEdit_, 1);
    primaryKeyLayout->addWidget(llmClearApiKeyCheckBox_);

    primary->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Link),
        tr("API endpoint"),
        tr("HTTP(S) Chat Completions or Responses endpoint"),
        llmApiUrlEdit_);
    primary->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::VPN),
        tr("API key"),
        tr("The saved secret is never returned to Qt"),
        primaryKeyEditor);
    primary->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Robot),
        tr("Model"),
        tr("Provider model identifier"),
        llmModelIdEdit_);
    primary->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::CloudDownload),
        tr("Provider tools"),
        tr("Fetch a bounded model list or send a short non-streaming connection probe"),
        primaryProviderActions);
    primary->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Code),
        tr("API mode"),
        tr("Responses automatically falls back when an endpoint is incompatible"),
        llmApiModeComboBox_);
    primary->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Brightness),
        tr("Reasoning request"),
        tr("Ask compatible providers to enable or disable thinking"),
        llmThinkingComboBox_);

    auto* auxiliary = new qfw::GroupHeaderCardWidget(tr("Auxiliary model"), content);
    llmAuxApiUrlEdit_ = new qfw::LineEdit(auxiliary);
    llmAuxApiUrlEdit_->setPlaceholderText(tr("Blank uses the primary endpoint"));
    llmAuxApiUrlEdit_->setMinimumWidth(380);
    llmAuxModelIdEdit_ = new qfw::LineEdit(auxiliary);
    llmAuxModelIdEdit_->setPlaceholderText(tr("Blank uses the primary model"));
    auto* auxiliaryProviderActions = new QWidget(auxiliary);
    auto* auxiliaryProviderLayout = new QHBoxLayout(auxiliaryProviderActions);
    auxiliaryProviderLayout->setContentsMargins(0, 0, 0, 0);
    auxiliaryProviderLayout->setSpacing(8);
    llmAuxDiscoveredModelsComboBox_ = new qfw::ComboBox(auxiliaryProviderActions);
    llmAuxDiscoveredModelsComboBox_->addItem(
        tr("No discovered models"), QVariant(), QString());
    llmAuxDiscoveredModelsComboBox_->setEnabled(false);
    llmAuxFetchModelsButton_ =
        new qfw::PushButton(tr("Fetch models"), auxiliaryProviderActions);
    llmAuxTestButton_ =
        new qfw::PushButton(tr("Test connection"), auxiliaryProviderActions);
    auxiliaryProviderLayout->addWidget(llmAuxDiscoveredModelsComboBox_, 1);
    auxiliaryProviderLayout->addWidget(llmAuxFetchModelsButton_);
    auxiliaryProviderLayout->addWidget(llmAuxTestButton_);
    llmAuxThinkingComboBox_ = new qfw::ComboBox(auxiliary);
    addThinkingItems(llmAuxThinkingComboBox_);
    llmAuxVisionSwitch_ = new qfw::SwitchButton(auxiliary);
    llmOutfitRecognitionSwitch_ = new qfw::SwitchButton(auxiliary);

    auto* auxiliaryKeyEditor = new QWidget(auxiliary);
    auto* auxiliaryKeyLayout = new QHBoxLayout(auxiliaryKeyEditor);
    auxiliaryKeyLayout->setContentsMargins(0, 0, 0, 0);
    auxiliaryKeyLayout->setSpacing(8);
    llmAuxApiKeyEdit_ = new qfw::LineEdit(auxiliaryKeyEditor);
    llmAuxApiKeyEdit_->setEchoMode(QLineEdit::Password);
    llmAuxApiKeyEdit_->setPlaceholderText(tr("Leave blank to keep the saved key"));
    llmClearAuxApiKeyCheckBox_ =
        new qfw::CheckBox(tr("Clear saved key"), auxiliaryKeyEditor);
    auxiliaryKeyLayout->addWidget(llmAuxApiKeyEdit_, 1);
    auxiliaryKeyLayout->addWidget(llmClearAuxApiKeyCheckBox_);

    auxiliary->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Link),
        tr("API endpoint"),
        tr("Optional endpoint for planning and memory analysis"),
        llmAuxApiUrlEdit_);
    auxiliary->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::VPN),
        tr("API key"),
        tr("Blank falls back to the primary saved key"),
        auxiliaryKeyEditor);
    auxiliary->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Robot),
        tr("Model"),
        tr("Optional smaller model for background work"),
        llmAuxModelIdEdit_);
    auxiliary->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::CloudDownload),
        tr("Provider tools"),
        tr("Blank auxiliary values fall back to the primary endpoint, key and model"),
        auxiliaryProviderActions);
    auxiliary->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Brightness),
        tr("Reasoning request"),
        tr("Independent thinking preference for the auxiliary model"),
        llmAuxThinkingComboBox_);
    auxiliary->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Photo),
        tr("Vision fallback"),
        tr("Allow the auxiliary model to handle image context when supported"),
        llmAuxVisionSwitch_);
    auxiliary->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::People),
        tr("Recognize Live2D outfit"),
        tr("Inject visual outfit context into compatible character prompts"),
        llmOutfitRecognitionSwitch_);

    auto* webTools = new qfw::GroupHeaderCardWidget(tr("Web tools"), content);
    llmWebSearchSwitch_ = new qfw::SwitchButton(webTools);
    llmWebSearchEngineComboBox_ = new qfw::ComboBox(webTools);
    llmWebSearchEngineComboBox_->addItem(
        tr("Bing CN"), QVariant(), QStringLiteral("bing_cn"));
    llmWebSearchEngineComboBox_->addItem(
        tr("Bing"), QVariant(), QStringLiteral("bing"));
    llmWebSearchEngineComboBox_->addItem(
        tr("Google"), QVariant(), QStringLiteral("google"));
    llmWebSearchEngineComboBox_->addItem(
        tr("DuckDuckGo"), QVariant(), QStringLiteral("duckduckgo"));
    llmWebSearchEngineComboBox_->addItem(
        tr("Baidu"), QVariant(), QStringLiteral("baidu"));
    llmWebSearchEngineComboBox_->setFixedWidth(180);
    llmWebSearchSourcesSwitch_ = new qfw::SwitchButton(webTools);
    llmWebFetchSwitch_ = new qfw::SwitchButton(webTools);
    webTools->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Search),
        tr("Public web search"),
        tr("Let the model search current public information through a bounded native Rust tool"),
        llmWebSearchSwitch_);
    webTools->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Search),
        tr("Search engine"),
        tr("Falls back to DuckDuckGo when the selected engine returns no usable results"),
        llmWebSearchEngineComboBox_);
    webTools->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Document),
        tr("Show sources"),
        tr("Ask the model to append the compatible JSON source block"),
        llmWebSearchSourcesSwitch_);
    webTools->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Link),
        tr("WebFetch public URLs"),
        tr("Blocks credentials, private addresses and unsafe redirects; response bodies are bounded"),
        llmWebFetchSwitch_);

    auto* mcpTools = new qfw::GroupHeaderCardWidget(tr("MCP tools"), content);
    llmMcpEnabledSwitch_ = new qfw::SwitchButton(mcpTools);
    llmMcpNativeSwitch_ = new qfw::SwitchButton(mcpTools);
    llmMcpServersEdit_ = new qfw::PlainTextEdit(mcpTools);
    llmMcpServersEdit_->setPlaceholderText(QStringLiteral(
        "[{\n  \"enabled\": true,\n  \"label\": \"filesystem\",\n  \"transport\": \"stdio\",\n  \"command\": \"npx\",\n  \"args\": [\"-y\", \"@modelcontextprotocol/server-filesystem\", \".\"],\n  \"require_approval\": \"always\"\n}]"));
    llmMcpServersEdit_->setMinimumHeight(180);
    llmMcpServersEdit_->setMaximumHeight(280);
    mcpTools->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Code),
        tr("Enable MCP"),
        tr("Discover tools on enabled HTTP or stdio servers before the first model request"),
        llmMcpEnabledSwitch_);
    mcpTools->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::CloudDownload),
        tr("Responses native MCP"),
        tr("Use provider-native MCP only for Responses servers with approval set to never"),
        llmMcpNativeSwitch_);
    mcpTools->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Document),
        tr("MCP server JSON"),
        tr("Supports http, stdio and native transports; authorization and env values are stored in config.json"),
        llmMcpServersEdit_);

    auto* computerUse = new qfw::GroupHeaderCardWidget(tr("Computer Use"), content);
    computerUseEnabledSwitch_ = new qfw::SwitchButton(computerUse);
    computerUseAutoDetectSwitch_ = new qfw::SwitchButton(computerUse);
    computerUseSendScreenshotsSwitch_ = new qfw::SwitchButton(computerUse);
    computerUseMaxScreenshotWidthSpinBox_ = new qfw::SpinBox(computerUse);
    computerUseMaxScreenshotWidthSpinBox_->setRange(640, 1920);
    computerUseMaxScreenshotWidthSpinBox_->setSingleStep(64);
    computerUseMaxScreenshotWidthSpinBox_->setSuffix(tr(" px"));
    computerUseMaxScreenshotWidthSpinBox_->setFixedWidth(150);
    computerUseAllowScreenshotSwitch_ = new qfw::SwitchButton(computerUse);
    computerUseAllowMouseSwitch_ = new qfw::SwitchButton(computerUse);
    computerUseAllowKeyboardSwitch_ = new qfw::SwitchButton(computerUse);
    computerUseAllowClipboardSwitch_ = new qfw::SwitchButton(computerUse);
    computerUseAllowWaitSwitch_ = new qfw::SwitchButton(computerUse);
    computerUse->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::View),
        tr("Enable Computer Use"),
        tr("Expose only the explicitly allowed desktop tools to compatible models"),
        computerUseEnabledSwitch_);
    computerUse->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Robot),
        tr("Automatic intent detection"),
        tr("Allow natural screen and UI requests without requiring the words Computer Use"),
        computerUseAutoDetectSwitch_);
    computerUse->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Photo),
        tr("Screenshot after actions"),
        tr("Return a fresh multimodal screenshot after mouse, keyboard or wait actions"),
        computerUseSendScreenshotsSwitch_);
    computerUse->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Photo),
        tr("Maximum screenshot width"),
        tr("Screenshots are scaled before being encoded and sent to the model"),
        computerUseMaxScreenshotWidthSpinBox_);
    computerUse->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::View),
        tr("Allow screenshots"),
        tr("Read-only desktop capture across all screens"),
        computerUseAllowScreenshotSwitch_);
    computerUse->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Scroll),
        tr("Allow mouse control"),
        tr("Move, click, double-click and scroll using mapped screenshot coordinates"),
        computerUseAllowMouseSwitch_);
    computerUse->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Edit),
        tr("Allow keyboard input"),
        tr("Type bounded text or press a supported shortcut in the focused application"),
        computerUseAllowKeyboardSwitch_);
    computerUse->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Copy),
        tr("Allow clipboard writes"),
        tr("Write at most 100,000 text characters without pasting automatically"),
        computerUseAllowClipboardSwitch_);
    computerUse->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Sync),
        tr("Allow wait"),
        tr("Wait asynchronously for 0.1 to 10 seconds before continuing"),
        computerUseAllowWaitSwitch_);

    auto* context = new qfw::GroupHeaderCardWidget(tr("Conversation context"), content);
    llmHistoryLimitSpinBox_ = new qfw::SpinBox(context);
    llmHistoryLimitSpinBox_->setRange(0, 100);
    llmHistoryLimitSpinBox_->setSpecialValueText(tr("Unlimited"));
    llmHistoryLimitSpinBox_->setFixedWidth(130);
    llmCompactHistoryLimitSpinBox_ = new qfw::SpinBox(context);
    llmCompactHistoryLimitSpinBox_->setRange(0, 100);
    llmCompactHistoryLimitSpinBox_->setSpecialValueText(tr("Unlimited"));
    llmCompactHistoryLimitSpinBox_->setFixedWidth(130);
    llmCrossChatHistorySwitch_ = new qfw::SwitchButton(context);
    llmCustomPromptSwitch_ = new qfw::SwitchButton(context);
    llmCustomPromptEdit_ = new qfw::PlainTextEdit(context);
    llmCustomPromptEdit_->setPlaceholderText(
        tr("Highest-priority global instruction placed before character personas"));
    llmCustomPromptEdit_->setMinimumHeight(90);
    llmCustomPromptEdit_->setMaximumHeight(150);

    context->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Chat),
        tr("Chat history messages"),
        tr("0 is unlimited; otherwise 2-100 messages"),
        llmHistoryLimitSpinBox_);
    context->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Chat),
        tr("Compact overlay history"),
        tr("Retained for compatibility with the compact chat migration"),
        llmCompactHistoryLimitSpinBox_);
    context->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::History),
        tr("Cross-chat context"),
        tr("Include bounded recent excerpts from other owned conversations"),
        llmCrossChatHistorySwitch_);
    context->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Code),
        tr("Custom system prompt"),
        tr("Disable without deleting the saved instruction"),
        llmCustomPromptSwitch_);
    context->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Document),
        tr("System instruction"),
        tr("Maximum 64 KiB; whitespace is trimmed on save"),
        llmCustomPromptEdit_);

    auto* actionRow = new QHBoxLayout();
    llmSettingsStatusLabel_ = new qfw::CaptionLabel(
        tr("Loading redacted LLM configuration"), content);
    llmSaveButton_ = new qfw::PrimaryPushButton(tr("Save LLM settings"), content);
    actionRow->addWidget(llmSettingsStatusLabel_, 1);
    actionRow->addWidget(llmSaveButton_);

    layout->addWidget(title);
    layout->addWidget(subtitle);
    layout->addWidget(profiles);
    layout->addWidget(primary);
    layout->addWidget(auxiliary);
    layout->addWidget(webTools);
    layout->addWidget(mcpTools);
    layout->addWidget(computerUse);
    layout->addWidget(context);
    layout->addLayout(actionRow);
    layout->addStretch(1);
    content->setMinimumWidth(600);
    page->setWidget(content);
    page->setWidgetResizable(true);
    page->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);

    connect(
        llmClearApiKeyCheckBox_,
        &QCheckBox::toggled,
        this,
        [this](bool clear) { llmApiKeyEdit_->setEnabled(!clear); });
    connect(
        llmClearAuxApiKeyCheckBox_,
        &QCheckBox::toggled,
        this,
        [this](bool clear) { llmAuxApiKeyEdit_->setEnabled(!clear); });
    connect(
        llmCustomPromptSwitch_,
        &qfw::SwitchButton::checkedChanged,
        this,
        [this](bool enabled) { llmCustomPromptEdit_->setEnabled(enabled); });
    connect(
        llmWebSearchSwitch_,
        &qfw::SwitchButton::checkedChanged,
        this,
        [this](bool enabled) {
            llmWebSearchEngineComboBox_->setEnabled(enabled);
            llmWebSearchSourcesSwitch_->setEnabled(enabled);
        });
    connect(
        llmMcpEnabledSwitch_,
        &qfw::SwitchButton::checkedChanged,
        this,
        [this](bool enabled) {
            llmMcpNativeSwitch_->setEnabled(enabled);
            llmMcpServersEdit_->setEnabled(enabled);
        });
    connect(
        computerUseEnabledSwitch_,
        &qfw::SwitchButton::checkedChanged,
        this,
        [this](bool enabled) {
            computerUseAutoDetectSwitch_->setEnabled(enabled);
            computerUseSendScreenshotsSwitch_->setEnabled(enabled);
            computerUseMaxScreenshotWidthSpinBox_->setEnabled(enabled);
            computerUseAllowScreenshotSwitch_->setEnabled(enabled);
            computerUseAllowMouseSwitch_->setEnabled(enabled);
            computerUseAllowKeyboardSwitch_->setEnabled(enabled);
            computerUseAllowClipboardSwitch_->setEnabled(enabled);
            computerUseAllowWaitSwitch_->setEnabled(enabled);
        });
    connect(
        llmProfileComboBox_,
        &qfw::ComboBox::currentIndexChanged,
        this,
        [this](int) {
            const QString name = llmProfileComboBox_->currentData().toString();
            if (!name.isEmpty()) {
                llmProfileNameEdit_->setText(name);
            }
            llmApplyProfileButton_->setEnabled(!name.isEmpty());
            llmDeleteProfileButton_->setEnabled(!name.isEmpty());
        });
    connect(
        llmApplyProfileButton_,
        &QPushButton::clicked,
        this,
        [this]() { applySelectedNativeLlmProfile(); });
    connect(
        llmSaveProfileButton_,
        &QPushButton::clicked,
        this,
        [this]() { saveCurrentNativeLlmProfile(); });
    connect(
        llmDeleteProfileButton_,
        &QPushButton::clicked,
        this,
        [this]() { deleteSelectedNativeLlmProfile(); });
    connect(llmPrimaryFetchModelsButton_, &QPushButton::clicked, this, [this]() {
        startNativeProviderOperation(QStringLiteral("primary"), QStringLiteral("fetch_models"));
    });
    connect(llmPrimaryTestButton_, &QPushButton::clicked, this, [this]() {
        startNativeProviderOperation(
            QStringLiteral("primary"), QStringLiteral("test_connection"));
    });
    connect(llmAuxFetchModelsButton_, &QPushButton::clicked, this, [this]() {
        startNativeProviderOperation(
            QStringLiteral("auxiliary"), QStringLiteral("fetch_models"));
    });
    connect(llmAuxTestButton_, &QPushButton::clicked, this, [this]() {
        startNativeProviderOperation(
            QStringLiteral("auxiliary"), QStringLiteral("test_connection"));
    });
    connect(
        llmPrimaryDiscoveredModelsComboBox_,
        &qfw::ComboBox::currentIndexChanged,
        this,
        [this](int) {
            const QString model = llmPrimaryDiscoveredModelsComboBox_->currentData().toString();
            if (!model.isEmpty()) {
                llmModelIdEdit_->setText(model);
            }
        });
    connect(
        llmAuxDiscoveredModelsComboBox_,
        &qfw::ComboBox::currentIndexChanged,
        this,
        [this](int) {
            const QString model = llmAuxDiscoveredModelsComboBox_->currentData().toString();
            if (!model.isEmpty()) {
                llmAuxModelIdEdit_->setText(model);
            }
        });
    connect(llmSaveButton_, &QPushButton::clicked, this, [this]() {
        saveNativeLlmSettings();
    });
    llmApplyProfileButton_->setEnabled(false);
    llmDeleteProfileButton_->setEnabled(false);
    return page;
}

QWidget* NativeMainWindow::createTtsSettingsPage() {
    auto* page = new qfw::ScrollArea(this);
    auto* content = new QWidget(page);
    auto* layout = new QVBoxLayout(content);
    layout->setContentsMargins(40, 34, 40, 40);
    layout->setSpacing(24);

    auto* title = new qfw::TitleLabel(tr("Native text-to-speech"), content);
    auto* subtitle = new qfw::BodyLabel(
        tr("Rust sends bounded GPT-SoVITS/Qwen-compatible requests; Qt Multimedia owns playback and forwards lip-sync poses to the matching pet process."),
        content);
    subtitle->setWordWrap(true);

    auto* endpoint = new qfw::GroupHeaderCardWidget(tr("Synthesis service"), content);
    ttsEnabledSwitch_ = new qfw::SwitchButton(endpoint);
    ttsApiUrlEdit_ = new qfw::LineEdit(endpoint);
    ttsApiUrlEdit_->setPlaceholderText(QStringLiteral("http://127.0.0.1:9880/"));
    ttsApiUrlEdit_->setMinimumWidth(380);
    endpoint->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Volume),
        tr("Chat and reminder TTS"),
        tr("Disabled requests are skipped unless you explicitly run the test below"),
        ttsEnabledSwitch_);
    endpoint->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Link),
        tr("API endpoint"),
        tr("HTTP(S) GPT-SoVITS or compatible root endpoint"),
        ttsApiUrlEdit_);

    auto* voice = new qfw::GroupHeaderCardWidget(tr("Voice and language"), content);
    ttsLanguageComboBox_ = new qfw::ComboBox(voice);
    ttsLanguageComboBox_->addItem(tr("Chinese"), QVariant(), QStringLiteral("Chinese"));
    ttsLanguageComboBox_->addItem(tr("Japanese"), QVariant(), QStringLiteral("Japanese"));
    ttsLanguageComboBox_->addItem(tr("English"), QVariant(), QStringLiteral("English"));
    ttsLanguageComboBox_->setFixedWidth(170);
    ttsReferenceCharacterComboBox_ = new qfw::ComboBox(voice);
    ttsReferenceCharacterComboBox_->setMinimumWidth(220);
    ttsTemperatureSpinBox_ = new qfw::DoubleSpinBox(voice);
    ttsTemperatureSpinBox_->setRange(0.01, 2.0);
    ttsTemperatureSpinBox_->setSingleStep(0.05);
    ttsTemperatureSpinBox_->setDecimals(2);
    ttsTemperatureSpinBox_->setValue(0.9);
    ttsTemperatureSpinBox_->setFixedWidth(120);
    voice->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Chat),
        tr("TTS text language"),
        tr("Non-Chinese output can be translated first by the configured auxiliary model"),
        ttsLanguageComboBox_);
    voice->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::People),
        tr("Reference voice"),
        tr("Automatic follows the speaking character and resolves audio_reference files in Rust"),
        ttsReferenceCharacterComboBox_);
    voice->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::SpeedHigh),
        tr("Sampling temperature"),
        tr("Validated and clamped to 0.01-2.00"),
        ttsTemperatureSpinBox_);

    auto* delivery = new qfw::GroupHeaderCardWidget(tr("Delivery"), content);
    ttsStreamingSwitch_ = new qfw::SwitchButton(delivery);
    ttsTranslateSwitch_ = new qfw::SwitchButton(delivery);
    delivery->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Play),
        tr("Stream audio"),
        tr("Framed OGG is parsed incrementally; incompatible endpoints retry once with WAV"),
        ttsStreamingSwitch_);
    delivery->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Robot),
        tr("Translate non-Chinese speech"),
        tr("Uses the auxiliary LLM when configured and falls back to the original text on failure"),
        ttsTranslateSwitch_);

    auto* test = new qfw::GroupHeaderCardWidget(tr("Playback test"), content);
    ttsTestTextEdit_ = new qfw::PlainTextEdit(test);
    ttsTestTextEdit_->setPlaceholderText(
        tr("Enter test text; blank uses a short default sentence."));
    ttsTestTextEdit_->setMinimumHeight(80);
    ttsTestTextEdit_->setMaximumHeight(130);
    auto* actions = new QWidget(test);
    auto* actionsLayout = new QHBoxLayout(actions);
    actionsLayout->setContentsMargins(0, 0, 0, 0);
    actionsLayout->setSpacing(8);
    ttsTestButton_ = new qfw::PushButton(tr("Test playback"), actions);
    ttsStopButton_ = new qfw::PushButton(tr("Stop"), actions);
    ttsSaveButton_ = new qfw::PrimaryPushButton(tr("Save TTS settings"), actions);
    actionsLayout->addWidget(ttsTestButton_);
    actionsLayout->addWidget(ttsStopButton_);
    actionsLayout->addStretch(1);
    actionsLayout->addWidget(ttsSaveButton_);
    test->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Edit),
        tr("Test text"),
        tr("Action tags and appended search-source metadata are removed before synthesis"),
        ttsTestTextEdit_);
    test->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::PlaySolid),
        tr("Actions"),
        tr("Test playback may run even when automatic TTS is disabled"),
        actions);

    ttsStatusLabel_ = new qfw::CaptionLabel(tr("Loading native TTS settings"), content);
    ttsStatusLabel_->setWordWrap(true);
    layout->addWidget(title);
    layout->addWidget(subtitle);
    layout->addWidget(endpoint);
    layout->addWidget(voice);
    layout->addWidget(delivery);
    layout->addWidget(test);
    layout->addWidget(ttsStatusLabel_);
    layout->addStretch(1);
    content->setMinimumWidth(620);
    page->setWidget(content);
    page->setWidgetResizable(true);
    page->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);

    ttsAudioOutput_ = new QAudioOutput(this);
    ttsMediaPlayer_ = new QMediaPlayer(this);
    ttsMediaPlayer_->setAudioOutput(ttsAudioOutput_);
    ttsLipSyncTimer_.setInterval(40);
    connect(&ttsLipSyncTimer_, &QTimer::timeout, this, [this]() {
        updateNativeTtsLipSync();
    });
    connect(
        ttsMediaPlayer_,
        &QMediaPlayer::mediaStatusChanged,
        this,
        [this](QMediaPlayer::MediaStatus status) {
            if (status == QMediaPlayer::EndOfMedia || status == QMediaPlayer::InvalidMedia) {
                if (status == QMediaPlayer::InvalidMedia) {
                    ttsStatusLabel_->setText(tr("Qt Multimedia could not decode a TTS audio chunk"));
                }
                playNextNativeTtsAudio();
            }
        });
    connect(
        ttsMediaPlayer_,
        &QMediaPlayer::playbackStateChanged,
        this,
        [this](QMediaPlayer::PlaybackState state) {
            if (state == QMediaPlayer::PlayingState) {
                ttsLipSyncTimer_.start();
            } else {
                ttsLipSyncTimer_.stop();
                if (!ttsPlayingCharacter_.isEmpty()) {
                    supervisor_.broadcastControlLine(
                        QStringLiteral("LIP\t%1\t0\t0").arg(ttsPlayingCharacter_), false);
                }
            }
        });
    connect(ttsSaveButton_, &QPushButton::clicked, this, [this]() {
        saveNativeTtsSettings();
    });
    connect(ttsTestButton_, &QPushButton::clicked, this, [this]() {
        if (!saveNativeTtsSettings()) {
            return;
        }
        QString text = ttsTestTextEdit_->toPlainText().trimmed();
        if (text.isEmpty()) {
            text = tr("Hello, this is a native TTS playback test.");
        }
        QString character = ttsReferenceCharacterComboBox_->currentData().toString();
        if (character.isEmpty() && !catalog_.isEmpty()) {
            character = catalog_.first().character;
        }
        if (character.isEmpty()) {
            ttsStatusLabel_->setText(tr("No character is available for reference audio"));
            return;
        }
        enqueueNativeTts(text, character, true);
    });
    connect(ttsStopButton_, &QPushButton::clicked, this, [this]() { stopNativeTts(); });
    ttsStopButton_->setEnabled(false);
    return page;
}

QWidget* NativeMainWindow::createAsrSettingsPage() {
    auto* page = new qfw::ScrollArea(this);
    auto* content = new QWidget(page);
    auto* layout = new QVBoxLayout(content);
    layout->setContentsMargins(40, 34, 40, 40);
    layout->setSpacing(24);

    auto* title = new qfw::TitleLabel(tr("Native ASR voice input"), content);
    auto* subtitle = new qfw::BodyLabel(
        tr("Record through Qt Multimedia and send bounded WAV audio to an OpenAI-compatible transcription endpoint through Rust."),
        content);
    subtitle->setWordWrap(true);

    auto* service = new qfw::GroupHeaderCardWidget(tr("Transcription service"), content);
    asrEnabledSwitch_ = new qfw::SwitchButton(service);
    asrApiUrlEdit_ = new qfw::LineEdit(service);
    asrApiUrlEdit_->setPlaceholderText(
        QStringLiteral("http://127.0.0.1:8000/v1/audio/transcriptions"));
    asrApiUrlEdit_->setMinimumWidth(360);
    asrApiKeyEdit_ = new qfw::LineEdit(service);
    asrApiKeyEdit_->setEchoMode(QLineEdit::Password);
    asrApiKeyEdit_->setPlaceholderText(tr("Blank preserves the saved key"));
    asrClearApiKeyCheckBox_ = new qfw::CheckBox(tr("Clear saved key"), service);
    auto* keyEditor = new QWidget(service);
    auto* keyLayout = new QHBoxLayout(keyEditor);
    keyLayout->setContentsMargins(0, 0, 0, 0);
    keyLayout->setSpacing(8);
    keyLayout->addWidget(asrApiKeyEdit_, 1);
    keyLayout->addWidget(asrClearApiKeyCheckBox_);
    asrModelIdEdit_ = new qfw::LineEdit(service);
    asrModelIdEdit_->setPlaceholderText(QStringLiteral("whisper-large-v3"));
    service->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Microphone),
        tr("Enable voice input"),
        tr("The chat microphone remains hidden from requests until this setting is enabled"),
        asrEnabledSwitch_);
    service->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Link),
        tr("ASR API endpoint"),
        tr("Bare hosts, /v1 and /v1/audio are normalized to the compatible transcription route"),
        asrApiUrlEdit_);
    service->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Fingerprint),
        tr("API key"),
        tr("The secret is write-only and never enters QObject properties or ASR events"),
        keyEditor);
    service->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Robot),
        tr("Model"),
        tr("Sent as the multipart model field"),
        asrModelIdEdit_);

    auto* behavior = new qfw::GroupHeaderCardWidget(tr("Recording behavior"), content);
    asrLanguageComboBox_ = new qfw::ComboBox(behavior);
    asrLanguageComboBox_->addItem(tr("Automatic detection"), QVariant(), QString());
    asrLanguageComboBox_->addItem(tr("Chinese"), QVariant(), QStringLiteral("zh"));
    asrLanguageComboBox_->addItem(tr("Japanese"), QVariant(), QStringLiteral("ja"));
    asrLanguageComboBox_->addItem(tr("English"), QVariant(), QStringLiteral("en"));
    asrLanguageComboBox_->setFixedWidth(180);
    asrInsertModeComboBox_ = new qfw::ComboBox(behavior);
    asrInsertModeComboBox_->addItem(tr("Append to input"), QVariant(), QStringLiteral("append"));
    asrInsertModeComboBox_->addItem(tr("Replace input"), QVariant(), QStringLiteral("replace"));
    asrInsertModeComboBox_->setFixedWidth(180);
    asrAutoSendSwitch_ = new qfw::SwitchButton(behavior);
    asrMaxRecordSecondsSpinBox_ = new qfw::SpinBox(behavior);
    asrMaxRecordSecondsSpinBox_->setRange(3, 300);
    asrMaxRecordSecondsSpinBox_->setSuffix(tr(" s"));
    asrMaxRecordSecondsSpinBox_->setFixedWidth(120);
    behavior->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Language),
        tr("Recognition language"),
        tr("Automatic detection omits the multipart language field"),
        asrLanguageComboBox_);
    behavior->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Edit),
        tr("Insert recognized text"),
        tr("Append keeps existing draft text; replace overwrites it"),
        asrInsertModeComboBox_);
    behavior->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Send),
        tr("Send after recognition"),
        tr("Automatically starts a chat turn only after a non-empty transcript"),
        asrAutoSendSwitch_);
    behavior->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::StopWatch),
        tr("Maximum recording duration"),
        tr("Qt stops and submits automatically at this bounded duration"),
        asrMaxRecordSecondsSpinBox_);

    auto* test = new qfw::GroupHeaderCardWidget(tr("Microphone test"), content);
    asrTestResultEdit_ = new qfw::PlainTextEdit(test);
    asrTestResultEdit_->setReadOnly(true);
    asrTestResultEdit_->setPlaceholderText(
        tr("Start recording, speak, then stop to transcribe through the saved endpoint."));
    asrTestResultEdit_->setMinimumHeight(82);
    asrTestResultEdit_->setMaximumHeight(130);
    auto* actions = new QWidget(test);
    auto* actionsLayout = new QHBoxLayout(actions);
    actionsLayout->setContentsMargins(0, 0, 0, 0);
    actionsLayout->setSpacing(8);
    asrTestButton_ = new qfw::PushButton(tr("Start recording"), actions);
    asrCancelButton_ = new qfw::PushButton(tr("Cancel"), actions);
    asrSaveButton_ = new qfw::PrimaryPushButton(tr("Save ASR settings"), actions);
    actionsLayout->addWidget(asrTestButton_);
    actionsLayout->addWidget(asrCancelButton_);
    actionsLayout->addStretch(1);
    actionsLayout->addWidget(asrSaveButton_);
    test->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Document),
        tr("Transcript"),
        tr("The test may run while automatic chat voice input is disabled"),
        asrTestResultEdit_);
    test->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Microphone),
        tr("Actions"),
        tr("Recording uses the default input device and prefers 16 kHz mono PCM"),
        actions);

    asrStatusLabel_ = new qfw::CaptionLabel(
        tr("A compatible local service may still be run by the legacy ASR sidecar during migration."),
        content);
    asrStatusLabel_->setWordWrap(true);
    layout->addWidget(title);
    layout->addWidget(subtitle);
    layout->addWidget(service);
    layout->addWidget(behavior);
    layout->addWidget(test);
    layout->addWidget(asrStatusLabel_);
    layout->addStretch(1);
    content->setMinimumWidth(620);
    page->setWidget(content);
    page->setWidgetResizable(true);
    page->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);

    asrRecordLimitTimer_.setSingleShot(true);
    connect(&asrRecordLimitTimer_, &QTimer::timeout, this, [this]() {
        stopNativeAsrRecording(true);
    });
    connect(asrSaveButton_, &QPushButton::clicked, this, [this]() {
        saveNativeAsrSettings();
    });
    connect(asrTestButton_, &QPushButton::clicked, this, [this]() {
        if (!asrRecording_ && !saveNativeAsrSettings()) {
            return;
        }
        toggleNativeAsrRecording(true);
    });
    connect(asrCancelButton_, &QPushButton::clicked, this, [this]() { stopNativeAsr(); });
    asrCancelButton_->setEnabled(false);
    return page;
}

QWidget* NativeMainWindow::createScreenAwarenessPage() {
    auto* page = new qfw::ScrollArea(this);
    auto* content = new QWidget(page);
    auto* layout = new QVBoxLayout(content);
    layout->setContentsMargins(40, 34, 40, 40);
    layout->setSpacing(24);

    auto* title = new qfw::TitleLabel(tr("Native screen awareness"), content);
    auto* subtitle = new qfw::BodyLabel(
        tr("Capture a bounded composite of all displays with Qt, analyze it through Rust, and let a configured character decide whether a short proactive message is appropriate."),
        content);
    subtitle->setWordWrap(true);

    auto* schedule = new qfw::GroupHeaderCardWidget(tr("Schedule and speaker"), content);
    screenAwarenessEnabledSwitch_ = new qfw::SwitchButton(schedule);
    screenAwarenessIntervalSpinBox_ = new qfw::SpinBox(schedule);
    screenAwarenessIntervalSpinBox_->setRange(5, 120);
    screenAwarenessIntervalSpinBox_->setSuffix(tr(" min"));
    screenAwarenessIntervalSpinBox_->setFixedWidth(132);
    screenAwarenessCharacterComboBox_ = new qfw::ComboBox(schedule);
    screenAwarenessCharacterComboBox_->setMinimumWidth(220);
    schedule->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::View),
        tr("Enable screen awareness"),
        tr("A single-shot timer is rearmed only after the previous analysis completes"),
        screenAwarenessEnabledSwitch_);
    schedule->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Clock),
        tr("Proactive interval"),
        tr("This stays synchronized with the shared proactive-care cooldown"),
        screenAwarenessIntervalSpinBox_);
    schedule->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::People),
        tr("Speaking character"),
        tr("Choose a visible pet, the default pet, or one fixed character"),
        screenAwarenessCharacterComboBox_);

    auto* analysis = new qfw::GroupHeaderCardWidget(tr("Capture and analysis"), content);
    screenAwarenessMaxWidthSpinBox_ = new qfw::SpinBox(analysis);
    screenAwarenessMaxWidthSpinBox_->setRange(640, 1920);
    screenAwarenessMaxWidthSpinBox_->setSingleStep(160);
    screenAwarenessMaxWidthSpinBox_->setSuffix(tr(" px"));
    screenAwarenessMaxWidthSpinBox_->setFixedWidth(132);
    screenAwarenessModelModeComboBox_ = new qfw::ComboBox(analysis);
    screenAwarenessModelModeComboBox_->addItem(
        tr("Main model reads screenshot"), QVariant(), QStringLiteral("main"));
    screenAwarenessModelModeComboBox_->addItem(
        tr("Auxiliary model summarizes first"), QVariant(), QStringLiteral("aux"));
    screenAwarenessModelModeComboBox_->setMinimumWidth(250);
    screenAwarenessDisplayModeComboBox_ = new qfw::ComboBox(analysis);
    screenAwarenessDisplayModeComboBox_->addItem(
        tr("Floating pet bubble"), QVariant(), QStringLiteral("floating"));
    screenAwarenessDisplayModeComboBox_->addItem(
        tr("System notification"), QVariant(), QStringLiteral("system"));
    screenAwarenessDisplayModeComboBox_->setMinimumWidth(210);
    analysis->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Transparent),
        tr("Screenshot longest edge"),
        tr("All displays are composited, scaled once, PNG-encoded, and bounded to 24 MiB"),
        screenAwarenessMaxWidthSpinBox_);
    analysis->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Robot),
        tr("Screen-reading model"),
        tr("Auxiliary mode falls back to sending the image to the main model"),
        screenAwarenessModelModeComboBox_);
    analysis->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Send),
        tr("Message delivery"),
        tr("NO_SPEAK decisions are never displayed"),
        screenAwarenessDisplayModeComboBox_);

    auto* privacy = new qfw::GroupHeaderCardWidget(tr("Foreground privacy"), content);
    screenAwarenessIncludeProcessSwitch_ = new qfw::SwitchButton(privacy);
    screenAwarenessIncludeTitleSwitch_ = new qfw::SwitchButton(privacy);
    privacy->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Fingerprint),
        tr("Include foreground process name"),
        tr("Used only as model context and explicitly forbidden from being repeated"),
        screenAwarenessIncludeProcessSwitch_);
    privacy->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Document),
        tr("Include foreground window title"),
        tr("Disabled by default because titles may contain file names or private text"),
        screenAwarenessIncludeTitleSwitch_);

    auto* actions = new QWidget(content);
    auto* actionsLayout = new QHBoxLayout(actions);
    actionsLayout->setContentsMargins(0, 0, 0, 0);
    actionsLayout->setSpacing(8);
    screenAwarenessTestButton_ = new qfw::PushButton(tr("Capture and test now"), actions);
    screenAwarenessCancelButton_ = new qfw::PushButton(tr("Cancel"), actions);
    screenAwarenessSaveButton_ =
        new qfw::PrimaryPushButton(tr("Save screen-awareness settings"), actions);
    actionsLayout->addWidget(screenAwarenessTestButton_);
    actionsLayout->addWidget(screenAwarenessCancelButton_);
    actionsLayout->addStretch(1);
    actionsLayout->addWidget(screenAwarenessSaveButton_);
    screenAwarenessStatusLabel_ = new qfw::CaptionLabel(
        tr("Screen capture stays local until a scheduled or manual analysis starts."),
        content);
    screenAwarenessStatusLabel_->setWordWrap(true);

    layout->addWidget(title);
    layout->addWidget(subtitle);
    layout->addWidget(schedule);
    layout->addWidget(analysis);
    layout->addWidget(privacy);
    layout->addWidget(actions);
    layout->addWidget(screenAwarenessStatusLabel_);
    layout->addStretch(1);
    content->setMinimumWidth(620);
    page->setWidget(content);
    page->setWidgetResizable(true);
    page->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);

    connect(screenAwarenessSaveButton_, &QPushButton::clicked, this, [this]() {
        saveNativeScreenAwarenessSettings();
    });
    connect(screenAwarenessTestButton_, &QPushButton::clicked, this, [this]() {
        if (saveNativeScreenAwarenessSettings()) {
            triggerNativeScreenAwareness(true);
        }
    });
    connect(screenAwarenessCancelButton_, &QPushButton::clicked, this, [this]() {
        stopNativeScreenAwareness();
    });
    screenAwarenessCancelButton_->setEnabled(false);
    return page;
}

QWidget* NativeMainWindow::createIntegrationPage() {
    auto* page = new qfw::ScrollArea(this);
    auto* content = new QWidget(page);
    auto* layout = new QVBoxLayout(content);
    layout->setContentsMargins(40, 34, 40, 40);
    layout->setSpacing(24);

    auto* title = new qfw::TitleLabel(tr("Native local integrations"), content);
    auto* subtitle = new qfw::BodyLabel(
        tr("Expose bounded webhook endpoints on 127.0.0.1 only. Rust authenticates, parses and stores each request before Qt forwards display events to isolated pets."),
        content);
    subtitle->setWordWrap(true);

    auto* chat = new qfw::GroupHeaderCardWidget(tr("External chat webhook"), content);
    chatIntegrationEnabledSwitch_ = new qfw::SwitchButton(chat);
    chatIntegrationPortSpinBox_ = new qfw::SpinBox(chat);
    chatIntegrationPortSpinBox_->setRange(1024, 65535);
    chatIntegrationPortSpinBox_->setFixedWidth(132);
    chatIntegrationOverlaySwitch_ = new qfw::SwitchButton(chat);
    chatIntegrationContextSwitch_ = new qfw::SwitchButton(chat);
    chatIntegrationTokenEdit_ = new qfw::LineEdit(chat);
    chatIntegrationTokenEdit_->setEchoMode(QLineEdit::PasswordEchoOnEdit);
    chatIntegrationTokenEdit_->setClearButtonEnabled(true);
    chatIntegrationTokenEdit_->setMinimumWidth(260);
    chatIntegrationClearTokenCheckBox_ = new qfw::CheckBox(tr("Clear saved token"), chat);
    auto* chatToken = new QWidget(chat);
    auto* chatTokenLayout = new QHBoxLayout(chatToken);
    chatTokenLayout->setContentsMargins(0, 0, 0, 0);
    chatTokenLayout->setSpacing(8);
    chatTokenLayout->addWidget(chatIntegrationTokenEdit_, 1);
    chatTokenLayout->addWidget(chatIntegrationClearTokenCheckBox_);
    chat->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Chat),
        tr("Enable chat webhook"),
        tr("Accept GET or POST on /chat-events and explicit read receipts on /chat-read"),
        chatIntegrationEnabledSwitch_);
    chat->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Link),
        tr("Chat port"),
        tr("Loopback endpoint: http://127.0.0.1:<port>/chat-events"),
        chatIntegrationPortSpinBox_);
    chat->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::View),
        tr("Show unread overlay"),
        tr("Duplicate external message IDs are stored once and never trigger another overlay"),
        chatIntegrationOverlaySwitch_);
    chat->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Document),
        tr("Include unread chat context"),
        tr("Preserve the shared prompt-context setting for external conversations"),
        chatIntegrationContextSwitch_);
    chat->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::LockClosed),
        tr("Chat bearer token"),
        tr("Blank keeps the saved token; enabling without one generates a cryptographically random token"),
        chatToken);

    auto* aiStatus = new qfw::GroupHeaderCardWidget(tr("AI status webhook"), content);
    aiStatusEnabledSwitch_ = new qfw::SwitchButton(aiStatus);
    compactAiWindowSwitch_ = new qfw::SwitchButton(aiStatus);
    compactAiWindowOpacitySpinBox_ = new qfw::SpinBox(aiStatus);
    compactAiWindowOpacitySpinBox_->setRange(10, 100);
    compactAiWindowOpacitySpinBox_->setSuffix(QStringLiteral(" %"));
    compactAiWindowOpacitySpinBox_->setFixedWidth(112);
    compactAiWindowFontSizeSpinBox_ = new qfw::SpinBox(aiStatus);
    compactAiWindowFontSizeSpinBox_->setRange(8, 36);
    compactAiWindowFontSizeSpinBox_->setSuffix(QStringLiteral(" px"));
    compactAiWindowFontSizeSpinBox_->setFixedWidth(112);
    compactAiWindowBackgroundEdit_ = new qfw::LineEdit(aiStatus);
    compactAiWindowBackgroundEdit_->setMaxLength(9);
    compactAiWindowBackgroundEdit_->setPlaceholderText(QStringLiteral("#fb7299"));
    compactAiWindowBackgroundEdit_->setFixedWidth(128);
    compactAiWindowTextEdit_ = new qfw::LineEdit(aiStatus);
    compactAiWindowTextEdit_->setMaxLength(9);
    compactAiWindowTextEdit_->setPlaceholderText(QStringLiteral("#24242a"));
    compactAiWindowTextEdit_->setFixedWidth(128);
    aiEventOverlaySwitch_ = new qfw::SwitchButton(aiStatus);
    aiStatusPortSpinBox_ = new qfw::SpinBox(aiStatus);
    aiStatusPortSpinBox_->setRange(1024, 65535);
    aiStatusPortSpinBox_->setFixedWidth(132);
    aiStatusTokenEdit_ = new qfw::LineEdit(aiStatus);
    aiStatusTokenEdit_->setEchoMode(QLineEdit::PasswordEchoOnEdit);
    aiStatusTokenEdit_->setClearButtonEnabled(true);
    aiStatusTokenEdit_->setMinimumWidth(260);
    aiStatusClearTokenCheckBox_ = new qfw::CheckBox(tr("Clear saved token"), aiStatus);
    auto* aiToken = new QWidget(aiStatus);
    auto* aiTokenLayout = new QHBoxLayout(aiToken);
    aiTokenLayout->setContentsMargins(0, 0, 0, 0);
    aiTokenLayout->setSpacing(8);
    aiTokenLayout->addWidget(aiStatusTokenEdit_, 1);
    aiTokenLayout->addWidget(aiStatusClearTokenCheckBox_);
    aiStatus->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Robot),
        tr("Enable AI status webhook"),
        tr("Accept authenticated JSON objects on /ai-events for native pet status display"),
        aiStatusEnabledSwitch_);
    aiStatus->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Chat),
        tr("Compact native event bubbles"),
        tr("Allow chat, reminder and AI event text to appear beside native pets"),
        compactAiWindowSwitch_);
    aiStatus->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Transparent),
        tr("Bubble opacity"),
        tr("Adjust only the compact bubble background without changing pet opacity"),
        compactAiWindowOpacitySpinBox_);
    aiStatus->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Font),
        tr("Bubble font size"),
        tr("Use an 8-36 pixel font for compact event text"),
        compactAiWindowFontSizeSpinBox_);
    aiStatus->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Palette),
        tr("Bubble background color"),
        tr("Hex color; legacy blank values resolve to the active user avatar color"),
        compactAiWindowBackgroundEdit_);
    aiStatus->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Font),
        tr("Bubble text color"),
        tr("Hex color used for compact chat, reminder and AI event text"),
        compactAiWindowTextEdit_);
    aiStatus->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::View),
        tr("Show AI status events"),
        tr("Apply AI_EVENT actions and compact text only when this switch is enabled"),
        aiEventOverlaySwitch_);
    aiStatus->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Link),
        tr("AI status port"),
        tr("Loopback endpoint: http://127.0.0.1:<port>/ai-events"),
        aiStatusPortSpinBox_);
    aiStatus->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::LockClosed),
        tr("AI status bearer token"),
        tr("The saved secret is never copied into a Qt property or exported package"),
        aiToken);

    auto* napcat = new qfw::GroupHeaderCardWidget(tr("NapCat forward WebSocket"), content);
    napcatEnabledSwitch_ = new qfw::SwitchButton(napcat);
    napcatUrlEdit_ = new qfw::LineEdit(napcat);
    napcatUrlEdit_->setPlaceholderText(QStringLiteral("ws://127.0.0.1:3001"));
    napcatUrlEdit_->setMinimumWidth(280);
    napcatTokenEdit_ = new qfw::LineEdit(napcat);
    napcatTokenEdit_->setEchoMode(QLineEdit::PasswordEchoOnEdit);
    napcatTokenEdit_->setClearButtonEnabled(true);
    napcatClearTokenCheckBox_ = new qfw::CheckBox(tr("Clear saved token"), napcat);
    auto* napcatToken = new QWidget(napcat);
    auto* napcatTokenLayout = new QHBoxLayout(napcatToken);
    napcatTokenLayout->setContentsMargins(0, 0, 0, 0);
    napcatTokenLayout->setSpacing(8);
    napcatTokenLayout->addWidget(napcatTokenEdit_, 1);
    napcatTokenLayout->addWidget(napcatClearTokenCheckBox_);
    napcatAutoReplySwitch_ = new qfw::SwitchButton(napcat);
    napcatReplyPrivateSwitch_ = new qfw::SwitchButton(napcat);
    napcatGroupAtOnlySwitch_ = new qfw::SwitchButton(napcat);
    napcatMentionSenderSwitch_ = new qfw::SwitchButton(napcat);
    napcatReplyCharacterEdit_ = new qfw::LineEdit(napcat);
    napcatReplyCharacterEdit_->setPlaceholderText(
        tr("Blank uses the first configured pet"));
    napcatSavePolicyComboBox_ = new qfw::ComboBox(napcat);
    napcatSavePolicyComboBox_->addItem(
        tr("Save group and private chat"), QVariant(), QStringLiteral("all"));
    napcatSavePolicyComboBox_->addItem(
        tr("Save private chat only"), QVariant(), QStringLiteral("private_only"));
    napcatSavePolicyComboBox_->addItem(
        tr("Overlay only; do not save"), QVariant(), QStringLiteral("overlay_only"));
    napcatSavePolicyComboBox_->setMinimumWidth(220);
    auto makeRetentionEditor = [napcat, this](
                                   qfw::ComboBox** mode,
                                   qfw::SpinBox** days) {
        auto* editor = new QWidget(napcat);
        auto* row = new QHBoxLayout(editor);
        row->setContentsMargins(0, 0, 0, 0);
        row->setSpacing(8);
        *mode = new qfw::ComboBox(editor);
        (*mode)->addItem(tr("Manual deletion"), QVariant(), QStringLiteral("manual"));
        (*mode)->addItem(tr("Automatic deletion"), QVariant(), QStringLiteral("auto"));
        (*mode)->setFixedWidth(170);
        *days = new qfw::SpinBox(editor);
        (*days)->setRange(1, 3650);
        (*days)->setSuffix(tr(" days"));
        (*days)->setFixedWidth(130);
        row->addWidget(*mode);
        row->addWidget(*days);
        row->addStretch(1);
        connect(*mode, &qfw::ComboBox::currentIndexChanged, editor, [mode, days](int) {
            (*days)->setEnabled((*mode)->currentData().toString() == QStringLiteral("auto"));
        });
        return editor;
    };
    QWidget* groupRetention = makeRetentionEditor(
        &napcatGroupRetentionModeComboBox_, &napcatGroupRetentionDaysSpinBox_);
    QWidget* privateRetention = makeRetentionEditor(
        &napcatPrivateRetentionModeComboBox_, &napcatPrivateRetentionDaysSpinBox_);
    auto* napcatRecordActions = new QWidget(napcat);
    auto* napcatRecordActionsLayout = new QHBoxLayout(napcatRecordActions);
    napcatRecordActionsLayout->setContentsMargins(0, 0, 0, 0);
    napcatRecordActionsLayout->setSpacing(8);
    auto* deleteGroupRecords = new qfw::PushButton(tr("Delete group records"), napcatRecordActions);
    auto* deletePrivateRecords = new qfw::PushButton(tr("Delete private records"), napcatRecordActions);
    napcatRecordActionsLayout->addWidget(deleteGroupRecords);
    napcatRecordActionsLayout->addWidget(deletePrivateRecords);
    napcatRecordActionsLayout->addStretch(1);
    napcatStatusLabel_ = new qfw::CaptionLabel(tr("NapCat is stopped."), napcat);
    napcatStatusLabel_->setWordWrap(true);
    napcat->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Link),
        tr("Enable NapCat"),
        tr("Connect outward to a OneBot v11 WebSocket server and reconnect every three seconds"),
        napcatEnabledSwitch_);
    napcat->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Link),
        tr("WebSocket URL"),
        tr("Supports ws:// and wss://; the token is sent as Bearer and access_token query fallback"),
        napcatUrlEdit_);
    napcat->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::LockClosed),
        tr("Access token"),
        tr("Blank keeps the saved token; the secret is never exposed through a Qt property"),
        napcatToken);
    napcat->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Robot),
        tr("AI auto reply"),
        tr("Generate native LLM replies without blocking the interactive chat stream"),
        napcatAutoReplySwitch_);
    napcat->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Chat),
        tr("Reply to private chat"),
        tr("Allow private OneBot messages to trigger AI replies"),
        napcatReplyPrivateSwitch_);
    napcat->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::People),
        tr("Group reply only when mentioned"),
        tr("Require an @ segment targeting the logged-in self_id"),
        napcatGroupAtOnlySwitch_);
    napcat->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::People),
        tr("Mention sender in group reply"),
        tr("Prefix outbound group text with a OneBot CQ at code"),
        napcatMentionSenderSwitch_);
    napcat->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::People),
        tr("Reply character ID"),
        tr("Use this character persona for NapCat replies"),
        napcatReplyCharacterEdit_);
    napcat->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Save),
        tr("Record policy"),
        tr("Choose which NapCat messages are persisted in the external-chat database"),
        napcatSavePolicyComboBox_);
    napcat->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Delete),
        tr("Group-chat retention"),
        tr("Automatic mode purges expired group messages after each accepted event"),
        groupRetention);
    napcat->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Delete),
        tr("Private-chat retention"),
        tr("Automatic mode purges expired private messages after each accepted event"),
        privateRetention);
    napcat->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Delete),
        tr("Delete saved records"),
        tr("Permanently delete all external records of the selected chat type"),
        napcatRecordActions);
    napcat->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Info),
        tr("Connection status"),
        tr("Connection, message and reply failures remain visible here"),
        napcatStatusLabel_);
    auto deleteNapcatRecords = [this](const QString& chatType, const QString& label) {
        if (QMessageBox::warning(
                this,
                tr("Delete %1 records?").arg(label),
                tr("This permanently deletes every saved %1 external-chat record. This cannot be undone.")
                    .arg(label),
                QMessageBox::Yes | QMessageBox::No,
                QMessageBox::No)
            != QMessageBox::Yes) {
            return;
        }
        const QString databasePath = nativeDatabasePath();
        if (!backend_.deleteNapcatRecords(databasePath, chatType)) {
            napcatStatusLabel_->setText(backend_.getStatus());
            return;
        }
        const QJsonObject result = parseObject(backend_.getNapcatEventResultJson());
        napcatStatusLabel_->setText(
            tr("Deleted %1 messages and %2 threads.")
                .arg(result.value(QStringLiteral("deleted_messages")).toInteger())
                .arg(result.value(QStringLiteral("deleted_threads")).toInteger()));
    };
    connect(deleteGroupRecords, &QPushButton::clicked, this, [deleteNapcatRecords]() {
        deleteNapcatRecords(QStringLiteral("group"), QObject::tr("group-chat"));
    });
    connect(deletePrivateRecords, &QPushButton::clicked, this, [deleteNapcatRecords]() {
        deleteNapcatRecords(QStringLiteral("private"), QObject::tr("private-chat"));
    });

    auto* actions = new QWidget(content);
    auto* actionsLayout = new QHBoxLayout(actions);
    actionsLayout->setContentsMargins(0, 0, 0, 0);
    actionsLayout->setSpacing(8);
    integrationStopButton_ = new qfw::PushButton(tr("Stop services"), actions);
    integrationSaveButton_ =
        new qfw::PrimaryPushButton(tr("Save and restart services"), actions);
    actionsLayout->addWidget(integrationStopButton_);
    actionsLayout->addStretch(1);
    actionsLayout->addWidget(integrationSaveButton_);
    integrationStatusLabel_ = new qfw::CaptionLabel(
        tr("Local integration settings have not been loaded."), content);
    integrationStatusLabel_->setWordWrap(true);

    layout->addWidget(title);
    layout->addWidget(subtitle);
    layout->addWidget(chat);
    layout->addWidget(aiStatus);
    layout->addWidget(napcat);
    layout->addWidget(actions);
    layout->addWidget(integrationStatusLabel_);
    layout->addStretch(1);
    content->setMinimumWidth(620);
    page->setWidget(content);
    page->setWidgetResizable(true);
    page->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);

    connect(integrationSaveButton_, &QPushButton::clicked, this, [this]() {
        if (saveNativeIntegrationSettings()) {
            restartNativeIntegrationServices();
        }
    });
    connect(integrationStopButton_, &QPushButton::clicked, this, [this]() {
        stopNativeIntegrationServices();
    });
    return page;
}

QWidget* NativeMainWindow::createSettingsPage() {
    auto* page = new qfw::ScrollArea(this);
    auto* content = new QWidget(page);
    auto* layout = new QVBoxLayout(content);
    layout->setContentsMargins(40, 34, 40, 40);
    layout->setSpacing(24);

    auto* title = new qfw::TitleLabel(tr("Native application state"), content);
    auto* live2d = new qfw::GroupHeaderCardWidget(tr("Live2D runtime"), content);
    fpsSpinBox_ = new qfw::SpinBox(live2d);
    fpsSpinBox_->setRange(10, 240);
    fpsSpinBox_->setSuffix(QStringLiteral(" FPS"));
    fpsSpinBox_->setFixedWidth(132);
    opacitySpinBox_ = new qfw::DoubleSpinBox(live2d);
    opacitySpinBox_->setRange(0.05, 1.0);
    opacitySpinBox_->setSingleStep(0.05);
    opacitySpinBox_->setDecimals(2);
    opacitySpinBox_->setFixedWidth(112);
    gameTopmostSwitch_ = new qfw::SwitchButton(live2d);
    obsWindowCaptureSwitch_ = new qfw::SwitchButton(live2d);
    hideLive2dModelSwitch_ = new qfw::SwitchButton(live2d);
    vsyncSwitch_ = new qfw::SwitchButton(live2d);
    gpuAccelerationSwitch_ = new qfw::SwitchButton(live2d);
    qualityComboBox_ = new qfw::ComboBox(live2d);
    qualityComboBox_->addItem(tr("Performance"), QVariant(), QStringLiteral("performance"));
    qualityComboBox_->addItem(tr("Balanced"), QVariant(), QStringLiteral("balanced"));
    qualityComboBox_->setFixedWidth(148);
    scaleSpinBox_ = new qfw::SpinBox(live2d);
    scaleSpinBox_->setRange(25, 500);
    scaleSpinBox_->setSuffix(QStringLiteral(" %"));
    scaleSpinBox_->setFixedWidth(112);
    idleActionsSwitch_ = new qfw::SwitchButton(live2d);
    randomActionsSwitch_ = new qfw::SwitchButton(live2d);
    dragLockedSwitch_ = new qfw::SwitchButton(live2d);
    moveTogetherSwitch_ = new qfw::SwitchButton(live2d);
    headTrackingSwitch_ = new qfw::SwitchButton(live2d);
    mutualGazeSwitch_ = new qfw::SwitchButton(live2d);
    emotionBehaviorSwitch_ = new qfw::SwitchButton(live2d);
    themeComboBox_ = new qfw::ComboBox(live2d);
    themeComboBox_->addItem(
        tr("Follow system"), QVariant(), QStringLiteral("follow_system"));
    themeComboBox_->addItem(tr("Light"), QVariant(), QStringLiteral("off"));
    themeComboBox_->addItem(tr("Dark"), QVariant(), QStringLiteral("on"));
    themeComboBox_->setFixedWidth(148);
    live2d->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::SpeedHigh),
        tr("Frame rate"),
        tr("Target refresh rate for every isolated pet renderer"),
        fpsSpinBox_);
    live2d->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Transparent),
        tr("Opacity"),
        tr("Window opacity shared by Live2D pets"),
        opacitySpinBox_);
    live2d->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Up),
        tr("Stay above games"),
        tr("Continuously restore native pets to the topmost layer while games are active"),
        gameTopmostSwitch_);
    live2d->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Video),
        tr("OBS window capture compatibility"),
        tr("Expose each Windows pet as an application window instead of a tool window"),
        obsWindowCaptureSwitch_);
    live2d->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Hide),
        tr("Hide pet models"),
        tr("Keep each pet process and IPC session alive while hiding every pet window"),
        hideLive2dModelSwitch_);
    live2d->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::SpeedHigh),
        tr("Vertical synchronization"),
        tr("Recreate renderer surfaces with the configured swap interval"),
        vsyncSwitch_);
    live2d->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::SpeedHigh),
        tr("GPU acceleration"),
        tr("Prefer desktop OpenGL; disabling selects Qt software OpenGL on the next pet restart"),
        gpuAccelerationSwitch_);
    live2d->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::View),
        tr("Render quality"),
        tr("Performance uses native resolution; balanced enables Cubism 3 SSAA"),
        qualityComboBox_);
    live2d->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::View),
        tr("Model scale"),
        tr("Resize MOC from 400x500 and MOC3 from 400x800 baselines"),
        scaleSpinBox_);
    live2d->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Robot),
        tr("Idle motion"),
        tr("Loop the configured motion or automatically discover an Idle group"),
        idleActionsSwitch_);
    live2d->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Sync),
        tr("Rotate idle variants"),
        tr("Select another discovered Idle group when the current loop ends"),
        randomActionsSwitch_);
    live2d->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::LockClosed),
        tr("Drag lock"),
        tr("Prevent direct pet-window dragging"),
        dragLockedSwitch_);
    live2d->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Move),
        tr("Move pets together"),
        tr("Mirror one drag session across all active pets"),
        moveTogetherSwitch_);
    live2d->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::View),
        tr("Cursor head tracking"),
        tr("Look toward the global pointer when mutual gaze is disabled"),
        headTrackingSwitch_);
    live2d->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::People),
        tr("Mutual gaze"),
        tr("Look toward the nearest pet on the shared IPC session"),
        mutualGazeSwitch_);
    live2d->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Heart),
        tr("Emotion behavior"),
        tr("Infer expression, motion, window feedback and speech rate from replies"),
        emotionBehaviorSwitch_);
    live2d->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Brush),
        tr("Application theme"),
        tr("Apply light, dark or system appearance to Qt-Fluent-Widgets"),
        themeComboBox_);
    auto* behavior = new qfw::GroupHeaderCardWidget(tr("Application behavior"), content);
    autoStartSwitch_ = new qfw::SwitchButton(behavior);
    chatWindowAlwaysOnTopSwitch_ = new qfw::SwitchButton(behavior);
    birthdayNotificationsSwitch_ = new qfw::SwitchButton(behavior);
    behavior->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Sync),
        tr("Start with the desktop session"),
        tr("Register this native executable for the current user on Windows, macOS or Linux"),
        autoStartSwitch_);
    behavior->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Up),
        tr("Keep chat control center on top"),
        tr("Native chat is integrated into this normal Qt-Fluent window"),
        chatWindowAlwaysOnTopSwitch_);
    behavior->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Calendar),
        tr("Birthday tray notifications"),
        tr("Show native system notifications for today's character birthdays"),
        birthdayNotificationsSwitch_);
    saveSettingsButton_ = new qfw::PrimaryPushButton(tr("Save and apply"), content);

    auto* reminders = new qfw::GroupHeaderCardWidget(tr("Reminders"), content);
    reminderDisplayModeComboBox_ = new qfw::ComboBox(reminders);
    reminderDisplayModeComboBox_->addItem(
        tr("Floating pet bubble"), QVariant(), QStringLiteral("floating"));
    reminderDisplayModeComboBox_->addItem(
        tr("System notification"), QVariant(), QStringLiteral("system"));
    reminderDisplayModeComboBox_->setFixedWidth(190);

    auto* alarmEditor = new QWidget(reminders);
    auto* alarmEditorLayout = new QVBoxLayout(alarmEditor);
    alarmEditorLayout->setContentsMargins(0, 0, 0, 0);
    alarmEditorLayout->setSpacing(8);
    auto* alarmPrimaryRow = new QHBoxLayout();
    alarmPrimaryRow->setContentsMargins(0, 0, 0, 0);
    alarmPrimaryRow->setSpacing(8);
    alarmTimePicker_ = new qfw::TimePicker(alarmEditor);
    alarmTimePicker_->setTime(QTime::currentTime().addSecs(3600));
    alarmTimePicker_->setFixedWidth(112);
    alarmRepeatComboBox_ = new qfw::ComboBox(alarmEditor);
    alarmRepeatComboBox_->addItem(tr("Once"), QVariant(), QStringLiteral("none"));
    alarmRepeatComboBox_->addItem(tr("Daily"), QVariant(), QStringLiteral("daily"));
    alarmRepeatComboBox_->addItem(
        tr("Weekdays"), QVariant(), QStringLiteral("weekdays"));
    alarmRepeatComboBox_->addItem(
        tr("Weekends"), QVariant(), QStringLiteral("weekends"));
    alarmRepeatComboBox_->addItem(
        tr("Custom days"), QVariant(), QStringLiteral("custom"));
    alarmRepeatComboBox_->setFixedWidth(132);
    alarmCharacterComboBox_ = new qfw::ComboBox(alarmEditor);
    alarmCharacterComboBox_->setMinimumWidth(160);
    alarmPrimaryRow->addWidget(alarmTimePicker_);
    alarmPrimaryRow->addWidget(alarmRepeatComboBox_);
    alarmPrimaryRow->addWidget(alarmCharacterComboBox_, 1);
    alarmEditorLayout->addLayout(alarmPrimaryRow);

    alarmCustomDaysWidget_ = new QWidget(alarmEditor);
    auto* weekdayLayout = new QHBoxLayout(alarmCustomDaysWidget_);
    weekdayLayout->setContentsMargins(0, 0, 0, 0);
    weekdayLayout->setSpacing(7);
    for (const QString& label : {
             tr("Mon"), tr("Tue"), tr("Wed"), tr("Thu"), tr("Fri"), tr("Sat"), tr("Sun")}) {
        auto* checkBox = new qfw::CheckBox(label, alarmCustomDaysWidget_);
        alarmWeekdayCheckBoxes_.append(checkBox);
        weekdayLayout->addWidget(checkBox);
    }
    weekdayLayout->addStretch(1);
    alarmCustomDaysWidget_->setVisible(false);
    alarmEditorLayout->addWidget(alarmCustomDaysWidget_);

    auto* alarmDescriptionRow = new QHBoxLayout();
    alarmDescriptionRow->setContentsMargins(0, 0, 0, 0);
    alarmDescriptionRow->setSpacing(8);
    alarmDescriptionEdit_ = new qfw::LineEdit(alarmEditor);
    alarmDescriptionEdit_->setPlaceholderText(tr("Description, for example: practice guitar"));
    addAlarmButton_ = new qfw::PrimaryPushButton(tr("Add alarm"), alarmEditor);
    alarmDescriptionRow->addWidget(alarmDescriptionEdit_, 1);
    alarmDescriptionRow->addWidget(addAlarmButton_);
    alarmEditorLayout->addLayout(alarmDescriptionRow);

    auto* pomodoroEditor = new QWidget(reminders);
    auto* pomodoroEditorLayout = new QHBoxLayout(pomodoroEditor);
    pomodoroEditorLayout->setContentsMargins(0, 0, 0, 0);
    pomodoroEditorLayout->setSpacing(8);
    pomodoroRepeatSpinBox_ = new qfw::SpinBox(pomodoroEditor);
    pomodoroRepeatSpinBox_->setRange(1, 24);
    pomodoroRepeatSpinBox_->setValue(1);
    pomodoroRepeatSpinBox_->setSuffix(tr(" rounds"));
    pomodoroRepeatSpinBox_->setFixedWidth(120);
    pomodoroDescriptionEdit_ = new qfw::LineEdit(pomodoroEditor);
    pomodoroDescriptionEdit_->setPlaceholderText(tr("Description, for example: write code"));
    pomodoroCharacterComboBox_ = new qfw::ComboBox(pomodoroEditor);
    pomodoroCharacterComboBox_->setMinimumWidth(160);
    addPomodoroButton_ = new qfw::PrimaryPushButton(tr("Start Pomodoro"), pomodoroEditor);
    pomodoroEditorLayout->addWidget(pomodoroRepeatSpinBox_);
    pomodoroEditorLayout->addWidget(pomodoroDescriptionEdit_, 1);
    pomodoroEditorLayout->addWidget(pomodoroCharacterComboBox_);
    pomodoroEditorLayout->addWidget(addPomodoroButton_);

    auto* reminderManager = new QWidget(reminders);
    auto* reminderManagerLayout = new QVBoxLayout(reminderManager);
    reminderManagerLayout->setContentsMargins(0, 0, 0, 0);
    reminderManagerLayout->setSpacing(8);
    reminderList_ = new qfw::ListWidget(reminderManager);
    reminderList_->setSelectionMode(QAbstractItemView::SingleSelection);
    reminderList_->setMinimumHeight(180);
    auto* reminderActions = new QHBoxLayout();
    reminderActions->setContentsMargins(0, 0, 0, 0);
    reminderActions->setSpacing(8);
    reminderStatusLabel_ = new qfw::CaptionLabel(tr("No reminder selected"), reminderManager);
    toggleReminderButton_ = new qfw::PushButton(tr("Disable alarm"), reminderManager);
    deleteReminderButton_ = new qfw::PushButton(tr("Delete"), reminderManager);
    reminderActions->addWidget(reminderStatusLabel_, 1);
    reminderActions->addWidget(toggleReminderButton_);
    reminderActions->addWidget(deleteReminderButton_);
    reminderManagerLayout->addWidget(reminderList_);
    reminderManagerLayout->addLayout(reminderActions);

    reminders->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::View),
        tr("Delivery"),
        tr("Choose a non-blocking pet bubble or the system notification tray"),
        reminderDisplayModeComboBox_);
    reminders->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Clock),
        tr("New alarm"),
        tr("Schedule a one-time or repeating character reminder"),
        alarmEditor);
    reminders->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Clock),
        tr("New Pomodoro"),
        tr("Each round is 25 minutes of focus followed by a 5 minute break"),
        pomodoroEditor);
    reminders->addGroup(
        qfw::FluentIcon(qfw::FluentIconEnum::Calendar),
        tr("Saved reminders"),
        tr("Enable, disable, or delete persisted alarms and Pomodoro timers"),
        reminderManager);

    auto* sources = new qfw::SettingCardGroup(tr("Rust service sources"), content);
    configCard_ = new qfw::SettingCard(
        qfw::FluentIconEnum::Document,
        tr("Configuration"),
        configPath_,
        sources);
    modelRootCard_ = new qfw::SettingCard(
        qfw::FluentIconEnum::Folder,
        tr("Model roots"),
        QStringLiteral("%1\n%2").arg(QDir(projectRoot_).filePath(QStringLiteral("models")), userModelsRoot_),
        sources);
    auto* reloadCard = new qfw::PushSettingCard(
        tr("Reload"),
        qfw::FluentIconEnum::Sync,
        tr("Refresh Rust state"),
        tr("Reload the configuration and rescan bundled and user models"),
        sources);
    sources->addSettingCards({configCard_, modelRootCard_, reloadCard});

    auto* renderer = new qfw::SettingCardGroup(tr("Isolated renderer"), content);
    runtimeCard_ = new qfw::SettingCard(
        qfw::FluentIconEnum::Robot,
        tr("Pet process"),
        tr("Pet renderer is not started"),
        renderer);
    auto* stopCard = new qfw::PushSettingCard(
        tr("Stop"),
        qfw::FluentIconEnum::PowerButton,
        tr("Stop active renderer"),
        tr("Gracefully shuts down the isolated pet process through Rust IPC"),
        renderer);
    renderer->addSettingCards({runtimeCard_, stopCard});

    layout->addWidget(title);
    layout->addWidget(live2d);
    layout->addWidget(behavior);
    layout->addWidget(saveSettingsButton_, 0, Qt::AlignRight);
    layout->addWidget(reminders);
    layout->addWidget(sources);
    layout->addWidget(renderer);
    layout->addStretch(1);
    content->setMinimumWidth(560);
    page->setWidget(content);
    page->setWidgetResizable(true);
    page->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);

    connect(reloadCard, &qfw::PushSettingCard::clicked, this, [this]() { reloadBackendState(); });
    connect(stopCard, &qfw::PushSettingCard::clicked, &supervisor_, &PetProcessSupervisor::stop);
    connect(saveSettingsButton_, &QPushButton::clicked, this, [this]() {
        saveNativeSettings();
    });
    connect(
        alarmRepeatComboBox_,
        &qfw::ComboBox::currentIndexChanged,
        this,
        [this](int) {
            alarmCustomDaysWidget_->setVisible(
                alarmRepeatComboBox_->currentData().toString() == QStringLiteral("custom"));
        });
    connect(addAlarmButton_, &QPushButton::clicked, this, [this]() { addNativeAlarm(); });
    connect(
        addPomodoroButton_,
        &QPushButton::clicked,
        this,
        [this]() { addNativePomodoro(); });
    connect(
        reminderDisplayModeComboBox_,
        &qfw::ComboBox::activated,
        this,
        [this](int) {
            mutateNativeReminder({
                {QStringLiteral("op"), QStringLiteral("set_display_mode")},
                {QStringLiteral("mode"), reminderDisplayModeComboBox_->currentData().toString()},
            });
        });
    connect(
        reminderList_,
        &QListWidget::itemSelectionChanged,
        this,
        [this]() { updateNativeReminderActions(); });
    connect(
        toggleReminderButton_,
        &QPushButton::clicked,
        this,
        [this]() { toggleSelectedNativeAlarm(); });
    connect(
        deleteReminderButton_,
        &QPushButton::clicked,
        this,
        [this]() { deleteSelectedNativeReminder(); });
    updateNativeReminderActions();
    return page;
}

bool NativeMainWindow::reloadBackendState() {
    const bool loaded = backend_.reloadState(projectRoot_, userModelsRoot_, configPath_);
    applyBackendState();
    return loaded;
}

void NativeMainWindow::restoreNativeWindowGeometry() {
    const QJsonValue xValue = runtime_.value(QStringLiteral("chat_window_x"));
    const QJsonValue yValue = runtime_.value(QStringLiteral("chat_window_y"));
    const QJsonValue widthValue = runtime_.value(QStringLiteral("chat_window_width"));
    const QJsonValue heightValue = runtime_.value(QStringLiteral("chat_window_height"));
    if (!xValue.isDouble() || !yValue.isDouble()
        || !widthValue.isDouble() || !heightValue.isDouble()) {
        return;
    }

    const QRect saved(
        xValue.toInt(),
        yValue.toInt(),
        std::clamp(widthValue.toInt(), minimumWidth(), 16'384),
        std::clamp(heightValue.toInt(), minimumHeight(), 16'384));
    bool visibleOnDesktop = false;
    for (const QScreen* screen : QGuiApplication::screens()) {
        if (screen != nullptr && screen->availableGeometry().intersects(saved)) {
            visibleOnDesktop = true;
            break;
        }
    }
    if (!visibleOnDesktop) {
        return;
    }

    restoringNativeWindowGeometry_ = true;
    setGeometry(saved);
    restoringNativeWindowGeometry_ = false;
}

void NativeMainWindow::scheduleNativeWindowGeometrySave() {
    if (!restoringNativeWindowGeometry_
        && runtime_.contains(QStringLiteral("chat_window_x"))) {
        nativeWindowGeometryTimer_.start();
    }
}

void NativeMainWindow::persistNativeWindowGeometry() {
    if (restoringNativeWindowGeometry_
        || !runtime_.contains(QStringLiteral("chat_window_x"))) {
        return;
    }
    const QRect current = (isMaximized() || isFullScreen()) && normalGeometry().isValid()
        ? normalGeometry()
        : geometry();
    const QJsonObject settings {
        {QStringLiteral("chat_window_x"), current.x()},
        {QStringLiteral("chat_window_y"), current.y()},
        {QStringLiteral("chat_window_width"), current.width()},
        {QStringLiteral("chat_window_height"), current.height()},
    };
    if (backend_.saveNativeSettings(configPath_, compactJson(settings))) {
        runtime_ = parseObject(backend_.getRuntimeConfigJson());
    }
}

QString NativeMainWindow::nativeDatabasePath() const {
    return QDir(dataRoot_).filePath(QStringLiteral("data.db"));
}

void NativeMainWindow::applyBackendState() {
    serviceStatusLabel_->setText(backend_.getStatus());
    configSummaryLabel_->setText(backend_.getConfigSummary());
    configCard_->setContent(
        QStringLiteral("%1\n%2").arg(configPath_, backend_.getConfigSummary()));
    runtime_ = parseObject(backend_.getRuntimeConfigJson());
    syncSettingsControls();
    applyChatWindowPolicy();
    if (attachmentAutoCleanupSwitch_ != nullptr) {
        const QSignalBlocker switchBlocker(attachmentAutoCleanupSwitch_);
        const QSignalBlocker daysBlocker(attachmentRetentionDaysSpinBox_);
        attachmentAutoCleanupSwitch_->setChecked(
            runtime_
                .value(QStringLiteral("chat_attachment_auto_cleanup_enabled"))
                .toBool(false));
        attachmentRetentionDaysSpinBox_->setValue(
            runtime_.value(QStringLiteral("chat_attachment_retention_days")).toInt(30));
        if (!attachmentStartupCleanupRan_) {
            attachmentStartupCleanupRan_ = true;
            if (attachmentAutoCleanupSwitch_->isChecked()) {
                const QString databasePath = nativeDatabasePath();
                if (!backend_.cleanupChatAttachments(
                        databasePath, attachmentRetentionDaysSpinBox_->value())) {
                    dataStatusLabel_->setText(backend_.getStatus());
                    serviceStatusLabel_->setText(backend_.getStatus());
                }
            }
        }
        refreshNativeAttachmentStats();
    }
    catalog_.clear();
    for (const QJsonValue& value : parseArray(backend_.getModelCatalogJson())) {
        if (!value.isObject()) {
            continue;
        }
        ModelCatalogItem item = modelFromJson(value.toObject());
        if (!item.character.isEmpty() && !item.costume.isEmpty() && !item.path.isEmpty()) {
            catalog_.append(std::move(item));
        }
    }
    populateModelList();
    populateClickMotionProfiles();
    loadNativeUserProfiles();
    loadNativePersonaSettings();
    loadNativeHistoryFilters();
    populateNativeStatisticsCharacters();
    refreshNativeStatistics();
    populateChatCharacters();
    populateMemoryCharacters();
    populateReminderCharacters();
    populateNativeScreenAwarenessCharacters();
    loadNativeReminderState();
    loadNativeLlmSettings();
    loadNativeTtsSettings();
    loadNativeAsrSettings();
    loadNativeScreenAwarenessSettings();
    loadNativeIntegrationSettings();
    restartNativeIntegrationServices();
    refreshNativeMemoryState();
    const int configured = configuredModels().size();
    startConfiguredButton_->setText(
        configured > 1
            ? tr("Start %1 configured pets").arg(configured)
            : (configured == 1 ? tr("Start configured pet") : tr("No pet model available")));
    startConfiguredButton_->setEnabled(configured > 0);
    reconcileNativeAutoStart();
}

void NativeMainWindow::populateReminderCharacters() {
    if (alarmCharacterComboBox_ == nullptr || pomodoroCharacterComboBox_ == nullptr) {
        return;
    }
    const QString previousAlarm = alarmCharacterComboBox_->currentData().toString();
    const QString previousPomodoro = pomodoroCharacterComboBox_->currentData().toString();
    alarmCharacterComboBox_->clear();
    pomodoroCharacterComboBox_->clear();
    alarmCharacterComboBox_->addItem(
        tr("Default configured character"), QVariant(), QString());
    pomodoroCharacterComboBox_->addItem(
        tr("Default configured character"), QVariant(), QString());

    QStringList added;
    for (const ModelCatalogItem& model : configuredModels()) {
        if (model.character.isEmpty() || added.contains(model.character)) {
            continue;
        }
        added.append(model.character);
        const QString display = model.characterDisplay.isEmpty()
            ? model.character
            : model.characterDisplay;
        alarmCharacterComboBox_->addItem(display, QVariant(), model.character);
        pomodoroCharacterComboBox_->addItem(display, QVariant(), model.character);
    }
    const int alarmIndex = alarmCharacterComboBox_->findData(previousAlarm);
    alarmCharacterComboBox_->setCurrentIndex(alarmIndex < 0 ? 0 : alarmIndex);
    const int pomodoroIndex = pomodoroCharacterComboBox_->findData(previousPomodoro);
    pomodoroCharacterComboBox_->setCurrentIndex(pomodoroIndex < 0 ? 0 : pomodoroIndex);
}

void NativeMainWindow::loadNativeReminderState() {
    if (reminderList_ == nullptr) {
        return;
    }
    if (!backend_.loadReminderState(configPath_, currentLocalDateTime())) {
        reminderStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        return;
    }
    reminderState_ = parseObject(backend_.getReminderStateJson());
    const QString mode = reminderState_
                             .value(QStringLiteral("display_mode"))
                             .toString(QStringLiteral("floating"));
    const int modeIndex = reminderDisplayModeComboBox_->findData(mode);
    reminderDisplayModeComboBox_->setCurrentIndex(modeIndex < 0 ? 0 : modeIndex);
    refreshNativeReminderList();
}

void NativeMainWindow::refreshNativeReminderList() {
    if (reminderList_ == nullptr) {
        return;
    }
    QString selectedKind;
    QString selectedId;
    if (const QListWidgetItem* selected = reminderList_->currentItem()) {
        selectedKind = selected->data(kReminderKindRole).toString();
        selectedId = selected->data(kReminderIdRole).toString();
    }
    reminderList_->clear();

    const QJsonArray alarms = reminderState_.value(QStringLiteral("alarms")).toArray();
    for (const QJsonValue& value : alarms) {
        if (!value.isObject()) {
            continue;
        }
        const QJsonObject alarm = value.toObject();
        const bool enabled = alarm.value(QStringLiteral("enabled")).toBool(true);
        const QString character = alarm.value(QStringLiteral("character")).toString();
        const QString display = character.isEmpty()
            ? tr("default character")
            : displayNameForCharacter(character);
        QString description = alarm.value(QStringLiteral("description")).toString().trimmed();
        if (description.isEmpty()) {
            description = tr("Alarm");
        }
        QString nextAt = alarm.value(QStringLiteral("next_at")).toString();
        const QString detail = nextAt.isEmpty()
            ? tr("not scheduled")
            : tr("next %1").arg(nextAt.replace(QStringLiteral("T"), QStringLiteral(" ")));
        const QString text = QStringLiteral("%1 %2 · %3 · %4\n%5 · %6")
                                 .arg(
                                     enabled ? QStringLiteral("●") : QStringLiteral("○"),
                                     alarm.value(QStringLiteral("time")).toString(),
                                     repeatDaysLabel(
                                         alarm.value(QStringLiteral("repeat_days")).toArray()),
                                     description,
                                     display,
                                     detail);
        auto* item = new QListWidgetItem(text, reminderList_);
        item->setData(kReminderKindRole, QStringLiteral("alarm"));
        item->setData(kReminderIdRole, alarm.value(QStringLiteral("id")).toString());
        item->setData(kReminderEnabledRole, enabled);
        if (selectedKind == QStringLiteral("alarm")
            && selectedId == item->data(kReminderIdRole).toString()) {
            reminderList_->setCurrentItem(item);
        }
    }

    const QJsonArray pomodoros = reminderState_.value(QStringLiteral("pomodoros")).toArray();
    for (const QJsonValue& value : pomodoros) {
        if (!value.isObject()) {
            continue;
        }
        const QJsonObject pomodoro = value.toObject();
        const QString character = pomodoro.value(QStringLiteral("character")).toString();
        const QString display = character.isEmpty()
            ? tr("default character")
            : displayNameForCharacter(character);
        QString description = pomodoro.value(QStringLiteral("description")).toString().trimmed();
        if (description.isEmpty()) {
            description = tr("Pomodoro");
        }
        const int completed = pomodoro
                                  .value(QStringLiteral("completed_focus_count"))
                                  .toInt();
        const int repeats = pomodoro.value(QStringLiteral("repeat_count")).toInt(1);
        const QString status = pomodoro
                                   .value(QStringLiteral("status"))
                                   .toString(QStringLiteral("running"));
        const QString phase = pomodoro
                                  .value(QStringLiteral("phase"))
                                  .toString(QStringLiteral("focus"));
        const QString text = tr("Pomodoro · %1/%2 rounds · %3\n%4 · %5 · %6")
                                 .arg(completed)
                                 .arg(repeats)
                                 .arg(description, display, status, phase);
        auto* item = new QListWidgetItem(text, reminderList_);
        item->setData(kReminderKindRole, QStringLiteral("pomodoro"));
        item->setData(kReminderIdRole, pomodoro.value(QStringLiteral("id")).toString());
        item->setData(kReminderEnabledRole, false);
        if (selectedKind == QStringLiteral("pomodoro")
            && selectedId == item->data(kReminderIdRole).toString()) {
            reminderList_->setCurrentItem(item);
        }
    }
    updateNativeReminderActions();
}

void NativeMainWindow::updateNativeReminderActions() {
    if (reminderList_ == nullptr) {
        return;
    }
    const QListWidgetItem* selected = reminderList_->currentItem();
    const bool hasSelection = selected != nullptr;
    const bool isAlarm = hasSelection
        && selected->data(kReminderKindRole).toString() == QStringLiteral("alarm");
    const bool enabled = isAlarm && selected->data(kReminderEnabledRole).toBool();
    toggleReminderButton_->setEnabled(isAlarm);
    toggleReminderButton_->setText(enabled ? tr("Disable alarm") : tr("Enable alarm"));
    deleteReminderButton_->setEnabled(hasSelection);
    if (hasSelection) {
        reminderStatusLabel_->setText(
            isAlarm ? tr("Alarm selected") : tr("Pomodoro selected"));
    } else {
        const int alarmCount = reminderState_.value(QStringLiteral("alarms")).toArray().size();
        const int pomodoroCount =
            reminderState_.value(QStringLiteral("pomodoros")).toArray().size();
        reminderStatusLabel_->setText(
            tr("%1 alarm(s), %2 Pomodoro timer(s)").arg(alarmCount).arg(pomodoroCount));
    }
}

bool NativeMainWindow::mutateNativeReminder(const QJsonObject& command) {
    if (!backend_.mutateReminder(configPath_, currentLocalDateTime(), compactJson(command))) {
        serviceStatusLabel_->setText(backend_.getStatus());
        reminderStatusLabel_->setText(backend_.getStatus());
        return false;
    }
    reminderState_ = parseObject(backend_.getReminderStateJson());
    serviceStatusLabel_->setText(backend_.getStatus());
    refreshNativeReminderList();
    return true;
}

void NativeMainWindow::addNativeAlarm() {
    QJsonValue repeatDays(alarmRepeatComboBox_->currentData().toString());
    if (alarmRepeatComboBox_->currentData().toString() == QStringLiteral("custom")) {
        QJsonArray selectedDays;
        for (int index = 0; index < alarmWeekdayCheckBoxes_.size(); ++index) {
            if (alarmWeekdayCheckBoxes_.at(index)->isChecked()) {
                selectedDays.append(index);
            }
        }
        if (selectedDays.isEmpty()) {
            reminderStatusLabel_->setText(tr("Select at least one custom repeat day"));
            return;
        }
        repeatDays = selectedDays;
    }
    const QJsonObject command {
        {QStringLiteral("op"), QStringLiteral("add_alarm")},
        {QStringLiteral("time"), alarmTimePicker_->time().toString(QStringLiteral("HH:mm"))},
        {QStringLiteral("repeat_days"), repeatDays},
        {QStringLiteral("description"), alarmDescriptionEdit_->text().trimmed()},
        {QStringLiteral("character"), alarmCharacterComboBox_->currentData().toString()},
    };
    if (mutateNativeReminder(command)) {
        alarmDescriptionEdit_->clear();
        reminderStatusLabel_->setText(tr("Alarm added"));
    }
}

void NativeMainWindow::addNativePomodoro() {
    const QJsonObject command {
        {QStringLiteral("op"), QStringLiteral("add_pomodoro")},
        {QStringLiteral("repeat_count"), pomodoroRepeatSpinBox_->value()},
        {QStringLiteral("description"), pomodoroDescriptionEdit_->text().trimmed()},
        {QStringLiteral("character"), pomodoroCharacterComboBox_->currentData().toString()},
    };
    if (mutateNativeReminder(command)) {
        pomodoroDescriptionEdit_->clear();
        reminderStatusLabel_->setText(tr("Pomodoro timer started"));
    }
}

void NativeMainWindow::toggleSelectedNativeAlarm() {
    const QListWidgetItem* selected = reminderList_->currentItem();
    if (selected == nullptr
        || selected->data(kReminderKindRole).toString() != QStringLiteral("alarm")) {
        return;
    }
    mutateNativeReminder({
        {QStringLiteral("op"), QStringLiteral("toggle_alarm")},
        {QStringLiteral("id"), selected->data(kReminderIdRole).toString()},
        {QStringLiteral("enabled"), !selected->data(kReminderEnabledRole).toBool()},
    });
}

void NativeMainWindow::deleteSelectedNativeReminder() {
    const QListWidgetItem* selected = reminderList_->currentItem();
    if (selected == nullptr) {
        return;
    }
    const QString kind = selected->data(kReminderKindRole).toString();
    mutateNativeReminder({
        {QStringLiteral("op"),
         kind == QStringLiteral("alarm")
             ? QStringLiteral("delete_alarm")
             : QStringLiteral("delete_pomodoro")},
        {QStringLiteral("id"), selected->data(kReminderIdRole).toString()},
    });
}

void NativeMainWindow::loadNativeLlmSettings() {
    if (llmApiUrlEdit_ == nullptr) {
        return;
    }
    if (!backend_.loadLlmSettings(configPath_)) {
        llmSettingsStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        return;
    }
    llmSettings_ = parseObject(backend_.getLlmSettingsJson());
    syncNativeLlmSettingsControls();
}

void NativeMainWindow::syncNativeLlmSettingsControls() {
    if (llmApiUrlEdit_ == nullptr) {
        return;
    }
    const QString previousProfile = llmProfileComboBox_->currentData().toString();
    const QString activeProfile =
        llmSettings_.value(QStringLiteral("active_api_profile")).toString().trimmed();
    const QString selectedProfile = activeProfile.isEmpty() ? previousProfile : activeProfile;
    {
        const QSignalBlocker blocker(llmProfileComboBox_);
        llmProfileComboBox_->clear();
        llmProfileComboBox_->addItem(tr("No profile selected"), QVariant(), QString());
        for (const QJsonValue& value : llmSettings_.value(QStringLiteral("profiles")).toArray()) {
            if (!value.isObject()) {
                continue;
            }
            const QJsonObject profile = value.toObject();
            const QString name = profile.value(QStringLiteral("name")).toString().trimmed();
            if (name.isEmpty()) {
                continue;
            }
            const QString model = profile.value(QStringLiteral("model_id")).toString().trimmed();
            const QString label = model.isEmpty()
                ? name
                : QStringLiteral("%1 · %2").arg(name, model);
            llmProfileComboBox_->addItem(label, QVariant(), name);
        }
        const int profileIndex = llmProfileComboBox_->findData(selectedProfile);
        llmProfileComboBox_->setCurrentIndex(profileIndex < 0 ? 0 : profileIndex);
    }
    const QString currentProfile = llmProfileComboBox_->currentData().toString();
    if (!currentProfile.isEmpty()) {
        llmProfileNameEdit_->setText(currentProfile);
    }
    llmApplyProfileButton_->setEnabled(!currentProfile.isEmpty());
    llmDeleteProfileButton_->setEnabled(!currentProfile.isEmpty());

    llmApiUrlEdit_->setText(llmSettings_.value(QStringLiteral("api_url")).toString());
    llmModelIdEdit_->setText(llmSettings_.value(QStringLiteral("model_id")).toString());
    const QString apiMode = llmSettings_
                                .value(QStringLiteral("api_mode"))
                                .toString(QStringLiteral("chat_completions"));
    const int apiModeIndex = llmApiModeComboBox_->findData(apiMode);
    llmApiModeComboBox_->setCurrentIndex(apiModeIndex < 0 ? 0 : apiModeIndex);

    auto setThinking = [](qfw::ComboBox* combo, const QJsonValue& value) {
        const QString mode = value.isBool()
            ? (value.toBool() ? QStringLiteral("on") : QStringLiteral("off"))
            : QStringLiteral("default");
        const int index = combo->findData(mode);
        combo->setCurrentIndex(index < 0 ? 0 : index);
    };
    setThinking(llmThinkingComboBox_, llmSettings_.value(QStringLiteral("enable_thinking")));

    llmAuxApiUrlEdit_->setText(
        llmSettings_.value(QStringLiteral("aux_api_url")).toString());
    llmAuxModelIdEdit_->setText(
        llmSettings_.value(QStringLiteral("aux_model_id")).toString());
    setThinking(
        llmAuxThinkingComboBox_,
        llmSettings_.value(QStringLiteral("aux_enable_thinking")));
    llmAuxVisionSwitch_->setChecked(
        llmSettings_.value(QStringLiteral("aux_vision_fallback_enabled")).toBool());
    llmOutfitRecognitionSwitch_->setChecked(
        llmSettings_.value(QStringLiteral("live2d_outfit_recognition_enabled")).toBool());
    llmHistoryLimitSpinBox_->setValue(
        llmSettings_.value(QStringLiteral("chat_history_message_limit")).toInt(40));
    llmCompactHistoryLimitSpinBox_->setValue(
        llmSettings_.value(QStringLiteral("compact_history_message_limit")).toInt(12));
    llmCrossChatHistorySwitch_->setChecked(
        llmSettings_.value(QStringLiteral("cross_chat_history_enabled")).toBool(true));
    const bool webSearchEnabled =
        llmSettings_.value(QStringLiteral("web_search_enabled")).toBool(false);
    llmWebSearchSwitch_->setChecked(webSearchEnabled);
    const QString webSearchEngine = llmSettings_
                                        .value(QStringLiteral("web_search_engine"))
                                        .toString(QStringLiteral("bing_cn"));
    const int webSearchEngineIndex =
        llmWebSearchEngineComboBox_->findData(webSearchEngine);
    llmWebSearchEngineComboBox_->setCurrentIndex(
        webSearchEngineIndex < 0 ? 0 : webSearchEngineIndex);
    llmWebSearchEngineComboBox_->setEnabled(webSearchEnabled);
    llmWebSearchSourcesSwitch_->setChecked(
        llmSettings_.value(QStringLiteral("web_search_show_sources")).toBool(true));
    llmWebSearchSourcesSwitch_->setEnabled(webSearchEnabled);
    llmWebFetchSwitch_->setChecked(
        llmSettings_.value(QStringLiteral("web_fetch_enabled")).toBool(false));
    const bool mcpEnabled =
        llmSettings_.value(QStringLiteral("mcp_enabled")).toBool(false);
    llmMcpEnabledSwitch_->setChecked(mcpEnabled);
    llmMcpNativeSwitch_->setChecked(
        llmSettings_.value(QStringLiteral("mcp_use_native")).toBool(true));
    llmMcpNativeSwitch_->setEnabled(mcpEnabled);
    llmMcpServersEdit_->setEnabled(mcpEnabled);
    llmMcpServersEdit_->setPlainText(QString::fromUtf8(
        QJsonDocument(llmSettings_.value(QStringLiteral("mcp_servers")).toArray())
            .toJson(QJsonDocument::Indented)));
    const bool computerUseEnabled =
        llmSettings_.value(QStringLiteral("computer_use_enabled")).toBool(false);
    computerUseEnabledSwitch_->setChecked(computerUseEnabled);
    computerUseAutoDetectSwitch_->setChecked(
        llmSettings_.value(QStringLiteral("computer_use_auto_detect")).toBool(true));
    computerUseSendScreenshotsSwitch_->setChecked(
        llmSettings_.value(QStringLiteral("computer_use_send_screenshots")).toBool(true));
    computerUseMaxScreenshotWidthSpinBox_->setValue(
        llmSettings_.value(QStringLiteral("computer_use_max_screenshot_width")).toInt(1280));
    computerUseAllowScreenshotSwitch_->setChecked(
        llmSettings_.value(QStringLiteral("computer_use_allow_screenshot")).toBool(true));
    computerUseAllowMouseSwitch_->setChecked(
        llmSettings_.value(QStringLiteral("computer_use_allow_mouse")).toBool(false));
    computerUseAllowKeyboardSwitch_->setChecked(
        llmSettings_.value(QStringLiteral("computer_use_allow_keyboard")).toBool(false));
    computerUseAllowClipboardSwitch_->setChecked(
        llmSettings_.value(QStringLiteral("computer_use_allow_clipboard")).toBool(false));
    computerUseAllowWaitSwitch_->setChecked(
        llmSettings_.value(QStringLiteral("computer_use_allow_wait")).toBool(true));
    for (QWidget* control : {
             static_cast<QWidget*>(computerUseAutoDetectSwitch_),
             static_cast<QWidget*>(computerUseSendScreenshotsSwitch_),
             static_cast<QWidget*>(computerUseMaxScreenshotWidthSpinBox_),
             static_cast<QWidget*>(computerUseAllowScreenshotSwitch_),
             static_cast<QWidget*>(computerUseAllowMouseSwitch_),
             static_cast<QWidget*>(computerUseAllowKeyboardSwitch_),
             static_cast<QWidget*>(computerUseAllowClipboardSwitch_),
             static_cast<QWidget*>(computerUseAllowWaitSwitch_),
         }) {
        control->setEnabled(computerUseEnabled);
    }
    const bool customPromptEnabled =
        llmSettings_.value(QStringLiteral("custom_system_prompt_enabled")).toBool(true);
    llmCustomPromptSwitch_->setChecked(customPromptEnabled);
    llmCustomPromptEdit_->setEnabled(customPromptEnabled);
    llmCustomPromptEdit_->setPlainText(
        llmSettings_.value(QStringLiteral("custom_system_prompt")).toString());

    llmApiKeyEdit_->clear();
    llmAuxApiKeyEdit_->clear();
    llmClearApiKeyCheckBox_->setChecked(false);
    llmClearAuxApiKeyCheckBox_->setChecked(false);
    llmApiKeyEdit_->setEnabled(true);
    llmAuxApiKeyEdit_->setEnabled(true);
    const bool primaryKeyConfigured =
        llmSettings_.value(QStringLiteral("api_key_configured")).toBool();
    const bool auxiliaryKeyConfigured =
        llmSettings_.value(QStringLiteral("aux_api_key_configured")).toBool();
    llmApiKeyEdit_->setPlaceholderText(
        primaryKeyConfigured
            ? tr("Saved key configured — blank keeps it")
            : tr("No saved key — local services may leave this blank"));
    llmAuxApiKeyEdit_->setPlaceholderText(
        auxiliaryKeyConfigured
            ? tr("Saved auxiliary key configured — blank keeps it")
            : tr("Blank falls back to the primary saved key"));
    llmSettingsStatusLabel_->setText(
        activeProfile.isEmpty()
            ? tr("Editing the current custom LLM configuration")
            : tr("Loaded profile “%1”; saving edits detaches the current configuration")
                  .arg(activeProfile));
}

bool NativeMainWindow::saveNativeLlmSettings() {
    auto thinkingValue = [](const qfw::ComboBox* combo) -> QJsonValue {
        const QString mode = combo->currentData().toString();
        if (mode == QStringLiteral("on")) {
            return true;
        }
        if (mode == QStringLiteral("off")) {
            return false;
        }
        return QJsonValue(QJsonValue::Null);
    };
    const QByteArray mcpServersSource =
        llmMcpServersEdit_->toPlainText().trimmed().isEmpty()
        ? QByteArrayLiteral("[]")
        : llmMcpServersEdit_->toPlainText().trimmed().toUtf8();
    QJsonParseError mcpParseError;
    const QJsonDocument mcpServersDocument =
        QJsonDocument::fromJson(mcpServersSource, &mcpParseError);
    if (mcpParseError.error != QJsonParseError::NoError
        || !mcpServersDocument.isArray()) {
        llmSettingsStatusLabel_->setText(
            tr("MCP server JSON must be a valid array: %1")
                .arg(mcpParseError.errorString()));
        return false;
    }
    QJsonObject settings {
        {QStringLiteral("api_url"), llmApiUrlEdit_->text().trimmed()},
        {QStringLiteral("clear_api_key"), llmClearApiKeyCheckBox_->isChecked()},
        {QStringLiteral("model_id"), llmModelIdEdit_->text().trimmed()},
        {QStringLiteral("api_mode"), llmApiModeComboBox_->currentData().toString()},
        {QStringLiteral("enable_thinking"), thinkingValue(llmThinkingComboBox_)},
        {QStringLiteral("aux_api_url"), llmAuxApiUrlEdit_->text().trimmed()},
        {QStringLiteral("clear_aux_api_key"),
         llmClearAuxApiKeyCheckBox_->isChecked()},
        {QStringLiteral("aux_model_id"), llmAuxModelIdEdit_->text().trimmed()},
        {QStringLiteral("aux_enable_thinking"),
         thinkingValue(llmAuxThinkingComboBox_)},
        {QStringLiteral("aux_vision_fallback_enabled"), llmAuxVisionSwitch_->isChecked()},
        {QStringLiteral("live2d_outfit_recognition_enabled"),
         llmOutfitRecognitionSwitch_->isChecked()},
        {QStringLiteral("chat_history_message_limit"), llmHistoryLimitSpinBox_->value()},
        {QStringLiteral("compact_history_message_limit"),
         llmCompactHistoryLimitSpinBox_->value()},
        {QStringLiteral("cross_chat_history_enabled"),
         llmCrossChatHistorySwitch_->isChecked()},
        {QStringLiteral("web_search_enabled"), llmWebSearchSwitch_->isChecked()},
        {QStringLiteral("web_search_engine"),
         llmWebSearchEngineComboBox_->currentData().toString()},
        {QStringLiteral("web_search_show_sources"),
         llmWebSearchSourcesSwitch_->isChecked()},
        {QStringLiteral("web_fetch_enabled"), llmWebFetchSwitch_->isChecked()},
        {QStringLiteral("mcp_enabled"), llmMcpEnabledSwitch_->isChecked()},
        {QStringLiteral("mcp_use_native"), llmMcpNativeSwitch_->isChecked()},
        {QStringLiteral("mcp_servers"), mcpServersDocument.array()},
        {QStringLiteral("computer_use_enabled"), computerUseEnabledSwitch_->isChecked()},
        {QStringLiteral("computer_use_auto_detect"),
         computerUseAutoDetectSwitch_->isChecked()},
        {QStringLiteral("computer_use_send_screenshots"),
         computerUseSendScreenshotsSwitch_->isChecked()},
        {QStringLiteral("computer_use_max_screenshot_width"),
         computerUseMaxScreenshotWidthSpinBox_->value()},
        {QStringLiteral("computer_use_allow_screenshot"),
         computerUseAllowScreenshotSwitch_->isChecked()},
        {QStringLiteral("computer_use_allow_mouse"),
         computerUseAllowMouseSwitch_->isChecked()},
        {QStringLiteral("computer_use_allow_keyboard"),
         computerUseAllowKeyboardSwitch_->isChecked()},
        {QStringLiteral("computer_use_allow_clipboard"),
         computerUseAllowClipboardSwitch_->isChecked()},
        {QStringLiteral("computer_use_allow_wait"),
         computerUseAllowWaitSwitch_->isChecked()},
        {QStringLiteral("custom_system_prompt_enabled"),
         llmCustomPromptSwitch_->isChecked()},
        {QStringLiteral("custom_system_prompt"),
         llmCustomPromptEdit_->toPlainText().trimmed()},
    };
    const QString primaryKey = llmApiKeyEdit_->text().trimmed();
    if (!primaryKey.isEmpty()) {
        settings.insert(QStringLiteral("api_key"), primaryKey);
    }
    const QString auxiliaryKey = llmAuxApiKeyEdit_->text().trimmed();
    if (!auxiliaryKey.isEmpty()) {
        settings.insert(QStringLiteral("aux_api_key"), auxiliaryKey);
    }
    if (!backend_.saveLlmSettings(configPath_, compactJson(settings))) {
        serviceStatusLabel_->setText(backend_.getStatus());
        llmSettingsStatusLabel_->setText(backend_.getStatus());
        return false;
    }
    llmSettings_ = parseObject(backend_.getLlmSettingsJson());
    serviceStatusLabel_->setText(backend_.getStatus());
    syncNativeLlmSettingsControls();
    llmSettingsStatusLabel_->setText(tr("Native LLM settings saved"));
    return true;
}

bool NativeMainWindow::mutateNativeLlmProfile(const QJsonObject& command) {
    if (!backend_.mutateLlmProfile(configPath_, compactJson(command))) {
        serviceStatusLabel_->setText(backend_.getStatus());
        llmSettingsStatusLabel_->setText(backend_.getStatus());
        return false;
    }
    llmSettings_ = parseObject(backend_.getLlmSettingsJson());
    serviceStatusLabel_->setText(backend_.getStatus());
    syncNativeLlmSettingsControls();
    return true;
}

void NativeMainWindow::applySelectedNativeLlmProfile() {
    const QString name = llmProfileComboBox_->currentData().toString().trimmed();
    if (name.isEmpty()) {
        llmSettingsStatusLabel_->setText(tr("Select a saved profile first"));
        return;
    }
    if (mutateNativeLlmProfile({
            {QStringLiteral("op"), QStringLiteral("apply_profile")},
            {QStringLiteral("name"), name},
        })) {
        llmSettingsStatusLabel_->setText(tr("Applied LLM profile “%1”").arg(name));
    }
}

void NativeMainWindow::saveCurrentNativeLlmProfile() {
    const QString name = llmProfileNameEdit_->text().trimmed();
    if (name.isEmpty()) {
        llmSettingsStatusLabel_->setText(tr("Enter a profile name first"));
        return;
    }
    if (!saveNativeLlmSettings()) {
        return;
    }
    if (mutateNativeLlmProfile({
            {QStringLiteral("op"), QStringLiteral("save_current_profile")},
            {QStringLiteral("name"), name},
        })) {
        llmSettingsStatusLabel_->setText(tr("Saved and applied LLM profile “%1”").arg(name));
    }
}

void NativeMainWindow::deleteSelectedNativeLlmProfile() {
    const QString name = llmProfileComboBox_->currentData().toString().trimmed();
    if (name.isEmpty()) {
        return;
    }
    if (mutateNativeLlmProfile({
            {QStringLiteral("op"), QStringLiteral("delete_profile")},
            {QStringLiteral("name"), name},
        })) {
        llmProfileNameEdit_->clear();
        llmSettingsStatusLabel_->setText(tr("Deleted LLM profile “%1”").arg(name));
    }
}

void NativeMainWindow::startNativeProviderOperation(
    const QString& target,
    const QString& operation) {
    if (activeProviderRequestId_ != 0) {
        return;
    }
    const bool auxiliary = target == QStringLiteral("auxiliary");
    QString apiUrl = auxiliary ? llmAuxApiUrlEdit_->text().trimmed() : QString();
    if (apiUrl.isEmpty()) {
        apiUrl = llmApiUrlEdit_->text().trimmed();
    }
    QString apiKey = auxiliary ? llmAuxApiKeyEdit_->text().trimmed() : QString();
    if (apiKey.isEmpty()) {
        apiKey = llmApiKeyEdit_->text().trimmed();
    }
    QString model = auxiliary ? llmAuxModelIdEdit_->text().trimmed() : QString();
    if (model.isEmpty()) {
        model = llmModelIdEdit_->text().trimmed();
    }
    const QString apiMode = llmApiModeComboBox_->currentData().toString();
    const qint64 requestId = backend_.startProviderOperation(
        configPath_, target, operation, apiUrl, apiKey, model, apiMode);
    serviceStatusLabel_->setText(backend_.getStatus());
    llmSettingsStatusLabel_->setText(backend_.getStatus());
    if (requestId <= 0) {
        return;
    }
    activeProviderRequestId_ = requestId;
    setNativeProviderBusy(true);
}

void NativeMainWindow::handleNativeProviderOperation(const QString& payloadJson) {
    const QJsonObject payload = parseObject(payloadJson);
    const qint64 requestId = payload.value(QStringLiteral("request_id")).toInteger();
    if (requestId <= 0 || requestId != activeProviderRequestId_) {
        return;
    }
    activeProviderRequestId_ = 0;
    setNativeProviderBusy(false);
    serviceStatusLabel_->setText(backend_.getStatus());
    const QString state = payload.value(QStringLiteral("state")).toString();
    const QString target = payload.value(QStringLiteral("target")).toString();
    const QString operation = payload.value(QStringLiteral("operation")).toString();
    if (state != QStringLiteral("finished")) {
        llmSettingsStatusLabel_->setText(
            payload.value(QStringLiteral("message")).toString(tr("Provider operation failed")));
        return;
    }
    if (operation == QStringLiteral("fetch_models")) {
        qfw::ComboBox* combo = target == QStringLiteral("auxiliary")
            ? llmAuxDiscoveredModelsComboBox_
            : llmPrimaryDiscoveredModelsComboBox_;
        const QJsonArray models = payload.value(QStringLiteral("models")).toArray();
        constexpr int kMaximumVisibleProviderModels = 2'000;
        {
            const QSignalBlocker blocker(combo);
            combo->clear();
            if (models.isEmpty()) {
                combo->addItem(tr("Provider returned no models"), QVariant(), QString());
                combo->setEnabled(false);
            } else {
                combo->addItem(tr("Select a discovered model"), QVariant(), QString());
                const int visible = std::min(
                    static_cast<int>(models.size()), kMaximumVisibleProviderModels);
                for (int index = 0; index < visible; ++index) {
                    const QString model = models.at(index).toString();
                    combo->addItem(model, QVariant(), model);
                }
                combo->setEnabled(true);
                combo->setCurrentIndex(0);
            }
        }
        llmSettingsStatusLabel_->setText(
            models.size() > kMaximumVisibleProviderModels
                ? tr("Fetched %1 models; showing the first %2")
                      .arg(models.size())
                      .arg(kMaximumVisibleProviderModels)
                : tr("Fetched %1 provider models").arg(models.size()));
        return;
    }
    const QString mode = payload.value(QStringLiteral("mode")).toString();
    llmSettingsStatusLabel_->setText(
        target == QStringLiteral("auxiliary")
            ? tr("Auxiliary model connection succeeded via %1").arg(mode)
            : tr("Primary model connection succeeded via %1").arg(mode));
}

void NativeMainWindow::setNativeProviderBusy(bool busy) {
    llmPrimaryFetchModelsButton_->setEnabled(!busy);
    llmPrimaryTestButton_->setEnabled(!busy);
    llmAuxFetchModelsButton_->setEnabled(!busy);
    llmAuxTestButton_->setEnabled(!busy);
}

void NativeMainWindow::loadNativeTtsSettings() {
    if (ttsApiUrlEdit_ == nullptr) {
        return;
    }
    if (!backend_.loadTtsSettings(configPath_)) {
        ttsStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        return;
    }
    ttsSettings_ = parseObject(backend_.getTtsSettingsJson());
    syncNativeTtsSettingsControls();
}

void NativeMainWindow::syncNativeTtsSettingsControls() {
    if (ttsApiUrlEdit_ == nullptr) {
        return;
    }
    const QSignalBlocker enabledBlocker(ttsEnabledSwitch_);
    const QSignalBlocker languageBlocker(ttsLanguageComboBox_);
    const QSignalBlocker referenceBlocker(ttsReferenceCharacterComboBox_);
    const QSignalBlocker streamingBlocker(ttsStreamingSwitch_);
    const QSignalBlocker translateBlocker(ttsTranslateSwitch_);
    ttsEnabledSwitch_->setChecked(ttsSettings_.value(QStringLiteral("enabled")).toBool());
    ttsApiUrlEdit_->setText(
        ttsSettings_
            .value(QStringLiteral("api_url"))
            .toString(QStringLiteral("http://127.0.0.1:9880/")));
    const QString language = ttsSettings_
                                 .value(QStringLiteral("language"))
                                 .toString(QStringLiteral("Chinese"));
    const int languageIndex = ttsLanguageComboBox_->findData(language);
    ttsLanguageComboBox_->setCurrentIndex(languageIndex < 0 ? 0 : languageIndex);

    const QString reference =
        ttsSettings_.value(QStringLiteral("reference_character")).toString();
    ttsReferenceCharacterComboBox_->clear();
    ttsReferenceCharacterComboBox_->addItem(
        tr("Follow speaking character"), QVariant(), QString());
    QStringList added;
    for (const ModelCatalogItem& model : catalog_) {
        if (model.character.isEmpty() || added.contains(model.character)) {
            continue;
        }
        added.append(model.character);
        ttsReferenceCharacterComboBox_->addItem(
            model.characterDisplay.isEmpty() ? model.character : model.characterDisplay,
            QVariant(),
            model.character);
    }
    if (!reference.isEmpty() && !added.contains(reference)) {
        ttsReferenceCharacterComboBox_->addItem(reference, QVariant(), reference);
    }
    const int referenceIndex = ttsReferenceCharacterComboBox_->findData(reference);
    ttsReferenceCharacterComboBox_->setCurrentIndex(referenceIndex < 0 ? 0 : referenceIndex);
    ttsTemperatureSpinBox_->setValue(
        ttsSettings_.value(QStringLiteral("temperature")).toDouble(0.9));
    ttsStreamingSwitch_->setChecked(
        ttsSettings_.value(QStringLiteral("streaming")).toBool(true));
    ttsTranslateSwitch_->setChecked(
        ttsSettings_
            .value(QStringLiteral("translate_to_selected_language"))
            .toBool(true));
    ttsStatusLabel_->setText(
        ttsEnabledSwitch_->isChecked()
            ? tr("Native chat and reminder TTS is enabled")
            : tr("Native automatic TTS is disabled; test playback remains available"));
}

bool NativeMainWindow::saveNativeTtsSettings() {
    const QJsonObject settings {
        {QStringLiteral("enabled"), ttsEnabledSwitch_->isChecked()},
        {QStringLiteral("api_url"), ttsApiUrlEdit_->text().trimmed()},
        {QStringLiteral("language"), ttsLanguageComboBox_->currentData().toString()},
        {QStringLiteral("reference_character"),
         ttsReferenceCharacterComboBox_->currentData().toString()},
        {QStringLiteral("streaming"), ttsStreamingSwitch_->isChecked()},
        {QStringLiteral("temperature"), ttsTemperatureSpinBox_->value()},
        {QStringLiteral("translate_to_selected_language"), ttsTranslateSwitch_->isChecked()},
    };
    if (!backend_.saveTtsSettings(configPath_, compactJson(settings))) {
        ttsStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        return false;
    }
    ttsSettings_ = parseObject(backend_.getTtsSettingsJson());
    syncNativeTtsSettingsControls();
    serviceStatusLabel_->setText(backend_.getStatus());
    ttsStatusLabel_->setText(tr("Native TTS settings saved"));
    return true;
}

void NativeMainWindow::enqueueNativeTts(
    const QString& text,
    const QString& character,
    bool force,
    double speedFactor) {
    if (text.trimmed().isEmpty() || character.trimmed().isEmpty()) {
        return;
    }
    if (!force && !ttsSettings_.value(QStringLiteral("enabled")).toBool()) {
        return;
    }
    ttsSynthesisQueue_.enqueue({
        {QStringLiteral("text"), text},
        {QStringLiteral("character"), character.trimmed()},
        {QStringLiteral("force"), force},
        {QStringLiteral("speed_factor"), std::clamp(speedFactor, 0.75, 1.25)},
    });
    ttsStopButton_->setEnabled(true);
    startNextNativeTtsSynthesis();
}

void NativeMainWindow::startNextNativeTtsSynthesis() {
    if (activeTtsRequestId_ != 0 || ttsSynthesisQueue_.isEmpty()) {
        return;
    }
    const QJsonObject request = ttsSynthesisQueue_.dequeue();
    const qint64 requestId = backend_.startTtsSynthesis(
        configPath_,
        projectRoot_,
        request.value(QStringLiteral("text")).toString(),
        request.value(QStringLiteral("character")).toString(),
        request.value(QStringLiteral("speed_factor")).toDouble(1.0),
        request.value(QStringLiteral("force")).toBool());
    if (requestId <= 0) {
        ttsStatusLabel_->setText(backend_.getStatus());
        QTimer::singleShot(0, this, [this]() { startNextNativeTtsSynthesis(); });
        return;
    }
    activeTtsRequestId_ = requestId;
    ttsStatusLabel_->setText(tr("Synthesizing native speech…"));
}

void NativeMainWindow::handleNativeTtsAudio(
    const QString& payloadJson,
    const QByteArray& audio) {
    const QJsonObject payload = parseObject(payloadJson);
    const qint64 requestId = payload.value(QStringLiteral("request_id")).toInteger();
    if (requestId <= 0 || requestId != activeTtsRequestId_) {
        return;
    }
    const QString state = payload.value(QStringLiteral("state")).toString();
    if (state == QStringLiteral("audio")) {
        if (audio.isEmpty()) {
            return;
        }
        const QString mediaType =
            payload.value(QStringLiteral("media_type")).toString() == QStringLiteral("ogg")
            ? QStringLiteral("ogg")
            : QStringLiteral("wav");
        auto* file = new QTemporaryFile(
            QDir::temp().filePath(QStringLiteral("bandori-native-tts-XXXXXX.%1").arg(mediaType)),
            this);
        file->setAutoRemove(true);
        if (!file->open() || file->write(audio) != audio.size() || !file->flush()) {
            ttsStatusLabel_->setText(tr("Could not stage native TTS audio for Qt playback"));
            delete file;
            return;
        }
        file->close();
        file->setProperty(
            "ttsCharacter", payload.value(QStringLiteral("character")).toString());
        ttsAudioQueue_.enqueue(file);
        ttsStatusLabel_->setText(
            tr("Received %1 native audio chunk(s)").arg(ttsAudioQueue_.size()));
        if (currentTtsAudioFile_ == nullptr) {
            playNextNativeTtsAudio();
        }
        return;
    }

    activeTtsRequestId_ = 0;
    if (state == QStringLiteral("finished")) {
        const QString warning =
            payload.value(QStringLiteral("translation_warning")).toString().trimmed();
        ttsStatusLabel_->setText(
            warning.isEmpty()
                ? tr("TTS synthesis finished · %1 chunks · %2")
                      .arg(payload.value(QStringLiteral("chunk_count")).toInteger())
                      .arg(formatAttachmentSize(
                          payload.value(QStringLiteral("total_bytes")).toInteger()))
                : tr("TTS synthesis finished; translation fallback: %1").arg(warning));
    } else if (state == QStringLiteral("cancelled")) {
        ttsStatusLabel_->setText(tr("Native TTS synthesis cancelled"));
    } else {
        ttsStatusLabel_->setText(
            payload.value(QStringLiteral("message")).toString(backend_.getStatus()));
    }
    startNextNativeTtsSynthesis();
    ttsStopButton_->setEnabled(
        activeTtsRequestId_ != 0 || !ttsSynthesisQueue_.isEmpty()
        || currentTtsAudioFile_ != nullptr || !ttsAudioQueue_.isEmpty());
}

void NativeMainWindow::playNextNativeTtsAudio() {
    if (ttsMediaPlayer_ == nullptr) {
        return;
    }
    ttsMediaPlayer_->stop();
    ttsMediaPlayer_->setSource(QUrl());
    if (currentTtsAudioFile_ != nullptr) {
        currentTtsAudioFile_->deleteLater();
        currentTtsAudioFile_ = nullptr;
    }
    if (ttsAudioQueue_.isEmpty()) {
        if (!ttsPlayingCharacter_.isEmpty()) {
            supervisor_.broadcastControlLine(
                QStringLiteral("LIP\t%1\t0\t0").arg(ttsPlayingCharacter_), false);
        }
        ttsPlayingCharacter_.clear();
        ttsLipSyncTimer_.stop();
        ttsStopButton_->setEnabled(
            activeTtsRequestId_ != 0 || !ttsSynthesisQueue_.isEmpty());
        return;
    }
    currentTtsAudioFile_ = ttsAudioQueue_.dequeue();
    ttsPlayingCharacter_ = currentTtsAudioFile_->property("ttsCharacter").toString();
    ttsMediaPlayer_->setSource(QUrl::fromLocalFile(currentTtsAudioFile_->fileName()));
    ttsMediaPlayer_->play();
    ttsStopButton_->setEnabled(true);
}

void NativeMainWindow::stopNativeTts() {
    ttsSynthesisQueue_.clear();
    if (activeTtsRequestId_ != 0) {
        backend_.cancelTtsSynthesis(activeTtsRequestId_);
    }
    if (ttsMediaPlayer_ != nullptr) {
        ttsMediaPlayer_->stop();
        ttsMediaPlayer_->setSource(QUrl());
    }
    if (currentTtsAudioFile_ != nullptr) {
        delete currentTtsAudioFile_;
        currentTtsAudioFile_ = nullptr;
    }
    while (!ttsAudioQueue_.isEmpty()) {
        delete ttsAudioQueue_.dequeue();
    }
    if (!ttsPlayingCharacter_.isEmpty()) {
        supervisor_.broadcastControlLine(
            QStringLiteral("LIP\t%1\t0\t0").arg(ttsPlayingCharacter_), false);
    }
    ttsPlayingCharacter_.clear();
    ttsLipSyncTimer_.stop();
    if (ttsStatusLabel_ != nullptr) {
        ttsStatusLabel_->setText(tr("Native TTS playback stopped"));
    }
    if (ttsStopButton_ != nullptr) {
        ttsStopButton_->setEnabled(activeTtsRequestId_ != 0);
    }
}

void NativeMainWindow::updateNativeTtsLipSync() {
    if (ttsMediaPlayer_ == nullptr || ttsPlayingCharacter_.isEmpty()
        || ttsMediaPlayer_->playbackState() != QMediaPlayer::PlayingState) {
        return;
    }
    const double position = static_cast<double>(ttsMediaPlayer_->position());
    const double level = 0.14 + 0.38 * std::abs(std::sin(position / 82.0));
    const double form = 0.45 * std::sin(position / 190.0);
    supervisor_.broadcastControlLine(
        QStringLiteral("LIP\t%1\t%2\t%3")
            .arg(ttsPlayingCharacter_)
            .arg(level, 0, 'f', 3)
            .arg(form, 0, 'f', 3),
        false);
}

void NativeMainWindow::loadNativeAsrSettings() {
    if (asrApiUrlEdit_ == nullptr) {
        return;
    }
    if (!backend_.loadAsrSettings(configPath_)) {
        asrStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        return;
    }
    asrSettings_ = parseObject(backend_.getAsrSettingsJson());
    syncNativeAsrSettingsControls();
}

void NativeMainWindow::syncNativeAsrSettingsControls() {
    if (asrApiUrlEdit_ == nullptr) {
        return;
    }
    const QSignalBlocker enabledBlocker(asrEnabledSwitch_);
    const QSignalBlocker languageBlocker(asrLanguageComboBox_);
    const QSignalBlocker insertBlocker(asrInsertModeComboBox_);
    const QSignalBlocker autoSendBlocker(asrAutoSendSwitch_);
    asrEnabledSwitch_->setChecked(asrSettings_.value(QStringLiteral("enabled")).toBool());
    asrApiUrlEdit_->setText(
        asrSettings_
            .value(QStringLiteral("api_url"))
            .toString(QStringLiteral("http://127.0.0.1:8000/v1/audio/transcriptions")));
    asrApiKeyEdit_->clear();
    asrApiKeyEdit_->setPlaceholderText(
        asrSettings_.value(QStringLiteral("has_api_key")).toBool()
            ? tr("A saved key is present; blank preserves it")
            : tr("Local services may leave this blank"));
    asrClearApiKeyCheckBox_->setChecked(false);
    asrModelIdEdit_->setText(
        asrSettings_
            .value(QStringLiteral("model_id"))
            .toString(QStringLiteral("whisper-large-v3")));
    const int languageIndex = asrLanguageComboBox_->findData(
        asrSettings_.value(QStringLiteral("language")).toString(QStringLiteral("zh")));
    asrLanguageComboBox_->setCurrentIndex(languageIndex < 0 ? 0 : languageIndex);
    const int insertIndex = asrInsertModeComboBox_->findData(
        asrSettings_
            .value(QStringLiteral("insert_mode"))
            .toString(QStringLiteral("append")));
    asrInsertModeComboBox_->setCurrentIndex(insertIndex < 0 ? 0 : insertIndex);
    asrAutoSendSwitch_->setChecked(
        asrSettings_.value(QStringLiteral("auto_send")).toBool(false));
    asrMaxRecordSecondsSpinBox_->setValue(
        asrSettings_.value(QStringLiteral("max_record_seconds")).toInt(60));
    asrStatusLabel_->setText(
        asrEnabledSwitch_->isChecked()
            ? tr("Native chat voice input is enabled")
            : tr("Automatic chat voice input is disabled; microphone test remains available"));
    setChatBusy(activeChatRequestId_ != 0 || groupSequenceActive_);
}

bool NativeMainWindow::saveNativeAsrSettings() {
    const QJsonObject settings {
        {QStringLiteral("enabled"), asrEnabledSwitch_->isChecked()},
        {QStringLiteral("api_url"), asrApiUrlEdit_->text().trimmed()},
        {QStringLiteral("api_key"), asrApiKeyEdit_->text().trimmed()},
        {QStringLiteral("clear_api_key"), asrClearApiKeyCheckBox_->isChecked()},
        {QStringLiteral("model_id"), asrModelIdEdit_->text().trimmed()},
        {QStringLiteral("language"), asrLanguageComboBox_->currentData().toString()},
        {QStringLiteral("auto_send"), asrAutoSendSwitch_->isChecked()},
        {QStringLiteral("insert_mode"), asrInsertModeComboBox_->currentData().toString()},
        {QStringLiteral("sample_rate"), 16'000},
        {QStringLiteral("max_record_seconds"), asrMaxRecordSecondsSpinBox_->value()},
        {QStringLiteral("timeout_seconds"),
         asrSettings_.value(QStringLiteral("timeout_seconds")).toInt(60)},
    };
    if (!backend_.saveAsrSettings(configPath_, compactJson(settings))) {
        asrStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        return false;
    }
    asrSettings_ = parseObject(backend_.getAsrSettingsJson());
    syncNativeAsrSettingsControls();
    serviceStatusLabel_->setText(backend_.getStatus());
    asrStatusLabel_->setText(tr("Native ASR settings saved"));
    return true;
}

void NativeMainWindow::toggleNativeAsrRecording(bool forTest) {
    if (asrRecording_) {
        stopNativeAsrRecording(true);
        return;
    }
    if (activeAsrRequestId_ != 0) {
        asrStatusLabel_->setText(tr("Wait for or cancel the active transcription"));
        return;
    }
    startNativeAsrRecording(forTest);
}

void NativeMainWindow::startNativeAsrRecording(bool forTest) {
    if (!forTest && !asrSettings_.value(QStringLiteral("enabled")).toBool()) {
        chatStatusLabel_->setText(tr("Enable ASR voice input in settings first"));
        return;
    }
    const QAudioDevice input = QMediaDevices::defaultAudioInput();
    if (input.isNull()) {
        asrStatusLabel_->setText(tr("No audio input device is available"));
        if (!forTest) {
            chatStatusLabel_->setText(asrStatusLabel_->text());
        }
        return;
    }
    QAudioFormat format;
    format.setSampleRate(
        asrSettings_.value(QStringLiteral("sample_rate")).toInt(16'000));
    format.setChannelCount(1);
    format.setSampleFormat(QAudioFormat::Int16);
    if (!input.isFormatSupported(format)) {
        format = input.preferredFormat();
    }
    if (format.bytesPerSample() <= 0 || format.bytesPerFrame() <= 0) {
        asrStatusLabel_->setText(tr("The default microphone format cannot be encoded as WAV"));
        return;
    }
    asrRawAudio_.clear();
    asrAudioLimitExceeded_ = false;
    asrAudioFormat_ = format;
    asrAudioSource_ = new QAudioSource(input, format, this);
    asrAudioDevice_ = asrAudioSource_->start();
    if (asrAudioDevice_ == nullptr) {
        asrAudioSource_->deleteLater();
        asrAudioSource_ = nullptr;
        asrStatusLabel_->setText(tr("Qt Multimedia could not start microphone capture"));
        return;
    }
    connect(asrAudioDevice_, &QIODevice::readyRead, this, [this]() {
        collectNativeAsrAudio();
    });
    asrRecording_ = true;
    asrRecordingForTest_ = forTest;
    const int maximumSeconds =
        asrSettings_.value(QStringLiteral("max_record_seconds")).toInt(60);
    asrRecordLimitTimer_.start(std::clamp(maximumSeconds, 3, 300) * 1'000);
    asrTestButton_->setText(tr("Stop and transcribe"));
    asrCancelButton_->setEnabled(true);
    chatAsrButton_->setText(tr("Stop voice"));
    asrStatusLabel_->setText(
        tr("Recording %1 Hz · %2 channel(s)")
            .arg(format.sampleRate())
            .arg(format.channelCount()));
    if (!forTest) {
        chatStatusLabel_->setText(tr("Recording voice input; press Voice again to transcribe"));
    }
    setChatBusy(activeChatRequestId_ != 0 || groupSequenceActive_);
}

void NativeMainWindow::collectNativeAsrAudio() {
    if (!asrRecording_ || asrAudioDevice_ == nullptr) {
        return;
    }
    const QByteArray chunk = asrAudioDevice_->readAll();
    const qsizetype remaining = kMaximumAsrAudioBytes - asrRawAudio_.size();
    if (chunk.size() > remaining) {
        asrRawAudio_.append(chunk.constData(), std::max<qsizetype>(0, remaining));
        asrAudioLimitExceeded_ = true;
        asrStatusLabel_->setText(tr("ASR recording exceeded the 64 MiB safety limit"));
        QTimer::singleShot(0, this, [this]() { stopNativeAsrRecording(false); });
        return;
    }
    asrRawAudio_.append(chunk);
}

void NativeMainWindow::stopNativeAsrRecording(bool submit) {
    if (!asrRecording_) {
        return;
    }
    collectNativeAsrAudio();
    asrRecording_ = false;
    asrRecordLimitTimer_.stop();
    if (asrAudioDevice_ != nullptr) {
        disconnect(asrAudioDevice_, nullptr, this, nullptr);
    }
    if (asrAudioSource_ != nullptr) {
        asrAudioSource_->stop();
        asrAudioSource_->deleteLater();
    }
    asrAudioDevice_ = nullptr;
    asrAudioSource_ = nullptr;
    const bool forTest = asrRecordingForTest_;
    asrRecordingForTest_ = false;
    const bool audioLimitExceeded = asrAudioLimitExceeded_;
    asrAudioLimitExceeded_ = false;
    const QByteArray wave = submit && !audioLimitExceeded
        ? encodeWaveAudio(asrRawAudio_, asrAudioFormat_)
        : QByteArray();
    asrRawAudio_.clear();
    asrTestButton_->setText(tr("Start recording"));
    chatAsrButton_->setText(tr("Voice"));
    if (!submit) {
        asrCancelButton_->setEnabled(activeAsrRequestId_ != 0);
        setChatBusy(activeChatRequestId_ != 0 || groupSequenceActive_);
        return;
    }
    if (audioLimitExceeded) {
        asrStatusLabel_->setText(tr("ASR recording exceeded the 64 MiB safety limit"));
        if (!forTest) {
            chatStatusLabel_->setText(asrStatusLabel_->text());
        }
        asrCancelButton_->setEnabled(false);
        setChatBusy(activeChatRequestId_ != 0 || groupSequenceActive_);
        return;
    }
    if (wave.size() <= 44) {
        asrStatusLabel_->setText(tr("No microphone audio was captured"));
        if (!forTest) {
            chatStatusLabel_->setText(asrStatusLabel_->text());
        }
        asrCancelButton_->setEnabled(false);
        setChatBusy(activeChatRequestId_ != 0 || groupSequenceActive_);
        return;
    }
    startNativeAsrTranscription(wave, forTest, forTest);
}

void NativeMainWindow::startNativeAsrTranscription(
    const QByteArray& wavAudio,
    bool force,
    bool forTest) {
    const qint64 requestId =
        backend_.startAsrTranscription(configPath_, wavAudio, force);
    if (requestId <= 0) {
        asrStatusLabel_->setText(backend_.getStatus());
        if (!forTest) {
            chatStatusLabel_->setText(backend_.getStatus());
        }
        asrCancelButton_->setEnabled(false);
        setChatBusy(activeChatRequestId_ != 0 || groupSequenceActive_);
        return;
    }
    activeAsrRequestId_ = requestId;
    asrRequestForTest_ = forTest;
    asrCancelButton_->setEnabled(true);
    asrTestButton_->setEnabled(false);
    asrStatusLabel_->setText(tr("Transcribing microphone audio through Rust…"));
    if (!forTest) {
        chatStatusLabel_->setText(tr("Transcribing voice input…"));
    }
    setChatBusy(activeChatRequestId_ != 0 || groupSequenceActive_);
}

void NativeMainWindow::handleNativeAsrEvent(const QString& payloadJson) {
    const QJsonObject payload = parseObject(payloadJson);
    const qint64 requestId = payload.value(QStringLiteral("request_id")).toInteger();
    if (requestId <= 0 || requestId != activeAsrRequestId_) {
        return;
    }
    const bool forTest = asrRequestForTest_;
    const QString state = payload.value(QStringLiteral("state")).toString();
    activeAsrRequestId_ = 0;
    asrRequestForTest_ = false;
    asrCancelButton_->setEnabled(asrRecording_);
    asrTestButton_->setEnabled(true);
    if (state == QStringLiteral("finished")) {
        const QString text = payload.value(QStringLiteral("text")).toString().trimmed();
        if (forTest) {
            asrTestResultEdit_->setPlainText(text);
            asrStatusLabel_->setText(tr("ASR microphone test completed"));
        } else if (!text.isEmpty()) {
            const bool replace =
                asrSettings_.value(QStringLiteral("insert_mode")).toString()
                == QStringLiteral("replace");
            if (replace || chatInput_->toPlainText().trimmed().isEmpty()) {
                chatInput_->setPlainText(text);
            } else {
                chatInput_->setPlainText(
                    chatInput_->toPlainText().trimmed() + u'\n' + text);
            }
            chatInput_->moveCursor(QTextCursor::End);
            chatInput_->setFocus();
            chatStatusLabel_->setText(tr("Voice transcript inserted into the composer"));
            if (asrSettings_.value(QStringLiteral("auto_send")).toBool()
                && activeChatRequestId_ == 0 && !groupSequenceActive_) {
                QTimer::singleShot(0, this, [this]() { sendNativeChat(); });
            }
        }
    } else if (state == QStringLiteral("cancelled")) {
        asrStatusLabel_->setText(tr("Native ASR transcription cancelled"));
        if (!forTest) {
            chatStatusLabel_->setText(asrStatusLabel_->text());
        }
    } else {
        const QString message =
            payload.value(QStringLiteral("message")).toString(backend_.getStatus());
        asrStatusLabel_->setText(message);
        if (!forTest) {
            chatStatusLabel_->setText(message);
        }
    }
    setChatBusy(activeChatRequestId_ != 0 || groupSequenceActive_);
}

void NativeMainWindow::stopNativeAsr() {
    if (asrRecording_) {
        stopNativeAsrRecording(false);
    }
    if (activeAsrRequestId_ != 0) {
        backend_.cancelAsrTranscription(activeAsrRequestId_);
    }
    if (asrStatusLabel_ != nullptr) {
        asrStatusLabel_->setText(tr("Native ASR stopped"));
    }
    if (asrCancelButton_ != nullptr) {
        asrCancelButton_->setEnabled(activeAsrRequestId_ != 0);
    }
}

void NativeMainWindow::populateNativeScreenAwarenessCharacters() {
    if (screenAwarenessCharacterComboBox_ == nullptr) {
        return;
    }
    const QString previous = screenAwarenessCharacterComboBox_->currentData().toString();
    const QString savedMode =
        screenAwarenessSettings_
            .value(QStringLiteral("character_mode"))
            .toString(QStringLiteral("random_visible"));
    const QString savedCharacter =
        screenAwarenessSettings_.value(QStringLiteral("character")).toString().trimmed();
    const QSignalBlocker blocker(screenAwarenessCharacterComboBox_);
    screenAwarenessCharacterComboBox_->clear();
    screenAwarenessCharacterComboBox_->addItem(
        tr("Random visible character"), QVariant(), QStringLiteral("__random_visible__"));
    screenAwarenessCharacterComboBox_->addItem(
        tr("Default configured character"), QVariant(), QStringLiteral("__default__"));
    QStringList added;
    for (const ModelCatalogItem& model : catalog_) {
        if (model.character.isEmpty() || added.contains(model.character)) {
            continue;
        }
        added.append(model.character);
        screenAwarenessCharacterComboBox_->addItem(
            model.characterDisplay.isEmpty() ? model.character : model.characterDisplay,
            QVariant(),
            model.character);
    }
    if (!savedCharacter.isEmpty()
        && screenAwarenessCharacterComboBox_->findData(savedCharacter) < 0) {
        screenAwarenessCharacterComboBox_->addItem(savedCharacter, QVariant(), savedCharacter);
    }
    QString selected;
    if (!screenAwarenessSettings_.isEmpty()) {
        selected = savedMode == QStringLiteral("fixed")
            ? savedCharacter
            : (savedMode == QStringLiteral("default")
                   ? QStringLiteral("__default__")
                   : QStringLiteral("__random_visible__"));
    } else {
        selected = previous;
    }
    const int index = screenAwarenessCharacterComboBox_->findData(selected);
    screenAwarenessCharacterComboBox_->setCurrentIndex(index < 0 ? 0 : index);
}

void NativeMainWindow::loadNativeScreenAwarenessSettings() {
    if (screenAwarenessEnabledSwitch_ == nullptr) {
        return;
    }
    if (!backend_.loadScreenAwarenessSettings(configPath_)) {
        screenAwarenessStatusLabel_->setText(backend_.getStatus());
        screenAwarenessTimer_.stop();
        return;
    }
    screenAwarenessSettings_ = parseObject(backend_.getScreenAwarenessSettingsJson());
    populateNativeScreenAwarenessCharacters();
    syncNativeScreenAwarenessControls();
    scheduleNativeScreenAwareness();
}

void NativeMainWindow::syncNativeScreenAwarenessControls() {
    if (screenAwarenessEnabledSwitch_ == nullptr) {
        return;
    }
    const QSignalBlocker enabledBlocker(screenAwarenessEnabledSwitch_);
    const QSignalBlocker intervalBlocker(screenAwarenessIntervalSpinBox_);
    const QSignalBlocker characterBlocker(screenAwarenessCharacterComboBox_);
    const QSignalBlocker widthBlocker(screenAwarenessMaxWidthSpinBox_);
    const QSignalBlocker modelBlocker(screenAwarenessModelModeComboBox_);
    const QSignalBlocker displayBlocker(screenAwarenessDisplayModeComboBox_);
    const QSignalBlocker processBlocker(screenAwarenessIncludeProcessSwitch_);
    const QSignalBlocker titleBlocker(screenAwarenessIncludeTitleSwitch_);
    screenAwarenessEnabledSwitch_->setChecked(
        screenAwarenessSettings_.value(QStringLiteral("enabled")).toBool(false));
    screenAwarenessIntervalSpinBox_->setValue(
        screenAwarenessSettings_.value(QStringLiteral("interval_minutes")).toInt(30));
    screenAwarenessMaxWidthSpinBox_->setValue(
        screenAwarenessSettings_.value(QStringLiteral("max_screenshot_width")).toInt(1920));
    const int modelIndex = screenAwarenessModelModeComboBox_->findData(
        screenAwarenessSettings_
            .value(QStringLiteral("model_mode"))
            .toString(QStringLiteral("main")));
    screenAwarenessModelModeComboBox_->setCurrentIndex(modelIndex < 0 ? 0 : modelIndex);
    const int displayIndex = screenAwarenessDisplayModeComboBox_->findData(
        screenAwarenessSettings_
            .value(QStringLiteral("display_mode"))
            .toString(QStringLiteral("floating")));
    screenAwarenessDisplayModeComboBox_->setCurrentIndex(displayIndex < 0 ? 0 : displayIndex);
    screenAwarenessIncludeProcessSwitch_->setChecked(
        screenAwarenessSettings_
            .value(QStringLiteral("include_process_name"))
            .toBool(true));
    screenAwarenessIncludeTitleSwitch_->setChecked(
        screenAwarenessSettings_
            .value(QStringLiteral("include_window_title"))
            .toBool(false));
    screenAwarenessStatusLabel_->setText(
        screenAwarenessEnabledSwitch_->isChecked()
            ? tr("Screen awareness is enabled; the next capture is scheduled after the configured interval")
            : tr("Screen awareness is disabled; manual tests remain available"));
}

bool NativeMainWindow::saveNativeScreenAwarenessSettings() {
    if (screenAwarenessEnabledSwitch_ == nullptr) {
        return false;
    }
    const QString selection =
        screenAwarenessCharacterComboBox_->currentData().toString().trimmed();
    QString characterMode = QStringLiteral("fixed");
    QString character = selection;
    if (selection == QStringLiteral("__random_visible__")) {
        characterMode = QStringLiteral("random_visible");
        character.clear();
    } else if (selection == QStringLiteral("__default__")) {
        characterMode = QStringLiteral("default");
        character.clear();
    }
    const QJsonObject settings {
        {QStringLiteral("enabled"), screenAwarenessEnabledSwitch_->isChecked()},
        {QStringLiteral("interval_minutes"), screenAwarenessIntervalSpinBox_->value()},
        {QStringLiteral("character_mode"), characterMode},
        {QStringLiteral("character"), character},
        {QStringLiteral("max_screenshot_width"), screenAwarenessMaxWidthSpinBox_->value()},
        {QStringLiteral("model_mode"),
         screenAwarenessModelModeComboBox_->currentData().toString()},
        {QStringLiteral("display_mode"),
         screenAwarenessDisplayModeComboBox_->currentData().toString()},
        {QStringLiteral("include_process_name"),
         screenAwarenessIncludeProcessSwitch_->isChecked()},
        {QStringLiteral("include_window_title"),
         screenAwarenessIncludeTitleSwitch_->isChecked()},
    };
    if (!backend_.saveScreenAwarenessSettings(configPath_, compactJson(settings))) {
        screenAwarenessStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        return false;
    }
    screenAwarenessSettings_ = parseObject(backend_.getScreenAwarenessSettingsJson());
    syncNativeScreenAwarenessControls();
    scheduleNativeScreenAwareness();
    screenAwarenessStatusLabel_->setText(tr("Native screen-awareness settings saved"));
    return true;
}

void NativeMainWindow::scheduleNativeScreenAwareness() {
    screenAwarenessTimer_.stop();
    if (exitRequested_ || activeScreenAwarenessRequestId_ != 0
        || !screenAwarenessSettings_.value(QStringLiteral("enabled")).toBool(false)) {
        return;
    }
    const int minutes = std::clamp(
        screenAwarenessSettings_.value(QStringLiteral("interval_minutes")).toInt(30),
        5,
        120);
    screenAwarenessTimer_.start(minutes * 60 * 1'000);
}

QString NativeMainWindow::chooseNativeScreenAwarenessCharacter() const {
    const QString mode =
        screenAwarenessSettings_
            .value(QStringLiteral("character_mode"))
            .toString(QStringLiteral("random_visible"));
    if (mode == QStringLiteral("fixed")) {
        return screenAwarenessSettings_.value(QStringLiteral("character")).toString().trimmed();
    }
    QList<ModelCatalogItem> candidates;
    if (mode == QStringLiteral("random_visible") && !activeSpecs_.isEmpty()) {
        QStringList added;
        for (const PetLaunchSpec& spec : activeSpecs_) {
            const QString character = spec.character.trimmed();
            if (character.isEmpty() || added.contains(character)) {
                continue;
            }
            added.append(character);
            const auto found = std::find_if(
                catalog_.cbegin(), catalog_.cend(), [&character](const ModelCatalogItem& model) {
                    return model.character == character;
                });
            if (found != catalog_.cend()) {
                candidates.append(*found);
            }
        }
    }
    if (candidates.isEmpty()) {
        candidates = configuredModels();
    }
    if (candidates.isEmpty()) {
        return {};
    }
    if (mode == QStringLiteral("random_visible") && candidates.size() > 1) {
        return candidates
            .at(QRandomGenerator::global()->bounded(static_cast<int>(candidates.size())))
            .character;
    }
    return candidates.first().character;
}

QByteArray NativeMainWindow::captureNativeDesktop(
    QJsonObject* metadata,
    int maximumWidth) const {
    if (metadata == nullptr) {
        return {};
    }
    QRect desktopGeometry;
    const QList<QScreen*> screens = QGuiApplication::screens();
    for (const QScreen* screen : screens) {
        if (screen != nullptr) {
            desktopGeometry = desktopGeometry.united(screen->geometry());
        }
    }
    const qint64 pixels =
        static_cast<qint64>(desktopGeometry.width()) * desktopGeometry.height();
    if (!desktopGeometry.isValid() || pixels <= 0 || pixels > 100'000'000) {
        return {};
    }
    QImage composite(desktopGeometry.size(), QImage::Format_RGB32);
    if (composite.isNull()) {
        return {};
    }
    composite.fill(Qt::black);
    QPainter painter(&composite);
    bool capturedAny = false;
    for (QScreen* screen : screens) {
        if (screen == nullptr) {
            continue;
        }
        const QPixmap pixmap = screen->grabWindow(0);
        if (pixmap.isNull()) {
            continue;
        }
        const QRect target(
            screen->geometry().topLeft() - desktopGeometry.topLeft(),
            screen->geometry().size());
        painter.drawPixmap(target, pixmap, pixmap.rect());
        capturedAny = true;
    }
    painter.end();
    if (!capturedAny) {
        return {};
    }
    const int maximum = std::clamp(
        maximumWidth > 0
            ? maximumWidth
            : screenAwarenessSettings_
                  .value(QStringLiteral("max_screenshot_width"))
                  .toInt(1920),
        640,
        1920);
    QImage encoded = composite;
    if (std::max(encoded.width(), encoded.height()) > maximum) {
        encoded = encoded.scaled(
            maximum,
            maximum,
            Qt::KeepAspectRatio,
            Qt::SmoothTransformation);
    }
    QByteArray png;
    QBuffer buffer(&png);
    if (!buffer.open(QIODevice::WriteOnly) || !encoded.save(&buffer, "PNG")
        || png.isEmpty() || png.size() > 24 * 1024 * 1024) {
        return {};
    }
    metadata->insert(QStringLiteral("image_width"), encoded.width());
    metadata->insert(QStringLiteral("image_height"), encoded.height());
    metadata->insert(QStringLiteral("desktop_width"), desktopGeometry.width());
    metadata->insert(QStringLiteral("desktop_height"), desktopGeometry.height());
    metadata->insert(QStringLiteral("desktop_left"), desktopGeometry.left());
    metadata->insert(QStringLiteral("desktop_top"), desktopGeometry.top());
    metadata->insert(QStringLiteral("desktop_state"), nativeForegroundDesktopState());
    return png;
}

void NativeMainWindow::handleNativeComputerTool(
    qint64 requestId,
    const QString& toolName,
    const QString& argumentsJson) {
    if (requestId <= 0) {
        return;
    }
    QJsonParseError parseError;
    const QJsonDocument document =
        QJsonDocument::fromJson(argumentsJson.toUtf8(), &parseError);
    if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
        finishNativeComputerTool(
            requestId,
            false,
            tr("Computer tool arguments are not a valid JSON object"),
            false);
        return;
    }
    const QJsonObject arguments = document.object();
    const bool enabled =
        llmSettings_.value(QStringLiteral("computer_use_enabled")).toBool(false);
    auto permission = [this](const QString& key, bool fallback) {
        return llmSettings_.value(key).toBool(fallback);
    };
    if (!enabled) {
        finishNativeComputerTool(
            requestId,
            false,
            tr("Computer Use is disabled in settings"),
            false);
        return;
    }
    auto integerArgument = [&arguments](const QString& key, bool* ok) {
        const QJsonValue value = arguments.value(key);
        if (value.isDouble()) {
            *ok = true;
            return value.toInt();
        }
        if (value.isString()) {
            return value.toString().toInt(ok);
        }
        *ok = false;
        return 0;
    };
    const bool afterActionScreenshot =
        permission(QStringLiteral("computer_use_send_screenshots"), true)
        && permission(QStringLiteral("computer_use_allow_screenshot"), true);

    if (toolName == QStringLiteral("computer_screenshot")) {
        if (!permission(QStringLiteral("computer_use_allow_screenshot"), true)) {
            finishNativeComputerTool(
                requestId,
                false,
                tr("Screenshot capture is disabled in Computer Use settings"),
                false);
            return;
        }
        finishNativeComputerTool(
            requestId,
            true,
            tr("Screenshot captured."),
            true,
            true);
        return;
    }
    if (toolName == QStringLiteral("computer_move")
        || toolName == QStringLiteral("computer_click")
        || toolName == QStringLiteral("computer_double_click")
        || toolName == QStringLiteral("computer_scroll")) {
        if (!permission(QStringLiteral("computer_use_allow_mouse"), false)) {
            finishNativeComputerTool(
                requestId,
                false,
                tr("Mouse control is disabled in Computer Use settings"),
                false);
            return;
        }
        bool xOk = false;
        bool yOk = false;
        const int screenshotX = integerArgument(QStringLiteral("x"), &xOk);
        const int screenshotY = integerArgument(QStringLiteral("y"), &yOk);
        if (!xOk || !yOk) {
            finishNativeComputerTool(
                requestId,
                false,
                tr("Mouse tools require integer x and y coordinates"),
                false);
            return;
        }
        const QPoint desktopPoint = mapNativeComputerPoint(screenshotX, screenshotY);
        QString action;
        if (toolName == QStringLiteral("computer_move")) {
            action = QStringLiteral("move");
        } else if (toolName == QStringLiteral("computer_double_click")) {
            action = QStringLiteral("double_click");
        } else if (toolName == QStringLiteral("computer_scroll")) {
            action = QStringLiteral("scroll");
        } else {
            action = QStringLiteral("click");
        }
        QString button = arguments
                             .value(QStringLiteral("button"))
                             .toString(QStringLiteral("left"))
                             .trimmed()
                             .toLower();
        if (button != QStringLiteral("left") && button != QStringLiteral("right")
            && button != QStringLiteral("middle")) {
            button = QStringLiteral("left");
        }
        bool deltaOk = true;
        const int delta = action == QStringLiteral("scroll")
            ? integerArgument(QStringLiteral("delta"), &deltaOk)
            : 0;
        if (!deltaOk) {
            finishNativeComputerTool(
                requestId,
                false,
                tr("Scroll requires an integer delta"),
                false);
            return;
        }
        QString error;
        if (!nativeComputerMouseAction(
                action,
                desktopPoint,
                button,
                delta,
                &error)) {
            finishNativeComputerTool(requestId, false, error, false);
            return;
        }
        const QString verb = action == QStringLiteral("move")
            ? tr("Mouse moved")
            : action == QStringLiteral("double_click")
            ? tr("Double-clicked")
            : action == QStringLiteral("scroll")
            ? tr("Scrolled")
            : tr("Clicked");
        QString content = tr("%1 at screenshot (%2, %3), mapped to desktop (%4, %5).")
                              .arg(verb)
                              .arg(screenshotX)
                              .arg(screenshotY)
                              .arg(desktopPoint.x())
                              .arg(desktopPoint.y());
        if (action == QStringLiteral("scroll")) {
            content += tr(" Delta: %1.").arg(delta);
        }
        finishNativeComputerTool(
            requestId,
            true,
            content,
            afterActionScreenshot);
        return;
    }
    if (toolName == QStringLiteral("computer_type")) {
        if (!permission(QStringLiteral("computer_use_allow_keyboard"), false)) {
            finishNativeComputerTool(
                requestId,
                false,
                tr("Keyboard input is disabled in Computer Use settings"),
                false);
            return;
        }
        const QString rawText = arguments.value(QStringLiteral("text")).toString();
        const QString text = rawText.left(2'000);
        QString error;
        if (!nativeComputerTypeText(text, &error)) {
            finishNativeComputerTool(requestId, false, error, false);
            return;
        }
        QString content = tr("Typed %1 characters.").arg(text.size());
        if (rawText.size() > text.size()) {
            content += tr(" Input was truncated to the safety limit.");
        }
        finishNativeComputerTool(
            requestId,
            true,
            content,
            afterActionScreenshot);
        return;
    }
    if (toolName == QStringLiteral("computer_key")) {
        if (!permission(QStringLiteral("computer_use_allow_keyboard"), false)) {
            finishNativeComputerTool(
                requestId,
                false,
                tr("Keyboard input is disabled in Computer Use settings"),
                false);
            return;
        }
        const QString keys =
            arguments.value(QStringLiteral("keys")).toString().trimmed().left(100);
        QString error;
        if (!nativeComputerPressKeys(keys, &error)) {
            finishNativeComputerTool(requestId, false, error, false);
            return;
        }
        finishNativeComputerTool(
            requestId,
            true,
            tr("Pressed key: %1.").arg(keys),
            afterActionScreenshot);
        return;
    }
    if (toolName == QStringLiteral("computer_set_clipboard")) {
        if (!permission(QStringLiteral("computer_use_allow_clipboard"), false)) {
            finishNativeComputerTool(
                requestId,
                false,
                tr("Clipboard writes are disabled in Computer Use settings"),
                false);
            return;
        }
        const QString text =
            arguments.value(QStringLiteral("text")).toString().left(100'000);
        QGuiApplication::clipboard()->setText(text);
        finishNativeComputerTool(
            requestId,
            true,
            tr("Clipboard updated with %1 characters.").arg(text.size()),
            false);
        return;
    }
    if (toolName == QStringLiteral("computer_wait")) {
        if (!permission(QStringLiteral("computer_use_allow_wait"), true)) {
            finishNativeComputerTool(
                requestId,
                false,
                tr("Wait is disabled in Computer Use settings"),
                false);
            return;
        }
        bool secondsOk = false;
        double seconds = arguments.value(QStringLiteral("seconds")).toVariant().toDouble(&secondsOk);
        if (!secondsOk) {
            seconds = 2.0;
        }
        seconds = std::clamp(seconds, 0.1, 10.0);
        pendingComputerWaitRequests_.insert(requestId);
        QTimer::singleShot(
            qRound(seconds * 1'000.0),
            this,
            [this, requestId, seconds, afterActionScreenshot]() {
                if (!pendingComputerWaitRequests_.remove(requestId)) {
                    return;
                }
                finishNativeComputerTool(
                    requestId,
                    true,
                    tr("Waited %1 seconds.").arg(seconds, 0, 'f', 1),
                    afterActionScreenshot);
            });
        return;
    }
    finishNativeComputerTool(
        requestId,
        false,
        tr("Unsupported computer tool: %1").arg(toolName),
        false);
}

void NativeMainWindow::finishNativeComputerTool(
    qint64 requestId,
    bool succeeded,
    const QString& content,
    bool includeScreenshot,
    bool screenshotRequired) {
    QString resultContent = content;
    QJsonArray extraMessages;
    if (includeScreenshot) {
        QJsonObject metadata;
        const int maximumWidth = std::clamp(
            llmSettings_
                .value(QStringLiteral("computer_use_max_screenshot_width"))
                .toInt(1280),
            640,
            1920);
        const QByteArray png = captureNativeDesktop(&metadata, maximumWidth);
        if (png.isEmpty()) {
            resultContent += tr(" Screenshot capture failed or returned no pixels.");
            if (screenshotRequired) {
                succeeded = false;
            }
        } else {
            computerScreenshotMetrics_ = metadata;
            const QString coordinateHint = tr(
                "Latest screenshot image is %1x%2; real desktop coordinate space is %3x%4 at origin (%5, %6). Use screenshot image coordinates for later mouse tools; the app maps them to the real desktop.")
                                               .arg(metadata.value(QStringLiteral("image_width")).toInt())
                                               .arg(metadata.value(QStringLiteral("image_height")).toInt())
                                               .arg(metadata.value(QStringLiteral("desktop_width")).toInt())
                                               .arg(metadata.value(QStringLiteral("desktop_height")).toInt())
                                               .arg(metadata.value(QStringLiteral("desktop_left")).toInt())
                                               .arg(metadata.value(QStringLiteral("desktop_top")).toInt());
            resultContent += QStringLiteral(" ") + coordinateHint;
            const QString dataUrl = QStringLiteral("data:image/png;base64,")
                + QString::fromLatin1(png.toBase64());
            extraMessages.append(QJsonObject {
                {QStringLiteral("role"), QStringLiteral("user")},
                {QStringLiteral("content"), QJsonArray {
                     QJsonObject {
                         {QStringLiteral("type"), QStringLiteral("text")},
                         {QStringLiteral("text"),
                          tr("Computer Use screenshot after the last action. %1 Use the image to decide the next UI step; do not mention tool internals unless the user asked.")
                              .arg(coordinateHint)},
                     },
                     QJsonObject {
                         {QStringLiteral("type"), QStringLiteral("image_url")},
                         {QStringLiteral("image_url"), QJsonObject {
                              {QStringLiteral("url"), dataUrl},
                          }},
                     },
                 }},
            });
        }
    }
    const QJsonObject result {
        {QStringLiteral("succeeded"), succeeded},
        {QStringLiteral("content"), resultContent},
        {QStringLiteral("extra_messages"), extraMessages},
    };
    backend_.completeComputerTool(requestId, compactJson(result));
}

QPoint NativeMainWindow::mapNativeComputerPoint(
    int screenshotX,
    int screenshotY) const {
    if (computerScreenshotMetrics_.isEmpty()) {
        return {screenshotX, screenshotY};
    }
    const int imageWidth =
        std::max(1, computerScreenshotMetrics_.value(QStringLiteral("image_width")).toInt(1));
    const int imageHeight =
        std::max(1, computerScreenshotMetrics_.value(QStringLiteral("image_height")).toInt(1));
    const int desktopLeft =
        computerScreenshotMetrics_.value(QStringLiteral("desktop_left")).toInt(0);
    const int desktopTop =
        computerScreenshotMetrics_.value(QStringLiteral("desktop_top")).toInt(0);
    const int desktopWidth = std::max(
        1,
        computerScreenshotMetrics_
            .value(QStringLiteral("desktop_width"))
            .toInt(imageWidth));
    const int desktopHeight = std::max(
        1,
        computerScreenshotMetrics_
            .value(QStringLiteral("desktop_height"))
            .toInt(imageHeight));
    const bool withinImage = screenshotX >= -1 && screenshotX <= imageWidth + 1
        && screenshotY >= -1 && screenshotY <= imageHeight + 1;
    if (withinImage && (imageWidth != desktopWidth || imageHeight != desktopHeight)) {
        const int clippedX = std::clamp(screenshotX, 0, imageWidth - 1);
        const int clippedY = std::clamp(screenshotY, 0, imageHeight - 1);
        const int mappedX = imageWidth <= 1 || desktopWidth <= 1
            ? desktopLeft
            : desktopLeft
                + qRound(
                    static_cast<double>(clippedX) * (desktopWidth - 1)
                    / (imageWidth - 1));
        const int mappedY = imageHeight <= 1 || desktopHeight <= 1
            ? desktopTop
            : desktopTop
                + qRound(
                    static_cast<double>(clippedY) * (desktopHeight - 1)
                    / (imageHeight - 1));
        return {mappedX, mappedY};
    }
    return {
        std::clamp(screenshotX, desktopLeft, desktopLeft + desktopWidth - 1),
        std::clamp(screenshotY, desktopTop, desktopTop + desktopHeight - 1),
    };
}

QJsonObject NativeMainWindow::nativeForegroundDesktopState() const {
    QJsonObject state {
        {QStringLiteral("state"), QStringLiteral("desktop")},
        {QStringLiteral("label"), QStringLiteral("使用电脑")},
        {QStringLiteral("confidence"), 0.5},
        {QStringLiteral("reason"), QStringLiteral("Qt native foreground context")},
        {QStringLiteral("captured_at"), currentLocalDateTime()},
    };
#ifdef Q_OS_WIN
    LASTINPUTINFO inputInfo {};
    inputInfo.cbSize = sizeof(inputInfo);
    if (GetLastInputInfo(&inputInfo)) {
        const DWORD idleMilliseconds = GetTickCount() - inputInfo.dwTime;
        const int idleSeconds = static_cast<int>(idleMilliseconds / 1'000);
        state.insert(QStringLiteral("idle_seconds"), idleSeconds);
        state.insert(QStringLiteral("idle_threshold_seconds"), 180);
        if (idleSeconds >= 180) {
            state.insert(QStringLiteral("state"), QStringLiteral("idle"));
            state.insert(QStringLiteral("label"), QStringLiteral("发呆/离开"));
            state.insert(QStringLiteral("confidence"), 0.95);
            state.insert(
                QStringLiteral("reason"),
                QStringLiteral("Keyboard and pointer have been idle"));
        }
    }
    const HWND window = GetForegroundWindow();
    if (window != nullptr) {
        if (screenAwarenessSettings_
                .value(QStringLiteral("include_window_title"))
                .toBool(false)) {
            wchar_t title[141] = {};
            const int length = GetWindowTextW(window, title, 141);
            if (length > 0) {
                state.insert(
                    QStringLiteral("foreground_title"),
                    QString::fromWCharArray(title, length));
            }
        }
        if (screenAwarenessSettings_
                .value(QStringLiteral("include_process_name"))
                .toBool(true)) {
            DWORD processId = 0;
            GetWindowThreadProcessId(window, &processId);
            HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, processId);
            if (process != nullptr) {
                wchar_t path[4096] = {};
                DWORD length = 4096;
                if (QueryFullProcessImageNameW(process, 0, path, &length) && length > 0) {
                    const QFileInfo info(QString::fromWCharArray(path, static_cast<int>(length)));
                    state.insert(
                        QStringLiteral("process_name"),
                        info.fileName().toLower());
                    state.insert(QStringLiteral("app_name"), info.completeBaseName());
                }
                CloseHandle(process);
            }
        }
    }
#endif
    return state;
}

void NativeMainWindow::triggerNativeScreenAwareness(bool force) {
    screenAwarenessTimer_.stop();
    if (activeScreenAwarenessRequestId_ != 0) {
        screenAwarenessStatusLabel_->setText(tr("A screen-awareness analysis is already running"));
        return;
    }
    if (!force
        && !screenAwarenessSettings_.value(QStringLiteral("enabled")).toBool(false)) {
        return;
    }
    const QString character = chooseNativeScreenAwarenessCharacter();
    if (character.isEmpty()) {
        screenAwarenessStatusLabel_->setText(
            tr("No configured character is available for screen awareness"));
        scheduleNativeScreenAwareness();
        return;
    }
    QJsonObject capture;
    const QByteArray png = captureNativeDesktop(&capture);
    if (png.isEmpty()) {
        screenAwarenessStatusLabel_->setText(
            tr("Qt could not capture the desktop, or the PNG exceeded the safety limit"));
        scheduleNativeScreenAwareness();
        return;
    }
    capture.insert(QStringLiteral("character"), character);
    QString displayName = displayNameForCharacter(character).trimmed();
    if (displayName.isEmpty()) {
        displayName = character;
    }
    capture.insert(QStringLiteral("display_name"), displayName);
    capture.insert(QStringLiteral("local_datetime"), currentLocalDateTime());
    const qint64 requestId = backend_.startScreenAwareness(
        configPath_,
        projectRoot_,
        nativeDatabasePath(),
        compactJson(capture),
        png,
        force);
    if (requestId <= 0) {
        screenAwarenessStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        scheduleNativeScreenAwareness();
        return;
    }
    activeScreenAwarenessRequestId_ = requestId;
    screenAwarenessTestButton_->setEnabled(false);
    screenAwarenessCancelButton_->setEnabled(true);
    screenAwarenessStatusLabel_->setText(
        tr("Desktop captured; Rust is asking the configured model whether to speak…"));
}

void NativeMainWindow::handleNativeScreenAwarenessEvent(const QString& payloadJson) {
    const QJsonObject payload = parseObject(payloadJson);
    const qint64 requestId = payload.value(QStringLiteral("request_id")).toInteger();
    if (requestId <= 0 || requestId != activeScreenAwarenessRequestId_) {
        return;
    }
    activeScreenAwarenessRequestId_ = 0;
    screenAwarenessTestButton_->setEnabled(true);
    screenAwarenessCancelButton_->setEnabled(false);
    const QString state = payload.value(QStringLiteral("state")).toString();
    if (state == QStringLiteral("finished")) {
        const QString text = payload.value(QStringLiteral("text")).toString().trimmed();
        const QString character = payload.value(QStringLiteral("character")).toString().trimmed();
        QString displayName = payload.value(QStringLiteral("display_name")).toString().trimmed();
        if (displayName.isEmpty()) {
            displayName = displayNameForCharacter(character).trimmed();
        }
        if (displayName.isEmpty()) {
            displayName = QStringLiteral("BandoriPet");
        }
        const QJsonArray actions = payload.value(QStringLiteral("actions")).toArray();
        const QString action = actions.isEmpty()
            ? QStringLiteral("surprised")
            : actions.first().toString(QStringLiteral("surprised"));
        if (payload.value(QStringLiteral("display_mode")).toString()
                == QStringLiteral("system")
            && trayIcon_ != nullptr) {
            trayIcon_->showMessage(
                displayName, text, QSystemTrayIcon::Information, 15'000);
            if (!action.isEmpty()) {
                supervisor_.broadcastControlLine(
                    QStringLiteral("ACTION\t%1\t%2").arg(character, action));
            }
        } else {
            QJsonObject event {
                {QStringLiteral("source"), QStringLiteral("screen_awareness")},
                {QStringLiteral("kind"), QStringLiteral("screen_awareness")},
                {QStringLiteral("state"), QStringLiteral("done")},
                {QStringLiteral("mode"), QStringLiteral("replace_raw")},
                {QStringLiteral("character"), character},
                {QStringLiteral("title"), displayName},
                {QStringLiteral("text"), text},
                {QStringLiteral("action"), action},
                {QStringLiteral("ttl_ms"), 18'000},
                {QStringLiteral("anchor_to_pet"), true},
            };
            supervisor_.broadcastControlLine(
                QStringLiteral("REMINDER_EVENT\t") + compactJson(event));
        }
        const double ttsRate = dispatchNativeEmotionBehavior(text, character, actions);
        enqueueNativeTts(text, character, false, ttsRate);
        const QString warning =
            payload.value(QStringLiteral("auxiliary_warning")).toString().trimmed();
        screenAwarenessStatusLabel_->setText(
            warning.isEmpty()
                ? tr("Screen awareness delivered a proactive character message")
                : tr("Message delivered after auxiliary-model fallback: %1").arg(warning));
    } else if (state == QStringLiteral("no_speak")) {
        screenAwarenessStatusLabel_->setText(
            tr("The character decided not to interrupt this time"));
    } else if (state == QStringLiteral("cancelled")) {
        screenAwarenessStatusLabel_->setText(tr("Native screen-awareness analysis cancelled"));
    } else {
        QString message = payload.value(QStringLiteral("message")).toString().trimmed();
        if (message.isEmpty()) {
            message = tr("Native screen-awareness analysis failed");
        }
        screenAwarenessStatusLabel_->setText(message);
        serviceStatusLabel_->setText(message);
    }
    scheduleNativeScreenAwareness();
}

void NativeMainWindow::stopNativeScreenAwareness() {
    screenAwarenessTimer_.stop();
    if (activeScreenAwarenessRequestId_ != 0) {
        backend_.cancelScreenAwareness(activeScreenAwarenessRequestId_);
    }
    if (screenAwarenessStatusLabel_ != nullptr) {
        screenAwarenessStatusLabel_->setText(tr("Native screen awareness stopped"));
    }
    if (screenAwarenessCancelButton_ != nullptr) {
        screenAwarenessCancelButton_->setEnabled(activeScreenAwarenessRequestId_ != 0);
    }
}

void NativeMainWindow::loadNativeIntegrationSettings() {
    if (integrationStatusLabel_ == nullptr) {
        return;
    }
    if (!backend_.loadIntegrationSettings(configPath_)
        || !backend_.loadNapcatSettings(configPath_)) {
        integrationStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        return;
    }
    integrationSettings_ = parseObject(backend_.getIntegrationSettingsJson());
    napcatSettings_ = parseObject(backend_.getNapcatSettingsJson());
    syncNativeIntegrationControls();
}

void NativeMainWindow::syncNativeIntegrationControls() {
    if (chatIntegrationEnabledSwitch_ == nullptr) {
        return;
    }
    const QSignalBlocker chatEnabledBlocker(chatIntegrationEnabledSwitch_);
    const QSignalBlocker chatPortBlocker(chatIntegrationPortSpinBox_);
    const QSignalBlocker chatOverlayBlocker(chatIntegrationOverlaySwitch_);
    const QSignalBlocker chatContextBlocker(chatIntegrationContextSwitch_);
    const QSignalBlocker aiEnabledBlocker(aiStatusEnabledSwitch_);
    const QSignalBlocker compactBlocker(compactAiWindowSwitch_);
    const QSignalBlocker compactOpacityBlocker(compactAiWindowOpacitySpinBox_);
    const QSignalBlocker compactFontBlocker(compactAiWindowFontSizeSpinBox_);
    const QSignalBlocker aiOverlayBlocker(aiEventOverlaySwitch_);
    const QSignalBlocker aiPortBlocker(aiStatusPortSpinBox_);
    const QSignalBlocker napcatEnabledBlocker(napcatEnabledSwitch_);
    const QSignalBlocker napcatAutoReplyBlocker(napcatAutoReplySwitch_);
    const QSignalBlocker napcatPrivateBlocker(napcatReplyPrivateSwitch_);
    const QSignalBlocker napcatAtBlocker(napcatGroupAtOnlySwitch_);
    const QSignalBlocker napcatMentionBlocker(napcatMentionSenderSwitch_);
    chatIntegrationEnabledSwitch_->setChecked(
        integrationSettings_.value(QStringLiteral("chat_enabled")).toBool(false));
    chatIntegrationPortSpinBox_->setValue(
        integrationSettings_.value(QStringLiteral("chat_port")).toInt(38'473));
    chatIntegrationOverlaySwitch_->setChecked(
        integrationSettings_
            .value(QStringLiteral("chat_overlay_enabled"))
            .toBool(true));
    chatIntegrationContextSwitch_->setChecked(
        integrationSettings_
            .value(QStringLiteral("chat_include_context"))
            .toBool(true));
    aiStatusEnabledSwitch_->setChecked(
        integrationSettings_
            .value(QStringLiteral("ai_status_enabled"))
            .toBool(false));
    compactAiWindowSwitch_->setChecked(
        integrationSettings_
            .value(QStringLiteral("compact_ai_window_enabled"))
            .toBool(false));
    compactAiWindowOpacitySpinBox_->setValue(
        integrationSettings_.value(QStringLiteral("compact_ai_window_opacity")).toInt(44));
    compactAiWindowFontSizeSpinBox_->setValue(
        integrationSettings_.value(QStringLiteral("compact_ai_window_font_size")).toInt(12));
    compactAiWindowBackgroundEdit_->setText(
        integrationSettings_
            .value(QStringLiteral("compact_ai_window_background_color"))
            .toString(QStringLiteral("#fb7299")));
    compactAiWindowTextEdit_->setText(
        integrationSettings_
            .value(QStringLiteral("compact_ai_window_text_color"))
            .toString(QStringLiteral("#24242a")));
    aiEventOverlaySwitch_->setChecked(
        integrationSettings_
            .value(QStringLiteral("ai_event_overlay_enabled"))
            .toBool(false));
    aiStatusPortSpinBox_->setValue(
        integrationSettings_.value(QStringLiteral("ai_status_port")).toInt(38'472));
    napcatEnabledSwitch_->setChecked(
        napcatSettings_.value(QStringLiteral("enabled")).toBool(false));
    napcatUrlEdit_->setText(
        napcatSettings_
            .value(QStringLiteral("ws_url"))
            .toString(QStringLiteral("ws://127.0.0.1:3001")));
    napcatAutoReplySwitch_->setChecked(
        napcatSettings_.value(QStringLiteral("auto_reply_enabled")).toBool(false));
    napcatReplyPrivateSwitch_->setChecked(
        napcatSettings_.value(QStringLiteral("reply_private")).toBool(true));
    napcatGroupAtOnlySwitch_->setChecked(
        napcatSettings_.value(QStringLiteral("reply_group_at_only")).toBool(true));
    napcatMentionSenderSwitch_->setChecked(
        napcatSettings_.value(QStringLiteral("reply_mention_sender")).toBool(true));
    napcatReplyCharacterEdit_->setText(
        napcatSettings_.value(QStringLiteral("reply_character")).toString());
    const auto setCombo = [](qfw::ComboBox* combo, const QString& value, int fallback) {
        const int index = combo->findData(value);
        combo->setCurrentIndex(index < 0 ? fallback : index);
    };
    setCombo(
        napcatSavePolicyComboBox_,
        napcatSettings_
            .value(QStringLiteral("save_policy"))
            .toString(QStringLiteral("all")),
        0);
    setCombo(
        napcatGroupRetentionModeComboBox_,
        napcatSettings_
            .value(QStringLiteral("group_retention_mode"))
            .toString(QStringLiteral("manual")),
        0);
    napcatGroupRetentionDaysSpinBox_->setValue(
        napcatSettings_.value(QStringLiteral("group_retention_days")).toInt(7));
    napcatGroupRetentionDaysSpinBox_->setEnabled(
        napcatGroupRetentionModeComboBox_->currentData().toString()
        == QStringLiteral("auto"));
    setCombo(
        napcatPrivateRetentionModeComboBox_,
        napcatSettings_
            .value(QStringLiteral("private_retention_mode"))
            .toString(QStringLiteral("manual")),
        0);
    napcatPrivateRetentionDaysSpinBox_->setValue(
        napcatSettings_.value(QStringLiteral("private_retention_days")).toInt(30));
    napcatPrivateRetentionDaysSpinBox_->setEnabled(
        napcatPrivateRetentionModeComboBox_->currentData().toString()
        == QStringLiteral("auto"));
    chatIntegrationTokenEdit_->clear();
    aiStatusTokenEdit_->clear();
    napcatTokenEdit_->clear();
    chatIntegrationClearTokenCheckBox_->setChecked(false);
    aiStatusClearTokenCheckBox_->setChecked(false);
    napcatClearTokenCheckBox_->setChecked(false);
    chatIntegrationTokenEdit_->setPlaceholderText(
        integrationSettings_
                .value(QStringLiteral("chat_token_configured"))
                .toBool(false)
            ? tr("Saved token configured — blank keeps it")
            : tr("No saved token — enabling generates one"));
    aiStatusTokenEdit_->setPlaceholderText(
        integrationSettings_
                .value(QStringLiteral("ai_status_token_configured"))
                .toBool(false)
            ? tr("Saved token configured — blank keeps it")
            : tr("No saved token — enabling generates one"));
    napcatTokenEdit_->setPlaceholderText(
        napcatSettings_
                .value(QStringLiteral("access_token_configured"))
                .toBool(false)
            ? tr("Saved NapCat token configured — blank keeps it")
            : tr("No saved NapCat token"));
}

bool NativeMainWindow::saveNativeIntegrationSettings() {
    if (chatIntegrationEnabledSwitch_ == nullptr) {
        return false;
    }
    QJsonObject settings {
        {QStringLiteral("chat_enabled"), chatIntegrationEnabledSwitch_->isChecked()},
        {QStringLiteral("chat_port"), chatIntegrationPortSpinBox_->value()},
        {QStringLiteral("chat_overlay_enabled"),
         chatIntegrationOverlaySwitch_->isChecked()},
        {QStringLiteral("chat_include_context"),
         chatIntegrationContextSwitch_->isChecked()},
        {QStringLiteral("clear_chat_token"),
         chatIntegrationClearTokenCheckBox_->isChecked()},
        {QStringLiteral("compact_ai_window_enabled"),
         compactAiWindowSwitch_->isChecked()},
        {QStringLiteral("compact_ai_window_opacity"),
         compactAiWindowOpacitySpinBox_->value()},
        {QStringLiteral("compact_ai_window_font_size"),
         compactAiWindowFontSizeSpinBox_->value()},
        {QStringLiteral("compact_ai_window_background_color"),
         compactAiWindowBackgroundEdit_->text().trimmed()},
        {QStringLiteral("compact_ai_window_text_color"),
         compactAiWindowTextEdit_->text().trimmed()},
        {QStringLiteral("ai_event_overlay_enabled"),
         aiEventOverlaySwitch_->isChecked()},
        {QStringLiteral("ai_status_enabled"), aiStatusEnabledSwitch_->isChecked()},
        {QStringLiteral("ai_status_port"), aiStatusPortSpinBox_->value()},
        {QStringLiteral("clear_ai_status_token"),
         aiStatusClearTokenCheckBox_->isChecked()},
    };
    const QString chatToken = chatIntegrationTokenEdit_->text().trimmed();
    if (!chatToken.isEmpty()) {
        settings.insert(QStringLiteral("chat_token"), chatToken);
    }
    const QString aiToken = aiStatusTokenEdit_->text().trimmed();
    if (!aiToken.isEmpty()) {
        settings.insert(QStringLiteral("ai_status_token"), aiToken);
    }
    QJsonObject napcatSettings {
        {QStringLiteral("enabled"), napcatEnabledSwitch_->isChecked()},
        {QStringLiteral("ws_url"), napcatUrlEdit_->text().trimmed()},
        {QStringLiteral("clear_access_token"),
         napcatClearTokenCheckBox_->isChecked()},
        {QStringLiteral("auto_reply_enabled"), napcatAutoReplySwitch_->isChecked()},
        {QStringLiteral("reply_private"), napcatReplyPrivateSwitch_->isChecked()},
        {QStringLiteral("reply_group_at_only"),
         napcatGroupAtOnlySwitch_->isChecked()},
        {QStringLiteral("reply_mention_sender"),
         napcatMentionSenderSwitch_->isChecked()},
        {QStringLiteral("reply_character"),
         napcatReplyCharacterEdit_->text().trimmed()},
        {QStringLiteral("save_policy"),
         napcatSavePolicyComboBox_->currentData().toString()},
        {QStringLiteral("group_retention_mode"),
         napcatGroupRetentionModeComboBox_->currentData().toString()},
        {QStringLiteral("group_retention_days"),
         napcatGroupRetentionDaysSpinBox_->value()},
        {QStringLiteral("private_retention_mode"),
         napcatPrivateRetentionModeComboBox_->currentData().toString()},
        {QStringLiteral("private_retention_days"),
         napcatPrivateRetentionDaysSpinBox_->value()},
    };
    const QString napcatToken = napcatTokenEdit_->text().trimmed();
    if (!napcatToken.isEmpty()) {
        napcatSettings.insert(QStringLiteral("access_token"), napcatToken);
    }
    if (!backend_.saveNapcatSettings(configPath_, compactJson(napcatSettings))) {
        integrationStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        return false;
    }
    if (!backend_.saveIntegrationSettings(configPath_, compactJson(settings))) {
        integrationStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        return false;
    }
    integrationSettings_ = parseObject(backend_.getIntegrationSettingsJson());
    napcatSettings_ = parseObject(backend_.getNapcatSettingsJson());
    runtime_.insert(
        QStringLiteral("compact_ai_window_enabled"),
        integrationSettings_.value(QStringLiteral("compact_ai_window_enabled")));
    for (const QString& key : {
             QStringLiteral("compact_ai_window_opacity"),
             QStringLiteral("compact_ai_window_font_size"),
             QStringLiteral("compact_ai_window_background_color"),
             QStringLiteral("compact_ai_window_text_color")}) {
        runtime_.insert(key, integrationSettings_.value(key));
    }
    runtime_.insert(
        QStringLiteral("ai_event_overlay_enabled"),
        integrationSettings_.value(QStringLiteral("ai_event_overlay_enabled")));
    runtime_.insert(
        QStringLiteral("chat_integration_overlay_enabled"),
        integrationSettings_.value(QStringLiteral("chat_overlay_enabled")));
    for (PetLaunchSpec& spec : activeSpecs_) {
        spec.compactAiWindowEnabled = integrationSettings_
                                          .value(QStringLiteral("compact_ai_window_enabled"))
                                          .toBool(false);
        spec.compactAiWindowOpacity = integrationSettings_
                                          .value(QStringLiteral("compact_ai_window_opacity"))
                                          .toInt(44);
        spec.compactAiWindowFontSize = integrationSettings_
                                           .value(QStringLiteral("compact_ai_window_font_size"))
                                           .toInt(12);
        spec.compactAiWindowBackgroundColor = integrationSettings_
                                                   .value(QStringLiteral(
                                                       "compact_ai_window_background_color"))
                                                   .toString(QStringLiteral("#fb7299"));
        spec.compactAiWindowTextColor = integrationSettings_
                                             .value(QStringLiteral(
                                                 "compact_ai_window_text_color"))
                                             .toString(QStringLiteral("#24242a"));
        spec.aiEventOverlayEnabled = integrationSettings_
                                         .value(QStringLiteral("ai_event_overlay_enabled"))
                                         .toBool(false);
        spec.chatIntegrationOverlayEnabled = integrationSettings_
                                                  .value(QStringLiteral(
                                                      "chat_overlay_enabled"))
                                                  .toBool(true);
    }
    if (supervisor_.isRunning()) {
        supervisor_.broadcastSettings(compactJson({
            {QStringLiteral("compact_ai_window_enabled"),
             integrationSettings_
                 .value(QStringLiteral("compact_ai_window_enabled"))},
            {QStringLiteral("compact_ai_window_opacity"),
             integrationSettings_
                 .value(QStringLiteral("compact_ai_window_opacity"))},
            {QStringLiteral("compact_ai_window_font_size"),
             integrationSettings_
                 .value(QStringLiteral("compact_ai_window_font_size"))},
            {QStringLiteral("compact_ai_window_background_color"),
             integrationSettings_
                 .value(QStringLiteral("compact_ai_window_background_color"))},
            {QStringLiteral("compact_ai_window_text_color"),
             integrationSettings_
                 .value(QStringLiteral("compact_ai_window_text_color"))},
            {QStringLiteral("ai_event_overlay_enabled"),
             integrationSettings_
                 .value(QStringLiteral("ai_event_overlay_enabled"))},
            {QStringLiteral("chat_integration_overlay_enabled"),
             integrationSettings_
                 .value(QStringLiteral("chat_overlay_enabled"))},
        }));
    }
    syncNativeIntegrationControls();
    serviceStatusLabel_->setText(backend_.getStatus());
    integrationStatusLabel_->setText(tr("Native integration settings saved"));
    return true;
}

bool NativeMainWindow::restartNativeIntegrationServices() {
    const QString databasePath = nativeDatabasePath();
    if (!backend_.startIntegrationServices(configPath_, databasePath)) {
        integrationStatus_ = parseObject(backend_.getIntegrationStatusJson());
        integrationStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        startNativeNapcat();
        return false;
    }
    integrationSettings_ = parseObject(backend_.getIntegrationSettingsJson());
    integrationStatus_ = parseObject(backend_.getIntegrationStatusJson());
    syncNativeIntegrationControls();
    const bool chatRunning =
        integrationStatus_.value(QStringLiteral("chat_running")).toBool(false);
    const bool aiRunning =
        integrationStatus_.value(QStringLiteral("ai_status_running")).toBool(false);
    startNativeNapcat();
    const bool napcatEnabled =
        napcatSettings_.value(QStringLiteral("enabled")).toBool(false);
    QStringList endpoints;
    if (chatRunning) {
        endpoints.append(
            QStringLiteral("chat http://127.0.0.1:%1/chat-events")
                .arg(integrationStatus_.value(QStringLiteral("chat_port")).toInt()));
    }
    if (aiRunning) {
        endpoints.append(
            QStringLiteral("AI http://127.0.0.1:%1/ai-events")
                .arg(integrationStatus_.value(QStringLiteral("ai_status_port")).toInt()));
    }
    if (napcatEnabled) {
        endpoints.append(
            tr("NapCat %1")
                .arg(napcatSettings_.value(QStringLiteral("ws_url")).toString()));
    }
    integrationStatusLabel_->setText(
        endpoints.isEmpty()
            ? tr("Native integration services are disabled.")
            : tr("Listening on %1. Requests are limited to 1 MiB with a five-second timeout.")
                  .arg(endpoints.join(QStringLiteral(" · "))));
    integrationStopButton_->setEnabled(chatRunning || aiRunning || napcatEnabled);
    serviceStatusLabel_->setText(backend_.getStatus());
    return true;
}

void NativeMainWindow::stopNativeIntegrationServices() {
    stopNativeNapcat();
    backend_.stopIntegrationServices();
    integrationStatus_ = parseObject(backend_.getIntegrationStatusJson());
    if (integrationStatusLabel_ != nullptr) {
        integrationStatusLabel_->setText(tr("Native integration services stopped."));
    }
    if (integrationStopButton_ != nullptr) {
        integrationStopButton_->setEnabled(false);
    }
}

void NativeMainWindow::handleNativeIntegrationEvent(const QString& payloadJson) {
    const QJsonObject event = parseObject(payloadJson);
    const QString kind = event.value(QStringLiteral("kind")).toString();
    const QJsonObject payload = event.value(QStringLiteral("payload")).toObject();
    if (payload.isEmpty()) {
        return;
    }
    if (kind == QStringLiteral("chat_overlay")) {
        supervisor_.broadcastControlLine(
            QStringLiteral("CHAT_EVENT\t") + compactJson(payload));
        if (integrationStatusLabel_ != nullptr) {
            integrationStatusLabel_->setText(
                payload.value(QStringLiteral("state")).toString()
                        == QStringLiteral("clear")
                    ? tr("External chat unread state was explicitly cleared.")
                    : tr("External chat message stored and forwarded to native pets."));
        }
    } else if (kind == QStringLiteral("ai_event")) {
        supervisor_.broadcastControlLine(
            QStringLiteral("AI_EVENT\t") + compactJson(payload));
        if (integrationStatusLabel_ != nullptr) {
            integrationStatusLabel_->setText(
                tr("AI status event authenticated and forwarded to native pets."));
        }
    }
}

void NativeMainWindow::startNativeNapcat() {
    stopNativeNapcat();
    if (!backend_.loadNapcatSettings(configPath_)) {
        if (napcatStatusLabel_ != nullptr) {
            napcatStatusLabel_->setText(backend_.getStatus());
        }
        return;
    }
    napcatSettings_ = parseObject(backend_.getNapcatSettingsJson());
    if (!napcatSettings_.value(QStringLiteral("enabled")).toBool(false)) {
        if (napcatStatusLabel_ != nullptr) {
            napcatStatusLabel_->setText(tr("NapCat is disabled."));
        }
        return;
    }
    const QUrl url(
        napcatSettings_.value(QStringLiteral("ws_url")).toString().trimmed());
    if (!url.isValid()
        || (url.scheme() != QStringLiteral("ws")
            && url.scheme() != QStringLiteral("wss"))
        || url.host().isEmpty()) {
        if (napcatStatusLabel_ != nullptr) {
            napcatStatusLabel_->setText(
                tr("NapCat URL must be a valid ws:// or wss:// address."));
        }
        return;
    }
    napcatStopping_ = false;
    auto* socket = new QWebSocket(QString(), QWebSocketProtocol::VersionLatest, this);
    socket->setMaxAllowedIncomingFrameSize(1024 * 1024);
    socket->setMaxAllowedIncomingMessageSize(1024 * 1024);
    napcatSocket_ = socket;
    connect(socket, &QWebSocket::connected, this, [this, socket]() {
        if (socket != napcatSocket_) {
            return;
        }
        if (napcatStatusLabel_ != nullptr) {
            napcatStatusLabel_->setText(tr("NapCat connected."));
        }
    });
    connect(socket, &QWebSocket::disconnected, this, [this, socket]() {
        if (socket != napcatSocket_ || napcatStopping_) {
            return;
        }
        if (napcatStatusLabel_ != nullptr) {
            napcatStatusLabel_->setText(tr("NapCat disconnected; reconnecting…"));
        }
        scheduleNativeNapcatReconnect();
    });
    connect(
        socket,
        &QWebSocket::errorOccurred,
        this,
        [this, socket](QAbstractSocket::SocketError) {
            if (socket != napcatSocket_ || napcatStopping_) {
                return;
            }
            if (napcatStatusLabel_ != nullptr) {
                napcatStatusLabel_->setText(
                    tr("NapCat connection error: %1; reconnecting…")
                        .arg(socket->errorString()));
            }
            scheduleNativeNapcatReconnect();
        });
    connect(
        socket,
        &QWebSocket::textMessageReceived,
        this,
        [this, socket](const QString& message) {
            if (socket == napcatSocket_) {
                handleNativeNapcatMessage(message);
            }
        });
    connectNativeNapcat();
}

void NativeMainWindow::stopNativeNapcat() {
    napcatStopping_ = true;
    napcatReconnectTimer_.stop();
    for (qint64 requestId : std::as_const(activeNapcatReplyIds_)) {
        backend_.cancelNapcatReply(requestId);
    }
    activeNapcatReplyIds_.clear();
    if (napcatSocket_ != nullptr) {
        QWebSocket* socket = napcatSocket_;
        napcatSocket_ = nullptr;
        socket->abort();
        socket->deleteLater();
    }
    if (napcatStatusLabel_ != nullptr) {
        napcatStatusLabel_->setText(tr("NapCat is stopped."));
    }
}

void NativeMainWindow::connectNativeNapcat() {
    if (napcatStopping_ || napcatSocket_ == nullptr) {
        return;
    }
    if (napcatSocket_->state() != QAbstractSocket::UnconnectedState) {
        return;
    }
    QUrl url(napcatSettings_.value(QStringLiteral("ws_url")).toString().trimmed());
    const QString token = backend_.napcatAccessToken(configPath_).trimmed();
    if (!token.isEmpty()) {
        QUrlQuery query(url);
        query.removeAllQueryItems(QStringLiteral("access_token"));
        query.addQueryItem(QStringLiteral("access_token"), token);
        url.setQuery(query);
    }
    QNetworkRequest request(url);
    if (!token.isEmpty()) {
        request.setRawHeader(
            QByteArrayLiteral("Authorization"),
            QByteArrayLiteral("Bearer ") + token.toUtf8());
    }
    if (napcatStatusLabel_ != nullptr) {
        napcatStatusLabel_->setText(tr("Connecting to NapCat…"));
    }
    napcatSocket_->open(request);
}

void NativeMainWindow::scheduleNativeNapcatReconnect() {
    if (!napcatStopping_ && napcatSocket_ != nullptr
        && !napcatReconnectTimer_.isActive()) {
        napcatReconnectTimer_.start();
    }
}

void NativeMainWindow::handleNativeNapcatMessage(const QString& message) {
    const QByteArray encoded = message.toUtf8();
    if (encoded.size() > 1024 * 1024) {
        if (napcatStatusLabel_ != nullptr) {
            napcatStatusLabel_->setText(tr("NapCat message exceeded the 1 MiB limit."));
        }
        return;
    }
    QJsonParseError parseError;
    const QJsonDocument document = QJsonDocument::fromJson(encoded, &parseError);
    if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
        return;
    }
    const QString eventJson = compactJson(document.object());
    const QString databasePath = nativeDatabasePath();
    if (!backend_.ingestNapcatEvent(configPath_, databasePath, eventJson)) {
        if (napcatStatusLabel_ != nullptr) {
            napcatStatusLabel_->setText(backend_.getStatus());
        }
        return;
    }
    const QJsonObject result = parseObject(backend_.getNapcatEventResultJson());
    if (result.value(QStringLiteral("ignored")).toBool(true)) {
        return;
    }
    const QJsonObject overlay = result.value(QStringLiteral("overlay")).toObject();
    if (!overlay.isEmpty()) {
        supervisor_.broadcastControlLine(
            QStringLiteral("CHAT_EVENT\t") + compactJson(overlay));
    }
    if (result.value(QStringLiteral("should_reply")).toBool(false)) {
        if (activeNapcatReplyIds_.size() >= kMaximumConcurrentNapcatReplies) {
            if (napcatStatusLabel_ != nullptr) {
                napcatStatusLabel_->setText(
                    tr("NapCat message stored; the four-reply queue is busy."));
            }
            return;
        }
        const QJsonObject normalized =
            result.value(QStringLiteral("normalized_event")).toObject();
        const qint64 requestId = backend_.startNapcatReply(
            configPath_, projectRoot_, databasePath, compactJson(normalized));
        if (requestId > 0) {
            activeNapcatReplyIds_.insert(requestId);
        } else if (napcatStatusLabel_ != nullptr) {
            napcatStatusLabel_->setText(backend_.getStatus());
        }
    }
    if (napcatStatusLabel_ != nullptr) {
        napcatStatusLabel_->setText(
            result.value(QStringLiteral("duplicate")).toBool(false)
                ? tr("NapCat duplicate ignored.")
                : (result.value(QStringLiteral("saved")).toBool(false)
                       ? tr("NapCat message stored.")
                       : tr("NapCat message forwarded to the overlay without storage.")));
    }
}

void NativeMainWindow::handleNativeNapcatReply(const QString& payloadJson) {
    const QJsonObject payload = parseObject(payloadJson);
    const qint64 requestId = payload.value(QStringLiteral("request_id")).toInteger();
    if (!activeNapcatReplyIds_.remove(requestId)) {
        return;
    }
    const QString state = payload.value(QStringLiteral("state")).toString();
    if (state != QStringLiteral("finished")) {
        if (napcatStatusLabel_ != nullptr && state == QStringLiteral("error")) {
            napcatStatusLabel_->setText(
                tr("NapCat auto reply failed: %1")
                    .arg(payload.value(QStringLiteral("message")).toString()));
        }
        return;
    }
    const QString reply = payload.value(QStringLiteral("reply")).toString().trimmed();
    const bool sent = sendNativeNapcatReply(
        payload.value(QStringLiteral("raw_event")).toObject(),
        reply,
        payload.value(QStringLiteral("mention_sender")).toBool(true));
    if (!sent) {
        if (napcatStatusLabel_ != nullptr) {
            napcatStatusLabel_->setText(
                tr("NapCat reply completed after the connection became unavailable."));
        }
        return;
    }
    const QJsonObject overlay {
        {QStringLiteral("source"), QStringLiteral("napcat")},
        {QStringLiteral("state"), QStringLiteral("stream")},
        {QStringLiteral("mode"), QStringLiteral("replace")},
        {QStringLiteral("title"), tr("Replied to QQ")},
        {QStringLiteral("text"), reply},
        {QStringLiteral("action"), QStringLiteral("smile")},
        {QStringLiteral("ttl_ms"), 9000},
        {QStringLiteral("anchor_to_pet"), true},
        {QStringLiteral("character"),
         payload.value(QStringLiteral("character")).toString()},
    };
    supervisor_.broadcastControlLine(
        QStringLiteral("CHAT_EVENT\t") + compactJson(overlay));
    if (napcatStatusLabel_ != nullptr) {
        napcatStatusLabel_->setText(tr("NapCat AI reply sent."));
    }
}

bool NativeMainWindow::sendNativeNapcatReply(
    const QJsonObject& rawEvent,
    const QString& text,
    bool mentionSender) {
    if (text.trimmed().isEmpty() || napcatSocket_ == nullptr
        || napcatSocket_->state() != QAbstractSocket::ConnectedState) {
        return false;
    }
    const QJsonValue userId = rawEvent.value(QStringLiteral("user_id"));
    const QJsonValue groupId = rawEvent.value(QStringLiteral("group_id"));
    const bool isGroup =
        rawEvent.value(QStringLiteral("message_type")).toString().toLower()
        == QStringLiteral("group");
    auto idText = [](const QJsonValue& value) {
        if (value.isString()) {
            return value.toString();
        }
        return value.isDouble() ? QString::number(value.toInteger()) : QString();
    };
    QString message = text.trimmed();
    const QString senderId = idText(userId);
    if (isGroup && mentionSender && !senderId.isEmpty()) {
        message.prepend(QStringLiteral("[CQ:at,qq=%1] ").arg(senderId));
    }
    QString action;
    QJsonObject params;
    if (isGroup && !groupId.isNull() && !groupId.isUndefined()) {
        action = QStringLiteral("send_group_msg");
        params.insert(QStringLiteral("group_id"), groupId);
    } else if (!userId.isNull() && !userId.isUndefined()) {
        action = QStringLiteral("send_private_msg");
        params.insert(QStringLiteral("user_id"), userId);
    } else {
        return false;
    }
    params.insert(QStringLiteral("message"), message);
    const QJsonObject request {
        {QStringLiteral("action"), action},
        {QStringLiteral("params"), params},
        {QStringLiteral("echo"),
         QUuid::createUuid().toString(QUuid::WithoutBraces).remove('-')},
    };
    return napcatSocket_->sendTextMessage(compactJson(request)) > 0;
}

void NativeMainWindow::populateMemoryCharacters() {
    if (memoryCharacterComboBox_ == nullptr) {
        return;
    }
    const QString previous = memoryCharacterComboBox_->currentData().toString();
    const QString configured = runtime_.value(QStringLiteral("selected_character")).toString();
    updatingMemoryControls_ = true;
    memoryCharacterComboBox_->clear();
    memoryCharacterComboBox_->addItem(
        tr("User preferences · global"), QVariant(), QStringLiteral("__global__"));
    QStringList added;
    for (const ModelCatalogItem& model : catalog_) {
        if (model.character.isEmpty() || added.contains(model.character)) {
            continue;
        }
        added.append(model.character);
        const QString display = model.characterDisplay.isEmpty()
            ? model.character
            : model.characterDisplay;
        memoryCharacterComboBox_->addItem(display, QVariant(), model.character);
    }
    QString selected = previous;
    if (selected.isEmpty() || memoryCharacterComboBox_->findData(selected) < 0) {
        selected = configured;
    }
    const int selectedIndex = memoryCharacterComboBox_->findData(selected);
    memoryCharacterComboBox_->setCurrentIndex(selectedIndex < 0 ? 0 : selectedIndex);
    updatingMemoryControls_ = false;
}

void NativeMainWindow::refreshNativeMemoryState() {
    if (memoryCharacterComboBox_ == nullptr || memoryCharacterComboBox_->count() == 0) {
        return;
    }
    const QString character = memoryCharacterComboBox_->currentData().toString().trimmed();
    const QString userKey = runtime_
                                .value(QStringLiteral("active_user_key"))
                                .toString(QStringLiteral("__default__"));
    const QString databasePath = nativeDatabasePath();
    if (!backend_.loadMemoryState(databasePath, character, userKey)) {
        memoryStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        return;
    }
    memorySnapshot_ = parseObject(backend_.getMemorySnapshotJson());
    renderNativeMemories();
}

void NativeMainWindow::renderNativeMemories() {
    if (memoryList_ == nullptr) {
        return;
    }
    const qint64 previousId = memoryList_->currentItem() == nullptr
        ? 0
        : memoryList_->currentItem()->data(kMemoryIdRole).toLongLong();
    updatingMemoryControls_ = true;
    memoryList_->clear();
    const QJsonArray memories = memorySnapshot_.value(QStringLiteral("memories")).toArray();
    for (const QJsonValue& value : memories) {
        if (!value.isObject()) {
            continue;
        }
        const QJsonObject memory = value.toObject();
        const qint64 id = memory.value(QStringLiteral("id")).toInteger();
        QString preview = memory.value(QStringLiteral("content")).toString().trimmed();
        preview.replace(QRegularExpression(QStringLiteral("\\s+")), QStringLiteral(" "));
        if (preview.size() > 240) {
            preview = preview.left(237) + QStringLiteral("...");
        }
        const QString text = tr("%1 · importance %2 · %3\n%4")
                                 .arg(
                                     memory.value(QStringLiteral("kind")).toString(),
                                     QString::number(
                                         memory.value(QStringLiteral("importance")).toInt()),
                                     memory.value(QStringLiteral("updated_at")).toString(),
                                     preview);
        auto* item = new QListWidgetItem(text, memoryList_);
        item->setData(kMemoryIdRole, id);
        item->setData(kMemoryKindRole, memory.value(QStringLiteral("kind")).toString());
        item->setData(kMemoryContentRole, memory.value(QStringLiteral("content")).toString());
        item->setData(kMemoryImportanceRole, memory.value(QStringLiteral("importance")).toInt(50));
        if (id == previousId) {
            memoryList_->setCurrentItem(item);
        }
    }
    updatingMemoryControls_ = false;

    const QJsonValue relationshipValue = memorySnapshot_.value(QStringLiteral("relationship"));
    const bool hasRelationship = relationshipValue.isObject();
    memoryRelationshipCard_->setVisible(hasRelationship);
    if (hasRelationship) {
        const QJsonObject relationship = relationshipValue.toObject();
        memoryAffectionLabel_->setText(
            QStringLiteral("%1 / 100").arg(
                relationship.value(QStringLiteral("affection")).toInt()));
        memoryTrustLabel_->setText(
            QStringLiteral("%1 / 100").arg(
                relationship.value(QStringLiteral("trust")).toInt()));
        memoryFamiliarityLabel_->setText(
            QStringLiteral("%1 / 100").arg(
                relationship.value(QStringLiteral("familiarity")).toInt()));
        memoryMoodLabel_->setText(
            QStringLiteral("%1 · %2 / 100")
                .arg(
                    relationship.value(QStringLiteral("mood")).toString(),
                    QString::number(
                        relationship.value(QStringLiteral("mood_intensity")).toInt())));
    }
    const QString userKey = memorySnapshot_.value(QStringLiteral("user_key")).toString();
    memoryStatusLabel_->setText(
        tr("%1 memory item(s) · user %2").arg(memories.size()).arg(userKey));
    loadSelectedNativeMemory();
}

void NativeMainWindow::loadSelectedNativeMemory() {
    if (memoryList_ == nullptr || updatingMemoryControls_) {
        return;
    }
    QListWidgetItem* item = memoryList_->currentItem();
    memoryDeleteButton_->setEnabled(!memoryList_->selectedItems().isEmpty());
    if (item == nullptr) {
        memoryKindComboBox_->setCurrentIndex(
            std::max(0, memoryKindComboBox_->findData(QStringLiteral("profile"))));
        memoryImportanceSpinBox_->setValue(70);
        memoryContentEdit_->clear();
        return;
    }
    const int kindIndex = memoryKindComboBox_->findData(item->data(kMemoryKindRole));
    memoryKindComboBox_->setCurrentIndex(kindIndex < 0 ? 0 : kindIndex);
    memoryImportanceSpinBox_->setValue(item->data(kMemoryImportanceRole).toInt());
    memoryContentEdit_->setPlainText(item->data(kMemoryContentRole).toString());
}

bool NativeMainWindow::mutateNativeMemory(const QJsonObject& command) {
    const QString character = memoryCharacterComboBox_->currentData().toString().trimmed();
    const QString userKey = runtime_
                                .value(QStringLiteral("active_user_key"))
                                .toString(QStringLiteral("__default__"));
    const QString databasePath = nativeDatabasePath();
    if (!backend_.mutateMemory(databasePath, character, userKey, compactJson(command))) {
        serviceStatusLabel_->setText(backend_.getStatus());
        memoryStatusLabel_->setText(backend_.getStatus());
        return false;
    }
    memorySnapshot_ = parseObject(backend_.getMemorySnapshotJson());
    serviceStatusLabel_->setText(backend_.getStatus());
    renderNativeMemories();
    return true;
}

void NativeMainWindow::saveNativeMemory() {
    const QString content = memoryContentEdit_->toPlainText().trimmed();
    if (content.isEmpty()) {
        memoryStatusLabel_->setText(tr("Memory content cannot be empty"));
        return;
    }
    const qint64 memoryId = memoryList_->currentItem() == nullptr
        ? 0
        : memoryList_->currentItem()->data(kMemoryIdRole).toLongLong();
    if (mutateNativeMemory({
            {QStringLiteral("op"), QStringLiteral("save_memory")},
            {QStringLiteral("id"), memoryId},
            {QStringLiteral("kind"), memoryKindComboBox_->currentData().toString()},
            {QStringLiteral("content"), content},
            {QStringLiteral("importance"), memoryImportanceSpinBox_->value()},
        })) {
        memoryStatusLabel_->setText(memoryId > 0 ? tr("Memory updated") : tr("Memory added"));
    }
}

void NativeMainWindow::deleteSelectedNativeMemories() {
    const QList<QListWidgetItem*> selected = memoryList_->selectedItems();
    if (selected.isEmpty()) {
        return;
    }
    if (QMessageBox::warning(
            this,
            tr("Delete long-term memories"),
            tr("Delete %1 selected memory item(s)? This removes them from future chat context.")
                .arg(selected.size()),
            QMessageBox::Yes | QMessageBox::No,
            QMessageBox::No)
        != QMessageBox::Yes) {
        return;
    }
    QJsonArray ids;
    for (const QListWidgetItem* item : selected) {
        ids.append(item->data(kMemoryIdRole).toLongLong());
    }
    if (mutateNativeMemory({
            {QStringLiteral("op"), QStringLiteral("delete_memories")},
            {QStringLiteral("ids"), ids},
        })) {
        startNewNativeMemory();
        memoryStatusLabel_->setText(tr("Deleted %1 memory item(s)").arg(ids.size()));
    }
}

void NativeMainWindow::startNewNativeMemory() {
    updatingMemoryControls_ = true;
    memoryList_->clearSelection();
    memoryList_->setCurrentItem(nullptr);
    updatingMemoryControls_ = false;
    memoryKindComboBox_->setCurrentIndex(
        std::max(0, memoryKindComboBox_->findData(QStringLiteral("profile"))));
    memoryImportanceSpinBox_->setValue(70);
    memoryContentEdit_->clear();
    memoryDeleteButton_->setEnabled(false);
    memoryContentEdit_->setFocus();
}

void NativeMainWindow::loadNativeUserProfiles() {
    if (userProfileComboBox_ == nullptr) {
        return;
    }
    if (!backend_.loadUserProfiles(configPath_)) {
        userProfileStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        return;
    }
    userProfilesState_ = parseObject(backend_.getUserProfilesJson());
    runtime_ = parseObject(backend_.getRuntimeConfigJson());
    syncNativeUserProfileControls();
}

void NativeMainWindow::syncNativeUserProfileControls() {
    if (userProfileComboBox_ == nullptr) {
        return;
    }
    const QString previous = userProfileComboBox_->currentData().toString();
    const QString active =
        userProfilesState_.value(QStringLiteral("active_key")).toString();
    updatingUserProfileControls_ = true;
    userProfileComboBox_->clear();
    for (const QJsonValue& value : userProfilesState_.value(QStringLiteral("profiles")).toArray()) {
        if (!value.isObject()) {
            continue;
        }
        const QJsonObject profile = value.toObject();
        const QString key = profile.value(QStringLiteral("key")).toString();
        QString name = profile.value(QStringLiteral("name")).toString().trimmed();
        if (name.isEmpty()) {
            name = tr("Current user");
        }
        const QString label = key == active
            ? tr("%1 · current").arg(name)
            : (key == name || key == QStringLiteral("__default__")
                   ? name
                   : QStringLiteral("%1 · %2").arg(name, key));
        userProfileComboBox_->addItem(label, QVariant(), key);
    }
    QString selected = previous;
    if (selected.isEmpty() || userProfileComboBox_->findData(selected) < 0) {
        selected = active;
    }
    const int index = userProfileComboBox_->findData(selected);
    userProfileComboBox_->setCurrentIndex(index < 0 ? 0 : index);
    updatingUserProfileControls_ = false;
    loadSelectedNativeUserProfile();
}

void NativeMainWindow::loadSelectedNativeUserProfile() {
    if (userProfileComboBox_ == nullptr || updatingUserProfileControls_) {
        return;
    }
    const QString key = userProfileComboBox_->currentData().toString();
    QJsonObject selected;
    for (const QJsonValue& value : userProfilesState_.value(QStringLiteral("profiles")).toArray()) {
        if (value.isObject()
            && value.toObject().value(QStringLiteral("key")).toString() == key) {
            selected = value.toObject();
            break;
        }
    }
    userProfileNameEdit_->setText(selected.value(QStringLiteral("name")).toString());
    userProfileColorEdit_->setText(
        selected.value(QStringLiteral("avatar_color")).toString(QStringLiteral("#e4004f")));
    userProfileAvatarPathEdit_->setText(
        selected.value(QStringLiteral("avatar_path")).toString());
    const QString active =
        userProfilesState_.value(QStringLiteral("active_key")).toString();
    const bool exists = !selected.isEmpty();
    userProfileActivateButton_->setEnabled(exists && key != active);
    userProfileSaveButton_->setEnabled(exists);
    userProfileDeleteButton_->setEnabled(exists);
    userProfileStatusLabel_->setText(
        key == active
            ? tr("This is the current user partition")
            : tr("Previewing %1; click Set current to switch partitions").arg(key));
}

bool NativeMainWindow::mutateNativeUserProfile(const QJsonObject& command) {
    if (!backend_.mutateUserProfile(configPath_, compactJson(command))) {
        serviceStatusLabel_->setText(backend_.getStatus());
        userProfileStatusLabel_->setText(backend_.getStatus());
        return false;
    }
    userProfilesState_ = parseObject(backend_.getUserProfilesJson());
    runtime_ = parseObject(backend_.getRuntimeConfigJson());
    serviceStatusLabel_->setText(backend_.getStatus());
    syncNativeUserProfileControls();
    refreshNativeMemoryState();
    refreshNativeStatistics();
    if (activeChatRequestId_ == 0 && !groupSequenceActive_) {
        refreshChatState({}, true);
    }
    return true;
}

void NativeMainWindow::activateSelectedNativeUserProfile() {
    const QString key = userProfileComboBox_->currentData().toString();
    if (key.isEmpty()) {
        return;
    }
    if (mutateNativeUserProfile({
            {QStringLiteral("op"), QStringLiteral("activate_profile")},
            {QStringLiteral("key"), key},
        })) {
        userProfileStatusLabel_->setText(tr("Switched to user profile %1").arg(key));
    }
}

void NativeMainWindow::createNativeUserProfile() {
    QString name = userProfileNameEdit_->text().trimmed();
    if (name.isEmpty()) {
        name = tr("New user");
    }
    if (mutateNativeUserProfile({
            {QStringLiteral("op"), QStringLiteral("create_profile")},
            {QStringLiteral("name"), name},
            {QStringLiteral("avatar_color"), userProfileColorEdit_->text().trimmed()},
            {QStringLiteral("avatar_path"), userProfileAvatarPathEdit_->text().trimmed()},
        })) {
        userProfileStatusLabel_->setText(tr("Created and activated user profile %1").arg(name));
    }
}

void NativeMainWindow::saveSelectedNativeUserProfile() {
    const QString key = userProfileComboBox_->currentData().toString();
    if (key.isEmpty()) {
        return;
    }
    if (mutateNativeUserProfile({
            {QStringLiteral("op"), QStringLiteral("update_profile")},
            {QStringLiteral("key"), key},
            {QStringLiteral("name"), userProfileNameEdit_->text().trimmed()},
            {QStringLiteral("avatar_color"), userProfileColorEdit_->text().trimmed()},
            {QStringLiteral("avatar_path"), userProfileAvatarPathEdit_->text().trimmed()},
        })) {
        userProfileStatusLabel_->setText(tr("Saved user profile %1").arg(key));
    }
}

void NativeMainWindow::deleteSelectedNativeUserProfile() {
    const QString key = userProfileComboBox_->currentData().toString();
    if (key.isEmpty()) {
        return;
    }
    if (QMessageBox::warning(
            this,
            tr("Delete user profile"),
            tr("Delete profile %1? Existing chat and memory rows remain in its database partition.")
                .arg(key),
            QMessageBox::Yes | QMessageBox::No,
            QMessageBox::No)
        != QMessageBox::Yes) {
        return;
    }
    if (mutateNativeUserProfile({
            {QStringLiteral("op"), QStringLiteral("delete_profile")},
            {QStringLiteral("key"), key},
        })) {
        userProfileStatusLabel_->setText(tr("Deleted user profile %1").arg(key));
    }
}

void NativeMainWindow::chooseNativeUserAvatar() {
    const QString selected = QFileDialog::getOpenFileName(
        this,
        tr("Choose user avatar"),
        userProfileAvatarPathEdit_->text(),
        tr("Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*)"));
    if (!selected.isEmpty()) {
        userProfileAvatarPathEdit_->setText(QDir::cleanPath(selected));
    }
}

void NativeMainWindow::loadNativePersonaSettings() {
    if (povModeComboBox_ == nullptr) {
        return;
    }
    QJsonArray characters;
    QStringList seen;
    auto appendCharacter = [&characters, &seen](const QString& rawCharacter) {
        const QString character = rawCharacter.trimmed();
        if (!character.isEmpty() && !seen.contains(character)) {
            seen.append(character);
            characters.append(character);
        }
    };
    for (const ModelCatalogItem& model : catalog_) {
        appendCharacter(model.character);
    }
    appendCharacter(runtime_.value(QStringLiteral("character")).toString());
    const QString charactersJson = QString::fromUtf8(
        QJsonDocument(characters).toJson(QJsonDocument::Compact));
    if (!backend_.loadPersonaSettings(configPath_, projectRoot_, charactersJson)) {
        personaStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        return;
    }
    personaSettingsState_ = parseObject(backend_.getPersonaSettingsJson());
    runtime_ = parseObject(backend_.getRuntimeConfigJson());
    syncNativePersonaControls();
    personaStatusLabel_->setText(tr("Persona settings loaded from Rust"));
}

void NativeMainWindow::syncNativePersonaControls() {
    if (povModeComboBox_ == nullptr || updatingPersonaControls_) {
        return;
    }
    const QString selectedCharacter =
        characterPersonaCharacterComboBox_->currentData().toString();
    updatingPersonaControls_ = true;

    const QString mode =
        personaSettingsState_.value(QStringLiteral("pov_mode")).toString(QStringLiteral("off"));
    const int modeIndex = povModeComboBox_->findData(mode);
    povModeComboBox_->setCurrentIndex(modeIndex < 0 ? 0 : modeIndex);
    const QString customPrompt =
        personaSettingsState_.value(QStringLiteral("pov_custom_prompt")).toString();
    povCustomPromptEdit_->setPlainText(customPrompt);

    povPersonaComboBox_->clear();
    povPersonaComboBox_->addItem(tr("New custom POV preset"), QVariant(), QString());
    int selectedPovPersona = 0;
    for (const QJsonValue& value :
         personaSettingsState_.value(QStringLiteral("pov_personas")).toArray()) {
        if (!value.isObject()) {
            continue;
        }
        const QJsonObject persona = value.toObject();
        const QString prompt = persona.value(QStringLiteral("prompt")).toString();
        if (prompt.isEmpty()) {
            continue;
        }
        QString title = persona.value(QStringLiteral("title")).toString().trimmed();
        if (title.isEmpty()) {
            title = tr("Persona");
        }
        povPersonaComboBox_->addItem(title, QVariant(), prompt);
        if (prompt == customPrompt) {
            selectedPovPersona = povPersonaComboBox_->count() - 1;
        }
    }
    povPersonaComboBox_->setCurrentIndex(selectedPovPersona);

    QStringList characters;
    for (const QJsonValue& value :
         personaSettingsState_.value(QStringLiteral("characters")).toArray()) {
        if (!value.isObject()) {
            continue;
        }
        const QString character =
            value.toObject().value(QStringLiteral("character")).toString();
        if (!character.isEmpty() && !characters.contains(character)) {
            characters.append(character);
        }
    }
    for (const ModelCatalogItem& model : catalog_) {
        if (!model.character.isEmpty() && !characters.contains(model.character)) {
            characters.append(model.character);
        }
    }
    std::sort(characters.begin(), characters.end());
    povRoleCharacterComboBox_->clear();
    characterPersonaCharacterComboBox_->clear();
    for (const QString& character : characters) {
        const QString display = displayNameForCharacter(character);
        povRoleCharacterComboBox_->addItem(display, QVariant(), character);
        characterPersonaCharacterComboBox_->addItem(display, QVariant(), character);
    }
    const QString roleCharacter =
        personaSettingsState_.value(QStringLiteral("pov_role_character")).toString();
    const int roleIndex = povRoleCharacterComboBox_->findData(roleCharacter);
    povRoleCharacterComboBox_->setCurrentIndex(roleIndex < 0 ? 0 : roleIndex);
    QString characterToSelect = selectedCharacter;
    if (characterToSelect.isEmpty()
        || characterPersonaCharacterComboBox_->findData(characterToSelect) < 0) {
        characterToSelect = runtime_.value(QStringLiteral("character")).toString();
    }
    const int characterIndex =
        characterPersonaCharacterComboBox_->findData(characterToSelect);
    characterPersonaCharacterComboBox_->setCurrentIndex(characterIndex < 0 ? 0 : characterIndex);
    updatingPersonaControls_ = false;

    updateNativePovModeControls();
    syncSelectedNativeCharacterPersona();
}

void NativeMainWindow::updateNativePovModeControls() {
    if (povModeComboBox_ == nullptr) {
        return;
    }
    const QString mode = povModeComboBox_->currentData().toString();
    const bool custom = mode == QStringLiteral("custom");
    const bool role = mode == QStringLiteral("role");
    povCustomPromptEdit_->setEnabled(custom);
    povPersonaComboBox_->setEnabled(custom);
    povSavePersonaButton_->setEnabled(custom);
    povDeletePersonaButton_->setEnabled(
        custom && !povPersonaComboBox_->currentData().toString().isEmpty());
    povRoleCharacterComboBox_->setEnabled(role);
}

void NativeMainWindow::syncSelectedNativeCharacterPersona() {
    if (characterPersonaCharacterComboBox_ == nullptr) {
        return;
    }
    const QString character =
        characterPersonaCharacterComboBox_->currentData().toString();
    QJsonObject collection;
    for (const QJsonValue& value :
         personaSettingsState_.value(QStringLiteral("characters")).toArray()) {
        if (value.isObject()
            && value.toObject().value(QStringLiteral("character")).toString() == character) {
            collection = value.toObject();
            break;
        }
    }
    updatingPersonaControls_ = true;
    characterPersonaPresetComboBox_->clear();
    characterPersonaPresetComboBox_->addItem(
        tr("Use default persona"), QVariant(), QString());
    const QString activeId = collection.value(QStringLiteral("active_id")).toString();
    int selectedPreset = 0;
    for (const QJsonValue& value : collection.value(QStringLiteral("presets")).toArray()) {
        if (!value.isObject()) {
            continue;
        }
        const QJsonObject preset = value.toObject();
        const QString id = preset.value(QStringLiteral("id")).toString();
        QString title = preset.value(QStringLiteral("title")).toString().trimmed();
        if (id.isEmpty()) {
            continue;
        }
        if (title.isEmpty()) {
            title = tr("Persona");
        }
        characterPersonaPresetComboBox_->addItem(title, QVariant(), id);
        if (id == activeId) {
            selectedPreset = characterPersonaPresetComboBox_->count() - 1;
        }
    }
    characterPersonaPresetComboBox_->setCurrentIndex(selectedPreset);
    characterPersonaDefaultPreview_->setPlainText(
        collection.value(QStringLiteral("default_prompt")).toString());
    updatingPersonaControls_ = false;
    loadSelectedNativeCharacterPersona();
}

void NativeMainWindow::loadSelectedNativeCharacterPersona() {
    if (characterPersonaPresetComboBox_ == nullptr || updatingPersonaControls_) {
        return;
    }
    const QString character =
        characterPersonaCharacterComboBox_->currentData().toString();
    const QString presetId = characterPersonaPresetComboBox_->currentData().toString();
    QJsonObject selected;
    for (const QJsonValue& value :
         personaSettingsState_.value(QStringLiteral("characters")).toArray()) {
        if (!value.isObject()) {
            continue;
        }
        const QJsonObject collection = value.toObject();
        if (collection.value(QStringLiteral("character")).toString() != character) {
            continue;
        }
        for (const QJsonValue& presetValue :
             collection.value(QStringLiteral("presets")).toArray()) {
            if (presetValue.isObject()
                && presetValue.toObject().value(QStringLiteral("id")).toString() == presetId) {
                selected = presetValue.toObject();
                break;
            }
        }
        break;
    }
    characterPersonaTitleEdit_->setText(
        selected.value(QStringLiteral("title")).toString());
    characterPersonaPromptEdit_->setPlainText(
        selected.value(QStringLiteral("prompt")).toString());
    characterPersonaDeleteButton_->setEnabled(!presetId.isEmpty() && !selected.isEmpty());
}

bool NativeMainWindow::mutateNativePersona(const QJsonObject& command) {
    const QString operation = command.value(QStringLiteral("op")).toString();
    const QString draftPovMode = povModeComboBox_->currentData().toString();
    const QString draftPovPrompt = povCustomPromptEdit_->toPlainText();
    const QString draftRoleCharacter = povRoleCharacterComboBox_->currentData().toString();
    const QString draftCharacterTitle = characterPersonaTitleEdit_->text();
    const QString draftCharacterPrompt = characterPersonaPromptEdit_->toPlainText();
    QJsonArray characters;
    QStringList seen;
    auto appendCharacter = [&characters, &seen](const QString& rawCharacter) {
        const QString character = rawCharacter.trimmed();
        if (!character.isEmpty() && !seen.contains(character)) {
            seen.append(character);
            characters.append(character);
        }
    };
    for (const ModelCatalogItem& model : catalog_) {
        appendCharacter(model.character);
    }
    for (const QJsonValue& value :
         personaSettingsState_.value(QStringLiteral("characters")).toArray()) {
        if (value.isObject()) {
            appendCharacter(value.toObject().value(QStringLiteral("character")).toString());
        }
    }
    const QString charactersJson = QString::fromUtf8(
        QJsonDocument(characters).toJson(QJsonDocument::Compact));
    if (!backend_.mutatePersonaSettings(
            configPath_, projectRoot_, charactersJson, compactJson(command))) {
        personaStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        return false;
    }
    personaSettingsState_ = parseObject(backend_.getPersonaSettingsJson());
    runtime_ = parseObject(backend_.getRuntimeConfigJson());
    serviceStatusLabel_->setText(backend_.getStatus());
    syncNativePersonaControls();
    updatingPersonaControls_ = true;
    if (operation != QStringLiteral("save_pov")) {
        const int modeIndex = povModeComboBox_->findData(draftPovMode);
        povModeComboBox_->setCurrentIndex(modeIndex < 0 ? 0 : modeIndex);
        povCustomPromptEdit_->setPlainText(draftPovPrompt);
        const int roleIndex = povRoleCharacterComboBox_->findData(draftRoleCharacter);
        povRoleCharacterComboBox_->setCurrentIndex(roleIndex < 0 ? 0 : roleIndex);
    }
    if (!operation.contains(QStringLiteral("character_persona"))) {
        characterPersonaTitleEdit_->setText(draftCharacterTitle);
        characterPersonaPromptEdit_->setPlainText(draftCharacterPrompt);
    }
    updatingPersonaControls_ = false;
    updateNativePovModeControls();
    if (operation == QStringLiteral("save_pov")) {
        refreshNativeMemoryState();
        refreshNativeStatistics();
        if (activeChatRequestId_ == 0 && !groupSequenceActive_) {
            refreshChatState({}, true);
        }
    }
    personaStatusLabel_->setText(tr("Persona settings saved atomically"));
    return true;
}

void NativeMainWindow::saveNativePov() {
    if (mutateNativePersona({
            {QStringLiteral("op"), QStringLiteral("save_pov")},
            {QStringLiteral("mode"), povModeComboBox_->currentData().toString()},
            {QStringLiteral("custom_prompt"), povCustomPromptEdit_->toPlainText().trimmed()},
            {QStringLiteral("role_character"),
             povRoleCharacterComboBox_->currentData().toString()},
            {QStringLiteral("now"), currentLocalDateTime()},
        })) {
        personaStatusLabel_->setText(tr("POV mode saved; new chat requests use it immediately"));
    }
}

void NativeMainWindow::saveNativePovPersona() {
    const QString prompt = povCustomPromptEdit_->toPlainText().trimmed();
    if (prompt.isEmpty()) {
        personaStatusLabel_->setText(tr("Enter a custom POV prompt first"));
        return;
    }
    if (mutateNativePersona({
            {QStringLiteral("op"), QStringLiteral("save_pov_persona")},
            {QStringLiteral("title"), QString()},
            {QStringLiteral("prompt"), prompt},
            {QStringLiteral("now"), currentLocalDateTime()},
        })) {
        personaStatusLabel_->setText(tr("Custom POV preset saved"));
    }
}

void NativeMainWindow::deleteSelectedNativePovPersona() {
    const QString prompt = povPersonaComboBox_->currentData().toString();
    if (prompt.isEmpty()) {
        return;
    }
    if (mutateNativePersona({
            {QStringLiteral("op"), QStringLiteral("delete_pov_persona")},
            {QStringLiteral("prompt"), prompt},
            {QStringLiteral("now"), currentLocalDateTime()},
        })) {
        personaStatusLabel_->setText(tr("Custom POV preset deleted"));
    }
}

void NativeMainWindow::saveNativeCharacterPersona(bool asNew) {
    const QString character =
        characterPersonaCharacterComboBox_->currentData().toString();
    const QString prompt = characterPersonaPromptEdit_->toPlainText().trimmed();
    if (character.isEmpty() || prompt.isEmpty()) {
        personaStatusLabel_->setText(tr("Choose a character and enter a persona prompt first"));
        return;
    }
    const QString presetId = asNew
        ? QString()
        : characterPersonaPresetComboBox_->currentData().toString();
    if (mutateNativePersona({
            {QStringLiteral("op"), QStringLiteral("save_character_persona")},
            {QStringLiteral("character"), character},
            {QStringLiteral("preset_id"), presetId},
            {QStringLiteral("title"), characterPersonaTitleEdit_->text().trimmed()},
            {QStringLiteral("prompt"), prompt},
            {QStringLiteral("now"), currentLocalDateTime()},
        })) {
        personaStatusLabel_->setText(tr("Character persona saved and activated"));
    }
}

void NativeMainWindow::deleteSelectedNativeCharacterPersona() {
    const QString character =
        characterPersonaCharacterComboBox_->currentData().toString();
    const QString presetId = characterPersonaPresetComboBox_->currentData().toString();
    if (character.isEmpty() || presetId.isEmpty()) {
        return;
    }
    if (mutateNativePersona({
            {QStringLiteral("op"), QStringLiteral("delete_character_persona")},
            {QStringLiteral("character"), character},
            {QStringLiteral("preset_id"), presetId},
            {QStringLiteral("now"), currentLocalDateTime()},
        })) {
        personaStatusLabel_->setText(tr("Character persona deleted; default persona restored"));
    }
}

void NativeMainWindow::importNativeCharacterPersonaDocuments() {
    QStringList paths = QFileDialog::getOpenFileNames(
        this,
        tr("Import character persona documents"),
        QString(),
        tr("Text files (*.md *.txt);;All files (*)"));
    if (paths.isEmpty()) {
        return;
    }
    std::sort(paths.begin(), paths.end());
    QStringList sections;
    QStringList failed;
    for (const QString& path : paths) {
        QFile file(path);
        if (!file.open(QIODevice::ReadOnly)) {
            failed.append(path);
            continue;
        }
        const QString text = QString::fromUtf8(file.readAll()).trimmed();
        if (text.isEmpty()) {
            failed.append(path);
            continue;
        }
        sections.append(QStringLiteral("# %1\n\n%2").arg(QFileInfo(path).fileName(), text));
    }
    if (sections.isEmpty()) {
        personaStatusLabel_->setText(tr("No readable persona text was found"));
        return;
    }
    const QFileInfo first(paths.first());
    characterPersonaTitleEdit_->setText(
        paths.size() == 1 ? first.completeBaseName() : tr("%1 and others").arg(first.completeBaseName()));
    characterPersonaPromptEdit_->setPlainText(sections.join(QStringLiteral("\n\n")));
    personaStatusLabel_->setText(
        failed.isEmpty()
            ? tr("Persona documents imported into the editor; save to persist them")
            : tr("Imported readable documents; %1 file(s) failed").arg(failed.size()));
}

void NativeMainWindow::loadNativeHistoryFilters() {
    if (historyCharacterComboBox_ == nullptr) {
        return;
    }
    const QString databasePath = nativeDatabasePath();
    if (!backend_.loadHistoryFilters(databasePath)) {
        historyStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        return;
    }
    historyFiltersState_ = parseObject(backend_.getHistoryFiltersJson());
    syncNativeHistoryFilters();
    searchNativeHistory(false);
}

void NativeMainWindow::syncNativeHistoryFilters() {
    const QString selectedCharacter = historyCharacterComboBox_->currentData().toString();
    const QString selectedUser = historyUserComboBox_->currentData().toString();
    historyCharacterComboBox_->clear();
    historyCharacterComboBox_->addItem(tr("All characters"), QVariant(), QString());
    for (const QJsonValue& value :
         historyFiltersState_.value(QStringLiteral("characters")).toArray()) {
        const QString character = value.toString().trimmed();
        if (!character.isEmpty()) {
            historyCharacterComboBox_->addItem(
                displayNameForCharacter(character), QVariant(), character);
        }
    }
    const int characterIndex = historyCharacterComboBox_->findData(selectedCharacter);
    historyCharacterComboBox_->setCurrentIndex(characterIndex < 0 ? 0 : characterIndex);

    historyUserComboBox_->clear();
    historyUserComboBox_->addItem(tr("All user partitions"), QVariant(), QString());
    for (const QJsonValue& value :
         historyFiltersState_.value(QStringLiteral("user_keys")).toArray()) {
        const QString userKey = value.toString().trimmed();
        if (userKey.isEmpty()) {
            continue;
        }
        QString label = userKey;
        if (userKey == QStringLiteral("__default__")) {
            label = tr("Default user");
        } else if (userKey.startsWith(QStringLiteral("__role__:"))) {
            const QString roleCharacter = userKey.mid(9);
            label = tr("Role POV · %1").arg(displayNameForCharacter(roleCharacter));
        }
        historyUserComboBox_->addItem(label, QVariant(), userKey);
    }
    const int userIndex = historyUserComboBox_->findData(selectedUser);
    historyUserComboBox_->setCurrentIndex(userIndex < 0 ? 0 : userIndex);
}

void NativeMainWindow::searchNativeHistory(bool append) {
    if (historyList_ == nullptr || (append && !historyHasMore_)) {
        return;
    }
    historySearchButton_->setEnabled(false);
    historyLoadMoreButton_->setEnabled(false);
    historyStatusLabel_->setText(append ? tr("Loading more history…") : tr("Searching history…"));
    const int offset = append ? historyOffset_ : 0;
    const QJsonObject query {
        {QStringLiteral("keyword"), historyKeywordEdit_->text().trimmed()},
        {QStringLiteral("date_from"), historyDateFromEdit_->text().trimmed()},
        {QStringLiteral("date_to"), historyDateToEdit_->text().trimmed()},
        {QStringLiteral("character"), historyCharacterComboBox_->currentData().toString()},
        {QStringLiteral("user_key"), historyUserComboBox_->currentData().toString()},
        {QStringLiteral("role"), historyRoleComboBox_->currentData().toString()},
        {QStringLiteral("source"), historySourceComboBox_->currentData().toString()},
        {QStringLiteral("limit"), 50},
        {QStringLiteral("offset"), offset},
        {QStringLiteral("skip_count"), append},
    };
    const QString databasePath = nativeDatabasePath();
    if (!backend_.searchHistory(databasePath, compactJson(query))) {
        historyStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        historySearchButton_->setEnabled(true);
        historyLoadMoreButton_->setEnabled(historyHasMore_);
        return;
    }
    const QJsonObject result = parseObject(backend_.getHistoryResultJson());
    const QJsonArray records = result.value(QStringLiteral("records")).toArray();
    if (!append) {
        historyList_->clear();
        historyOffset_ = 0;
        historyTotal_ = result.value(QStringLiteral("total")).toInteger(-1);
    }
    for (const QJsonValue& value : records) {
        if (!value.isObject()) {
            continue;
        }
        const QJsonObject record = value.toObject();
        const QString source = record.value(QStringLiteral("source")).toString();
        const QString role = record.value(QStringLiteral("role")).toString();
        const QString userKey = record.value(QStringLiteral("user_key")).toString();
        const QString character = record.value(QStringLiteral("character")).toString();
        const QString groupKey = record.value(QStringLiteral("group_key")).toString();
        const QString target = source == QStringLiteral("group")
            ? groupDisplayName(groupKey)
            : displayNameForCharacter(character);
        const QString sourceLabel = source == QStringLiteral("group") ? tr("Group") : tr("Private");
        const QString roleLabel = role == QStringLiteral("user")
            ? tr("User")
            : (role == QStringLiteral("assistant") ? tr("Character") : tr("System"));
        QString userLabel = userKey;
        if (userKey == QStringLiteral("__default__")) {
            userLabel = tr("Default user");
        } else if (userKey.startsWith(QStringLiteral("__role__:"))) {
            userLabel = tr("Role POV · %1").arg(
                displayNameForCharacter(userKey.mid(9)));
        }
        const QString content = record.value(QStringLiteral("content")).toString();
        QString preview = content;
        if (preview.size() > 600) {
            preview = preview.left(600).trimmed() + QStringLiteral("…");
        }
        const QString createdAt = record.value(QStringLiteral("created_at")).toString();
        auto* item = new QListWidgetItem(
            QStringLiteral("%1 · %2 · %3 · %4\n%5\n%6")
                .arg(createdAt, sourceLabel, target, roleLabel, userLabel, preview),
            historyList_);
        item->setToolTip(content);
        const int estimatedLines = std::clamp(
            3 + preview.count(QLatin1Char('\n')) + preview.size() / 90, 3, 9);
        item->setSizeHint(QSize(0, 22 * estimatedLines));
    }
    historyOffset_ += records.size();
    historyHasMore_ = result.value(QStringLiteral("has_more")).toBool()
        || (historyTotal_ >= 0 && historyOffset_ < historyTotal_);
    historySearchButton_->setEnabled(true);
    historyLoadMoreButton_->setEnabled(historyHasMore_);
    if (historyList_->count() == 0) {
        historyStatusLabel_->setText(tr("No history matched these filters"));
    } else if (historyTotal_ >= 0) {
        historyStatusLabel_->setText(
            tr("Showing %1 of %2 messages").arg(historyList_->count()).arg(historyTotal_));
    } else {
        historyStatusLabel_->setText(
            tr("Showing %1 messages").arg(historyList_->count()));
    }
}

void NativeMainWindow::resetNativeHistoryFilters() {
    historyKeywordEdit_->clear();
    historyDateFromEdit_->clear();
    historyDateToEdit_->clear();
    historyRoleComboBox_->setCurrentIndex(0);
    historySourceComboBox_->setCurrentIndex(0);
    historyCharacterComboBox_->setCurrentIndex(0);
    historyUserComboBox_->setCurrentIndex(0);
    loadNativeHistoryFilters();
}

void NativeMainWindow::populateNativeStatisticsCharacters() {
    if (statisticsCharacterComboBox_ == nullptr) {
        return;
    }
    const QString previous = statisticsCharacterComboBox_->currentData().toString();
    const QSignalBlocker blocker(statisticsCharacterComboBox_);
    statisticsCharacterComboBox_->clear();
    statisticsCharacterComboBox_->addItem(
        tr("No relationship character"), QVariant(), QString());
    QStringList added;
    for (const ModelCatalogItem& model : catalog_) {
        if (model.character.isEmpty() || added.contains(model.character)) {
            continue;
        }
        added.append(model.character);
        statisticsCharacterComboBox_->addItem(
            displayNameForCharacter(model.character), QVariant(), model.character);
    }
    for (const QJsonValue& value :
         historyFiltersState_.value(QStringLiteral("characters")).toArray()) {
        const QString character = value.toString().trimmed();
        if (character.isEmpty() || added.contains(character)) {
            continue;
        }
        added.append(character);
        statisticsCharacterComboBox_->addItem(
            displayNameForCharacter(character), QVariant(), character);
    }
    QString selected = previous;
    if (selected.isEmpty() || statisticsCharacterComboBox_->findData(selected) < 0) {
        selected = runtime_.value(QStringLiteral("character")).toString();
    }
    const int index = statisticsCharacterComboBox_->findData(selected);
    statisticsCharacterComboBox_->setCurrentIndex(index < 0 ? 0 : index);
}

void NativeMainWindow::refreshNativeStatistics() {
    if (statisticsRangeComboBox_ == nullptr || statisticsCharacterComboBox_ == nullptr) {
        return;
    }
    statisticsRefreshButton_->setEnabled(false);
    statisticsStatusLabel_->setText(tr("Refreshing statistics…"));
    QJsonObject aliases;
    for (const ModelCatalogItem& model : catalog_) {
        if (model.character.isEmpty() || model.characterDisplay.isEmpty()) {
            continue;
        }
        QJsonArray values = aliases.value(model.character).toArray();
        bool exists = false;
        for (const QJsonValue& value : values) {
            if (value.toString() == model.characterDisplay) {
                exists = true;
                break;
            }
        }
        if (!exists) {
            values.append(model.characterDisplay);
            aliases.insert(model.character, values);
        }
    }
    const QJsonObject query {
        {QStringLiteral("days"), statisticsRangeComboBox_->currentData().toInt()},
        {QStringLiteral("character"),
         statisticsCharacterComboBox_->currentData().toString()},
        {QStringLiteral("user_key"),
         runtime_.value(QStringLiteral("active_user_key"))
             .toString(QStringLiteral("__default__"))},
        {QStringLiteral("display_aliases"), aliases},
    };
    const QString databasePath = nativeDatabasePath();
    if (!backend_.loadStatistics(databasePath, compactJson(query))) {
        statisticsStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        statisticsRefreshButton_->setEnabled(true);
        return;
    }
    statisticsSnapshot_ = parseObject(backend_.getStatisticsSnapshotJson());
    serviceStatusLabel_->setText(backend_.getStatus());
    renderNativeStatistics();
    statisticsRefreshButton_->setEnabled(true);
}

void NativeMainWindow::renderNativeStatistics() {
    if (statisticsRelationshipTable_ == nullptr) {
        return;
    }
    const QJsonObject summary = statisticsSnapshot_.value(QStringLiteral("summary")).toObject();
    statisticsMessagesLabel_->setText(
        tr("%1 messages · %2 private conversations")
            .arg(statisticsSnapshot_.value(QStringLiteral("total_messages")).toInteger())
            .arg(summary.value(QStringLiteral("total_conversations")).toInteger()));
    statisticsUsageTodayLabel_->setText(durationLabel(
        statisticsSnapshot_.value(QStringLiteral("usage_today_seconds")).toInteger()));
    statisticsUsageWeekLabel_->setText(durationLabel(
        statisticsSnapshot_.value(QStringLiteral("usage_week_seconds")).toInteger()));
    statisticsUsageAllLabel_->setText(durationLabel(
        statisticsSnapshot_.value(QStringLiteral("usage_all_seconds")).toInteger()));

    const QJsonArray relationship =
        statisticsSnapshot_.value(QStringLiteral("relationship_trend")).toArray();
    statisticsRelationshipTable_->setRowCount(relationship.size());
    for (int row = 0; row < relationship.size(); ++row) {
        const QJsonObject point = relationship.at(row).toObject();
        const QStringList values {
            point.value(QStringLiteral("day")).toString(),
            QString::number(point.value(QStringLiteral("affection")).toInteger()),
            QString::number(point.value(QStringLiteral("trust")).toInteger()),
            QString::number(point.value(QStringLiteral("familiarity")).toInteger()),
        };
        for (int column = 0; column < values.size(); ++column) {
            statisticsRelationshipTable_->setItem(
                row, column, new QTableWidgetItem(values.at(column)));
        }
    }
    statisticsRelationshipTable_->resizeRowsToContents();

    const QJsonArray perCharacter =
        statisticsSnapshot_.value(QStringLiteral("messages_per_character")).toArray();
    statisticsCharacterTable_->setRowCount(perCharacter.size());
    for (int row = 0; row < perCharacter.size(); ++row) {
        const QJsonObject item = perCharacter.at(row).toObject();
        statisticsCharacterTable_->setItem(
            row,
            0,
            new QTableWidgetItem(
                displayNameForCharacter(item.value(QStringLiteral("character")).toString())));
        statisticsCharacterTable_->setItem(
            row,
            1,
            new QTableWidgetItem(
                QString::number(item.value(QStringLiteral("count")).toInteger())));
    }
    statisticsCharacterTable_->resizeRowsToContents();

    QMap<QString, qint64> messagesByDay;
    QMap<QString, qint64> usageByDay;
    for (const QJsonValue& value :
         statisticsSnapshot_.value(QStringLiteral("daily_messages")).toArray()) {
        const QJsonObject item = value.toObject();
        messagesByDay.insert(
            item.value(QStringLiteral("day")).toString(),
            item.value(QStringLiteral("count")).toInteger());
    }
    for (const QJsonValue& value :
         statisticsSnapshot_.value(QStringLiteral("daily_usage")).toArray()) {
        const QJsonObject item = value.toObject();
        usageByDay.insert(
            item.value(QStringLiteral("day")).toString(),
            item.value(QStringLiteral("seconds")).toInteger());
    }
    QStringList days = messagesByDay.keys();
    for (const QString& day : usageByDay.keys()) {
        if (!days.contains(day)) {
            days.append(day);
        }
    }
    std::sort(days.begin(), days.end());
    statisticsDailyTable_->setRowCount(days.size());
    for (int row = 0; row < days.size(); ++row) {
        const QString day = days.at(row);
        statisticsDailyTable_->setItem(row, 0, new QTableWidgetItem(day));
        statisticsDailyTable_->setItem(
            row, 1, new QTableWidgetItem(QString::number(messagesByDay.value(day))));
        statisticsDailyTable_->setItem(
            row, 2, new QTableWidgetItem(durationLabel(usageByDay.value(day))));
    }
    statisticsDailyTable_->resizeRowsToContents();

    const QJsonArray heatmap =
        statisticsSnapshot_.value(QStringLiteral("hourly_heatmap")).toArray();
    const QStringList weekdays {
        tr("Mon"), tr("Tue"), tr("Wed"), tr("Thu"), tr("Fri"), tr("Sat"), tr("Sun"),
    };
    statisticsHeatmapTable_->setRowCount(7);
    statisticsHeatmapTable_->setVerticalHeaderLabels(weekdays);
    for (int day = 0; day < 7; ++day) {
        const QJsonArray hours = day < heatmap.size() ? heatmap.at(day).toArray() : QJsonArray();
        for (int hour = 0; hour < 24; ++hour) {
            const qint64 count = hour < hours.size() ? hours.at(hour).toInteger() : 0;
            statisticsHeatmapTable_->setItem(
                day, hour, new QTableWidgetItem(count == 0 ? QString() : QString::number(count)));
        }
    }
    statisticsHeatmapTable_->resizeRowsToContents();

    const QString userKey = statisticsSnapshot_
                                .value(QStringLiteral("query"))
                                .toObject()
                                .value(QStringLiteral("user_key"))
                                .toString();
    statisticsStatusLabel_->setText(
        tr("Statistics refreshed for user partition %1").arg(userKey));
}

void NativeMainWindow::exportNativeSettingsPackage() {
    const QString category = dataCategoryComboBox_->currentData().toString();
    const QString stamp = QDateTime::currentDateTime().toString(QStringLiteral("yyyyMMdd-HHmmss"));
    QString path = QFileDialog::getSaveFileName(
        this,
        tr("Export native settings package"),
        QDir(dataRoot_).filePath(
            QStringLiteral("bandori-settings-%1-%2.json").arg(category, stamp)),
        tr("BandoriPet settings package (*.json)"));
    if (path.isEmpty()) {
        return;
    }
    if (QFileInfo(path).suffix().isEmpty()) {
        path += QStringLiteral(".json");
    }
    dataExportButton_->setEnabled(false);
    const QString databasePath = nativeDatabasePath();
    const bool exported =
        backend_.exportSettingsPackage(configPath_, databasePath, category, path);
    dataExportButton_->setEnabled(true);
    serviceStatusLabel_->setText(backend_.getStatus());
    if (!exported) {
        dataStatusLabel_->setText(backend_.getStatus());
        QMessageBox::critical(this, tr("Settings export failed"), backend_.getStatus());
        return;
    }
    showNativeDataSummary(tr("Settings package exported to %1").arg(path));
}

void NativeMainWindow::importNativeSettingsPackage() {
    const QString category = dataCategoryComboBox_->currentData().toString();
    const QString path = QFileDialog::getOpenFileName(
        this,
        tr("Import native settings package"),
        dataRoot_,
        tr("BandoriPet settings package (*.json)"));
    if (path.isEmpty()) {
        return;
    }
    const QMessageBox::StandardButton reply = QMessageBox::warning(
        this,
        tr("Confirm settings import"),
        tr("This will overwrite whitelisted fields in the selected category. Local API keys and integration tokens will be preserved. Continue?"),
        QMessageBox::Yes | QMessageBox::No,
        QMessageBox::No);
    if (reply != QMessageBox::Yes) {
        return;
    }
    dataImportButton_->setEnabled(false);
    const QString databasePath = nativeDatabasePath();
    const bool imported = backend_.importSettingsPackage(
        configPath_, databasePath, category, path);
    dataImportButton_->setEnabled(true);
    serviceStatusLabel_->setText(backend_.getStatus());
    if (!imported) {
        dataStatusLabel_->setText(backend_.getStatus());
        QMessageBox::critical(this, tr("Settings import failed"), backend_.getStatus());
        return;
    }
    const QJsonObject summary = parseObject(backend_.getDataOperationJson());
    reloadBackendState();
    showNativeDataSummary(
        tr("Imported %1 configuration fields from %2")
            .arg(summary.value(QStringLiteral("config_keys")).toInteger())
            .arg(path));
}

void NativeMainWindow::exportNativeChatDatabase() {
    const QString stamp = QDateTime::currentDateTime().toString(QStringLiteral("yyyyMMdd-HHmmss"));
    QString path = QFileDialog::getSaveFileName(
        this,
        tr("Create chat database backup"),
        QDir(dataRoot_).filePath(QStringLiteral("bandori-chat-%1.db").arg(stamp)),
        tr("SQLite database (*.db)"));
    if (path.isEmpty()) {
        return;
    }
    if (QFileInfo(path).suffix().isEmpty()) {
        path += QStringLiteral(".db");
    }
    databaseExportButton_->setEnabled(false);
    const QString databasePath = nativeDatabasePath();
    const bool exported = backend_.exportChatDatabase(databasePath, path);
    databaseExportButton_->setEnabled(true);
    serviceStatusLabel_->setText(backend_.getStatus());
    if (!exported) {
        dataStatusLabel_->setText(backend_.getStatus());
        QMessageBox::critical(this, tr("Database backup failed"), backend_.getStatus());
        return;
    }
    showNativeDataSummary(tr("Chat database backup created at %1").arg(path));
}

void NativeMainWindow::importNativeChatDatabase() {
    if (activeChatRequestId_ != 0 || groupSequenceActive_) {
        QMessageBox::warning(
            this,
            tr("Chat is still active"),
            tr("Wait for the current private or group response to finish, then restore the database."));
        return;
    }
    const QString path = QFileDialog::getOpenFileName(
        this,
        tr("Restore chat database backup"),
        dataRoot_,
        tr("SQLite database (*.db)"));
    if (path.isEmpty()) {
        return;
    }
    const QMessageBox::StandardButton reply = QMessageBox::warning(
        this,
        tr("Replace current chat database?"),
        tr("Restoring %1 will replace all current chats, relationships, memories and usage history. This cannot be undone unless you have another backup.")
            .arg(path),
        QMessageBox::Yes | QMessageBox::No,
        QMessageBox::No);
    if (reply != QMessageBox::Yes) {
        return;
    }
    databaseImportButton_->setEnabled(false);
    const QString databasePath = nativeDatabasePath();
    const bool imported = backend_.importChatDatabase(databasePath, path);
    databaseImportButton_->setEnabled(true);
    serviceStatusLabel_->setText(backend_.getStatus());
    if (!imported) {
        dataStatusLabel_->setText(backend_.getStatus());
        QMessageBox::critical(this, tr("Database restore failed"), backend_.getStatus());
        return;
    }
    reloadBackendState();
    showNativeDataSummary(tr("Chat database restored from %1").arg(path));
}

void NativeMainWindow::showNativeDataSummary(const QString& action) {
    const QJsonObject summary = parseObject(backend_.getDataOperationJson());
    const QJsonObject database = summary.value(QStringLiteral("database")).toObject();
    QStringList details;
    const QJsonArray sections = summary.value(QStringLiteral("sections")).toArray();
    if (!sections.isEmpty()) {
        details.append(tr("%1 sections").arg(sections.size()));
    }
    const qint64 configKeys = summary.value(QStringLiteral("config_keys")).toInteger();
    if (configKeys > 0) {
        details.append(tr("%1 configuration fields").arg(configKeys));
    }
    const qint64 states = summary.value(QStringLiteral("relationship_states")).toInteger();
    const qint64 memories = summary.value(QStringLiteral("character_memories")).toInteger();
    if (states > 0 || memories > 0) {
        details.append(tr("%1 relationship states · %2 memories").arg(states).arg(memories));
    }
    if (!database.isEmpty()) {
        details.append(
            tr("%1 conversations · %2 private messages · %3 group messages")
                .arg(database.value(QStringLiteral("conversations")).toInteger())
                .arg(database.value(QStringLiteral("messages")).toInteger())
                .arg(database.value(QStringLiteral("group_messages")).toInteger()));
    }
    dataStatusLabel_->setText(
        details.isEmpty() ? action : QStringLiteral("%1\n%2").arg(action, details.join(" · ")));
}

void NativeMainWindow::refreshNativeAttachmentStats() {
    if (attachmentStatsLabel_ == nullptr) {
        return;
    }
    const QString databasePath = nativeDatabasePath();
    if (!backend_.loadAttachmentStats(databasePath)) {
        attachmentStatsLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        return;
    }
    const QJsonObject stats = parseObject(backend_.getAttachmentManagementJson());
    const qint64 files = stats.value(QStringLiteral("file_count")).toInteger();
    const qint64 bytes = stats.value(QStringLiteral("total_bytes")).toInteger();
    QString range;
    const qint64 oldest =
        stats.value(QStringLiteral("oldest_uploaded_at_unix")).toInteger(-1);
    const qint64 newest =
        stats.value(QStringLiteral("newest_uploaded_at_unix")).toInteger(-1);
    if (oldest >= 0 && newest >= 0) {
        const QString oldestLabel = QDateTime::fromSecsSinceEpoch(oldest)
                                        .toLocalTime()
                                        .toString(QStringLiteral("yyyy-MM-dd"));
        const QString newestLabel = QDateTime::fromSecsSinceEpoch(newest)
                                        .toLocalTime()
                                        .toString(QStringLiteral("yyyy-MM-dd"));
        range = oldestLabel == newestLabel
            ? tr(" · uploaded %1").arg(oldestLabel)
            : tr(" · uploaded %1 to %2").arg(oldestLabel, newestLabel);
    }
    attachmentStatsLabel_->setText(
        tr("%1 files · %2%3").arg(files).arg(formatAttachmentSize(bytes), range));
    attachmentCleanupOldButton_->setEnabled(files > 0);
    attachmentClearAllButton_->setEnabled(files > 0);
}

void NativeMainWindow::saveNativeAttachmentSettings() {
    const QJsonObject settings {
        {QStringLiteral("chat_attachment_auto_cleanup_enabled"),
         attachmentAutoCleanupSwitch_->isChecked()},
        {QStringLiteral("chat_attachment_retention_days"),
         attachmentRetentionDaysSpinBox_->value()},
    };
    if (!backend_.saveNativeSettings(configPath_, compactJson(settings))) {
        dataStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        QMessageBox::critical(this, tr("Attachment policy failed"), backend_.getStatus());
        return;
    }
    runtime_ = parseObject(backend_.getRuntimeConfigJson());
    if (attachmentAutoCleanupSwitch_->isChecked()) {
        const QString databasePath = nativeDatabasePath();
        if (!backend_.cleanupChatAttachments(
                databasePath, attachmentRetentionDaysSpinBox_->value())) {
            dataStatusLabel_->setText(backend_.getStatus());
            serviceStatusLabel_->setText(backend_.getStatus());
            return;
        }
        const QJsonObject result = parseObject(backend_.getAttachmentManagementJson());
        const qint64 removedReferences =
            result.value(QStringLiteral("removed_references")).toInteger();
        if (removedReferences > 0) {
            if (isGroupChatMode()) {
                refreshGroupChatState({}, true);
            } else {
                refreshChatState({}, true);
            }
        }
        dataStatusLabel_->setText(
            tr("Attachment policy saved · removed %1 expired files (%2) · %3 database references removed")
                .arg(result.value(QStringLiteral("deleted_files")).toInteger())
                .arg(formatAttachmentSize(
                    result.value(QStringLiteral("deleted_bytes")).toInteger()))
                .arg(removedReferences));
    } else {
        dataStatusLabel_->setText(tr("Attachment policy saved · automatic cleanup disabled"));
    }
    serviceStatusLabel_->setText(backend_.getStatus());
    refreshNativeAttachmentStats();
}

void NativeMainWindow::cleanupNativeChatAttachments(bool clearAll) {
    if (activeChatRequestId_ != 0 || groupSequenceActive_) {
        QMessageBox::warning(
            this,
            tr("Chat is still active"),
            tr("Wait for the current private or group response to finish before cleaning attachments."));
        return;
    }
    const int retentionDays = attachmentRetentionDaysSpinBox_->value();
    const QMessageBox::StandardButton reply = QMessageBox::warning(
        this,
        clearAll ? tr("Clear every chat attachment?") : tr("Clean expired attachments?"),
        clearAll
            ? tr("This permanently deletes every file in chat_attachments and removes all affected database references. This cannot be undone.")
            : tr("This permanently deletes attachment files older than %1 days and removes affected database references.")
                  .arg(retentionDays),
        QMessageBox::Yes | QMessageBox::No,
        QMessageBox::No);
    if (reply != QMessageBox::Yes) {
        return;
    }

    attachmentCleanupOldButton_->setEnabled(false);
    attachmentClearAllButton_->setEnabled(false);
    const QString databasePath = nativeDatabasePath();
    if (!backend_.cleanupChatAttachments(databasePath, clearAll ? 0 : retentionDays)) {
        dataStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        QMessageBox::critical(this, tr("Attachment cleanup failed"), backend_.getStatus());
        refreshNativeAttachmentStats();
        return;
    }
    const QJsonObject result = parseObject(backend_.getAttachmentManagementJson());
    const qint64 removedReferences =
        result.value(QStringLiteral("removed_references")).toInteger();
    if (clearAll && !pendingChatAttachments_.isEmpty()) {
        pendingChatAttachments_ = QJsonArray();
        updatePendingChatAttachments();
    }
    if (removedReferences > 0) {
        if (isGroupChatMode()) {
            refreshGroupChatState({}, true);
        } else {
            refreshChatState({}, true);
        }
    }
    dataStatusLabel_->setText(
        tr("Attachment cleanup finished · %1 files (%2) deleted · %3 failures · %4 database references removed")
            .arg(result.value(QStringLiteral("deleted_files")).toInteger())
            .arg(formatAttachmentSize(
                result.value(QStringLiteral("deleted_bytes")).toInteger()))
            .arg(result.value(QStringLiteral("failed_files")).toInteger())
            .arg(removedReferences));
    serviceStatusLabel_->setText(backend_.getStatus());
    refreshNativeAttachmentStats();
}

void NativeMainWindow::syncSettingsControls() {
    if (fpsSpinBox_ == nullptr) {
        return;
    }
    fpsSpinBox_->setValue(runtime_.value(QStringLiteral("fps")).toInt(120));
    opacitySpinBox_->setValue(runtime_.value(QStringLiteral("opacity")).toDouble(1.0));
    gameTopmostSwitch_->setChecked(
        runtime_.value(QStringLiteral("game_topmost")).toBool(false));
    obsWindowCaptureSwitch_->setChecked(
        runtime_.value(QStringLiteral("obs_window_capture_compatible")).toBool(false));
    hideLive2dModelSwitch_->setChecked(
        runtime_.value(QStringLiteral("hide_live2d_model")).toBool(false));
    vsyncSwitch_->setChecked(runtime_.value(QStringLiteral("vsync")).toBool(true));
    gpuAccelerationSwitch_->setChecked(
        runtime_.value(QStringLiteral("gpu_acceleration")).toBool(true));
    const QString quality =
        runtime_.value(QStringLiteral("live2d_quality")).toString(QStringLiteral("balanced"));
    const int qualityIndex = qualityComboBox_->findData(quality);
    qualityComboBox_->setCurrentIndex(qualityIndex < 0 ? 1 : qualityIndex);
    scaleSpinBox_->setValue(runtime_.value(QStringLiteral("live2d_scale")).toInt(100));
    idleActionsSwitch_->setChecked(
        runtime_.value(QStringLiteral("idle_actions_enabled")).toBool(true));
    randomActionsSwitch_->setChecked(
        runtime_.value(QStringLiteral("random_actions_enabled")).toBool(true));
    dragLockedSwitch_->setChecked(runtime_.value(QStringLiteral("drag_locked")).toBool());
    moveTogetherSwitch_->setChecked(
        runtime_.value(QStringLiteral("move_all_roles_together")).toBool());
    headTrackingSwitch_->setChecked(
        runtime_.value(QStringLiteral("head_tracking_enabled")).toBool(true));
    mutualGazeSwitch_->setChecked(
        runtime_.value(QStringLiteral("mutual_gaze_enabled")).toBool());
    emotionBehaviorSwitch_->setChecked(
        runtime_.value(QStringLiteral("emotion_behavior_enabled")).toBool(true));
    autoStartSwitch_->setChecked(
        runtime_.value(QStringLiteral("auto_start")).toBool(false));
    chatWindowAlwaysOnTopSwitch_->setChecked(
        runtime_.value(QStringLiteral("chat_window_always_on_top")).toBool(false));
    birthdayNotificationsSwitch_->setChecked(
        runtime_
            .value(QStringLiteral("birthday_tray_notifications_enabled"))
            .toBool(true));
    const QString theme =
        runtime_.value(QStringLiteral("dark_theme")).toString(QStringLiteral("follow_system"));
    const int themeIndex = themeComboBox_->findData(theme);
    themeComboBox_->setCurrentIndex(themeIndex < 0 ? 0 : themeIndex);
    applyTheme(theme);
}

bool NativeMainWindow::applyNativeAutoStart(bool enabled, QString* error) {
    return setNativeAutoStartEnabled(
        enabled,
        QCoreApplication::applicationFilePath(),
        nativeAutoStartArguments(projectRoot_, dataRoot_, configPath_, userModelsRoot_),
        error);
}

void NativeMainWindow::reconcileNativeAutoStart() {
    const bool desired = runtime_.value(QStringLiteral("auto_start")).toBool(false);
    QString error;
    const bool alreadyEnabled = nativeAutoStartEnabled(
        QCoreApplication::applicationFilePath(),
        nativeAutoStartArguments(projectRoot_, dataRoot_, configPath_, userModelsRoot_),
        &error);
    if (desired && alreadyEnabled) {
        return;
    }
    if (!applyNativeAutoStart(desired, &error)) {
        serviceStatusLabel_->setText(
            tr("Could not reconcile native auto-start: %1").arg(error));
    }
}

void NativeMainWindow::saveNativeSettings() {
    const QString quality = qualityComboBox_->currentData().toString();
    const bool rendererRestartRequired =
        runtime_.value(QStringLiteral("vsync")).toBool(true) != vsyncSwitch_->isChecked()
        || runtime_.value(QStringLiteral("gpu_acceleration")).toBool(true)
               != gpuAccelerationSwitch_->isChecked()
        || runtime_.value(QStringLiteral("live2d_quality"))
               .toString(QStringLiteral("balanced")) != quality;
    const bool desiredAutoStart = autoStartSwitch_->isChecked();
    QString autoStartError;
    const bool previousAutoStart = nativeAutoStartEnabled(
        QCoreApplication::applicationFilePath(),
        nativeAutoStartArguments(projectRoot_, dataRoot_, configPath_, userModelsRoot_),
        &autoStartError);
    if (!applyNativeAutoStart(desiredAutoStart, &autoStartError)) {
        serviceStatusLabel_->setText(
            tr("Could not update native auto-start: %1").arg(autoStartError));
        return;
    }
    const QJsonObject settings {
        {QStringLiteral("fps"), fpsSpinBox_->value()},
        {QStringLiteral("opacity"), opacitySpinBox_->value()},
        {QStringLiteral("game_topmost"), gameTopmostSwitch_->isChecked()},
        {QStringLiteral("obs_window_capture_compatible"),
         obsWindowCaptureSwitch_->isChecked()},
        {QStringLiteral("hide_live2d_model"), hideLive2dModelSwitch_->isChecked()},
        {QStringLiteral("auto_start"), desiredAutoStart},
        {QStringLiteral("chat_window_always_on_top"),
         chatWindowAlwaysOnTopSwitch_->isChecked()},
        {QStringLiteral("vsync"), vsyncSwitch_->isChecked()},
        {QStringLiteral("gpu_acceleration"), gpuAccelerationSwitch_->isChecked()},
        {QStringLiteral("live2d_quality"), quality},
        {QStringLiteral("live2d_scale"), scaleSpinBox_->value()},
        {QStringLiteral("live2d_idle_actions_enabled"), idleActionsSwitch_->isChecked()},
        {QStringLiteral("live2d_random_actions_enabled"), randomActionsSwitch_->isChecked()},
        {QStringLiteral("dark_theme"), themeComboBox_->currentData().toString()},
        {QStringLiteral("drag_locked"), dragLockedSwitch_->isChecked()},
        {QStringLiteral("move_all_roles_together"), moveTogetherSwitch_->isChecked()},
        {QStringLiteral("live2d_head_tracking_enabled"), headTrackingSwitch_->isChecked()},
        {QStringLiteral("live2d_mutual_gaze_enabled"), mutualGazeSwitch_->isChecked()},
        {QStringLiteral("emotion_behavior_enabled"), emotionBehaviorSwitch_->isChecked()},
        {QStringLiteral("birthday_tray_notifications_enabled"),
         birthdayNotificationsSwitch_->isChecked()},
    };
    const QString settingsJson = compactJson(settings);
    if (!backend_.saveNativeSettings(configPath_, settingsJson)) {
        QString rollbackError;
        const bool rolledBack = applyNativeAutoStart(previousAutoStart, &rollbackError);
        serviceStatusLabel_->setText(
            rolledBack
                ? backend_.getStatus()
                : tr("%1; auto-start rollback failed: %2")
                      .arg(backend_.getStatus(), rollbackError));
        return;
    }

    for (PetLaunchSpec& spec : activeSpecs_) {
        spec.fps = fpsSpinBox_->value();
        spec.opacity = opacitySpinBox_->value();
        spec.gameTopmost = gameTopmostSwitch_->isChecked();
        spec.obsWindowCaptureCompatible = obsWindowCaptureSwitch_->isChecked();
        spec.hideLive2dModel = hideLive2dModelSwitch_->isChecked();
        spec.vsync = vsyncSwitch_->isChecked();
        spec.gpuAcceleration = gpuAccelerationSwitch_->isChecked();
        spec.live2dQuality = quality;
        spec.live2dScale = scaleSpinBox_->value();
        spec.idleActionsEnabled = idleActionsSwitch_->isChecked();
        spec.randomActionsEnabled = randomActionsSwitch_->isChecked();
        spec.dragLocked = dragLockedSwitch_->isChecked();
        spec.moveAllRolesTogether = moveTogetherSwitch_->isChecked();
        spec.headTrackingEnabled = headTrackingSwitch_->isChecked();
        spec.mutualGazeEnabled = mutualGazeSwitch_->isChecked();
        spec.emotionBehaviorEnabled = emotionBehaviorSwitch_->isChecked();
    }
    const bool wasRunning = supervisor_.isRunning();
    bool delivered = true;
    if (wasRunning && rendererRestartRequired && !activeSpecs_.isEmpty()) {
        supervisor_.startAll(activeSpecs_);
    } else if (wasRunning) {
        delivered = supervisor_.broadcastSettings(settingsJson);
    }
    applyBackendState();
    rendererStatusLabel_->setText(
        wasRunning && rendererRestartRequired
            ? tr("Native settings saved; pet renderers are restarting for OpenGL policy, VSync or quality")
            : (delivered
                   ? tr("Native settings saved and applied")
                   : tr("Settings saved; running pets did not acknowledge the IPC broadcast")));
}

void NativeMainWindow::applyTheme(const QString& mode) {
    if (mode == QStringLiteral("on")) {
        qfw::setTheme(qfw::Theme::Dark);
    } else if (mode == QStringLiteral("off")) {
        qfw::setTheme(qfw::Theme::Light);
    } else {
        qfw::setTheme(qfw::Theme::Auto);
    }
}

void NativeMainWindow::populateModelList() {
    const QString previousPath =
        modelList_->currentItem() == nullptr
            ? QString()
            : modelList_->currentItem()->data(kPathRole).toString();
    modelList_->clear();
    int selectedRow = -1;
    for (int index = 0; index < catalog_.size(); ++index) {
        const ModelCatalogItem& model = catalog_.at(index);
        QString label = modelTitle(model);
        if (model.isDefault) {
            label += tr("  (default)");
        }
        label += QStringLiteral("  [%1]").arg(model.format.toUpper());
        auto* item = new QListWidgetItem(label, modelList_);
        item->setData(kPathRole, model.path);
        item->setData(kCharacterRole, model.character);
        item->setData(kCostumeRole, model.costume);
        item->setData(kFormatRole, model.format);
        item->setToolTip(model.path);
        if (model.path == previousPath) {
            selectedRow = index;
        }
    }
    modelCountLabel_->setText(
        tr("%1 characters · %2 costumes")
            .arg([this]() {
                QStringList characters;
                for (const ModelCatalogItem& model : catalog_) {
                    if (!characters.contains(model.character)) {
                        characters.append(model.character);
                    }
                }
                return characters.size();
            }())
            .arg(catalog_.size()));
    if (selectedRow < 0 && !catalog_.isEmpty()) {
        const std::optional<ModelCatalogItem> configured = configuredModel();
        if (configured.has_value()) {
            for (int index = 0; index < catalog_.size(); ++index) {
                if (catalog_.at(index).path == configured->path) {
                    selectedRow = index;
                    break;
                }
            }
        }
        if (selectedRow < 0) {
            selectedRow = 0;
        }
    }
    if (selectedRow >= 0) {
        modelList_->setCurrentRow(selectedRow);
    } else {
        updateModelDetails();
    }
}

void NativeMainWindow::populateClickMotionProfiles() {
    if (clickMotionProfileComboBox_ == nullptr) {
        return;
    }
    const std::optional<ModelCatalogItem> model = selectedModel();
    const QString selectedName = model.has_value()
        ? configuredPetFor(*model)
              .value(QStringLiteral("click_motion_profile_name"))
              .toString()
        : QString();
    const QHash<QString, QString> builtinLabels {
        {QStringLiteral("auto"), tr("Automatic matching")},
        {QStringLiteral("genki"), tr("Energetic")},
        {QStringLiteral("tsundere"), tr("Tsundere")},
        {QStringLiteral("shy"), tr("Shy")},
        {QStringLiteral("cool"), tr("Cool")},
        {QStringLiteral("surprised"), tr("Surprised")},
        {QStringLiteral("random"), tr("Random")},
    };

    updatingClickMotionControls_ = true;
    clickMotionProfileComboBox_->clear();
    clickMotionProfileComboBox_->addItem(
        tr("Current custom behavior"), QVariant(), QString());
    for (const QJsonValue& value :
         runtime_.value(QStringLiteral("click_motion_profiles")).toArray()) {
        const QJsonObject profile = value.toObject();
        const QString name = profile.value(QStringLiteral("name")).toString().trimmed();
        if (name.isEmpty()) {
            continue;
        }
        const bool builtin = profile.value(QStringLiteral("is_builtin")).toBool(false);
        const QString label = builtin
            ? builtinLabels.value(name, name)
            : name;
        clickMotionProfileComboBox_->addItem(label, QVariant(), name);
    }
    int selectedIndex = clickMotionProfileComboBox_->findData(selectedName);
    if (selectedIndex < 0) {
        selectedIndex = 0;
    }
    clickMotionProfileComboBox_->setCurrentIndex(selectedIndex);
    updatingClickMotionControls_ = false;
    syncClickMotionProfileControls();
}

void NativeMainWindow::syncClickMotionProfileControls() {
    if (clickMotionProfileComboBox_ == nullptr || updatingClickMotionControls_) {
        return;
    }
    const std::optional<ModelCatalogItem> model = selectedModel();
    const bool configured = model.has_value() && !configuredPetFor(*model).isEmpty();
    const QString name = clickMotionProfileComboBox_->currentData().toString();
    const bool builtin = isBuiltinClickMotionProfile(name);
    clickMotionApplyButton_->setEnabled(configured);
    clickMotionSaveButton_->setEnabled(configured);
    clickMotionDeleteButton_->setEnabled(!name.isEmpty() && !builtin);
    if (!builtin && !name.isEmpty()) {
        clickMotionProfileNameEdit_->setText(name);
    } else if (builtin) {
        clickMotionProfileNameEdit_->clear();
    }
    if (!configured) {
        clickMotionStatusLabel_->setText(
            tr("This costume is not in the configured pet fleet; add it before editing behavior."));
    } else if (name.isEmpty()) {
        clickMotionStatusLabel_->setText(
            tr("The selected costume keeps its current custom click map."));
    } else {
        clickMotionStatusLabel_->setText(
            tr("Ready to apply profile “%1” to the selected costume.").arg(name));
    }
}

bool NativeMainWindow::mutateSelectedClickMotionProfile(
    const QString& operation,
    const QString& name) {
    const std::optional<ModelCatalogItem> model = selectedModel();
    if (!model.has_value() && operation != QStringLiteral("delete")) {
        clickMotionStatusLabel_->setText(tr("No model is selected"));
        return false;
    }
    QJsonObject command {
        {QStringLiteral("op"), operation},
        {QStringLiteral("name"), name.trimmed()},
    };
    if (model.has_value()) {
        command.insert(QStringLiteral("character"), model->character);
        command.insert(QStringLiteral("costume"), model->costume);
    }
    if (!backend_.mutateClickMotionProfile(
            projectRoot_, userModelsRoot_, configPath_, compactJson(command))) {
        clickMotionStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        return false;
    }
    const QString status = backend_.getStatus();
    applyBackendState();
    if (model.has_value()) {
        broadcastClickMotionSettings(*model);
    }
    clickMotionStatusLabel_->setText(status);
    serviceStatusLabel_->setText(status);
    return true;
}

void NativeMainWindow::applySelectedClickMotionProfile() {
    mutateSelectedClickMotionProfile(
        QStringLiteral("apply"),
        clickMotionProfileComboBox_->currentData().toString());
}

void NativeMainWindow::saveCurrentClickMotionProfile() {
    const QString name = clickMotionProfileNameEdit_->text().trimmed();
    if (name.isEmpty()) {
        clickMotionStatusLabel_->setText(tr("Enter a custom profile name first"));
        return;
    }
    mutateSelectedClickMotionProfile(QStringLiteral("save_current"), name);
}

void NativeMainWindow::deleteSelectedClickMotionProfile() {
    const QString name = clickMotionProfileComboBox_->currentData().toString();
    if (name.isEmpty() || isBuiltinClickMotionProfile(name)) {
        return;
    }
    if (QMessageBox::question(
            this,
            tr("Delete click profile"),
            tr("Delete custom click profile “%1”? Existing model action maps are kept.").arg(name))
        != QMessageBox::Yes) {
        return;
    }
    mutateSelectedClickMotionProfile(QStringLiteral("delete"), name);
}

void NativeMainWindow::broadcastClickMotionSettings(const ModelCatalogItem& model) {
    const QJsonObject configured = configuredPetFor(model);
    const QString actionsJson = compactJson(
        configured.value(QStringLiteral("click_motion_actions")).toObject());
    for (PetLaunchSpec& spec : activeSpecs_) {
        if (QDir::cleanPath(spec.modelPath) == QDir::cleanPath(model.path)) {
            spec.clickMotionActions = actionsJson;
        }
    }
    if (!supervisor_.isRunning()) {
        return;
    }
    QJsonArray models;
    for (const PetLaunchSpec& spec : std::as_const(activeSpecs_)) {
        models.append(QJsonObject {
            {QStringLiteral("character"), spec.character},
            {QStringLiteral("path"), spec.modelPath},
            {QStringLiteral("click_motion_actions"), parseObject(spec.clickMotionActions)},
        });
    }
    supervisor_.broadcastSettings(compactJson(QJsonObject {
        {QStringLiteral("models"), models},
    }));
}

void NativeMainWindow::updateModelDetails() {
    const std::optional<ModelCatalogItem> model = selectedModel();
    launchSelectedButton_->setEnabled(model.has_value());
    if (!model.has_value()) {
        modelDetailsLabel_->setText(tr("No pet model was found in either model root"));
        syncClickMotionProfileControls();
        return;
    }
    const QJsonObject configured = configuredPetFor(*model);
    const QString mode =
        configured.value(QStringLiteral("pet_mode")).toString(QStringLiteral("live2d"));
    const bool pixelAvailable = QFileInfo::exists(
        QDir(projectRoot_)
            .filePath(QStringLiteral("pixels/%1.webp").arg(model->character)));
    modelDetailsLabel_->setText(
        QStringLiteral("%1\n%2 · %3\n%4\n%5")
            .arg(
                modelTitle(*model),
                model->character,
                model->costume,
                model->path,
                tr("Configured mode: %1 · pixel assets: %2")
                    .arg(
                        mode == QStringLiteral("pixel") ? tr("pixel") : tr("Live2D"),
                        pixelAvailable ? tr("available") : tr("unavailable"))));
    populateClickMotionProfiles();
}

void NativeMainWindow::populateChatCharacters() {
    if (chatCharacterComboBox_ == nullptr || chatGroupMembersList_ == nullptr) {
        return;
    }
    const QString previous = chatCharacterComboBox_->currentData().toString();
    QStringList previousGroupMembers;
    for (const QListWidgetItem* item : chatGroupMembersList_->selectedItems()) {
        previousGroupMembers.append(item->data(Qt::UserRole).toString());
    }
    if (previousGroupMembers.isEmpty() && chatGroupComboBox_ != nullptr) {
        const QString groupKey = chatGroupComboBox_->currentData().toString();
        if (groupKey.startsWith(QStringLiteral("__group__:"))) {
            previousGroupMembers = groupKey.mid(10).split(u'|', Qt::SkipEmptyParts);
        }
    }
    updatingChatControls_ = true;
    chatCharacterComboBox_->clear();
    chatGroupMembersList_->clear();
    QStringList pinnedKeys;
    for (const QJsonValue& value : runtime_.value(QStringLiteral("pinned_chat_keys")).toArray()) {
        const QString key = value.toString().trimmed();
        if (!key.isEmpty() && !pinnedKeys.contains(key)) {
            pinnedKeys.append(key);
        }
    }
    QList<ModelCatalogItem> chatModels;
    QStringList added;
    for (const ModelCatalogItem& model : catalog_) {
        if (added.contains(model.character)) {
            continue;
        }
        added.append(model.character);
        chatModels.append(model);
    }
    std::stable_sort(
        chatModels.begin(),
        chatModels.end(),
        [&pinnedKeys](const ModelCatalogItem& left, const ModelCatalogItem& right) {
            const int leftIndex = pinnedKeys.indexOf(left.character);
            const int rightIndex = pinnedKeys.indexOf(right.character);
            if (leftIndex < 0 && rightIndex < 0) {
                return false;
            }
            if (leftIndex < 0) {
                return false;
            }
            return rightIndex < 0 || leftIndex < rightIndex;
        });
    for (const ModelCatalogItem& model : std::as_const(chatModels)) {
        const QString displayName = displayNameForCharacter(model.character);
        const QString avatarPath = chatAvatarPath(model.character);
        const QVariant avatar = avatarPath.isEmpty()
            ? QVariant()
            : QVariant::fromValue(QIcon(avatarPath));
        chatCharacterComboBox_->addItem(
            displayName,
            avatar,
            model.character);
        auto* member = new QListWidgetItem(
            displayName,
            chatGroupMembersList_);
        member->setData(Qt::UserRole, model.character);
        if (!avatarPath.isEmpty()) {
            member->setIcon(QIcon(avatarPath));
        }
    }
    int index = chatCharacterComboBox_->findData(previous);
    if (index < 0) {
        const QString selected = runtime_.value(QStringLiteral("selected_character")).toString();
        index = chatCharacterComboBox_->findData(selected);
    }
    if (index < 0 && chatCharacterComboBox_->count() > 0) {
        index = 0;
    }
    chatCharacterComboBox_->setCurrentIndex(index);

    if (previousGroupMembers.isEmpty()) {
        for (const ModelCatalogItem& model : configuredModels()) {
            if (!previousGroupMembers.contains(model.character)) {
                previousGroupMembers.append(model.character);
            }
        }
    }
    int selectedCount = 0;
    for (int row = 0; row < chatGroupMembersList_->count(); ++row) {
        QListWidgetItem* item = chatGroupMembersList_->item(row);
        const bool selected = previousGroupMembers.contains(
            item->data(Qt::UserRole).toString());
        item->setSelected(selected);
        selectedCount += selected ? 1 : 0;
    }
    for (int row = 0; selectedCount < 2 && row < chatGroupMembersList_->count(); ++row) {
        QListWidgetItem* item = chatGroupMembersList_->item(row);
        if (!item->isSelected()) {
            item->setSelected(true);
            ++selectedCount;
        }
    }
    const bool groupMode = isGroupChatMode();
    chatPrivateSelector_->setVisible(!groupMode);
    updatingChatControls_ = false;
    syncChatPresentationControls();
}

bool NativeMainWindow::isGroupChatMode() const {
    return chatModeComboBox_ != nullptr
        && chatModeComboBox_->currentData().toString() == QStringLiteral("group");
}

QJsonArray NativeMainWindow::selectedGroupMembers() const {
    QJsonArray members;
    if (chatGroupMembersList_ == nullptr) {
        return members;
    }
    for (int row = 0; row < chatGroupMembersList_->count(); ++row) {
        const QListWidgetItem* item = chatGroupMembersList_->item(row);
        if (!item->isSelected()) {
            continue;
        }
        const QString key = item->data(Qt::UserRole).toString();
        if (!key.isEmpty()) {
            members.append(QJsonObject{
                {QStringLiteral("key"), key},
                {QStringLiteral("name"), item->text()},
            });
        }
    }
    return members;
}

QString NativeMainWindow::selectedGroupKey() const {
    QStringList keys;
    for (const QJsonValue& value : selectedGroupMembers()) {
        keys.append(value.toObject().value(QStringLiteral("key")).toString());
    }
    if (keys.size() < 2) {
        return {};
    }
    std::stable_sort(
        keys.begin(),
        keys.end(),
        [](const QString& left, const QString& right) {
            return QString::compare(left, right, Qt::CaseInsensitive) < 0;
        });
    return QStringLiteral("__group__:") + keys.join(u'|');
}

QString NativeMainWindow::currentChatKey() const {
    if (isGroupChatMode()) {
        QString key = selectedGroupKey();
        if (key.isEmpty() && chatGroupComboBox_ != nullptr) {
            key = chatGroupComboBox_->currentData().toString();
        }
        return key.trimmed();
    }
    return chatCharacterComboBox_ == nullptr
        ? QString()
        : chatCharacterComboBox_->currentData().toString().trimmed();
}

QString NativeMainWindow::chatAvatarPath(const QString& character) const {
    const QString path = runtime_
                             .value(QStringLiteral("chat_avatar_paths"))
                             .toObject()
                             .value(character)
                             .toString()
                             .trimmed();
    return QFileInfo::exists(path) ? path : QString();
}

void NativeMainWindow::syncChatPresentationControls() {
    if (chatGroupSelector_ == nullptr || chatPinButton_ == nullptr) {
        return;
    }
    const bool group = isGroupChatMode();
    const bool collapsed = runtime_
                               .value(QStringLiteral("group_chat_sidebar_collapsed"))
                               .toBool(false);
    chatGroupSelector_->setVisible(group && !collapsed);
    chatGroupSidebarToggleButton_->setVisible(group);
    chatGroupSidebarToggleButton_->setText(
        collapsed ? tr("Show members") : tr("Hide members"));
    chatRenameButton_->setVisible(!group);
    chatAvatarButton_->setVisible(!group);
    chatResetAvatarButton_->setVisible(!group);

    const QString key = currentChatKey();
    const QJsonArray pinned = runtime_.value(QStringLiteral("pinned_chat_keys")).toArray();
    bool isPinned = false;
    for (const QJsonValue& value : pinned) {
        if (value.toString() == key) {
            isPinned = true;
            break;
        }
    }
    chatPinButton_->setEnabled(!key.isEmpty());
    chatPinButton_->setText(isPinned ? tr("Unpin chat") : tr("Pin chat"));
    if (!group) {
        const QString character = currentChatKey();
        chatRenameButton_->setEnabled(!character.isEmpty());
        chatAvatarButton_->setEnabled(!character.isEmpty());
        chatResetAvatarButton_->setEnabled(!chatAvatarPath(character).isEmpty());
    }

    if (group && !collapsed && chatGroupSplitter_ != nullptr) {
        const double ratio = std::clamp(
            runtime_
                .value(QStringLiteral("group_chat_sidebar_ratio"))
                .toDouble(0.28),
            0.18,
            0.46);
        const int total = std::max(640, chatGroupSplitter_->width());
        const QSignalBlocker blocker(chatGroupSplitter_);
        chatGroupSplitter_->setSizes(
            {static_cast<int>(std::round(total * ratio)),
             static_cast<int>(std::round(total * (1.0 - ratio)))});
    }
}

bool NativeMainWindow::saveChatPresentationSettings(const QJsonObject& changes) {
    if (changes.isEmpty()) {
        return true;
    }
    if (!backend_.saveNativeSettings(configPath_, compactJson(changes))) {
        chatStatusLabel_->setText(backend_.getStatus());
        serviceStatusLabel_->setText(backend_.getStatus());
        return false;
    }
    runtime_ = parseObject(backend_.getRuntimeConfigJson());
    serviceStatusLabel_->setText(backend_.getStatus());
    return true;
}

void NativeMainWindow::toggleCurrentChatPin() {
    const QString key = currentChatKey();
    if (key.isEmpty()) {
        return;
    }
    QJsonArray next;
    bool wasPinned = false;
    for (const QJsonValue& value : runtime_.value(QStringLiteral("pinned_chat_keys")).toArray()) {
        const QString existing = value.toString().trimmed();
        if (existing == key) {
            wasPinned = true;
        } else if (!existing.isEmpty()) {
            next.append(existing);
        }
    }
    if (!wasPinned) {
        next.insert(0, key);
    }
    if (!saveChatPresentationSettings({
            {QStringLiteral("pinned_chat_keys"), next},
        })) {
        return;
    }
    populateChatCharacters();
    refreshChatState({}, true);
    syncChatPresentationControls();
}

void NativeMainWindow::renameCurrentPrivateChat() {
    if (isGroupChatMode()) {
        return;
    }
    const QString character = currentChatKey();
    if (character.isEmpty()) {
        return;
    }
    const QJsonObject names = runtime_.value(QStringLiteral("chat_display_names")).toObject();
    bool accepted = false;
    const QString current = names.value(character).toString(displayNameForCharacter(character));
    const QString name = QInputDialog::getText(
                             this,
                             tr("Rename private chat"),
                             tr("Display name; leave blank to restore the model name"),
                             QLineEdit::Normal,
                             current,
                             &accepted)
                             .trimmed();
    if (!accepted) {
        return;
    }
    QJsonObject updated = names;
    if (name.isEmpty()) {
        updated.remove(character);
    } else {
        updated.insert(character, name.left(80));
    }
    if (saveChatPresentationSettings({
            {QStringLiteral("chat_display_names"), updated},
        })) {
        populateChatCharacters();
        refreshChatState({}, true);
    }
}

void NativeMainWindow::chooseCurrentChatAvatar() {
    if (isGroupChatMode()) {
        return;
    }
    const QString character = currentChatKey();
    if (character.isEmpty()) {
        return;
    }
    const QString source = QFileDialog::getOpenFileName(
        this,
        tr("Choose chat avatar"),
        QString(),
        tr("Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"));
    if (source.isEmpty()) {
        return;
    }
    const QString avatarRoot = QDir(dataRoot_).filePath(QStringLiteral("chat_avatars"));
    if (!QDir().mkpath(avatarRoot)) {
        chatStatusLabel_->setText(tr("Could not create the chat avatar directory"));
        return;
    }
    QString suffix = QFileInfo(source).suffix().toLower();
    if (!QStringList {QStringLiteral("png"), QStringLiteral("jpg"),
                      QStringLiteral("jpeg"), QStringLiteral("webp"),
                      QStringLiteral("bmp"), QStringLiteral("gif")}
             .contains(suffix)) {
        suffix = QStringLiteral("png");
    }
    const QString target = QDir(avatarRoot).filePath(
        QStringLiteral("%1.%2")
            .arg(QUuid::createUuid().toString(QUuid::WithoutBraces), suffix));
    if (!QFile::copy(source, target)) {
        chatStatusLabel_->setText(tr("Could not copy the selected chat avatar"));
        return;
    }
    QJsonObject avatars = runtime_.value(QStringLiteral("chat_avatar_paths")).toObject();
    avatars.insert(character, target);
    if (saveChatPresentationSettings({
            {QStringLiteral("chat_avatar_paths"), avatars},
        })) {
        populateChatCharacters();
        syncChatPresentationControls();
    }
}

void NativeMainWindow::resetCurrentChatAvatar() {
    if (isGroupChatMode()) {
        return;
    }
    const QString character = currentChatKey();
    QJsonObject avatars = runtime_.value(QStringLiteral("chat_avatar_paths")).toObject();
    if (character.isEmpty() || !avatars.contains(character)) {
        return;
    }
    avatars.remove(character);
    if (saveChatPresentationSettings({
            {QStringLiteral("chat_avatar_paths"), avatars},
        })) {
        populateChatCharacters();
        syncChatPresentationControls();
    }
}

void NativeMainWindow::toggleGroupChatSidebar() {
    if (!isGroupChatMode()) {
        return;
    }
    const bool collapsed = runtime_
                               .value(QStringLiteral("group_chat_sidebar_collapsed"))
                               .toBool(false);
    if (saveChatPresentationSettings({
            {QStringLiteral("group_chat_sidebar_collapsed"), !collapsed},
        })) {
        syncChatPresentationControls();
    }
}

void NativeMainWindow::scheduleGroupChatLayoutSave() {
    if (!updatingChatControls_ && isGroupChatMode()
        && chatGroupSelector_ != nullptr && chatGroupSelector_->isVisible()) {
        chatLayoutSaveTimer_.start();
    }
}

QString NativeMainWindow::displayNameForCharacter(const QString& character) const {
    const QString customName = runtime_
                                   .value(QStringLiteral("chat_display_names"))
                                   .toObject()
                                   .value(character)
                                   .toString()
                                   .trimmed();
    if (!customName.isEmpty()) {
        return customName;
    }
    if (chatGroupMembersList_ != nullptr) {
        for (int row = 0; row < chatGroupMembersList_->count(); ++row) {
            const QListWidgetItem* item = chatGroupMembersList_->item(row);
            if (item->data(Qt::UserRole).toString() == character) {
                return item->text();
            }
        }
    }
    const auto found = std::find_if(
        catalog_.cbegin(),
        catalog_.cend(),
        [&character](const ModelCatalogItem& model) {
            return model.character == character;
        });
    if (found == catalog_.cend()) {
        return character;
    }
    return found->characterDisplay.isEmpty() ? found->character : found->characterDisplay;
}

QString NativeMainWindow::groupDisplayName(const QString& groupKey) const {
    if (!groupKey.startsWith(QStringLiteral("__group__:"))) {
        return groupKey;
    }
    QStringList names;
    for (const QString& character : groupKey.mid(10).split(u'|', Qt::SkipEmptyParts)) {
        names.append(displayNameForCharacter(character));
    }
    return names.join(QStringLiteral("、"));
}

void NativeMainWindow::selectGroupKeyMembers(const QString& groupKey) {
    if (chatGroupMembersList_ == nullptr
        || !groupKey.startsWith(QStringLiteral("__group__:"))) {
        return;
    }
    const QStringList keys = groupKey.mid(10).split(u'|', Qt::SkipEmptyParts);
    const QSignalBlocker blocker(chatGroupMembersList_);
    for (int row = 0; row < chatGroupMembersList_->count(); ++row) {
        QListWidgetItem* item = chatGroupMembersList_->item(row);
        item->setSelected(keys.contains(item->data(Qt::UserRole).toString()));
    }
}

void NativeMainWindow::refreshChatState(
    const QString& requestedConversationId,
    bool resetPagination) {
    if (chatCharacterComboBox_ == nullptr || chatTranscript_ == nullptr) {
        return;
    }
    if (isGroupChatMode()) {
        refreshGroupChatState(requestedConversationId, resetPagination);
        return;
    }
    draftingNewConversation_ = false;
    const QString character = chatCharacterComboBox_->currentData().toString();
    if (resetPagination) {
        chatMessageLimit_ = kChatMessagePageSize;
    }
    if (character.isEmpty()) {
        chatConversationComboBox_->clear();
        chatTranscriptBase_.clear();
        chatTranscript_->clear();
        chatLoadOlderButton_->setEnabled(false);
        chatStatusLabel_->setText(tr("No character is available"));
        return;
    }
    const QString databasePath = nativeDatabasePath();
    const QString userKey =
        runtime_.value(QStringLiteral("active_user_key")).toString(QStringLiteral("__default__"));
    if (!backend_.loadChatState(
            databasePath,
            character,
            userKey,
            requestedConversationId,
            chatMessageLimit_)) {
        chatStatusLabel_->setText(backend_.getStatus());
        chatTranscriptBase_.clear();
        chatTranscript_->clear();
        chatLoadOlderButton_->setEnabled(false);
        return;
    }

    const QJsonArray conversations = parseArray(backend_.getChatConversationsJson());
    const QString activeId = backend_.getChatActiveConversationId();
    updatingChatControls_ = true;
    chatConversationComboBox_->clear();
    int activeIndex = -1;
    for (const QJsonValue& value : conversations) {
        const QJsonObject conversation = value.toObject();
        const QString id = QString::number(conversation.value(QStringLiteral("id")).toInteger());
        QString label = conversation.value(QStringLiteral("title")).toString().trimmed();
        if (label.isEmpty()) {
            label = conversation.value(QStringLiteral("last_message_content")).toString().trimmed();
        }
        if (label.isEmpty()) {
            label = tr("Conversation %1").arg(id);
        }
        const QString lastMessageAt =
            conversation.value(QStringLiteral("last_message_at")).toString();
        if (!lastMessageAt.isEmpty()) {
            label += QStringLiteral("  ·  ") + lastMessageAt;
        }
        chatConversationComboBox_->addItem(label, QVariant(), id);
        if (id == activeId) {
            activeIndex = chatConversationComboBox_->count() - 1;
        }
    }
    chatConversationComboBox_->setCurrentIndex(activeIndex);
    updatingChatControls_ = false;
    syncChatPresentationControls();
    chatDeleteConversationButton_->setEnabled(activeIndex >= 0 && activeChatRequestId_ == 0);

    const QJsonArray messages = parseArray(backend_.getChatMessagesJson());
    const bool hasOlderMessages = backend_.getChatHasOlderMessages();
    chatLoadOlderButton_->setEnabled(hasOlderMessages && chatMessageLimit_ < kChatMessageLimit);
    QStringList transcript;
    transcript.reserve(messages.size() * 3);
    for (const QJsonValue& value : messages) {
        const QJsonObject message = value.toObject();
        const QString role = message.value(QStringLiteral("role")).toString();
        const QString createdAt = message.value(QStringLiteral("created_at")).toString();
        transcript.append(
            createdAt.isEmpty()
                ? QStringLiteral("[%1]").arg(role)
                : QStringLiteral("[%1 · %2]").arg(role, createdAt));
        transcript.append(message.value(QStringLiteral("content")).toString());
        transcript.append(attachmentSummaries(
            message.value(QStringLiteral("attachments_json")).toString()));
        transcript.append(QString());
    }
    chatTranscriptBase_ = transcript.join(u'\n');
    if (activeChatRequestId_ == 0) {
        chatTranscript_->setPlainText(chatTranscriptBase_);
    } else {
        renderChatStreamPreview();
    }
    chatStatusLabel_->setText(
        conversations.isEmpty()
            ? tr("No saved conversation for %1 and user %2").arg(character, userKey)
            : tr("%1 conversations · %2 messages shown%3")
                  .arg(conversations.size())
                  .arg(messages.size())
                  .arg(hasOlderMessages ? tr(" · older messages available") : QString()));
    setChatBusy(activeChatRequestId_ != 0 || groupSequenceActive_);
}

void NativeMainWindow::refreshGroupChatState(
    const QString& requestedConversationId,
    bool resetPagination) {
    if (chatGroupMembersList_ == nullptr || chatTranscript_ == nullptr) {
        return;
    }
    draftingNewConversation_ = false;
    if (resetPagination) {
        chatMessageLimit_ = kChatMessagePageSize;
    }
    QString groupKey = groupSequenceActive_ ? activeGroupKey_ : selectedGroupKey();
    if (groupKey.isEmpty() && chatGroupComboBox_ != nullptr) {
        groupKey = chatGroupComboBox_->currentData().toString();
    }
    const QString databasePath = nativeDatabasePath();
    const QString userKey = runtime_
                                .value(QStringLiteral("active_user_key"))
                                .toString(QStringLiteral("__default__"));
    if (!backend_.loadGroupChatState(
            databasePath,
            groupKey,
            userKey,
            requestedConversationId,
            chatMessageLimit_)) {
        chatStatusLabel_->setText(backend_.getStatus());
        chatTranscriptBase_.clear();
        chatTranscript_->clear();
        chatLoadOlderButton_->setEnabled(false);
        return;
    }

    const QJsonObject snapshot = parseObject(backend_.getChatTurnJson());
    const QString activeGroupKey = snapshot
                                       .value(QStringLiteral("active_group_key"))
                                       .toString(groupKey);
    if (!activeGroupKey.isEmpty()) {
        selectGroupKeyMembers(activeGroupKey);
    }
    const QJsonArray chats = snapshot.value(QStringLiteral("chats")).toArray();
    updatingChatControls_ = true;
    chatGroupComboBox_->clear();
    QStringList pinnedKeys;
    for (const QJsonValue& value : runtime_.value(QStringLiteral("pinned_chat_keys")).toArray()) {
        const QString key = value.toString().trimmed();
        if (!key.isEmpty() && !pinnedKeys.contains(key)) {
            pinnedKeys.append(key);
        }
    }
    QList<QJsonObject> sortedChats;
    for (const QJsonValue& value : chats) {
        if (value.isObject()) {
            sortedChats.append(value.toObject());
        }
    }
    std::stable_sort(
        sortedChats.begin(),
        sortedChats.end(),
        [&pinnedKeys](const QJsonObject& left, const QJsonObject& right) {
            const int leftIndex = pinnedKeys.indexOf(
                left.value(QStringLiteral("group_key")).toString());
            const int rightIndex = pinnedKeys.indexOf(
                right.value(QStringLiteral("group_key")).toString());
            if (leftIndex < 0 && rightIndex < 0) {
                return false;
            }
            if (leftIndex < 0) {
                return false;
            }
            return rightIndex < 0 || leftIndex < rightIndex;
        });
    QStringList groupKeys;
    for (const QJsonObject& chat : std::as_const(sortedChats)) {
        const QString key = chat.value(QStringLiteral("group_key")).toString();
        if (key.isEmpty() || groupKeys.contains(key)) {
            continue;
        }
        groupKeys.append(key);
        chatGroupComboBox_->addItem(groupDisplayName(key), QVariant(), key);
    }
    if (!activeGroupKey.isEmpty() && !groupKeys.contains(activeGroupKey)) {
        groupKeys.append(activeGroupKey);
        chatGroupComboBox_->addItem(
            tr("New group · %1").arg(groupDisplayName(activeGroupKey)),
            QVariant(),
            activeGroupKey);
    }
    chatGroupComboBox_->setCurrentIndex(chatGroupComboBox_->findData(activeGroupKey));

    const QJsonArray conversations = parseArray(backend_.getChatConversationsJson());
    const QString activeId = backend_.getChatActiveConversationId();
    chatConversationComboBox_->clear();
    int activeIndex = -1;
    for (const QJsonValue& value : conversations) {
        const QJsonObject conversation = value.toObject();
        const QString id = conversation.value(QStringLiteral("conversation_id")).toString();
        QString label = conversation.value(QStringLiteral("content")).toString().trimmed();
        if (label.isEmpty()) {
            label = tr("Group conversation %1").arg(id);
        }
        const QString createdAt = conversation.value(QStringLiteral("created_at")).toString();
        if (!createdAt.isEmpty()) {
            label += QStringLiteral("  ·  ") + createdAt;
        }
        chatConversationComboBox_->addItem(label, QVariant(), id);
        if (id == activeId) {
            activeIndex = chatConversationComboBox_->count() - 1;
        }
    }
    chatConversationComboBox_->setCurrentIndex(activeIndex);
    updatingChatControls_ = false;
    syncChatPresentationControls();
    chatDeleteConversationButton_->setEnabled(
        activeIndex >= 0 && activeChatRequestId_ == 0 && !groupSequenceActive_);

    const QJsonArray messages = parseArray(backend_.getChatMessagesJson());
    const bool hasOlderMessages = backend_.getChatHasOlderMessages();
    chatLoadOlderButton_->setEnabled(
        hasOlderMessages && chatMessageLimit_ < kChatMessageLimit);
    QStringList transcript;
    transcript.reserve(messages.size() * 3);
    for (const QJsonValue& value : messages) {
        const QJsonObject message = value.toObject();
        const QString role = message.value(QStringLiteral("role")).toString();
        const QString createdAt = message.value(QStringLiteral("created_at")).toString();
        transcript.append(
            createdAt.isEmpty()
                ? QStringLiteral("[%1]").arg(role)
                : QStringLiteral("[%1 · %2]").arg(role, createdAt));
        transcript.append(message.value(QStringLiteral("content")).toString());
        transcript.append(attachmentSummaries(
            message.value(QStringLiteral("attachments_json")).toString()));
        transcript.append(QString());
    }
    chatTranscriptBase_ = transcript.join(u'\n');
    if (activeChatRequestId_ == 0) {
        chatTranscript_->setPlainText(chatTranscriptBase_);
    } else {
        renderChatStreamPreview();
    }
    chatStatusLabel_->setText(
        conversations.isEmpty()
            ? tr("No saved conversation for group %1 and user %2")
                  .arg(groupDisplayName(activeGroupKey), userKey)
            : tr("%1 group conversations · %2 messages shown%3")
                  .arg(conversations.size())
                  .arg(messages.size())
                  .arg(hasOlderMessages ? tr(" · older messages available") : QString()));
    setChatBusy(activeChatRequestId_ != 0 || groupSequenceActive_);
}

void NativeMainWindow::startNewChatConversation() {
    const bool hasTarget = isGroupChatMode()
        ? !selectedGroupKey().isEmpty()
        : !chatCharacterComboBox_->currentData().toString().isEmpty();
    if (activeChatRequestId_ != 0 || groupSequenceActive_ || !hasTarget) {
        return;
    }
    draftingNewConversation_ = true;
    const QSignalBlocker blocker(chatConversationComboBox_);
    chatConversationComboBox_->setCurrentIndex(-1);
    chatTranscriptBase_.clear();
    chatTranscript_->clear();
    chatLoadOlderButton_->setEnabled(false);
    chatDeleteConversationButton_->setEnabled(false);
    chatStatusLabel_->setText(
        isGroupChatMode()
            ? tr("New group conversation · it will be created when you send")
            : tr("New conversation · it will be created when you send"));
    chatInput_->setFocus();
    setChatBusy(false);
}

void NativeMainWindow::deleteSelectedChatConversation() {
    if (activeChatRequestId_ != 0 || groupSequenceActive_ || draftingNewConversation_) {
        return;
    }
    const QString conversationId = chatConversationComboBox_->currentData().toString();
    const QString targetKey = isGroupChatMode()
        ? selectedGroupKey()
        : chatCharacterComboBox_->currentData().toString();
    if (conversationId.isEmpty() || targetKey.isEmpty()) {
        return;
    }
    if (QMessageBox::question(
            this,
            tr("Delete conversation"),
            tr("Delete this conversation and its saved attachment copies?"),
            QMessageBox::Yes | QMessageBox::No,
            QMessageBox::No)
        != QMessageBox::Yes) {
        return;
    }
    const QString databasePath = nativeDatabasePath();
    const QString userKey = runtime_
                                .value(QStringLiteral("active_user_key"))
                                .toString(QStringLiteral("__default__"));
    const bool deleted = isGroupChatMode()
        ? backend_.deleteGroupChatConversation(
              databasePath,
              targetKey,
              userKey,
              conversationId)
        : backend_.deleteChatConversation(
              databasePath,
              targetKey,
              userKey,
              conversationId);
    if (!deleted) {
        chatStatusLabel_->setText(backend_.getStatus());
        return;
    }
    const QString status = backend_.getStatus();
    refreshChatState({}, true);
    chatStatusLabel_->setText(status);
}

void NativeMainWindow::chooseChatAttachments() {
    if (activeChatRequestId_ != 0 || groupSequenceActive_) {
        return;
    }
    constexpr int kMaximumPendingAttachments = 32;
    const int remaining = kMaximumPendingAttachments - pendingChatAttachments_.size();
    if (remaining <= 0) {
        chatStatusLabel_->setText(tr("At most 32 attachments can be pending"));
        return;
    }
    QStringList paths = QFileDialog::getOpenFileNames(
        this,
        tr("Choose chat attachments"),
        QString(),
        tr("All files (*)"));
    if (paths.isEmpty()) {
        return;
    }
    paths = paths.mid(0, remaining);
    QJsonArray sources;
    for (const QString& path : paths) {
        sources.append(path);
    }
    const QString databasePath = nativeDatabasePath();
    const QString sourceJson =
        QString::fromUtf8(QJsonDocument(sources).toJson(QJsonDocument::Compact));
    const bool imported = backend_.importChatAttachments(databasePath, sourceJson);
    const QJsonObject result = parseObject(backend_.getChatImportedAttachmentsJson());
    for (const QJsonValue& value : result.value(QStringLiteral("attachments")).toArray()) {
        if (value.isObject()) {
            pendingChatAttachments_.append(value);
        }
    }
    updatePendingChatAttachments();
    const QJsonArray errors = result.value(QStringLiteral("errors")).toArray();
    if (!errors.isEmpty()) {
        QStringList messages;
        for (const QJsonValue& error : errors) {
            messages.append(error.toString());
        }
        chatStatusLabel_->setText(messages.join(QStringLiteral(" · ")));
    } else if (imported) {
        chatStatusLabel_->setText(backend_.getStatus());
    }
}

void NativeMainWindow::clearPendingChatAttachments() {
    if (pendingChatAttachments_.isEmpty()) {
        updatePendingChatAttachments();
        return;
    }
    const QString databasePath = nativeDatabasePath();
    const QString attachmentsJson = QString::fromUtf8(
        QJsonDocument(pendingChatAttachments_).toJson(QJsonDocument::Compact));
    if (!backend_.discardChatAttachments(databasePath, attachmentsJson)) {
        if (chatStatusLabel_ != nullptr) {
            chatStatusLabel_->setText(backend_.getStatus());
        }
        return;
    }
    pendingChatAttachments_ = QJsonArray();
    updatePendingChatAttachments();
}

void NativeMainWindow::updatePendingChatAttachments() {
    if (chatAttachmentLabel_ == nullptr) {
        return;
    }
    QStringList names;
    for (const QJsonValue& value : pendingChatAttachments_) {
        const QString name = value.toObject().value(QStringLiteral("name")).toString();
        if (!name.isEmpty()) {
            names.append(name);
        }
        if (names.size() >= 4) {
            break;
        }
    }
    chatAttachmentLabel_->setText(
        pendingChatAttachments_.isEmpty()
            ? tr("No pending attachments")
            : tr("%1 attachment(s): %2%3")
                  .arg(pendingChatAttachments_.size())
                  .arg(names.join(QStringLiteral(", ")))
                  .arg(pendingChatAttachments_.size() > names.size()
                           ? tr(" and %1 more").arg(pendingChatAttachments_.size() - names.size())
                           : QString()));
    setChatBusy(activeChatRequestId_ != 0);
}

void NativeMainWindow::sendNativeChat() {
    if (activeChatRequestId_ != 0 || groupSequenceActive_ || chatInput_ == nullptr) {
        return;
    }
    QString content = chatInput_->toPlainText().trimmed();
    if (content.isEmpty() && !pendingChatAttachments_.isEmpty()) {
        const bool hasFile = std::any_of(
            pendingChatAttachments_.begin(),
            pendingChatAttachments_.end(),
            [](const QJsonValue& value) {
                return value.toObject().value(QStringLiteral("type")).toString()
                    == QStringLiteral("file");
            });
        content = hasFile ? tr("Please inspect these attachments.")
                          : tr("Please look at this image.");
    }
    if (content.isEmpty()) {
        return;
    }
    const QString attachmentsJson = QString::fromUtf8(
        QJsonDocument(pendingChatAttachments_).toJson(QJsonDocument::Compact));
    if (isGroupChatMode()) {
        sendNativeGroupChat(content, attachmentsJson);
        return;
    }
    const QString character = chatCharacterComboBox_->currentData().toString().trimmed();
    if (character.isEmpty()) {
        return;
    }
    stopNativeTts();
    const QString databasePath = nativeDatabasePath();
    const QString userKey = runtime_
                                .value(QStringLiteral("active_user_key"))
                                .toString(QStringLiteral("__default__"));
    const QString requestedConversationId = draftingNewConversation_
        ? QString()
        : chatConversationComboBox_->currentData().toString();
    if (!backend_.prepareChatTurn(
            databasePath,
            character,
            userKey,
            requestedConversationId,
            content,
            attachmentsJson)) {
        chatStatusLabel_->setText(backend_.getStatus());
        return;
    }
    draftingNewConversation_ = false;
    chatInput_->clear();
    pendingChatAttachments_ = QJsonArray();
    updatePendingChatAttachments();
    const QString conversationId = backend_.getChatActiveConversationId();
    if (!backend_.buildChatRequest(
            databasePath,
            configPath_,
            projectRoot_,
            chatCharacterComboBox_->currentText(),
            currentTimeInstruction(),
            currentLocalDateTime())) {
        const QString status = backend_.getStatus();
        refreshChatState(conversationId);
        chatStatusLabel_->setText(status);
        return;
    }
    const qint64 requestId = backend_.startChatStream(
        configPath_,
        backend_.getChatRequestJson(),
        QDateTime::currentDateTime().toString(QStringLiteral("yyyy-MM-dd'T'HH:mm:ss")));
    if (requestId <= 0) {
        const QString status = backend_.getStatus();
        refreshChatState(conversationId);
        chatStatusLabel_->setText(status);
        return;
    }

    activeChatRequestId_ = requestId;
    activeChatPhase_ = QStringLiteral("private");
    activeChatCharacter_ = character;
    activeChatCharacterDisplay_ = chatCharacterComboBox_->currentText();
    activeChatConversationId_ = conversationId;
    chatStreamText_.clear();
    chatStreamReasoning_.clear();
    setChatBusy(true);
    refreshChatState(conversationId);
    renderChatStreamPreview();
    chatStatusLabel_->setText(tr("Streaming native response…"));
}

void NativeMainWindow::sendNativeGroupChat(
    const QString& content,
    const QString& attachmentsJson) {
    const QJsonArray members = selectedGroupMembers();
    const QString groupKey = selectedGroupKey();
    if (members.size() < 2 || groupKey.isEmpty()) {
        chatStatusLabel_->setText(tr("Select at least two group members"));
        return;
    }
    stopNativeTts();
    const QString databasePath = nativeDatabasePath();
    const QString userKey = runtime_
                                .value(QStringLiteral("active_user_key"))
                                .toString(QStringLiteral("__default__"));
    const QString requestedConversationId = draftingNewConversation_
        ? QString()
        : chatConversationComboBox_->currentData().toString();
    const QString newConversationId = QStringLiteral("group-%1-%2")
                                          .arg(
                                              QDateTime::currentDateTime().toString(
                                                  QStringLiteral("yyyyMMddhhmmsszzz")),
                                              QUuid::createUuid()
                                                  .toString(QUuid::WithoutBraces)
                                                  .left(8));
    if (!backend_.prepareGroupChatTurn(
            databasePath,
            groupKey,
            userKey,
            requestedConversationId,
            newConversationId,
            content,
            attachmentsJson)) {
        chatStatusLabel_->setText(backend_.getStatus());
        return;
    }

    draftingNewConversation_ = false;
    chatInput_->clear();
    pendingChatAttachments_ = QJsonArray();
    updatePendingChatAttachments();
    activeChatConversationId_ = backend_.getChatActiveConversationId();
    activeGroupKey_ = groupKey;
    activeGroupMembers_ = members;
    groupSpeakerQueue_.clear();
    groupSpokenNames_.clear();
    groupSequenceActive_ = true;
    activeChatPhase_ = QStringLiteral("group_plan");
    const QString membersJson = QString::fromUtf8(
        QJsonDocument(members).toJson(QJsonDocument::Compact));
    if (!backend_.buildGroupPlanRequest(databasePath, membersJson, QString())) {
        finishGroupSequence(backend_.getStatus());
        return;
    }
    const qint64 requestId =
        backend_.startGroupPlanStream(configPath_, backend_.getChatRequestJson());
    if (requestId <= 0) {
        const QString plannerStatus = backend_.getStatus();
        if (!backend_.resolveGroupPlan(membersJson, QString(), QString())) {
            finishGroupSequence(plannerStatus);
            return;
        }
        const QJsonArray speakers = parseObject(backend_.getChatTurnJson())
                                        .value(QStringLiteral("speakers"))
                                        .toArray();
        for (const QJsonValue& value : speakers) {
            const QString speaker = value.toString();
            if (!speaker.isEmpty()) {
                groupSpeakerQueue_.append(speaker);
            }
        }
        activeChatPhase_.clear();
        setChatBusy(true);
        chatStatusLabel_->setText(
            tr("%1 · using fallback speaker order").arg(plannerStatus));
        startNextGroupResponse();
        return;
    }

    activeChatRequestId_ = requestId;
    chatStreamText_.clear();
    chatStreamReasoning_.clear();
    setChatBusy(true);
    refreshChatState(activeChatConversationId_);
    renderChatStreamPreview();
    chatStatusLabel_->setText(tr("Scheduling group speakers…"));
}

void NativeMainWindow::startNextGroupResponse() {
    if (!groupSequenceActive_ || activeChatRequestId_ != 0) {
        return;
    }
    if (groupSpeakerQueue_.isEmpty()) {
        finishGroupSequence(tr("Native group response sequence completed"));
        return;
    }
    const QString character = groupSpeakerQueue_.takeFirst();
    QString characterDisplay;
    for (const QJsonValue& value : activeGroupMembers_) {
        const QJsonObject member = value.toObject();
        if (member.value(QStringLiteral("key")).toString() == character) {
            characterDisplay = member.value(QStringLiteral("name")).toString();
            break;
        }
    }
    if (characterDisplay.isEmpty()) {
        finishGroupSequence(tr("The planned group speaker is no longer available"));
        return;
    }
    const QString databasePath = nativeDatabasePath();
    const QString membersJson = QString::fromUtf8(
        QJsonDocument(activeGroupMembers_).toJson(QJsonDocument::Compact));
    QJsonArray spokenNames;
    for (const QString& name : std::as_const(groupSpokenNames_)) {
        spokenNames.append(name);
    }
    const QString spokenNamesJson = QString::fromUtf8(
        QJsonDocument(spokenNames).toJson(QJsonDocument::Compact));
    if (!backend_.buildGroupChatRequest(
            databasePath,
            configPath_,
            projectRoot_,
            character,
            characterDisplay,
            membersJson,
            spokenNamesJson,
            currentTimeInstruction(),
            currentLocalDateTime())) {
        finishGroupSequence(backend_.getStatus());
        return;
    }
    const qint64 requestId = backend_.startGroupChatStream(
        configPath_,
        backend_.getChatRequestJson(),
        QDateTime::currentDateTime().toString(QStringLiteral("yyyy-MM-dd'T'HH:mm:ss")));
    if (requestId <= 0) {
        finishGroupSequence(backend_.getStatus());
        return;
    }
    activeChatRequestId_ = requestId;
    activeChatPhase_ = QStringLiteral("group_speaker");
    activeChatCharacter_ = character;
    activeChatCharacterDisplay_ = characterDisplay;
    chatStreamText_.clear();
    chatStreamReasoning_.clear();
    setChatBusy(true);
    renderChatStreamPreview();
    chatStatusLabel_->setText(
        tr("%1 is replying · %2 speaker(s) remain")
            .arg(characterDisplay)
            .arg(groupSpeakerQueue_.size()));
}

void NativeMainWindow::finishGroupSequence(const QString& status) {
    const QString conversationId = activeChatConversationId_;
    backend_.finishGroupChatTurn();
    activeChatRequestId_ = 0;
    activeChatPhase_.clear();
    activeChatCharacter_.clear();
    activeChatCharacterDisplay_.clear();
    chatStreamText_.clear();
    chatStreamReasoning_.clear();
    groupSpeakerQueue_.clear();
    groupSpokenNames_.clear();
    activeGroupMembers_ = QJsonArray();
    groupSequenceActive_ = false;
    setChatBusy(false);
    refreshChatState(conversationId);
    activeChatConversationId_.clear();
    activeGroupKey_.clear();
    chatStatusLabel_->setText(status);
    chatInput_->setFocus();
}

void NativeMainWindow::cancelNativeChat() {
    if (activeChatRequestId_ == 0) {
        return;
    }
    if (backend_.cancelChatStream(activeChatRequestId_)) {
        chatStatusLabel_->setText(tr("Cancelling native response…"));
        chatCancelButton_->setEnabled(false);
    } else {
        chatStatusLabel_->setText(backend_.getStatus());
    }
}

void NativeMainWindow::handleChatStreamEvent(const QString& payloadJson) {
    const QJsonObject payload = parseObject(payloadJson);
    const qint64 requestId = payload.value(QStringLiteral("request_id")).toInteger();
    if (requestId <= 0 || requestId != activeChatRequestId_) {
        return;
    }
    const QString state = payload.value(QStringLiteral("state")).toString();
    if (state == QStringLiteral("event")) {
        const QJsonObject event = payload.value(QStringLiteral("event")).toObject();
        const QString kind = event.value(QStringLiteral("kind")).toString();
        if (kind == QStringLiteral("text_delta")) {
            chatStreamText_ += event.value(QStringLiteral("text")).toString();
            renderChatStreamPreview();
        } else if (kind == QStringLiteral("reasoning_delta")) {
            chatStreamReasoning_ += event.value(QStringLiteral("text")).toString();
            renderChatStreamPreview();
        }
        return;
    }

    if (activeChatPhase_ == QStringLiteral("group_plan")) {
        const QString plannerResponse = chatStreamText_;
        activeChatRequestId_ = 0;
        chatStreamText_.clear();
        chatStreamReasoning_.clear();
        activeChatPhase_.clear();
        if (state == QStringLiteral("cancelled")) {
            finishGroupSequence(
                tr("Group scheduling cancelled; the user message remains in history"));
            return;
        }
        const QString membersJson = QString::fromUtf8(
            QJsonDocument(activeGroupMembers_).toJson(QJsonDocument::Compact));
        const QString response = state == QStringLiteral("finished")
            ? plannerResponse
            : QString();
        if (!backend_.resolveGroupPlan(membersJson, QString(), response)) {
            finishGroupSequence(backend_.getStatus());
            return;
        }
        groupSpeakerQueue_.clear();
        const QJsonObject plan = parseObject(backend_.getChatTurnJson());
        for (const QJsonValue& value : plan.value(QStringLiteral("speakers")).toArray()) {
            const QString speaker = value.toString();
            if (!speaker.isEmpty()) {
                groupSpeakerQueue_.append(speaker);
            }
        }
        if (groupSpeakerQueue_.isEmpty()) {
            finishGroupSequence(tr("The group planner returned no usable speakers"));
            return;
        }
        chatStatusLabel_->setText(
            plan.value(QStringLiteral("used_fallback")).toBool()
                ? tr("Planner unavailable; using fallback speaker order")
                : tr("Group speaker order ready"));
        startNextGroupResponse();
        return;
    }

    if (activeChatPhase_ == QStringLiteral("group_speaker")) {
        const QString character = activeChatCharacter_;
        const QString characterDisplay = activeChatCharacterDisplay_;
        const QString conversationId = activeChatConversationId_;
        dispatchChatToolEffects(payload, character);
        QString terminalStatus;
        bool saved = false;
        if (state == QStringLiteral("finished")) {
            const QString databasePath = nativeDatabasePath();
            saved = backend_.saveGroupChatAssistant(
                databasePath,
                configPath_,
                requestId,
                chatStreamText_,
                chatStreamReasoning_,
                compactJson(payload));
            if (saved) {
                const QJsonObject turn = parseObject(backend_.getChatTurnJson());
                const QJsonArray turnActions =
                    turn.value(QStringLiteral("actions")).toArray();
                int actionsSent = 0;
                for (const QJsonValue& value : turnActions) {
                    const QString action = value.toString();
                    if (!action.isEmpty()
                        && supervisor_.broadcastControlLine(
                            QStringLiteral("ACTION\t%1\t%2").arg(character, action))) {
                        ++actionsSent;
                    }
                }
                terminalStatus = actionsSent > 0
                    ? tr("%1 · %2 Live2D action(s) sent")
                          .arg(backend_.getStatus())
                          .arg(actionsSent)
                    : backend_.getStatus();
                groupSpokenNames_.append(characterDisplay);
                const double ttsRate =
                    dispatchNativeEmotionBehavior(chatStreamText_, character, turnActions);
                enqueueNativeTts(chatStreamText_, character, false, ttsRate);
            } else {
                terminalStatus = backend_.getStatus();
            }
        } else if (state == QStringLiteral("cancelled")) {
            terminalStatus = tr("Group response cancelled; completed speakers remain saved");
        } else {
            terminalStatus = payload.value(QStringLiteral("message")).toString().trimmed();
            if (terminalStatus.isEmpty()) {
                terminalStatus = tr("Native group speaker request failed");
            }
        }

        activeChatRequestId_ = 0;
        activeChatPhase_.clear();
        activeChatCharacter_.clear();
        activeChatCharacterDisplay_.clear();
        chatStreamText_.clear();
        chatStreamReasoning_.clear();
        if (!saved) {
            finishGroupSequence(terminalStatus);
            return;
        }
        refreshChatState(conversationId);
        chatStatusLabel_->setText(terminalStatus);
        startNextGroupResponse();
        return;
    }

    const QString character = activeChatCharacter_;
    const QString conversationId = activeChatConversationId_;
    dispatchChatToolEffects(payload, character);
    QString terminalStatus;
    if (state == QStringLiteral("finished")) {
        const QString databasePath = nativeDatabasePath();
        if (backend_.saveChatAssistant(
                databasePath,
                configPath_,
                activeChatCharacterDisplay_,
                requestId,
                chatStreamText_,
                chatStreamReasoning_,
                compactJson(payload))) {
            const QJsonObject turn = parseObject(backend_.getChatTurnJson());
            const QJsonArray turnActions =
                turn.value(QStringLiteral("actions")).toArray();
            int actionsSent = 0;
            for (const QJsonValue& value : turnActions) {
                const QString action = value.toString();
                if (!action.isEmpty()
                    && supervisor_.broadcastControlLine(
                        QStringLiteral("ACTION\t%1\t%2").arg(character, action))) {
                    ++actionsSent;
                }
            }
            const QString savedStatus = backend_.getStatus();
            terminalStatus = actionsSent > 0
                ? tr("%1 · %2 Live2D action(s) sent").arg(savedStatus).arg(actionsSent)
                : savedStatus;
            const double ttsRate =
                dispatchNativeEmotionBehavior(chatStreamText_, character, turnActions);
            enqueueNativeTts(chatStreamText_, character, false, ttsRate);
        } else {
            terminalStatus = backend_.getStatus();
        }
    } else if (state == QStringLiteral("cancelled")) {
        terminalStatus = tr("Native response cancelled; the user message remains in history");
    } else {
        terminalStatus = payload.value(QStringLiteral("message")).toString();
        if (terminalStatus.isEmpty()) {
            terminalStatus = tr("Native LLM request failed");
        }
    }

    activeChatRequestId_ = 0;
    activeChatPhase_.clear();
    activeChatCharacter_.clear();
    activeChatCharacterDisplay_.clear();
    activeChatConversationId_.clear();
    chatStreamText_.clear();
    chatStreamReasoning_.clear();
    setChatBusy(false);
    refreshChatState(conversationId);
    chatStatusLabel_->setText(terminalStatus);
    chatInput_->setFocus();
}

int NativeMainWindow::dispatchChatToolEffects(
    const QJsonObject& payload,
    const QString& character) {
    const QString target = character.trimmed();
    if (target.isEmpty()) {
        return 0;
    }
    int dispatched = 0;
    for (const QJsonValue& value : payload.value(QStringLiteral("tool_calls")).toArray()) {
        if (dispatched >= 16) {
            break;
        }
        if (!value.isObject()) {
            continue;
        }
        const QJsonObject result = value.toObject();
        if (!result.value(QStringLiteral("succeeded")).toBool()
            || result.value(QStringLiteral("name")).toString() != QStringLiteral("poke_user")) {
            continue;
        }
        const QJsonObject effect = result.value(QStringLiteral("effect")).toObject();
        if (effect.value(QStringLiteral("kind")).toString() != QStringLiteral("poke_user")) {
            continue;
        }
        const QString message = effect.value(QStringLiteral("message"))
                                    .toString()
                                    .trimmed()
                                    .left(280);
        const QJsonObject poke {
            {QStringLiteral("character"), target},
            {QStringLiteral("message"), message},
            {QStringLiteral("source"), QStringLiteral("llm_tool")},
            {QStringLiteral("direction"), QStringLiteral("to_user")},
        };
        if (supervisor_.broadcastControlLine(
                QStringLiteral("POKE_USER\t") + compactJson(poke))) {
            ++dispatched;
        }
    }
    return dispatched;
}

double NativeMainWindow::dispatchNativeEmotionBehavior(
    const QString& text,
    const QString& character,
    const QJsonArray& actions) {
    const QString actionsJson =
        QString::fromUtf8(QJsonDocument(actions).toJson(QJsonDocument::Compact));
    QJsonObject behavior =
        parseObject(backend_.getEmotionBehaviorJson(text, actionsJson));
    const double ttsRate = std::clamp(
        behavior.value(QStringLiteral("tts_rate")).toDouble(1.0),
        0.75,
        1.25);
    const QString target = character.trimmed();
    if (!behavior.isEmpty() && !target.isEmpty()
        && runtime_.value(QStringLiteral("emotion_behavior_enabled")).toBool(true)) {
        behavior.insert(QStringLiteral("character"), target);
        supervisor_.broadcastControlLine(
            QStringLiteral("EMOTION\t") + compactJson(behavior));
    }
    return ttsRate;
}

void NativeMainWindow::pollNativeReminders() {
    const QString now = currentLocalDateTime();
    if (!backend_.tickReminders(configPath_, now)) {
        return;
    }
    loadNativeReminderState();
    for (const QJsonValue& value : parseArray(backend_.getReminderEventsJson())) {
        if (!value.isObject()) {
            continue;
        }
        QJsonObject event = value.toObject();
        const QString character = event.value(QStringLiteral("character")).toString().trimmed();
        QString displayName = displayNameForCharacter(character).trimmed();
        if (displayName.isEmpty()) {
            displayName = QStringLiteral("BandoriPet");
        }
        const QString text = reminderFallbackText(event, displayName);
        QString ttsCharacter = character;
        if (ttsCharacter.isEmpty()) {
            ttsCharacter =
                ttsSettings_.value(QStringLiteral("reference_character")).toString().trimmed();
        }
        if (ttsCharacter.isEmpty()) {
            const std::optional<ModelCatalogItem> model = configuredModel();
            if (model.has_value()) {
                ttsCharacter = model->character;
            }
        }
        enqueueNativeTts(text, ttsCharacter);
        const bool systemMode =
            event.value(QStringLiteral("display_mode")).toString() == QStringLiteral("system");
        if (systemMode && trayIcon_ != nullptr) {
            trayIcon_->showMessage(
                displayName,
                text,
                QSystemTrayIcon::Information,
                15'000);
            continue;
        }
        event.insert(QStringLiteral("source"), QStringLiteral("reminder"));
        event.insert(QStringLiteral("state"), QStringLiteral("done"));
        event.insert(QStringLiteral("mode"), QStringLiteral("replace_raw"));
        event.insert(QStringLiteral("title"), displayName);
        event.insert(QStringLiteral("text"), text);
        event.insert(QStringLiteral("action"), QStringLiteral("surprised"));
        event.insert(QStringLiteral("ttl_ms"), 18'000);
        event.insert(QStringLiteral("anchor_to_pet"), true);
        supervisor_.broadcastControlLine(
            QStringLiteral("REMINDER_EVENT\t") + compactJson(event));
    }
}

void NativeMainWindow::pollNativeSpecialEvents() {
    const QString today = QDate::currentDate().toString(Qt::ISODate);
    if (today == lastSpecialEventDate_) {
        scheduleNativeSpecialEventPoll();
        return;
    }
    const QString eventsDir = QDir(projectRoot_).filePath(QStringLiteral("events"));
    if (!backend_.loadSpecialEvents(eventsDir, currentLocalDateTime())) {
        serviceStatusLabel_->setText(backend_.getStatus());
        scheduleNativeSpecialEventPoll(60'000);
        return;
    }
    lastSpecialEventDate_ = today;
    for (const QJsonValue& value : parseArray(backend_.getSpecialEventsJson())) {
        if (!value.isObject()) {
            continue;
        }
        const QJsonObject event = value.toObject();
        if (event.value(QStringLiteral("event_type")).toString()
                == QStringLiteral("birthday")
            && !runtime_
                    .value(QStringLiteral("birthday_tray_notifications_enabled"))
                    .toBool(true)) {
            continue;
        }
        if (trayIcon_ == nullptr) {
            continue;
        }
        const QString name = event.value(QStringLiteral("name_zh")).toString().trimmed();
        const QString text =
            event.value(QStringLiteral("notification_text")).toString().trimmed();
        if (!name.isEmpty() && !text.isEmpty()) {
            trayIcon_->showMessage(
                QStringLiteral("🎉 %1").arg(name),
                text,
                QSystemTrayIcon::Information,
                15'000);
        }
    }
    scheduleNativeSpecialEventPoll();
}

void NativeMainWindow::scheduleNativeSpecialEventPoll(int retryMilliseconds) {
    specialEventTimer_.stop();
    if (exitRequested_) {
        return;
    }
    if (retryMilliseconds > 0) {
        specialEventTimer_.start(std::clamp(retryMilliseconds, 1'000, 60 * 60 * 1'000));
        return;
    }
    const QDateTime now = QDateTime::currentDateTime();
    const QDateTime nextMidnight(
        now.date().addDays(1), QTime(0, 0), now.timeZone());
    const qint64 milliseconds = std::max<qint64>(1'000, now.msecsTo(nextMidnight));
    specialEventTimer_.start(static_cast<int>(std::min<qint64>(
        milliseconds, std::numeric_limits<int>::max())));
}

void NativeMainWindow::handleChatMemoryEvent(const QString& payloadJson) {
    if (activeChatRequestId_ != 0 || chatStatusLabel_ == nullptr) {
        return;
    }
    const QJsonObject payload = parseObject(payloadJson);
    const QString state = payload.value(QStringLiteral("state")).toString();
    if (state == QStringLiteral("finished")) {
        const qint64 added = payload.value(QStringLiteral("memories_added")).toInteger();
        const qint64 removed = payload.value(QStringLiteral("memories_removed")).toInteger();
        chatStatusLabel_->setText(
            tr("Relationship updated · %1 memories saved · %2 outdated memories removed")
                .arg(added)
                .arg(removed));
    } else if (state == QStringLiteral("fallback")) {
        chatStatusLabel_->setText(
            tr("Memory model unavailable; heuristic relationship update saved"));
    } else if (state == QStringLiteral("error")) {
        QString message = payload.value(QStringLiteral("message")).toString().trimmed();
        if (message.isEmpty()) {
            message = tr("Native memory analysis failed");
        }
        chatStatusLabel_->setText(message);
    }
    if (state == QStringLiteral("finished") || state == QStringLiteral("fallback")) {
        refreshNativeMemoryState();
    }
}

void NativeMainWindow::setChatBusy(bool busy) {
    if (chatInput_ == nullptr) {
        return;
    }
    const bool chatBusy = busy || groupSequenceActive_;
    const bool asrBusy = asrRecording_ || activeAsrRequestId_ != 0;
    busy = chatBusy || asrBusy;
    const bool hasTarget = isGroupChatMode()
        ? !selectedGroupKey().isEmpty()
        : !chatCharacterComboBox_->currentData().toString().isEmpty();
    chatModeComboBox_->setEnabled(!busy);
    chatPrivateSelector_->setEnabled(!busy);
    chatGroupSelector_->setEnabled(!busy);
    chatCharacterComboBox_->setEnabled(!busy);
    chatGroupComboBox_->setEnabled(!busy);
    chatGroupMembersList_->setEnabled(!busy);
    chatConversationComboBox_->setEnabled(!busy);
    chatRefreshButton_->setEnabled(!busy);
    chatNewConversationButton_->setEnabled(
        !busy && hasTarget);
    chatDeleteConversationButton_->setEnabled(
        !busy && !draftingNewConversation_
        && !chatConversationComboBox_->currentData().toString().isEmpty());
    chatLoadOlderButton_->setEnabled(
        !busy && backend_.getChatHasOlderMessages() && chatMessageLimit_ < kChatMessageLimit);
    chatInput_->setEnabled(!busy);
    chatAttachButton_->setEnabled(!busy && pendingChatAttachments_.size() < 32);
    chatAsrButton_->setEnabled(
        asrRecording_
        || (!chatBusy && activeAsrRequestId_ == 0
            && asrSettings_.value(QStringLiteral("enabled")).toBool()));
    chatClearAttachmentsButton_->setEnabled(!busy && !pendingChatAttachments_.isEmpty());
    chatSendButton_->setEnabled(
        !busy
        && (!chatInput_->toPlainText().trimmed().isEmpty()
            || !pendingChatAttachments_.isEmpty())
        && hasTarget);
    chatCancelButton_->setEnabled(chatBusy);
}

void NativeMainWindow::renderChatStreamPreview() {
    if (chatTranscript_ == nullptr || activeChatRequestId_ == 0) {
        return;
    }
    QString transcript = chatTranscriptBase_.trimmed();
    const QString reasoning = stripActionTags(chatStreamReasoning_);
    const QString response = stripActionTags(chatStreamText_);
    if (!reasoning.isEmpty()) {
        if (!transcript.isEmpty()) {
            transcript += QStringLiteral("\n\n");
        }
        transcript += QStringLiteral("[reasoning · streaming]\n") + reasoning;
    }
    if (!transcript.isEmpty()) {
        transcript += QStringLiteral("\n\n");
    }
    if (activeChatPhase_ == QStringLiteral("group_plan")) {
        transcript += QStringLiteral("[planner · scheduling]\n");
    } else if (activeChatPhase_ == QStringLiteral("group_speaker")) {
        transcript += QStringLiteral("[%1 · streaming]\n").arg(activeChatCharacterDisplay_);
    } else {
        transcript += QStringLiteral("[assistant · streaming]\n");
    }
    transcript += response.isEmpty() ? QStringLiteral("…") : response;
    chatTranscript_->setPlainText(transcript);
    QScrollBar* scrollBar = chatTranscript_->verticalScrollBar();
    scrollBar->setValue(scrollBar->maximum());
}

void NativeMainWindow::openNativeChat(const QString& character) {
    showControlCenter();
    populateChatCharacters();
    if (activeChatRequestId_ != 0
        && !character.trimmed().isEmpty()
        && character.trimmed() != activeChatCharacter_) {
        switchTo(chatPage_);
        chatStatusLabel_->setText(
            tr("Finish or cancel the active native response before switching characters"));
        return;
    }
    if (!character.trimmed().isEmpty()) {
        const QSignalBlocker modeBlocker(chatModeComboBox_);
        const int privateMode = chatModeComboBox_->findData(QStringLiteral("private"));
        if (privateMode >= 0) {
            chatModeComboBox_->setCurrentIndex(privateMode);
            chatPrivateSelector_->setVisible(true);
            syncChatPresentationControls();
        }
        const QSignalBlocker blocker(chatCharacterComboBox_);
        const int index = chatCharacterComboBox_->findData(character.trimmed());
        if (index >= 0) {
            chatCharacterComboBox_->setCurrentIndex(index);
        }
    }
    switchTo(chatPage_);
    refreshChatState({}, true);
}

std::optional<ModelCatalogItem> NativeMainWindow::selectedModel() const {
    const QListWidgetItem* item = modelList_->currentItem();
    if (item == nullptr) {
        return std::nullopt;
    }
    const QString path = item->data(kPathRole).toString();
    const auto found = std::find_if(
        catalog_.cbegin(),
        catalog_.cend(),
        [&path](const ModelCatalogItem& model) { return model.path == path; });
    if (found == catalog_.cend()) {
        return std::nullopt;
    }
    return *found;
}

std::optional<ModelCatalogItem> NativeMainWindow::configuredModel() const {
    const QList<ModelCatalogItem> models = configuredModels();
    return models.isEmpty() ? std::nullopt
                            : std::optional<ModelCatalogItem>(models.first());
}

QList<ModelCatalogItem> NativeMainWindow::configuredModels() const {
    QList<ModelCatalogItem> models;
    const QJsonArray configured = runtime_.value(QStringLiteral("configured_pets")).toArray();
    for (const QJsonValue& value : configured) {
        const QJsonObject pet = value.toObject();
        const QString path = pet.value(QStringLiteral("path")).toString();
        const auto found = std::find_if(
            catalog_.cbegin(),
            catalog_.cend(),
            [&path](const ModelCatalogItem& model) { return model.path == path; });
        const bool alreadyAdded = std::any_of(
            models.cbegin(), models.cend(), [&path](const ModelCatalogItem& model) {
                return model.path == path;
            });
        if (found != catalog_.cend() && !alreadyAdded) {
            models.append(*found);
        }
    }
    if (!models.isEmpty()) {
        return models;
    }
    const QString character = runtime_.value(QStringLiteral("selected_character")).toString();
    const QString costume = runtime_.value(QStringLiteral("selected_costume")).toString();
    const auto found = std::find_if(
        catalog_.cbegin(),
        catalog_.cend(),
        [&character, &costume](const ModelCatalogItem& model) {
            return model.character == character
                && (costume.isEmpty() ? model.isDefault : model.costume == costume);
        });
    if (found != catalog_.cend()) {
        models.append(*found);
        return models;
    }
    const auto fallback = std::find_if(
        catalog_.cbegin(),
        catalog_.cend(),
        [](const ModelCatalogItem& model) { return model.isDefault; });
    if (fallback != catalog_.cend()) {
        models.append(*fallback);
        return models;
    }
    if (!catalog_.isEmpty()) {
        models.append(catalog_.first());
    }
    return models;
}

QJsonObject NativeMainWindow::configuredPetFor(const ModelCatalogItem& model) const {
    const QJsonArray configured = runtime_.value(QStringLiteral("configured_pets")).toArray();
    for (const QJsonValue& value : configured) {
        const QJsonObject pet = value.toObject();
        if (pet.value(QStringLiteral("path")).toString() == model.path) {
            return pet;
        }
    }
    for (const QJsonValue& value : configured) {
        const QJsonObject pet = value.toObject();
        if (pet.value(QStringLiteral("character")).toString() == model.character
            && pet.value(QStringLiteral("costume")).toString() == model.costume) {
            return pet;
        }
    }
    return {};
}

PetLaunchSpec NativeMainWindow::launchSpecFor(const ModelCatalogItem& model) const {
    const QJsonObject pet = configuredPetFor(model);
    PetLaunchSpec spec;
    spec.projectRoot = projectRoot_;
    spec.userModelsRoot = userModelsRoot_;
    spec.configPath = configPath_;
    spec.modelPath = model.path;
    spec.character = model.character;
    spec.language = runtime_.value(QStringLiteral("language")).toString();
    spec.petMode = pet.contains(QStringLiteral("pet_mode"))
        ? pet.value(QStringLiteral("pet_mode")).toString()
        : runtime_.value(QStringLiteral("pet_mode")).toString(QStringLiteral("live2d"));
    if (spec.petMode != QStringLiteral("pixel")) {
        spec.petMode = QStringLiteral("live2d");
    }
    spec.format = model.format;
    spec.width = pet.contains(QStringLiteral("window_width"))
        ? pet.value(QStringLiteral("window_width")).toInt(400)
        : runtime_.value(QStringLiteral("window_width")).toInt(400);
    spec.height = pet.contains(QStringLiteral("window_height"))
        ? pet.value(QStringLiteral("window_height")).toInt(500)
        : runtime_.value(QStringLiteral("window_height")).toInt(500);
    spec.x = spec.petMode == QStringLiteral("pixel")
        ? (pet.contains(QStringLiteral("pixel_window_x"))
               ? pet.value(QStringLiteral("pixel_window_x")).toInt(-1)
               : runtime_.value(QStringLiteral("pixel_window_x")).toInt(-1))
        : (pet.contains(QStringLiteral("window_x"))
               ? pet.value(QStringLiteral("window_x")).toInt(-1)
               : runtime_.value(QStringLiteral("window_x")).toInt(-1));
    spec.y = spec.petMode == QStringLiteral("pixel")
        ? (pet.contains(QStringLiteral("pixel_window_y"))
               ? pet.value(QStringLiteral("pixel_window_y")).toInt(-1)
               : runtime_.value(QStringLiteral("pixel_window_y")).toInt(-1))
        : (pet.contains(QStringLiteral("window_y"))
               ? pet.value(QStringLiteral("window_y")).toInt(-1)
               : runtime_.value(QStringLiteral("window_y")).toInt(-1));
    spec.fps = runtime_.value(QStringLiteral("fps")).toInt(120);
    spec.opacity = runtime_.value(QStringLiteral("opacity")).toDouble(1.0);
    spec.gameTopmost = runtime_.value(QStringLiteral("game_topmost")).toBool(false);
    spec.obsWindowCaptureCompatible =
        runtime_.value(QStringLiteral("obs_window_capture_compatible")).toBool(false);
    spec.hideLive2dModel =
        runtime_.value(QStringLiteral("hide_live2d_model")).toBool(false);
    spec.vsync = runtime_.value(QStringLiteral("vsync")).toBool(true);
    spec.gpuAcceleration =
        runtime_.value(QStringLiteral("gpu_acceleration")).toBool(true);
    spec.live2dQuality =
        runtime_.value(QStringLiteral("live2d_quality")).toString(QStringLiteral("balanced"));
    spec.live2dScale = runtime_.value(QStringLiteral("live2d_scale")).toInt(100);
    spec.lipSyncMaxOpen =
        runtime_.value(QStringLiteral("lip_sync_max_open")).toDouble(0.55);
    spec.hitAlphaThreshold =
        runtime_.value(QStringLiteral("hit_alpha_threshold")).toInt(8);
    spec.clickMotionActions =
        compactJson(pet.value(QStringLiteral("click_motion_actions")).toObject());
    spec.pokeMotion = runtime_.value(QStringLiteral("poke_motion")).toString();
    spec.pokeExpression = runtime_.value(QStringLiteral("poke_expression")).toString();
    spec.defaultMotion = pet.value(QStringLiteral("default_motion")).toString();
    spec.defaultExpression = pet.value(QStringLiteral("default_expression")).toString();
    spec.idleActionsEnabled =
        runtime_.value(QStringLiteral("idle_actions_enabled")).toBool(true);
    spec.randomActionsEnabled =
        runtime_.value(QStringLiteral("random_actions_enabled")).toBool(true);
    spec.dragLocked = pet.contains(QStringLiteral("drag_locked"))
        ? pet.value(QStringLiteral("drag_locked")).toBool()
        : runtime_.value(QStringLiteral("drag_locked")).toBool();
    spec.moveAllRolesTogether =
        runtime_.value(QStringLiteral("move_all_roles_together")).toBool();
    spec.headTrackingEnabled =
        runtime_.value(QStringLiteral("head_tracking_enabled")).toBool(true);
    spec.mutualGazeEnabled =
        runtime_.value(QStringLiteral("mutual_gaze_enabled")).toBool(false);
    spec.emotionBehaviorEnabled =
        runtime_.value(QStringLiteral("emotion_behavior_enabled")).toBool(true);
    spec.compactAiWindowEnabled =
        runtime_.value(QStringLiteral("compact_ai_window_enabled")).toBool(false);
    spec.compactAiWindowOpacity =
        runtime_.value(QStringLiteral("compact_ai_window_opacity")).toInt(44);
    spec.compactAiWindowFontSize =
        runtime_.value(QStringLiteral("compact_ai_window_font_size")).toInt(12);
    spec.compactAiWindowBackgroundColor = runtime_
                                              .value(QStringLiteral(
                                                  "compact_ai_window_background_color"))
                                              .toString(QStringLiteral("#fb7299"));
    spec.compactAiWindowTextColor = runtime_
                                        .value(QStringLiteral("compact_ai_window_text_color"))
                                        .toString(QStringLiteral("#24242a"));
    spec.aiEventOverlayEnabled =
        runtime_.value(QStringLiteral("ai_event_overlay_enabled")).toBool(false);
    spec.chatIntegrationOverlayEnabled =
        runtime_
            .value(QStringLiteral("chat_integration_overlay_enabled"))
            .toBool(true);
    return spec;
}

void NativeMainWindow::startPet(PetLaunchSpec spec) {
    startPets({std::move(spec)});
}

void NativeMainWindow::startPets(QList<PetLaunchSpec> specs) {
    specs.erase(
        std::remove_if(specs.begin(), specs.end(), [](const PetLaunchSpec& spec) {
            return spec.modelPath.isEmpty();
        }),
        specs.end());
    if (specs.isEmpty()) {
        rendererStatusLabel_->setText(tr("Cannot start a pet without a model manifest"));
        return;
    }
    activeSpecs_ = std::move(specs);
    rendererStatusLabel_->setText(
        activeSpecs_.size() == 1
            ? tr("Starting %1").arg(QFileInfo(activeSpecs_.first().modelPath).fileName())
            : tr("Starting %1 isolated pets").arg(activeSpecs_.size()));
    restartButton_->setEnabled(true);
    supervisor_.startAll(activeSpecs_);
}

bool NativeMainWindow::startConfiguredPet() {
    return startConfiguredPets();
}

bool NativeMainWindow::startConfiguredPets() {
    const QList<ModelCatalogItem> models = configuredModels();
    if (models.isEmpty()) {
        rendererStatusLabel_->setText(tr("No configured pet models are available"));
        return false;
    }
    QList<PetLaunchSpec> specs;
    specs.reserve(models.size());
    for (const ModelCatalogItem& model : models) {
        specs.append(launchSpecFor(model));
    }
    startPets(std::move(specs));
    return true;
}

void NativeMainWindow::startSelectedPet() {
    const std::optional<ModelCatalogItem> model = selectedModel();
    if (model.has_value()) {
        startPet(launchSpecFor(*model));
    }
}

}  // namespace bandori
