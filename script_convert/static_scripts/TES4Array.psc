ScriptName TES4Array Hidden
{Length-prefixed, persistent String representation of xOBSE arrays/maps.}

String Function IntKey(Int aiKey) Global
  Return "i" + (aiKey as String)
EndFunction

String Function StringKey(String asKey) Global
  Return "s" + asKey
EndFunction

Int Function EntryEnd(String asArray, Int aiStart) Global
  Int firstColon = StringUtil.Find(asArray, ":", aiStart)
  If firstColon < 0
    Return StringUtil.GetLength(asArray)
  EndIf
  Int keyLength = StringUtil.Substring(asArray, aiStart, firstColon - aiStart) as Int
  Int valueLengthStart = firstColon + keyLength + 2
  Int secondColon = StringUtil.Find(asArray, ":", valueLengthStart)
  If secondColon < 0
    Return StringUtil.GetLength(asArray)
  EndIf
  Int valueLength = StringUtil.Substring(asArray, valueLengthStart, secondColon - valueLengthStart) as Int
  Return secondColon + 1 + valueLength
EndFunction

String Function EntryKey(String asArray, Int aiStart) Global
  Int colon = StringUtil.Find(asArray, ":", aiStart)
  If colon < 0
    Return ""
  EndIf
  Int keyLength = StringUtil.Substring(asArray, aiStart, colon - aiStart) as Int
  Return StringUtil.Substring(asArray, colon + 1, keyLength)
EndFunction

String Function EntryType(String asArray, Int aiStart) Global
  Int colon = StringUtil.Find(asArray, ":", aiStart)
  If colon < 0
    Return ""
  EndIf
  Int keyLength = StringUtil.Substring(asArray, aiStart, colon - aiStart) as Int
  Return StringUtil.Substring(asArray, colon + keyLength + 1, 1)
EndFunction

String Function EntryRaw(String asArray, Int aiStart) Global
  Int firstColon = StringUtil.Find(asArray, ":", aiStart)
  If firstColon < 0
    Return ""
  EndIf
  Int keyLength = StringUtil.Substring(asArray, aiStart, firstColon - aiStart) as Int
  Int valueLengthStart = firstColon + keyLength + 2
  Int secondColon = StringUtil.Find(asArray, ":", valueLengthStart)
  If secondColon < 0
    Return ""
  EndIf
  Int valueLength = StringUtil.Substring(asArray, valueLengthStart, secondColon - valueLengthStart) as Int
  Return StringUtil.Substring(asArray, secondColon + 1, valueLength)
EndFunction

String Function Encode(String asKey, String asType, String asRaw) Global
  Return (StringUtil.GetLength(asKey) as String) + ":" + asKey + asType + (StringUtil.GetLength(asRaw) as String) + ":" + asRaw
EndFunction

String Function SetRaw(String asArray, String asKey, String asType, String asRaw) Global
  String result = ""
  Int pos = 0
  Int total = StringUtil.GetLength(asArray)
  While pos < total
    Int nextPos = EntryEnd(asArray, pos)
    If EntryKey(asArray, pos) != asKey
      result += StringUtil.Substring(asArray, pos, nextPos - pos)
    EndIf
    If nextPos <= pos
      pos = total
    Else
      pos = nextPos
    EndIf
  EndWhile
  Return result + Encode(asKey, asType, asRaw)
EndFunction

String Function GetRaw(String asArray, String asKey) Global
  Int pos = 0
  Int total = StringUtil.GetLength(asArray)
  While pos < total
    If EntryKey(asArray, pos) == asKey
      Return EntryRaw(asArray, pos)
    EndIf
    Int nextPos = EntryEnd(asArray, pos)
    If nextPos <= pos
      Return ""
    EndIf
    pos = nextPos
  EndWhile
  Return ""
EndFunction

String Function GetType(String asArray, String asKey) Global
  Int pos = 0
  Int total = StringUtil.GetLength(asArray)
  While pos < total
    If EntryKey(asArray, pos) == asKey
      Return EntryType(asArray, pos)
    EndIf
    Int nextPos = EntryEnd(asArray, pos)
    If nextPos <= pos
      Return ""
    EndIf
    pos = nextPos
  EndWhile
  Return ""
EndFunction

Int Function Size(String asArray) Global
  Int count = 0
  Int pos = 0
  Int total = StringUtil.GetLength(asArray)
  While pos < total
    Int nextPos = EntryEnd(asArray, pos)
    If nextPos <= pos
      Return count
    EndIf
    count += 1
    pos = nextPos
  EndWhile
  Return count
EndFunction

