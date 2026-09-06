Scriptname TES4OBSEState extends Quest
{Shared mutable state for OBSE record operations that SKSE64 does not expose
as direct setters. The converter creates and binds every FormList property.}

FormList Property TES4SpellType0 Auto
FormList Property TES4SpellType1 Auto
FormList Property TES4SpellType2 Auto
FormList Property TES4SpellType3 Auto
FormList Property TES4SpellType4 Auto
FormList Property TES4SpellType5 Auto
FormList Property TES4SpellTypeOverride0 Auto
FormList Property TES4SpellTypeOverride1 Auto
FormList Property TES4SpellTypeOverride2 Auto
FormList Property TES4SpellTypeOverride3 Auto
FormList Property TES4SpellTypeOverride4 Auto
FormList Property TES4SpellTypeOverride5 Auto
FormList Property TES4SpellTypeChanged Auto

FormList Property TES4MapMarkers Auto
FormList Property TES4MapMarkerType0 Auto
FormList Property TES4MapMarkerType1 Auto
FormList Property TES4MapMarkerType2 Auto
FormList Property TES4MapMarkerType3 Auto
FormList Property TES4MapMarkerType4 Auto
FormList Property TES4MapMarkerType5 Auto
FormList Property TES4MapMarkerType6 Auto
FormList Property TES4MapMarkerType7 Auto
FormList Property TES4MapMarkerType8 Auto
FormList Property TES4MapMarkerType9 Auto
FormList Property TES4MapMarkerType10 Auto
FormList Property TES4MapMarkerType11 Auto
FormList Property TES4MapMarkerTypeOverride0 Auto
FormList Property TES4MapMarkerTypeOverride1 Auto
FormList Property TES4MapMarkerTypeOverride2 Auto
FormList Property TES4MapMarkerTypeOverride3 Auto
FormList Property TES4MapMarkerTypeOverride4 Auto
FormList Property TES4MapMarkerTypeOverride5 Auto
FormList Property TES4MapMarkerTypeOverride6 Auto
FormList Property TES4MapMarkerTypeOverride7 Auto
FormList Property TES4MapMarkerTypeOverride8 Auto
FormList Property TES4MapMarkerTypeOverride9 Auto
FormList Property TES4MapMarkerTypeOverride10 Auto
FormList Property TES4MapMarkerTypeOverride11 Auto
FormList Property TES4MapMarkerTypeChanged Auto
FormList Property TES4MapMarkerVisibilityChanged Auto
FormList Property TES4MapMarkerVisibleOverride Auto
FormList Property TES4OblivionWorlds Auto
FormList Property TES4OblivionInteriorCells Auto
FormList Property TES4ExteriorBehaviorCells Auto
FormList Property TES4ParentWorldChildren Auto
FormList Property TES4ParentWorldTargets Auto
FormList Property TES4FactionEvil Auto
FormList Property TES4FactionEvilChanged Auto
FormList Property TES4FactionEvilOverride Auto
FormList Property TES4ActorRespawns Auto
FormList Property TES4ActorRespawnsChanged Auto
FormList Property TES4ActorRespawnsOverride Auto
FormList Property TES4PCLevelOffset Auto
FormList Property TES4PCLevelOffsetChanged Auto
FormList Property TES4PCLevelOffsetOverride Auto
FormList Property TES4ActorLowLevelProcessing Auto
FormList Property TES4ActorLowLevelProcessingChanged Auto
FormList Property TES4ActorLowLevelProcessingOverride Auto
FormList Property TES4ActorNoPersuasion Auto
FormList Property TES4ActorNoPersuasionChanged Auto
FormList Property TES4ActorNoPersuasionOverride Auto
FormList Property TES4ContainerRespawns Auto
FormList Property TES4ContainerRespawnsChanged Auto
FormList Property TES4ContainerRespawnsOverride Auto
FormList Property TES4OblivionGates Auto
FormList Property TES4OblivionGatesChanged Auto
FormList Property TES4OblivionGatesOverride Auto
FormList Property TES4IgnoresResistance Auto
FormList Property TES4IgnoresResistanceChanged Auto
FormList Property TES4IgnoresResistanceOverride Auto
FormList Property TES4MagicItemAutoCalc Auto
FormList Property TES4MagicItemAutoCalcChanged Auto
FormList Property TES4MagicItemAutoCalcOverride Auto
FormList Property TES4EnchantmentCostKeys Auto
FormList Property TES4EnchantmentCostValues Auto
FormList Property TES4ApparatusTypeKeys Auto
FormList Property TES4ApparatusTypeValues Auto
FormList Property TES4ActorBaseLevelKeys Auto
FormList Property TES4ActorBaseLevelValues Auto
FormList Property TES4ActorMinLevelKeys Auto
FormList Property TES4ActorMinLevelValues Auto
FormList Property TES4ActorMaxLevelKeys Auto
FormList Property TES4ActorMaxLevelValues Auto
FormList Property TES4ActorSoulLevelKeys Auto
FormList Property TES4ActorSoulLevelValues Auto
FormList Property TES4ActorServicesKeys Auto
FormList Property TES4ActorServicesValues Auto
FormList Property TES4ActorTrainerSkillKeys Auto
FormList Property TES4ActorTrainerSkillValues Auto
FormList Property TES4ActorTrainerLevelKeys Auto
FormList Property TES4ActorTrainerLevelValues Auto
FormList Property TES4CreatureTypeKeys Auto
FormList Property TES4CreatureTypeValues Auto
FormList Property TES4CreatureCombatSkillKeys Auto
FormList Property TES4CreatureCombatSkillValues Auto
FormList Property TES4CreatureMagicSkillKeys Auto
FormList Property TES4CreatureMagicSkillValues Auto
FormList Property TES4CreatureStealthSkillKeys Auto
FormList Property TES4CreatureStealthSkillValues Auto
FormList Property TES4CreatureBaseScaleKeys Auto
FormList Property TES4CreatureBaseScaleValues Auto
FormList Property TES4RaceMaleScaleKeys Auto
FormList Property TES4RaceMaleScaleValues Auto
FormList Property TES4RaceFemaleScaleKeys Auto
FormList Property TES4RaceFemaleScaleValues Auto
Quest Property TES4ActiveQuest Auto

