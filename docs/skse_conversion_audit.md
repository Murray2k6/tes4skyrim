# SKSE / OBSE Convertibility Audit — Grounded in the Original Nehrim Scripts

**Date:** 2026-07-24; implementation updated 2026-08-29
**Question:** Nehrim relies on OBSE. For a *faithful* conversion of its scripts, which OBSE (and Skyrim-removed vanilla-Oblivion) functions are **actually used**, and for each, is a faithful Skyrim conversion possible with **vanilla Papyrus**, only with **SKSE**, or **not at all**?

**Method (grep-based, reading the ORIGINAL source):**
1. **What is actually used** — extracted every function token invoked in the original Oblivion script source: `SCPT.SCTX` + `INFO.ResultScript` in `export/Nehrim.esm` (2,415 script bodies). Tool: `tools/audit/obse_convertibility_audit.py`.
2. **Is it OBSE-added?** — a token counts as OBSE only if it appears in the xOBSE command set (`DEFINE_COMMAND*` / `CommandInfo kCommandInfo_*` across `references/xOBSE-master/`; 1,567 names) or is an OBSE compiler keyword (`Let`/`eval`/`Call`/`Function`/`ForEach`/`SetFunctionValue`/`loop`). Everything else used in the scripts is vanilla Oblivion.
3. **Does SKSE provide it?** — grepped every Papyrus native SKSE registers (`NativeFunctionN(...)` across `references/skse64-master/skse64/Papyrus*.cpp`; 644 names). Name-matching is a starting point; the per-function verdict below maps OBSE *capability* → best Skyrim target (OBSE and SKSE often name the same capability differently).
4. **Does the converter already target it?** — grepped `script_convert/constants.py` + `converter.py`.

> **Scope caveat — this measures the source, not runtime correctness.** The counts are what the original scripts *invoke*. The mappings implemented on 2026-08-29 have been converter-tested and compiled with the Papyrus compiler, but have not all been runtime-verified in Skyrim.

## Implemented SKSE64 target (2026-08-29)

The script converter now targets the official SKSE64 Papyrus API where it is
the real Skyrim counterpart. `convert.py --scripts-only` builds a temporary
compile-header overlay from the installed Creation Kit headers and the official
SKSE64 declarations; only `.pex` output ships, so the mod never replaces
`Game.psc`, `Utility.psc`, `Form.psc`, or `ObjectReference.psc` at runtime.

Implemented families:

- DirectInput polling/writers (`IsKeyPressed2/3`, `TapKey`, `HoldKey`,
  `ReleaseKey`) and Oblivion control-ID translation through `Input.GetMappedKey`.
- typed INI access (`Utility.GetINI*` and the vanilla `Utility.SetINI*`) and typed
  game-setting access (`Game.Get/SetGameSetting*`).
- current crosshair reference, form names, playability, display names, and base
  form-type tests.
- `GetObjectType` dereferencing plus Skyrim→Oblivion type-code translation.
- OBSE string variables and `sv_Construct`, `sv_Destruct`, `sv_Length`,
  `sv_Compare`, `sv_Erase`, `sv_Find`, `sv_Count`, `sv_Replace`, and `sv_Insert`.
- `SetNameEx`, `AppendToName`, `CopyName`, `ModName`, and `CompareName`.
- per-instance `Get/SetCurrentHealth` through SKSE64 item-health percentage.
  xOBSE `Get/SetObjectHealth` is intentionally not mapped to that API: xOBSE
  changes the base form's durability field, which Skyrim does not have.

Two apparent SKSE mappings are deliberately not emitted. Stock SKSE64 contains
implementations of `Input.DisableKey`/`EnableKey`, but their registrations are
commented out, so a Papyrus call cannot resolve. Oblivion `get/setMenu*` paths
address Oblivion XML menus, whereas SKSE `UI.*` addresses Skyrim Scaleform
movie targets; there is no generic path translation without an authored target
for the converted SWF.

---

## Headline finding

**Only 37 distinct OBSE-added functions are used across all 2,415 Nehrim script bodies** — and OBSE's dominant use is *not* arrays or strings, it is **user-defined functions** (`Call` 771×/383 scripts, `eval` 174×, `Let` 156×, `SetFunctionValue`/`Function`/`loop`/`ForEach`). Those are language constructs the converter already reshapes into the `TES4Call` method mechanism, and **SKSE is irrelevant to them** — they are a compiler feature, not an API gap.

Of the 37, after mapping each to its capability:

| Convertibility of the OBSE function | # functions | Notes |
|---|---:|---|
| **Vanilla Skyrim Papyrus** (no SKSE needed) | ~20 | incl. the UDF keywords, math, `PushActorAway`, `IsCasting`, `IsInAir`, `HasSpell`, `GetParentCell` |
| **SKSE required** for a faithful conversion | ~9 | input (`IsKeyPressed2`/`GetControl`/`GetAltControl`), INI readers, form/name/type inspection, and crosshair lookup |
| **Neither** (no faithful target anywhere) | ~4 | heterogeneous OBSE arrays/maps, `PurgeCellBuffers`, exact per-key disabling in stock SKSE64, and generic Oblivion-menu path access |

