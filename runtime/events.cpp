#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <algorithm>
#include <map>
#include <mutex>
#include <cctype>

std::string SourceString(RE::StaticFunctionTag*, RE::TESForm*, std::string);
int SourceInt(RE::StaticFunctionTag*, RE::TESForm*, std::string, int);

namespace {
struct Handler {
    RE::FormID host, first, second;
    bool operator==(const Handler&) const = default;
};
std::mutex mutex;
std::map<std::string, std::vector<Handler>> handlers;
constexpr std::uint32_t recordType = 0x45564E54; // EVNT
std::string loadingSave;
RE::ObjectRefHandle lastDropped;
RE::FormID lastDroppedBase = 0;
RE::TESObjectREFR* lastDroppedReference(RE::StaticFunctionTag*) {
    std::scoped_lock lock(mutex);
    return lastDropped.get().get();
}
RE::TESForm* lastDroppedItem(RE::StaticFunctionTag*) {
    std::scoped_lock lock(mutex);
    return RE::TESForm::LookupByID(lastDroppedBase);
}
RE::FormID id(RE::TESForm* form) { return form ? form->GetFormID() : 0; }
std::string lower(std::string text) {
    std::ranges::transform(text, text.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return text;
}
bool setHandler(RE::StaticFunctionTag*, std::string name, RE::TESForm* host,
                RE::TESForm* first, RE::TESForm* second, bool enabled) {
    if (!host || !host->As<RE::TESQuest>() || SourceString(nullptr, host, "PapyrusName").empty()) return false;
    name = lower(name);
    if (name.empty()) return false;
    std::scoped_lock lock(mutex);
    auto& list = handlers[name];
    Handler entry{id(host), id(first), id(second)};
    if (enabled) {
        if (std::ranges::find(list, entry) == list.end()) list.push_back(entry);
    } else {
        std::erase_if(list, [&](auto& value) {
            return value.host == entry.host && (!entry.first || value.first == entry.first) &&
                   (!entry.second || value.second == entry.second);
        });
    }
    return true;
}

// Filters compare the authored event parameters, not the event's caller.
// The separate caller is significant for OBSE OnMagicApply and OnHealthDamage.
template <class... Args>
void send(const std::string& name, RE::TESObjectREFR* caller,
          RE::TESForm* first, RE::TESForm* second, Args... args) {
    std::vector<Handler> listeners;
    {
        std::scoped_lock lock(mutex);
        auto found = handlers.find(name);
        if (found == handlers.end()) return;
        listeners = found->second;
    }
    auto vm = RE::BSScript::Internal::VirtualMachine::GetSingleton();
    for (auto& entry : listeners) {
        if ((entry.first && entry.first != id(first)) || (entry.second && entry.second != id(second))) continue;
        auto host = RE::TESForm::LookupByID<RE::TESQuest>(entry.host);
        if (!host) continue;
        auto script = SourceString(nullptr, host, "PapyrusName");
        const auto handle = vm->GetObjectHandlePolicy()->GetHandleForObject(host->GetFormType(), host);
        RE::BSTSmartPointer<RE::BSScript::IStackCallbackFunctor> result;
        if (!vm->DispatchMethodCall(handle, script.c_str(), "TES4Call",
                RE::MakeFunctionArguments(static_cast<RE::TESObjectREFR*>(caller), Args(args)...), result))
            SKSE::log::error("{} callback {} on {:08X} could not be dispatched", name, script, entry.host);
    }
}
void forms(const std::string& name, RE::TESForm* first, RE::TESForm* second,
           RE::TESObjectREFR* caller = nullptr) {
    send(name, caller, first, second, first, second);
}

class Events final : public RE::BSTEventSink<RE::TESEquipEvent>,
                     public RE::BSTEventSink<RE::TESHitEvent>,
                     public RE::BSTEventSink<RE::TESDeathEvent>,
                     public RE::BSTEventSink<RE::TESActivateEvent>,
                     public RE::BSTEventSink<RE::TESCombatEvent>,
                     public RE::BSTEventSink<RE::TESSpellCastEvent>,
                     public RE::BSTEventSink<RE::TESMagicEffectApplyEvent>,
                     public RE::BSTEventSink<RE::TESActiveEffectApplyRemoveEvent>,
                     public RE::BSTEventSink<RE::TESContainerChangedEvent> {
    using Result = RE::BSEventNotifyControl;
    static constexpr Result next = Result::kContinue;
public:
    Result ProcessEvent(const RE::TESEquipEvent* e, RE::BSTEventSource<RE::TESEquipEvent>*) override {
        if (e) forms(e->equipped ? "onactorequip" : "onactorunequip", e->actor.get(), RE::TESForm::LookupByID(e->baseObject));
        return next;
    }
    Result ProcessEvent(const RE::TESHitEvent* e, RE::BSTEventSource<RE::TESHitEvent>*) override {
        if (e) {
            forms("onhit", e->target.get(), e->cause.get());
            auto weapon = RE::TESForm::LookupByID<RE::TESObjectWEAP>(e->source);
            if (weapon) forms("onhitwith", e->target.get(), weapon);
        }
        return next;
    }
    Result ProcessEvent(const RE::TESDeathEvent* e, RE::BSTEventSource<RE::TESDeathEvent>*) override {
        if (e && e->dead) forms("ondeath", e->actorDying.get(), e->actorKiller.get());
        return next;
    }
    Result ProcessEvent(const RE::TESActivateEvent* e, RE::BSTEventSource<RE::TESActivateEvent>*) override {
        if (e) forms("onactivate", e->objectActivated.get(), e->actionRef.get());
        return next;
    }
    Result ProcessEvent(const RE::TESCombatEvent* e, RE::BSTEventSource<RE::TESCombatEvent>*) override {
        if (e && e->newState == RE::ACTOR_COMBAT_STATE::kCombat) forms("onstartcombat", e->actor.get(), e->targetActor.get());
        return next;
    }
    Result ProcessEvent(const RE::TESSpellCastEvent* e, RE::BSTEventSource<RE::TESSpellCastEvent>*) override {
        if (e) {
            auto spell = RE::TESForm::LookupByID(e->spell);
            if (spell && spell->Is(RE::FormType::Scroll)) forms("onscrollcast", e->object.get(), spell);
            else if (spell && spell->Is(RE::FormType::Spell)) forms("onspellcast", e->object.get(), spell);
        }
        return next;
    }
    Result ProcessEvent(const RE::TESMagicEffectApplyEvent* e, RE::BSTEventSource<RE::TESMagicEffectApplyEvent>*) override {
        if (e) {
            auto effect = RE::TESForm::LookupByID(e->magicEffect);
            auto code = SourceInt(nullptr, effect, "EffectCode", 0);
            if (code) send("onmagiceffecthit", nullptr, e->target.get(), effect,
                           static_cast<RE::TESForm*>(e->target.get()), code);
            forms("onmagiceffecthit2", e->target.get(), effect);
        }
        return next;
    }
    Result ProcessEvent(const RE::TESActiveEffectApplyRemoveEvent* e, RE::BSTEventSource<RE::TESActiveEffectApplyRemoveEvent>*) override {
        if (!e || !e->isApplied || !e->target) return next;
        auto actor = e->target->As<RE::Actor>();
        auto list = actor ? actor->AsMagicTarget()->GetActiveEffectList() : nullptr;
        if (list) for (auto effect : *list) {
            if (effect && effect->usUniqueID == e->activeEffectUniqueID) {
                forms("onmagicapply", effect->spell, e->caster.get(), e->target.get());
                break;
            }
        }
        return next;
    }
    Result ProcessEvent(const RE::TESContainerChangedEvent* e, RE::BSTEventSource<RE::TESContainerChangedEvent>*) override {
        // A dropped object enters the world. Consuming/removing an inventory
        // item also has newContainer=0, but has no new world reference.
        if (e && e->oldContainer && !e->newContainer && e->reference.get()) {
            {
                std::scoped_lock lock(mutex);
                // xOBSE's drop hook records every actor despite the PC name.
                lastDropped = e->reference;
                lastDroppedBase = e->baseObj;
            }
            forms("onactordrop", RE::TESForm::LookupByID(e->oldContainer), e->reference.get().get());
        }
        return next;
    }
} events;
}

void ResetEvents() {
    std::scoped_lock lock(mutex);
    handlers.clear();
    lastDropped.reset();
    lastDroppedBase = 0;
}
void SaveEvents(SKSE::SerializationInterface* stream) {
    std::scoped_lock lock(mutex);
    for (auto& [name, list] : handlers) for (auto entry : list) {
        auto length = static_cast<std::uint32_t>(name.size());
        if (!stream->OpenRecord(recordType, 1) || !stream->WriteRecordData(entry) ||
                !stream->WriteRecordData(length) || !stream->WriteRecordData(name.data(), length))
            SKSE::log::error("Could not save event handler {}", name);
    }
}
bool LoadEvent(SKSE::SerializationInterface* stream, std::uint32_t type, std::uint32_t version, std::uint32_t length) {
    if (type != recordType) return false;
    if (version != 1 || length < 16) return true;
    Handler entry;
    std::uint32_t size;
    if (stream->ReadRecordData(entry) != sizeof(entry) || stream->ReadRecordData(size) != sizeof(size) || size != length - 16 || size > 1024) return true;
    std::string name(size, '\0');
    if (stream->ReadRecordData(name.data(), size) != size) return true;
    for (auto ptr : {&entry.host, &entry.first, &entry.second}) {
        RE::FormID resolved;
        if (*ptr && !stream->ResolveFormID(*ptr, resolved)) return true;
        if (*ptr) *ptr = resolved;
    }
    std::scoped_lock lock(mutex);
    handlers[name].push_back(entry);
    return true;
}
void EventMessage(SKSE::MessagingInterface::Message* message) {
    if (message->type == SKSE::MessagingInterface::kDataLoaded) {
        auto source = RE::ScriptEventSourceHolder::GetSingleton();
        source->AddEventSink<RE::TESEquipEvent>(&events);
        source->AddEventSink<RE::TESHitEvent>(&events);
        source->AddEventSink<RE::TESDeathEvent>(&events);
        source->AddEventSink<RE::TESActivateEvent>(&events);
        source->AddEventSink<RE::TESCombatEvent>(&events);
        source->AddEventSink<RE::TESSpellCastEvent>(&events);
        source->AddEventSink<RE::TESMagicEffectApplyEvent>(&events);
        source->AddEventSink<RE::TESActiveEffectApplyRemoveEvent>(&events);
        source->AddEventSink<RE::TESContainerChangedEvent>(&events);
    } else if (message->type == SKSE::MessagingInterface::kPreLoadGame) {
        auto name = static_cast<const char*>(message->data);
        loadingSave = name ? name : "";
    } else if (message->type == SKSE::MessagingInterface::kPostLoadGame) {
        if (message->data) send("loadgame", nullptr, nullptr, nullptr, RE::BSFixedString(loadingSave));
        send("postloadgame", nullptr, nullptr, nullptr, message->data ? 1 : 0);
    } else if (message->type == SKSE::MessagingInterface::kSaveGame) {
        auto name = static_cast<const char*>(message->data);
        send("savegame", nullptr, nullptr, nullptr, RE::BSFixedString(name ? name : ""));
    }
}
bool RegisterEvents(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("EventHandler", "TES4Runtime", setHandler);
    vm->RegisterFunction("GetLastDroppedReference", "TES4Runtime", lastDroppedReference);
    vm->RegisterFunction("GetLastDroppedItem", "TES4Runtime", lastDroppedItem);
    return true;
}
