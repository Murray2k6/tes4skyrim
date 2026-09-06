Scriptname TES4Runtime Hidden

Bool Function IsVirtualKeyPressed(Int key) Global Native
Bool Function IsPhysicalKeyPressed(Int key) Global Native
Bool Function GameTransition(Bool restart) Global Native
Float Function GetFrameSeconds() Global Native
Function PositionWorld(ObjectReference subject, WorldSpace destination, Float x, Float y, Float z, Float angleZ) Global Native
Form Function ReadReferenceVariable(Form subject, String variableName) Global Native
Float Function ReadVariable(Form subject, String variableName) Global Native

Int Function GetCharacterState(Actor subject) Global Native
Float Function GetBaseActorValueForForm(Form subject, String actorValue) Global Native
Float Function GetVelocity(Actor subject, Int axis) Global Native
Int Function SetVelocity(Actor subject, Float x, Float y, Float z, Bool verticalOnly = False) Global Native

Function SetCombatStyle(Actor subject, CombatStyle style) Global Native
Function SendTrespassAlarm(Actor subject, Actor criminal) Global Native
Bool Function GetTalkedToPC(Actor subject) Global Native
Bool Function GetIsPlayableRace(Actor subject) Global Native

Float Function GetStartingCoordinate(ObjectReference subject, Int axis, Bool angle = False) Global Native
WorldSpace Function GetParentWorld(WorldSpace subject) Global Native
Function SetCellPublic(Cell subject, String editorID, Bool enabled) Global Native
Function SetCellOwner(Cell subject, String editorID, Form owner) Global Native
Function SetCellName(Cell subject, String editorID, String name) Global Native
String Function AsciiToChar(Int code) Global Native
String Function GetFormIDString(Form subject) Global Native
Int Function GetClimateNumber(Form subject, Int field) Global Native
Float Function GetWeaponNumber(Form subject, Bool reach) Global Native
Enchantment Function ChangeEnchantment(Form subject, Form value, Bool remove = False) Global Native
Float Function GetTerrainHeight(Float x, Float y) Global Native
Int Function CountMatchingEffects(Form subject, Int code, Int actorValue = -1) Global Native
Int Function SpellType(Spell subject, Int value = -1, Bool writing = False) Global Native
MagicEffect Function MagicEffectFromCode(Int code) Global Native
Int Function MagicEffectCodeFromChars(String chars) Global Native
String Function GetMagicEffectChars(Int code) Global Native
Form Function GetMagicEffectUsedObject(MagicEffect subject) Global Native
Int Function ChangeMagicEffectObject(MagicEffect subject, Form value, Bool light) Global Native
Bool Function SetActorFlag(Form subject, Int mask, Bool enabled) Global Native
Int Function SetContainerRespawns(Form subject, Bool enabled) Global Native
Bool Function IsSwimming(Actor subject) Global Native
Bool Function GetGodMode() Global Native
Bool Function GetIsAlerted(Actor subject) Global Native
Bool Function GetShouldAttack(Actor subject, Actor target) Global Native
Float Function GetVampirism(Actor subject, Bool baseOnly = False) Global Native
Int Function ChangeVampirism(Actor subject, Float amount, Int operation = 0) Global Native
Bool Function GetIgnoreFriendlyHits(Actor subject) Global Native
Bool Function IsPlayersLastRiddenHorse(Actor subject) Global Native
Bool Function GetPlayerHasLastRiddenHorse() Global Native
Bool Function IsCurrentFurniture(Actor subject, Form target, Bool baseObject) Global Native
Int Function SetForcedMovement(Actor subject, Bool enabled, Bool sneak) Global Native
Function PositionCell(ObjectReference subject, Cell destination, String editorID, Float x, Float y, Float z, Float angle) Global Native
Bool Function IsClassSkill(Form subject, Int skill) Global Native
Int Function ChangeWeight(Form subject, Float value, Bool modify = False) Global Native
Int Function SetLightRadius(Form subject, Int value) Global Native
Int Function GetGoldValue(Form subject, Bool includeEnchantment = False) Global Native
Int Function ChangeGoldValue(Form subject, Float value, Bool modify = False, Bool persist = True) Global Native
Int Function SetItemValue(ObjectReference subject, Int value) Global Native
Int Function GetDifficultyLevel() Global Native
Float Function GetNumericGameSetting(String name) Global Native
Float Function GetMaxActorValue(Actor subject, String actorValue) Global Native
Bool Function SetNumericGameSetting(String name, Float value) Global Native
String Function GetStringGameSetting(String name) Global Native
Bool Function SetStringGameSetting(String formatted) Global Native

Bool Function EventHandler(String eventName, Form handler, Form firstFilter = None, Form secondFilter = None, Bool enabled = True) Global Native

