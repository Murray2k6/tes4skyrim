"""
Mods menu: importing a mod archive, and re-importing it with a new selection.

Split out of `gui.py` because mod import is a self-contained feature with its
own dialogs -- the confirm card, the BAIN sub-package picker and the manage
list -- and `gui.py` is at its size limit. The seam is `ModsUI`, a plain
carrier for the handful of callbacks and widgets the dialogs need from the
main window; nothing here reaches back into `gui_main`'s closures.

See: docs/commentary/asset_convert_mod_ingest.md#payload-roots
"""

import os
import queue
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from asset_convert.sources import archive as _archive
from asset_convert.sources import mod_ingest, source_registry
from output_layout import record_dir
from plugin_masters import get_masters_from_binary

#: Plugins shown before the picker gets its own scrolling viewport.
PICKER_MAX_ROWS = 8

#: Missing masters named in full before the rest are counted.
_MAX_NAMED_MASTERS = 10


# ---------------------------------------------------------------------------
#  The seam, the menu, and shared widgets
# ---------------------------------------------------------------------------

class ModsUI:
    """What the mod dialogs need from the main window.

    A carrier, not a base class: `gui_main` fills it once and passes it in,
    so these dialogs never close over the main window's local scope.
    """

    def __init__(self, root, outer, colors, export_dir, running, status_var):
        """Bind the widgets and state the dialogs cannot build themselves."""
        self.root = root
        self.outer = outer
        self.CLR = colors
        self.EXPORT_DIR = export_dir
        self.running = running
        self.status_var = status_var
        self.info = self.confirm = self.log = self.clear_log = None
        self.refresh_scopes = self.apply_scope = None
        self.apply_step_availability = self.refresh_upgrade_notice = None
        self.set_running = self.start_timer = self.stop_timer = None


def add_mods_menu(menu, ui: ModsUI) -> None:
    """Add the Mods menu: import an archive or folder, re-import, manage."""

    def _archive_cmd():
        """Pick a mod archive and start its import."""
        path = filedialog.askopenfilename(
            title="Select a mod archive",
            filetypes=[("Mod archives", "*.zip *.7z *.rar"),
                       ("All files", "*.*")])
        if path:
            begin_import(path, ui)

    def _folder_cmd():
        """Pick an extracted mod folder and start its import."""
        path = filedialog.askdirectory(title="Select an extracted mod folder")
        if path:
            begin_import(path, ui)

    menu.add_command(label="Import Mod Archive…", command=_archive_cmd)
    menu.add_command(label="Import Mod Folder…", command=_folder_cmd)
    menu.add_separator()
    menu.add_command(label="Re-import Mod…",
                     command=lambda: reimport_dialog(ui))
    menu.add_command(label="Manage Imported Mods…",
                     command=lambda: manage_mods(ui))


def _card(ui: ModsUI, title: str):
    """A modal card centred on the window, with its title and separator."""
    card = tk.Frame(ui.outer, bg=ui.CLR["panel"],
                    highlightbackground=ui.CLR["border"], highlightthickness=1)
    tk.Label(card, text=title, bg=ui.CLR["panel"], fg=ui.CLR["text"],
             font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=16,
                                                 pady=(14, 0))
    ttk.Separator(card, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=16, pady=8)
    return card


def _show(card) -> None:
    """Centre a finished card and make it modal."""
    card.place(relx=0.5, rely=0.5, anchor="center")
    card.grab_set()


def _closer(card):
    """A callable that drops the grab and destroys `card`."""
    def _close():
        """Dismiss the card."""
        card.grab_release()
        card.destroy()
    return _close


def _checkbutton(parent, ui: ModsUI, text: str, var, **kw):
    """One themed checkbutton; tk's own colors ignore the dark palette."""
    return tk.Checkbutton(parent, text=text, variable=var,
                          bg=ui.CLR["panel"], fg=ui.CLR["text"],
                          selectcolor=ui.CLR["btn"],
                          activebackground=ui.CLR["panel"],
                          activeforeground=ui.CLR["text"],
                          font=("Segoe UI", 9), anchor="w",
                          highlightthickness=0, borderwidth=0, **kw)


