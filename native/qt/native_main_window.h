#pragma once

#include <QJsonObject>
#include <QList>
#include <QString>

#include <optional>

#include <bandori_qt_bridge/src/backend.cxxqt.h>
#include <qtfluentwidgets.h>

#include "pet_process_supervisor.h"

class QAction;
class QCloseEvent;
class QSystemTrayIcon;
class QTextBrowser;

namespace bandori {

struct ModelCatalogItem {
    QString character;
    QString characterDisplay;
    QString costume;
    QString costumeDisplay;
    QString path;
    QString format;
    bool isDefault = false;
};

class NativeMainWindow final : public qfw::FluentWindow {
public:
    NativeMainWindow(
        QString projectRoot,
        QString userModelsRoot,
        QString configPath,
        QWidget* parent = nullptr);

    void startPet(PetLaunchSpec spec);
    void startPets(QList<PetLaunchSpec> specs);
    bool startConfiguredPet();
    bool startConfiguredPets();

private:
    void setupUi();
    void setupTray();
    void showControlCenter();
    void quitFromTray();
    QWidget* createDashboardPage();
    QWidget* createModelsPage();
    QWidget* createChatPage();
    QWidget* createSettingsPage();
    bool reloadBackendState();
    void syncSettingsControls();
    void saveNativeSettings();
    void applyTheme(const QString& mode);
    void applyBackendState();
    void populateModelList();
    void updateModelDetails();
    void populateChatCharacters();
    void refreshChatState(
        const QString& requestedConversationId = {},
        bool resetPagination = false);
    void openNativeChat(const QString& character);
    void startSelectedPet();
    std::optional<ModelCatalogItem> selectedModel() const;
    std::optional<ModelCatalogItem> configuredModel() const;
    QList<ModelCatalogItem> configuredModels() const;
    PetLaunchSpec launchSpecFor(const ModelCatalogItem& model) const;
    QJsonObject configuredPetFor(const ModelCatalogItem& model) const;

protected:
    void closeEvent(QCloseEvent* event) override;

private:
    QString projectRoot_;
    QString userModelsRoot_;
    QString configPath_;
    Backend backend_;
    PetProcessSupervisor supervisor_;
    QList<ModelCatalogItem> catalog_;
    QJsonObject runtime_;
    QList<PetLaunchSpec> activeSpecs_;

    qfw::BodyLabel* serviceStatusLabel_ = nullptr;
    qfw::CaptionLabel* configSummaryLabel_ = nullptr;
    qfw::CaptionLabel* rendererStatusLabel_ = nullptr;
    qfw::PrimaryPushButton* startConfiguredButton_ = nullptr;
    qfw::PushButton* restartButton_ = nullptr;
    qfw::PushButton* stopButton_ = nullptr;
    qfw::ListWidget* modelList_ = nullptr;
    qfw::CaptionLabel* modelCountLabel_ = nullptr;
    qfw::BodyLabel* modelDetailsLabel_ = nullptr;
    qfw::PrimaryPushButton* launchSelectedButton_ = nullptr;
    QWidget* chatPage_ = nullptr;
    qfw::ComboBox* chatCharacterComboBox_ = nullptr;
    qfw::ComboBox* chatConversationComboBox_ = nullptr;
    qfw::CaptionLabel* chatStatusLabel_ = nullptr;
    qfw::PushButton* chatLoadOlderButton_ = nullptr;
    QTextBrowser* chatTranscript_ = nullptr;
    int chatMessageLimit_ = 200;
    bool updatingChatControls_ = false;
    qfw::SettingCard* configCard_ = nullptr;
    qfw::SettingCard* modelRootCard_ = nullptr;
    qfw::SettingCard* runtimeCard_ = nullptr;
    qfw::SpinBox* fpsSpinBox_ = nullptr;
    qfw::DoubleSpinBox* opacitySpinBox_ = nullptr;
    qfw::SwitchButton* vsyncSwitch_ = nullptr;
    qfw::ComboBox* qualityComboBox_ = nullptr;
    qfw::SpinBox* scaleSpinBox_ = nullptr;
    qfw::SwitchButton* idleActionsSwitch_ = nullptr;
    qfw::SwitchButton* randomActionsSwitch_ = nullptr;
    qfw::SwitchButton* dragLockedSwitch_ = nullptr;
    qfw::SwitchButton* moveTogetherSwitch_ = nullptr;
    qfw::SwitchButton* headTrackingSwitch_ = nullptr;
    qfw::SwitchButton* mutualGazeSwitch_ = nullptr;
    qfw::ComboBox* themeComboBox_ = nullptr;
    qfw::PrimaryPushButton* saveSettingsButton_ = nullptr;
    QSystemTrayIcon* trayIcon_ = nullptr;
    QAction* startTrayAction_ = nullptr;
    QAction* stopTrayAction_ = nullptr;
    bool exitRequested_ = false;
    bool trayHintShown_ = false;
};

}  // namespace bandori
