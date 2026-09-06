#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <algorithm>
#include <Windows.h>
#include <cwctype>
#include <cstdlib>
#include <cstdio>
#include <filesystem>

namespace {
using Tag = RE::StaticFunctionTag;

bool fileExists(Tag*, std::string name) {
    std::replace(name.begin(), name.end(), '\\', '/');
    std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) { return std::tolower(c); });
    if (name.starts_with("data/")) name.erase(0, 5);
    const auto path = std::filesystem::u8path(name);
    if (path.is_absolute()) return false;
    for (const auto& part : path) if (part == "..") return false;
    std::error_code error;
    if (std::filesystem::is_regular_file(std::filesystem::path("Data") / path, error)) return true;
    if (RE::BSResourceNiBinaryStream(name).good()) return true;
    // Record and mesh conversion put TES4 art in a separate asset namespace.
    for (const auto prefix : {"meshes/", "textures/"}) {
        if (name.starts_with(prefix)) {
            name.insert(std::char_traits<char>::length(prefix), "tes4/");
            return RE::BSResourceNiBinaryStream(name).good();
        }
    }
    return false;
}

std::wstring wide(RE::BSFixedString text) {
    const auto size = MultiByteToWideChar(CP_UTF8, 0, text.c_str(), -1, nullptr, 0);
    if (!size) return {};
    std::wstring result(size, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, text.c_str(), -1, result.data(), size);
    result.pop_back();
    return result;
}
int stringSearch(Tag*, RE::BSFixedString text, RE::BSFixedString needle, int start,
                 int length, bool caseSensitive, bool count) {
    auto source = wide(text);
    auto target = wide(needle);
    if (start < 0 || static_cast<std::size_t>(start) >= source.size()) return count ? 0 : -1;
    source = source.substr(start, length < 0 ? std::wstring::npos : length);
    if (!caseSensitive) {
        std::transform(source.begin(), source.end(), source.begin(), std::towlower);
        std::transform(target.begin(), target.end(), target.begin(), std::towlower);
    }
    auto pos = source.find(target);
    if (!count) return pos == std::wstring::npos ? -1 : static_cast<int>(pos) + start;
    if (target.empty()) return 0;
    int result = 0;
    while (pos != std::wstring::npos) {
        ++result;
        pos = source.find(target, pos + target.size());
    }
    return result;
}
int stringLength(Tag*, RE::BSFixedString text) { return static_cast<int>(wide(text).size()); }
std::string utf8(const std::wstring& value) {
    const auto size = WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
    std::string result(size, '\0');
    WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), result.data(), size, nullptr, nullptr);
    return result;
}
std::string stringSlice(Tag*, RE::BSFixedString text, int start, int length) {
    auto value = wide(text);
    if (start < 0 || static_cast<std::size_t>(start) >= value.size()) return {};
    return utf8(value.substr(start, length < 0 ? std::wstring::npos : length));
}
std::vector<std::string> stringEdit(Tag*, RE::BSFixedString text, RE::BSFixedString formatted,
        RE::BSFixedString operation, int start, int length, bool caseSensitive, int limit) {
    auto value = wide(text);
    const auto edit = wide(formatted);
    const std::string_view op(operation.c_str());
    int count = 0;
    if (op == "set") value = edit;
    else if (op == "insert") {
        if (start >= 0 && static_cast<std::size_t>(start) <= value.size()) value.insert(start, edit);
    } else if (op == "erase") {
        if (start >= 0 && static_cast<std::size_t>(start) < value.size())
            value.erase(start, length < 0 ? std::wstring::npos : length);
    } else if (op == "replace") {
        const auto separator = edit.find(L'|');
        if (separator == std::wstring::npos) count = -1;
        else if (start >= 0 && static_cast<std::size_t>(start) < value.size()) {
            const auto needle = edit.substr(0, separator);
            const auto replacement = edit.substr(separator + 1);
            const auto size = length < 0 ? value.size() - start : std::min<std::size_t>(length, value.size() - start);
            auto part = value.substr(start, size);
            std::size_t cursor = 0;
            // A zero-width search has no finite replace-all result.
            while (!needle.empty() && (limit < 0 || count < limit) && cursor <= part.size()) {
                const auto found = std::search(part.begin() + cursor, part.end(), needle.begin(), needle.end(),
                    [caseSensitive](wchar_t a, wchar_t b) { return caseSensitive ? a == b : std::towlower(a) == std::towlower(b); });
                if (found == part.end()) break;
                cursor = static_cast<std::size_t>(found - part.begin());
                part.replace(cursor, needle.size(), replacement);
                cursor += replacement.size();
                ++count;
            }
            value.replace(start, size, part);
        }
    }
    return {utf8(value), std::to_string(count)};
}
std::string stringAt(Tag*, RE::BSFixedString text, int index) {
    auto value = wide(text);
    if (index < 0) index += static_cast<int>(value.size());
    if (index < 0 || index >= value.size()) return {};
    char result[4];
    const auto size = WideCharToMultiByte(CP_UTF8, 0, &value[index], 1, result, sizeof(result), nullptr, nullptr);
    return std::string(result, size);
}
int charToAscii(Tag*, RE::BSFixedString text) {
    auto value = wide(text);
    if (value.size() != 1) return -1;
    char byte;
    BOOL substituted = FALSE;
    if (WideCharToMultiByte(1252, WC_NO_BEST_FIT_CHARS, value.data(), 1, &byte, 1, nullptr, &substituted) != 1 || substituted) return -1;
    return static_cast<signed char>(byte);
}
std::string asciiToChar(Tag*, int code) {
    if (code <= 0 || code >= 256) return {};
    const char byte = static_cast<char>(code);
    wchar_t character;
    if (MultiByteToWideChar(1252, 0, &byte, 1, &character, 1) != 1) return {};
    return utf8(std::wstring(1, character));
}
float stringToNumber(Tag*, RE::BSFixedString text, bool hexadecimal) {
    const std::string_view value(text.c_str());
    const auto first = value.find_first_not_of(" \t\r\n");
    hexadecimal = hexadecimal || (first != std::string_view::npos &&
        (value.substr(first, 2) == "0x" || value.substr(first, 2) == "0X"));
    return hexadecimal ? static_cast<float>(std::strtoul(text.c_str(), nullptr, 16)) :
        static_cast<float>(std::strtod(text.c_str(), nullptr));
}
std::string numberToString(Tag*, float value) {
    char result[32];
    std::snprintf(result, sizeof(result), "%g", static_cast<double>(value));
    return result;
}

