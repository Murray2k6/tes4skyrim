Scriptname TES4Menu Hidden
{Skyrim-side implementation of converted TES4 menu operations.}

String Function Name(Int menu) Global
  If menu == 1002
    Return "InventoryMenu"
  ElseIf menu == 1022
    Return "MagicMenu"
  ElseIf menu == 1008
    If UI.IsMenuOpen("BarterMenu")
      Return "BarterMenu"
    EndIf
    Return "ContainerMenu"
  ElseIf menu == 1023
    Return "MapMenu"
  ElseIf menu == 1012
    Return "Sleep/Wait Menu"
  ElseIf menu == 1009
    Return "Dialogue Menu"
  ElseIf menu == 1004
    Return "HUD Menu"
  ElseIf menu == 1011
    Return "CustomMenu"
  ElseIf menu == 1026
    Return "Book Menu"
  EndIf
  Return ""
EndFunction

Int Function ActiveMenu() Global
  If UI.IsMenuOpen("CustomMenu")
    If TES4Runtime.IsTextInputInUse()
      If UI.GetInt("CustomMenu", "_root.TES4InputKind") == 0
        Return 1001
      EndIf
      Return 1026
    EndIf
    Return 1011
  ElseIf UI.IsMenuOpen("InventoryMenu")
    Return 1002
  ElseIf UI.IsMenuOpen("MagicMenu")
    Return 1022
  ElseIf UI.IsMenuOpen("BarterMenu") || UI.IsMenuOpen("ContainerMenu")
    Return 1008
  ElseIf UI.IsMenuOpen("MapMenu")
    Return 1023
  ElseIf UI.IsMenuOpen("Dialogue Menu")
    Return 1009
  ElseIf UI.IsMenuOpen("Sleep/Wait Menu")
    Return 1012
  ElseIf UI.IsMenuOpen("Book Menu")
    Return 1026
  EndIf
  Return 0
EndFunction

String Function Normalize(String path) Global
  String result = ""
  Int i = 0
  While i < StringUtil.GetLength(path)
    String ch = StringUtil.Substring(path, i, 1)
    If ch == "\\"
      ch = "/"
    EndIf
    result += ch
    i += 1
  EndWhile
  Return result
EndFunction

Int Function Open(String pluginName, String xmlPath) Global
  String path = Normalize(xmlPath)
  Int extension = StringUtil.Find(path, ".xml")
  If extension >= 0
    path = StringUtil.Substring(path, 0, extension)
  EndIf
  UI.OpenCustomMenu("tes4menus/" + pluginName + "/" + path)
  Int tries = 0
  While !UI.GetBool("CustomMenu", "_root.TES4Ready") && tries < 100
    Utility.WaitMenuMode(0.01)
    tries += 1
  EndWhile
  Return UI.GetBool("CustomMenu", "_root.TES4Ready") as Int
EndFunction

Function SetNumber(Int menu, String path, Float value) Global
  String[] args = new String[2]
  args[0] = Normalize(path)
  args[1] = value as String
  UI.InvokeStringA(Name(menu), "_root.TES4SetNumber", args)
EndFunction

Function SetString(Int menu, String pathAndValue) Global
  Int pipe = StringUtil.Find(pathAndValue, "|")
  If pipe < 0
    Return
  EndIf
  String[] args = new String[2]
  args[0] = Normalize(StringUtil.Substring(pathAndValue, 0, pipe))
  args[1] = StringUtil.Substring(pathAndValue, pipe + 1)
  UI.InvokeStringA(Name(menu), "_root.TES4SetString", args)
EndFunction

Float Function GetNumber(Int menu, String path) Global
  Return UI.GetFloat(Name(menu), "_root.TES4Values." + TraitPath(path))
EndFunction

String Function GetString(Int menu, String path) Global
  Return UI.GetString(Name(menu), "_root.TES4Values." + TraitPath(path))
EndFunction

Bool Function HasTrait(Int menu, String path) Global
  Return UI.GetBool(Name(menu), "_root.TES4Traits." + TraitPath(path))
EndFunction

String Function TraitPath(String path) Global
  String result = ""
  Int i = 0
  While i < StringUtil.GetLength(path)
    String ch = StringUtil.Substring(path, i, 1)
    If ch == "\\" || ch == "/"
      ch = "."
    EndIf
    result += ch
    i += 1
  EndWhile
  Return result
EndFunction

Function Click(Int menu, String path) Global
  UI.InvokeString(Name(menu), "_root.TES4Click", Normalize(path))
EndFunction

Form Function Selection() Global
  Return TES4Runtime.GetActiveMenuSelection()
EndFunction
