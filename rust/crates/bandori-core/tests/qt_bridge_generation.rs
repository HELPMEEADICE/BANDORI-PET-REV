use cxx_qt_gen::{
    CppFragment, CxxQtItem, GeneratedCppBlocks, GeneratedOpt, GeneratedRustBlocks, Parser,
    parse_qt_file, self_inlining::qualify_self_types, write_cpp,
};
use std::path::PathBuf;

#[test]
fn backend_bridge_generates_without_a_qt_sdk() {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let bridge = manifest_dir.join("../bandori-qt-bridge/src/backend.rs");
    let file = parse_qt_file(bridge).expect("CXX-Qt bridge should be valid Rust syntax");
    let module = file
        .items
        .into_iter()
        .find_map(|item| match item {
            CxxQtItem::CxxQt(module) => Some(*module),
            _ => None,
        })
        .expect("backend.rs should contain a CXX-Qt module");
    let mut parser = Parser::from(module).expect("CXX-Qt bridge should pass semantic parsing");
    qualify_self_types(&mut parser).expect("Self types should resolve to Backend");
    GeneratedRustBlocks::from(&parser).expect("Rust bridge generation should succeed");
    let cpp = GeneratedCppBlocks::from(&parser, &GeneratedOpt::default())
        .expect("C++ bridge generation should succeed");
    let CppFragment::Pair { header, .. } = write_cpp(&cpp, "backend") else {
        panic!("CXX-Qt backend should generate a header/source pair");
    };

    for symbol in [
        "getStatus",
        "getConfigSummary",
        "getModelCatalogJson",
        "getRuntimeConfigJson",
        "getChatConversationsJson",
        "getChatMessagesJson",
        "getChatActiveConversationId",
        "getChatTurnJson",
        "getChatRequestJson",
        "getChatImportedAttachmentsJson",
        "getReminderEventsJson",
        "getReminderStateJson",
        "getLlmSettingsJson",
        "getTtsSettingsJson",
        "getAsrSettingsJson",
        "getScreenAwarenessSettingsJson",
        "getIntegrationSettingsJson",
        "getIntegrationStatusJson",
        "getSpecialEventsJson",
        "getMemorySnapshotJson",
        "getUserProfilesJson",
        "getPersonaSettingsJson",
        "getHistoryFiltersJson",
        "getHistoryResultJson",
        "getStatisticsSnapshotJson",
        "getDataOperationJson",
        "getAttachmentManagementJson",
        "getChatHasOlderMessages",
        "reloadState",
        "saveNativeSettings",
        "tickReminders",
        "loadReminderState",
        "mutateReminder",
        "loadLlmSettings",
        "saveLlmSettings",
        "mutateLlmProfile",
        "startProviderOperation",
        "cancelProviderOperation",
        "loadTtsSettings",
        "saveTtsSettings",
        "startTtsSynthesis",
        "cancelTtsSynthesis",
        "loadAsrSettings",
        "saveAsrSettings",
        "startAsrTranscription",
        "cancelAsrTranscription",
        "loadScreenAwarenessSettings",
        "saveScreenAwarenessSettings",
        "startScreenAwareness",
        "cancelScreenAwareness",
        "loadIntegrationSettings",
        "saveIntegrationSettings",
        "startIntegrationServices",
        "stopIntegrationServices",
        "loadSpecialEvents",
        "loadMemoryState",
        "mutateMemory",
        "loadUserProfiles",
        "mutateUserProfile",
        "loadPersonaSettings",
        "mutatePersonaSettings",
        "loadHistoryFilters",
        "searchHistory",
        "loadStatistics",
        "exportSettingsPackage",
        "importSettingsPackage",
        "exportChatDatabase",
        "importChatDatabase",
        "loadAttachmentStats",
        "cleanupChatAttachments",
        "loadChatState",
        "loadGroupChatState",
        "prepareChatTurn",
        "prepareGroupChatTurn",
        "importChatAttachments",
        "discardChatAttachments",
        "deleteChatConversation",
        "deleteGroupChatConversation",
        "buildChatRequest",
        "buildGroupPlanRequest",
        "resolveGroupPlan",
        "buildGroupChatRequest",
        "saveChatAssistant",
        "saveGroupChatAssistant",
        "startChatStream",
        "startGroupPlanStream",
        "startGroupChatStream",
        "finishGroupChatTurn",
        "cancelChatStream",
        "chatStreamEvent",
        "chatMemoryEvent",
        "providerOperationEvent",
        "ttsAudioEvent",
        "asrTranscriptionEvent",
        "screenAwarenessEvent",
        "integrationEvent",
    ] {
        assert!(header.contains(symbol), "generated header missed {symbol}");
    }
}