def _buttons(ui: ModsUI, card, close, accept_label: str, on_accept):
    """The Cancel / accept pair every card ends with."""
    btns = ttk.Frame(card, style="Panel.TFrame")
    btns.pack(anchor="e", padx=16, pady=(14, 14))
    ttk.Button(btns, text="Cancel", command=close).pack(side=tk.RIGHT,
                                                        padx=(6, 0))
    ttk.Button(btns, text=accept_label, style="Accent.TButton",
               command=on_accept).pack(side=tk.RIGHT)
    return btns


# ---------------------------------------------------------------------------
#  Re-import: change a mod's BAIN sub-package selection
# ---------------------------------------------------------------------------

def reimport_dialog(ui: ModsUI) -> None:
    """Pick an imported mod, then re-run its import with a new selection."""
    try:
        groups = source_registry.groups(ui.EXPORT_DIR)
    except Exception as exc:
        ui.info("Re-import Mod", f"Could not read the mod registry:\n\n{exc}")
        return
    if not groups:
        ui.info("Re-import Mod", "No mods imported yet.")
        return

    card = _card(ui, "Re-import Mod")
    close = _closer(card)
    tk.Label(card, text="Which mod?", bg=ui.CLR["panel"],
             fg=ui.CLR["subtext"], font=("Segoe UI", 9)).pack(anchor="w",
                                                              padx=16)
    choice = tk.StringVar(value=groups[0][1])
    by_label = {label: plugs for _gid, label, plugs in groups}
    ttk.Combobox(card, textvariable=choice, values=[g[1] for g in groups],
                 state="readonly", width=52).pack(anchor="w", padx=16,
                                                  pady=(2, 8))

    def _next():
        """Close, then open the sub-package picker for the chosen mod."""
        plugs = by_label.get(choice.get()) or []
        close()
        if plugs:
            subpackage_dialog(ui, plugs[0])

    _buttons(ui, card, close, "Next", _next)
    _show(card)


def subpackage_dialog(ui: ModsUI, plugin: str) -> None:
    """Read `plugin`'s sub-packages off the UI thread, then show the picker.

    A mod imported before sub-packages existed has none recorded, so the
    answer may cost a full archive listing -- which must not happen inline.
    See: docs/commentary/asset_convert_mod_ingest.md#payload-roots
    """
    _inspect_then(
        ui, lambda: mod_ingest.known_subpackages(plugin, ui.EXPORT_DIR),
        f"Reading {plugin}...",
        lambda options: _subpackage_card(ui, plugin, options),
        "Re-import Mod", plugin)


def _subpackage_card(ui: ModsUI, plugin: str, options) -> None:
    """Tick which BAIN sub-packages to install, then re-import.

    A simple archive offers no choice; say so rather than showing an empty
    list, because re-importing it is still a useful thing to do.
    """
    entry = source_registry.get(ui.EXPORT_DIR, plugin) or {}
    active = set(entry.get('subpackages') or options)
    label = entry.get('group_label') or plugin

    card = _card(ui, "Re-import Mod")
    close = _closer(card)
    gap = os.linesep * 2
    blurb = (f"{label}{gap}Sub-packages to install:" if options else
             f"{label}{gap}This mod has no BAIN sub-packages; re-importing "
             f"reinstalls the whole payload.")
    tk.Label(card, text=blurb, bg=ui.CLR["panel"], fg=ui.CLR["subtext"],
             font=("Segoe UI", 9), justify=tk.LEFT, anchor="w",
             wraplength=420).pack(anchor="w", padx=16)

    picks = []
    for name in options:
        var = tk.BooleanVar(value=name in active)
        picks.append((name, var))
        _checkbutton(card, ui, name, var).pack(anchor="w", padx=(28, 16))

    def _go():
        """Re-run the import with whatever is ticked."""
        chosen = [n for n, v in picks if v.get()]
        close()
        if options and not chosen:
            ui.info("Re-import Mod", "No sub-packages selected.")
            return
        run_reimport(ui, plugin, chosen or None)

    _buttons(ui, card, close, "Re-import", _go)
    _show(card)


