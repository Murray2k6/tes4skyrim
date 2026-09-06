Scriptname TES4Collection Hidden
{Native collections stored entirely in Papyrus objects for save/load and reference lifetime.}

Int Property Kind Auto
Int Property Count Auto
TES4CollectionPage Property First Auto

TES4Collection Function Create(String kind = "Array") Global Native
TES4Collection Function MapMarkers(Int visibility = 1, Int markerType = 0) Global Native
TES4Collection Function Actors(Int processLevel = 0) Global Native
TES4Collection Function Inventory(Form subject, Bool equipped = False) Global Native
TES4Collection Function Items(ObjectReference subject, TES4Collection types = None) Global Native
TES4Collection Function Spells(Form subject, Bool leveled = False) Global Native
TES4Collection Function ActiveEffects(Actor subject, Bool casters = False) Global Native
TES4Collection Function BoundingBox(Actor subject) Global Native
TES4Collection Function CombatActors(Actor subject, Bool targets = False) Global Native
Int Function Size() Native
Int Function ValueType(String key) Native
Bool Function HasKey(String key) Native
String Function KeyAt(Int index) Native
Float Function GetNumber(String key) Native
Int Function GetInteger(String key) Native
String Function GetString(String key) Native
Form Function GetForm(String key) Native
TES4Collection Function GetArray(String key) Native
Function SetNumber(String key, Float value) Native
Function SetInteger(String key, Int value) Native
Function SetString(String key, String value) Native
Function SetForm(String key, Form value) Native
Function SetArray(String key, TES4Collection value) Native
Int Function AppendNumber(Float value) Native
Int Function AppendInteger(Int value) Native
Int Function AppendString(String value) Native
Int Function AppendForm(Form value) Native
Int Function AppendArray(TES4Collection value) Native
Int Function AppendValue(TES4Collection source, String sourceKey) Native
Function ResizeNumber(Int size, Float value = 0.0) Native
Function ResizeInteger(Int size, Int value = 0) Native
Function ResizeForm(Int size, Form value = None) Native
Function ResizeString(Int size, String value = "") Native
Int Function Erase(String key) Native
Int Function Clear() Native
String Function FindNumber(Float value) Native
String Function FindInteger(Int value) Native
String Function FindString(String value) Native
String Function FindForm(Form value) Native
String Function FindArray(TES4Collection value) Native
Function CopyValue(String key, TES4Collection source, String sourceKey) Native

TES4Collection Function WithNumber(String key, Float value)
  SetNumber(key, value)
  Return Self
EndFunction

TES4Collection Function WithInteger(String key, Int value)
  SetInteger(key, value)
  Return Self
EndFunction

TES4Collection Function WithForm(String key, Form value)
  SetForm(key, value)
  Return Self
EndFunction

TES4Collection Function WithString(String key, String value)
  SetString(key, value)
  Return Self
EndFunction

TES4Collection Function WithArray(String key, TES4Collection value)
  SetArray(key, value)
  Return Self
EndFunction

TES4Collection Function WithValue(String key, TES4Collection source, String sourceKey)
  CopyValue(key, source, sourceKey)
  Return Self
EndFunction
