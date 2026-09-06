#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <atomic>

extern "C" __declspec(dllimport) short __stdcall GetAsyncKeyState(int);

namespace {
using Device = REX::W32::IDirectInputDevice8A;
using Poll = std::int32_t (*)(Device*, std::uint32_t, void*);
struct Hook { std::uintptr_t* table{}; Poll original{}; };
std::array<Hook, 2> hooks{};
std::array<std::atomic_bool, 264> physical{};
Device* keyboard{};
Device* mouse{};

std::int32_t poll(Device* device, std::uint32_t size, void* data) {
    auto table = *reinterpret_cast<std::uintptr_t**>(device);
    const auto hook = std::find_if(hooks.begin(), hooks.end(),
        [table](const Hook& entry) { return entry.table == table; });
    if (hook == hooks.end()) return static_cast<std::int32_t>(0x80004005);
    const auto result = hook->original(device, size, data);
    // Observe the original device BEFORE SKSE's wrapper filters/inserts keys.
    // Do not poll again: an extra mouse read consumes wheel movement.
    if (device == keyboard && size == 256) {
        const auto state = static_cast<const std::uint8_t*>(data);
        for (unsigned i = 0; i < 256; ++i)
            physical[i].store(result >= 0 && (state[i] & 0x80), std::memory_order_relaxed);
    } else if (device == mouse && size == sizeof(REX::W32::DIMOUSESTATE2)) {
        const auto state = static_cast<const REX::W32::DIMOUSESTATE2*>(data);
        for (unsigned i = 0; i < 8; ++i)
            physical[256 + i].store(result >= 0 && (state->rgbButtons[i] & 0x80), std::memory_order_relaxed);
    }
    return result;
}

Device* observe(void* wrapped) {
    if (!wrapped) return nullptr;
    Device* real{};
    // SKSE FakeDirectInputDevice::QueryInterface forwards to the real device.
    auto device = static_cast<Device*>(wrapped);
    if (device->QueryInterface(REX::W32::IID_IDirectInputDevice8A,
            reinterpret_cast<void**>(&real)) < 0 || !real) return nullptr;
    auto table = *reinterpret_cast<std::uintptr_t**>(real);
    const auto installed = std::find_if(hooks.begin(), hooks.end(),
        [table](const Hook& entry) { return entry.table == table; });
    if (installed == hooks.end()) {
        auto free = std::find_if(hooks.begin(), hooks.end(),
            [](const Hook& entry) { return !entry.table; });
        if (free == hooks.end()) { real->Release(); return nullptr; }
        *free = {table, reinterpret_cast<Poll>(table[9])};
        // IDirectInputDevice8A's COM contract: GetDeviceState is slot 9.
        REL::safe_write(reinterpret_cast<std::uintptr_t>(&table[9]),
                        reinterpret_cast<std::uintptr_t>(&poll));
    }
    real->Release();  // The game's wrapper retains the underlying device.
    return real;
}

bool virtualKey(RE::StaticFunctionTag*, int key) {
    return key >= 0 && key < 256 && (GetAsyncKeyState(key) & 0x8000);
}
bool physicalKey(RE::StaticFunctionTag*, int key) {
    return key >= 0 && key < 264 && physical[key].load(std::memory_order_relaxed);
}
}

void InputMessage(SKSE::MessagingInterface::Message* message) {
    if (message->type != SKSE::MessagingInterface::kInputLoaded) return;
    auto manager = RE::BSInputDeviceManager::GetSingleton();
    if (!manager) return;
    auto keys = manager->GetKeyboard();
    auto buttons = manager->GetMouse();
    keyboard = observe(keys ? keys->dInputDevice : nullptr);
    mouse = observe(buttons ? buttons->dInputDevice : nullptr);
    if (!keyboard || !mouse) SKSE::log::error("TES4 physical input observer failed to attach");
}

bool RegisterInput(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("IsVirtualKeyPressed", "TES4Runtime", virtualKey);
    vm->RegisterFunction("IsPhysicalKeyPressed", "TES4Runtime", physicalKey);
    return true;
}
