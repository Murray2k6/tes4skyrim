#include <RE/Skyrim.h>
#include <SKSE/SKSE.h>
#include <algorithm>
#include <charconv>
#include <cmath>
#include <functional>
#include <mutex>
#include <limits>

std::vector<RE::TESForm*> MapMarkers(int, int);
int SourceInt(RE::StaticFunctionTag*, RE::TESForm*, std::string, int);
int SourceObjectType(RE::TESForm*);

namespace {
using namespace RE::BSScript;
using Obj = RE::BSTSmartPointer<Object>;
using Arr = RE::BSTSmartPointer<Array>;
using Args = std::vector<Variable>;
using Raw = TypeInfo::RawType;
constexpr int pageSize = 128;
std::recursive_mutex lock;

TypeInfo type(IVirtualMachine* vm, std::string_view name) {
    if (name == "Int") return TypeInfo(Raw::kInt);
    if (name == "Float") return TypeInfo(Raw::kFloat);
    if (name == "String") return TypeInfo(Raw::kString);
    if (name == "Bool") return TypeInfo(Raw::kBool);
    if (name.empty()) return TypeInfo(Raw::kNone);
    RE::BSTSmartPointer<ObjectTypeInfo> info;
    vm->GetScriptObjectType(RE::BSFixedString(name), info);
    return TypeInfo(static_cast<Raw>(reinterpret_cast<std::uintptr_t>(info.get())));
}
Variable& prop(const Obj& obj, const char* name) {
    return *obj->GetProperty(name);
}
Variable number(float value) { Variable r; r.SetFloat(value); return r; }
Variable integer(int value) { Variable r; r.SetSInt(value); return r; }
Variable string(std::string_view value) { Variable r; r.SetString(value); return r; }
Variable object(const Obj& value) { Variable r; r.SetObject(value); return r; }
Variable boolean(bool value) { Variable r; r.SetBool(value); return r; }
int count(const Obj& obj) { return obj ? prop(obj, "Count").GetSInt() : -1; }

Obj create(IVirtualMachine* vm, const char* name) {
    Obj obj;
    if (!vm->CreateObject(name, obj)) return {};
    obj->constructed = true;
    obj->initialized = true;
    obj->valid = true;
    return obj;
}
Obj page(IVirtualMachine* vm) {
    auto p = create(vm, "TES4CollectionPage");
    if (!p) return {};
    for (auto [name, element] : {std::pair{"Keys", "String"}, {"Types", "Int"},
         {"Numbers", "Float"}, {"Strings", "String"}, {"Forms", "Form"}, {"Arrays", "TES4Collection"}, {"Integers", "Int"}}) {
        Arr a;
        if (!vm->CreateArray(type(vm, element), pageSize, a)) return {};
        prop(p, name).SetArray(a);
    }
    return p;
}
Obj pageAt(IVirtualMachine* vm, const Obj& obj, int index, bool grow) {
    auto p = prop(obj, "First").GetObject();
    if (!p && grow) { p = page(vm); prop(obj, "First").SetObject(p); }
    for (int n = index / pageSize; p && n; --n) {
        auto next = prop(p, "Next").GetObject();
        if (!next && grow) { next = page(vm); prop(p, "Next").SetObject(next); }
        p = next;
    }
    return p;
}
Variable& slot(const Obj& p, const char* field, int index) {
    return (*prop(p, field).GetArray())[index % pageSize];
}
double numericKey(std::string_view key) {
    std::string s(key);
    char* end;
    const auto value = std::strtod(s.c_str(), &end);
    return !s.empty() && end == s.c_str() + s.size() && std::isfinite(value) ? value : std::numeric_limits<double>::quiet_NaN();
}
int indexOf(IVirtualMachine* vm, const Obj& obj, std::string_view key) {
    if (!obj) return -1;
    const int kind = prop(obj, "Kind").GetSInt();
    if (kind == 0) {
        auto n = numericKey(key);
        if (n < 0) n += count(obj);
        return n >= 0 && n < count(obj) ? int(n) : -1;
    }
    auto p = prop(obj, "First").GetObject();
    for (int i = 0; i < count(obj) && p; ++i) {
        if (i && i % pageSize == 0) p = prop(p, "Next").GetObject();
        auto stored = slot(p, "Keys", i).GetString();
        if (kind == 2 ? stored == key : numericKey(stored) == numericKey(key)) return i;
    }
    return -1;
}
const char* fieldFor(int valueType) {
    return valueType == 2 ? "Forms" : valueType == 3 ? "Strings" : valueType == 4 ? "Arrays" : valueType == 5 ? "Integers" : "Numbers";
}
void clear(const Obj& p, int index) {
    slot(p, "Types", index).SetSInt(0);
    slot(p, "Numbers", index).SetFloat(0);
    slot(p, "Integers", index).SetSInt(0);
    slot(p, "Strings", index).SetString("");
    slot(p, "Forms", index).SetNone();
    slot(p, "Arrays", index).SetNone();
}
void setAt(IVirtualMachine* vm, const Obj& obj, int index, int valueType, const Variable& value) {
    auto p = pageAt(vm, obj, index, true);
    if (!p) return;
    Variable copied(value);  // Copy before clearing: source and destination can alias.
    clear(p, index);
    slot(p, "Types", index).SetSInt(valueType);
    slot(p, fieldFor(valueType), index) = copied;
}
void set(IVirtualMachine* vm, const Obj& obj, std::string_view key, int valueType, const Variable& value) {
    if (!obj) return;
    const int kind = prop(obj, "Kind").GetSInt();
    if (kind != 2 && !std::isfinite(numericKey(key))) return;
    int index = indexOf(vm, obj, key);
    if (index < 0) {
        index = count(obj);
        // Packed arrays accept only the next index; sparse keys belong to Map.
        if (kind == 0 && std::trunc(numericKey(key)) != index) return;
        auto p = pageAt(vm, obj, index, true);
        if (!p) return;
        // OBSE maps iterate by sorted key, independent of insertion order.
        if (kind != 0) {
            while (index > 0) {
                auto prev = pageAt(vm, obj, index - 1, false);
                auto prior = slot(prev, "Keys", index - 1).GetString();
                if (!(kind == 2 ? key < prior : numericKey(key) < numericKey(prior))) break;
                auto dst = pageAt(vm, obj, index, true);
                for (auto field : {"Keys", "Types", "Numbers", "Strings", "Forms", "Arrays", "Integers"})
                    slot(dst, field, index) = slot(prev, field, index - 1);
                --index;
            }
        }
        slot(pageAt(vm, obj, index, true), "Keys", index).SetString(key);
        prop(obj, "Count").SetSInt(count(obj) + 1);
    }
    setAt(vm, obj, index, valueType, value);
}
Variable get(IVirtualMachine* vm, const Obj& obj, std::string_view key, int expected) {
    int index = indexOf(vm, obj, key);
    auto p = index < 0 ? Obj{} : pageAt(vm, obj, index, false);
    if (p && slot(p, "Types", index).GetSInt() == expected) return slot(p, fieldFor(expected), index);
    if (p && expected == 1 && slot(p, "Types", index).GetSInt() == 5)
        return number(static_cast<float>(slot(p, "Integers", index).GetSInt()));
    if (expected == 5) {
        if (p && slot(p, "Types", index).GetSInt() == 1) {
            double value = slot(p, "Numbers", index).GetFloat();
            if (std::isfinite(value) && value >= INT_MIN && value <= INT_MAX) return integer(static_cast<int>(value));
        }
        return integer(0);
    }
    if (expected == 1) return number(0);
    if (expected == 3) return string("");
    return {};
}
void resize(IVirtualMachine* vm, const Obj& obj, int size, int valueType, const Variable& value) {
    if (!obj || size < 0 || prop(obj, "Kind").GetSInt() != 0) return;
    const auto old = count(obj);
    for (int i = old; i < size; ++i) set(vm, obj, std::to_string(i), valueType, value);
    for (int i = size; i < old; ++i) clear(pageAt(vm, obj, i, false), i);
    prop(obj, "Count").SetSInt(size);
    if (!size) prop(obj, "First").SetNone();
    else if (auto p = pageAt(vm, obj, size - 1, false)) prop(p, "Next").SetNone();
}
int append(IVirtualMachine* vm, const Obj& obj, int valueType, const Variable& value) {
    // xOBSE ar_Append inserts at SizeOf and rejects non-packed arrays.
    if (!obj || prop(obj, "Kind").GetSInt() != 0) return 0;
    const auto before = count(obj);
    set(vm, obj, std::to_string(before), valueType, value);
    return count(obj) == before + 1 ? 1 : 0;
}
int erase(IVirtualMachine* vm, const Obj& obj, std::string_view key) {
    if (!obj) return -1;
    int index = indexOf(vm, obj, key);
    if (index < 0) return 0;
    const int old = count(obj);
    for (int i = index; i < old - 1; ++i) {
        auto dst = pageAt(vm, obj, i, false), src = pageAt(vm, obj, i + 1, false);
        for (auto field : {"Keys", "Types", "Numbers", "Strings", "Forms", "Arrays", "Integers"})
            slot(dst, field, i) = slot(src, field, i + 1);
    }
    clear(pageAt(vm, obj, old - 1, false), old - 1);
    prop(obj, "Count").SetSInt(old - 1);
    if (old == 1) prop(obj, "First").SetNone();
    else prop(pageAt(vm, obj, old - 2, false), "Next").SetNone();
    return 1;
}

using Callback = std::function<Variable(IVirtualMachine*, Obj, const Args&)>;
class Function final : public NF_util::NativeFunctionBase {
    Callback callback;
public:
    Function(IVirtualMachine* vm, const char* name, const char* result, std::initializer_list<const char*> params,
             Callback cb, bool global = false) : NativeFunctionBase(name, "TES4Collection", global, std::uint16_t(params.size())), callback(std::move(cb)) {
        _retType = type(vm, result);
        int i = 0;
        for (auto param : params) _descTable.entries[i++].second = type(vm, param);
    }
    bool HasStub() const override { return true; }
    bool MarshallAndDispatch(Variable& base, Internal::VirtualMachine& vm, RE::VMStackID, Variable& result, const StackFrame& frame) const override {
        std::scoped_lock guard(lock);
        Args args;
        auto framePage = frame.GetPageForFrame();
        for (std::uint32_t i = 0; i < GetParamCount(); ++i) args.push_back(frame.GetStackFrameVariable(i, framePage));
        result = callback(&vm, _isStatic ? Obj{} : base.GetObject(), args);
        return true;
    }
};
}

