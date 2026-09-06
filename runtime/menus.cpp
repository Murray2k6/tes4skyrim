#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <atomic>

namespace {
using Tag = RE::StaticFunctionTag;
std::atomic<int> pressed{-1};

RE::GPtr<RE::IMenu> inputMenu() {
    auto ui = RE::UI::GetSingleton();
    auto menu = ui ? ui->GetMenu("CustomMenu") : nullptr;
    RE::GFxValue active;
    return menu && menu->uiMovie && menu->uiMovie->GetVariable(&active, "_root.TES4InputActive") &&
        active.IsBool() && active.GetBool() ? menu : nullptr;
}

bool textInput(Tag*) {
    return !!inputMenu();
}
std::vector<RE::TESQuest*> activeQuests(Tag*) {
    std::vector<RE::TESQuest*> result;
    auto player = RE::PlayerCharacter::GetSingleton();
    if (player) {
        const auto& objectives = player->GetPlayerRuntimeData().objectives;
        for (auto i = objectives.size(); i > 0; --i) {
            auto objective = objectives[i - 1].Objective;
            auto quest = objective ? objective->ownerQuest : nullptr;
            if (quest && quest->IsActive() && std::find(result.begin(), result.end(), quest) == result.end()) result.push_back(quest);
        }
    }
    if (auto data = RE::TESDataHandler::GetSingleton()) for (auto quest : data->GetFormArray<RE::TESQuest>())
        if (quest && quest->IsActive() && std::find(result.begin(), result.end(), quest) == result.end()) result.push_back(quest);
    return result;
}
void storeButton(Tag*, int index) { pressed.store(index); }
int takeButton(Tag*) {
    if (auto menu = inputMenu()) {
        RE::GFxValue button;
        if (menu->uiMovie->GetVariable(&button, "_root.TES4InputButton") && button.IsNumber()) {
            const auto index = static_cast<int>(button.GetNumber());
            menu->uiMovie->SetVariable("_root.TES4InputButton", RE::GFxValue(-1));
            return index;
        }
    }
    return pressed.exchange(-1);
}
bool gamepad(Tag*, int index) {
    auto input = RE::BSInputDeviceManager::GetSingleton();
    auto pad = input ? input->GetGamepad() : nullptr;
    return pad && pad->connected && (index == -1 || index == pad->userIndex);
}
bool gamepadKey(Tag*, int index, int key, int flags) {
    if (!gamepad(nullptr, index) || key < 0 || key > 17) return false;
    auto device = RE::BSInputDeviceManager::GetSingleton()->GetGamepad();
    auto pad = skyrim_cast<RE::BSWin32GamepadDevice*>(device);
    if (!pad) return false;
    const auto code = key == 16 ? RE::BSWin32GamepadDevice::Key::kLeftTrigger :
        key == 17 ? RE::BSWin32GamepadDevice::Key::kRightTrigger : 1U << key;
    if (!(flags & 1)) return pad->IsPressed(code);
    if (key == 16) return pad->currentState.gamepad.leftTrigger > REX::W32::XINPUT_GAMEPAD_TRIGGER_THRESHOLD;
    if (key == 17) return pad->currentState.gamepad.rightTrigger > REX::W32::XINPUT_GAMEPAD_TRIGGER_THRESHOLD;
    return (pad->currentState.gamepad.buttons & code) != 0;
}
RE::TESObjectREFR* menuReference(Tag*, int requested) {
    auto ui = RE::UI::GetSingleton();
    if (!ui) return nullptr;
    if (!requested || requested == 1008) {
        if (ui->IsMenuOpen(RE::BarterMenu::MENU_NAME))
            return RE::TESObjectREFR::LookupByHandle(RE::BarterMenu::GetTargetRefHandle()).get();
        if (ui->IsMenuOpen(RE::ContainerMenu::MENU_NAME))
            return RE::TESObjectREFR::LookupByHandle(RE::ContainerMenu::GetTargetRefHandle()).get();
    }
    if ((!requested || requested == 1009) && ui->IsMenuOpen(RE::DialogueMenu::MENU_NAME)) {
        auto topics = RE::MenuTopicManager::GetSingleton();
        return topics ? topics->speaker.get().get() : nullptr;
    }
    if ((!requested || requested == 1026) && ui->IsMenuOpen(RE::BookMenu::MENU_NAME))
        return RE::BookMenu::GetTargetReference();
    return nullptr;
}
RE::TESForm* selectedForm(RE::ItemList* list) {
    auto item = list ? list->GetSelectedItem() : nullptr;
    return item && item->data.objDesc ? item->data.objDesc->object : nullptr;
}
RE::TESForm* selection(Tag*, int requested) {
    auto ui = RE::UI::GetSingleton();
    if (!ui) return nullptr;
    if (!requested || requested == 1008) {
        if (ui->IsMenuOpen(RE::BarterMenu::MENU_NAME))
            if (auto menu = ui->GetMenu<RE::BarterMenu>()) return selectedForm(menu->GetRuntimeData().itemList);
        if (ui->IsMenuOpen(RE::ContainerMenu::MENU_NAME))
            if (auto menu = ui->GetMenu<RE::ContainerMenu>()) return selectedForm(menu->GetRuntimeData().itemList);
    }
    if ((!requested || requested == 1002) && ui->IsMenuOpen(RE::InventoryMenu::MENU_NAME))
        if (auto menu = ui->GetMenu<RE::InventoryMenu>()) return selectedForm(menu->GetRuntimeData().itemList);
    if ((!requested || requested == 1022) && ui->IsMenuOpen(RE::MagicMenu::MENU_NAME))
        if (auto menu = ui->GetMenu<RE::MagicMenu>(); menu && menu->uiMovie) {
            RE::GFxValue id;
            if (menu->uiMovie->GetVariable(&id, "_root.Menu_mc.inventoryLists.itemList.selectedEntry.formId") && id.IsNumber())
                return RE::TESForm::LookupByID(static_cast<RE::FormID>(id.GetNumber()));
        }
    if ((!requested || requested == 1026) && ui->IsMenuOpen(RE::BookMenu::MENU_NAME))
        return RE::BookMenu::GetTargetForm();
    return nullptr;
}
}