def run_reimport(ui: ModsUI, plugin: str, subpackages) -> None:
    """Re-ingest `plugin` from its retained archive, streaming to the log."""
    ui.clear_log()
    ui.log(f"Re-importing {plugin}")
    _run_on_worker(
        ui, lambda put: mod_ingest.reingest(plugin, ui.EXPORT_DIR, log=put,
                                            force=True,
                                            subpackages=subpackages),
        "Re-import Failed")


# ---------------------------------------------------------------------------
#  Running an import off the UI thread
# ---------------------------------------------------------------------------

def _run_on_worker(ui: ModsUI, work, failure_title: str) -> None:
    """Run `work(log_put)` off the UI thread, draining its log into the pane.

    tkinter is not thread-safe, so the worker only ever puts strings on a
    queue and the UI thread drains it.
    """
    ui.set_running(True)
    ui.start_timer()
    q = queue.Queue()
    outcome = {}

    def _work():
        """The worker body; every failure is reported, never raised."""
        try:
            outcome["results"] = work(q.put)
        except Exception as exc:
            outcome["error"] = exc

    def _drain(thread):
        """Pump the queue into the log, then finish once the worker exits."""
        try:
            while True:
                ui.log(q.get_nowait())
        except queue.Empty:
            pass
        if thread.is_alive():
            ui.root.after(60, lambda: _drain(thread))
            return
        ui.set_running(False)
        ui.stop_timer()
        if "error" in outcome:
            ui.log(f"  FAILED: {outcome['error']}")
            ui.info(failure_title, str(outcome["error"]))
            return
        _after_import(ui, sorted(outcome.get("results") or {}))

    th = threading.Thread(target=_work, daemon=True)
    th.start()
    ui.root.after(60, lambda: _drain(th))


def _after_import(ui: ModsUI, names: list) -> None:
    """Report the result and point the plugin selector at what just landed.

    Source ids are prefixed (`mod:<group_id>`); passing the bare group_id
    silently fails to match and leaves the old source selected.
    """
    ui.log(f"  Imported: {', '.join(names)}")
    try:
        entry = source_registry.get(ui.EXPORT_DIR, names[0]) if names else None
        gid = entry.get("group_id") if entry else None
        ui.refresh_scopes(select=f"mod:{gid}" if gid else None)
        ui.apply_scope(select_plugin=names[0] if names else None)
    except Exception:
        ui.refresh_scopes()
        ui.apply_scope()
    ui.apply_step_availability()
    ui.refresh_upgrade_notice()


# ---------------------------------------------------------------------------
#  Manage imported mods
# ---------------------------------------------------------------------------

def manage_mods(ui: ModsUI) -> None:
    """List imported mods, with Remove and Re-import actions for each."""
    try:
        groups = source_registry.groups(ui.EXPORT_DIR)
    except Exception as exc:
        ui.info("Imported Mods", f"Could not read the mod registry:\n\n{exc}")
        return
    if not groups:
        ui.info("Imported Mods",
                "No mods imported yet.\n\n"
                "Use Mods > Import Mod Archive…, or drag an archive onto "
                "the left panel.")
        return

    card = _card(ui, "Imported Mods")
    close = _closer(card)
    body = ttk.Frame(card, style="Panel.TFrame")
    body.pack(fill=tk.BOTH, padx=16)
    for _gid, label, plugs in groups:
        _mod_row(ui, body, label, list(plugs), close)
    ttk.Button(card, text="Close", command=close).pack(anchor="e", padx=16,
                                                       pady=(10, 14))
    _show(card)


