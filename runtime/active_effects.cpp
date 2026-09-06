#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <algorithm>
#include <cmath>
#include <map>
#include <mutex>

int SourceInt(RE::StaticFunctionTag*, RE::TESForm*, std::string, int);
RE::TESForm* SourceForm(RE::StaticFunctionTag*, RE::TESForm*, std::string);

namespace {
using Tag = RE::StaticFunctionTag;
struct VampireValue { float base = 0; float modifier = 0; };
std::mutex vampireMutex;
std::map<RE::FormID, VampireValue> vampireValues;
constexpr std::uint32_t vampireRecord = 0x56414D50;  // VAMP
constexpr int vampireCode = 0x504D4156;  // source four-character effect code
float vampireEffects(RE::Actor* actor) {
    float result = 0;
    auto list = actor ? actor->AsMagicTarget()->GetActiveEffectList() : nullptr;
    if (list) for (auto effect : *list)
        if (effect && !effect->flags.any(RE::ActiveEffect::Flag::kInactive, RE::ActiveEffect::Flag::kDispelled) &&
                SourceInt(nullptr, effect->GetBaseObject(), "EffectCode", 0) == vampireCode)
            result += effect->magnitude;
    return result;
}
float vampirism(Tag*, RE::Actor* actor, bool baseOnly) {
    if (!actor) return 0;
    const auto effects = baseOnly ? 0 : vampireEffects(actor);
    std::scoped_lock guard(vampireMutex);
    auto found = vampireValues.find(actor->GetFormID());
    const auto value = found == vampireValues.end() ? VampireValue{} : found->second;
    return baseOnly ? value.base : std::max(0.0f, value.base + value.modifier + effects);
}
int changeVampirism(Tag*, RE::Actor* actor, float amount, int operation) {
    if (!actor || !std::isfinite(amount) || operation < 0 || operation > 2) return 0;
    const auto effects = vampireEffects(actor);
    std::scoped_lock guard(vampireMutex);
    auto& value = vampireValues[actor->GetFormID()];
    if (operation == 0) value.base = amount;
    else if (operation == 1) value.modifier += amount;
    else value.modifier = amount - value.base - effects;
    return 0;
}
RE::ActiveEffect* effect(RE::Actor* actor, int index) {
    auto list = actor ? actor->AsMagicTarget()->GetActiveEffectList() : nullptr;
    if (list && index >= 0) for (auto value : *list) if (index-- == 0) return value;
    return nullptr;
}
int count(Tag*, RE::Actor* actor) {
    auto list = actor ? actor->AsMagicTarget()->GetActiveEffectList() : nullptr;
    int result = 0;
    if (list) for (auto value : *list) if (value) ++result;
    return result;
}
RE::TESForm* form(Tag*, RE::Actor* actor, int index, std::string field) {
    auto value = effect(actor, index);
    if (!value) return nullptr;
    if (field == "MagicItem") return value->spell;
    if (field == "Caster") return value->GetCasterActor().get();
    if (field == "Object") return value->source;
    if (field == "SummonRef") {
        auto summon = skyrim_cast<RE::SummonCreatureEffect*>(value);
        return summon ? summon->commandedActor.get().get() : nullptr;
    }
    auto base = value->GetBaseObject();
    if (!base) return nullptr;
    if (field == "BoundItem") {
        if (auto bound = SourceForm(nullptr, base, "BoundItem")) return bound;
        return skyrim_cast<RE::BoundItemEffect*>(value) ? base->data.associatedForm : nullptr;
    }
    return field == "Data" ? base->data.associatedForm : nullptr;
}
float number(Tag*, RE::Actor* actor, int index, std::string field) {
    auto value = effect(actor, index);
    if (!value) return 0;
    if (field == "Duration") return value->duration;
    if (field == "TimeElapsed") return value->elapsedSeconds;
    return field == "Magnitude" ? value->magnitude : 0;
}
int code(Tag*, RE::Actor* actor, int index) {
    auto value = effect(actor, index);
    return value ? SourceInt(nullptr, value->GetBaseObject(), "EffectCode", 0) : 0;
}
bool applied(Tag*, RE::Actor* actor, int index) {
    auto value = effect(actor, index);
    return value && !value->flags.any(RE::ActiveEffect::Flag::kInactive, RE::ActiveEffect::Flag::kDispelled);
}
bool dispel(Tag*, RE::Actor* actor, int index) {
    auto value = effect(actor, index);
    if (!value) return false;
    value->Dispel(false);
    return true;
}
int dispelMagicItem(Tag*, RE::Actor* actor, RE::TESForm* form) {
    auto magic = form ? form->As<RE::MagicItem>() : nullptr;
    auto list = actor ? actor->AsMagicTarget()->GetActiveEffectList() : nullptr;
    if (!magic || !list) return 0;
    for (auto value : *list) if (value && value->spell == magic) value->Dispel(false);
    return 0;
}
}

void SaveVampirism(SKSE::SerializationInterface* stream) {
    std::scoped_lock guard(vampireMutex);
    for (const auto& [id, value] : vampireValues)
        if (!stream->OpenRecord(vampireRecord, 1) || !stream->WriteRecordData(id) ||
                !stream->WriteRecordData(value.base) || !stream->WriteRecordData(value.modifier))
            SKSE::log::error("Could not save Vampirism value for {:08X}", id);
}
void ResetVampirism() {
    std::scoped_lock guard(vampireMutex);
    vampireValues.clear();
}
bool LoadVampirism(SKSE::SerializationInterface* stream, std::uint32_t type,
                   std::uint32_t version, std::uint32_t length) {
    if (type != vampireRecord) return false;
    if (version != 1 || length != 12) return true;
    RE::FormID oldID, newID;
    VampireValue value;
    if (stream->ReadRecordData(oldID) == sizeof(oldID) &&
            stream->ReadRecordData(value.base) == sizeof(value.base) &&
            stream->ReadRecordData(value.modifier) == sizeof(value.modifier) &&
            std::isfinite(value.base) && std::isfinite(value.modifier) &&
            stream->ResolveFormID(oldID, newID)) {
        std::scoped_lock guard(vampireMutex);
        vampireValues[newID] = value;
    }
    return true;
}

bool RegisterActiveEffects(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("DispelMagicItem", "TES4Runtime", dispelMagicItem);
    vm->RegisterFunction("GetVampirism", "TES4Runtime", vampirism);
    vm->RegisterFunction("ChangeVampirism", "TES4Runtime", changeVampirism);
    vm->RegisterFunction("GetActiveEffectCount", "TES4Runtime", count);
    vm->RegisterFunction("GetActiveEffectForm", "TES4Runtime", form);
    vm->RegisterFunction("GetActiveEffectNumber", "TES4Runtime", number);
    vm->RegisterFunction("GetActiveEffectCode", "TES4Runtime", code);
    vm->RegisterFunction("IsActiveEffectApplied", "TES4Runtime", applied);
    vm->RegisterFunction("DispelActiveEffect", "TES4Runtime", dispel);
    return true;
}
