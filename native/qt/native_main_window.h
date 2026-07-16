#pragma once

#include <QAudioFormat>
#include <QByteArray>
#include <QJsonArray>
#include <QJsonObject>
#include <QList>
#include <QPoint>
#include <QQueue>
#include <QSet>
#include <QString>
#include <QStringList>
#include <QTimer>

#include <optional>

#include <bandori_qt_bridge/src/backend.cxxqt.h>
#include <qtfluentwidgets.h>

#include "pet_process_supervisor.h"

class QAction;
class QAudioOutput;
class QAudioSource;
class QCloseEvent;
class QIODevice;
class QMediaPlayer;
class QMoveEvent;
class QResizeEvent;
class QSystemTrayIcon;
class QTemporaryFile;
class QTextBrowser;
class QWebSocket;

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
        QString dataRoot,
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
    QWidget* createTtsSettingsPage();
    QWidget* createAsrSettingsPage();
    QWidget* createScreenAwarenessPage();
    QWidget* createIntegrationPage();
    QWidget* createSettingsPage();
    bool reloadBackendState();
    void syncSettingsControls();
    void saveNativeSettings();
    void restoreNativeWindowGeometry();
    void scheduleNativeWindowGeometrySave();
    void persistNativeWindowGeometry();
    bool applyNativeAutoStart(bool enabled, QString* error = nullptr);
    void reconcileNativeAutoStart();
    void applyTheme(const QString& mode);
    void applyBackendState();
    void populateModelList();
    void updateModelDetails();
    void populateClickMotionProfiles();
    void syncClickMotionProfileControls();
    bool mutateSelectedClickMotionProfile(const QString& operation, const QString& name);
    void applySelectedClickMotionProfile();
    void saveCurrentClickMotionProfile();
    void deleteSelectedClickMotionProfile();
    void broadcastClickMotionSettings(const ModelCatalogItem& model);
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
    void pollNativeSpecialEvents();
    void scheduleNativeSpecialEventPoll(int retryMilliseconds = 0);
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
    void loadNativeTtsSettings();
    void syncNativeTtsSettingsControls();
    bool saveNativeTtsSettings();
    void enqueueNativeTts(
        const QString& text,
        const QString& character,
        bool force = false,
        double speedFactor = 1.0);
    void startNextNativeTtsSynthesis();
    void handleNativeTtsAudio(const QString& payloadJson, const QByteArray& audio);
    void playNextNativeTtsAudio();
    void stopNativeTts();
    void updateNativeTtsLipSync();
    void loadNativeAsrSettings();
    void syncNativeAsrSettingsControls();
    bool saveNativeAsrSettings();
    void toggleNativeAsrRecording(bool forTest);
    void startNativeAsrRecording(bool forTest);
    void collectNativeAsrAudio();
    void stopNativeAsrRecording(bool submit);
    void startNativeAsrTranscription(const QByteArray& wavAudio, bool force, bool forTest);
    void handleNativeAsrEvent(const QString& payloadJson);
    void stopNativeAsr();
    void populateNativeScreenAwarenessCharacters();
    void loadNativeScreenAwarenessSettings();
    void syncNativeScreenAwarenessControls();
    bool saveNativeScreenAwarenessSettings();
    void scheduleNativeScreenAwareness();
    void triggerNativeScreenAwareness(bool force = false);
    QString chooseNativeScreenAwarenessCharacter() const;
    QByteArray captureNativeDesktop(QJsonObject* metadata, int maximumWidth = -1) const;
    QJsonObject nativeForegroundDesktopState() const;
    void handleNativeComputerTool(
        qint64 requestId,
        const QString& toolName,
        const QString& argumentsJson);
    void finishNativeComputerTool(
        qint64 requestId,
        bool succeeded,
        const QString& content,
        bool includeScreenshot,
        bool screenshotRequired = false);
    QPoint mapNativeComputerPoint(int screenshotX, int screenshotY) const;
    void handleNativeScreenAwarenessEvent(const QString& payloadJson);
    void stopNativeScreenAwareness();
    void loadNativeIntegrationSettings();
    void syncNativeIntegrationControls();
    bool saveNativeIntegrationSettings();
    bool restartNativeIntegrationServices();
    void stopNativeIntegrationServices();
    void handleNativeIntegrationEvent(const QString& payloadJson);
    void startNativeNapcat();
    void stopNativeNapcat();
    void connectNativeNapcat();
    void scheduleNativeNapcatReconnect();
    void handleNativeNapcatMessage(const QString& message);
    void handleNativeNapcatReply(const QString& payloadJson);
    bool sendNativeNapcatReply(
        const QJsonObject& rawEvent,
        const QString& text,
        bool mentionSender);
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
    double dispatchNativeEmotionBehavior(
        const QString& text,
        const QString& character,
        const QJsonArray& actions);
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
    QString nativeDatabasePath() const;

