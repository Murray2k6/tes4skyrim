#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <bit>

int SourceInt(RE::StaticFunctionTag*, RE::TESForm*, std::string, int);
RE::TESForm* SourceForm(RE::StaticFunctionTag*, RE::TESForm*, std::string);
const std::vector<RE::EffectSetting*>& SourceEffects(int);
void UpdateSourceBoundItem(RE::EffectSetting*, RE::TESForm*);

namespace {
using Tag = RE::StaticFunctionTag;
RE::MagicItem* magic(RE::TESForm* form) {
    if (form) if (auto ref = form->As<RE::TESObjectREFR>()) form = ref->GetBaseObject();
    return form ? form->As<RE::MagicItem>() : nullptr;
}
int matchingEffects(Tag*, RE::TESForm* form, int code, int actorValue) {
    auto item = magic(form);
    int result = 0;
    if (item && code) for (auto effect : item->effects)
        if (effect && effect->baseEffect && SourceInt(nullptr, effect->baseEffect, "EffectCode", 0) == code &&
            (actorValue < 0 || actorValue == 72 || SourceInt(nullptr, effect->baseEffect, "EffectActorValue", -1) == actorValue))
            ++result;
    return result;
}
int spellType(Tag*, RE::SpellItem* spell, int value, bool writing) {
    if (!spell) return 0;
    if (writing) {
        if (value < 0 || value > 4) return 0;
        spell->data.spellType = static_cast<RE::MagicSystem::SpellType>(value);
        // Skyrim chooses the magic-menu/equip slot independently of SPIT type.
        // Match the importer and vanilla: powers use Voice, others EitherHand.
        const RE::FormID slot = value == 2 || value == 3 ? 0x25BEE : 0x13F44;
        spell->SetEquipSlot(RE::TESForm::LookupByID<RE::BGSEquipSlot>(slot));
        return 0;
    }
    return static_cast<int>(spell->data.spellType);
}
RE::EffectSetting* effectFromCode(Tag*, int code) {
    const auto& forms = SourceEffects(code);
    for (auto form : forms)
        if (SourceInt(nullptr, form, "EffectActorValue", -1) < 0 && !SourceForm(nullptr, form, "BoundItem")) return form;
    return forms.empty() ? nullptr : forms.front();
}
int effectCodeFromChars(Tag*, std::string chars) {
    // OBSE resolves the four bytes as an installed MGEF before returning its code.
    if (chars.size() != 4 || chars.find('\0') != std::string::npos) return 0;
    std::uint32_t code = 0;
    for (unsigned i = 0; i < 4; ++i)
        code |= static_cast<std::uint32_t>(static_cast<unsigned char>(chars[i])) << (8 * i);
    const auto value = std::bit_cast<std::int32_t>(code);
    return effectFromCode(nullptr, value) ? value : 0;
}
std::string effectChars(Tag*, int code) {
    if (!effectFromCode(nullptr, code)) return "0";
    std::string result(4, '\0');
    for (unsigned i = 0; i < 4; ++i)
        result[i] = static_cast<char>(static_cast<std::uint32_t>(code) >> (8 * i));
    return result;
}
RE::TESForm* usedObject(Tag*, RE::EffectSetting* effect) {
    if (!effect) return nullptr;
    if (auto bound = SourceForm(nullptr, effect, "BoundItem")) return bound;
    return effect->data.associatedForm;
}
int changeEffectObject(Tag*, RE::EffectSetting* effect, RE::TESForm* value, bool light) {
    if (value) if (auto ref = value->As<RE::TESObjectREFR>()) value = ref->GetBaseObject();
    if (!effect || !value || (light && !value->As<RE::TESObjectLIGH>())) return 0;
    auto change = [=](RE::EffectSetting* target) {
        if (light) target->data.light = value->As<RE::TESObjectLIGH>();
        else {
            target->data.associatedForm = value;
            UpdateSourceBoundItem(target, value);
        }
    };
    change(effect);
    // Per-AV and bound-item variants represent the same authored MGEF.
    for (auto target : SourceEffects(SourceInt(nullptr, effect, "EffectCode", 0)))
        if (target != effect) change(target);
    return light ? 0 : 1;
}
}

bool RegisterMagicItems(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("CountMatchingEffects", "TES4Runtime", matchingEffects);
    vm->RegisterFunction("SpellType", "TES4Runtime", spellType);
    vm->RegisterFunction("MagicEffectFromCode", "TES4Runtime", effectFromCode);
    vm->RegisterFunction("MagicEffectCodeFromChars", "TES4Runtime", effectCodeFromChars);
    vm->RegisterFunction("GetMagicEffectChars", "TES4Runtime", effectChars);
    vm->RegisterFunction("GetMagicEffectUsedObject", "TES4Runtime", usedObject);
    vm->RegisterFunction("ChangeMagicEffectObject", "TES4Runtime", changeEffectObject);
    return true;
}