def _mod_row(ui: ModsUI, body, label: str, plugs: list, close) -> None:
    """One mod's row: its plugins, plus Re-import and Remove."""
    row = ttk.Frame(body, style="Panel.TFrame")
    row.pack(fill=tk.X, pady=3)
    tk.Label(row, text=f"{label}\n  " + "\n  ".join(plugs),
             bg=ui.CLR["panel"], fg=ui.CLR["subtext"], font=("Segoe UI", 9),
             justify=tk.LEFT, anchor="w").pack(side=tk.LEFT, fill=tk.X,
                                               expand=True)

    def _remove():
        """Delete the imported copies, leaving the original archive alone."""
        if not ui.confirm("Remove Imported Mod",
                          "Delete the imported copy of:\n\n  "
                          + "\n  ".join(plugs)
                          + "\n\nThis removes their export folders. The "
                            "original archive on disk is not touched.",
                          yes="Remove", no="Cancel"):
            return
        for name in plugs:
            try:
                mod_ingest.remove(name, ui.EXPORT_DIR)
            except Exception as exc:
                ui.log(f"  Could not remove {name}: {exc}")
        close()
        ui.refresh_scopes()
        ui.apply_scope()
        manage_mods(ui)

    def _reimport():
        """Re-import this mod, letting the user re-pick its sub-packages."""
        close()
        subpackage_dialog(ui, plugs[0])

    ttk.Button(row, text="Remove", style="Danger.TButton",
               command=_remove).pack(side=tk.RIGHT, padx=(8, 0))
    ttk.Button(row, text="Re-import", command=_reimport).pack(side=tk.RIGHT,
                                                              padx=(8, 0))


# ---------------------------------------------------------------------------
#  First import: inspect, confirm, ingest
# ---------------------------------------------------------------------------

def _inspect_then(ui: ModsUI, work, busy: str, show, fail: str, subject: str):
    """Run `work()` off the UI thread, then `show(result)` back on it.

    Every dialog that needs to know what an archive contains goes through
    here: listing a multi-GB `.7z` takes real seconds, and doing it inline
    freezes tkinter with no cursor, no status and no way to cancel. Errors
    become an info box titled `fail` rather than a traceback on a dead thread.
    """
    ui.status_var.set(busy)
    result = {}

    def _work():
        """The worker body; every failure is reported, never raised."""
        try:
            result["value"] = work()
        except Exception as exc:
            result["error"] = exc

    def _done(thread):
        """Hand the result to `show` once the worker exits."""
        if thread.is_alive():
            ui.root.after(80, lambda: _done(thread))
            return
        ui.status_var.set("Ready")
        if "error" in result:
            ui.info(fail, f"{subject}{os.linesep * 2}{result['error']}")
            return
        show(result["value"])

    th = threading.Thread(target=_work, daemon=True)
    th.start()
    ui.root.after(80, lambda: _done(th))


def begin_import(path: str, ui: ModsUI) -> None:
    """Inspect `path` on a worker thread, then show the confirm dialog.

    NOTHING is written until the user confirms.
    """
    if ui.running.is_set():
        ui.info("Busy", "A conversion is running. Wait for it to finish "
                        "before importing a mod.")
        return

    def _work():
        """Inspect the archive and pre-read its plugins' masters."""
        man = mod_ingest.inspect(path)
        return man, masters_by_plugin(man)

    _inspect_then(ui, _work, "Reading archive...",
                  lambda got: confirm_import(ui, got[0], got[1]),
                  "Cannot Import", os.path.basename(path))


def _summary_lines(manifest) -> list:
    """What the confirm card says the archive holds."""
    info = [os.path.basename(str(manifest.path)),
            mod_ingest.layout_description(manifest.payload_root),
            manifest.summary()]
    if manifest.bsas:
        info.append(f"{len(manifest.bsas)} BSA(s) will be extracted")
    if manifest.nested:
        info.append(f"{len(manifest.nested)} nested archive(s)")
    if manifest.ambiguous_data:
        info.append("NOTE: several equally-shallow Data folders; "
                    f"using {manifest.payload_root[0]}")
    return info