Bool Function HasKey(String asArray, String asKey) Global
  Int pos = 0
  Int total = StringUtil.GetLength(asArray)
  While pos < total
    If EntryKey(asArray, pos) == asKey
      Return True
    EndIf
    Int nextPos = EntryEnd(asArray, pos)
    If nextPos <= pos
      Return False
    EndIf
    pos = nextPos
  EndWhile
  Return False
EndFunction

String Function Erase(String asArray, String asKey) Global
  String result = ""
  Int pos = 0
  Int total = StringUtil.GetLength(asArray)
  While pos < total
    Int nextPos = EntryEnd(asArray, pos)
    If EntryKey(asArray, pos) != asKey
      result += StringUtil.Substring(asArray, pos, nextPos - pos)
    EndIf
    If nextPos <= pos
      Return result
    EndIf
    pos = nextPos
  EndWhile
  Return result
EndFunction

String Function KeyAt(String asArray, Int aiIndex) Global
  Int pos = 0
  Int current = 0
  Int total = StringUtil.GetLength(asArray)
  While pos < total
    If current == aiIndex
      Return EntryKey(asArray, pos)
    EndIf
    Int nextPos = EntryEnd(asArray, pos)
    If nextPos <= pos
      Return ""
    EndIf
    pos = nextPos
    current += 1
  EndWhile
  Return ""
EndFunction

String Function SetInt(String asArray, String asKey, Int aiValue) Global
  Return SetRaw(asArray, asKey, "i", aiValue as String)
EndFunction

String Function SetFloat(String asArray, String asKey, Float afValue) Global
  Return SetRaw(asArray, asKey, "f", afValue as String)
EndFunction

String Function SetString(String asArray, String asKey, String asValue) Global
  Return SetRaw(asArray, asKey, "s", asValue)
EndFunction

String Function SetForm(String asArray, String asKey, Form akValue) Global
  Int formID = 0
  If akValue != None
    formID = akValue.GetFormID()
  EndIf
  Return SetRaw(asArray, asKey, "r", formID as String)
EndFunction

String Function SetArray(String asArray, String asKey, String asValue) Global
  Return SetRaw(asArray, asKey, "a", asValue)
EndFunction

Int Function GetInt(String asArray, String asKey) Global
  Return GetRaw(asArray, asKey) as Int
EndFunction

Float Function GetFloat(String asArray, String asKey) Global
  Return GetRaw(asArray, asKey) as Float
EndFunction

String Function GetString(String asArray, String asKey) Global
  Return GetRaw(asArray, asKey)
EndFunction

Form Function GetForm(String asArray, String asKey) Global
  Int formID = GetRaw(asArray, asKey) as Int
  If formID == 0
    Return None
  EndIf
  Return Game.GetForm(formID)
EndFunction

String Function GetArray(String asArray, String asKey) Global
  Return GetRaw(asArray, asKey)
EndFunction

Int Function FindRaw(String asArray, String asType, String asRaw) Global
  Int pos = 0
  Int index = 0
  Int total = StringUtil.GetLength(asArray)
  While pos < total
    If EntryType(asArray, pos) == asType && EntryRaw(asArray, pos) == asRaw
      Return index
    EndIf
    Int nextPos = EntryEnd(asArray, pos)
    If nextPos <= pos
      Return -1
    EndIf
    pos = nextPos
    index += 1
  EndWhile
  Return -1
EndFunction

Int Function FindInt(String asArray, Int aiValue) Global
  Return FindRaw(asArray, "i", aiValue as String)
EndFunction

Int Function FindFloat(String asArray, Float afValue) Global
  Return FindRaw(asArray, "f", afValue as String)
EndFunction

Int Function FindString(String asArray, String asValue) Global
  Return FindRaw(asArray, "s", asValue)
EndFunction

Int Function FindForm(String asArray, Form akValue) Global
  Int formID = 0
  If akValue != None
    formID = akValue.GetFormID()
  EndIf
  Return FindRaw(asArray, "r", formID as String)
EndFunction

String Function Resize(String asArray, Int aiSize) Global
  If aiSize < 0
    aiSize = 0
  EndIf
  Int i = Size(asArray) - 1
  While i >= aiSize
    asArray = Erase(asArray, IntKey(i))
    i -= 1
  EndWhile
  i = Size(asArray)
  While i < aiSize
    asArray = SetInt(asArray, IntKey(i), 0)
    i += 1
  EndWhile
  Return asArray
EndFunction

Function Dump(String asArray) Global
  Debug.Trace("TES4Array size=" + (Size(asArray) as String) + " data=" + asArray)
EndFunction