bool isAttacking(Tag*, RE::Actor* actor) { return actor && actor->IsAttacking(); }
bool isBlocking(Tag*, RE::Actor* actor) { return actor && actor->IsBlocking(); }
bool isSwimming(Tag*, RE::Actor* actor) { return actor && actor->AsActorState()->IsSwimming(); }
bool godMode(Tag*) { return RE::PlayerCharacter::IsGodMode(); }
bool movingForward(Tag*, RE::Actor* actor) { return actor && actor->AsActorState()->actorState1.movingForward; }
bool condition(RE::TESObjectREFR* actor, RE::FUNCTION_DATA::FunctionID function, RE::TESForm* argument = nullptr) {
    if (!actor) return false;
    RE::TESConditionItem item;
    item.data.functionData.function = function;
    item.data.functionData.params[0] = argument;
    item.data.comparisonValue.f = 1;
    RE::ConditionCheckParams params(actor, RE::PlayerCharacter::GetSingleton());
    return item.IsTrue(params);
}
bool torchOut(Tag*, RE::Actor* actor) { return condition(actor, RE::FUNCTION_DATA::FunctionID::kIsTorchOut); }
bool ignoreFriendlyHits(Tag*, RE::Actor* actor) { return condition(actor, RE::FUNCTION_DATA::FunctionID::kGetIgnoreFriendlyHits); }
bool lastRiddenMount(Tag*, RE::Actor* actor) { return condition(actor, RE::FUNCTION_DATA::FunctionID::kIsPlayersLastRiddenMount); }
bool alerted(Tag*, RE::Actor* actor) { return condition(actor, RE::FUNCTION_DATA::FunctionID::kGetIsAlerted); }
bool talkedToPC(Tag*, RE::Actor* actor) { return condition(actor, RE::FUNCTION_DATA::FunctionID::kGetTalkedToPC); }
bool playableRace(Tag*, RE::Actor* actor) { return condition(actor, RE::FUNCTION_DATA::FunctionID::kGetIsPlayableRace); }
bool shouldAttack(Tag*, RE::Actor* actor, RE::Actor* target) {
    return target && condition(actor, RE::FUNCTION_DATA::FunctionID::kGetShouldAttack, target);
}
bool currentFurniture(Tag*, RE::Actor* actor, RE::TESForm* target, bool object) {
    const auto furniture = actor ? actor->GetOccupiedFurniture().get() : nullptr;
    return furniture && target &&
        (object ? furniture->GetBaseObject() == target : furniture.get() == target);
}
bool snowing(Tag*) { return condition(RE::PlayerCharacter::GetSingleton(), RE::FUNCTION_DATA::FunctionID::kIsSnowing); }
int sleepHours(Tag*) {
    auto player = RE::PlayerCharacter::GetSingleton();
    return player ? player->GetPlayerRuntimeData().hoursToSleep : 0;
}
RE::TESPackage* editorPackage(Tag*, RE::Actor* actor) {
    auto process = actor ? actor->GetActorRuntimeData().currentProcess : nullptr;
    return process ? process->currentPackage.package : nullptr;
}
RE::Actor* horse(Tag*, RE::Actor* actor, bool rider) {
    RE::NiPointer<RE::Actor> result;
    if (actor) {
        const bool found = rider ? actor->GetMountedBy(result) : actor->GetMount(result);
        if (!found) return nullptr;
    }
    return result.get();
}
RE::Actor* lastHorse(Tag*) {
    auto player = RE::PlayerCharacter::GetSingleton();
    return player ? player->QLastRiddenMount().get().get() : nullptr;
}
bool hasLastHorse(Tag*) {
    // TES4 0x4F8630 accepts either the current mount or lastRiddenHorse.
    auto player = RE::PlayerCharacter::GetSingleton();
    RE::NiPointer<RE::Actor> mount;
    return player && (player->GetMount(mount) || lastHorse(nullptr));
}
bool thirdPerson(Tag*) {
    auto camera = RE::PlayerCamera::GetSingleton();
    return camera && camera->IsInThirdPerson();
}
bool forceRun(Tag*, RE::Actor* actor) { return actor && actor->AsActorState()->actorState2.forceRun; }
bool forceSneak(Tag*, RE::Actor* actor) { return actor && actor->AsActorState()->actorState2.forceSneak; }
int forceMovement(Tag*, RE::Actor* actor, bool enabled, bool sneak) {
    if (!actor) return 0;
    auto& state = actor->AsActorState()->actorState2;
    if (sneak) state.forceSneak = enabled;
    else state.forceRun = enabled;
    return 1;
}
bool isTrespassing(Tag*, RE::Actor* actor) { return actor && actor->IsTrespassing(); }
bool powerAttacking(Tag*, RE::Actor* actor) {
    auto process = actor ? actor->GetActorRuntimeData().currentProcess : nullptr;
    auto attack = process && process->high ? process->high->attackData.get() : nullptr;
    return actor && actor->IsAttacking() && attack && attack->data.flags.all(RE::AttackData::AttackFlag::kPowerAttack);
}
float lightAmount(Tag*, RE::Actor* actor) {
    auto process = actor ? actor->GetActorRuntimeData().currentProcess : nullptr;
    return process && process->high ? process->high->lightLevel : 100;
}
RE::TESForm* playerSpell(Tag*) {
    auto player = RE::PlayerCharacter::GetSingleton();
    if (!player) return nullptr;
    // TES4 had one selected slot. Prefer the slot currently casting; when
    // idle, the right-hand slot is the primary converted spell slot.
    for (auto source : {RE::MagicSystem::CastingSource::kRightHand, RE::MagicSystem::CastingSource::kLeftHand,
                        RE::MagicSystem::CastingSource::kOther}) {
        auto caster = player->GetMagicCaster(source);
        if (caster && caster->currentSpell && caster->state.any(RE::MagicCaster::State::kCasting,
                RE::MagicCaster::State::kCharging)) return caster->currentSpell;
    }
    for (int index : {1, 0, 2}) if (auto spell = player->GetActorRuntimeData().selectedSpells[index]) return spell;
    return nullptr;
}

