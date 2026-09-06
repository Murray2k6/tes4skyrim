#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <format>
#include <sstream>
#include <unordered_map>

bool SourceScriptRemoved(RE::StaticFunctionTag*, RE::TESForm*);
int SourceInt(RE::StaticFunctionTag*, RE::TESForm*, std::string, int);

namespace {
struct Identity {
    int type; int creature; int weapon;
    std::unordered_map<std::string, int> traits;
    std::unordered_map<std::string, RE::TESForm*> forms;
    std::unordered_map<std::string, float> numbers;
    std::unordered_map<std::string, std::string> strings;
};
std::unordered_map<RE::FormID, Identity> identities;
std::unordered_map<std::string, RE::TESForm*> editorForms;
std::unordered_map<int, std::vector<RE::EffectSetting*>> effectForms;
RE::TESForm* base(RE::TESForm* form) {
    if (form) if (auto ref = form->As<RE::TESObjectREFR>()) return ref->GetBaseObject();
    return form;
}
bool cloned(RE::StaticFunctionTag*, RE::TESForm* form) {
    form = base(form);
    return form && form->IsDynamicForm();
}
RE::TESFullName* nameField(RE::TESForm* form) {
    if (!form) return nullptr;
    if (auto ref = form->As<RE::TESObjectREFR>()) {
        if (auto marker = ref->extraList.GetByType<RE::ExtraMapMarker>(); marker && marker->mapData)
            return &marker->mapData->locationName;
        form = ref->GetBaseObject();
    }
    const auto name = form ? form->GetName() : nullptr;
    if ((!name || !*name) && form) {
        if (auto cell = form->As<RE::TESObjectCELL>(); cell && cell->GetRuntimeData().worldSpace)
            return cell->GetRuntimeData().worldSpace->As<RE::TESFullName>();
    }
    return form ? form->As<RE::TESFullName>() : nullptr;
}
const char* fullName(RE::TESForm* form) {
    const auto field = nameField(form);
    return field ? field->GetFullName() : "";
}
bool hasName(RE::StaticFunctionTag*, RE::TESForm* form) {
    const auto name = fullName(form);
    return name && *name;
}
bool nameIncludes(RE::StaticFunctionTag*, RE::TESForm* form, std::string needle) {
    const auto value = fullName(base(form));
    if (!value || !*value) return false;
    const std::string name(value);
    return std::search(name.begin(), name.end(), needle.begin(), needle.end(),
        [](unsigned char a, unsigned char b) { return std::tolower(a) == std::tolower(b); }) != name.end();
}
std::string getName(RE::StaticFunctionTag*, RE::TESForm* form) {
    if (!form) return "";
    const auto name = fullName(form);
    return name && *name ? name : "<no name>";
}
std::string formIDString(RE::StaticFunctionTag*, RE::TESForm* form) {
    return std::format("{:08X}", form ? form->GetFormID() : 0);
}
int setName(RE::StaticFunctionTag*, RE::TESForm* form, RE::BSFixedString value) {
    if (auto field = nameField(form)) field->SetFullName(value.c_str());
    return 0;
}
RE::TESFullName* baseNameTarget(RE::TESForm* target, RE::TESForm* caller) {
    target = base(target ? target : caller);
    return target ? target->As<RE::TESFullName>() : nullptr;
}
int copyName(RE::StaticFunctionTag*, RE::TESForm* source, RE::TESForm* target, RE::TESForm* caller) {
    source = base(source);
    if (source) if (auto field = baseNameTarget(target, caller))
        field->SetFullName(getName(nullptr, source).c_str());
    return 0;
}
int appendName(RE::StaticFunctionTag*, std::string suffix, RE::TESForm* target, RE::TESForm* caller) {
    if (auto field = baseNameTarget(target, caller)) {
        const auto current = field->GetFullName();
        const std::string value = std::string(current ? current : "") + suffix;
        field->SetFullName(value.c_str());
    }
    return 0;
}
void setActorFullName(RE::StaticFunctionTag*, RE::Actor* actor, RE::BSFixedString value) {
    // Oblivion 0x512BB0 changes the actor base's TESFullName and marks it saved.
    if (auto npc = actor ? actor->GetActorBase() : nullptr) {
        npc->SetFullName(value.c_str());
        npc->AddChange(RE::TESNPC::ChangeFlags::kFullName);
    }
}
std::string description(RE::StaticFunctionTag*, RE::TESForm* form) {
    form = base(form);
    RE::BSString text;
    if (form) if (auto field = form->As<RE::TESDescription>()) field->GetDescription(text, form);
    return text.c_str() ? text.c_str() : "";
}
bool classSkill(RE::StaticFunctionTag*, RE::TESForm* form, int skill) {
    if (skill < 12 || skill > 32) return false;
    form = base(form);
    if (auto npc = form ? form->As<RE::TESNPC>() : nullptr) form = npc->npcClass;
    if (!form || !form->As<RE::TESClass>()) return false;
    for (int index = 0; index < 7; ++index)
        if (SourceInt(nullptr, form, "ClassSkill" + std::to_string(index), -1) == skill) return true;
    return false;
}
bool actorFlag(RE::StaticFunctionTag*, RE::TESForm* form, int mask, bool enabled) {
    form = base(form);
    auto actor = form ? form->As<RE::TESNPC>() : nullptr;
    if (!actor || (mask != 8 && mask != 8192 && mask != 16384)) return false;
    const auto flag = static_cast<RE::ACTOR_BASE_DATA::Flag>(mask);
    if (enabled) actor->actorData.actorBaseFlags.set(flag);
    else actor->actorData.actorBaseFlags.reset(flag);
    actor->AddChange(RE::TESNPC::ChangeFlags::kBaseData);
    return true;
}
int containerRespawns(RE::StaticFunctionTag*, RE::TESForm* form, bool enabled) {
    form = base(form);
    if (auto container = form ? form->As<RE::TESObjectCONT>() : nullptr) {
        if (enabled) container->data.flags.set(RE::CONT_DATA::Flag::kRespawn);
        else container->data.flags.reset(RE::CONT_DATA::Flag::kRespawn);
    }
    return 0;
}
int changeWeight(RE::StaticFunctionTag*, RE::TESForm* form, float value, bool modify) {
    form = base(form);
    if (auto field = form ? form->As<RE::TESWeightForm>() : nullptr)
        field->weight = std::max(0.0f, modify ? field->weight + value : value);
    return 0;
}
int lightRadius(RE::StaticFunctionTag*, RE::TESForm* form, int value) {
    form = base(form);
    if (auto light = form ? form->As<RE::TESObjectLIGH>() : nullptr) {
        light->data.radius = static_cast<std::uint32_t>(std::max(0, value));
        return 1;
    }
    return 0;
}
int soulLevel(RE::StaticFunctionTag*, RE::TESForm* form, bool capacity) {
    form = base(form);
    auto gem = form ? form->As<RE::TESSoulGem>() : nullptr;
    return gem ? static_cast<int>(capacity ? gem->GetMaximumCapacity() : gem->GetContainedSoul()) : 0;
}
int objectType(RE::StaticFunctionTag*, RE::TESForm* form) {
    if (form) if (auto ref = form->As<RE::TESObjectREFR>())
        if (skyrim_cast<RE::Projectile*>(ref)) return 34;
    form = base(form);
    if (!form) return 0;
    if (auto it = identities.find(form->GetFormID()); it != identities.end()) return it->second.type;
    constexpr std::string_view signatures[] = {"NONE", "TES4", "GRUP", "GMST", "GLOB", "CLAS", "FACT", "HAIR", "EYES", "RACE", "SOUN", "SKIL", "MGEF", "SCPT", "LTEX", "ENCH", "SPEL", "BSGN", "ACTI", "APPA", "ARMO", "BOOK", "CLOT", "CONT", "DOOR", "INGR", "LIGH", "MISC", "STAT", "GRAS", "TREE", "FLOR", "FURN", "WEAP", "AMMO", "NPC_", "CREA", "LVLC", "SLGM", "KEYM", "ALCH", "SBSP", "SGST", "LVLI", "SNDG", "WTHR", "CLMT", "REGN", "CELL", "REFR", "ACHR", "ACRE", "PGRD", "WRLD", "LAND", "TLOD", "ROAD", "DIAL", "INFO", "QUST", "IDLE", "PACK", "CSTY", "LSCR", "LVSP", "ANIO", "WATR", "EFSH"};
    auto signature = RE::FormTypeToString(form->GetFormType());
    if (signature == "LVLN") return 37;
    if (signature == "SCRL") return 21;
    if (signature == "TACT") return 18;
    for (int i = 0; i < std::size(signatures); ++i) if (signature == signatures[i]) return i;
    return 0;
}
int creatureType(RE::StaticFunctionTag*, RE::TESForm* form) {
    form = base(form);
    if (form) if (auto it = identities.find(form->GetFormID()); it != identities.end()) return it->second.creature;
    return -1;
}
int armorType(RE::StaticFunctionTag*, RE::TESForm* form) {
    form = base(form);
    if (form) if (auto armor = form->As<RE::TESObjectARMO>()) return armor->IsHeavyArmor() ? 1 : 0;
    return 0;
}
int weaponType(RE::StaticFunctionTag*, RE::TESForm* form) {
    form = base(form);
    if (!form) return 0;
    if (auto it = identities.find(form->GetFormID()); it != identities.end() && it->second.weapon >= 0)
        return it->second.weapon;
    if (auto weapon = form->As<RE::TESObjectWEAP>()) {
        // Skyrim: hand, sword, dagger, axe, mace, greatsword, battleaxe, bow, staff, crossbow.
        constexpr int types[] = {0, 0, 0, 2, 2, 1, 3, 5, 4, 5};
        const auto type = static_cast<unsigned>(weapon->GetWeaponType());
        if (type < std::size(types)) return types[type];
    }
    return 0;
}
bool isFood(RE::StaticFunctionTag*, RE::TESForm* form) {
    form = base(form);
    if (form) {
        if (auto ingredient = form->As<RE::IngredientItem>()) return ingredient->IsFood();
        if (auto potion = form->As<RE::AlchemyItem>()) return potion->IsFood();
    }
    return false;
}
}

