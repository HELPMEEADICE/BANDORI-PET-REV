#include "native_main_window.h"

#include <QAbstractItemView>
#include <QAction>
#include <QApplication>
#include <QCloseEvent>
#include <QDateTime>
#include <QDebug>
#include <QDir>
#include <QFileDialog>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QKeySequence>
#include <QListWidgetItem>
#include <QMenu>
#include <QMessageBox>
#include <QRegularExpression>
#include <QScrollArea>
#include <QScrollBar>
#include <QShortcut>
#include <QSignalBlocker>
#include <QSystemTrayIcon>
#include <QTextBrowser>
#include <QVariant>
#include <QVBoxLayout>
#include <QUuid>

#include <algorithm>
#include <utility>

namespace bandori {

namespace {

constexpr int kPathRole = Qt::UserRole;
constexpr int kCharacterRole = Qt::UserRole + 1;
constexpr int kCostumeRole = Qt::UserRole + 2;
constexpr int kFormatRole = Qt::UserRole + 3;
constexpr int kReminderKindRole = Qt::UserRole + 10;
constexpr int kReminderIdRole = Qt::UserRole + 11;
constexpr int kReminderEnabledRole = Qt::UserRole + 12;
constexpr int kChatMessagePageSize = 200;
constexpr int kChatMessageLimit = 1000;

QString currentLocalDateTime() {
    return QDateTime::currentDateTime().toString(QStringLiteral("yyyy-MM-dd'T'HH:mm:ss"));
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
    return QStringLiteral("%1 MB").arg(QString::number(size / (1024.0 * 1024.0), 'f', 1));
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

}  // namespace

NativeMainWindow::NativeMainWindow(
    QString projectRoot,
    QString userModelsRoot,
    QString configPath,
    QWidget* parent)
    : qfw::FluentWindow(parent),
      projectRoot_(QDir(std::move(projectRoot)).absolutePath()),
      userModelsRoot_(QDir(std::move(userModelsRoot)).absolutePath()),
      configPath_(QDir::cleanPath(std::move(configPath))),
      supervisor_(this) {
    setupUi();
    connect(
        &backend_,
        &Backend::chatStreamEvent,
        this,
        [this](const QString& payloadJson) { handleChatStreamEvent(payloadJson); });
    connect(
        &backend_,
        &Backend::chatMemoryEvent,
        this,
        [this](const QString& payloadJson) { handleChatMemoryEvent(payloadJson); });
    reloadBackendState();
    setupTray();
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

void NativeMainWindow::quitFromTray() {
    if (exitRequested_) {
        return;
    }
    exitRequested_ = true;
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
    qfw::FluentWindow::closeEvent(event);
    if (trayIcon_ == nullptr) {
        QCoreApplication::quit();
    }
}

void NativeMainWindow::setupUi() {
    setWindowTitle(QStringLiteral("BandoriPet Rust + Qt"));
    resize(920, 640);
    setMinimumSize(760, 520);

    QWidget* dashboard = createDashboardPage();
    QWidget* models = createModelsPage();
    chatPage_ = createChatPage();
    QWidget* llmSettings = createLlmSettingsPage();
    QWidget* settings = createSettingsPage();
    dashboard->setObjectName(QStringLiteral("dashboardPage"));
    models->setObjectName(QStringLiteral("modelsPage"));
    chatPage_->setObjectName(QStringLiteral("chatPage"));
    llmSettings->setObjectName(QStringLiteral("llmSettingsPage"));
    settings->setObjectName(QStringLiteral("settingsPage"));
    addSubInterface(dashboard, qfw::FluentIconEnum::Home, tr("Overview"));
    addSubInterface(models, qfw::FluentIconEnum::People, tr("Models"));
    addSubInterface(chatPage_, qfw::FluentIconEnum::Chat, tr("Chat history"));
    addSubInterface(llmSettings, qfw::FluentIconEnum::Robot, tr("LLM settings"));
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

    auto* title = new qfw::TitleLabel(tr("Available Live2D models"), page);
    modelCountLabel_ = new qfw::CaptionLabel(page);
    modelList_ = new qfw::ListWidget(page);
    modelList_->setSelectionMode(QAbstractItemView::SingleSelection);
    modelList_->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    modelDetailsLabel_ = new qfw::BodyLabel(tr("Select a costume to inspect it"), page);
    modelDetailsLabel_->setWordWrap(true);
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
    layout->addLayout(buttons);

    launchSelectedButton_->setEnabled(false);
    connect(
        modelList_,
        &QListWidget::currentItemChanged,
        this,
        [this](QListWidgetItem*, QListWidgetItem*) { updateModelDetails(); });
    connect(launchSelectedButton_, &QPushButton::clicked, this, [this]() { startSelectedPet(); });
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
        tr("Rust owns private/group prompts, safe attachments, cancellable speaker streams and transactional data.db history. Local tool parity remains staged."),
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
    attachmentControls->addWidget(chatAttachButton_);
    attachmentControls->addWidget(chatClearAttachmentsButton_);
    attachmentControls->addWidget(chatAttachmentLabel_, 1);
    auto* composer = new QHBoxLayout();
    composer->setSpacing(10);
    composer->addWidget(chatInput_, 1);
    composer->addLayout(composerButtons);

    layout->addWidget(title);
    layout->addWidget(explanation);
    layout->addLayout(controls);
    layout->addWidget(chatGroupSelector_);
    layout->addWidget(chatStatusLabel_);
    layout->addWidget(chatTranscript_, 1);
    layout->addLayout(attachmentControls);
    layout->addLayout(composer);

    connect(chatRefreshButton_, &QPushButton::clicked, this, [this]() {
        refreshChatState(chatConversationComboBox_->currentData().toString());
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
            chatGroupSelector_->setVisible(group);
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
    connect(
        chatClearAttachmentsButton_,
        &QPushButton::clicked,
        this,
        [this]() { clearPendingChatAttachments(); });
    auto* sendShortcut = new QShortcut(QKeySequence(QStringLiteral("Ctrl+Return")), chatInput_);
    connect(sendShortcut, &QShortcut::activated, this, [this]() { sendNativeChat(); });
    updatePendingChatAttachments();
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

    auto* primary = new qfw::GroupHeaderCardWidget(tr("Primary model"), content);
    llmApiUrlEdit_ = new qfw::LineEdit(primary);
    llmApiUrlEdit_->setPlaceholderText(
        QStringLiteral("https://api.example.com/v1/chat/completions"));
    llmApiUrlEdit_->setMinimumWidth(380);
    llmModelIdEdit_ = new qfw::LineEdit(primary);
    llmModelIdEdit_->setPlaceholderText(tr("Model ID"));
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
    layout->addWidget(primary);
    layout->addWidget(auxiliary);
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
    connect(llmSaveButton_, &QPushButton::clicked, this, [this]() {
        saveNativeLlmSettings();
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
    vsyncSwitch_ = new qfw::SwitchButton(live2d);
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
        qfw::FluentIcon(qfw::FluentIconEnum::SpeedHigh),
        tr("Vertical synchronization"),
        tr("Recreate renderer surfaces with the configured swap interval"),
        vsyncSwitch_);
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
        qfw::FluentIcon(qfw::FluentIconEnum::Brush),
        tr("Application theme"),
        tr("Apply light, dark or system appearance to Qt-Fluent-Widgets"),
        themeComboBox_);
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

void NativeMainWindow::applyBackendState() {
    serviceStatusLabel_->setText(backend_.getStatus());
    configSummaryLabel_->setText(backend_.getConfigSummary());
    configCard_->setContent(
        QStringLiteral("%1\n%2").arg(configPath_, backend_.getConfigSummary()));
    runtime_ = parseObject(backend_.getRuntimeConfigJson());
    syncSettingsControls();
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
    populateChatCharacters();
    populateReminderCharacters();
    loadNativeReminderState();
    loadNativeLlmSettings();
    const int configured = configuredModels().size();
    startConfiguredButton_->setText(
        configured > 1
            ? tr("Start %1 configured pets").arg(configured)
            : (configured == 1 ? tr("Start configured pet") : tr("No Live2D pet available")));
    startConfiguredButton_->setEnabled(configured > 0);
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
    const QString activeProfile =
        llmSettings_.value(QStringLiteral("active_api_profile")).toString().trimmed();
    llmSettingsStatusLabel_->setText(
        activeProfile.isEmpty()
            ? tr("Editing the current custom LLM configuration")
            : tr("Loaded profile “%1”; saving edits detaches the current configuration")
                  .arg(activeProfile));
}

void NativeMainWindow::saveNativeLlmSettings() {
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
        return;
    }
    llmSettings_ = parseObject(backend_.getLlmSettingsJson());
    serviceStatusLabel_->setText(backend_.getStatus());
    syncNativeLlmSettingsControls();
    llmSettingsStatusLabel_->setText(tr("Native LLM settings saved"));
}

void NativeMainWindow::syncSettingsControls() {
    if (fpsSpinBox_ == nullptr) {
        return;
    }
    fpsSpinBox_->setValue(runtime_.value(QStringLiteral("fps")).toInt(120));
    opacitySpinBox_->setValue(runtime_.value(QStringLiteral("opacity")).toDouble(1.0));
    vsyncSwitch_->setChecked(runtime_.value(QStringLiteral("vsync")).toBool(true));
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
    const QString theme =
        runtime_.value(QStringLiteral("dark_theme")).toString(QStringLiteral("follow_system"));
    const int themeIndex = themeComboBox_->findData(theme);
    themeComboBox_->setCurrentIndex(themeIndex < 0 ? 0 : themeIndex);
    applyTheme(theme);
}

void NativeMainWindow::saveNativeSettings() {
    const QString quality = qualityComboBox_->currentData().toString();
    const bool rendererRestartRequired =
        runtime_.value(QStringLiteral("vsync")).toBool(true) != vsyncSwitch_->isChecked()
        || runtime_.value(QStringLiteral("live2d_quality"))
               .toString(QStringLiteral("balanced")) != quality;
    const QJsonObject settings {
        {QStringLiteral("fps"), fpsSpinBox_->value()},
        {QStringLiteral("opacity"), opacitySpinBox_->value()},
        {QStringLiteral("vsync"), vsyncSwitch_->isChecked()},
        {QStringLiteral("live2d_quality"), quality},
        {QStringLiteral("live2d_scale"), scaleSpinBox_->value()},
        {QStringLiteral("live2d_idle_actions_enabled"), idleActionsSwitch_->isChecked()},
        {QStringLiteral("live2d_random_actions_enabled"), randomActionsSwitch_->isChecked()},
        {QStringLiteral("dark_theme"), themeComboBox_->currentData().toString()},
        {QStringLiteral("drag_locked"), dragLockedSwitch_->isChecked()},
        {QStringLiteral("move_all_roles_together"), moveTogetherSwitch_->isChecked()},
        {QStringLiteral("live2d_head_tracking_enabled"), headTrackingSwitch_->isChecked()},
        {QStringLiteral("live2d_mutual_gaze_enabled"), mutualGazeSwitch_->isChecked()},
    };
    const QString settingsJson = compactJson(settings);
    if (!backend_.saveNativeSettings(configPath_, settingsJson)) {
        serviceStatusLabel_->setText(backend_.getStatus());
        return;
    }

    for (PetLaunchSpec& spec : activeSpecs_) {
        spec.fps = fpsSpinBox_->value();
        spec.opacity = opacitySpinBox_->value();
        spec.vsync = vsyncSwitch_->isChecked();
        spec.live2dQuality = quality;
        spec.live2dScale = scaleSpinBox_->value();
        spec.idleActionsEnabled = idleActionsSwitch_->isChecked();
        spec.randomActionsEnabled = randomActionsSwitch_->isChecked();
        spec.dragLocked = dragLockedSwitch_->isChecked();
        spec.moveAllRolesTogether = moveTogetherSwitch_->isChecked();
        spec.headTrackingEnabled = headTrackingSwitch_->isChecked();
        spec.mutualGazeEnabled = mutualGazeSwitch_->isChecked();
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
            ? tr("Native settings saved; pet renderers are restarting for VSync or quality")
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

void NativeMainWindow::updateModelDetails() {
    const std::optional<ModelCatalogItem> model = selectedModel();
    launchSelectedButton_->setEnabled(model.has_value());
    if (!model.has_value()) {
        modelDetailsLabel_->setText(tr("No Live2D model was found in either model root"));
        return;
    }
    modelDetailsLabel_->setText(
        QStringLiteral("%1\n%2 · %3\n%4")
            .arg(modelTitle(*model), model->character, model->costume, model->path));
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
    QStringList added;
    for (const ModelCatalogItem& model : catalog_) {
        if (added.contains(model.character)) {
            continue;
        }
        added.append(model.character);
        chatCharacterComboBox_->addItem(
            model.characterDisplay.isEmpty() ? model.character : model.characterDisplay,
            QVariant(),
            model.character);
        auto* member = new QListWidgetItem(
            model.characterDisplay.isEmpty() ? model.character : model.characterDisplay,
            chatGroupMembersList_);
        member->setData(Qt::UserRole, model.character);
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
    chatGroupSelector_->setVisible(groupMode);
    updatingChatControls_ = false;
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

QString NativeMainWindow::displayNameForCharacter(const QString& character) const {
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
    const QString databasePath = QDir(projectRoot_).filePath(QStringLiteral("data.db"));
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
    const QString databasePath = QDir(projectRoot_).filePath(QStringLiteral("data.db"));
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
    QStringList groupKeys;
    for (const QJsonValue& value : chats) {
        const QString key = value.toObject().value(QStringLiteral("group_key")).toString();
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
    const QString databasePath = QDir(projectRoot_).filePath(QStringLiteral("data.db"));
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
    const QString databasePath = QDir(projectRoot_).filePath(QStringLiteral("data.db"));
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
    const QString databasePath = QDir(projectRoot_).filePath(QStringLiteral("data.db"));
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
    const QString databasePath = QDir(projectRoot_).filePath(QStringLiteral("data.db"));
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
            currentTimeInstruction())) {
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
    const QString databasePath = QDir(projectRoot_).filePath(QStringLiteral("data.db"));
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
    const QString databasePath = QDir(projectRoot_).filePath(QStringLiteral("data.db"));
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
            currentTimeInstruction())) {
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
            const QString databasePath =
                QDir(projectRoot_).filePath(QStringLiteral("data.db"));
            saved = backend_.saveGroupChatAssistant(
                databasePath,
                configPath_,
                requestId,
                chatStreamText_,
                chatStreamReasoning_,
                compactJson(payload));
            if (saved) {
                const QJsonObject turn = parseObject(backend_.getChatTurnJson());
                int actionsSent = 0;
                for (const QJsonValue& value : turn.value(QStringLiteral("actions")).toArray()) {
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
        const QString databasePath = QDir(projectRoot_).filePath(QStringLiteral("data.db"));
        if (backend_.saveChatAssistant(
                databasePath,
                configPath_,
                activeChatCharacterDisplay_,
                requestId,
                chatStreamText_,
                chatStreamReasoning_,
                compactJson(payload))) {
            const QJsonObject turn = parseObject(backend_.getChatTurnJson());
            int actionsSent = 0;
            for (const QJsonValue& value : turn.value(QStringLiteral("actions")).toArray()) {
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
}

void NativeMainWindow::setChatBusy(bool busy) {
    if (chatInput_ == nullptr) {
        return;
    }
    busy = busy || groupSequenceActive_;
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
    chatClearAttachmentsButton_->setEnabled(!busy && !pendingChatAttachments_.isEmpty());
    chatSendButton_->setEnabled(
        !busy
        && (!chatInput_->toPlainText().trimmed().isEmpty()
            || !pendingChatAttachments_.isEmpty())
        && hasTarget);
    chatCancelButton_->setEnabled(busy);
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
            chatGroupSelector_->setVisible(false);
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
        if (pet.value(QStringLiteral("pet_mode")).toString(QStringLiteral("live2d"))
            != QStringLiteral("live2d")) {
            continue;
        }
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
    spec.modelPath = model.path;
    spec.character = model.character;
    spec.language = runtime_.value(QStringLiteral("language")).toString();
    spec.format = model.format;
    spec.width = pet.value(QStringLiteral("window_width")).toInt(400);
    spec.height = pet.value(QStringLiteral("window_height")).toInt(500);
    spec.x = pet.value(QStringLiteral("window_x")).toInt(-1);
    spec.y = pet.value(QStringLiteral("window_y")).toInt(-1);
    spec.fps = runtime_.value(QStringLiteral("fps")).toInt(120);
    spec.opacity = runtime_.value(QStringLiteral("opacity")).toDouble(1.0);
    spec.vsync = runtime_.value(QStringLiteral("vsync")).toBool(true);
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
        rendererStatusLabel_->setText(tr("No configured Live2D models are available"));
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
