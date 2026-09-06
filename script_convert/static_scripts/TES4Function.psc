Scriptname TES4Function extends Quest
{Host and UI event delivery for converted OBSE user functions.}

String registrations = ""
Form lastSelection

TES4Collection Function TES4Invoke(ObjectReference TES4_Caller, TES4Collection TES4_Arguments)
  Debug.Trace("TES4Function: missing converted function implementation")
  Return None
EndFunction

Function RegisterMenuHandler(String eventName, Int menu, Int tileID = -1)
  String key = "|" + eventName + ":" + menu + ":" + tileID + "|"
  If StringUtil.Find(registrations, key) < 0
    registrations += key
  EndIf
  RegisterForMenu(TES4Menu.Name(menu))
  If menu == 1008
    RegisterForMenu("BarterMenu")
  EndIf
  RegisterForModEvent("TES4Menu_OnClick", "TES4Click")
  RegisterForModEvent("TES4Menu_OnMouseOver", "TES4MouseOver")
EndFunction

Bool Function Wants(String eventName, Int menu, Int tileID)
  Return StringUtil.Find(registrations, "|" + eventName + ":" + menu + ":-1|") >= 0 || StringUtil.Find(registrations, "|" + eventName + ":" + menu + ":" + tileID + "|") >= 0
EndFunction

Event OnMenuOpen(String menuName)
  Int menu = TES4Menu.ActiveMenu()
  If Wants("OnOpen", menu, -1)
    TES4MenuCallback(menu, "", -1)
  EndIf
  If Wants("OnMouseOver", menu, -1)
    lastSelection = None
    While UI.IsMenuOpen(menuName)
      Form selected = TES4Menu.Selection()
      If selected != lastSelection
        lastSelection = selected
        TES4MenuCallback(menu, "", -1)
      EndIf
      Utility.WaitMenuMode(0.1)
    EndWhile
  EndIf
EndEvent

Event TES4Click(String eventName, String tile, Float tileID, Form sender)
  If Wants("OnClick", 1011, tileID as Int)
    TES4MenuCallback(1011, tile, tileID as Int)
  EndIf
EndEvent

Event TES4MouseOver(String eventName, String tile, Float tileID, Form sender)
  If Wants("OnMouseOver", 1011, tileID as Int)
    TES4MenuCallback(1011, tile, tileID as Int)
  EndIf
EndEvent

Function TES4MenuCallback(Int menu, String tile, Int tileID)
EndFunction
