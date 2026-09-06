#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <map>
#include <mutex>
#include <algorithm>

void SaveEvents(SKSE::SerializationInterface*);
void ResetEvents();
bool LoadEvent(SKSE::SerializationInterface*, std::uint32_t, std::uint32_t, std::uint32_t);
void SaveGoldValues(SKSE::SerializationInterface*);
void ResetGoldValues();
bool LoadGoldValue(SKSE::SerializationInterface*, std::uint32_t, std::uint32_t, std::uint32_t);
void SaveVampirism(SKSE::SerializationInterface*);
void ResetVampirism();
bool LoadVampirism(SKSE::SerializationInterface*, std::uint32_t, std::uint32_t, std::uint32_t);

namespace {
// TES4's ExtraInvestmentGold has no Skyrim extra-data counterpart. Keep the
// same per-reference integer in the SKSE cosave, resolving IDs on load.
std::mutex mutex;
std::map<RE::FormID, int> investments;
constexpr std::uint32_t recordType = 0x49565354;  // IVST
std::map<std::pair<RE::FormID, RE::FormID>, float> dispositions;
constexpr std::uint32_t dispositionType = 0x4453504E;  // DSPN
float disposition(RE::StaticFunctionTag*, RE::Actor* actor, RE::Actor* other,
                  float fallback, float change, bool modify) {
    if (!actor || !other) return 0;
    std::scoped_lock guard(mutex);
    const auto key = std::pair{actor->GetFormID(), other->GetFormID()};
    const auto found = dispositions.find(key);
    const auto current = found == dispositions.end() ? fallback : found->second;
    if (!modify) return current;
    return dispositions[key] = std::clamp(current + change, 0.f, 100.f);
}
int investment(RE::StaticFunctionTag*, RE::TESObjectREFR* merchant) {
    if (!merchant) return 0;
    std::scoped_lock guard(mutex);
    auto found = investments.find(merchant->GetFormID());
    return found == investments.end() ? 0 : found->second;
}
void setInvestment(RE::StaticFunctionTag*, RE::TESObjectREFR* merchant, int gold) {
    if (!merchant) return;
    std::scoped_lock guard(mutex);
    if (gold) investments[merchant->GetFormID()] = gold;
    else investments.erase(merchant->GetFormID());
}
void save(SKSE::SerializationInterface* stream) {
    SaveEvents(stream);
    SaveGoldValues(stream);
    SaveVampirism(stream);
    std::scoped_lock guard(mutex);
    for (auto [id, gold] : investments) {
        if (!stream->OpenRecord(recordType, 1) || !stream->WriteRecordData(id) || !stream->WriteRecordData(gold)) {
            SKSE::log::error("Could not save merchant investment {:08X}", id);
            return;
        }
    }
    for (auto [pair, value] : dispositions) {
        if (!stream->OpenRecord(dispositionType, 1) || !stream->WriteRecordData(pair.first) ||
                !stream->WriteRecordData(pair.second) || !stream->WriteRecordData(value)) {
            SKSE::log::error("Could not save disposition {:08X} toward {:08X}", pair.first, pair.second);
            return;
        }
    }
}
void revert(SKSE::SerializationInterface*) {
    ResetEvents();
    ResetGoldValues();
    ResetVampirism();
    std::scoped_lock guard(mutex);
    investments.clear();
    dispositions.clear();
}
void load(SKSE::SerializationInterface* stream) {
    ResetEvents();
    ResetGoldValues();
    ResetVampirism();
    std::scoped_lock guard(mutex);
    investments.clear();
    dispositions.clear();
    std::uint32_t type, version, length;
    while (stream->GetNextRecordInfo(type, version, length)) {
        if (LoadEvent(stream, type, version, length)) continue;
        if (LoadGoldValue(stream, type, version, length)) continue;
        if (LoadVampirism(stream, type, version, length)) continue;
        if (type == dispositionType && version == 1 && length == 12) {
            RE::FormID actor, other, newActor, newOther;
            float value;
            if (stream->ReadRecordData(actor) == sizeof(actor) &&
                    stream->ReadRecordData(other) == sizeof(other) &&
                    stream->ReadRecordData(value) == sizeof(value) &&
                    stream->ResolveFormID(actor, newActor) && stream->ResolveFormID(other, newOther))
                dispositions[{newActor, newOther}] = value;
            continue;
        }
        if (type != recordType || version != 1 || length != 8) continue;
        RE::FormID oldID, newID;
        int gold;
        if (stream->ReadRecordData(oldID) == sizeof(oldID) && stream->ReadRecordData(gold) == sizeof(gold) &&
            stream->ResolveFormID(oldID, newID)) investments[newID] = gold;
    }
}
}

void RegisterMerchantSerialization() {
    auto stream = SKSE::GetSerializationInterface();
    stream->SetUniqueID(0x54345254);  // T4RT
    stream->SetSaveCallback(save);
    stream->SetLoadCallback(load);
    stream->SetRevertCallback(revert);
}
bool RegisterMerchant(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("DispositionValue", "TES4Runtime", disposition);
    vm->RegisterFunction("GetInvestmentGold", "TES4Runtime", investment);
    vm->RegisterFunction("SetInvestmentGold", "TES4Runtime", setInvestment);
    return true;
}