RE::ACTOR_VALUE_MODIFIER modifierType(RE::BSFixedString modifier) {
    std::string kind(modifier.c_str());
    std::transform(kind.begin(), kind.end(), kind.begin(), [](unsigned char c) { return std::tolower(c); });
    return kind == "script" ? RE::ACTOR_VALUE_MODIFIER::kPermanent :
        kind == "max" ? RE::ACTOR_VALUE_MODIFIER::kTemporary :
        kind == "damage" ? RE::ACTOR_VALUE_MODIFIER::kDamage : RE::ACTOR_VALUE_MODIFIER::kTotal;
}
float actorValueModifier(Tag*, RE::Actor* actor, RE::BSFixedString av, RE::BSFixedString modifier) {
    if (!actor) return 0;
    const auto value = RE::ActorValueList::GetSingleton()->LookupActorValueByName(av.c_str());
    if (value == RE::ActorValue::kNone) return 0;
    const auto kind = modifierType(modifier);
    if (kind == RE::ACTOR_VALUE_MODIFIER::kTotal) return 0;
    return actor->GetActorValueModifier(kind, value);
}
float maxActorValue(Tag*, RE::Actor* actor, RE::BSFixedString av) {
    if (!actor) return 0;
    const auto value = RE::ActorValueList::GetSingleton()->LookupActorValueByName(av.c_str());
    if (value == RE::ActorValue::kNone) return 0;
    return actor->AsActorValueOwner()->GetPermanentActorValue(value) +
           actor->GetActorValueModifier(RE::ACTOR_VALUE_MODIFIER::kTemporary, value);
}
float baseActorValue(Tag*, RE::TESForm* form, RE::BSFixedString av) {
    if (auto ref = form ? form->As<RE::TESObjectREFR>() : nullptr) form = ref->GetBaseObject();
    auto base = form ? form->As<RE::TESNPC>() : nullptr;
    if (!base) return 0;
    const auto value = RE::ActorValueList::GetSingleton()->LookupActorValueByName(av.c_str());
    return value == RE::ActorValue::kNone ? 0 : base->GetActorValue(value);
}
float modifyActorValueModifier(Tag*, RE::Actor* actor, RE::BSFixedString av,
        RE::BSFixedString modifier, float amount, bool absolute) {
    if (!actor) return 0;
    const auto value = RE::ActorValueList::GetSingleton()->LookupActorValueByName(av.c_str());
    const auto kind = modifierType(modifier);
    if (value == RE::ActorValue::kNone || kind == RE::ACTOR_VALUE_MODIFIER::kTotal) return 0;
    if (absolute) amount -= actor->GetActorValueModifier(kind, value);
    actor->AsActorValueOwner()->RestoreActorValue(kind, value, amount);
    return actor->GetActorValueModifier(kind, value);
}

