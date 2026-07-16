#pragma once

extern "C" {

const char* bandori_config_last_error();
bool bandori_config_save_pet_state(const char* configPath, const char* payloadJson);
bool bandori_config_migrate_legacy_data(const char* legacyRoot, const char* nativeRoot);

}