int SourceInt(RE::StaticFunctionTag*, RE::TESForm* form, std::string field, int fallback) {
    if (field == "IsScripted" && SourceScriptRemoved(nullptr, form)) return 0;
    if (!form) return fallback;
    if (auto it = identities.find(form->GetFormID()); it != identities.end())
        if (auto value = it->second.traits.find(field); value != it->second.traits.end()) {
            if (field == "ActorFlags") if (auto actor = base(form)->As<RE::TESNPC>()) {
                constexpr int shared = 8 | 8192 | 16384;
                return (value->second & ~shared) | (actor->actorData.actorBaseFlags.underlying() & shared);
            }
            if (field == "Flags") if (auto container = base(form)->As<RE::TESObjectCONT>())
                return (value->second & ~2) | (container->data.flags.underlying() & 2);
            return value->second;
        }
    auto formBase = base(form);
    return formBase != form ? SourceInt(nullptr, formBase, field, fallback) : fallback;
}

RE::TESForm* SourceForm(RE::StaticFunctionTag*, RE::TESForm* form, std::string field) {
    if (field == "Script" && SourceScriptRemoved(nullptr, form)) return nullptr;
    if (form) if (auto it = identities.find(form->GetFormID()); it != identities.end())
        if (auto value = it->second.forms.find(field); value != it->second.forms.end()) return value->second;
    auto formBase = base(form);
    return formBase != form ? SourceForm(nullptr, formBase, field) : nullptr;
}

