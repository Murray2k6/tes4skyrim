#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <algorithm>

int SourceInt(RE::StaticFunctionTag*, RE::TESForm*, std::string, int);
RE::TESForm* SourceForm(RE::StaticFunctionTag*, RE::TESForm*, std::string);

namespace {
using Entry = std::pair<RE::TESFaction*, int>;
std::vector<Entry> factions(RE::TESForm* form) {
    std::vector<Entry> result;
    auto add = [&](RE::TESFaction* faction, std::int8_t rank) {
        auto found = std::find_if(result.begin(), result.end(), [&](const auto& entry) { return entry.first == faction; });
        if (found != result.end()) found->second = rank;
        else result.emplace_back(faction, rank);
        return false;
    };
    if (form) {
        if (auto actor = form->As<RE::Actor>()) actor->VisitFactions(add);
        else if (auto npc = form->As<RE::TESNPC>()) for (const auto& entry : npc->factions) add(entry.faction, entry.rank);
    }
    std::erase_if(result, [](const auto& entry) { return !entry.first || entry.second < 0; });
    return result;
}
int count(RE::StaticFunctionTag*, RE::TESForm* subject) { return static_cast<int>(factions(subject).size()); }
RE::TESFaction* nth(RE::StaticFunctionTag*, RE::TESForm* subject, int index) {
    auto values = factions(subject);
    return index >= 0 && index < values.size() ? values[index].first : nullptr;
}
int rank(RE::StaticFunctionTag*, RE::TESForm* subject, int index) {
    auto values = factions(subject);
    return index >= 0 && index < values.size() ? values[index].second : -1;
}
int sourceReaction(RE::StaticFunctionTag*, RE::TESFaction* subject, RE::TESFaction* other) {
    if (!subject || !other) return 0;
    const auto total = SourceInt(nullptr, subject, "RelationCount", 0);
    for (int i = 0; i < total; ++i)
        if (SourceForm(nullptr, subject, "Relation" + std::to_string(i)) == other)
            return SourceInt(nullptr, subject, "Reaction" + std::to_string(i), 0);
    return 0;
}
void fightReaction(RE::StaticFunctionTag*, RE::TESFaction* subject, RE::TESFaction* other, int value) {
    if (!subject || !other) return;
    const auto reaction = value <= -50 ? RE::FIGHT_REACTION::kEnemy : value < 50 ? RE::FIGHT_REACTION::kNeutral :
        subject == other ? RE::FIGHT_REACTION::kAlly : RE::FIGHT_REACTION::kFriend;
    subject->SetFactionFightReaction(other, reaction);
    if (auto lists = RE::ProcessLists::GetSingleton()) lists->ClearCachedFactionFightReactions();
}
}

bool RegisterFactions(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("SourceFactionReaction", "TES4Runtime", sourceReaction);
    vm->RegisterFunction("SetFactionFightReaction", "TES4Runtime", fightReaction);
    vm->RegisterFunction("GetNumFactions", "TES4Runtime", count);
    vm->RegisterFunction("GetNthFaction", "TES4Runtime", nth);
    vm->RegisterFunction("GetNthFactionRank", "TES4Runtime", rank);
    return true;
}