String TES4ActorBaseLevelOverrides = ""
String TES4ActorMinLevelOverrides = ""
String TES4ActorMaxLevelOverrides = ""
String TES4ActorServicesOverrides = ""
String TES4ActorTrainerSkillOverrides = ""
String TES4ActorTrainerLevelOverrides = ""
String TES4CreatureTypeOverrides = ""
String TES4CreatureCombatSkillOverrides = ""
String TES4CreatureMagicSkillOverrides = ""
String TES4CreatureStealthSkillOverrides = ""
String TES4EnchantmentCostOverrides = ""
String TES4ForceRunOverrides = ""
String TES4ForceSneakOverrides = ""
String TES4DeathTimes = ""

Int Function GetSpellType(Form akSpell)
  If akSpell == None
    Return 0
  EndIf
  If TES4SpellTypeChanged.HasForm(akSpell)
    If TES4SpellTypeOverride1.HasForm(akSpell)
      Return 1
    ElseIf TES4SpellTypeOverride2.HasForm(akSpell)
      Return 2
    ElseIf TES4SpellTypeOverride3.HasForm(akSpell)
      Return 3
    ElseIf TES4SpellTypeOverride4.HasForm(akSpell)
      Return 4
    ElseIf TES4SpellTypeOverride5.HasForm(akSpell)
      Return 5
    EndIf
    Return 0
  EndIf
  If TES4SpellType1.HasForm(akSpell)
    Return 1
  ElseIf TES4SpellType2.HasForm(akSpell)
    Return 2
  ElseIf TES4SpellType3.HasForm(akSpell)
    Return 3
  ElseIf TES4SpellType4.HasForm(akSpell)
    Return 4
  ElseIf TES4SpellType5.HasForm(akSpell)
    Return 5
  EndIf
  Return 0
EndFunction