float SourceFloat(RE::StaticFunctionTag*, RE::TESForm* form, std::string field, float fallback) {
    form = base(form);
    if (form) if (auto it = identities.find(form->GetFormID()); it != identities.end())
        if (auto value = it->second.numbers.find(field); value != it->second.numbers.end()) return value->second;
    return fallback;
}

std::string SourceString(RE::StaticFunctionTag*, RE::TESForm* form, std::string field) {
    form = base(form);
    if (form) if (auto it = identities.find(form->GetFormID()); it != identities.end())
        if (auto value = it->second.strings.find(field); value != it->second.strings.end()) return value->second;
    return {};
}

bool SourceContains(RE::StaticFunctionTag*, RE::TESForm* form, std::string field, std::string text) {
    auto value = SourceString(nullptr, form, field);
    return !text.empty() && std::search(value.begin(), value.end(), text.begin(), text.end(),
        [](unsigned char a, unsigned char b) { return std::tolower(a) == std::tolower(b); }) != value.end();
}

void LoadFormIdentities(SKSE::MessagingInterface::Message* message) {
    if (message->type != SKSE::MessagingInterface::kDataLoaded) return;
    auto handler = RE::TESDataHandler::GetSingleton();
    const std::filesystem::path directory("Data/SKSE/Plugins/TES4Runtime");
    if (!std::filesystem::is_directory(directory)) return;
    std::vector<std::pair<unsigned, std::filesystem::path>> files;
    for (const auto& file : std::filesystem::recursive_directory_iterator(directory)) {
        if (file.path().extension() != ".tsv") continue;
        const auto plugin = handler->LookupLoadedModByName(file.path().stem().string());
        if (plugin) files.emplace_back(plugin->compileIndex, file.path());
    }
    std::sort(files.begin(), files.end());
    identities.clear();
    editorForms.clear();
    for (const auto& [order, path] : files) {
        std::ifstream input(path);
        std::string line;
        while (std::getline(input, line)) {
            std::istringstream stream(line);
            std::string owner, id, type, creature, weapon;
            if (!std::getline(stream, owner, '\t') || !std::getline(stream, id, '\t') ||
                !std::getline(stream, type, '\t') || !std::getline(stream, creature, '\t') ||
                !std::getline(stream, weapon, '\t')) continue;
            try {
                const auto form = handler->LookupForm(std::stoul(id, nullptr, 16), owner);
                if (form) {
                    Identity identity{std::stoi(type), std::stoi(creature), std::stoi(weapon), {}, {}, {}, {}};
                    std::string trait;
                    while (std::getline(stream, trait, '\t')) {
                        auto split = trait.find('=');
                        if (split == std::string::npos) continue;
                        if (trait[0] == '@') {
                            auto separator = trait.find('|', split);
                            if (separator != std::string::npos)
                                identity.forms[trait.substr(1, split - 1)] = handler->LookupForm(
                                    std::stoul(trait.substr(separator + 1), nullptr, 16), trait.substr(split + 1, separator - split - 1));
                        } else if (trait[0] == '%') {
                            identity.numbers[trait.substr(1, split - 1)] = std::stof(trait.substr(split + 1));
                        } else if (trait[0] == '$') {
                            std::string decoded;
                            for (auto i = split + 1; i + 1 < trait.size(); i += 2)
                                decoded += static_cast<char>(std::stoul(trait.substr(i, 2), nullptr, 16));
                            identity.strings[trait.substr(1, split - 1)] = std::move(decoded);
                        } else identity.traits[trait.substr(0, split)] = std::stoi(trait.substr(split + 1));
                    }
                    if (auto named = identity.strings.find("EditorID"); named != identity.strings.end()) {
                        auto key = named->second;
                        std::transform(key.begin(), key.end(), key.begin(), [](unsigned char c) { return std::tolower(c); });
                        editorForms[key] = form;
                    }
                    identities[form->GetFormID()] = std::move(identity);
                }
            } catch (const std::exception&) { SKSE::log::warn("Invalid source identity in {}", path.string()); }
        }
    }
    effectForms.clear();
    for (const auto& [id, identity] : identities)
        if (const auto code = identity.traits.find("EffectCode"); code != identity.traits.end())
            if (auto effect = RE::TESForm::LookupByID<RE::EffectSetting>(id))
                effectForms[code->second].push_back(effect);
    for (auto& [code, forms] : effectForms)
        std::sort(forms.begin(), forms.end(), [](auto a, auto b) { return a->GetFormID() < b->GetFormID(); });
}

