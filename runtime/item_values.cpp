#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <algorithm>
#include <cmath>
#include <map>
#include <mutex>

namespace {
struct GoldState { std::uint32_t value; bool overrideCost; };
std::mutex goldMutex;
std::map<RE::FormID, GoldState> originals;
std::map<RE::FormID, std::uint32_t> changed;
constexpr std::uint32_t recordType = 0x474F4C44;  // GOLD
RE::TESForm* base(RE::TESForm* form) {
    if (form) if (auto ref = form->As<RE::TESObjectREFR>()) return ref->GetBaseObject();
    return form;
}
bool snapshot(RE::TESForm* form, GoldState& state) {
    if (auto field = form ? form->As<RE::TESValueForm>() : nullptr) {
        state = {static_cast<std::uint32_t>(field->value), false}; return true;
    }
    if (auto potion = form ? form->As<RE::AlchemyItem>() : nullptr) {
        state = {static_cast<std::uint32_t>(potion->data.costOverride),
                 potion->data.flags.all(RE::AlchemyItem::AlchemyFlag::kCostOverride)};
        return true;
    }
    return false;
}
void apply(RE::TESForm* form, GoldState state) {
    if (auto field = form ? form->As<RE::TESValueForm>() : nullptr) field->value = static_cast<std::int32_t>(state.value);
    else if (auto potion = form ? form->As<RE::AlchemyItem>() : nullptr) {
        potion->data.costOverride = static_cast<std::int32_t>(state.value);
        if (state.overrideCost) potion->data.flags.set(RE::AlchemyItem::AlchemyFlag::kCostOverride);
        else potion->data.flags.reset(RE::AlchemyItem::AlchemyFlag::kCostOverride);
    }
}
int gold(RE::StaticFunctionTag*, RE::TESForm* form, bool includeEnchantment) {
    form = base(form);
    if (!form) return 0;
    if (!includeEnchantment) if (auto field = form->As<RE::TESValueForm>()) return field->value;
    return std::max(0, form->GetGoldValue());
}
void write(RE::TESForm* form, std::uint32_t value, bool persist) {
    GoldState before;
    if (!snapshot(form, before)) return;
    if (persist) {
        originals.try_emplace(form->GetFormID(), before);
        changed[form->GetFormID()] = value;
    }
    apply(form, {value, true});
}
int changeGold(RE::StaticFunctionTag*, RE::TESForm* form, float amount, bool modify, bool persist) {
    form = base(form);
    if (!form || !std::isfinite(amount)) return 0;
    std::scoped_lock guard(goldMutex);
    double value = modify ? static_cast<double>(gold(nullptr, form, false)) + amount : amount;
    write(form, static_cast<std::uint32_t>(std::clamp(value, 0.0, static_cast<double>(INT32_MAX))), persist);
    return 0;
}
int setItemValue(RE::StaticFunctionTag*, RE::TESObjectREFR* ref, int value) {
    // Oblivion SetItemValue 0x506810 calls TESValueForm::SetValue 0x4703C0:
    // write the integer base value and mark it for save/load.
    if (!ref) return 0;
    std::scoped_lock guard(goldMutex);
    write(ref->GetBaseObject(), static_cast<std::uint32_t>(value), true);
    return 0;
}
}

void SaveGoldValues(SKSE::SerializationInterface* stream) {
    std::scoped_lock guard(goldMutex);
    for (const auto& [id, value] : changed) {
        GoldState current;
        if (!snapshot(RE::TESForm::LookupByID(id), current)) continue;
        if (!stream->OpenRecord(recordType, 1) || !stream->WriteRecordData(id) || !stream->WriteRecordData(current.value))
            SKSE::log::error("Could not save gold value for {:08X}", id);
    }
}
void ResetGoldValues() {
    std::scoped_lock guard(goldMutex);
    for (const auto& [id, state] : originals) apply(RE::TESForm::LookupByID(id), state);
    originals.clear();
    changed.clear();
}
bool LoadGoldValue(SKSE::SerializationInterface* stream, std::uint32_t type,
                   std::uint32_t version, std::uint32_t length) {
    if (type != recordType) return false;
    if (version != 1 || length != 8) return true;
    RE::FormID oldID, newID;
    std::uint32_t value;
    if (stream->ReadRecordData(oldID) != sizeof(oldID) || stream->ReadRecordData(value) != sizeof(value) ||
            !stream->ResolveFormID(oldID, newID)) return true;
    std::scoped_lock guard(goldMutex);
    write(RE::TESForm::LookupByID(newID), value, true);
    return true;
}
bool RegisterItemValues(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("GetGoldValue", "TES4Runtime", gold);
    vm->RegisterFunction("ChangeGoldValue", "TES4Runtime", changeGold);
    vm->RegisterFunction("SetItemValue", "TES4Runtime", setItemValue);
    return true;
}
