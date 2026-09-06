Scriptname TES4Input Hidden
{An editable OBSE prompt whose text and button remain available until closed.}

Bool Function PhysicalKey(Int key) Global
  ; OBSE IsKeyPressed3 uses current game state for wheel directions only.
  If key == 264 || key == 265
    Return Input.IsKeyPressed(key)
  EndIf
  Return TES4Runtime.IsPhysicalKeyPressed(key)
EndFunction

Int Function Open(String text, Int kind = 0, Int limit = 16384) Global
  If TES4Runtime.IsTextInputInUse() || kind < 0 || kind > 2
    Return 0
  EndIf
  UI.OpenCustomMenu("tes4menus/TES4TextInput")
  Int tries = 0
  While !UI.GetBool("CustomMenu", "_root.TES4InputReady") && tries < 100
    Utility.WaitMenuMode(0.01)
    tries += 1
  EndWhile
  If !UI.GetBool("CustomMenu", "_root.TES4InputReady")
    Return 0
  EndIf
  String[] args = new String[3]
  args[0] = text
  args[1] = kind as String
  args[2] = limit as String
  UI.InvokeStringA("CustomMenu", "_root.TES4InputSetup", args)
  While !TES4Runtime.IsTextInputInUse() && tries < 100
    Utility.WaitMenuMode(0.01)
    tries += 1
  EndWhile
  Return TES4Runtime.IsTextInputInUse() as Int
EndFunction

Function Update() Global
  UI.Invoke("CustomMenu", "_root.TES4InputUpdate")
EndFunction

Function Close() Global
  UI.Invoke("CustomMenu", "_root.TES4InputClose")
EndFunction

String Function Text(Bool plain = False) Global
  If !TES4Runtime.IsTextInputInUse()
    Return ""
  EndIf
  If plain
    Return UI.GetString("CustomMenu", "_root.TES4InputPlainText")
  EndIf
  Return UI.GetString("CustomMenu", "_root.TES4InputText")
EndFunction

Int Function Cursor() Global
  If !TES4Runtime.IsTextInputInUse()
    Return -1
  EndIf
  Return UI.GetInt("CustomMenu", "_root.TES4InputCursor")
EndFunction

Function Insert(String text) Global
  UI.InvokeString("CustomMenu", "_root.TES4InputInsert", text)
EndFunction

Function DeleteText(Int count, Bool backwards = False, Bool words = False) Global
  String[] args = new String[3]
  args[0] = count as String
  args[1] = (backwards as Int) as String
  args[2] = (words as Int) as String
  UI.InvokeStringA("CustomMenu", "_root.TES4InputDelete", args)
EndFunction

Function Move(Int count, Bool backwards = False) Global
  String[] args = new String[2]
  args[0] = count as String
  args[1] = (backwards as Int) as String
  UI.InvokeStringA("CustomMenu", "_root.TES4InputMove", args)
EndFunction
