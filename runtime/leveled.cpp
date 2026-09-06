#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <algorithm>
#include <mutex>
#include <random>

namespace {
using Tag = RE::StaticFunctionTag;
std::recursive_mutex listLock;
std::mt19937 random(std::random_device{}());

RE::TESLeveledList* list(RE::TESForm* form) {
    if (!form) return nullptr;
    if (auto item = form->As<RE::TESLevItem>()) return item;
    if (auto actor = form->As<RE::TESLevCharacter>()) return actor;
    return form->As<RE::TESLevSpell>();
}
RE::LEVELED_OBJECT* entry(RE::TESForm* form, int index) {
    auto target = list(form);
    return target && index >= 0 && index < target->numEntries ? &target->entries[index] : nullptr;
}
void add(Tag*, RE::TESForm* form, RE::TESForm* item, int level, int count) {
    std::scoped_lock guard(listLock);
    auto target = list(form);
    if (!target || !item) return;
    if (target->numEntries == 255) {
        SKSE::log::error("TES4Runtime: leveled list {:08X} reached Skyrim's 255-entry limit", form->GetFormID());
        return;
    }
    const auto old = target->numEntries;
    target->entries.resize(old + 1);
    int index = old;
    // OBSE inserts before the first entry at the same or a higher level.
    const auto storedLevel = static_cast<std::uint16_t>(level);
    while (index && target->entries[index - 1].level >= storedLevel) {
        target->entries[index] = target->entries[index - 1];
        --index;
    }
    target->entries[index] = {item, static_cast<std::uint16_t>(count), storedLevel, 0, nullptr};
    target->numEntries = old + 1;
}
void clear(Tag*, RE::TESForm* form) {
    std::scoped_lock guard(listLock);
    if (auto target = list(form)) { target->entries.clear(); target->numEntries = 0; }
}
template<class Predicate>
int remove(RE::TESForm* form, Predicate match) {
    auto target = list(form);
    if (!target) return 0;
    int kept = 0, old = target->numEntries;
    for (int i = 0; i < old; ++i)
        if (!match(target->entries[i], i)) target->entries[kept++] = target->entries[i];
    if (kept) target->entries.resize(kept);
    else target->entries.clear();
    target->numEntries = static_cast<std::uint8_t>(kept);
    return old - kept;
}
int removeForm(Tag*, RE::TESForm* form, RE::TESForm* item) {
    std::scoped_lock guard(listLock);
    return remove(form, [&](const auto& e, int) { return e.form == item; });
}
int removeLevel(Tag*, int level, RE::TESForm* form) {
    std::scoped_lock guard(listLock);
    return remove(form, [&](const auto& e, int) { return e.level == level; });
}
void removeNth(Tag*, int index, RE::TESForm* form) {
    std::scoped_lock guard(listLock);
    remove(form, [&](const auto&, int i) { return i == index; });
}
int size(Tag*, RE::TESForm* form) { std::scoped_lock guard(listLock); auto p = list(form); return p ? p->numEntries : 0; }
RE::TESForm* nth(Tag*, int index, RE::TESForm* form) { std::scoped_lock guard(listLock); auto p = entry(form,index); return p ? p->form : nullptr; }
int nthLevel(Tag*, int index, RE::TESForm* form) { std::scoped_lock guard(listLock); auto p = entry(form,index); return p ? p->level : 0; }
int nthCount(Tag*, int index, RE::TESForm* form) { std::scoped_lock guard(listLock); auto p = entry(form,index); return p ? p->count : 0; }
int chance(Tag*, RE::TESForm* form) { std::scoped_lock guard(listLock); auto p = list(form); return p ? p->GetChanceNone() : -1; }
void setChance(Tag*, int value, RE::TESForm* form) {
    std::scoped_lock guard(listLock);
    if (auto p = list(form); p && value >= 0 && value <= 100) p->chanceNone = static_cast<std::int8_t>(value);
}
bool allLevels(Tag*, RE::TESForm* form) { std::scoped_lock guard(listLock); auto p = list(form); return p && (p->llFlags & RE::TESLeveledList::kCalculateFromAllLevelsLTOrEqPCLevel); }
bool eachCount(Tag*, RE::TESForm* form) { std::scoped_lock guard(listLock); auto p = list(form); return p && (p->llFlags & RE::TESLeveledList::kCalculateForEachItemInCount); }
int findForm(Tag*, RE::TESForm* form, RE::TESForm* item) {
    std::scoped_lock guard(listLock);
    if (auto p = list(form)) for (int i = 0; i < p->numEntries; ++i) if (p->entries[i].form == item) return i;
    return -1;
}
int findLevel(Tag*, int level, RE::TESForm* form) {
    std::scoped_lock guard(listLock);
    if (auto p = list(form)) for (int i = 0; i < p->numEntries; ++i) if (p->entries[i].level == level) return i;
    return -1;
}
RE::TESForm* byLevel(Tag* tag, int level, RE::TESForm* form) { return nth(tag,findLevel(tag,level,form),form); }

RE::TESForm* calculate(Tag*, RE::TESForm* form, int level, bool useChance, int difference, bool recurse) {
    std::scoped_lock guard(listLock);
    if (level < 0) return nullptr;
    if (difference < 0) {
        const auto setting = RE::GameSettingCollection::GetSingleton()->GetSetting("iLevItemLevelDifferenceMax");
        difference = setting ? setting->data.i : 0;
    }
    // CalcLeveledItem is OBSE's selector, not the game's CalculateCurrentFormList:
    // it selects one form, ignores counts, and permits chance/difference overrides.
    // Match xOBSE GameForms.cpp::CalcElement, including NR's all-level behavior.
    std::vector<RE::TESForm*> visited;
    while (auto target = list(form)) {
        if (std::find(visited.begin(),visited.end(),form) != visited.end()) return nullptr;
        visited.push_back(form);
        if (useChance && random() % 100 < target->GetChanceNone()) return nullptr;
        int maximum = level, minimum = 0;
        if (recurse && !(target->llFlags & RE::TESLeveledList::kCalculateFromAllLevelsLTOrEqPCLevel)) {
            maximum = 0;
            for (int i = 0; i < target->numEntries; ++i)
                if (target->entries[i].level <= level) maximum = std::max(maximum, int(target->entries[i].level));
            minimum = std::max(0, maximum - difference);
        }
        RE::TESForm* selected = nullptr;
        unsigned matches = 0;
        for (int i = 0; i < target->numEntries; ++i) {
            const auto& candidate = target->entries[i];
            if (candidate.level >= minimum && candidate.level <= maximum && random() % ++matches == 0) selected = candidate.form;
        }
        if (!recurse || !selected) return selected;
        form = selected;
    }
    return form;
}
}

