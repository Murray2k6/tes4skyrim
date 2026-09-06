#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <cmath>
#include <cstdio>

int SourceInt(RE::StaticFunctionTag*, RE::TESForm*, std::string, int);
int SourceObjectType(RE::TESForm*);
RE::TESForm* SourceByEditorID(std::string);

namespace {
float frameSeconds(RE::StaticFunctionTag*) { return RE::GetSecondsSinceLastFrame(); }

void setCombatStyle(RE::StaticFunctionTag*, RE::Actor* actor, RE::TESCombatStyle* style) {
    if (!actor || !style) return;
    const auto handle = actor->GetHandle();
    SKSE::GetTaskInterface()->AddTask([handle, style] {
        auto subject = handle.get();
        auto factory = RE::IFormFactory::GetConcreteFormFactoryByType<RE::Script>();
        if (!subject || !factory) return;
        auto command = factory->Create();
        if (!command) return;
        char text[48];
        std::snprintf(text, sizeof(text), "SetCombatStyle %08X", style->GetFormID());
        // The engine command sets ExtraCombatStyle, saves the actor change,
        // refreshes its combat controller and updates current combat.
        command->SetCommand(text);
        command->CompileAndRun(subject.get());
        delete command;
    });
}
void trespassAlarm(RE::StaticFunctionTag*, RE::Actor* subject, RE::Actor* criminal) {
    if (!subject || !criminal) return;
    const auto witness = subject->GetHandle(), offender = criminal->GetHandle();
    SKSE::GetTaskInterface()->AddTask([witness, offender] {
        auto subject = witness.get(), criminal = offender.get();
        // Skyrim's SendTrespassAlarm command passes the witness's base owner
        // and -1 for automatic crime selection to the criminal's native alarm.
        if (subject && criminal) criminal->TrespassAlarm(subject.get(), subject->GetBaseObject(), -1);
    });
}
int characterState(RE::StaticFunctionTag*, RE::Actor* actor) {
    const auto controller = actor ? actor->GetCharController() : nullptr;
    return controller ? static_cast<int>(controller->context.currentState) : -1;
}
float velocity(RE::StaticFunctionTag*, RE::Actor* actor, int axis) {
    const auto cell = actor ? actor->GetParentCell() : nullptr;
    const auto world = cell ? cell->GetbhkWorld() : nullptr;
    if (!world || axis < 0 || axis > 2) return 0;
    RE::BSReadLockGuard lock(world->worldLock);
    const auto controller = actor->GetCharController();
    if (!controller) return 0;
    RE::hkVector4 value;
    controller->GetLinearVelocityImpl(value);
    float components[4];
    _mm_storeu_ps(components, value.quad);
    return components[axis] * RE::bhkWorld::GetWorldScaleInverse();
}
int setVelocity(RE::StaticFunctionTag*, RE::Actor* actor, float x, float y, float z, bool verticalOnly) {
    const auto cell = actor ? actor->GetParentCell() : nullptr;
    const auto world = cell ? cell->GetbhkWorld() : nullptr;
    if (!world || !std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) return 0;
    RE::BSWriteLockGuard lock(world->worldLock);
    const auto controller = actor->GetCharController();
    if (!controller) return 0;
    // xOBSE Commands_Physics.cpp reads/writes controller velocity in game
    // units. Its vertical-only command leaves the current X and Y intact.
    const float scale = RE::bhkWorld::GetWorldScale();
    RE::hkVector4 value{x * scale, y * scale, z * scale, 0};
    if (verticalOnly) {
        RE::hkVector4 current;
        controller->GetLinearVelocityImpl(current);
        float components[4];
        _mm_storeu_ps(components, current.quad);
        value = RE::hkVector4{components[0], components[1], z * scale, components[3]};
    }
    controller->SetLinearVelocityImpl(value);
    return verticalOnly ? 1 : 0;
}
float startingCoordinate(RE::StaticFunctionTag*, RE::TESObjectREFR* ref, int axis, bool angle) {
    if (!ref || axis < 0 || axis > 2) return 0;
    const auto point = angle ? ref->GetStartingAngle() : ref->GetStartingLocation();
    const auto value = axis == 0 ? point.x : axis == 1 ? point.y : point.z;
    return angle ? value * (180.0f / 3.14159265358979323846f) : value;
}
float teleportCoordinate(RE::StaticFunctionTag*, RE::TESObjectREFR* ref, int axis) {
    if (!ref || !ref->GetBaseObject() || !ref->GetBaseObject()->As<RE::TESObjectDOOR>()) return 0;
    const auto extra = ref->extraList.GetByType<RE::ExtraTeleport>();
    const auto data = extra ? extra->teleportData : nullptr;
    if (!data) return 0;
    if (axis == 3) return data->rotation.z * (180.0f / 3.14159265358979323846f);
    return axis == 0 ? data->position.x : axis == 1 ? data->position.y : axis == 2 ? data->position.z : 0;
}
RE::TESWorldSpace* parentWorld(RE::StaticFunctionTag*, RE::TESWorldSpace* world) {
    return world ? world->parentWorld : nullptr;
}
RE::TESObjectCELL* destinationCell(RE::TESObjectCELL* cell, RE::BSFixedString editorID) {
    if (!cell && !editorID.empty()) {
        auto form = SourceByEditorID(editorID.c_str());
        cell = form ? form->As<RE::TESObjectCELL>() : nullptr;
    }
    return cell;
}
void cellPublic(RE::StaticFunctionTag*, RE::TESObjectCELL* cell, RE::BSFixedString editorID, bool enabled) {
    if (auto target = destinationCell(cell, editorID)) target->SetPublic(enabled);
    else SKSE::log::warn("SetCellPublicFlag: missing destination {}", editorID.c_str());
}
void cellOwner(RE::StaticFunctionTag*, RE::TESObjectCELL* cell, RE::BSFixedString editorID, RE::TESForm* owner) {
    if (owner) if (auto ref = owner->As<RE::TESObjectREFR>()) owner = ref->GetBaseObject();
    if (owner && !owner->Is(RE::FormType::NPC, RE::FormType::Faction)) return;
    if (auto target = destinationCell(cell, editorID)) target->SetOwner(owner);
    else SKSE::log::warn("SetCellOwnership: missing destination {}", editorID.c_str());
}
void cellName(RE::StaticFunctionTag*, RE::TESObjectCELL* cell, RE::BSFixedString editorID, RE::BSFixedString name) {
    if (auto target = destinationCell(cell, editorID)) {
        target->SetFullName(name.c_str());
        target->AddChange(RE::TESObjectCELL::ChangeFlags::kFullName);
    } else SKSE::log::warn("SetCellFullName: missing destination {}", editorID.c_str());
}
float terrainHeight(RE::StaticFunctionTag*, float x, float y) {
    float height = 0.0f;
    auto world = RE::TES::GetSingleton();
    if (world && std::isfinite(x) && std::isfinite(y) && world->GetLandHeight({x, y, 0.0f}, height)) return height;
    return 0.0f;
}
void positionCell(RE::StaticFunctionTag*, RE::TESObjectREFR* ref, RE::TESObjectCELL* destination,
                  RE::BSFixedString editorID, float x, float y, float z, float angle) {
    destination = destinationCell(destination, editorID);
    if (!ref || !destination) {
        SKSE::log::warn("PositionCell: missing reference or destination {}", editorID.c_str());
        return;
    }
    // Oblivion.exe 0x508E20 copies the authored Z rotation as radians and
    // leaves a reference already in the destination cell alone (0x508EC2).
    if (ref->GetParentCell() == destination) return;
    if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z) || !std::isfinite(angle)) return;
    constexpr float tau = 6.2831853071795864769f;
    angle = std::fmod(angle, tau);
    if (angle < 0) angle += tau;
    const RE::NiPoint3 position{x, y, z}, rotation{0, 0, angle};
    using Move = void(RE::TESObjectREFR*, const RE::ObjectRefHandle&, RE::TESObjectCELL*,
                      RE::TESWorldSpace*, const RE::NiPoint3&, const RE::NiPoint3&);
    REL::Relocation<Move*> move{RE::Offset::TESObjectREFR::MoveTo};
    move(ref, RE::ObjectRefHandle{}, destination, destination->GetRuntimeData().worldSpace, position, rotation);
}

