#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <algorithm>
#include <mutex>
#include <unordered_map>

int SourceInt(RE::StaticFunctionTag*, RE::TESForm*, std::string, int);

namespace {
struct Stack {
    RE::NiPointer<RE::TESObjectREFR> owner;
    RE::TESBoundObject* base;
    RE::ExtraDataList* extra;
    int count;
    RE::NiPointer<RE::TESObjectREFR> proxy;
};
std::recursive_mutex mutex;
std::unordered_map<int, std::vector<std::unique_ptr<Stack>>> cursors;
std::unordered_map<RE::TESForm*, Stack*> proxies;
int nextCursor = 0;

// InventoryEntryData returned by GetInventory is a copy; its ExtraDataLists
// belong to the container. Confirm the list still exists before dereferencing
// it after another script has transferred or consumed an item.
RE::ExtraDataList* extraFor(Stack& stack) {
    if (!stack.extra) return nullptr;
    auto changes = stack.owner->GetInventoryChanges();
    if (changes && changes->entryList) for (auto entry : *changes->entryList) {
        if (!entry || entry->object != stack.base || !entry->extraLists) continue;
        for (auto extra : *entry->extraLists) if (extra == stack.extra) return extra;
    }
    return nullptr;
}
RE::ExtraDataList* extraFor(RE::TESForm* form) {
    if (auto found = proxies.find(form); found != proxies.end()) return extraFor(*found->second);
    auto ref = form ? form->As<RE::TESObjectREFR>() : nullptr;
    return ref ? &ref->extraList : nullptr;
}
RE::ExtraDataList* writableExtra(Stack& stack) {
    if (stack.extra) return extraFor(stack);
    if (stack.count <= 0) return nullptr;
    auto changes = stack.owner->GetInventoryChanges();
    if (!changes) return nullptr;
    // CommonLib's multi-runtime ExtraDataList deliberately has no C++
    // constructor/layout. Allocate its actual runtime size with the game heap;
    // 1.6.629 added a vptr ahead of the two pointers and the eight-byte lock.
    // Take that vptr from an engine-created list, never an address constant.
    const bool hasVtable = REL::Module::IsAE() && REL::Module::get().version() >= SKSE::RUNTIME_SSE_1_6_629;
    auto extra = static_cast<RE::ExtraDataList*>(RE::calloc(1, hasVtable ? 0x20 : 0x18));
    if (!extra) return nullptr;
    if (hasVtable) std::memcpy(extra, &stack.owner->extraList, sizeof(void*));
    extra->SetCount(static_cast<std::uint16_t>(std::min(stack.count, 32767)));
    RE::InventoryEntryData* entry = nullptr;
    if (changes->entryList) for (auto candidate : *changes->entryList)
        if (candidate && candidate->object == stack.base) { entry = candidate; break; }
    if (!entry) {
        entry = new RE::InventoryEntryData(stack.base, 0);
        changes->AddEntryData(entry);
    }
    entry->AddExtraList(extra);
    stack.extra = extra;
    changes->changed = true;
    return extra;
}
RE::ExtraDataList* writableExtra(RE::TESForm* form) {
    if (auto found = proxies.find(form); found != proxies.end()) {
        found->second->owner->AddChange(RE::TESObjectREFR::ChangeFlags::kInventory);
        return writableExtra(*found->second);
    }
    return extraFor(form);
}
RE::TESForm* base(RE::TESForm* form) {
    if (form) if (auto ref = form->As<RE::TESObjectREFR>()) return ref->GetBaseObject();
    return form;
}
RE::TESForm* owner(RE::StaticFunctionTag*, RE::TESForm* form) {
    std::scoped_lock guard(mutex);
    if (form) if (auto cell = form->As<RE::TESObjectCELL>()) return cell->GetOwner();
    auto extra = extraFor(form);
    return extra ? extra->GetOwner() : nullptr;
}
void setOwner(RE::StaticFunctionTag*, RE::TESForm* form, RE::TESForm* value, bool save) {
    std::scoped_lock guard(mutex);
    value = base(value);
    if (value && !value->Is(RE::FormType::NPC, RE::FormType::Faction)) return;
    if (form) if (auto cell = form->As<RE::TESObjectCELL>()) {
        if (value && value->Is(RE::FormType::Faction)) cell->SetFactionOwner(value->As<RE::TESFaction>());
        else cell->SetActorOwner(value ? value->As<RE::TESNPC>() : nullptr);
        return;
    }
    if (auto extra = writableExtra(form)) extra->SetOwner(value);
    if (save && form) if (auto ref = form->As<RE::TESObjectREFR>()) ref->AddChange(RE::TESObjectREFR::ChangeFlags::kOwnershipExtra);
}
int begin(RE::StaticFunctionTag*, RE::TESObjectREFR* owner, RE::TESForm* filter) {
    std::scoped_lock guard(mutex);
    auto id = ++nextCursor;
    auto& entries = cursors[id];
    if (!owner) return id;
    for (const auto& [item, data] : owner->GetInventory()) {
        if (filter && item != base(filter)) continue;
        int remaining = data.first;
        if (remaining <= 0) continue;
        if (data.second && data.second->extraLists) for (auto extra : *data.second->extraLists) {
            if (!extra || remaining <= 0) continue;
            auto count = std::min(remaining, extra->GetCount());
            if (count <= 0) continue;
            entries.push_back(std::make_unique<Stack>(RE::NiPointer(owner), item, extra, count));
            remaining -= count;
        }
        while (remaining > 0) {
            int amount = std::min(remaining, 32767);
            entries.push_back(std::make_unique<Stack>(RE::NiPointer(owner), item, nullptr, amount));
            remaining -= amount;
        }
    }
    return id;
}
int size(RE::StaticFunctionTag*, int cursor) {
    std::scoped_lock guard(mutex);
    auto found = cursors.find(cursor);
    return found == cursors.end() ? 0 : static_cast<int>(found->second.size());
}
RE::TESObjectREFR* reference(RE::StaticFunctionTag*, int cursor, int index) {
    std::scoped_lock guard(mutex);
    auto found = cursors.find(cursor);
    if (found == cursors.end() || index < 0 || index >= found->second.size()) return nullptr;
    auto& stack = *found->second[index];
    if (!stack.proxy) {
        auto factory = RE::IFormFactory::GetFormFactoryByType(RE::FormType::Reference);
        auto created = factory ? factory->Create() : nullptr;
        auto ref = created ? created->As<RE::TESObjectREFR>() : nullptr;
        if (!ref) { SKSE::log::error("Cannot create an inventory reference"); return nullptr; }
        // GetNextID is the engine allocator, also exposed by libxse/CommonLibSSE.
        REL::Relocation<RE::FormID (*)(RE::TESDataHandler*)> nextID{RELOCATION_ID(13635, 13740)};
        ref->SetFormID(nextID(RE::TESDataHandler::GetSingleton()), true);
        ref->SetObjectReference(stack.base);
        stack.proxy.reset(ref);
        proxies[ref] = &stack;
    }
    return stack.proxy.get();
}
void end(RE::StaticFunctionTag*, int cursor) {
    std::scoped_lock guard(mutex);
    auto found = cursors.find(cursor);
    if (found == cursors.end()) return;
    for (auto& stack : found->second) if (stack->proxy) {
        proxies.erase(stack->proxy.get());
        stack->proxy->SetDelete(true);
    }
    cursors.erase(found);
}
bool removeReference(RE::StaticFunctionTag*, RE::TESForm* form, RE::TESObjectREFR* destination) {
    std::scoped_lock guard(mutex);
    auto found = proxies.find(form);
    if (found == proxies.end()) return false;
    auto& stack = *found->second;
    if (stack.count <= 0 || stack.owner.get() == destination) return false;
    auto extra = extraFor(stack);
    if (stack.extra && !extra) return false;
    auto inventory = stack.owner->GetInventoryCounts();
    auto available = inventory.find(stack.base);
    int count = available == inventory.end() ? 0 : std::min(stack.count, available->second);
    if (count <= 0) return false;
    stack.owner->RemoveItem(stack.base, count, destination ? RE::ITEM_REMOVE_REASON::kStoreInContainer :
        RE::ITEM_REMOVE_REASON::kRemove, extra, destination);
    stack.count = 0;
    stack.extra = nullptr;
    return true;
}
bool equip(RE::StaticFunctionTag*, RE::TESForm* form, bool worn) {
    std::scoped_lock guard(mutex);
    auto found = proxies.find(form);
    if (found == proxies.end()) return false;
    auto& stack = *found->second;
    auto actor = stack.owner->As<RE::Actor>();
    auto extra = extraFor(stack);
    if (!actor || stack.count <= 0 || (stack.extra && !extra)) return false;
    auto manager = RE::ActorEquipManager::GetSingleton();
    if (worn) manager->EquipObject(actor, stack.base, extra, 1, nullptr, false, false, true, true);
    else manager->UnequipObject(actor, stack.base, extra, 1, nullptr, false, false, true, true);
    return true;
}
bool equipped(RE::StaticFunctionTag*, RE::TESForm* form) {
    std::scoped_lock guard(mutex);
    auto extra = extraFor(form);
    return extra && (extra->HasType<RE::ExtraWorn>() || extra->HasType<RE::ExtraWornLeft>());
}
int currentSoul(RE::StaticFunctionTag*, RE::TESForm* form) {
    std::scoped_lock guard(mutex);
    if (auto extra = extraFor(form))
        if (auto soul = extra->GetByType<RE::ExtraSoul>()) return static_cast<int>(soul->GetContainedSoul());
    auto item = base(form);
    auto gem = item ? item->As<RE::TESSoulGem>() : nullptr;
    return gem ? static_cast<int>(gem->GetContainedSoul()) : 0;
}
int refCount(RE::StaticFunctionTag*, RE::TESForm* form) {
    std::scoped_lock guard(mutex);
    if (auto found = proxies.find(form); found != proxies.end()) {
        auto& stack = *found->second;
        auto extra = extraFor(stack);
        return stack.extra ? (extra ? extra->GetCount() : 0) : stack.count;
    }
    auto extra = extraFor(form);
    return extra ? extra->GetCount() : 0;
}
RE::TESObjectREFR* container(RE::StaticFunctionTag*, RE::TESForm* form) {
    std::scoped_lock guard(mutex);
    auto found = proxies.find(form);
    return found == proxies.end() ? nullptr : found->second->owner.get();
}
float health(RE::StaticFunctionTag*, RE::TESForm* form) {
    std::scoped_lock guard(mutex);
    if (form) if (auto actor = form->As<RE::Actor>()) return actor->AsActorValueOwner()->GetActorValue(RE::ActorValue::kHealth);
    auto maximum = SourceInt(nullptr, base(form), "ObjectHealth", 0);
    auto extra = extraFor(form);
    auto condition = extra ? extra->GetByType<RE::ExtraHealth>() : nullptr;
    return maximum * (condition ? condition->health : 1.0f);
}
void setHealth(RE::StaticFunctionTag*, RE::TESForm* form, float value) {
    std::scoped_lock guard(mutex);
    if (form) if (auto actor = form->As<RE::Actor>()) { actor->AsActorValueOwner()->SetActorValue(RE::ActorValue::kHealth, value); return; }
    auto maximum = SourceInt(nullptr, base(form), "ObjectHealth", 0);
    auto extra = maximum > 0 ? writableExtra(form) : nullptr;
    if (!extra) return;
    auto condition = extra->GetByType<RE::ExtraHealth>();
    auto ratio = std::max(0.0f, value / maximum);
    if (condition) condition->health = ratio;
    else extra->Add(new RE::ExtraHealth(ratio));
}
float charge(RE::StaticFunctionTag*, RE::TESForm* form) {
    std::scoped_lock guard(mutex);
    auto extra = extraFor(form);
    if (extra) if (auto charge = extra->GetByType<RE::ExtraCharge>()) return charge->charge;
    return static_cast<float>(SourceInt(nullptr, base(form), "ObjectCharge", 0));
}
void setCharge(RE::StaticFunctionTag*, RE::TESForm* form, float value) {
    std::scoped_lock guard(mutex);
    auto extra = writableExtra(form);
    if (!extra) return;
    auto charge = extra->GetByType<RE::ExtraCharge>();
    if (charge) charge->charge = value;
    else {
        auto added = new RE::ExtraCharge();
        added->charge = value;
        extra->Add(added);
    }
}
}