Function SetSpellType(Form akSpell, Int aiType)
  If akSpell == None
    Return
  EndIf
  TES4SpellTypeChanged.AddForm(akSpell)
  TES4SpellTypeOverride0.RemoveAddedForm(akSpell)
  TES4SpellTypeOverride1.RemoveAddedForm(akSpell)
  TES4SpellTypeOverride2.RemoveAddedForm(akSpell)
  TES4SpellTypeOverride3.RemoveAddedForm(akSpell)
  TES4SpellTypeOverride4.RemoveAddedForm(akSpell)
  TES4SpellTypeOverride5.RemoveAddedForm(akSpell)
  If aiType == 1
    TES4SpellTypeOverride1.AddForm(akSpell)
  ElseIf aiType == 2
    TES4SpellTypeOverride2.AddForm(akSpell)
  ElseIf aiType == 3
    TES4SpellTypeOverride3.AddForm(akSpell)
  ElseIf aiType == 4
    TES4SpellTypeOverride4.AddForm(akSpell)
  ElseIf aiType == 5
    TES4SpellTypeOverride5.AddForm(akSpell)
  Else
    TES4SpellTypeOverride0.AddForm(akSpell)
  EndIf
EndFunction

Int Function GetMapMarkerType(Form akMarker)
  If akMarker == None
    Return 0
  EndIf
  If TES4MapMarkerTypeChanged.HasForm(akMarker)
    If TES4MapMarkerTypeOverride1.HasForm(akMarker)
      Return 1
    ElseIf TES4MapMarkerTypeOverride2.HasForm(akMarker)
      Return 2
    ElseIf TES4MapMarkerTypeOverride3.HasForm(akMarker)
      Return 3
    ElseIf TES4MapMarkerTypeOverride4.HasForm(akMarker)
      Return 4
    ElseIf TES4MapMarkerTypeOverride5.HasForm(akMarker)
      Return 5
    ElseIf TES4MapMarkerTypeOverride6.HasForm(akMarker)
      Return 6
    ElseIf TES4MapMarkerTypeOverride7.HasForm(akMarker)
      Return 7
    ElseIf TES4MapMarkerTypeOverride8.HasForm(akMarker)
      Return 8
    ElseIf TES4MapMarkerTypeOverride9.HasForm(akMarker)
      Return 9
    ElseIf TES4MapMarkerTypeOverride10.HasForm(akMarker)
      Return 10
    ElseIf TES4MapMarkerTypeOverride11.HasForm(akMarker)
      Return 11
    EndIf
    Return 0
  EndIf
  If TES4MapMarkerType1.HasForm(akMarker)
    Return 1
  ElseIf TES4MapMarkerType2.HasForm(akMarker)
    Return 2
  ElseIf TES4MapMarkerType3.HasForm(akMarker)
    Return 3
  ElseIf TES4MapMarkerType4.HasForm(akMarker)
    Return 4
  ElseIf TES4MapMarkerType5.HasForm(akMarker)
    Return 5
  ElseIf TES4MapMarkerType6.HasForm(akMarker)
    Return 6
  ElseIf TES4MapMarkerType7.HasForm(akMarker)
    Return 7
  ElseIf TES4MapMarkerType8.HasForm(akMarker)
    Return 8
  ElseIf TES4MapMarkerType9.HasForm(akMarker)
    Return 9
  ElseIf TES4MapMarkerType10.HasForm(akMarker)
    Return 10
  ElseIf TES4MapMarkerType11.HasForm(akMarker)
    Return 11
  EndIf
  Return 0
EndFunction