void positionWorld(RE::StaticFunctionTag*, RE::TESObjectREFR* ref, RE::TESWorldSpace* world,
                   float x, float y, float z, float angle) {
    if (!ref || !world || !std::isfinite(x) || !std::isfinite(y) ||
        !std::isfinite(z) || !std::isfinite(angle)) return;
    const auto cx = std::floor(x / 4096.0f), cy = std::floor(y / 4096.0f);
    if (cx < -32768 || cx > 32767 || cy < -32768 || cy > 32767) return;
    const RE::CellID key{static_cast<std::int16_t>(cy), static_cast<std::int16_t>(cx)};
    const auto it = world->cellMap.find(key);
    auto destination = it != world->cellMap.end() ? it->second : world->persistentCell;
    if (!destination) {
        SKSE::log::warn("PositionWorld: destination world {:08X} has no cell", world->GetFormID());
        return;
    }
    // Oblivion.exe PositionWorld/PosWorld 0x508C30 copies angleZ directly
    // into the radian rotation and resolves the cell in the requested world.
    constexpr float tau = 6.2831853071795864769f;
    angle = std::fmod(angle, tau);
    if (angle < 0) angle += tau;
    using Move = void(RE::TESObjectREFR*, const RE::ObjectRefHandle&, RE::TESObjectCELL*,
                      RE::TESWorldSpace*, const RE::NiPoint3&, const RE::NiPoint3&);
    REL::Relocation<Move*> move{RE::Offset::TESObjectREFR::MoveTo};
    move(ref, RE::ObjectRefHandle{}, destination, world, RE::NiPoint3{x, y, z}, RE::NiPoint3{0, 0, angle});
}