// Same TES4 -> TES5 NAM0 slot mapping as the record converter.
constexpr int colors[] = {0, 1, 11, 3, 4, 5, 6, 7, 8, 10};
RE::Color* weatherColor(RE::TESWeather* weather, int color, int time) {
    return weather && color >= 0 && color < 10 && time >= 0 && time < 4 ?
        &weather->colorData[colors[color]][time] : nullptr;
}
int getWeatherColor(Tag*, int component, int color, RE::TESWeather* weather, int time) {
    const auto rgba = weatherColor(weather, color, time);
    if (!rgba || component < 0 || component > 2) return 0;
    return component == 0 ? rgba->red : component == 1 ? rgba->green : rgba->blue;
}
void setWeatherColor(Tag*, int red, int green, int blue, int color, RE::TESWeather* weather, int time) {
    auto rgba = weatherColor(weather, color, time);
    if (!rgba) return;
    *rgba = RE::Color(std::clamp(red, 0, 255), std::clamp(green, 0, 255), std::clamp(blue, 0, 255), rgba->alpha);
    if (color == 1) weather->colorData[12][time] = *rgba;
    if (color == 2 || color == 9) weather->cloudColorData[color == 2 ? 0 : 1][time] = *rgba;
    if (color == 3) {
        // Updating ambient light must also update Skyrim's directional faces.
        auto& d = weather->directionalAmbientLightingColors[time].directional;
        RE::Color* faces[] = {&d.x.max, &d.x.min, &d.y.max, &d.y.min, &d.z.max, &d.z.min};
        constexpr float weights[] = {.98f, .94f, .96f, .95f, .67f, 1.28f};
        for (int i = 0; i < 6; ++i) {
            *faces[i] = RE::Color(std::min(255, int(rgba->red * weights[i])),
                std::min(255, int(rgba->green * weights[i])), std::min(255, int(rgba->blue * weights[i])), 0);
        }
    }
}
float sunDamage(Tag*, RE::TESWeather* weather) {
    return weather ? static_cast<std::uint8_t>(weather->data.sunDamage) / 255.f : 0.f;
}
int climateNumber(Tag*, RE::TESForm* form, int field) {
    auto climate = form ? form->As<RE::TESClimate>() : nullptr;
    if (!climate) return 0;
    const auto& time = climate->timing;
    switch (field) {
    case 0: return time.sunrise.begin;
    case 1: return time.sunrise.end;
    case 2: return time.sunset.begin;
    case 3: return time.sunset.end;
    case 4: return time.GetPhaseLength();
    case 5: return time.IncludesMasser();
    case 6: return time.IncludesSecunda();
    default: return 0;
    }
}
bool available(Tag*) { return true; }
}