bool RegisterCollections(RE::BSScript::IVirtualMachine* vm) {
    auto bind = [&](const char* name, const char* result, std::initializer_list<const char*> args, Callback cb, bool global = false) {
        vm->BindNativeMethod(new Function(vm, name, result, args, std::move(cb), global));
    };
    bind("Create", "TES4Collection", {"String"}, [](auto vm, auto, const Args& a) {
        auto obj = create(vm, "TES4Collection");
        if (obj) {
            prop(obj, "Kind").SetSInt(a[0].GetString() == "StringMap" ? 2 : a[0].GetString() == "Map" ? 1 : 0);
            prop(obj, "Count").SetSInt(0);
            prop(obj, "First").SetNone();
        }
        return object(obj);
    }, true);
    bind("Size", "Int", {}, [](auto, auto obj, const auto&) {return integer(count(obj));});
    bind("Inventory", "TES4Collection", {"Form", "Bool"}, [](auto vm, auto, const Args& a) {
        auto obj = create(vm, "TES4Collection");
        if (!obj) return object(obj);
        auto form = a[0].Unpack<RE::TESForm*>();
        auto ref = form ? form->As<RE::TESObjectREFR>() : nullptr;
        if (a[1].GetBool()) {
            if (auto actor = ref ? ref->As<RE::Actor>() : nullptr)
                for (const auto& [item, data] : actor->GetInventory())
                    if (data.second && data.second->IsWorn()) {
                        Variable value;
                        RE::TESForm* base = item;
                        PackValue(&value, base);
                        set(vm, obj, std::to_string(count(obj)), 2, value);
                    }
        } else {
            if (ref) form = ref->GetBaseObject();
            auto container = form ? form->As<RE::TESContainer>() : nullptr;
            if (container) container->ForEachContainerObject([&](const auto& entry) {
                auto row = create(vm, "TES4Collection");
                if (row) {
                    prop(row, "Kind").SetSInt(2);
                    Variable value;
                    RE::TESForm* base = entry.obj;
                    PackValue(&value, base);
                    set(vm, row, "item", 2, value);
                    set(vm, row, "count", 1, number(static_cast<float>(entry.count)));
                    set(vm, obj, std::to_string(count(obj)), 4, object(row));
                }
                return RE::BSContainer::ForEachResult::kContinue;
            });
        }
        return object(obj);
    }, true);
    bind("Items", "TES4Collection", {"ObjectReference", "TES4Collection"}, [](auto vm, auto, const Args& a) {
        auto obj = create(vm, "TES4Collection");
        auto owner = a[0].Unpack<RE::TESObjectREFR*>();
        auto filter = a[1].GetObject();
        std::vector<int> types;
        for (int i = 0; i < count(filter); ++i) {
            int value = get(vm, filter, std::to_string(i), 5).GetSInt();
            if (!value) break;
            types.push_back(value);
        }
        if (obj && owner) for (const auto& [item, entry] : owner->GetInventory()) {
            if (!item || entry.first <= 0) continue;
            if (!types.empty() && std::find(types.begin(), types.end(), SourceObjectType(item)) == types.end()) continue;
            Variable value;
            RE::TESForm* form = item;
            PackValue(&value, form);
            set(vm, obj, std::to_string(count(obj)), 2, value);
        }
        return object(obj);
    }, true);
    bind("ActiveEffects", "TES4Collection", {"Actor", "Bool"}, [](auto vm, auto, const Args& a) {
        auto obj = create(vm, "TES4Collection");
        auto actor = a[0].Unpack<RE::Actor*>();
        auto list = actor ? actor->AsMagicTarget()->GetActiveEffectList() : nullptr;
        if (obj && list) for (auto effect : *list) {
            if (!effect) break;
            Variable value;
            int kind = a[1].GetBool() ? 2 : 5;
            if (kind == 2) {
                RE::TESForm* caster = effect->GetCasterActor().get();
                PackValue(&value, caster);
            } else value = integer(SourceInt(nullptr, effect->GetBaseObject(), "EffectCode", 0));
            set(vm, obj, std::to_string(count(obj)), kind, value);
        }
        return object(obj);
    }, true);
    bind("BoundingBox", "TES4Collection", {"Actor"}, [](auto vm, auto, const Args& a) {
        auto actor = a[0].Unpack<RE::Actor*>();
        if (!actor || !actor->Is3DLoaded()) return object({});
        const auto low = actor->GetBoundMin();
        const auto high = actor->GetBoundMax();
        const auto center = (high + low) * 0.5f;
        const auto extent = (high - low) * 0.5f;
        auto obj = create(vm, "TES4Collection");
        if (!obj) return object(obj);
        prop(obj, "Kind").SetSInt(2);
        for (auto [key, point] : {std::pair{"center", center}, {"extent", extent}}) {
            auto vector = create(vm, "TES4Collection");
            if (!vector) return object({});
            prop(vector, "Kind").SetSInt(2);
            set(vm, vector, "x", 1, number(point.x));
            set(vm, vector, "y", 1, number(point.y));
            set(vm, vector, "z", 1, number(point.z));
            set(vm, obj, key, 4, object(vector));
        }
        return object(obj);
    }, true);
    bind("CombatActors", "TES4Collection", {"Actor", "Bool"}, [](auto vm, auto, const Args& a) {
        auto obj = create(vm, "TES4Collection");
        auto actor = a[0].Unpack<RE::Actor*>();
        auto group = actor ? actor->GetCombatGroup() : nullptr;
        if (!obj || !group) return object(obj);
        RE::BSReadLockGuard guard(group->lock);
        auto append = [&](RE::ActorHandle handle) {
            auto ref = handle.get();
            if (!ref || ref.get() == actor) return;
            RE::TESForm* form = ref.get();
            Variable value;
            PackValue(&value, form);
            set(vm, obj, std::to_string(count(obj)), 2, value);
        };
        if (a[1].GetBool()) for (auto& target : group->targets) append(target.targetHandle);
        else for (auto& member : group->members) append(member.memberHandle);
        return object(obj);
    }, true);
    bind("Spells", "TES4Collection", {"Form", "Bool"}, [](auto vm, auto, const Args& a) {
        auto obj = create(vm, "TES4Collection");
        if (!obj) return object(obj);
        auto form = a[0].Unpack<RE::TESForm*>();
        auto actor = form ? form->As<RE::Actor>() : nullptr;
        if (auto ref = form ? form->As<RE::TESObjectREFR>() : nullptr) form = ref->GetBaseObject();
        auto npc = form ? form->As<RE::TESNPC>() : nullptr;
        auto list = npc ? npc->GetSpellList() : nullptr;
        std::vector<RE::TESForm*> spells;
        if (list) {
            if (a[1].GetBool()) for (unsigned i = 0; i < list->numlevSpells; ++i) spells.push_back(list->levSpells[i]);
            else for (unsigned i = 0; i < list->numSpells; ++i) spells.push_back(list->spells[i]);
        }
        // TES4 AddSpell changed the base list; Skyrim keeps added spells on
        // the actor. Include that state in the translated actor's spell list.
        if (actor && !a[1].GetBool()) for (auto spell : actor->GetActorRuntimeData().addedSpells)
            if (std::find(spells.begin(), spells.end(), spell) == spells.end()) spells.push_back(spell);
        for (auto spell : spells) {
            Variable value;
            PackValue(&value, spell);
            set(vm, obj, std::to_string(count(obj)), 2, value);
        }
        return object(obj);
    }, true);
    bind("MapMarkers", "TES4Collection", {"Int", "Int"}, [](auto vm, auto, const auto& a) {
        auto obj = create(vm, "TES4Collection");
        if (!obj) return object(obj);
        prop(obj, "Kind").SetSInt(0);
        prop(obj, "Count").SetSInt(0);
        prop(obj, "First").SetNone();
        for (auto form : MapMarkers(a[0].GetSInt(), a[1].GetSInt())) {
            Variable value;
            PackValue(&value, form);
            set(vm, obj, std::to_string(count(obj)), 2, value);
        }
        return object(obj);
    }, true);
    bind("Actors", "TES4Collection", {"Int"}, [](auto vm, auto, const auto& a) {
        auto obj = create(vm, "TES4Collection");
        if (!obj) return object(obj);
        prop(obj, "Kind").SetSInt(0);
        prop(obj, "Count").SetSInt(0);
        prop(obj, "First").SetNone();
        auto processes = RE::ProcessLists::GetSingleton();
        int level = a[0].GetSInt();
        if (processes && level >= 0 && level < 4) {
            auto list = processes->allProcesses[level];
            if (list) for (auto handle : *list) if (auto actor = handle.get()) {
                Variable value;
                RE::TESForm* form = actor.get();
                PackValue(&value, form);
                set(vm, obj, std::to_string(count(obj)), 2, value);
            }
        }
        return object(obj);
    }, true);
    bind("HasKey", "Bool", {"String"}, [](auto vm, auto obj, const auto& a) {return boolean(indexOf(vm,obj,a[0].GetString()) >= 0);});
    bind("ValueType", "Int", {"String"}, [](auto vm, auto obj, const auto& a) {
        int i = indexOf(vm,obj,a[0].GetString());
        int kind = i < 0 ? 0 : slot(pageAt(vm,obj,i,false),"Types",i).GetSInt();
        return integer(kind == 5 ? 1 : kind);
    });
    bind("KeyAt", "String", {"Int"}, [](auto vm, auto obj, const auto& a) {
        int i=a[0].GetSInt();
        if(i < 0 || i >= count(obj)) return string("");
        return prop(obj,"Kind").GetSInt() == 0 ? string(std::to_string(i)) : slot(pageAt(vm,obj,i,false),"Keys",i);
    });
    const char* names[] = {"Number", "Form", "String", "Array", "Integer"};
    const char* types[] = {"Float", "Form", "String", "TES4Collection", "Int"};
    for (int k=1;k<=5;++k) {
        const auto suffix=std::string(names[k-1]);
        bind(("Get"+suffix).c_str(), types[k-1], {"String"}, [k](auto vm, auto obj, const auto& a) {return get(vm,obj,a[0].GetString(),k);});
        bind(("Set"+suffix).c_str(), "", {"String",types[k-1]}, [k](auto vm, auto obj, const auto& a) {set(vm,obj,a[0].GetString(),k,a[1]);return Variable{};});
        bind(("Append"+suffix).c_str(), "Int", {types[k-1]}, [k](auto vm, auto obj, const auto& a) {return integer(append(vm,obj,k,a[0]));});
        if(k != 4) bind(("Resize"+suffix).c_str(), "", {"Int",types[k-1]}, [k](auto vm, auto obj, const auto& a) {resize(vm,obj,a[0].GetSInt(),k,a[1]);return Variable{};});
        bind(("Find"+suffix).c_str(), "String", {types[k-1]}, [k](auto vm, auto obj, const auto& a) {
            for(int i=0;i<count(obj);++i) {
                auto p=pageAt(vm,obj,i,false);
                int stored = slot(p,"Types",i).GetSInt();
                bool numeric = (k == 1 || k == 5) && (stored == 1 || stored == 5);
                if(stored == k || numeric) {
                    const auto& value = slot(p,fieldFor(k),i);
                    const double numberValue = numeric ? (stored == 5 ? double(slot(p,"Integers",i).GetSInt()) : double(slot(p,"Numbers",i).GetFloat())) : 0;
                    const bool equal = numeric ? numberValue == (k == 5 ? double(a[0].GetSInt()) : double(a[0].GetFloat())) :
                        k == 3 ? _stricmp(std::string(value.GetString()).c_str(), std::string(a[0].GetString()).c_str()) == 0 : value == a[0];
                    if(equal) return prop(obj,"Kind").GetSInt() == 0 ? string(std::to_string(i)) : slot(p,"Keys",i);
                }
            }
            return string(obj && prop(obj,"Kind").GetSInt() == 2 ? "" : "-99999");
        });
    }
    bind("Erase", "Int", {"String"}, [](auto vm, auto obj, const auto& a) {return integer(erase(vm,obj,a[0].GetString()));});
    bind("Clear", "Int", {}, [](auto, auto obj, const auto&) {
        int removed = count(obj);
        if (obj) { prop(obj,"First").SetNone(); prop(obj,"Count").SetSInt(0); }
        return integer(removed);
    });
    bind("CopyValue", "", {"String", "TES4Collection", "String"}, [](auto vm, auto obj, const auto& a) {
        auto src = a[1].GetObject();
        int i = indexOf(vm, src, a[2].GetString());
        if (i >= 0) {
            auto p = pageAt(vm, src, i, false);
            int k = slot(p, "Types", i).GetSInt();
            Variable value(slot(p, fieldFor(k), i));
            set(vm, obj, a[0].GetString(), k, value);
        }
        return Variable{};
    });
    bind("AppendValue", "Int", {"TES4Collection", "String"}, [](auto vm, auto obj, const auto& a) {
        auto src = a[0].GetObject();
        int i = indexOf(vm, src, a[1].GetString());
        if (i < 0) return integer(0);
        auto p = pageAt(vm, src, i, false);
        int k = slot(p, "Types", i).GetSInt();
        Variable value(slot(p, fieldFor(k), i));
        return integer(append(vm, obj, k, value));
    });
    return true;
}