RE::TESObjectCELL* cell(RE::TESForm* form) {
    if (!form) return nullptr;
    if (auto ref = form->As<RE::TESObjectREFR>()) return ref->GetParentCell();
    return form->As<RE::TESObjectCELL>();
}
bool activatable(RE::StaticFunctionTag*, RE::TESObjectREFR* ref) {
    if (!ref) return false;
    auto type = SourceObjectType(ref);
    return (type >= 18 && type <= 26) || type == 27 || (type >= 31 && type <= 36) ||
           (type >= 38 && type <= 40) || type == 42;
}
bool offLimits(RE::StaticFunctionTag*, RE::TESObjectREFR* ref) { return ref && ref->IsOffLimits(); }
bool deletable(RE::StaticFunctionTag*, RE::TESObjectREFR* ref) {
    return ref && ref->IsDynamicForm() && !(ref->GetFormFlags() & RE::TESForm::RecordFlags::kTemporary) && ref->IsDisabled();
}
RE::TESObjectREFR* linkedDoor(RE::StaticFunctionTag*, RE::TESObjectREFR* ref) {
    if (ref) if (auto teleport = ref->extraList.GetByType<RE::ExtraTeleport>())
        if (teleport->teleportData) return teleport->teleportData->linkedDoor.get().get();
    return nullptr;
}
bool hasWater(RE::StaticFunctionTag*, RE::TESForm* form) {
    auto parent = cell(form);
    return parent && parent->cellFlags.all(RE::TESObjectCELL::Flag::kHasWater);
}
float waterHeight(RE::StaticFunctionTag*, RE::TESObjectREFR* ref) {
    auto parent = ref ? ref->GetParentCell() : nullptr;
    if (!parent) return 0;
    return parent->IsInteriorCell() ? parent->GetRuntimeData().waterHeight : parent->GetExteriorWaterHeight();
}
bool inOblivion(RE::StaticFunctionTag*, RE::TESObjectREFR* ref) {
    auto parent = ref ? ref->GetParentCell() : nullptr;
    if (!parent) return false;
    if (parent->IsInteriorCell()) return (SourceInt(nullptr, parent, "Flags", 0) & 8) != 0;
    return (SourceInt(nullptr, ref->GetWorldspace(), "Flags", 0) & 4) != 0;
}
int sourceMod(RE::StaticFunctionTag*, RE::TESForm* form) {
    auto file = form ? form->GetFile(0) : nullptr;
    return file ? file->compileIndex : 255;
}
bool persistent(RE::StaticFunctionTag*, RE::TESObjectREFR* ref) { return ref && ref->IsPersistent(); }
RE::TESKey* openKey(RE::StaticFunctionTag*, RE::TESObjectREFR* ref) {
    auto lock = ref ? ref->GetLock() : nullptr;
    return lock ? lock->key : nullptr;
}
RE::TESClimate* climate(RE::StaticFunctionTag*) { return RE::Sky::GetSingleton()->currentClimate; }
float boundingRadius(RE::StaticFunctionTag*, RE::TESObjectREFR* ref) {
    auto node = ref ? ref->Get3D() : nullptr;
    return node ? node->worldBound.radius : -1;
}
RE::TESForm* base(RE::TESForm* form) {
    if (form) if (auto ref = form->As<RE::TESObjectREFR>()) return ref->GetBaseObject();
    return form;
}
float weight(RE::StaticFunctionTag*, RE::TESForm* form) {
    form = base(form);
    return form ? form->GetWeight() : 0;
}
RE::EnchantmentItem* enchantment(RE::StaticFunctionTag*, RE::TESForm* form) {
    form = base(form);
    auto enchanted = form ? form->As<RE::TESEnchantableForm>() : nullptr;
    return enchanted ? enchanted->formEnchanting : nullptr;
}
RE::TESPackage* nthPackage(RE::StaticFunctionTag*, RE::TESForm* form, int index) {
    form = base(form);
    auto actor = form ? form->As<RE::TESNPC>() : nullptr;
    if (!actor || index < 0) return nullptr;
    for (auto package : actor->aiPackages.packages) if (package && index-- == 0) return package;
    return nullptr;
}
int numPackages(RE::StaticFunctionTag*, RE::TESForm* form) {
    form = base(form);
    auto actor = form ? form->As<RE::TESNPC>() : nullptr;
    int count = 0;
    if (actor) for (auto package : actor->aiPackages.packages) if (package) ++count;
    return count;
}
int currentPackageType(RE::StaticFunctionTag*, RE::Actor* actor) {
    auto package = actor ? actor->GetCurrentPackage() : nullptr;
    if (!package) return -1;
    const int authored = SourceInt(nullptr, package, "PackageType", -1);
    if (authored >= 0) return authored;
    // Only the legacy procedures 0..11 share TES4's enumeration. Skyrim's
    // template type 18 is not the behavior of a converted package.
    const int type = static_cast<int>(package->packData.packType.get());
    return type <= 11 ? type : -1;
}
RE::TESObjectREFR* packageTarget(RE::StaticFunctionTag*, RE::Actor* actor) {
    auto process = actor ? actor->GetActorRuntimeData().currentProcess : nullptr;
    if (!process) return nullptr;
    auto state = &process->currentPackage;
    if (process->middleHigh && process->middleHigh->runOncePackage.package)
        state = &process->middleHigh->runOncePackage;
    RE::BSSpinLockGuard guard(state->packageLock);
    return state->target.get().get();
}
void setAlpha(RE::StaticFunctionTag*, RE::TESObjectREFR* ref, float opacity) {
    if (!ref) return;
    const auto handle = ref->CreateRefHandle();
    SKSE::GetTaskInterface()->AddTask([handle, opacity] {
        if (auto subject = handle.get()) {
            if (auto actor = subject->As<RE::Actor>()) actor->SetAlpha(opacity);
            else if (auto node = subject->Get3D()) node->UpdateMaterialAlpha(opacity, false);
        }
    });
}
void scriptPackage(RE::StaticFunctionTag*, RE::Actor* actor, RE::TESPackage* package) {
    if (!actor || !package) return;
    const auto handle = actor->GetHandle();
    SKSE::GetTaskInterface()->AddTask([handle, package] {
        if (auto subject = handle.get()) {
            // Let the engine create the actor's interrupt-package state and
            // run the package's own procedure tree. The PACK is plugin-owned.
            subject->PutCreatedPackage(package, true, false, true);
            if (subject->GetCurrentPackage() != package)
                SKSE::log::warn("Script package {:08X} has not started on {:08X}",
                    package->GetFormID(), subject->GetFormID());
        }
    });
}
void removeScriptPackage(RE::StaticFunctionTag*, RE::Actor* actor) {
    if (!actor) return;
    const auto handle = actor->GetHandle();
    SKSE::GetTaskInterface()->AddTask([handle] {
        if (auto subject = handle.get()) {
            auto process = subject->GetActorRuntimeData().currentProcess;
            auto package = process && process->middleHigh ? process->middleHigh->runOncePackage.package : nullptr;
            // Combat/dialogue interrupts are engine-created packages. Only
            // end an authored converted package, including after save/load.
            if (package && SourceInt(nullptr, package, "PackageType", -1) >= 0) {
                subject->EndInterruptPackage(false);
                subject->EvaluatePackage();
            }
        }
    });
}
}