Function SetMapMarkerType(Form akMarker, Int aiType)
  If akMarker == None
    Return
  EndIf
  TES4MapMarkerTypeChanged.AddForm(akMarker)
  TES4MapMarkerTypeOverride0.RemoveAddedForm(akMarker)
  TES4MapMarkerTypeOverride1.RemoveAddedForm(akMarker)
  TES4MapMarkerTypeOverride2.RemoveAddedForm(akMarker)
  TES4MapMarkerTypeOverride3.RemoveAddedForm(akMarker)
  TES4MapMarkerTypeOverride4.RemoveAddedForm(akMarker)
  TES4MapMarkerTypeOverride5.RemoveAddedForm(akMarker)
  TES4MapMarkerTypeOverride6.RemoveAddedForm(akMarker)
  TES4MapMarkerTypeOverride7.RemoveAddedForm(akMarker)
  TES4MapMarkerTypeOverride8.RemoveAddedForm(akMarker)
  TES4MapMarkerTypeOverride9.RemoveAddedForm(akMarker)
  TES4MapMarkerTypeOverride10.RemoveAddedForm(akMarker)
  TES4MapMarkerTypeOverride11.RemoveAddedForm(akMarker)
  If aiType == 1
    TES4MapMarkerTypeOverride1.AddForm(akMarker)
  ElseIf aiType == 2
    TES4MapMarkerTypeOverride2.AddForm(akMarker)
  ElseIf aiType == 3
    TES4MapMarkerTypeOverride3.AddForm(akMarker)
  ElseIf aiType == 4
    TES4MapMarkerTypeOverride4.AddForm(akMarker)
  ElseIf aiType == 5
    TES4MapMarkerTypeOverride5.AddForm(akMarker)
  ElseIf aiType == 6
    TES4MapMarkerTypeOverride6.AddForm(akMarker)
  ElseIf aiType == 7
    TES4MapMarkerTypeOverride7.AddForm(akMarker)
  ElseIf aiType == 8
    TES4MapMarkerTypeOverride8.AddForm(akMarker)
  ElseIf aiType == 9
    TES4MapMarkerTypeOverride9.AddForm(akMarker)
  ElseIf aiType == 10
    TES4MapMarkerTypeOverride10.AddForm(akMarker)
  ElseIf aiType == 11
    TES4MapMarkerTypeOverride11.AddForm(akMarker)
  Else
    TES4MapMarkerTypeOverride0.AddForm(akMarker)
  EndIf
EndFunction

Bool Function GetMapMarkerVisible(ObjectReference akMarker)
  If akMarker == None
    Return False
  EndIf
  If TES4MapMarkerVisibilityChanged.HasForm(akMarker)
    Return TES4MapMarkerVisibleOverride.HasForm(akMarker)
  EndIf
  Return akMarker.IsMapMarkerVisible()
EndFunction

Function SetMapMarkerVisible(ObjectReference akMarker, Bool abVisible)
  If akMarker == None
    Return
  EndIf
  TES4MapMarkerVisibilityChanged.AddForm(akMarker)
  TES4MapMarkerVisibleOverride.RemoveAddedForm(akMarker)
  If abVisible
    TES4MapMarkerVisibleOverride.AddForm(akMarker)
    akMarker.AddToMap(akMarker.CanFastTravelToMarker())
  EndIf
EndFunction

String Function GetMapMarkers(Int aiIncludeHidden = 1, Int aiType = 0)
  String result = ""
  WorldSpace currentWorld = Game.GetPlayer().GetWorldSpace()
  Int i = 0
  While i < TES4MapMarkers.GetSize()
    ObjectReference marker = TES4MapMarkers.GetAt(i) as ObjectReference
    If marker != None && marker.GetWorldSpace() == currentWorld
      Bool typeMatches = aiType == 0 || GetMapMarkerType(marker) == aiType
      Bool visible = GetMapMarkerVisible(marker)
      If typeMatches && (aiIncludeHidden == 2 || (!marker.IsDisabled() && visible))
        result = TES4Array.SetForm(result, TES4Array.IntKey(TES4Array.Size(result)), marker)
      EndIf
    EndIf
    i += 1
  EndWhile
  Return result
EndFunction

Bool Function IsInOblivion(ObjectReference akReference)
  If akReference == None
    Return False
  EndIf
  Cell parentCell = akReference.GetParentCell()
  If parentCell != None && TES4OblivionInteriorCells.HasForm(parentCell)
    Return True
  EndIf
  WorldSpace parentWorld = akReference.GetWorldSpace()
  Return parentWorld != None && TES4OblivionWorlds.HasForm(parentWorld)
EndFunction

Bool Function CellBehavesAsExterior(Form akCellOrReference)
  Cell targetCell = akCellOrReference as Cell
  ObjectReference placed = akCellOrReference as ObjectReference
  If targetCell == None && placed != None
    targetCell = placed.GetParentCell()
  EndIf
  Return targetCell != None && TES4ExteriorBehaviorCells.HasForm(targetCell)
EndFunction

WorldSpace Function GetParentWorldSpace(Form akWorld)
  WorldSpace targetWorld = akWorld as WorldSpace
  If targetWorld == None
    Return None
  EndIf
  Int index = TES4ParentWorldChildren.Find(targetWorld)
  If index < 0 || index >= TES4ParentWorldTargets.GetSize()
    Return None
  EndIf
  Return TES4ParentWorldTargets.GetAt(index) as WorldSpace
EndFunction