Race Function GetRaceVoice(Race source, Int gender = 0) Global Native
Function SetRaceVoice(Race source, Race voice, Int gender = 2) Global Native
Bool Function FileExists(String path) Global Native
Float Function ReadScriptNumber(String editorID, String variable, Float fallback = 0.0) Global Native
String Function ReadScriptString(String editorID, String variable, String fallback = "") Global Native
Bool Function WriteScriptNumber(String editorID, String variable, Float value) Global Native
Bool Function WriteScriptString(String editorID, String variable, String value) Global Native
Function SetAlpha(ObjectReference subject, Float opacity) Global Native
Int Function GetCurrentAIPackage(Actor subject) Global Native
ObjectReference Function GetPackageTarget(Actor subject) Global Native
Function AddScriptPackage(Actor subject, Package behavior) Global Native
Function RemoveScriptPackage(Actor subject) Global Native
Float Function DispositionValue(Actor subject, Actor other, Float fallback, Float change = 0.0, Bool modify = False) Global Native

Float Function GetDisposition(Actor subject, Actor other) Global
  Int rank = subject.GetRelationshipRank(other)
  Float initial = 50.0 + rank * 20.0
  If initial < 0.0
    initial = 0.0
  ElseIf initial > 100.0
    initial = 100.0
  EndIf
  Return DispositionValue(subject, other, initial)
EndFunction

Function ModDisposition(Actor subject, Actor other, Float change) Global
  Float value = DispositionValue(subject, other, GetDisposition(subject, other), change, True)
  ; Keep the engine dialogue gates consistent with dialog_conditions.py.
  Int rank = 0
  If value < 20.0
    rank = -2
  ElseIf value < 40.0
    rank = -1
  ElseIf value <= 60.0
    rank = 0
  ElseIf value < 80.0
    rank = 1
  Else
    rank = 2
  EndIf
  subject.SetRelationshipRank(other, rank)
EndFunction

ObjectReference Function GetWorldMapDoor() Global Native
String Function GetMapMenuMarkerName() Global Native
ObjectReference Function GetMapMenuMarkerRef() Global Native
Int Function GetMapMarkerType(ObjectReference subject) Global Native
Int Function GetInvestmentGold(ObjectReference subject) Global Native
Function SetInvestmentGold(ObjectReference subject, Int gold) Global Native
Float Function EquippedValue(Actor subject, Int slot, Bool charge = False, Int operation = 0, Float value = 0.0) Global Native
Int Function ResetAllVariables(Form subject, String attachedType = "") Global Native
Quest[] Function GetActiveQuests() Global Native

Quest Function GetActiveQuest() Global
  Quest[] active = GetActiveQuests()
  If active.Length
    Return active[0]
  EndIf
  Return None
EndFunction

Function SetActiveQuest(Quest subject) Global
  Quest[] active = GetActiveQuests()
  Int index = active.Length
  While index > 0
    index -= 1
    If active[index] != subject
      active[index].SetActive(False)
    EndIf
  EndWhile
  If subject
    subject.SetActive(True)
  EndIf
EndFunction

Int Function GetPCSleepHours() Global Native
Package Function GetCurrentEditorPackage(Actor subject) Global Native
Package Function GetNthPackage(Form subject, Int index) Global Native
Int Function GetNumPackages(Form subject) Global Native
Function StoreMessageButton(Int index) Global Native
Int Function TakeMessageButton() Global Native
Bool Function IsThirdPerson() Global Native
Bool Function IsMovingForward(Actor subject) Global Native
Bool Function IsTorchOut(Actor subject) Global Native
Bool Function IsSnowing() Global Native
Actor Function GetHorse(Actor subject, Bool rider = False) Global Native
Actor Function GetPlayersLastRiddenHorse() Global Native
Bool Function IsActivatable(ObjectReference subject) Global Native
Bool Function IsOffLimits(ObjectReference subject) Global Native
Bool Function CanDeleteReference(ObjectReference subject) Global Native

Bool Function DeleteReference(ObjectReference subject) Global
  If !CanDeleteReference(subject) || GetInventoryContainer(subject)
    Return False
  EndIf
  subject.Delete()
  Return True
EndFunction
Int Function GetProjectileType(Form subject) Global Native
ObjectReference Function GetProjectileSource(Form subject) Global Native
Form Function GetMagicProjectileSpell(Form subject) Global Native
ObjectReference Function GetProjectile(Actor subject, Int kind = 0, Float lifetime = 9999.0, Form match = None) Global Native
Float Function StringToNumber(String text, Bool hexadecimal = False) Global Native
String Function NumberToString(Float value) Global Native
{Open-source Skyrim runtime for translated TES4 script operations.}