void ResetMenus(SKSE::MessagingInterface::Message* message) {
    if (message->type == SKSE::MessagingInterface::kPreLoadGame || message->type == SKSE::MessagingInterface::kNewGame)
        pressed.store(-1);
}

bool RegisterMenuScaleform(RE::GFxMovieView* view, RE::GFxValue*) {
    // SKSE attaches _global.skse after invoking plugin registration callbacks.
    // Run after that attachment, while retaining the movie through the task.
    SKSE::GetTaskInterface()->AddUITask([movie = RE::GPtr<RE::GFxMovieView>(view)] {
        RE::GFxValue enabled(true), result;
        movie->Invoke("_global.skse.ExtendData", &result, &enabled, 1);
    });
    return true;
}

bool RegisterMenus(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("GetActiveQuests", "TES4Runtime", activeQuests);
    vm->RegisterFunction("IsTextInputInUse", "TES4Runtime", textInput);
    vm->RegisterFunction("StoreMessageButton", "TES4Runtime", storeButton);
    vm->RegisterFunction("TakeMessageButton", "TES4Runtime", takeButton);
    vm->RegisterFunction("IsGamepadConnected", "TES4Runtime", gamepad);
    vm->RegisterFunction("IsGamepadKeyPressed", "TES4Runtime", gamepadKey);
    vm->RegisterFunction("GetActiveMenuRef", "TES4Runtime", menuReference);
    vm->RegisterFunction("GetActiveMenuSelection", "TES4Runtime", selection);
    return true;
}