Form Function BaseForm(Form akForm)
  ObjectReference placed = akForm as ObjectReference
  If placed != None
    Return placed.GetBaseObject()
  EndIf
  Return akForm
EndFunction

Float Function LookupNumber(FormList akKeys, FormList akValues, Form akForm,
                            Float afDefault = 0.0)
  Form base = BaseForm(akForm)
  If base == None
    Return afDefault
  EndIf
  Int index = akKeys.Find(base)
  If index < 0 || index >= akValues.GetSize()
    Return afDefault
  EndIf
  GlobalVariable value = akValues.GetAt(index) as GlobalVariable
  If value == None
    Return afDefault
  EndIf
  Return value.GetValue()
EndFunction

String Function FormKey(Form akForm)
  Form base = BaseForm(akForm)
  If base == None
    Return TES4Array.IntKey(0)
  EndIf
  Return TES4Array.IntKey(base.GetFormID())
EndFunction

String Function ReferenceKey(ObjectReference akReference)
  If akReference == None
    Return TES4Array.IntKey(0)
  EndIf
  Return TES4Array.IntKey(akReference.GetFormID())
EndFunction

Bool Function GetForceRun(Actor akActor)
  If akActor == None
    Return False
  EndIf
  String key = ReferenceKey(akActor)
  If TES4Array.HasKey(TES4ForceRunOverrides, key)
    Return TES4Array.GetInt(TES4ForceRunOverrides, key) != 0
  EndIf
  Return akActor.IsRunning()
EndFunction

Function SetForceRun(Actor akActor, Bool abForce)
  If akActor == None
    Return
  EndIf
  TES4ForceRunOverrides = TES4Array.SetInt(
    TES4ForceRunOverrides, ReferenceKey(akActor), abForce as Int)
  ; Papyrus exposes no force-run flag.  Preserve the established speed
  ; approximation while keeping the readable OBSE flag reference-specific.
  If abForce
    akActor.SetActorValue("SpeedMult", 150.0)
  Else
    akActor.SetActorValue("SpeedMult", 100.0)
  EndIf
EndFunction

Bool Function GetForceSneak(Actor akActor)
  If akActor == None
    Return False
  EndIf
  String key = ReferenceKey(akActor)
  If TES4Array.HasKey(TES4ForceSneakOverrides, key)
    Return TES4Array.GetInt(TES4ForceSneakOverrides, key) != 0
  EndIf
  Return akActor.IsSneaking()
EndFunction

Function SetForceSneak(Actor akActor, Bool abForce)
  If akActor == None
    Return
  EndIf
  TES4ForceSneakOverrides = TES4Array.SetInt(
    TES4ForceSneakOverrides, ReferenceKey(akActor), abForce as Int)
  If abForce
    akActor.StartSneaking()
  Else
    akActor.EvaluatePackage()
  EndIf
EndFunction

Float Function GetTimeDead(Actor akActor)
  If akActor == None
    Return 0.0
  EndIf
  String key = ReferenceKey(akActor)
  If !akActor.IsDead()
    TES4DeathTimes = TES4Array.Erase(TES4DeathTimes, key)
    Return 0.0
  EndIf
  Float now = Utility.GetCurrentGameTime()
  If !TES4Array.HasKey(TES4DeathTimes, key)
    ; Skyrim exposes OnDeath but not the engine's stored time-of-death field.
    ; Record the first observation; subsequent reads retain OBSE's hour unit.
    TES4DeathTimes = TES4Array.SetFloat(TES4DeathTimes, key, now)
    Return 0.0
  EndIf
  Return (now - TES4Array.GetFloat(TES4DeathTimes, key)) * 24.0
EndFunction

Bool Function MutableFlag(Form akForm, FormList akAuthored,
                          FormList akChanged, FormList akOverride)
  Form base = BaseForm(akForm)
  If base == None
    Return False
  EndIf
  If akChanged.HasForm(base)
    Return akOverride.HasForm(base)
  EndIf
  Return akAuthored.HasForm(base)
EndFunction

Function SetMutableFlag(Form akForm, Bool abValue, FormList akChanged,
                        FormList akOverride)
  Form base = BaseForm(akForm)
  If base == None
    Return
  EndIf
  akChanged.AddForm(base)
  akOverride.RemoveAddedForm(base)
  If abValue
    akOverride.AddForm(base)
  EndIf