const std::vector<RE::EffectSetting*>& SourceEffects(int code) {
    static const std::vector<RE::EffectSetting*> empty;
    const auto found = effectForms.find(code);
    return found == effectForms.end() ? empty : found->second;
}

void UpdateSourceBoundItem(RE::EffectSetting* effect, RE::TESForm* item) {
    if (auto found = identities.find(effect->GetFormID()); found != identities.end())
        if (auto bound = found->second.forms.find("BoundItem"); bound != found->second.forms.end())
            bound->second = item;
}

int SourceObjectType(RE::TESForm* form) { return objectType(nullptr, form); }

RE::TESForm* SourceByEditorID(std::string name) {
    std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) { return std::tolower(c); });
    if (auto found = editorForms.find(name); found != editorForms.end()) return found->second;
    return RE::TESForm::LookupByEditorID(name);
}

bool RegisterFormTypes(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("GetFormIDString", "TES4Runtime", formIDString);
    vm->RegisterFunction("SetActorFlag", "TES4Runtime", actorFlag);
    vm->RegisterFunction("SetContainerRespawns", "TES4Runtime", containerRespawns);
    vm->RegisterFunction("GetName", "TES4Runtime", getName);
    vm->RegisterFunction("NameIncludes", "TES4Runtime", nameIncludes);
    vm->RegisterFunction("SetName", "TES4Runtime", setName);
    vm->RegisterFunction("CopyName", "TES4Runtime", copyName);
    vm->RegisterFunction("AppendToName", "TES4Runtime", appendName);
    vm->RegisterFunction("SetActorFullName", "TES4Runtime", setActorFullName);
    vm->RegisterFunction("GetDescription", "TES4Runtime", description);
    vm->RegisterFunction("IsClassSkill", "TES4Runtime", classSkill);
    vm->RegisterFunction("ChangeWeight", "TES4Runtime", changeWeight);
    vm->RegisterFunction("SetLightRadius", "TES4Runtime", lightRadius);
    vm->RegisterFunction("IsClonedForm", "TES4Runtime", cloned);
    vm->RegisterFunction("HasName", "TES4Runtime", hasName);
    vm->RegisterFunction("GetSoulLevel", "TES4Runtime", soulLevel);
    vm->RegisterFunction("GetObjectType", "TES4Runtime", objectType);
    vm->RegisterFunction("GetCreatureType", "TES4Runtime", creatureType);
    vm->RegisterFunction("GetArmorType", "TES4Runtime", armorType);
    vm->RegisterFunction("GetWeaponType", "TES4Runtime", weaponType);
    vm->RegisterFunction("IsFood", "TES4Runtime", isFood);
    vm->RegisterFunction("SourceInt", "TES4Runtime", SourceInt);
    vm->RegisterFunction("SourceForm", "TES4Runtime", SourceForm);
    vm->RegisterFunction("SourceFloat", "TES4Runtime", SourceFloat);
    vm->RegisterFunction("SourceString", "TES4Runtime", SourceString);
    vm->RegisterFunction("SourceContains", "TES4Runtime", SourceContains);
    return true;
}
