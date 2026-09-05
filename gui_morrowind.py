"""
Settings ▸ Morrowind source: the GUI half of the Morrowind master switch.

The export stage reads the chosen set from `conversion_config.json`, so the
radio group saves on every change and nothing else has to be plumbed. The same
menu builds the compatibility patch, because that is what makes Morroblivion
mode usable: without it every conversion in that mode is refused.

See: docs/commentary/tes4_export_morrowind.md#masters
"""

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from tes4_export.export_morrowind import (MORROWIND_SOURCE_KEY,
                                          SOURCE_MORROBLIVION, SOURCE_VANILLA,
                                          morroblivion_exports)
from tes4_export.morrowind_patch import (PATCH_NAME, PATCH_SOURCES,
                                         patch_exists, source_paths)

#: Source set -> its menu label, in menu order.
_LABELS = (
    (SOURCE_VANILLA, "Vanilla  (Morrowind + Tribunal + Bloodmoon)"),
    (SOURCE_MORROBLIVION, "Morroblivion + patch"),
)


def source_default(cfg: dict) -> str:
    """The configured source set; anything unrecognised reads as vanilla."""
    value = str(cfg.get(MORROWIND_SOURCE_KEY, "")).strip().lower()
    return value if value in dict(_LABELS) else SOURCE_VANILLA


def add_source_menu(settings_menu, menu_opts: dict, cfg: dict,
                    load_config, save_config, export_dir) -> tk.StringVar:
    """Add Settings ▸ Morrowind source as a radio cascade saved on change."""
    var = tk.StringVar(value=source_default(cfg))

    def _save():
        """Persist the chosen set the moment it is picked."""
        updated = load_config()
        updated[MORROWIND_SOURCE_KEY] = var.get()
        save_config(updated)

    menu = tk.Menu(settings_menu, **menu_opts)
    for mode, label in _LABELS:
        menu.add_radiobutton(label=label, value=mode, variable=var,
                             command=_save)
    menu.add_separator()
    menu.add_command(label="Build compatibility patch...",
                     command=lambda: build_patch_dialog(settings_menu,
                                                        str(export_dir)))
    settings_menu.add_cascade(label="Morrowind source", menu=menu)
    return var


def build_patch_dialog(parent, export_dir: str) -> None:
    """Ask for the Morrowind Data folder, then build the patch in a window.

    Morroblivion has to be converted first -- the patch holds what it does NOT
    supply, so without it there is no gap to measure.
    """
    exports = morroblivion_exports(export_dir)
    if not exports:
        messagebox.showerror(
            "Build compatibility patch",
            "No converted Morroblivion plugin was found.\n\n"
            "The patch holds the objects Morroblivion does NOT convert, so "
            "Morroblivion has to be converted first.")
        return

    if patch_exists(export_dir) and not messagebox.askyesno(
            "Build compatibility patch",
            f"{PATCH_NAME} already exists.\n\nRebuild it?"):
        return

    data_dir = filedialog.askdirectory(
        title="Select your Morrowind 'Data Files' folder")
    if not data_dir:
        return
    _, missing = source_paths(data_dir, PATCH_SOURCES)
    if missing:
        messagebox.showerror(
            "Build compatibility patch",
            "That folder is not a Morrowind Data Files directory.\n\n"
            f"Looked in:\n{data_dir}\n\nMissing:\n  "
            + "\n  ".join(missing))
        return

    _run_build_window(parent, data_dir, export_dir, exports)


def _run_build_window(parent, data_dir: str, export_dir: str,
                      exports: list) -> None:
    """Run the build on a worker thread, streaming progress into a window."""
    from tes4_export.morrowind_patch_build import build_patch

    win = tk.Toplevel(parent)
    win.title("Building compatibility patch")
    win.geometry("620x300")
    text = tk.Text(win, wrap="word", state="disabled")
    text.pack(fill="both", expand=True, padx=8, pady=8)
    log = _line_writer(win, text)

    def _work():
        """Build, then report the outcome in the same window."""
        try:
            result = build_patch(data_dir, export_dir, exports, progress=log)
        except Exception as exc:
            log(f"FAILED: {exc}")
            return
        if not result["ok"]:
            log(result["error"])
            return
        log("")
        log(f"Done in {result['seconds']:.1f}s -- {result['records']} records, "
            f"{result['assets']} assets.")
        log(f"{PATCH_NAME} is now a master of every Morroblivion-mode "
            f"conversion.")

    log(f"Source: {data_dir}")
    log(f"Against: {', '.join(exports)}")
    threading.Thread(target=_work, daemon=True).start()


def _line_writer(win, text):
    """A callable appending one line to `text`, safe to call off the UI thread."""
    def _log(line=""):
        """Queue one progress line onto the UI thread."""
        win.after(0, _append, str(line))

    def _append(line: str):
        """Append one line and scroll to it; runs on the UI thread."""
        text.configure(state="normal")
        text.insert("end", line + os.linesep)
        text.see("end")
        text.configure(state="disabled")

    return _log
