Scriptname TES4Collections Hidden

Int Function Size(TES4Collection collection) Global
  If collection == None
    Return -1
  EndIf
  Return collection.Size()
EndFunction

String Function ValueKey(TES4Collection collection) Global
  If collection.Size() == 2 && collection.HasKey("key") && collection.HasKey("value")
    Return "value"
  EndIf
  Return collection.KeyAt(0)
EndFunction

Int Function DereferenceInteger(TES4Collection collection) Global
  If collection == None
    Return 0
  EndIf
  Return collection.GetInteger(ValueKey(collection))
EndFunction

Float Function DereferenceNumber(TES4Collection collection) Global
  If collection == None
    Return 0.0
  EndIf
  Return collection.GetNumber(ValueKey(collection))
EndFunction

String Function DereferenceString(TES4Collection collection) Global
  If collection == None
    Return ""
  EndIf
  Return collection.GetString(ValueKey(collection))
EndFunction

Form Function DereferenceForm(TES4Collection collection) Global
  If collection == None
    Return None
  EndIf
  Return collection.GetForm(ValueKey(collection))
EndFunction

TES4Collection Function DereferenceArray(TES4Collection collection) Global
  If collection == None
    Return None
  EndIf
  Return collection.GetArray(ValueKey(collection))
EndFunction