Bool Function Available() Global Native
Bool Function IsTextInputInUse() Global Native
Bool Function IsGamepadConnected(Int index = -1) Global Native
Bool Function IsGamepadKeyPressed(Int index, Int key, Int flags = 0) Global Native
ObjectReference Function GetActiveMenuRef(Int menu = 0) Global Native
Form Function GetActiveMenuSelection(Int menu = 0) Global Native
Int Function StringSearch(String text, String needle, Int start = 0, Int length = -1, Bool caseSensitive = False, Bool count = False) Global Native
String Function StringAt(String text, Int index) Global Native
Int Function CharToAscii(String text) Global Native
Bool Function IsAttacking(Actor subject) Global Native
Bool Function IsBlocking(Actor subject) Global Native
Bool Function GetForceRun(Actor subject) Global Native
Bool Function GetForceSneak(Actor subject) Global Native
Bool Function IsClonedForm(Form subject) Global Native
String Function GetName(Form subject) Global Native
Bool Function NameIncludes(Form subject, String text) Global Native
Int Function SetName(Form subject, String text) Global Native
Int Function CopyName(Form source, Form target, Form caller) Global Native
Int Function AppendToName(String suffix, Form target, Form caller) Global Native
Function SetActorFullName(Actor subject, String text) Global Native
String Function GetDescription(Form subject) Global Native
Bool Function HasName(Form subject) Global Native
Int Function GetSoulLevel(Form subject, Bool capacity = False) Global Native
Bool Function IsPowerAttacking(Actor subject) Global Native
Bool Function IsTrespassing(Actor subject) Global Native
Float Function GetActorLightAmount(Actor subject) Global Native
Form Function GetPlayerSpell() Global Native
Form Function RemoveScript(Form subject) Global Native
Bool Function ScriptRemoved(Form subject) Global Native

TES4Collection Function GetCreatureModelPaths(Form subject) Global
  TES4Collection result = TES4Collection.Create("Array")
  Int total = SourceInt(subject, "CreatureModelCount")
  Int index = 0
  While index < total
    result.SetString(index as String, SourceString(subject, "CreatureModel" + index))
    index += 1
  EndWhile
  Return result
EndFunction
Int Function GetActiveEffectCount(Actor subject) Global Native
Form Function GetActiveEffectForm(Actor subject, Int index, String field) Global Native
Float Function GetActiveEffectNumber(Actor subject, Int index, String field) Global Native
Int Function GetActiveEffectCode(Actor subject, Int index) Global Native
Bool Function IsActiveEffectApplied(Actor subject, Int index) Global Native
Bool Function DispelActiveEffect(Actor subject, Int index) Global Native
Int Function DispelMagicItem(Actor subject, Form magicItem) Global Native
Int Function GetNumFactions(Form subject) Global Native
Int Function SourceFactionReaction(Faction subject, Faction other) Global Native
Function SetFactionFightReaction(Faction subject, Faction other, Int value) Global Native

Int Function GetFactionReaction(Faction subject, Faction other) Global
  Return SourceFactionReaction(subject, other) + subject.GetReaction(other)
EndFunction

Function SetFactionReaction(Faction subject, Faction other, Int value) Global
  ; Skyrim's saved reaction modifier starts at zero in converted FACT records.
  subject.SetReaction(other, value - SourceFactionReaction(subject, other))
  SetFactionFightReaction(subject, other, value)
EndFunction

Function ModFactionReaction(Faction subject, Faction other, Int amount) Global
  SetFactionReaction(subject, other, GetFactionReaction(subject, other) + amount)
EndFunction
Faction Function GetNthFaction(Form subject, Int index) Global Native
Int Function GetNthFactionRank(Form subject, Int index) Global Native

TES4Collection Function GetFactions(Form subject) Global
  TES4Collection result = TES4Collection.Create("Array")
  Int total = GetNumFactions(subject)
  Int index = 0
  While index < total
    result.SetForm(index as String, GetNthFaction(subject, index))
    index += 1
  EndWhile
  Return result
EndFunction

