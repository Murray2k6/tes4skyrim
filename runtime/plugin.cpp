#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>

bool RegisterCollections(RE::BSScript::IVirtualMachine*);
bool RegisterCore(RE::BSScript::IVirtualMachine*);
bool RegisterSettings(RE::BSScript::IVirtualMachine*);
bool RegisterItemValues(RE::BSScript::IVirtualMachine*);
bool RegisterMagicItems(RE::BSScript::IVirtualMachine*);
bool RegisterFormTypes(RE::BSScript::IVirtualMachine*);
bool RegisterLeveledLists(RE::BSScript::IVirtualMachine*);
bool RegisterReferences(RE::BSScript::IVirtualMachine*);
bool RegisterEquipment(RE::BSScript::IVirtualMachine*);
bool RegisterInventory(RE::BSScript::IVirtualMachine*);
bool RegisterReferenceWalk(RE::BSScript::IVirtualMachine*);
bool RegisterFactions(RE::BSScript::IVirtualMachine*);
bool RegisterActiveEffects(RE::BSScript::IVirtualMachine*);
bool RegisterScriptState(RE::BSScript::IVirtualMachine*);
bool RegisterMenus(RE::BSScript::IVirtualMachine*);
bool RegisterInput(RE::BSScript::IVirtualMachine*);
void InputMessage(SKSE::MessagingInterface::Message*);
bool RegisterProjectiles(RE::BSScript::IVirtualMachine*);
bool RegisterMerchant(RE::BSScript::IVirtualMachine*);
bool RegisterMap(RE::BSScript::IVirtualMachine*);
bool RegisterVoices(RE::BSScript::IVirtualMachine*);
bool RegisterEvents(RE::BSScript::IVirtualMachine*);
void EventMessage(SKSE::MessagingInterface::Message*);
void ResetVoices(SKSE::MessagingInterface::Message*);
void RegisterMerchantSerialization();
bool RegisterMenuScaleform(RE::GFxMovieView*, RE::GFxValue*);
void ResetScriptState(SKSE::MessagingInterface::Message*);
void ResetMenus(SKSE::MessagingInterface::Message*);
void ResetReferenceWalks(SKSE::MessagingInterface::Message*);
void ResetInventory(SKSE::MessagingInterface::Message*);
void LoadFormIdentities(SKSE::MessagingInterface::Message*);

extern "C" __declspec(dllexport) constinit auto SKSEPlugin_Version = [] {
    SKSE::PluginVersionData v;
    v.PluginVersion({0, 1, 0, 0});
    v.PluginName("TES4Runtime");
    v.AuthorName("TES4-to-TES5 converter contributors");
    v.UsesAddressLibrary(true);
    v.UsesNoStructs(true);
    return v;
}();

extern "C" __declspec(dllexport) bool SKSEPlugin_Load(const SKSE::LoadInterface* skse)
{
    SKSE::Init(skse);
    RegisterMerchantSerialization();
    SKSE::GetScaleformInterface()->Register(RegisterMenuScaleform, "TES4Runtime");
    SKSE::GetMessagingInterface()->RegisterListener(LoadFormIdentities);
    SKSE::GetMessagingInterface()->RegisterListener(ResetReferenceWalks);
    SKSE::GetMessagingInterface()->RegisterListener(ResetInventory);
    SKSE::GetMessagingInterface()->RegisterListener(ResetScriptState);
    SKSE::GetMessagingInterface()->RegisterListener(ResetMenus);
    SKSE::GetMessagingInterface()->RegisterListener(ResetVoices);
    SKSE::GetMessagingInterface()->RegisterListener(EventMessage);
    SKSE::GetMessagingInterface()->RegisterListener(InputMessage);
    return SKSE::GetPapyrusInterface()->Register([](RE::BSScript::IVirtualMachine* vm) {
        if (!RegisterInput(vm)) return false;
        return RegisterCollections(vm) && RegisterCore(vm) && RegisterSettings(vm) && RegisterItemValues(vm) && RegisterMagicItems(vm) && RegisterFormTypes(vm) && RegisterLeveledLists(vm) && RegisterReferences(vm) && RegisterEquipment(vm) && RegisterInventory(vm) && RegisterReferenceWalk(vm) && RegisterFactions(vm) && RegisterActiveEffects(vm) && RegisterScriptState(vm) && RegisterMenus(vm) && RegisterProjectiles(vm) && RegisterMerchant(vm) && RegisterMap(vm) && RegisterVoices(vm) && RegisterEvents(vm);
    });
}