def _subpackage_picks(ui: ModsUI, card, manifest) -> list:
    """Checkbuttons for a complex BAIN archive's sub-packages, all ticked."""
    if not manifest.all_subpackages:
        return []
    tk.Label(card, text=f"Sub-packages ({len(manifest.all_subpackages)})",
             bg=ui.CLR["panel"], fg=ui.CLR["text"],
             font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=16,
                                                pady=(10, 2))
    picks = []
    for name in manifest.all_subpackages:
        var = tk.BooleanVar(value=True)
        picks.append((name, var))
        _checkbutton(card, ui, name, var).pack(anchor="w", padx=(28, 16))
    return picks


def _plugin_picks(ui: ModsUI, card, manifest, on_change) -> list:
    """Checkbuttons for the plugins to register, all ticked.

    Anything past `PICKER_MAX_ROWS` gets its own scrolling viewport: Better
    Cities ships 99 plugins, which packed straight into the card makes it
    taller than the screen with no way to reach the buttons.
    """
    tk.Label(card, text=f"Plugins ({len(manifest.plugins)})",
             bg=ui.CLR["panel"], fg=ui.CLR["text"],
             font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=16,
                                                pady=(10, 2))
    picks = []
    plist = (_scrolling_list(ui, card, picks)
             if len(manifest.plugins) > PICKER_MAX_ROWS else card)
    for rel in manifest.plugins:
        var = tk.BooleanVar(value=True)
        picks.append((rel, var))
        var.trace_add("write", lambda *_a: on_change())
        _checkbutton(plist, ui, os.path.basename(rel), var).pack(
            anchor="w", padx=(24 if plist is card else 4))
    return picks


def _scrolling_list(ui: ModsUI, card, picks):
    """A fixed-height scrolling viewport, with All / None bulk buttons."""
    holder = tk.Frame(card, bg=ui.CLR["panel"], height=260)
    holder.pack(fill=tk.X, padx=16)
    holder.pack_propagate(False)
    canvas = tk.Canvas(holder, bg=ui.CLR["panel"], highlightthickness=0,
                       borderwidth=0)
    bar = ttk.Scrollbar(holder, orient=tk.VERTICAL, command=canvas.yview)
    canvas.configure(yscrollcommand=bar.set)
    bar.pack(side=tk.RIGHT, fill=tk.Y)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    plist = tk.Frame(canvas, bg=ui.CLR["panel"])
    win = canvas.create_window((0, 0), window=plist, anchor="nw")

    def _sync(_e=None):
        """Keep the scroll region and inner width matched to the canvas."""
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.itemconfigure(win, width=canvas.winfo_width())

    plist.bind("<Configure>", _sync)
    canvas.bind("<Configure>", _sync)
    canvas.bind("<MouseWheel>",
                lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1,
                                              "units"))

    def _set_all(value):
        """Tick or untick every plugin at once."""
        for _rel, v in picks:
            v.set(value)

    bulk = tk.Frame(card, bg=ui.CLR["panel"])
    bulk.pack(anchor="w", padx=16, pady=(4, 0))
    ttk.Button(bulk, text="All", command=lambda: _set_all(True)).pack(
        side=tk.LEFT)
    ttk.Button(bulk, text="None", command=lambda: _set_all(False)).pack(
        side=tk.LEFT, padx=(6, 0))
    return plist


