#pragma once

#include <QJsonArray>
#include <QJsonObject>
#include <QList>
#include <QString>
#include <QStringList>
#include <QTimer>

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
    QWidget* createHistorySearchPage();
    QWidget* createStatisticsPage();
    QWidget* createDataManagementPage();
    QWidget* createMemoryPage();
    QWidget* createUserProfilesPage();
    QWidget* createPersonaPage();
    QWidget* createLlmSettingsPage();
    QWidget* createSettingsPage();
    bool reloadBackendState();
    void syncSettingsControls();
    void saveNativeSettings();
    void applyTheme(const QString& mode);
    void applyBackendState();
    void populateModelList();
    void updateModelDetails();
    void populateChatCharacters();
    void populateReminderCharacters();
    void loadNativeReminderState();
    void refreshNativeReminderList();
    void updateNativeReminderActions();
    bool mutateNativeReminder(const QJsonObject& command);
    void addNativeAlarm();
    void addNativePomodoro();
    void toggleSelectedNativeAlarm();
    void deleteSelectedNativeReminder();
    void loadNativeLlmSettings();
    void syncNativeLlmSettingsControls();
    bool saveNativeLlmSettings();
    bool mutateNativeLlmProfile(const QJsonObject& command);
    void applySelectedNativeLlmProfile();
    void saveCurrentNativeLlmProfile();
    void deleteSelectedNativeLlmProfile();
    void startNativeProviderOperation(const QString& target, const QString& operation);
    void handleNativeProviderOperation(const QString& payloadJson);
    void setNativeProviderBusy(bool busy);
    void populateMemoryCharacters();
    void refreshNativeMemoryState();
    void renderNativeMemories();
    void loadSelectedNativeMemory();
    bool mutateNativeMemory(const QJsonObject& command);
    void saveNativeMemory();
    void deleteSelectedNativeMemories();
    void startNewNativeMemory();
    void loadNativeUserProfiles();
    void syncNativeUserProfileControls();
    void loadSelectedNativeUserProfile();
    bool mutateNativeUserProfile(const QJsonObject& command);
    void activateSelectedNativeUserProfile();
    void createNativeUserProfile();
    void saveSelectedNativeUserProfile();
    void deleteSelectedNativeUserProfile();
    void chooseNativeUserAvatar();
    void loadNativePersonaSettings();
    void syncNativePersonaControls();
    void updateNativePovModeControls();
    void syncSelectedNativeCharacterPersona();
    void loadSelectedNativeCharacterPersona();
    bool mutateNativePersona(const QJsonObject& command);
    void saveNativePov();
    void saveNativePovPersona();
    void deleteSelectedNativePovPersona();
    void saveNativeCharacterPersona(bool asNew);
    void deleteSelectedNativeCharacterPersona();
    void importNativeCharacterPersonaDocuments();
    void loadNativeHistoryFilters();
    void syncNativeHistoryFilters();
    void searchNativeHistory(bool append);
    void resetNativeHistoryFilters();
    void populateNativeStatisticsCharacters();
    void refreshNativeStatistics();
    void renderNativeStatistics();
    void exportNativeSettingsPackage();
    void importNativeSettingsPackage();
    void exportNativeChatDatabase();
    void importNativeChatDatabase();
    void showNativeDataSummary(const QString& action);
    void refreshNativeAttachmentStats();
    void saveNativeAttachmentSettings();
    void cleanupNativeChatAttachments(bool clearAll);
    void refreshChatState(
        const QString& requestedConversationId = {},
        bool resetPagination = false);
    void refreshGroupChatState(
        const QString& requestedConversationId = {},
        bool resetPagination = false);
    void sendNativeChat();
    void sendNativeGroupChat(const QString& content, const QString& attachmentsJson);
    void startNextGroupResponse();
    void finishGroupSequence(const QString& status);
    void cancelNativeChat();
    void handleChatStreamEvent(const QString& payloadJson);
    void handleChatMemoryEvent(const QString& payloadJson);
    int dispatchChatToolEffects(const QJsonObject& payload, const QString& character);
    void pollNativeReminders();
    void chooseChatAttachments();
    void clearPendingChatAttachments();
    void updatePendingChatAttachments();
    void startNewChatConversation();
    void deleteSelectedChatConversation();
    void setChatBusy(bool busy);
    void renderChatStreamPreview();
    bool isGroupChatMode() const;
    QJsonArray selectedGroupMembers() const;
    QString selectedGroupKey() const;
    QString displayNameForCharacter(const QString& character) const;
    QString groupDisplayName(const QString& groupKey) const;
    void selectGroupKeyMembers(const QString& groupKey);
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
    qfw::ComboBox* chatModeComboBox_ = nullptr;
    QWidget* chatPrivateSelector_ = nullptr;
    QWidget* chatGroupSelector_ = nullptr;
    qfw::ComboBox* chatCharacterComboBox_ = nullptr;
    qfw::ComboBox* chatGroupComboBox_ = nullptr;
    qfw::ListWidget* chatGroupMembersList_ = nullptr;
    qfw::ComboBox* chatConversationComboBox_ = nullptr;
    qfw::CaptionLabel* chatStatusLabel_ = nullptr;
    qfw::PushButton* chatLoadOlderButton_ = nullptr;
    qfw::PushButton* chatRefreshButton_ = nullptr;
    qfw::PushButton* chatNewConversationButton_ = nullptr;
    qfw::PushButton* chatDeleteConversationButton_ = nullptr;
    qfw::PushButton* chatAttachButton_ = nullptr;
    qfw::PushButton* chatClearAttachmentsButton_ = nullptr;
    qfw::CaptionLabel* chatAttachmentLabel_ = nullptr;
    QTextBrowser* chatTranscript_ = nullptr;
    qfw::PlainTextEdit* chatInput_ = nullptr;
    qfw::PrimaryPushButton* chatSendButton_ = nullptr;
    qfw::PushButton* chatCancelButton_ = nullptr;
    QString chatTranscriptBase_;
    QString chatStreamText_;
    QString chatStreamReasoning_;
    QString activeChatCharacter_;
    QString activeChatCharacterDisplay_;
    QString activeChatConversationId_;
    QString activeChatPhase_;
    QString activeGroupKey_;
    QJsonArray activeGroupMembers_;
    QStringList groupSpeakerQueue_;
    QStringList groupSpokenNames_;
    QJsonArray pendingChatAttachments_;
    qint64 activeChatRequestId_ = 0;
    int chatMessageLimit_ = 200;
    bool updatingChatControls_ = false;
    bool draftingNewConversation_ = false;
    bool groupSequenceActive_ = false;
    QJsonObject historyFiltersState_;
    qint64 historyTotal_ = -1;
    int historyOffset_ = 0;
    bool historyHasMore_ = false;
    qfw::LineEdit* historyKeywordEdit_ = nullptr;
    qfw::LineEdit* historyDateFromEdit_ = nullptr;
    qfw::LineEdit* historyDateToEdit_ = nullptr;
    qfw::ComboBox* historyCharacterComboBox_ = nullptr;
    qfw::ComboBox* historyUserComboBox_ = nullptr;
    qfw::ComboBox* historyRoleComboBox_ = nullptr;
    qfw::ComboBox* historySourceComboBox_ = nullptr;
    qfw::PrimaryPushButton* historySearchButton_ = nullptr;
    qfw::PushButton* historyResetButton_ = nullptr;
    qfw::ListWidget* historyList_ = nullptr;
    qfw::PushButton* historyLoadMoreButton_ = nullptr;
    qfw::CaptionLabel* historyStatusLabel_ = nullptr;
    QJsonObject statisticsSnapshot_;
    qfw::ComboBox* statisticsRangeComboBox_ = nullptr;
    qfw::ComboBox* statisticsCharacterComboBox_ = nullptr;
    qfw::PushButton* statisticsRefreshButton_ = nullptr;
    qfw::BodyLabel* statisticsMessagesLabel_ = nullptr;
    qfw::BodyLabel* statisticsUsageTodayLabel_ = nullptr;
    qfw::BodyLabel* statisticsUsageWeekLabel_ = nullptr;
    qfw::BodyLabel* statisticsUsageAllLabel_ = nullptr;
    qfw::TableWidget* statisticsRelationshipTable_ = nullptr;
    qfw::TableWidget* statisticsCharacterTable_ = nullptr;
    qfw::TableWidget* statisticsDailyTable_ = nullptr;
    qfw::TableWidget* statisticsHeatmapTable_ = nullptr;
    qfw::CaptionLabel* statisticsStatusLabel_ = nullptr;
    qfw::ComboBox* dataCategoryComboBox_ = nullptr;
    qfw::PrimaryPushButton* dataExportButton_ = nullptr;
    qfw::PushButton* dataImportButton_ = nullptr;
    qfw::PushButton* databaseExportButton_ = nullptr;
    qfw::PushButton* databaseImportButton_ = nullptr;
    qfw::CaptionLabel* dataStatusLabel_ = nullptr;
    qfw::SwitchButton* attachmentAutoCleanupSwitch_ = nullptr;
    qfw::SpinBox* attachmentRetentionDaysSpinBox_ = nullptr;
    qfw::PushButton* attachmentSavePolicyButton_ = nullptr;
    qfw::PushButton* attachmentRefreshButton_ = nullptr;
    qfw::PushButton* attachmentCleanupOldButton_ = nullptr;
    qfw::PushButton* attachmentClearAllButton_ = nullptr;
    qfw::BodyLabel* attachmentStatsLabel_ = nullptr;
    bool attachmentStartupCleanupRan_ = false;
    QTimer reminderTimer_;
    QJsonObject reminderState_;
    qfw::ComboBox* reminderDisplayModeComboBox_ = nullptr;
    qfw::TimePicker* alarmTimePicker_ = nullptr;
    qfw::ComboBox* alarmRepeatComboBox_ = nullptr;
    QWidget* alarmCustomDaysWidget_ = nullptr;
    QList<qfw::CheckBox*> alarmWeekdayCheckBoxes_;
    qfw::LineEdit* alarmDescriptionEdit_ = nullptr;
    qfw::ComboBox* alarmCharacterComboBox_ = nullptr;
    qfw::PrimaryPushButton* addAlarmButton_ = nullptr;
    qfw::SpinBox* pomodoroRepeatSpinBox_ = nullptr;
    qfw::LineEdit* pomodoroDescriptionEdit_ = nullptr;
    qfw::ComboBox* pomodoroCharacterComboBox_ = nullptr;
    qfw::PrimaryPushButton* addPomodoroButton_ = nullptr;
    qfw::ListWidget* reminderList_ = nullptr;
    qfw::PushButton* toggleReminderButton_ = nullptr;
    qfw::PushButton* deleteReminderButton_ = nullptr;
    qfw::CaptionLabel* reminderStatusLabel_ = nullptr;
    QJsonObject llmSettings_;
    qfw::ComboBox* llmProfileComboBox_ = nullptr;
    qfw::LineEdit* llmProfileNameEdit_ = nullptr;
    qfw::PushButton* llmApplyProfileButton_ = nullptr;
    qfw::PrimaryPushButton* llmSaveProfileButton_ = nullptr;
    qfw::PushButton* llmDeleteProfileButton_ = nullptr;
    qfw::LineEdit* llmApiUrlEdit_ = nullptr;
    qfw::LineEdit* llmApiKeyEdit_ = nullptr;
    qfw::CheckBox* llmClearApiKeyCheckBox_ = nullptr;
    qfw::LineEdit* llmModelIdEdit_ = nullptr;
    qfw::ComboBox* llmPrimaryDiscoveredModelsComboBox_ = nullptr;
    qfw::PushButton* llmPrimaryFetchModelsButton_ = nullptr;
    qfw::PushButton* llmPrimaryTestButton_ = nullptr;
    qfw::ComboBox* llmApiModeComboBox_ = nullptr;
    qfw::ComboBox* llmThinkingComboBox_ = nullptr;
    qfw::LineEdit* llmAuxApiUrlEdit_ = nullptr;
    qfw::LineEdit* llmAuxApiKeyEdit_ = nullptr;
    qfw::CheckBox* llmClearAuxApiKeyCheckBox_ = nullptr;
    qfw::LineEdit* llmAuxModelIdEdit_ = nullptr;
    qfw::ComboBox* llmAuxDiscoveredModelsComboBox_ = nullptr;
    qfw::PushButton* llmAuxFetchModelsButton_ = nullptr;
    qfw::PushButton* llmAuxTestButton_ = nullptr;
    qfw::ComboBox* llmAuxThinkingComboBox_ = nullptr;
    qfw::SwitchButton* llmAuxVisionSwitch_ = nullptr;
    qfw::SwitchButton* llmOutfitRecognitionSwitch_ = nullptr;
    qfw::SpinBox* llmHistoryLimitSpinBox_ = nullptr;
    qfw::SpinBox* llmCompactHistoryLimitSpinBox_ = nullptr;
    qfw::SwitchButton* llmCrossChatHistorySwitch_ = nullptr;
    qfw::SwitchButton* llmCustomPromptSwitch_ = nullptr;
    qfw::PlainTextEdit* llmCustomPromptEdit_ = nullptr;
    qfw::PrimaryPushButton* llmSaveButton_ = nullptr;
    qfw::CaptionLabel* llmSettingsStatusLabel_ = nullptr;
    qint64 activeProviderRequestId_ = 0;
    QJsonObject memorySnapshot_;
    bool updatingMemoryControls_ = false;
    qfw::ComboBox* memoryCharacterComboBox_ = nullptr;
    QWidget* memoryRelationshipCard_ = nullptr;
    qfw::BodyLabel* memoryAffectionLabel_ = nullptr;
    qfw::BodyLabel* memoryTrustLabel_ = nullptr;
    qfw::BodyLabel* memoryFamiliarityLabel_ = nullptr;
    qfw::BodyLabel* memoryMoodLabel_ = nullptr;
    qfw::ListWidget* memoryList_ = nullptr;
    qfw::ComboBox* memoryKindComboBox_ = nullptr;
    qfw::SpinBox* memoryImportanceSpinBox_ = nullptr;
    qfw::PlainTextEdit* memoryContentEdit_ = nullptr;
    qfw::PushButton* memoryNewButton_ = nullptr;
    qfw::PrimaryPushButton* memorySaveButton_ = nullptr;
    qfw::PushButton* memoryDeleteButton_ = nullptr;
    qfw::CaptionLabel* memoryStatusLabel_ = nullptr;
    QJsonObject userProfilesState_;
    bool updatingUserProfileControls_ = false;
    qfw::ComboBox* userProfileComboBox_ = nullptr;
    qfw::LineEdit* userProfileNameEdit_ = nullptr;
    qfw::LineEdit* userProfileColorEdit_ = nullptr;
    qfw::LineEdit* userProfileAvatarPathEdit_ = nullptr;
    qfw::PushButton* userProfileChooseAvatarButton_ = nullptr;
    qfw::PushButton* userProfileActivateButton_ = nullptr;
    qfw::PushButton* userProfileNewButton_ = nullptr;
    qfw::PrimaryPushButton* userProfileSaveButton_ = nullptr;
    qfw::PushButton* userProfileDeleteButton_ = nullptr;
    qfw::CaptionLabel* userProfileStatusLabel_ = nullptr;
    QJsonObject personaSettingsState_;
    bool updatingPersonaControls_ = false;
    qfw::ComboBox* povModeComboBox_ = nullptr;
    qfw::PlainTextEdit* povCustomPromptEdit_ = nullptr;
    qfw::ComboBox* povPersonaComboBox_ = nullptr;
    qfw::ComboBox* povRoleCharacterComboBox_ = nullptr;
    qfw::PushButton* povSavePersonaButton_ = nullptr;
    qfw::PushButton* povDeletePersonaButton_ = nullptr;
    qfw::PrimaryPushButton* povSaveButton_ = nullptr;
    qfw::ComboBox* characterPersonaCharacterComboBox_ = nullptr;
    qfw::ComboBox* characterPersonaPresetComboBox_ = nullptr;
    qfw::LineEdit* characterPersonaTitleEdit_ = nullptr;
    qfw::PlainTextEdit* characterPersonaPromptEdit_ = nullptr;
    qfw::PlainTextEdit* characterPersonaDefaultPreview_ = nullptr;
    qfw::PushButton* characterPersonaImportButton_ = nullptr;
    qfw::PushButton* characterPersonaSaveNewButton_ = nullptr;
    qfw::PrimaryPushButton* characterPersonaSaveButton_ = nullptr;
    qfw::PushButton* characterPersonaDeleteButton_ = nullptr;
    qfw::CaptionLabel* personaStatusLabel_ = nullptr;
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