bool RegisterLeveledLists(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("AddToLeveledList", "TES4Runtime", add);
    vm->RegisterFunction("ClearLeveledList", "TES4Runtime", clear);
    vm->RegisterFunction("RemoveFromLeveledList", "TES4Runtime", removeForm);
    vm->RegisterFunction("RemoveLevItemByLevel", "TES4Runtime", removeLevel);
    vm->RegisterFunction("RemoveNthLevItem", "TES4Runtime", removeNth);
    vm->RegisterFunction("GetNumLevItems", "TES4Runtime", size);
    vm->RegisterFunction("GetNthLevItem", "TES4Runtime", nth);
    vm->RegisterFunction("GetNthLevItemLevel", "TES4Runtime", nthLevel);
    vm->RegisterFunction("GetNthLevItemCount", "TES4Runtime", nthCount);
    vm->RegisterFunction("GetChanceNone", "TES4Runtime", chance);
    vm->RegisterFunction("SetChanceNone", "TES4Runtime", setChance);
    vm->RegisterFunction("GetCalcAllLevels", "TES4Runtime", allLevels);
    vm->RegisterFunction("GetCalcEachInCount", "TES4Runtime", eachCount);
    vm->RegisterFunction("GetLevItemIndexByForm", "TES4Runtime", findForm);
    vm->RegisterFunction("GetLevItemIndexByLevel", "TES4Runtime", findLevel);
    vm->RegisterFunction("GetLevItemByLevel", "TES4Runtime", byLevel);
    vm->RegisterFunction("CalcLeveledItem", "TES4Runtime", calculate);
    return true;
}