**The functions SKSE would genuinely unlock touch a tiny footprint** — see the per-function table. The array/string "marquee" SKSE feature is used in **4 scripts total**.

**Separately**, the largest *inert* problem in Nehrim is **not OBSE at all** — it is vanilla-Oblivion commands that Skyrim's engine removed (path-based music, flames, disposition, weather, package inspection). These were never OBSE functions, so requiring SKSE does nothing for them; see the second table.

---

## The 37 OBSE-added functions actually used (with grounded verdict)

Counts are occurrences / distinct SCPT scripts. "Verdict" is the faithful-conversion target after mapping capability → Skyrim.

| OBSE function | occ | scripts | Faithful conversion | Verdict |
|---|---:|---:|---|---|
| `Call` (UDF invoke) | 771 | 383 | `TES4Call` method (converter mechanism) | **VANILLA** — already handled, no SKSE |
| `eval` | 174 | 174 | pass-through wrapper, dropped | **VANILLA** — already handled |
| `Let` | 156 | 5 | `x = x op y` rewrite | **VANILLA** — already handled |
| `loop` | 17 | 5 | `While`/`EndWhile` | **VANILLA** — already handled |
| `SetFunctionValue` | 6 | 3 | `Return X` | **VANILLA** — already handled |
| `ForEach` | 2 | 1 | `While i < arr.Length` (only if the container converts) | **VANILLA** *iff* the OBSE array does — here it iterates an `ar_*`, so effectively BLOCKED |
| `PushActorAway` | 50 | 25 | vanilla `ObjectReference.PushActorAway` | **VANILLA** — already handled |
| `SetActorsAI` | 55 | 12 | *(vanilla-Oblivion AI toggle; no Skyrim equivalent)* | **NEITHER** — see note; this is not OBSE-exclusive behavior |
| `IsCasting` | 9 | 9 | vanilla `GetAnimationVariableBool("bIsCastingRight"/"Left")` | **VANILLA** — already handled |
| `sin` / `cos` | 10 / 10 | 5 / 5 | vanilla `Math.Sin` / `Math.Cos` | **VANILLA** |
| `PurgeCellBuffers` | 6 | 3 | engine-internal memory op | **NEITHER** — no-op is correct (safe to drop) |
| `sv_destruct` (+ `sv_*`) | 3 | 2 | Papyrus `String` + SKSE `StringUtil.*` | **SKSE** — implemented for the string operations listed above |
| `GetGameLoaded` | 2 | 2 | vanilla `OnPlayerLoadGame` event pattern | **VANILLA (approx)** |
| `GetStringGameSetting` | 19 | 1 | vanilla `Game.GetGameSettingString` | **VANILLA** — implemented |
| `IsKeyPressed2` | 6 | 1 | SKSE `Input.IsKeyPressed` | **SKSE** |
| `GetAltControl` | 4 | 1 | SKSE `Input.GetMappedKey`/`GetMappedControl` | **SKSE** |
| `GetControl` | 4 | 1 | SKSE `Input.GetMappedKey` | **SKSE** |
| `ar_null` (+ `ar_construct`, `ar_*`) | 4+2 | 1 | SKSE `Utility.Create*Array`/`Resize*Array` — needs full restructuring | **SKSE (partial)** — 1 script |
| `SetNumericINISetting` | 4 | 1 | vanilla `Utility.SetINI*`; SKSE supplies the matching getters | **VANILLA writer / SKSE reader** — implemented with b/i/f typing |
| `GetParentCell` | 3 | 1 | vanilla `ObjectReference.GetParentCell` | **VANILLA** — already handled |
| `EnableKey` / `DisableKey` | 2 / 2 | 1 / 1 | implementations exist in SKSE64 source but are not registered to Papyrus | **NEITHER in stock SKSE64** — emitted inert, not as an undefined native |
| `CloseAllMenus` | 2 | 1 | vanilla `Game.ForceThirdPerson`-style? No direct; `Input.TapKey(Esc)` hack | **NEITHER (approx only)** |
| `IsPlayable2` | 2 | 1 | SKSE `Form.IsPlayable` | **SKSE** — implemented |
| `SetMenuFloatValue` / `SetMenuStringValue` | 2 / 1 | 1 / 1 | SKSE `UI.SetFloat`/`SetString` needs a Skyrim Scaleform movie and authored target path | **NEITHER generically** |
| `PrintToConsole` | 2 | 1 | vanilla `Debug.Trace` (log, not console) / `Debug.Notification` | **VANILLA (approx)** |
| `GetMenuHasTrait` | 1 | 1 | SKSE `UI.GetBool`/`GetFloat` cannot read an Oblivion XML path | **NEITHER generically** |
| `MessageBoxEX` / `MessageEX` | 2 / 1 | 1 / 1 | vanilla `Debug.MessageBox` / `Message` record; `%`-format args need manual expansion | **VANILLA (partial)** |
| `HasSpell` | 1 | 1 | vanilla `Actor.HasSpell` | **VANILLA** — already handled |
| `GetCrosshairRef` | 1 | 1 | SKSE `Game.GetCurrentCrosshairRef` | **SKSE** |
| `GetFullGoldValue` | 1 | 1 | vanilla `Form.GetGoldValue`; Oblivion's enchantment premium is unavailable | **VANILLA (partial)** |
| `GetGameRestarted` | 1 | 1 | no equivalent | **NEITHER** |
| `IsInAir` | 1 | 1 | vanilla `GetAnimationVariableBool("bInAir")` | **VANILLA** |

