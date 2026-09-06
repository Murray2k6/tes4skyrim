#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <algorithm>
#include <map>
#include <unordered_set>

int SourceInt(RE::StaticFunctionTag*, RE::TESForm*, std::string, int);

namespace {
using Tag = RE::StaticFunctionTag;
constexpr int markerTypes[] = {0, 5, 4, 1, 8, 6, 15, 11, 2, 3, 34, 34, 11};
RE::TESWorldSpace* mapWorld(RE::TESWorldSpace* world) {
    std::unordered_set<RE::TESWorldSpace*> seen;
    while (world && world->parentWorld && world->parentUseFlags.all(RE::TESWorldSpace::ParentUseFlag::kUseMapData) && seen.insert(world).second)
        world = world->parentWorld;
    return world;
}
RE::TESWorldSpace* currentWorld() {
    auto player = RE::PlayerCharacter::GetSingleton();
    if (!player) return nullptr;
    auto world = player->GetWorldspace();
    return mapWorld(world ? world : player->GetPlayerRuntimeData().cachedWorldSpace);
}
int markerType(Tag*, RE::TESObjectREFR* ref) {
    auto extra = ref ? ref->extraList.GetByType<RE::ExtraMapMarker>() : nullptr;
    if (!extra || !extra->mapData) return 0;
    auto target = static_cast<int>(extra->mapData->type.get());
    auto authored = SourceInt(nullptr, ref, "MapMarkerType", -1);
    if (authored >= 0 && authored < std::size(markerTypes) && markerTypes[authored] == target) return authored;
    for (int i = 0; i < std::size(markerTypes); ++i) if (markerTypes[i] == target) return i;
    return 0;
}
RE::TESObjectREFR* worldDoor(Tag*) {
    auto player = RE::PlayerCharacter::GetSingleton();
    auto path = player ? player->GetPlayerRuntimeData().playerMarkerPath : nullptr;
    if (!path) return nullptr;
    auto world = currentWorld();
    for (const auto& node : path->unk18) {
        auto door = node.unk00;
        if (!door || !door->GetBaseObject() || !door->GetBaseObject()->Is(RE::FormType::Door)) continue;
        if (door->GetWorldspace() && mapWorld(door->GetWorldspace()) == world) return door;
        auto teleport = door->extraList.GetByType<RE::ExtraTeleport>();
        auto linked = teleport && teleport->teleportData ? teleport->teleportData->linkedDoor.get() : nullptr;
        if (linked && linked->GetWorldspace() && mapWorld(linked->GetWorldspace()) == world) return linked.get();
    }
    return nullptr;
}
RE::GPtr<RE::IMenu> selectedMarker(RE::GFxValue& selected) {
    auto ui = RE::UI::GetSingleton();
    auto menu = ui ? ui->GetMenu<RE::MapMenu>() : nullptr;
    RE::GFxValue callback, scope;
    // Read the registered MapMenu instance, shared by vanilla and SkyUI,
    // through Scaleform's actual callback table rather than a guessed root.
    if (!menu || !menu->uiMovie ||
        !menu->uiMovie->GetVariable(&callback, "_global.gfx.io.GameDelegate.callBackHash.SetSelectedMarker") ||
        !callback.IsArray() || !callback.GetElement(0, &scope) || !scope.IsObject() ||
        !scope.GetMember("SelectedMarker", &selected) || !selected.IsObject()) return nullptr;
    return menu;
}
std::string selectedName(Tag*) {
    RE::GFxValue selected, label;
    if (selectedMarker(selected) && selected.GetMember("label", &label) && label.IsString()) return label.GetString();
    return {};
}
RE::TESObjectREFR* selectedReference(Tag*) {
    RE::GFxValue selected, index, label;
    auto menu = selectedMarker(selected);
    if (!menu || !selected.GetMember("Index", &index) || !index.IsNumber() ||
        !selected.GetMember("label", &label) || !label.IsString()) return nullptr;
    auto map = static_cast<RE::MapMenu*>(menu.get());
    const auto i = static_cast<int>(index.GetNumber());
    const auto& entries = map->GetRuntimeData2().unk30470;
    if (i >= 0 && i < entries.size()) {
        auto entry = entries[i];
        auto ref = entry && entry->unk10 ? entry->unk10->As<RE::TESObjectREFR>() : nullptr;
        if (ref && ref->extraList.HasType<RE::ExtraMapMarker>() && std::string_view(ref->GetName()) == label.GetString()) return ref;
    }
    SKSE::log::warn("Map selection could not resolve marker {} at index {}", label.GetString(), i);
    return nullptr;
}
}

std::vector<RE::TESForm*> MapMarkers(int visibility, int type) {
    std::map<RE::FormID, RE::TESForm*> found;
    auto world = currentWorld();
    if (!world) return {};
    auto add = [&](RE::TESObjectREFR* ref) {
        auto extra = ref && !ref->IsDeleted() ? ref->extraList.GetByType<RE::ExtraMapMarker>() : nullptr;
        if (!extra || !extra->mapData || (type && markerType(nullptr, ref) != type)) return RE::BSContainer::ForEachResult::kContinue;
        auto flags = extra->mapData->flags;
        if (visibility != 2 && (ref->IsDisabled() || !flags.all(RE::MapMarkerData::Flag::kVisible) ||
            (visibility == 0 && !flags.all(RE::MapMarkerData::Flag::kCanTravelTo)))) return RE::BSContainer::ForEachResult::kContinue;
        found[ref->GetFormID()] = ref;
        return RE::BSContainer::ForEachResult::kContinue;
    };
    // Persistent world refs exist before the map menu is opened. Include
    // child worlds only when their authored parent flags share this map.
    if (auto data = RE::TESDataHandler::GetSingleton()) for (auto candidate : data->GetFormArray<RE::TESWorldSpace>()) {
        if (mapWorld(candidate) != world) continue;
        if (candidate->persistentCell) candidate->persistentCell->ForEachReference(add);
        for (const auto& [key, refs] : candidate->fixedPersistentRefMap) for (auto ref : refs) if (ref) add(ref.get());
    }
    std::vector<RE::TESForm*> result;
    for (auto [id, ref] : found) result.push_back(ref);
    return result;
}

bool RegisterMap(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("GetWorldMapDoor", "TES4Runtime", worldDoor);
    vm->RegisterFunction("GetMapMarkerType", "TES4Runtime", markerType);
    vm->RegisterFunction("GetMapMenuMarkerName", "TES4Runtime", selectedName);
    vm->RegisterFunction("GetMapMenuMarkerRef", "TES4Runtime", selectedReference);
    return true;
}