class _MissingWarning:
    """The red "convert these masters first" line, following the selection.

    A mod whose master was never converted imports "fine" and resolves every
    master-owned record to nothing, so this is the project's classic silent
    failure. Unticking the plugin that wanted a master must drop it from the
    warning, or the user is told to convert something nothing they picked
    needs.
    """

    def __init__(self, ui: ModsUI, card, anchor):
        """Build the (initially hidden) label above `anchor`."""
        self.var = tk.StringVar(value="")
        self.card = card
        self.anchor = anchor
        self.shown = False
        self.pending = None
        self.label = tk.Label(card, textvariable=self.var,
                              bg=ui.CLR["panel"], fg=ui.CLR["red"],
                              font=("Segoe UI", 9), justify=tk.LEFT,
                              anchor="w", wraplength=420)

    def refresh(self, missing) -> None:
        """Show, hide or reword the warning for `missing`.

        A plain flag, never `winfo_ismapped()`: that reads 0 until the
        geometry manager next runs, so a hide/show pair inside one callback
        left the warning permanently hidden.
        """
        if not missing:
            self.var.set("")
            if self.shown:
                self.label.pack_forget()
                self.shown = False
            return
        shown = sorted(missing)
        head = shown[:_MAX_NAMED_MASTERS]
        tail = (f"\n  …and {len(shown) - len(head)} more"
                if len(shown) > len(head) else "")
        self.var.set("Missing masters — convert these FIRST:\n  "
                     + "\n  ".join(head) + tail)
        if not self.shown:
            self.label.pack(anchor="w", padx=16, pady=(10, 0),
                            before=self.anchor)
            self.shown = True

    def queue(self, compute) -> None:
        """Coalesce refreshes to one idle-time pass.

        All/None writes every var in a loop and each write fires the trace;
        recomputing per write measured 708 ms for a single click.
        """
        if self.pending is not None:
            return

        def _run():
            """Run the deferred refresh."""
            self.pending = None
            self.refresh(compute())

        self.pending = self.card.after_idle(_run)


def _no_plugin_note(ui: ModsUI, card) -> None:
    """Say an asset-only mod has no plugins, rather than showing an empty list."""
    tk.Label(card, text="No plugin — assets only.\nExport, Import, Scripts "
                        "and Creatures will be unavailable for this mod.",
             bg=ui.CLR["panel"], fg=ui.CLR["subtext"], font=("Segoe UI", 9),
             justify=tk.LEFT, anchor="w", wraplength=420).pack(
        anchor="w", padx=16, pady=(10, 0))


def _keep_checkbox(ui: ModsUI, card, manifest, keep_var) -> None:
    """The "keep a copy of the archive" option, sized in MB."""
    try:
        size_mb = manifest.path.stat().st_size / 1024 ** 2
    except OSError:
        size_mb = 0
    _checkbutton(card, ui,
                 f"Keep a copy of the archive ({size_mb:.0f} MB) so steps "
                 f"can be re-run later", keep_var, wraplength=400,
                 justify=tk.LEFT).pack(anchor="w", padx=16, pady=(10, 0))


def confirm_import(ui: ModsUI, manifest, by_plugin=None) -> None:
    """Show what was found, let the user choose, then ingest.

    `by_plugin` is {plugin_rel: [master, ...]}, computed on the caller's
    worker thread -- see `masters_by_plugin`, far too slow to run here.
    Filtering it per selection is pure dict lookups, so the missing-master
    warning can follow the checkboxes live.
    """
    by_plugin = by_plugin or {}
    card = _card(ui, "Import Mod")
    close = _closer(card)
    tk.Label(card, text="\n".join(_summary_lines(manifest)),
             bg=ui.CLR["panel"], fg=ui.CLR["subtext"], font=("Segoe UI", 9),
             justify=tk.LEFT, anchor="w", wraplength=420).pack(anchor="w",
                                                               padx=16)
    subs = _subpackage_picks(ui, card, manifest)
    warning, picks = [None], []

    def _compute():
        """The masters still missing for whatever is ticked right now."""
        return missing_masters(ui, by_plugin,
                               [rel for rel, var in picks if var.get()])

    if manifest.plugins:
        picks = _plugin_picks(ui, card, manifest,
                              lambda: warning[0].queue(_compute))
    else:
        _no_plugin_note(ui, card)

    anchor = tk.Frame(card, bg=ui.CLR["panel"], height=0)
    anchor.pack(anchor="w")
    warning[0] = _MissingWarning(ui, card, anchor)
    warning[0].refresh(_compute())
    keep_var = tk.BooleanVar(value=True)
    if not manifest.is_folder:
        _keep_checkbox(ui, card, manifest, keep_var)

    def _go():
        """Start the ingest with the chosen plugins and sub-packages."""
        chosen = [rel for rel, var in picks if var.get()]
        picked = [n for n, v in subs if v.get()]
        keep = bool(keep_var.get())
        close()
        if manifest.plugins and not chosen:
            ui.info("Import Mod", "No plugins selected.")
        elif subs and not picked:
            ui.info("Import Mod", "No sub-packages selected.")
        else:
            run_import(ui, manifest, chosen or None, keep,
                       picked if subs else None)

    _buttons(ui, card, close, "Import", _go)
    _show(card)