**Implemented SKSE-only unlocks:** DirectInput polling/mapped controls,
`GetCrosshairRef`, typed INI reads and GMST writes, form/name/type inspection,
and OBSE string operations. Exact per-key disabling, heterogeneous arrays/maps,
and Oblivion XML menu paths remain outside stock SKSE64's callable model.

---

## The real inert bulk is Skyrim-removed VANILLA commands — SKSE does nothing for these

These appear heavily in the original scripts but are **vanilla Oblivion commands, not OBSE** (verified absent from the xOBSE command set), so "require SKSE" is the wrong lever entirely. Counts are raw occurrences / scripts in the original `SCPT.SCTX`.

| Vanilla-Oblivion command | occ | scripts | Why no faithful Skyrim conversion |
|---|---:|---:|---|
| **Path-based music** (`StreamMusic` 38 + Nehrim's `emc*` plugin) | ~170 | **~143** | Skyrim music is `MusicType`-form-based; no engine (vanilla or SKSE) plays a track by file path. Needs authored `MUSC` records + a path→MusicType map. |
| **Flame toggles** (`HasFlames` 58, `AddFlames` 46, `RemoveFlames` 31) | ~135 | 8 | Skyrim lights carry no scriptable flame state. No vanilla or SKSE native. |
| **AI inspection** (`GetCurrentAIProcedure` 18, `GetCurrentAIPackage` 9, `GetIsCurrentPackage`) | ~30 | ~30 | SKSE registers **zero** package natives. `Actor.GetCurrentPackage` is vanilla but shallow. |
| **Weather** (`ForceWeather` 16, `SetWeather` 8) | ~24 | 0 | **CONVERTED (2026-08-09)**: the full WTHR/CLMT/REGN chain is live, so these now emit `Weather.ForceActive(True)` / `SetActive(True, False)` / `Weather.ReleaseOverride()` against the converted records (see [weather_climate_conversion.md](weather_climate_conversion.md)). |
| `GetPlayerHasLastRiddenHorse` | 12 | 12 | vanilla `Game.GetPlayersLastRiddenHorse()` provides the tracked reference. |
| `ModDisposition` / `GetDisposition` | ~18 | ~15 | Disposition removed from Skyrim's engine. No native anywhere. |
| `PositionCell`, `ForceFlee`, `SetForceSneak`, `SetActorsAI` | ~65 | ~15 | No vanilla or SKSE natives; approximations only. |

These ~200+ scripts are inert for engine-semantic reasons. **No amount of SKSE changes them.**

---

## Dependency decision

Converted plugins that use an emitted SKSE64 native now require SKSE64 at
runtime. This is intentional: input, crosshair, form inspection, INI reads,
runtime GMST writes, and `StringUtil` cannot be reproduced faithfully with
vanilla Papyrus. Scripts that use only vanilla mappings remain ordinary
Papyrus; there is no blanket SKSE initialization script or DLL dependency.

**Highest-leverage work to reduce inert Nehrim scripts (all non-SKSE):**
1. **Path-based music → MusicType** (~143 scripts) — author `MUSC` records and map `emc*`/`StreamMusic`. Biggest single win in the whole audit.
2. **Convert `WTHR`** (remove from `SKIP_TYPES`) — unlocks the whole weather family via vanilla `SetWeather`/`ForceWeather`.
3. Continue converting typed array sites only when source dataflow proves one
   stable element type; heterogeneous OBSE arrays/maps have no direct Papyrus
   representation.

---

## Reproduce

```bash
# The grounded per-function audit (this document's numbers):
python tools/audit/obse_convertibility_audit.py export/Nehrim.esm

# Raw usage of the Skyrim-removed vanilla commands (music/flames/weather/etc.):
python tools/script/script_command_census.py export/Nehrim.esm --grep \
    streammusic emc hasflames addflames removeflames forceweather setweather \
    moddisposition getcurrentaipackage getcurrentaiprocedure positioncell
```

`tools/audit/obse_convertibility_audit.py` builds the OBSE-name set from xOBSE source and the SKSE-native set from skse64 source at run time, so re-running picks up any reference-tree changes.
