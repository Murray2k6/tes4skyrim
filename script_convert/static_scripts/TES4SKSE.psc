Scriptname TES4SKSE Hidden

; OBSE uses a continuous -1..1 slider; Skyrim uses Novice..Legendary (0..5).
; Preserve the normal difficulty (Adept, 2) and both endpoints.
Float Function GetGameDifficulty() Global
  Int level = TES4Runtime.GetDifficultyLevel()
  If level <= 2
    Return (level - 2) / 2.0
  EndIf
  Return (level - 2) / 3.0
EndFunction

; Numeric slots sometimes carry a reference identity alongside 0/1 flags.
; Keep all 32 bits in an Int and handle the unset reference without a VM error.
Int Function NumericFormID(Form value) Global
  If value
    Return value.GetFormID()
  EndIf
  Return 0
EndFunction

; Normalize a base form or a placed reference to its base form before calling
; SKSE64 Form natives. Oblivion's single ref type accepted both shapes.
Form Function GetBaseForm(Form akForm) Global
  ObjectReference placed = akForm as ObjectReference
  If placed
    Return placed.GetBaseObject()
  EndIf
  Return akForm
EndFunction

Int Function SetRefEssential(ObjectReference subject, Bool essential) Global
  ActorBase actor = GetBaseForm(subject) as ActorBase
  If actor
    actor.SetEssential(essential)
  EndIf
  Return 0
EndFunction