def run_import(ui: ModsUI, manifest, chosen, keep_archive,
               subpackages=None) -> None:
    """Do the ingest on a worker thread, streaming progress to the log."""
    ui.clear_log()
    ui.log(f"Importing {os.path.basename(str(manifest.path))}")
    _run_on_worker(
        ui, lambda put: mod_ingest.ingest(
            manifest.path, ui.EXPORT_DIR, plugin_members=chosen,
            keep_archive=keep_archive, manifest=manifest, log=put,
            subpackages=subpackages),
        "Import Failed")


# ---------------------------------------------------------------------------
#  Master resolution
# ---------------------------------------------------------------------------

def masters_by_plugin(manifest) -> dict:
    """{plugin_rel: [master, ...]} read straight out of the archive.

    ONE `extract_all` pass, never `extract_one` per plugin: a solid .7z is a
    single compressed stream, so extracting one member costs a scan of the
    whole archive. Measured on Better Cities (1.7 GB, 99 plugins), 3.7 s per
    member = 364 s serially against 3.5 s for all 99 in one pass -- slow
    enough that this must never run on the UI thread.
    """
    if not manifest.plugins:
        return {}
    own = {Path(p).name.lower() for p in manifest.plugins}
    by_plugin = {}
    with tempfile.TemporaryDirectory(prefix="tesconv_mast_") as tmp:
        for rel, target in _staged_plugins(manifest, tmp):
            try:
                by_plugin[rel] = [m for m in get_masters_from_binary(
                    str(target)) if m.lower() not in own]
            except Exception:
                continue
    return by_plugin


def _staged_plugins(manifest, tmp) -> list:
    """(member path, file on disk) for every plugin the archive holds."""
    if manifest.is_folder:
        roots = [manifest.path / r for r in manifest.payload_root]
        return [(rel, next((b / rel for b in roots if (b / rel).is_file()),
                           manifest.path / rel))
                for rel in manifest.plugins]
    members = [f"{root}/{rel}".lstrip('/') for rel in manifest.plugins
               for root in (manifest.payload_root or [''])]
    try:
        _archive.extract_all(manifest.path, tmp, members=members)
    except Exception:
        return []
    out = []
    for rel in manifest.plugins:
        want = Path(rel).name.lower()
        hit = next((p for p in (Path(tmp) / m for m in members)
                    if p.is_file() and p.name.lower() == want), None)
        if hit is not None:
            out.append((rel, hit))
    return out


def missing_masters(ui: ModsUI, by_plugin: dict, chosen: list) -> set:
    """Masters of the SELECTED plugins that have no export records yet.

    Resolved through `record_dir`, never by joining the name onto export/: an
    imported mod's plugins live inside their mod's shared folder, so a master
    that IS converted reads as missing under the plain join and the dialog
    tells the user to convert something they already have.
    """
    missing = set()
    for rel in chosen:
        for master in by_plugin.get(rel) or ():
            if not record_dir(ui.EXPORT_DIR, master).is_dir():
                missing.add(master)
    return missing
