#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <map>
#include <mutex>
#include <vector>

RE::TESForm* SourceForm(RE::StaticFunctionTag*, RE::TESForm*, std::string);

namespace {
struct VoiceState {
    RE::TESRace* race;
    RE::TESRace* originalRace;
    RE::TESRace* currentRace;
    RE::BGSVoiceType* originalVoice;
    std::vector<std::pair<RE::TESNPC*, RE::BGSVoiceType*>> actors;
};
std::mutex mutex;
std::map<std::pair<RE::FormID, int>, VoiceState> states;

RE::TESRace* authoredRace(RE::TESRace* race, int sex) {
    auto form = SourceForm(nullptr, race, sex ? "FemaleVoiceRace" : "MaleVoiceRace");
    return form && form->As<RE::TESRace>() ? form->As<RE::TESRace>() : race;
}
RE::TESRace* getVoice(RE::StaticFunctionTag*, RE::TESRace* race, int sex) {
    if (!race || sex < 0 || sex > 1) return nullptr;
    std::scoped_lock lock(mutex);
    auto state = states.find({race->GetFormID(), sex});
    return state == states.end() ? authoredRace(race, sex) : state->second.currentRace;
}
void setVoice(RE::StaticFunctionTag*, RE::TESRace* race, RE::TESRace* voiceRace, int gender) {
    if (!race || !voiceRace) return;
    std::scoped_lock lock(mutex);
    for (int sex = 0; sex < 2; ++sex) {
        if ((gender == 0 && sex == 1) || (gender == 1 && sex == 0)) continue;
        auto [entry, inserted] = states.try_emplace({race->GetFormID(), sex});
        auto& state = entry->second;
        if (inserted) {
            state.race = race;
            state.originalRace = authoredRace(race, sex);
            state.originalVoice = race->defaultVoiceTypes[sex];
            for (auto npc : RE::TESDataHandler::GetSingleton()->GetFormArray<RE::TESNPC>()) {
                if (npc && npc->GetRace() == race && static_cast<int>(npc->GetSex()) == sex)
                    state.actors.emplace_back(npc, npc->GetVoiceType());
            }
        }
        state.currentRace = voiceRace;
        const bool restore = voiceRace == state.originalRace;
        auto source = SourceForm(nullptr, voiceRace, sex ? "FemaleVoiceType" : "MaleVoiceType");
        auto voice = source ? source->As<RE::BGSVoiceType>() : voiceRace->defaultVoiceTypes[sex];
        race->defaultVoiceTypes[sex] = restore ? state.originalVoice : voice;
        // Converted NPCs carry explicit VTCKs, so changing RACE.VTCK alone
        // cannot change the voice the engine actually selects for them.
        for (const auto& [npc, original] : state.actors)
            npc->SetObjectVoiceType(restore ? original : voice);
    }
}
}

void ResetVoices(SKSE::MessagingInterface::Message* message) {
    if (message->type != SKSE::MessagingInterface::kPreLoadGame &&
        message->type != SKSE::MessagingInterface::kNewGame) return;
    std::scoped_lock lock(mutex);
    for (auto& [key, state] : states) {
        state.race->defaultVoiceTypes[key.second] = state.originalVoice;
        for (const auto& [npc, original] : state.actors) npc->SetObjectVoiceType(original);
    }
    states.clear();
}

bool RegisterVoices(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("GetRaceVoice", "TES4Runtime", getVoice);
    vm->RegisterFunction("SetRaceVoice", "TES4Runtime", setVoice);
    return true;
}