protected:
    void closeEvent(QCloseEvent* event) override;
    void moveEvent(QMoveEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;

private:
    QString projectRoot_;
    QString userModelsRoot_;
    QString dataRoot_;
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
    qfw::ComboBox* clickMotionProfileComboBox_ = nullptr;
    qfw::LineEdit* clickMotionProfileNameEdit_ = nullptr;
    qfw::PushButton* clickMotionApplyButton_ = nullptr;
    qfw::PushButton* clickMotionSaveButton_ = nullptr;
    qfw::PushButton* clickMotionDeleteButton_ = nullptr;
    qfw::CaptionLabel* clickMotionStatusLabel_ = nullptr;
    bool updatingClickMotionControls_ = false;
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
    qfw::PushButton* chatAsrButton_ = nullptr;
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
    QTimer nativeWindowGeometryTimer_;
    QTimer specialEventTimer_;
    QString lastSpecialEventDate_;
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
    qfw::SwitchButton* llmWebSearchSwitch_ = nullptr;
    qfw::ComboBox* llmWebSearchEngineComboBox_ = nullptr;
    qfw::SwitchButton* llmWebSearchSourcesSwitch_ = nullptr;
    qfw::SwitchButton* llmWebFetchSwitch_ = nullptr;
    qfw::SwitchButton* llmMcpEnabledSwitch_ = nullptr;
    qfw::SwitchButton* llmMcpNativeSwitch_ = nullptr;
    qfw::PlainTextEdit* llmMcpServersEdit_ = nullptr;
    qfw::SwitchButton* computerUseEnabledSwitch_ = nullptr;
    qfw::SwitchButton* computerUseAutoDetectSwitch_ = nullptr;
    qfw::SwitchButton* computerUseSendScreenshotsSwitch_ = nullptr;
    qfw::SpinBox* computerUseMaxScreenshotWidthSpinBox_ = nullptr;
    qfw::SwitchButton* computerUseAllowScreenshotSwitch_ = nullptr;
    qfw::SwitchButton* computerUseAllowMouseSwitch_ = nullptr;
    qfw::SwitchButton* computerUseAllowKeyboardSwitch_ = nullptr;
    qfw::SwitchButton* computerUseAllowClipboardSwitch_ = nullptr;
    qfw::SwitchButton* computerUseAllowWaitSwitch_ = nullptr;
    QJsonObject computerScreenshotMetrics_;
    QSet<qint64> pendingComputerWaitRequests_;
    qfw::SwitchButton* llmCustomPromptSwitch_ = nullptr;
    qfw::PlainTextEdit* llmCustomPromptEdit_ = nullptr;
    qfw::PrimaryPushButton* llmSaveButton_ = nullptr;
    qfw::CaptionLabel* llmSettingsStatusLabel_ = nullptr;
    QJsonObject ttsSettings_;
    qfw::SwitchButton* ttsEnabledSwitch_ = nullptr;
    qfw::LineEdit* ttsApiUrlEdit_ = nullptr;
    qfw::ComboBox* ttsLanguageComboBox_ = nullptr;
    qfw::ComboBox* ttsReferenceCharacterComboBox_ = nullptr;
    qfw::DoubleSpinBox* ttsTemperatureSpinBox_ = nullptr;
    qfw::SwitchButton* ttsStreamingSwitch_ = nullptr;
    qfw::SwitchButton* ttsTranslateSwitch_ = nullptr;
    qfw::PlainTextEdit* ttsTestTextEdit_ = nullptr;
    qfw::PrimaryPushButton* ttsSaveButton_ = nullptr;
    qfw::PushButton* ttsTestButton_ = nullptr;
    qfw::PushButton* ttsStopButton_ = nullptr;
    qfw::CaptionLabel* ttsStatusLabel_ = nullptr;
    QMediaPlayer* ttsMediaPlayer_ = nullptr;
    QAudioOutput* ttsAudioOutput_ = nullptr;
    QQueue<QTemporaryFile*> ttsAudioQueue_;
    QQueue<QJsonObject> ttsSynthesisQueue_;
    QTemporaryFile* currentTtsAudioFile_ = nullptr;
    QTimer ttsLipSyncTimer_;
    qint64 activeTtsRequestId_ = 0;
    QString ttsPlayingCharacter_;
    QJsonObject asrSettings_;
    qfw::SwitchButton* asrEnabledSwitch_ = nullptr;
    qfw::LineEdit* asrApiUrlEdit_ = nullptr;
    qfw::LineEdit* asrApiKeyEdit_ = nullptr;
    qfw::CheckBox* asrClearApiKeyCheckBox_ = nullptr;
    qfw::LineEdit* asrModelIdEdit_ = nullptr;
    qfw::ComboBox* asrLanguageComboBox_ = nullptr;
    qfw::ComboBox* asrInsertModeComboBox_ = nullptr;
    qfw::SwitchButton* asrAutoSendSwitch_ = nullptr;
    qfw::SpinBox* asrMaxRecordSecondsSpinBox_ = nullptr;
    qfw::PlainTextEdit* asrTestResultEdit_ = nullptr;
    qfw::PrimaryPushButton* asrSaveButton_ = nullptr;
    qfw::PushButton* asrTestButton_ = nullptr;
    qfw::PushButton* asrCancelButton_ = nullptr;
    qfw::CaptionLabel* asrStatusLabel_ = nullptr;
    QAudioSource* asrAudioSource_ = nullptr;
    QIODevice* asrAudioDevice_ = nullptr;
    QAudioFormat asrAudioFormat_;
    QByteArray asrRawAudio_;
    QTimer asrRecordLimitTimer_;
    qint64 activeAsrRequestId_ = 0;
    bool asrRecording_ = false;
    bool asrAudioLimitExceeded_ = false;
    bool asrRecordingForTest_ = false;
    bool asrRequestForTest_ = false;
    QJsonObject screenAwarenessSettings_;
    qfw::SwitchButton* screenAwarenessEnabledSwitch_ = nullptr;
    qfw::SpinBox* screenAwarenessIntervalSpinBox_ = nullptr;
    qfw::ComboBox* screenAwarenessCharacterComboBox_ = nullptr;
    qfw::SpinBox* screenAwarenessMaxWidthSpinBox_ = nullptr;
    qfw::ComboBox* screenAwarenessModelModeComboBox_ = nullptr;
    qfw::ComboBox* screenAwarenessDisplayModeComboBox_ = nullptr;
    qfw::SwitchButton* screenAwarenessIncludeProcessSwitch_ = nullptr;
    qfw::SwitchButton* screenAwarenessIncludeTitleSwitch_ = nullptr;
    qfw::PrimaryPushButton* screenAwarenessSaveButton_ = nullptr;
    qfw::PushButton* screenAwarenessTestButton_ = nullptr;
    qfw::PushButton* screenAwarenessCancelButton_ = nullptr;
    qfw::CaptionLabel* screenAwarenessStatusLabel_ = nullptr;
    QTimer screenAwarenessTimer_;
    qint64 activeScreenAwarenessRequestId_ = 0;
    QJsonObject integrationSettings_;
    QJsonObject integrationStatus_;
    QJsonObject napcatSettings_;
    qfw::SwitchButton* chatIntegrationEnabledSwitch_ = nullptr;
    qfw::SpinBox* chatIntegrationPortSpinBox_ = nullptr;
    qfw::SwitchButton* chatIntegrationOverlaySwitch_ = nullptr;
    qfw::SwitchButton* chatIntegrationContextSwitch_ = nullptr;
    qfw::LineEdit* chatIntegrationTokenEdit_ = nullptr;
    qfw::CheckBox* chatIntegrationClearTokenCheckBox_ = nullptr;
    qfw::SwitchButton* aiStatusEnabledSwitch_ = nullptr;
    qfw::SwitchButton* compactAiWindowSwitch_ = nullptr;
    qfw::SpinBox* compactAiWindowOpacitySpinBox_ = nullptr;
    qfw::SpinBox* compactAiWindowFontSizeSpinBox_ = nullptr;
    qfw::LineEdit* compactAiWindowBackgroundEdit_ = nullptr;
    qfw::LineEdit* compactAiWindowTextEdit_ = nullptr;
    qfw::SwitchButton* aiEventOverlaySwitch_ = nullptr;
    qfw::SpinBox* aiStatusPortSpinBox_ = nullptr;
    qfw::LineEdit* aiStatusTokenEdit_ = nullptr;
    qfw::CheckBox* aiStatusClearTokenCheckBox_ = nullptr;
    qfw::SwitchButton* napcatEnabledSwitch_ = nullptr;
    qfw::LineEdit* napcatUrlEdit_ = nullptr;
    qfw::LineEdit* napcatTokenEdit_ = nullptr;
    qfw::CheckBox* napcatClearTokenCheckBox_ = nullptr;
    qfw::SwitchButton* napcatAutoReplySwitch_ = nullptr;
    qfw::SwitchButton* napcatReplyPrivateSwitch_ = nullptr;
    qfw::SwitchButton* napcatGroupAtOnlySwitch_ = nullptr;
    qfw::SwitchButton* napcatMentionSenderSwitch_ = nullptr;
    qfw::LineEdit* napcatReplyCharacterEdit_ = nullptr;
    qfw::ComboBox* napcatSavePolicyComboBox_ = nullptr;
    qfw::ComboBox* napcatGroupRetentionModeComboBox_ = nullptr;
    qfw::SpinBox* napcatGroupRetentionDaysSpinBox_ = nullptr;
    qfw::ComboBox* napcatPrivateRetentionModeComboBox_ = nullptr;
    qfw::SpinBox* napcatPrivateRetentionDaysSpinBox_ = nullptr;
    qfw::CaptionLabel* napcatStatusLabel_ = nullptr;
    qfw::PrimaryPushButton* integrationSaveButton_ = nullptr;
    qfw::PushButton* integrationStopButton_ = nullptr;
    qfw::CaptionLabel* integrationStatusLabel_ = nullptr;
    QWebSocket* napcatSocket_ = nullptr;
    QTimer napcatReconnectTimer_;
    bool napcatStopping_ = true;
    QSet<qint64> activeNapcatReplyIds_;
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
    qfw::SwitchButton* gameTopmostSwitch_ = nullptr;
    qfw::SwitchButton* obsWindowCaptureSwitch_ = nullptr;
    qfw::SwitchButton* hideLive2dModelSwitch_ = nullptr;
    qfw::SwitchButton* vsyncSwitch_ = nullptr;
    qfw::ComboBox* qualityComboBox_ = nullptr;
    qfw::SpinBox* scaleSpinBox_ = nullptr;
    qfw::SwitchButton* idleActionsSwitch_ = nullptr;
    qfw::SwitchButton* randomActionsSwitch_ = nullptr;
    qfw::SwitchButton* dragLockedSwitch_ = nullptr;
    qfw::SwitchButton* moveTogetherSwitch_ = nullptr;
    qfw::SwitchButton* headTrackingSwitch_ = nullptr;
    qfw::SwitchButton* mutualGazeSwitch_ = nullptr;
    qfw::SwitchButton* emotionBehaviorSwitch_ = nullptr;
    qfw::SwitchButton* autoStartSwitch_ = nullptr;
    qfw::SwitchButton* birthdayNotificationsSwitch_ = nullptr;
    qfw::ComboBox* themeComboBox_ = nullptr;
    qfw::PrimaryPushButton* saveSettingsButton_ = nullptr;
    QSystemTrayIcon* trayIcon_ = nullptr;
    QAction* startTrayAction_ = nullptr;
    QAction* stopTrayAction_ = nullptr;
    bool exitRequested_ = false;
    bool trayHintShown_ = false;
    bool restoringNativeWindowGeometry_ = false;
};

}  // namespace bandori
