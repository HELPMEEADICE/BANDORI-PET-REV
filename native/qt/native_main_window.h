#pragma once

#include <QJsonObject>
#include <QList>
#include <QString>

#include <optional>

#include <bandori_qt_bridge/src/backend.cxxqt.h>
#include <qtfluentwidgets.h>

#include "pet_process_supervisor.h"

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
    QWidget* createDashboardPage();
    QWidget* createModelsPage();
    QWidget* createSettingsPage();
    bool reloadBackendState();
    void applyBackendState();
    void populateModelList();
    void updateModelDetails();
    void startSelectedPet();
    std::optional<ModelCatalogItem> selectedModel() const;
    std::optional<ModelCatalogItem> configuredModel() const;
    QList<ModelCatalogItem> configuredModels() const;
    PetLaunchSpec launchSpecFor(const ModelCatalogItem& model) const;
    QJsonObject configuredPetFor(const ModelCatalogItem& model) const;

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
    qfw::SettingCard* configCard_ = nullptr;
    qfw::SettingCard* modelRootCard_ = nullptr;
    qfw::SettingCard* runtimeCard_ = nullptr;
};

}  // namespace bandori