EndFunction

Quest Function GetActiveQuest()
  Return TES4ActiveQuest
EndFunction

Function SetActiveQuest(Quest akQuest)
  If TES4ActiveQuest != None && TES4ActiveQuest != akQuest
    TES4ActiveQuest.SetActive(False)
  EndIf
  TES4ActiveQuest = akQuest
  If TES4ActiveQuest != None
    TES4ActiveQuest.SetActive(True)
  EndIf
EndFunction

Bool Function IsFactionEvil(Form akFaction)
  Return MutableFlag(akFaction, TES4FactionEvil, TES4FactionEvilChanged,
                     TES4FactionEvilOverride)
EndFunction

Function SetFactionEvil(Form akFaction, Bool abEvil)
  SetMutableFlag(akFaction, abEvil, TES4FactionEvilChanged,
                 TES4FactionEvilOverride)
EndFunction

Bool Function IsActorRespawning(Form akActor)
  Return MutableFlag(akActor, TES4ActorRespawns, TES4ActorRespawnsChanged,
                     TES4ActorRespawnsOverride)
EndFunction

Function SetActorRespawns(Form akActor, Bool abRespawns)
  SetMutableFlag(akActor, abRespawns, TES4ActorRespawnsChanged,
                 TES4ActorRespawnsOverride)
EndFunction

Bool Function IsPCLevelOffset(Form akActor)
  Return MutableFlag(akActor, TES4PCLevelOffset, TES4PCLevelOffsetChanged,
                     TES4PCLevelOffsetOverride)
EndFunction

Function SetPCLevelOffset(Form akActor, Bool abOffset, Int aiMin = -1,
                          Int aiMax = -1)
  SetMutableFlag(akActor, abOffset, TES4PCLevelOffsetChanged,
                 TES4PCLevelOffsetOverride)
  String key = FormKey(akActor)
  If aiMin >= 0
    TES4ActorMinLevelOverrides = TES4Array.SetInt(
      TES4ActorMinLevelOverrides, key, aiMin)
  EndIf
  If aiMax >= 0
    TES4ActorMaxLevelOverrides = TES4Array.SetInt(
      TES4ActorMaxLevelOverrides, key, aiMax)
  EndIf
EndFunction

Bool Function HasLowLevelProcessing(Form akActor)
  Return MutableFlag(akActor, TES4ActorLowLevelProcessing,
                     TES4ActorLowLevelProcessingChanged,
                     TES4ActorLowLevelProcessingOverride)
EndFunction

Function SetLowLevelProcessing(Form akActor, Bool abEnabled)
  SetMutableFlag(akActor, abEnabled, TES4ActorLowLevelProcessingChanged,
                 TES4ActorLowLevelProcessingOverride)
EndFunction

Bool Function HasNoPersuasion(Form akActor)
  Return MutableFlag(akActor, TES4ActorNoPersuasion,
                     TES4ActorNoPersuasionChanged,
                     TES4ActorNoPersuasionOverride)
EndFunction

Function SetNoPersuasion(Form akActor, Bool abDisabled)
  SetMutableFlag(akActor, abDisabled, TES4ActorNoPersuasionChanged,
                 TES4ActorNoPersuasionOverride)
EndFunction

Bool Function GetContainerRespawns(Form akContainer)
  Return MutableFlag(akContainer, TES4ContainerRespawns,
                     TES4ContainerRespawnsChanged,
                     TES4ContainerRespawnsOverride)
EndFunction

Function SetContainerRespawns(Form akContainer, Bool abRespawns)
  SetMutableFlag(akContainer, abRespawns, TES4ContainerRespawnsChanged,
                 TES4ContainerRespawnsOverride)
EndFunction

Bool Function IsOblivionGate(Form akDoor)
  Return MutableFlag(akDoor, TES4OblivionGates, TES4OblivionGatesChanged,
                     TES4OblivionGatesOverride)
EndFunction

Bool Function GetIgnoresResistance(Form akItem)
  Return MutableFlag(akItem, TES4IgnoresResistance,
                     TES4IgnoresResistanceChanged,
                     TES4IgnoresResistanceOverride)
EndFunction