ObjectReference Function GetFirstRef(String script, Cell origin = None, Int formType = 0, Int depth = 0, Bool includeTaken = False, Bool includeDeleted = False) Global Native
ObjectReference Function GetNextRef(String script) Global Native
Int Function GetNumRefs(Cell origin = None, Int formType = 0, Int depth = 0, Bool includeTaken = False, Bool includeDeleted = False) Global Native
Int Function GetObjectType(Form subject) Global Native
Int Function GetCreatureType(Form subject) Global Native
Int Function GetArmorType(Form subject) Global Native
Int Function GetWeaponType(Form subject) Global Native
Bool Function IsFood(Form subject) Global Native
Int Function SourceInt(Form subject, String field, Int fallback = 0) Global Native
Form Function SourceForm(Form subject, String field) Global Native
Float Function SourceFloat(Form subject, String field, Float fallback = 0.0) Global Native
String Function SourceString(Form subject, String field) Global Native
Bool Function SourceContains(Form subject, String field, String text) Global Native
Float Function GetBoundingRadius(ObjectReference subject) Global Native
Float Function GetWeight(Form subject) Global Native
Enchantment Function GetEnchantment(Form subject) Global Native
Int Function GetEquipmentSlot(Form subject) Global Native
Form Function GetEquippedObject(Actor subject, Int slot) Global Native
Potion Function GetEquippedWeaponPoison(Actor subject) Global Native
ObjectReference Function GetLastDroppedReference() Global Native
Form Function GetLastDroppedItem() Global Native
Float Function GetTeleportCoordinate(ObjectReference subject, Int axis) Global Native
Potion Function ChangeEquippedWeaponPoison(Actor subject, Potion value, Bool remove) Global Native
Bool Function IsLightCarriable(Form subject) Global Native
Bool Function IsEquipped(Form subject) Global Native
Int Function BeginInventory(ObjectReference container, Form item = None) Global Native
Int Function GetCurrentSoulLevel(Form subject) Global Native
Int Function InventorySize(Int cursor) Global Native
ObjectReference Function InventoryReference(Int cursor, Int index) Global Native
Function EndInventory(Int cursor) Global Native
Bool Function RemoveInventoryReference(Form subject, ObjectReference destination = None) Global Native
Bool Function EquipInventoryReference(Form subject, Bool equipped = True) Global Native
Int Function GetRefCount(Form subject) Global Native
ObjectReference Function GetInventoryContainer(Form subject) Global Native
Float Function GetCurrentHealth(Form subject) Global Native
Function SetCurrentHealth(Form subject, Float value) Global Native
Float Function GetCurrentCharge(Form subject) Global Native
Function SetCurrentCharge(Form subject, Float value) Global Native
Form Function GetOwner(Form subject) Global Native
Function SetOwner(Form subject, Form owner, Bool save = True) Global Native
ObjectReference Function GetLinkedDoor(ObjectReference subject) Global Native

Cell Function GetTeleportCell(ObjectReference subject) Global
  ObjectReference destination = GetLinkedDoor(subject)
  If destination != None
    Return destination.GetParentCell()
  EndIf
  Return None
EndFunction
Bool Function HasWater(Form subject) Global Native
Float Function GetParentCellWaterHeight(ObjectReference subject) Global Native
Bool Function IsInOblivion(ObjectReference subject) Global Native
Int Function GetSourceModIndex(Form subject) Global Native
Bool Function IsPersistent(ObjectReference subject) Global Native
Key Function GetOpenKey(ObjectReference subject) Global Native
Form Function GetCurrentClimateID() Global Native
Float Function GetAVModifier(Actor subject, String actorValue, String modifier) Global Native
Int Function StringLength(String text) Global Native
String Function StringSlice(String text, Int start, Int length = -1) Global Native
String[] Function StringEdit(String text, String formatted, String operation, Int start = 0, Int length = -1, Bool caseSensitive = False, Int limit = -1) Global Native
Float Function ModifyAVModifier(Actor subject, String actorValue, String modifier, Float amount, Bool absolute = False) Global Native
Int Function GetWeatherColor(Int component, Int color, Weather subject, Int time = 0) Global Native
Function SetWeatherColor(Int red, Int green, Int blue, Int color, Weather subject, Int time = 0) Global Native
Float Function GetWeatherSunDamage(Weather subject) Global Native

Function AddToLeveledList(Form subject, Form item, Int level = 1, Int count = 1) Global Native
Function ClearLeveledList(Form subject) Global Native
Int Function RemoveFromLeveledList(Form subject, Form item) Global Native
Int Function RemoveLevItemByLevel(Int level, Form subject) Global Native
Function RemoveNthLevItem(Int index, Form subject) Global Native
Int Function GetNumLevItems(Form subject) Global Native
Form Function GetNthLevItem(Int index, Form subject) Global Native
Int Function GetNthLevItemLevel(Int index, Form subject) Global Native
Int Function GetNthLevItemCount(Int index, Form subject) Global Native
Int Function GetChanceNone(Form subject) Global Native
Function SetChanceNone(Int chance, Form subject) Global Native
Bool Function GetCalcAllLevels(Form subject) Global Native
Bool Function GetCalcEachInCount(Form subject) Global Native
Int Function GetLevItemIndexByForm(Form subject, Form item) Global Native
Int Function GetLevItemIndexByLevel(Int level, Form subject) Global Native
Form Function GetLevItemByLevel(Int level, Form subject) Global Native
Form Function CalcLeveledItem(Form subject, Int level, Bool useChanceNone = True, Int levelDifference = -1, Bool recurse = True) Global Native