bool RegisterCore(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("IsSwimming", "TES4Runtime", isSwimming);
    vm->RegisterFunction("GetGodMode", "TES4Runtime", godMode);
    vm->RegisterFunction("GetIgnoreFriendlyHits", "TES4Runtime", ignoreFriendlyHits);
    vm->RegisterFunction("GetIsAlerted", "TES4Runtime", alerted);
    vm->RegisterFunction("GetTalkedToPC", "TES4Runtime", talkedToPC);
    vm->RegisterFunction("GetIsPlayableRace", "TES4Runtime", playableRace);
    vm->RegisterFunction("GetShouldAttack", "TES4Runtime", shouldAttack);
    vm->RegisterFunction("IsPlayersLastRiddenHorse", "TES4Runtime", lastRiddenMount);
    vm->RegisterFunction("GetMaxActorValue", "TES4Runtime", maxActorValue);
    vm->RegisterFunction("GetBaseActorValueForForm", "TES4Runtime", baseActorValue);
    vm->RegisterFunction("FileExists", "TES4Runtime", fileExists);
    vm->RegisterFunction("StringSearch", "TES4Runtime", stringSearch);
    vm->RegisterFunction("StringLength", "TES4Runtime", stringLength);
    vm->RegisterFunction("StringSlice", "TES4Runtime", stringSlice);
    vm->RegisterFunction("StringEdit", "TES4Runtime", stringEdit);
    vm->RegisterFunction("StringAt", "TES4Runtime", stringAt);
    vm->RegisterFunction("CharToAscii", "TES4Runtime", charToAscii);
    vm->RegisterFunction("AsciiToChar", "TES4Runtime", asciiToChar);
    vm->RegisterFunction("GetClimateNumber", "TES4Runtime", climateNumber);
    vm->RegisterFunction("StringToNumber", "TES4Runtime", stringToNumber);
    vm->RegisterFunction("NumberToString", "TES4Runtime", numberToString);
    vm->RegisterFunction("IsAttacking", "TES4Runtime", isAttacking);
    vm->RegisterFunction("IsBlocking", "TES4Runtime", isBlocking);
    vm->RegisterFunction("IsMovingForward", "TES4Runtime", movingForward);
    vm->RegisterFunction("IsTorchOut", "TES4Runtime", torchOut);
    vm->RegisterFunction("IsSnowing", "TES4Runtime", snowing);
    vm->RegisterFunction("GetPCSleepHours", "TES4Runtime", sleepHours);
    vm->RegisterFunction("GetCurrentEditorPackage", "TES4Runtime", editorPackage);
    vm->RegisterFunction("GetHorse", "TES4Runtime", horse);
    vm->RegisterFunction("GetPlayersLastRiddenHorse", "TES4Runtime", lastHorse);
    vm->RegisterFunction("IsCurrentFurniture", "TES4Runtime", currentFurniture);
    vm->RegisterFunction("GetPlayerHasLastRiddenHorse", "TES4Runtime", hasLastHorse);
    vm->RegisterFunction("IsThirdPerson", "TES4Runtime", thirdPerson);
    vm->RegisterFunction("GetForceRun", "TES4Runtime", forceRun);
    vm->RegisterFunction("GetForceSneak", "TES4Runtime", forceSneak);
    vm->RegisterFunction("SetForcedMovement", "TES4Runtime", forceMovement);
    vm->RegisterFunction("IsPowerAttacking", "TES4Runtime", powerAttacking);
    vm->RegisterFunction("IsTrespassing", "TES4Runtime", isTrespassing);
    vm->RegisterFunction("GetActorLightAmount", "TES4Runtime", lightAmount);
    vm->RegisterFunction("GetPlayerSpell", "TES4Runtime", playerSpell);
    vm->RegisterFunction("Available", "TES4Runtime", available);
    vm->RegisterFunction("GetAVModifier", "TES4Runtime", actorValueModifier);
    vm->RegisterFunction("ModifyAVModifier", "TES4Runtime", modifyActorValueModifier);
    vm->RegisterFunction("GetWeatherColor", "TES4Runtime", getWeatherColor);
    vm->RegisterFunction("SetWeatherColor", "TES4Runtime", setWeatherColor);
    vm->RegisterFunction("GetWeatherSunDamage", "TES4Runtime", sunDamage);
    return true;
}