Function SetIgnoresResistance(Form akItem, Bool abIgnores)
  SetMutableFlag(akItem, abIgnores, TES4IgnoresResistanceChanged,
                 TES4IgnoresResistanceOverride)
EndFunction

Bool Function IsMagicItemAutoCalc(Form akItem)
  Return MutableFlag(akItem, TES4MagicItemAutoCalc,
                     TES4MagicItemAutoCalcChanged,
                     TES4MagicItemAutoCalcOverride)
EndFunction

Function SetMagicItemAutoCalc(Form akItem, Bool abAutoCalc)
  SetMutableFlag(akItem, abAutoCalc, TES4MagicItemAutoCalcChanged,
                 TES4MagicItemAutoCalcOverride)
EndFunction

Int Function GetEnchantmentCost(Form akEnchantment)
  String key = FormKey(akEnchantment)
  If TES4Array.HasKey(TES4EnchantmentCostOverrides, key)
    Return TES4Array.GetInt(TES4EnchantmentCostOverrides, key)
  EndIf
  Return LookupNumber(TES4EnchantmentCostKeys,
                      TES4EnchantmentCostValues,
                      akEnchantment) as Int
EndFunction

Function SetEnchantmentCost(Form akEnchantment, Int aiCost)
  TES4EnchantmentCostOverrides = TES4Array.SetInt(
    TES4EnchantmentCostOverrides, FormKey(akEnchantment), aiCost)
EndFunction

Int Function GetApparatusType(Form akApparatus)
  Return LookupNumber(TES4ApparatusTypeKeys, TES4ApparatusTypeValues,
                      akApparatus) as Int
EndFunction

Function SetIsOblivionGate(Form akDoor, Bool abGate)
  SetMutableFlag(akDoor, abGate, TES4OblivionGatesChanged,
                 TES4OblivionGatesOverride)
EndFunction

Int Function GetActorBaseLevel(Form akActor)
  String key = FormKey(akActor)
  If TES4Array.HasKey(TES4ActorBaseLevelOverrides, key)
    Return TES4Array.GetInt(TES4ActorBaseLevelOverrides, key)
  EndIf
  Return LookupNumber(TES4ActorBaseLevelKeys, TES4ActorBaseLevelValues,
                      akActor) as Int
EndFunction

Int Function GetActorMinLevel(Form akActor)
  String key = FormKey(akActor)
  If TES4Array.HasKey(TES4ActorMinLevelOverrides, key)
    Return TES4Array.GetInt(TES4ActorMinLevelOverrides, key)
  EndIf
  Return LookupNumber(TES4ActorMinLevelKeys, TES4ActorMinLevelValues,
                      akActor) as Int
EndFunction

Int Function GetActorMaxLevel(Form akActor)
  String key = FormKey(akActor)
  If TES4Array.HasKey(TES4ActorMaxLevelOverrides, key)
    Return TES4Array.GetInt(TES4ActorMaxLevelOverrides, key)
  EndIf
  Return LookupNumber(TES4ActorMaxLevelKeys, TES4ActorMaxLevelValues,
                      akActor) as Int
EndFunction

Int Function GetActorSoulLevel(Form akActor)
  Return LookupNumber(TES4ActorSoulLevelKeys, TES4ActorSoulLevelValues,
                      akActor) as Int
EndFunction

Int Function GetServicesMask(Form akActor)
  String key = FormKey(akActor)
  If TES4Array.HasKey(TES4ActorServicesOverrides, key)
    Return TES4Array.GetInt(TES4ActorServicesOverrides, key)
  EndIf
  Return LookupNumber(TES4ActorServicesKeys, TES4ActorServicesValues,
                      akActor) as Int
EndFunction

Function SetServicesMask(Form akActor, Int aiMask)
  TES4ActorServicesOverrides = TES4Array.SetInt(
    TES4ActorServicesOverrides, FormKey(akActor), aiMask)
EndFunction

Bool Function OffersService(Form akActor, Int aiBit)
  Return Math.LogicalAnd(GetServicesMask(akActor), Math.LeftShift(1, aiBit)) != 0
EndFunction

Function SetOffersService(Form akActor, Int aiBit, Bool abOffers)
  Int mask = GetServicesMask(akActor)
  Int flag = Math.LeftShift(1, aiBit)
  If abOffers
    mask = Math.LogicalOr(mask, flag)
  Else
    mask = Math.LogicalAnd(mask, Math.LogicalNot(flag))
  EndIf
  SetServicesMask(akActor, mask)
