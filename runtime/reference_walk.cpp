#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <algorithm>
#include <mutex>
#include <unordered_map>

int SourceObjectType(RE::TESForm*);

namespace {
struct Walk { std::vector<RE::FormID> refs; std::size_t position = 0; };
std::recursive_mutex mutex;
std::unordered_map<std::string, Walk> walks;

bool matches(RE::TESObjectREFR* ref, int type, bool taken, bool deleted) {
    if (!ref || !ref->GetBaseObject()) return false;
    if (type == 90) return ref->IsDeleted();
    if (!deleted && ref->IsDeleted()) return false;
    if (!taken && ref->IsDeleted() && ref->IsDisabled()) return false;
    if (!type) return true;
    if (type == 72) return ref->extraList.HasType<RE::ExtraMapMarker>();
    if (type == 71) return skyrim_cast<RE::Projectile*>(ref) != nullptr;
    if (ref == RE::PlayerCharacter::GetSingleton()) return false;
    auto sourceType = SourceObjectType(ref);
    if (type == 69) return sourceType == 35 || sourceType == 36;
    if (type == 70) return ref->GetBaseObject()->IsInventoryObject();
    return sourceType == type;
}

RE::TESObjectREFR* next(RE::StaticFunctionTag*, std::string script) {
    std::scoped_lock guard(mutex);
    auto found = walks.find(script);
    if (found == walks.end()) return nullptr;
    auto& walk = found->second;
    while (walk.position < walk.refs.size()) {
        auto form = RE::TESForm::LookupByID<RE::TESObjectREFR>(walk.refs[walk.position++]);
        if (form) return form;
    }
    walks.erase(found);
    return nullptr;
}

Walk scan(RE::TESObjectCELL* origin, int type, int depth, bool taken, bool deleted) {
    Walk walk;
    if (!origin) origin = RE::PlayerCharacter::GetSingleton()->GetParentCell();
    if (!origin) return walk;
    std::vector<RE::TESObjectCELL*> cells;
    auto world = origin->GetRuntimeData().worldSpace;
    auto coords = origin->IsExteriorCell() ? origin->GetCoordinates() : nullptr;
    if (world && coords && depth > 0) {
        for (const auto& [key, cell] : world->cellMap) {
            if (!cell || !cell->IsExteriorCell()) continue;
            auto position = cell->GetCoordinates();
            if (position && std::abs(position->cellX - coords->cellX) <= depth &&
                std::abs(position->cellY - coords->cellY) <= depth) cells.push_back(cell);
        }
        std::sort(cells.begin(), cells.end(), [](auto a, auto b) {
            auto x = a->GetCoordinates(), y = b->GetCoordinates();
            return std::pair(x->cellY, x->cellX) < std::pair(y->cellY, y->cellX);
        });
    } else cells.push_back(origin);
    for (auto cell : cells) cell->ForEachReference([&](RE::TESObjectREFR* ref) {
        if (matches(ref, type, taken, deleted)) walk.refs.push_back(ref->GetFormID());
        return RE::BSContainer::ForEachResult::kContinue;
    });
    return walk;
}

RE::TESObjectREFR* first(RE::StaticFunctionTag*, std::string script, RE::TESObjectCELL* origin,
                       int type, int depth, bool taken, bool deleted) {
    std::scoped_lock guard(mutex);
    walks[script] = scan(origin, type, depth, taken, deleted);
    return next(nullptr, script);
}
int count(RE::StaticFunctionTag*, RE::TESObjectCELL* origin, int type, int depth, bool taken, bool deleted) {
    return static_cast<int>(scan(origin, type, depth, taken, deleted).refs.size());
}
}

void ResetReferenceWalks(SKSE::MessagingInterface::Message* message) {
    if (message->type == SKSE::MessagingInterface::kPreLoadGame || message->type == SKSE::MessagingInterface::kNewGame) {
        std::scoped_lock guard(mutex);
        walks.clear();
    }
}

bool RegisterReferenceWalk(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("GetFirstRef", "TES4Runtime", first);
    vm->RegisterFunction("GetNextRef", "TES4Runtime", next);
    vm->RegisterFunction("GetNumRefs", "TES4Runtime", count);
    return true;
}
