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
constexpr int kChatMessagePageSize = 200;
constexpr int kChatMessageLimit = 1000;

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
    QWidget* settings = createSettingsPage();
    dashboard->setObjectName(QStringLiteral("dashboardPage"));
    models->setObjectName(QStringLiteral("modelsPage"));
    chatPage_->setObjectName(QStringLiteral("chatPage"));
    settings->setObjectName(QStringLiteral("settingsPage"));
    addSubInterface(dashboard, qfw::FluentIconEnum::Home, tr("Overview"));
    addSubInterface(models, qfw::FluentIconEnum::People, tr("Models"));
    addSubInterface(chatPage_, qfw::FluentIconEnum::Chat, tr("Chat history"));
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
    const int configured = configuredModels().size();
    startConfiguredButton_->setText(
        configured > 1
            ? tr("Start %1 configured pets").arg(configured)
            : (configured == 1 ? tr("Start configured pet") : tr("No Live2D pet available")));
    startConfiguredButton_->setEnabled(configured > 0);
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
    const qint64 requestId =
        backend_.startChatStream(configPath_, backend_.getChatRequestJson());
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
    const qint64 requestId =
        backend_.startGroupChatStream(configPath_, backend_.getChatRequestJson());
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
