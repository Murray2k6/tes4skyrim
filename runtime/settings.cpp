#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <algorithm>
#include <cmath>
#include <cstring>

namespace {
int difficultyLevel(RE::StaticFunctionTag*) {
    const auto player = RE::PlayerCharacter::GetSingleton();
    return player ? std::clamp(player->GetGameStatsData().difficulty, 0, 5) : 2;
}
RE::Setting* setting(RE::BSFixedString name) {
    auto collection = RE::GameSettingCollection::GetSingleton();
    auto result = collection ? collection->GetSetting(name.c_str()) : nullptr;
    if (!result) SKSE::log::warn("TES4 game setting is unavailable: {}", name.c_str());
    return result;
}
float numeric(RE::StaticFunctionTag*, RE::BSFixedString name) {
    const auto value = setting(name);
    if (!value) return 0;
    switch (value->GetType()) {
    case RE::Setting::Type::kFloat: return value->data.f;
    case RE::Setting::Type::kSignedInteger: return static_cast<float>(value->data.i);
    case RE::Setting::Type::kUnsignedInteger: return static_cast<float>(value->data.u);
    default: return 0;
    }
}
bool setNumeric(RE::StaticFunctionTag*, RE::BSFixedString name, float number) {
    auto value = setting(name);
    if (!value || !std::isfinite(number)) return false;
    switch (value->GetType()) {
    case RE::Setting::Type::kFloat: value->data.f = number; break;
    case RE::Setting::Type::kSignedInteger:
        value->data.i = static_cast<std::int32_t>(std::clamp<double>(number, INT32_MIN, INT32_MAX)); break;
    case RE::Setting::Type::kUnsignedInteger:
        value->data.u = static_cast<std::uint32_t>(std::clamp<double>(number, 0, UINT32_MAX)); break;
    default: return false;
    }
    return true;
}
std::string text(RE::StaticFunctionTag*, RE::BSFixedString name) {
    const auto value = setting(name);
    return value && value->GetType() == RE::Setting::Type::kString ? value->GetString() : "";
}
char* copy(std::string_view value) {
    auto result = static_cast<char*>(RE::malloc(value.size() + 1));
    if (result) {
        std::memcpy(result, value.data(), value.size());
        result[value.size()] = 0;
    }
    return result;
}
bool setText(RE::StaticFunctionTag*, RE::BSFixedString formatted) {
    const std::string_view input(formatted.c_str());
    const auto pipe = input.find('|');
    if (pipe == std::string_view::npos) return false;
    auto value = setting(std::string(input.substr(0, pipe)).c_str());
    if (!value || value->GetType() != RE::Setting::Type::kString) return false;
    auto replacement = copy(input.substr(pipe + 1));
    if (!replacement) return false;
    // SKSE's Setting::SetString ownership convention: uppercase S marks
    // heap-owned name and text; static lowercase-s storage must not be freed.
    if (!value->IsManaged()) {
        auto name = copy(value->name);
        if (!name) { RE::free(replacement); return false; }
        name[0] = 'S';
        value->name = name;
    } else RE::free(value->data.s);
    value->data.s = replacement;
    return true;
}
}

bool RegisterSettings(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("GetDifficultyLevel", "TES4Runtime", difficultyLevel);
    vm->RegisterFunction("GetNumericGameSetting", "TES4Runtime", numeric);
    vm->RegisterFunction("SetNumericGameSetting", "TES4Runtime", setNumeric);
    vm->RegisterFunction("GetStringGameSetting", "TES4Runtime", text);
    vm->RegisterFunction("SetStringGameSetting", "TES4Runtime", setText);
    return true;
}
