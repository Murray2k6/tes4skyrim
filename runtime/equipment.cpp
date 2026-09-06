#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <algorithm>

int SourceInt(RE::StaticFunctionTag*, RE::TESForm*, std::string, int);

namespace {
RE::TESForm* base(RE::TESForm* form) {
    if (form) if (auto ref = form->As<RE::TESObjectREFR>()) return ref->GetBaseObject();
    return form;
}
float weaponNumber(RE::StaticFunctionTag*, RE::TESForm* form, bool reach) {
    form = base(form);
    auto weapon = form ? form->As<RE::TESObjectWEAP>() : nullptr;
    return weapon ? (reach ? weapon->GetReach() : weapon->GetSpeed()) : 0.0f;
}
RE::EnchantmentItem* changeEnchantment(RE::StaticFunctionTag*, RE::TESForm* form,
                                      RE::TESForm* valueForm, bool remove) {
    form = base(form);
    valueForm = base(valueForm);
    auto value = valueForm ? valueForm->As<RE::EnchantmentItem>() : nullptr;
    auto field = form ? form->As<RE::TESEnchantableForm>() : nullptr;
    if (!field) return nullptr;
    auto before = field->formEnchanting;
    if (remove) field->formEnchanting = nullptr;
    else if (value && value->GetCastingType() == field->GetCastingType()) field->formEnchanting = value;
    return before;
}
int bipedMask(RE::TESForm* form) {
    int mask = SourceInt(nullptr, form, "BipedMask", -1);
    if (mask >= 0) return mask;
    auto armor = form ? form->As<RE::TESObjectARMO>() : nullptr;
    if (!armor) return -1;
    // Inverse of the converter's primary slots; extras only hide body parts.
    constexpr int slots[] = {0, 1, 2, 14, 3, 7, 6, 6, 5, -1, -1, -1, -1, 9, -1, 13};
    auto target = static_cast<unsigned>(armor->GetSlotMask());
    mask = 0;
    for (int i = 0; i < std::size(slots); ++i)
        if (slots[i] >= 0 && (target & (1u << slots[i]))) mask |= 1 << i;
    return mask;
}
bool lightCarriable(RE::StaticFunctionTag*, RE::TESForm* form) {
    form = base(form);
    auto light = form ? form->As<RE::TESObjectLIGH>() : nullptr;
    return light && light->data.flags.all(RE::TES_LIGHT_FLAGS::kCanCarry);
}
int equipmentSlot(RE::StaticFunctionTag*, RE::TESForm* form) {
    form = base(form);
    if (!form) return -1;
    auto mask = bipedMask(form);
    if (mask >= 0) {
        if (!mask) return 255;
        for (int slot = 0; slot < 16; ++slot) if (mask == (1 << slot)) return slot;
        constexpr int masks[] = {12, 44, 60, 28, 20};
        for (int i = 0; i < std::size(masks); ++i) if (mask == masks[i]) return 18 + i;
        return mask == 192 ? 6 : 0;
    }
    if (form->As<RE::TESObjectWEAP>()) return 16;
    if (form->As<RE::TESAmmo>()) return 17;
    return lightCarriable(nullptr, form) ? 14 : -1;
}
RE::TESForm* equippedObject(RE::StaticFunctionTag*, RE::Actor* actor, int slot) {
    if (!actor) return nullptr;
    if (slot == 16) {
        for (bool left : {false, true}) {
            auto item = actor->GetEquippedObject(left);
            if (item && item->As<RE::TESObjectWEAP>()) return item;
        }
        return nullptr;
    }
    if (slot == 17) return actor->GetCurrentAmmo();
    if (slot == 14) {
        for (bool left : {true, false}) {
            auto item = actor->GetEquippedObject(left);
            if (lightCarriable(nullptr, item)) return item;
        }
        return nullptr;
    }
    if (slot < 0 || slot > 255) return nullptr;
    for (const auto& [item, data] : actor->GetInventory()) {
        if (!data.second || !data.second->IsWorn()) continue;
        auto mask = bipedMask(item);
        if (mask < 0) continue;
        auto wanted = slot == 6 || slot == 7 ? 192 : slot < 16 ? 1 << slot : 0;
        if ((wanted && (mask & wanted)) || (!wanted && equipmentSlot(nullptr, item) == slot)) return item;
    }
    return nullptr;
}
RE::ExtraDataList* equippedWeaponExtra(RE::Actor* actor) {
    if (!actor) return nullptr;
    for (bool left : {false, true}) {
        auto entry = actor->GetEquippedEntryData(left);
        if (!entry || !entry->object || !entry->object->As<RE::TESObjectWEAP>()) continue;
        if (entry->extraLists) for (auto extra : *entry->extraLists) {
            if (!extra || !extra->HasType(left ? RE::ExtraDataType::kWornLeft : RE::ExtraDataType::kWorn)) continue;
            return extra;
        }
        return nullptr;
    }
    return nullptr;
}
RE::AlchemyItem* equippedWeaponPoison(RE::StaticFunctionTag*, RE::Actor* actor) {
    auto extra = equippedWeaponExtra(actor);
    auto poison = extra ? extra->GetByType<RE::ExtraPoison>() : nullptr;
    return poison ? poison->poison : nullptr;
}
RE::AlchemyItem* changeEquippedWeaponPoison(RE::StaticFunctionTag*, RE::Actor* actor,
                                          RE::AlchemyItem* value, bool remove) {
    auto extra = equippedWeaponExtra(actor);
    if (!extra) return nullptr;
    auto poison = extra->GetByType<RE::ExtraPoison>();
    auto before = poison ? poison->poison : nullptr;
    if (remove && poison) {
        if (extra->Remove(RE::ExtraDataType::kPoison, poison)) delete poison;
    }
    else if (!remove && value) {
        if (poison) { poison->poison = value; poison->count = 1; }
        else extra->Add(new RE::ExtraPoison(value, 1));
    }
    actor->AddChange(RE::TESObjectREFR::ChangeFlags::kInventory);
    return before;
}
float equippedValue(RE::StaticFunctionTag*, RE::Actor* actor, int slot, bool charge, int operation, float value) {
    auto form = equippedObject(nullptr, actor, slot);
    if (!form) return 0;
    auto maximum = static_cast<float>(SourceInt(nullptr, form, charge ? "ObjectCharge" : "ObjectHealth", 0));
    for (const auto& [item, data] : actor->GetInventory()) {
        if (item != form || !data.second || !data.second->extraLists) continue;
        for (auto extra : *data.second->extraLists) {
            if (!extra || !(extra->HasType<RE::ExtraWorn>() || extra->HasType<RE::ExtraWornLeft>())) continue;
            auto healthData = extra->GetByType<RE::ExtraHealth>();
            auto chargeData = extra->GetByType<RE::ExtraCharge>();
            float current = charge ? (chargeData ? chargeData->charge : maximum) :
                maximum * (healthData ? healthData->health : 1.0f);
            if (!operation) return current;
            auto updated = std::max(0.0f, operation == 2 ? current + value : value);
            if (charge) {
                if (chargeData) chargeData->charge = updated;
                else {
                    chargeData = new RE::ExtraCharge();
                    chargeData->charge = updated;
                    extra->Add(chargeData);
                }
            } else if (maximum > 0) {
                if (healthData) healthData->health = updated / maximum;
                else extra->Add(new RE::ExtraHealth(updated / maximum));
            }
            actor->AddChange(RE::TESObjectREFR::ChangeFlags::kInventory);
            return 0;
        }
    }
    return operation ? 0 : maximum;
}
}

bool RegisterEquipment(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("GetWeaponNumber", "TES4Runtime", weaponNumber);
    vm->RegisterFunction("ChangeEnchantment", "TES4Runtime", changeEnchantment);
    vm->RegisterFunction("GetEquipmentSlot", "TES4Runtime", equipmentSlot);
    vm->RegisterFunction("GetEquippedObject", "TES4Runtime", equippedObject);
    vm->RegisterFunction("GetEquippedWeaponPoison", "TES4Runtime", equippedWeaponPoison);
    vm->RegisterFunction("ChangeEquippedWeaponPoison", "TES4Runtime", changeEquippedWeaponPoison);
    vm->RegisterFunction("IsLightCarriable", "TES4Runtime", lightCarriable);
    vm->RegisterFunction("EquippedValue", "TES4Runtime", equippedValue);
    return true;
}
