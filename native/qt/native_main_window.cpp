#include "native_main_window.h"

#include <QAbstractItemView>
#include <QDebug>
#include <QDir>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QListWidgetItem>
#include <QScrollArea>
#include <QVariant>
#include <QVBoxLayout>

#include <algorithm>
#include <utility>

namespace bandori {

namespace {

constexpr int kPathRole = Qt::UserRole;
constexpr int kCharacterRole = Qt::UserRole + 1;
constexpr int kCostumeRole = Qt::UserRole + 2;
constexpr int kFormatRole = Qt::UserRole + 3;

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
    reloadBackendState();

    connect(
        &supervisor_,
        &PetProcessSupervisor::statusChanged,
        this,
        [this](const QString& status) {
            rendererStatusLabel_->setText(status);
            runtimeCard_->setContent(status);
            restartButton_->setEnabled(!activeSpecs_.isEmpty());
            stopButton_->setEnabled(supervisor_.isRunning());
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
                rendererStatusLabel_->setText(
                    tr("Native chat UI is not ported yet; renderer remains active"));
            }
        });
}

void NativeMainWindow::setupUi() {
    setWindowTitle(QStringLiteral("BandoriPet Rust + Qt"));
    resize(920, 640);
    setMinimumSize(760, 520);

    QWidget* dashboard = createDashboardPage();
    QWidget* models = createModelsPage();
    QWidget* settings = createSettingsPage();
    dashboard->setObjectName(QStringLiteral("dashboardPage"));
    models->setObjectName(QStringLiteral("modelsPage"));
    settings->setObjectName(QStringLiteral("settingsPage"));
    addSubInterface(dashboard, qfw::FluentIconEnum::Home, tr("Overview"));
    addSubInterface(models, qfw::FluentIconEnum::People, tr("Models"));
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
    const QJsonObject settings {
        {QStringLiteral("fps"), fpsSpinBox_->value()},
        {QStringLiteral("opacity"), opacitySpinBox_->value()},
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
        spec.dragLocked = dragLockedSwitch_->isChecked();
        spec.moveAllRolesTogether = moveTogetherSwitch_->isChecked();
        spec.headTrackingEnabled = headTrackingSwitch_->isChecked();
        spec.mutualGazeEnabled = mutualGazeSwitch_->isChecked();
    }
    const bool delivered = !supervisor_.isRunning()
        || supervisor_.broadcastSettings(settingsJson);
    applyBackendState();
    rendererStatusLabel_->setText(
        delivered ? tr("Native settings saved and applied")
                  : tr("Settings saved; running pets did not acknowledge the IPC broadcast"));
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
    spec.lipSyncMaxOpen =
        runtime_.value(QStringLiteral("lip_sync_max_open")).toDouble(0.55);
    spec.hitAlphaThreshold =
        runtime_.value(QStringLiteral("hit_alpha_threshold")).toInt(8);
    spec.clickMotionActions =
        compactJson(pet.value(QStringLiteral("click_motion_actions")).toObject());
    spec.pokeMotion = runtime_.value(QStringLiteral("poke_motion")).toString();
    spec.pokeExpression = runtime_.value(QStringLiteral("poke_expression")).toString();
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