EndFunction

Int Function GetTrainerSkill(Form akActor)
  String key = FormKey(akActor)
  If TES4Array.HasKey(TES4ActorTrainerSkillOverrides, key)
    Return TES4Array.GetInt(TES4ActorTrainerSkillOverrides, key)
  EndIf
  Return LookupNumber(TES4ActorTrainerSkillKeys, TES4ActorTrainerSkillValues,
                      akActor) as Int
EndFunction

Function SetTrainerSkill(Form akActor, Int aiSkill)
  TES4ActorTrainerSkillOverrides = TES4Array.SetInt(
    TES4ActorTrainerSkillOverrides, FormKey(akActor), aiSkill)
EndFunction

Int Function GetTrainerLevel(Form akActor)
  String key = FormKey(akActor)
  If TES4Array.HasKey(TES4ActorTrainerLevelOverrides, key)
    Return TES4Array.GetInt(TES4ActorTrainerLevelOverrides, key)
  EndIf
  Return LookupNumber(TES4ActorTrainerLevelKeys, TES4ActorTrainerLevelValues,
                      akActor) as Int
EndFunction

Function SetTrainerLevel(Form akActor, Int aiLevel)
  TES4ActorTrainerLevelOverrides = TES4Array.SetInt(
    TES4ActorTrainerLevelOverrides, FormKey(akActor), aiLevel)
EndFunction

Int Function GetCreatureType(Form akActor)
  String key = FormKey(akActor)
  If TES4Array.HasKey(TES4CreatureTypeOverrides, key)
    Return TES4Array.GetInt(TES4CreatureTypeOverrides, key)
  EndIf
  Return LookupNumber(TES4CreatureTypeKeys, TES4CreatureTypeValues,
                      akActor, -1.0) as Int
EndFunction

Function SetCreatureType(Form akActor, Int aiType)
  TES4CreatureTypeOverrides = TES4Array.SetInt(
    TES4CreatureTypeOverrides, FormKey(akActor), aiType)
EndFunction

Int Function GetCreatureSkill(Form akActor, String asSkill)
  String values = TES4CreatureCombatSkillOverrides
  FormList keys = TES4CreatureCombatSkillKeys
  FormList forms = TES4CreatureCombatSkillValues
  If asSkill == "Magic"
    values = TES4CreatureMagicSkillOverrides
    keys = TES4CreatureMagicSkillKeys
    forms = TES4CreatureMagicSkillValues
  ElseIf asSkill == "Stealth"
    values = TES4CreatureStealthSkillOverrides
    keys = TES4CreatureStealthSkillKeys
    forms = TES4CreatureStealthSkillValues
  EndIf
  String key = FormKey(akActor)
  If TES4Array.HasKey(values, key)
    Return TES4Array.GetInt(values, key)
  EndIf
  Return LookupNumber(keys, forms, akActor) as Int
EndFunction

Function SetCreatureSkill(Form akActor, String asSkill, Int aiValue)
  String key = FormKey(akActor)
  If asSkill == "Magic"
    TES4CreatureMagicSkillOverrides = TES4Array.SetInt(
      TES4CreatureMagicSkillOverrides, key, aiValue)
  ElseIf asSkill == "Stealth"
    TES4CreatureStealthSkillOverrides = TES4Array.SetInt(
      TES4CreatureStealthSkillOverrides, key, aiValue)
  Else
    TES4CreatureCombatSkillOverrides = TES4Array.SetInt(
      TES4CreatureCombatSkillOverrides, key, aiValue)
  EndIf
EndFunction

Float Function GetCreatureBaseScale(Form akActor)
  Return LookupNumber(TES4CreatureBaseScaleKeys, TES4CreatureBaseScaleValues,
                      akActor, 1.0)
EndFunction

Float Function GetRaceScale(Form akRace, Bool abFemale = False)
  If abFemale
    Return LookupNumber(TES4RaceFemaleScaleKeys, TES4RaceFemaleScaleValues,
                        akRace, 1.0)
  EndIf
  Return LookupNumber(TES4RaceMaleScaleKeys, TES4RaceMaleScaleValues,
                      akRace, 1.0)
EndFunction
