#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <cmath>

int SourceInt(RE::StaticFunctionTag*, RE::TESForm*, std::string, int);

namespace {
using Tag = RE::StaticFunctionTag;
RE::Projectile* projectile(RE::TESForm* form) {
    auto ref = form ? form->As<RE::TESObjectREFR>() : nullptr;
    return ref ? skyrim_cast<RE::Projectile*>(ref) : nullptr;
}
int type(Tag*, RE::TESForm* form) {
    auto shot = projectile(form);
    if (!shot) return -1;
    if (skyrim_cast<RE::ArrowProjectile*>(shot)) return 0;
    auto effect = shot->GetProjectileRuntimeData().avEffect;
    const auto flags = SourceInt(nullptr, effect, "EffectFlags", -1);
    if (flags != -1) return (flags & 0x40000000) ? 2 : (flags & 0x04000000) ? 3 : 1;
    if (skyrim_cast<RE::ConeProjectile*>(shot) || skyrim_cast<RE::BarrierProjectile*>(shot)) return 2;
    return skyrim_cast<RE::BeamProjectile*>(shot) ? 3 : 1;
}
RE::TESObjectREFR* source(Tag*, RE::TESForm* form) {
    auto shot = projectile(form);
    return shot ? shot->GetProjectileRuntimeData().shooter.get().get() : nullptr;
}
RE::TESForm* spell(Tag*, RE::TESForm* form) {
    auto shot = projectile(form);
    return shot && !skyrim_cast<RE::ArrowProjectile*>(shot) ? shot->GetProjectileRuntimeData().spell : nullptr;
}
RE::TESObjectREFR* find(Tag*, RE::Actor* actor, int filter, float lifetime, RE::TESForm* match) {
    if (!actor || filter < 0 || filter > 2) return nullptr;
    auto manager = RE::Projectile::Manager::GetSingleton();
    auto player = RE::PlayerCharacter::GetSingleton();
    auto origin = player ? player->GetParentCell() : nullptr;
    if (!manager || !origin) return nullptr;
    std::vector<RE::ProjectileHandle> shots;
    {
        RE::BSSpinLockGuard guard(manager->projectileLock);
        shots.insert(shots.end(), manager->unlimited.begin(), manager->unlimited.end());
        shots.insert(shots.end(), manager->limited.begin(), manager->limited.end());
    }
    RE::TESObjectREFR* result = nullptr;
    for (auto handle : shots) {
        auto shot = handle.get();
        if (!shot || shot->IsDeleted()) continue;
        auto cell = shot->GetParentCell();
        if (!cell) continue;
        if (cell != origin) {
            auto a = cell->GetCoordinates(), b = origin->GetCoordinates();
            if (origin->IsInteriorCell() || cell->IsInteriorCell() ||
                cell->GetRuntimeData().worldSpace != origin->GetRuntimeData().worldSpace ||
                !a || !b || std::abs(a->cellX - b->cellX) > 3 || std::abs(a->cellY - b->cellY) > 3) continue;
        }
        auto& data = shot->GetProjectileRuntimeData();
        const bool arrow = skyrim_cast<RE::ArrowProjectile*>(shot.get()) != nullptr;
        if ((filter == 1 && !arrow) || (filter == 2 && arrow) ||
            data.shooter.get().get() != actor || data.livingTime > lifetime) continue;
        if (match && ((filter == 1 && data.ammoSource != match) ||
                      (filter == 2 && match->As<RE::MagicItem>() && data.spell != match))) continue;
        result = shot.get();
        lifetime = data.livingTime;
    }
    return result;
}
}

bool RegisterProjectiles(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("GetProjectileType", "TES4Runtime", type);
    vm->RegisterFunction("GetProjectileSource", "TES4Runtime", source);
    vm->RegisterFunction("GetMagicProjectileSpell", "TES4Runtime", spell);
    vm->RegisterFunction("GetProjectile", "TES4Runtime", find);
    return true;
}