void ResetInventory(SKSE::MessagingInterface::Message* message) {
    if (message->type == SKSE::MessagingInterface::kPreLoadGame || message->type == SKSE::MessagingInterface::kNewGame) {
        std::scoped_lock guard(mutex);
        while (!cursors.empty()) end(nullptr, cursors.begin()->first);
    }
}

bool RegisterInventory(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("GetCurrentSoulLevel", "TES4Runtime", currentSoul);
    vm->RegisterFunction("RemoveInventoryReference", "TES4Runtime", removeReference);
    vm->RegisterFunction("EquipInventoryReference", "TES4Runtime", equip);
    vm->RegisterFunction("GetOwner", "TES4Runtime", owner);
    vm->RegisterFunction("SetOwner", "TES4Runtime", setOwner);
    vm->RegisterFunction("BeginInventory", "TES4Runtime", begin);
    vm->RegisterFunction("InventorySize", "TES4Runtime", size);
    vm->RegisterFunction("InventoryReference", "TES4Runtime", reference);
    vm->RegisterFunction("EndInventory", "TES4Runtime", end);
    vm->RegisterFunction("IsEquipped", "TES4Runtime", equipped);
    vm->RegisterFunction("GetRefCount", "TES4Runtime", refCount);
    vm->RegisterFunction("GetInventoryContainer", "TES4Runtime", container);
    vm->RegisterFunction("GetCurrentHealth", "TES4Runtime", health);
    vm->RegisterFunction("SetCurrentHealth", "TES4Runtime", setHealth);
    vm->RegisterFunction("GetCurrentCharge", "TES4Runtime", charge);
    vm->RegisterFunction("SetCurrentCharge", "TES4Runtime", setCharge);
    return true;
}
