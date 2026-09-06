#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <mutex>
#include <unordered_set>
#include <algorithm>
#include <cmath>

RE::TESForm* SourceForm(RE::StaticFunctionTag*, RE::TESForm*, std::string);
std::string SourceString(RE::StaticFunctionTag*, RE::TESForm*, std::string);
RE::TESForm* SourceByEditorID(std::string);

namespace {
std::mutex mutex;
std::unordered_set<RE::FormID> removed;
std::unordered_set<std::string> loadedScripts, restartedScripts;
bool gameTransition(RE::BSScript::Internal::VirtualMachine* vm, RE::VMStackID stackID,
                    RE::StaticFunctionTag*, bool restart) {
    RE::BSScript::Stack* stack = nullptr;
    if (!vm->GetStackByID(stackID, &stack) || !stack) return false;
    for (auto frame = stack->top; frame; frame = frame->previousFrame) {
        const auto function = frame->owningFunction.get();
        if (!function || function->GetIsNative()) continue;
        // All instances of one source script share the notification, as OBSE's
        // informedScripts / regScripts sets do. Never store this latch in saves.
        std::string name = function->GetObjectTypeName().c_str();
        std::transform(name.begin(), name.end(), name.begin(),
            [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        std::scoped_lock guard(mutex);
        return (restart ? restartedScripts : loadedScripts).insert(name).second;
    }
    return false;
}
RE::TESForm* base(RE::TESForm* form) {
    if (form) if (auto ref = form->As<RE::TESObjectREFR>()) return ref->GetBaseObject();
    return form;
}
RE::TESForm* removeScript(RE::StaticFunctionTag*, RE::TESForm* subject) {
    subject = base(subject);
    auto previous = SourceForm(nullptr, subject, "Script");
    if (previous) {
        std::scoped_lock guard(mutex);
        removed.insert(subject->GetFormID());
    }
    return previous;
}
int resetVariables(RE::StaticFunctionTag*, RE::TESForm* subject, RE::BSFixedString scriptName) {
    if (!subject) return 0;
    auto name = std::string(scriptName.c_str());
    if (name.empty()) name = SourceString(nullptr, SourceForm(nullptr, base(subject), "Script"), "PapyrusName");
    auto vm = RE::BSScript::Internal::VirtualMachine::GetSingleton();
    RE::BSTSmartPointer<RE::BSScript::Object> object;
    auto handle = vm->GetObjectHandlePolicy()->GetHandleForObject(subject->GetFormType(), subject);
    if (name.empty() || !vm->FindBoundObject(handle, name.c_str(), object)) return 0;
    auto declared = object->GetProperty("TES4DeclaredVariables");
    if (!declared || !declared->IsString()) return 0;
    auto names = declared->GetString();
    int count = 0;
    while (!names.empty()) {
        auto end = names.find('|');
        auto property = object->GetProperty(RE::BSFixedString(names.substr(0, end)));
        if (property) {
            // Preserve the declared Papyrus type while releasing strings,
            // arrays and references exactly as resetting an OBSE variable does.
            *property = RE::BSScript::Variable(property->GetType());
            ++count;
        }
        if (end == std::string_view::npos) break;
        names.remove_prefix(end + 1);
    }
    return count;
}
RE::BSTSmartPointer<RE::BSScript::Object> boundScript(RE::TESForm* subject) {
    if (!subject) return {};
    auto script = SourceForm(nullptr, base(subject), "Script");
    const auto name = SourceString(nullptr, script, "PapyrusName");
    auto vm = RE::BSScript::Internal::VirtualMachine::GetSingleton();
    RE::BSTSmartPointer<RE::BSScript::Object> object;
    const auto handle = vm->GetObjectHandlePolicy()->GetHandleForObject(subject->GetFormType(), subject);
    if (name.empty() || !vm->FindBoundObject(handle, name.c_str(), object)) return {};
    return object;
}
RE::BSTSmartPointer<RE::BSScript::Object> boundScript(const std::string& editorID) {
    return boundScript(SourceByEditorID(editorID));
}
RE::TESForm* readReferenceVariable(RE::StaticFunctionTag*, RE::TESForm* subject, RE::BSFixedString variable) {
    auto object = boundScript(subject);
    auto property = object ? object->GetProperty(variable) : nullptr;
    return property && property->IsObject() ? property->Unpack<RE::TESForm*>() : nullptr;
}
float readVariable(RE::StaticFunctionTag*, RE::TESForm* subject, RE::BSFixedString variable) {
    auto object = boundScript(subject);
    auto property = object ? object->GetProperty(variable) : nullptr;
    if (!property) return 0;
    if (property->IsInt()) return static_cast<float>(property->GetSInt());
    if (property->IsFloat()) return property->GetFloat();
    return property->IsBool() && property->GetBool() ? 1.f : 0.f;
}
float readScriptNumber(RE::StaticFunctionTag*, std::string editorID,
                       RE::BSFixedString variable, float fallback) {
    auto object = boundScript(editorID);
    if (!object) return fallback;
    auto property = object->GetProperty(variable);
    if (!property) return fallback;
    if (property->IsFloat()) return property->GetFloat();
    if (property->IsInt()) return static_cast<float>(property->GetSInt());
    if (property->IsBool()) return property->GetBool() ? 1.f : 0.f;
    return fallback;
}
std::string readScriptString(RE::StaticFunctionTag*, std::string editorID,
                             RE::BSFixedString variable, std::string fallback) {
    auto object = boundScript(editorID);
    auto property = object ? object->GetProperty(variable) : nullptr;
    return property && property->IsString() ? std::string(property->GetString()) : fallback;
}
bool writeScriptNumber(RE::StaticFunctionTag*, std::string editorID,
                        RE::BSFixedString variable, float number) {
    if (!std::isfinite(number)) return false;
    auto object = boundScript(editorID);
    auto property = object ? object->GetProperty(variable) : nullptr;
    if (!property) return false;
    RE::BSScript::Variable value;
    if (property->IsFloat()) value.SetFloat(number);
    else if (property->IsInt()) value.SetSInt(static_cast<std::int32_t>(
        std::clamp(static_cast<double>(number), static_cast<double>(INT32_MIN), static_cast<double>(INT32_MAX))));
    else if (property->IsBool()) value.SetBool(number != 0);
    else return false;
    return RE::BSScript::Internal::VirtualMachine::GetSingleton()->SetPropertyValue(object, variable.c_str(), value);
}
bool writeScriptString(RE::StaticFunctionTag*, std::string editorID,
                        RE::BSFixedString variable, std::string text) {
    auto object = boundScript(editorID);
    auto property = object ? object->GetProperty(variable) : nullptr;
    if (!property || !property->IsString()) return false;
    RE::BSScript::Variable value;
    value.SetString(text);
    return RE::BSScript::Internal::VirtualMachine::GetSingleton()->SetPropertyValue(object, variable.c_str(), value);
}
}

bool SourceScriptRemoved(RE::StaticFunctionTag*, RE::TESForm* subject) {
    subject = base(subject);
    std::scoped_lock guard(mutex);
    return subject && removed.contains(subject->GetFormID());
}

void ResetScriptState(SKSE::MessagingInterface::Message* message) {
    // OBSE changes the in-memory base SCRI pointer, without a saved change flag.
    if (message->type == SKSE::MessagingInterface::kPreLoadGame || message->type == SKSE::MessagingInterface::kNewGame) {
        std::scoped_lock guard(mutex);
        removed.clear();
        loadedScripts.clear();
    }
}

bool RegisterScriptState(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("GameTransition", "TES4Runtime", gameTransition);
    vm->RegisterFunction("ReadReferenceVariable", "TES4Runtime", readReferenceVariable);
    vm->RegisterFunction("ReadVariable", "TES4Runtime", readVariable);
    vm->RegisterFunction("ReadScriptNumber", "TES4Runtime", readScriptNumber);
    vm->RegisterFunction("ReadScriptString", "TES4Runtime", readScriptString);
    vm->RegisterFunction("WriteScriptNumber", "TES4Runtime", writeScriptNumber);
    vm->RegisterFunction("WriteScriptString", "TES4Runtime", writeScriptString);
    vm->RegisterFunction("ResetAllVariables", "TES4Runtime", resetVariables);
    vm->RegisterFunction("RemoveScript", "TES4Runtime", removeScript);
    vm->RegisterFunction("ScriptRemoved", "TES4Runtime", SourceScriptRemoved);
    return true;
}