bool RegisterReferences(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("GetFrameSeconds", "TES4Runtime", frameSeconds);
    vm->RegisterFunction("SetCombatStyle", "TES4Runtime", setCombatStyle);
    vm->RegisterFunction("SendTrespassAlarm", "TES4Runtime", trespassAlarm);
    vm->RegisterFunction("GetCharacterState", "TES4Runtime", characterState);
    vm->RegisterFunction("GetVelocity", "TES4Runtime", velocity);
    vm->RegisterFunction("SetVelocity", "TES4Runtime", setVelocity);
    vm->RegisterFunction("GetStartingCoordinate", "TES4Runtime", startingCoordinate);
    vm->RegisterFunction("GetParentWorld", "TES4Runtime", parentWorld);
    vm->RegisterFunction("SetCellPublic", "TES4Runtime", cellPublic);
    vm->RegisterFunction("SetCellOwner", "TES4Runtime", cellOwner);
    vm->RegisterFunction("SetCellName", "TES4Runtime", cellName);
    vm->RegisterFunction("GetTerrainHeight", "TES4Runtime", terrainHeight);
    vm->RegisterFunction("PositionCell", "TES4Runtime", positionCell);
    vm->RegisterFunction("PositionWorld", "TES4Runtime", positionWorld);
    vm->RegisterFunction("IsActivatable", "TES4Runtime", activatable);
    vm->RegisterFunction("IsOffLimits", "TES4Runtime", offLimits);
    vm->RegisterFunction("CanDeleteReference", "TES4Runtime", deletable);
    vm->RegisterFunction("GetLinkedDoor", "TES4Runtime", linkedDoor);
    vm->RegisterFunction("GetTeleportCoordinate", "TES4Runtime", teleportCoordinate);
    vm->RegisterFunction("HasWater", "TES4Runtime", hasWater);
    vm->RegisterFunction("GetParentCellWaterHeight", "TES4Runtime", waterHeight);
    vm->RegisterFunction("IsInOblivion", "TES4Runtime", inOblivion);
    vm->RegisterFunction("GetSourceModIndex", "TES4Runtime", sourceMod);
    vm->RegisterFunction("IsPersistent", "TES4Runtime", persistent);
    vm->RegisterFunction("GetOpenKey", "TES4Runtime", openKey);
    vm->RegisterFunction("GetCurrentClimateID", "TES4Runtime", climate);
    vm->RegisterFunction("GetBoundingRadius", "TES4Runtime", boundingRadius);
    vm->RegisterFunction("GetWeight", "TES4Runtime", weight);
    vm->RegisterFunction("GetEnchantment", "TES4Runtime", enchantment);
    vm->RegisterFunction("GetNthPackage", "TES4Runtime", nthPackage);
    vm->RegisterFunction("GetNumPackages", "TES4Runtime", numPackages);
    vm->RegisterFunction("GetCurrentAIPackage", "TES4Runtime", currentPackageType);
    vm->RegisterFunction("GetPackageTarget", "TES4Runtime", packageTarget);
    vm->RegisterFunction("SetAlpha", "TES4Runtime", setAlpha);
    vm->RegisterFunction("AddScriptPackage", "TES4Runtime", scriptPackage);
    vm->RegisterFunction("RemoveScriptPackage", "TES4Runtime", removeScriptPackage);
    return true;
}
