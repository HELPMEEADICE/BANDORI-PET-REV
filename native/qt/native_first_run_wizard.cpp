#include "native_first_run_wizard.h"

#include <QDesktopServices>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QFont>
#include <QFrame>
#include <QGridLayout>
#include <QHBoxLayout>
#include <QIcon>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QProgressBar>
#include <QScrollArea>
#include <QSet>
#include <QStackedWidget>
#include <QToolButton>
#include <QUrl>
#include <QVBoxLayout>

#include <algorithm>
#include <utility>

#include <qtfluentwidgets.h>

namespace bandori {

namespace {

constexpr auto kAccent = "#e90050";

QLabel* wrappedLabel(const QString& text, QWidget* parent, bool strong = false) {
    auto* label = new QLabel(text, parent);
    label->setWordWrap(true);
    if (strong) {
        QFont font = label->font();
        font.setBold(true);
        label->setFont(font);
    }
    return label;
}

QFrame* card(QWidget* parent) {
    auto* result = new QFrame(parent);
    result->setObjectName(QStringLiteral("wizardCard"));
    result->setStyleSheet(QStringLiteral(
        "QFrame#wizardCard { background: #ffffff; border: 1px solid #ececf0; "
        "border-radius: 8px; }"));
    return result;
}

QJsonArray loadBands(const QString& projectRoot) {
    QFile file(QDir(projectRoot).filePath(QStringLiteral("band.json")));
    if (!file.open(QIODevice::ReadOnly)) {
        return {};
    }
    return QJsonDocument::fromJson(file.readAll()).object().value(QStringLiteral("bands")).toArray();
}

QString displayText(const QJsonObject& model, const QString& key, const QString& fallback) {
    const QString value = model.value(key).toString().trimmed();
    return value.isEmpty() ? fallback : value;
}

}  // namespace

NativeFirstRunWizard::NativeFirstRunWizard(
    QString projectRoot,
    QString userModelsRoot,
    QJsonArray catalog,
    QJsonObject runtime,
    QWidget* parent)
    : QDialog(parent),
      projectRoot_(QDir(std::move(projectRoot)).absolutePath()),
      userModelsRoot_(QDir(std::move(userModelsRoot)).absolutePath()),
      catalog_(std::move(catalog)),
      runtime_(std::move(runtime)) {
    setWindowTitle(QStringLiteral("Bandori 桌宠 - 设置"));
    setModal(true);
    resize(1180, 710);
    setMinimumSize(980, 640);
    setStyleSheet(QStringLiteral(
        "QDialog { background: #ffffff; color: #111111; }"
        "QLabel { color: #111111; }"
        "QScrollArea { border: none; background: transparent; }"));

    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(20, 18, 20, 18);
    root->setSpacing(14);

    auto* title = new qfw::TitleLabel(QStringLiteral("首次启动向导"), this);
    auto* subtitle = new qfw::SubtitleLabel(
        QStringLiteral("按顺序完成模型包、角色服装和可选 AI/TTS 配置，之后就可以启动桌宠。"),
        this);
    root->addWidget(title);
    root->addWidget(subtitle);

    auto* steps = new QHBoxLayout();
    steps->setSpacing(8);
    for (const QString& text : {
             QStringLiteral("1 模型包"),
             QStringLiteral("2 角色/服装"),
             QStringLiteral("3 AI/TTS")}) {
        auto* label = new QLabel(text, this);
        label->setAlignment(Qt::AlignCenter);
        label->setFixedHeight(30);
        stepLabels_.append(label);
        steps->addWidget(label, 1);
    }
    root->addLayout(steps);

    stack_ = new QStackedWidget(this);
    stack_->addWidget(createModelPackagePage());
    stack_->addWidget(createModelSelectionPage());
    stack_->addWidget(createAiPage());
    root->addWidget(stack_, 1);

    auto* footer = new QHBoxLayout();
    footer->setSpacing(8);
    backButton_ = new qfw::PushButton(
        qfw::FluentIcon(qfw::FluentIconEnum::LeftArrow), QStringLiteral("上一步"), this);
    skipButton_ = new qfw::PushButton(QStringLiteral("跳过 AI/TTS，启动"), this);
    nextButton_ = new qfw::PrimaryPushButton(
        qfw::FluentIcon(qfw::FluentIconEnum::Accept), QStringLiteral("下一步"), this);
    for (QWidget* button : {
             static_cast<QWidget*>(backButton_),
             static_cast<QWidget*>(skipButton_),
             static_cast<QWidget*>(nextButton_),
         }) {
        button->setFixedHeight(36);
    }
    footer->addWidget(backButton_);
    footer->addStretch(1);
    footer->addWidget(skipButton_);
    footer->addWidget(nextButton_);
    root->addLayout(footer);

    connect(backButton_, &QPushButton::clicked, this, [this]() { goBack(); });
    connect(skipButton_, &QPushButton::clicked, this, &QDialog::accept);
    connect(nextButton_, &QPushButton::clicked, this, [this]() { advance(); });
    setStep(0);
}

QWidget* NativeFirstRunWizard::createModelPackagePage() {
    auto* scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    auto* page = new QWidget(scroll);
    auto* layout = new QVBoxLayout(page);
    layout->setContentsMargins(0, 6, 14, 6);
    layout->setSpacing(12);
    layout->addWidget(new qfw::TitleLabel(QStringLiteral("检测模型包"), page));
    layout->addWidget(wrappedLabel(
        QStringLiteral("自动检测 models 文件夹中的角色包，缺失时可从模型管理页补充。"),
        page, true));

    auto* guide = card(page);
    auto* guideLayout = new QVBoxLayout(guide);
    guideLayout->setContentsMargins(16, 14, 16, 14);
    guideLayout->setSpacing(10);
    guideLayout->addWidget(wrappedLabel(QStringLiteral("正确放置方式"), guide, true));
    guideLayout->addWidget(wrappedLabel(
        QStringLiteral("下载模型包后请先解压，然后把解压出的角色 .zst 压缩包或角色文件夹直接放进项目目录的 models 文件夹。"),
        guide));
    QSet<QString> characters;
    for (const QJsonValue& value : catalog_) {
        const QString character = value.toObject().value(QStringLiteral("character")).toString();
        if (!character.isEmpty()) {
            characters.insert(character);
        }
    }
    guideLayout->addWidget(wrappedLabel(
        QStringLiteral("检测到 %1 个模型条目，覆盖 %2 个角色。")
            .arg(catalog_.size()).arg(characters.size()), guide));
    guideLayout->addWidget(wrappedLabel(
        QStringLiteral("模型目录：%1").arg(userModelsRoot_), guide));
    layout->addWidget(guide);

    auto* status = card(page);
    auto* statusLayout = new QVBoxLayout(status);
    statusLayout->setContentsMargins(16, 14, 16, 14);
    statusLayout->setSpacing(8);
    statusLayout->addWidget(wrappedLabel(
        catalog_.isEmpty() ? QStringLiteral("还没有检测到模型") : QStringLiteral("已检测到模型"),
        status, true));
    modelStatusLabel_ = wrappedLabel(
        catalog_.isEmpty()
            ? QStringLiteral("请把模型包放入 models 文件夹后重新启动，或打开目录进行整理。")
            : QStringLiteral("当前检测到 %1 个可用角色/服装模型，可以进入下一步。")
                  .arg(catalog_.size()),
        status);
    statusLayout->addWidget(modelStatusLabel_);
    QSet<QString> expectedCharacters;
    for (const QJsonValue& bandValue : loadBands(projectRoot_)) {
        for (const QJsonValue& characterValue :
             bandValue.toObject().value(QStringLiteral("characters")).toArray()) {
            expectedCharacters.insert(characterValue.toString());
        }
    }
    auto* progress = new QProgressBar(status);
    progress->setTextVisible(false);
    progress->setRange(0, std::max(1, static_cast<int>(expectedCharacters.size())));
    progress->setValue(static_cast<int>(characters.size()));
    progress->setFixedHeight(4);
    progress->setStyleSheet(QStringLiteral(
        "QProgressBar { border: none; background: #d7d9de; }"
        "QProgressBar::chunk { background: #e90050; }"));
    statusLayout->addWidget(progress);
    layout->addWidget(status);

    auto* actions = new QHBoxLayout();
    auto* downloadButton = new qfw::PrimaryPushButton(
        qfw::FluentIcon(qfw::FluentIconEnum::Download), QStringLiteral("一键下载模型包"), page);
    auto* openButton = new qfw::PushButton(
        qfw::FluentIcon(qfw::FluentIconEnum::Folder), QStringLiteral("打开 models 文件夹"), page);
    downloadButton->setFixedHeight(36);
    openButton->setFixedHeight(36);
    actions->addWidget(downloadButton);
    actions->addWidget(openButton);
    actions->addStretch(1);
    connect(downloadButton, &QPushButton::clicked, this, [this]() {
        QDesktopServices::openUrl(QUrl(QStringLiteral(
            "https://modelscope.cn/datasets/HELPMEEADICE/BanG-Dream-Live2D/files")));
        modelStatusLabel_->setText(QStringLiteral(
            "已打开模型包下载页。下载完成后把 .zst 文件放入 models 文件夹，再重新检测。"));
    });
    connect(openButton, &QPushButton::clicked, this, [this]() { openModelsFolder(); });
    layout->addLayout(actions);
    layout->addStretch(1);
    scroll->setWidget(page);
    return scroll;
}

QWidget* NativeFirstRunWizard::createModelSelectionPage() {
    auto* scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    auto* page = new QWidget(scroll);
    auto* layout = new QVBoxLayout(page);
    layout->setContentsMargins(0, 6, 14, 6);
    layout->setSpacing(12);
    auto* title = new qfw::TitleLabel(QStringLiteral("选择乐队"), page);
    title->setAlignment(Qt::AlignCenter);
    layout->addWidget(title);
    auto* subtitle = wrappedLabel(QStringLiteral("请先选择乐队，再选择角色和服装"), page, true);
    subtitle->setAlignment(Qt::AlignCenter);
    layout->addWidget(subtitle);

    auto* filters = new QHBoxLayout();
    auto* search = new qfw::LineEdit(page);
    search->setPlaceholderText(QStringLiteral("搜索角色 / 乐队 / key"));
    auto* category = new qfw::ComboBox(page);
    category->addItem(QStringLiteral("全部"), QVariant(), QStringLiteral("all"));
    category->addItem(QStringLiteral("已有模型"), QVariant(), QStringLiteral("available"));
    category->setFixedWidth(140);
    auto* importButton = new qfw::PushButton(
        qfw::FluentIcon(qfw::FluentIconEnum::Add), QStringLiteral("导入自定义模型"), page);
    filters->addWidget(search, 1);
    filters->addWidget(category);
    filters->addWidget(importButton);
    layout->addLayout(filters);

    auto* grid = new QGridLayout();
    grid->setSpacing(12);
    int index = 0;
    QJsonObject firstAvailableBand;
    for (const QJsonValue& value : loadBands(projectRoot_)) {
        const QJsonObject band = value.toObject();
        int available = 0;
        const QJsonArray bandCharacters = band.value(QStringLiteral("characters")).toArray();
        for (const QJsonValue& characterValue : bandCharacters) {
            const QString character = characterValue.toString();
            const bool found = std::any_of(
                catalog_.cbegin(), catalog_.cend(), [&character](const QJsonValue& model) {
                    return model.toObject().value(QStringLiteral("character")).toString() == character;
                });
            available += found ? 1 : 0;
        }
        if (available == 0) {
            continue;
        }
        if (firstAvailableBand.isEmpty()) {
            firstAvailableBand = band;
        }
        auto* button = new QToolButton(page);
        button->setObjectName(QStringLiteral("wizardBandCard"));
        button->setToolButtonStyle(Qt::ToolButtonTextUnderIcon);
        button->setText(QStringLiteral("%1\n%2名角色")
                            .arg(band.value(QStringLiteral("display")).toString())
                            .arg(available));
        const QString logo = band.value(QStringLiteral("logo")).toString();
        if (!logo.isEmpty()) {
            button->setIcon(QIcon(QDir(projectRoot_).filePath(logo)));
            button->setIconSize(QSize(126, 58));
        }
        button->setMinimumSize(180, 120);
        button->setCursor(Qt::PointingHandCursor);
        button->setStyleSheet(QStringLiteral(
            "QToolButton { text-align: left; background: #fff; border: 1px solid #ececf0; "
            "border-radius: 8px; padding: 10px 16px; }"
            "QToolButton:hover { border-color: #e90050; background: #fff7fa; }"));
        connect(button, &QToolButton::clicked, this, [this, band]() { selectBand(band); });
        grid->addWidget(button, index / 3, index % 3);
        ++index;
    }
    layout->addLayout(grid);
    connect(search, &QLineEdit::textChanged, this, [page](const QString& text) {
        const QString query = text.trimmed();
        for (QToolButton* button : page->findChildren<QToolButton*>(
                 QStringLiteral("wizardBandCard"))) {
            button->setVisible(
                query.isEmpty() || button->text().contains(query, Qt::CaseInsensitive));
        }
    });
    connect(importButton, &QPushButton::clicked, this, [this]() { openModelsFolder(); });

    auto* selector = card(page);
    auto* selectorLayout = new QHBoxLayout(selector);
    selectorLayout->setContentsMargins(16, 12, 16, 12);
    selectionHintLabel_ = wrappedLabel(QStringLiteral("选择上方乐队"), selector, true);
    characterComboBox_ = new qfw::ComboBox(selector);
    costumeComboBox_ = new qfw::ComboBox(selector);
    characterComboBox_->setMinimumWidth(190);
    costumeComboBox_->setMinimumWidth(220);
    selectorLayout->addWidget(selectionHintLabel_, 1);
    selectorLayout->addWidget(characterComboBox_);
    selectorLayout->addWidget(costumeComboBox_);
    connect(
        characterComboBox_, &qfw::ComboBox::currentIndexChanged,
        this, [this](int) { updateModelSelection(characterComboBox_->currentData().toString()); });
    layout->addWidget(selector);
    if (!firstAvailableBand.isEmpty()) {
        selectBand(firstAvailableBand);
    }
    layout->addStretch(1);
    scroll->setWidget(page);
    return scroll;
}

QWidget* NativeFirstRunWizard::createAiPage() {
    auto* scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    auto* page = new QWidget(scroll);
    auto* layout = new QVBoxLayout(page);
    layout->setContentsMargins(0, 6, 14, 6);
    layout->setSpacing(12);
    layout->addWidget(new qfw::TitleLabel(QStringLiteral("可选配置 AI / TTS"), page));
    layout->addWidget(wrappedLabel(
        QStringLiteral("这些配置可以先跳过，以后也能在设置页里继续调整。"), page, true));

    auto* llm = card(page);
    auto* llmLayout = new QVBoxLayout(llm);
    llmLayout->setContentsMargins(16, 14, 16, 14);
    llmLayout->setSpacing(8);
    llmLayout->addWidget(new qfw::SubtitleLabel(QStringLiteral("LLM 配置"), llm));
    llmLayout->addWidget(wrappedLabel(QStringLiteral("配置 AI 聊天后端（兼容 OpenAI API）"), llm, true));
    llmApiUrlEdit_ = new qfw::LineEdit(llm);
    llmApiKeyEdit_ = new qfw::LineEdit(llm);
    llmModelEdit_ = new qfw::LineEdit(llm);
    llmApiUrlEdit_->setPlaceholderText(QStringLiteral("https://api.openai.com/v1/chat/completions"));
    llmApiKeyEdit_->setPlaceholderText(QStringLiteral("API 密钥（可留空）"));
    llmApiKeyEdit_->setEchoMode(QLineEdit::PasswordEchoOnEdit);
    llmModelEdit_->setPlaceholderText(QStringLiteral("主模型 ID，例如 gpt-4o"));
    llmLayout->addWidget(llmApiUrlEdit_);
    llmLayout->addWidget(llmApiKeyEdit_);
    llmLayout->addWidget(llmModelEdit_);
    layout->addWidget(llm);

    auto* tts = card(page);
    auto* ttsLayout = new QVBoxLayout(tts);
    ttsLayout->setContentsMargins(16, 14, 16, 14);
    ttsLayout->setSpacing(8);
    auto* ttsHeader = new QHBoxLayout();
    ttsHeader->addWidget(new qfw::SubtitleLabel(QStringLiteral("TTS 配置"), tts));
    ttsHeader->addStretch(1);
    ttsEnabledSwitch_ = new qfw::SwitchButton(tts);
    ttsHeader->addWidget(ttsEnabledSwitch_);
    ttsLayout->addLayout(ttsHeader);
    ttsApiUrlEdit_ = new qfw::LineEdit(tts);
    ttsApiUrlEdit_->setPlaceholderText(QStringLiteral("http://127.0.0.1:9880/"));
    ttsLayout->addWidget(ttsApiUrlEdit_);
    layout->addWidget(tts);
    layout->addStretch(1);
    scroll->setWidget(page);
    return scroll;
}

void NativeFirstRunWizard::setStep(int step) {
    step_ = std::clamp(step, 0, 2);
    stack_->setCurrentIndex(step_);
    backButton_->setEnabled(step_ > 0);
    skipButton_->setVisible(step_ == 2);
    nextButton_->setText(step_ == 2 ? QStringLiteral("保存并启动") : QStringLiteral("下一步"));
    nextButton_->setEnabled(step_ != 0 || !catalog_.isEmpty());
    updateStepStyle();
}

void NativeFirstRunWizard::updateStepStyle() {
    for (int index = 0; index < stepLabels_.size(); ++index) {
        const bool active = index == step_;
        stepLabels_.at(index)->setStyleSheet(QStringLiteral(
            "QLabel { color: %1; background: %2; border-radius: 8px; font-weight: 600; }")
                .arg(active ? QStringLiteral("#ffffff") : QStringLiteral("#26344d"),
                     active ? QString::fromLatin1(kAccent) : QStringLiteral("#edf0f5")));
    }
}

void NativeFirstRunWizard::selectBand(const QJsonObject& band) {
    const QJsonArray characters = band.value(QStringLiteral("characters")).toArray();
    const QString previous = characterComboBox_->currentData().toString();
    characterComboBox_->clear();
    for (const QJsonValue& characterValue : characters) {
        const QString character = characterValue.toString();
        const auto found = std::find_if(
            catalog_.cbegin(), catalog_.cend(), [&character](const QJsonValue& model) {
                return model.toObject().value(QStringLiteral("character")).toString() == character;
            });
        if (found == catalog_.cend()) {
            continue;
        }
        const QJsonObject model = found->toObject();
        characterComboBox_->addItem(
            displayText(model, QStringLiteral("character_display"), character),
            QVariant(), character);
    }
    const int previousIndex = characterComboBox_->findData(previous);
    if (previousIndex >= 0) {
        characterComboBox_->setCurrentIndex(previousIndex);
    }
    selectionHintLabel_->setText(
        QStringLiteral("已选择 %1").arg(band.value(QStringLiteral("display")).toString()));
    updateModelSelection(characterComboBox_->currentData().toString());
}

void NativeFirstRunWizard::updateModelSelection(const QString& character) {
    const QString previous = costumeComboBox_->currentData().toString();
    costumeComboBox_->clear();
    for (const QJsonValue& value : catalog_) {
        const QJsonObject model = value.toObject();
        if (model.value(QStringLiteral("character")).toString() != character) {
            continue;
        }
        QString label = displayText(
            model, QStringLiteral("costume_display"), model.value(QStringLiteral("costume")).toString());
        if (model.value(QStringLiteral("is_default")).toBool()) {
            label += QStringLiteral("（默认）");
        }
        costumeComboBox_->addItem(label, QVariant(), model.value(QStringLiteral("path")).toString());
    }
    const int previousIndex = costumeComboBox_->findData(previous);
    if (previousIndex >= 0) {
        costumeComboBox_->setCurrentIndex(previousIndex);
    }
}

QJsonObject NativeFirstRunWizard::currentModel() const {
    const QString path = costumeComboBox_->currentData().toString();
    for (const QJsonValue& value : catalog_) {
        const QJsonObject model = value.toObject();
        if (model.value(QStringLiteral("path")).toString() == path) {
            return model;
        }
    }
    return {};
}

void NativeFirstRunWizard::advance() {
    if (step_ == 0 && catalog_.isEmpty()) {
        QMessageBox::warning(
            this, QStringLiteral("还没有检测到模型"),
            QStringLiteral("请先把角色模型包放入 models 文件夹。"));
        return;
    }
    if (step_ == 1 && currentModel().isEmpty()) {
        QMessageBox::information(
            this, QStringLiteral("请选择角色"),
            QStringLiteral("请先选择乐队、角色和服装，再进入下一步。"));
        return;
    }
    if (step_ < 2) {
        setStep(step_ + 1);
    } else {
        accept();
    }
}

void NativeFirstRunWizard::goBack() {
    if (step_ > 0) {
        setStep(step_ - 1);
    }
}

void NativeFirstRunWizard::openModelsFolder() {
    QDir().mkpath(userModelsRoot_);
    QDesktopServices::openUrl(QUrl::fromLocalFile(userModelsRoot_));
}

QJsonObject NativeFirstRunWizard::nativeSettings() const {
    const QJsonObject model = currentModel();
    if (model.isEmpty()) {
        return {};
    }
    const QString character = model.value(QStringLiteral("character")).toString();
    const QString costume = model.value(QStringLiteral("costume")).toString();
    QJsonObject configured {
        {QStringLiteral("character"), character},
        {QStringLiteral("costume"), costume},
        {QStringLiteral("path"), model.value(QStringLiteral("path"))},
        {QStringLiteral("pet_mode"), QStringLiteral("live2d")},
    };
    return {
        {QStringLiteral("character"), character},
        {QStringLiteral("costume"), costume},
        {QStringLiteral("models"), QJsonArray {configured}},
    };
}

QJsonObject NativeFirstRunWizard::llmSettings() const {
    QJsonObject settings;
    if (!llmApiUrlEdit_->text().trimmed().isEmpty()) {
        settings.insert(QStringLiteral("api_url"), llmApiUrlEdit_->text().trimmed());
    }
    if (!llmApiKeyEdit_->text().trimmed().isEmpty()) {
        settings.insert(QStringLiteral("api_key"), llmApiKeyEdit_->text().trimmed());
    }
    if (!llmModelEdit_->text().trimmed().isEmpty()) {
        settings.insert(QStringLiteral("model_id"), llmModelEdit_->text().trimmed());
    }
    return settings;
}

QJsonObject NativeFirstRunWizard::ttsSettings() const {
    QJsonObject settings {{QStringLiteral("enabled"), ttsEnabledSwitch_->isChecked()}};
    if (!ttsApiUrlEdit_->text().trimmed().isEmpty()) {
        settings.insert(QStringLiteral("api_url"), ttsApiUrlEdit_->text().trimmed());
    }
    return settings;
}

}  // namespace bandori
