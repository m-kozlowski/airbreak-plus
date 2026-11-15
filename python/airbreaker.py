"""AirBreaker: a window for the Air 10 patch options, patching and flashing.

The patches, their phases, descriptions, defaults, parameters and dependencies come from the shared option
declarations (python/lib/as10_patch_options.py through patch_options.load("air10")). Presets and option files
are read, validated and written with python/lib/patch_config.py, the code the patcher and make use too.
The window edits a user preset, presets/user/air10/NAME.config, which can build on another preset such as the
built-in plus. Ticking a patch also ticks the patches it requires; unticking one unticks the patches that
require it. Options the preset sets itself are shown bold, and Save writes only those. The local options file
patch-airsense.config is edited by hand and applies under every preset, so the window shows what it sets.
Patch runs patch-airsense.py INPUT OUTPUT PATCH --preset NAME --overwrite, with its output in the log; on
Windows it runs in WSL unless arm-none-eabi-nm is on the Windows PATH, since the patcher reads the payload
ELFs with the ARM binutils. Build payloads runs make binaries (through WSL on Windows) to compile the payloads
the patcher loads from build/. Flash device does over SWD what docs/guide/flashing.md does in the OpenOCD
telnet console: each button runs OpenOCD once with tcl/airsense.cfg and one of its commands (dump,
flash_new, ...), either a Windows openocd.exe or run-ocd.sh in WSL. The paths and choices are remembered in
~/.airbreak_patch_gui.json. Needs only Python with tkinter (included in the Windows installer). Start it with
airbreaker.bat (no console) or python python/airbreaker.py.
"""
import glob
import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))   # <repo>/python
REPO = os.path.dirname(HERE)
PATCHER = os.path.join(HERE, "patch-airsense.py")
sys.path.insert(0, HERE)
from lib import patch_config, patch_options  # noqa: E402

TITLE = "AirBreaker"
PLATFORM = patch_options.load("air10")
LOCAL_FILE = patch_config.REPO / patch_config.LOCAL_FILES[PLATFORM.name]
USER_PRESETS = patch_config.REPO / patch_config.preset_dirs(PLATFORM.name)[0]   # presets/user/air10
DEFAULT_PRESET = "airbreaker"
PRESET_NAME = re.compile(r"[A-Za-z0-9_.-]+$")   # also passed to make in PATCH_ARGS, so no spaces or quotes
HEADER = "# Written by AirBreaker (python/airbreaker.py): the options this preset sets itself."
NO_BASE = "(none)"
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".airbreak_patch_gui.json")
DEFAULT_OUTPUT = os.path.join(REPO, "build", "stm32-patched.bin")
DEFAULT_BACKUP = os.path.join(REPO, "stm32.bin")   # where docs/guide/openocd.md has the stock dump
FLASH_SIZE = 0x100000   # flash_new and dump work on the whole 1 MB flash
OPENOCD_GLOBS = (   # Windows installs of OpenOCD, newest version first within each
    r"C:\Program Files*\OpenOCD*\bin\openocd.exe",
    r"C:\Program Files*\xpack-openocd*\bin\openocd.exe",
    os.path.expanduser(r"~\AppData\Roaming\xPacks\@xpack-dev-tools\openocd\*\.content\bin\openocd.exe"),
    os.path.expanduser(r"~\ModusToolbox\tools_*\openocd\bin\openocd.exe"),
    r"C:\VSCode_OnethinxPack_Windows\tools_*\openocd\bin\openocd.exe",
    r"C:\Program Files*\Cypress\*\openocd\bin\openocd.exe",
    r"C:\Program Files*\Infineon\*\openocd\bin\openocd.exe",
)
STEPS = (("choose", "1 Choose patches"), ("save", "2 Save"), ("build", "3 Build payloads"), ("patch", "4 Patch"),
         ("backup", "5 Dump backup"), ("flash", "6 Flash"))   # the checklist above the options


def parameter_items(patch):
    return [(parameter, patch) for parameter in patch.parameters]


PARAMETERS = [item for patch in PLATFORM.patches() for item in parameter_items(patch)]   # (parameter, patch)
OPTIONS = [patch.option for patch in PLATFORM.patches()] + [parameter.option for parameter, _ in PARAMETERS]


def value_text(value, syntax=None):
    """A parsed option value as the window shows it: on/off, '' for an unset parameter, 85 rather than 85.0."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "on" if value else "off"
    if syntax is not None and syntax.repeat:
        return shlex.join(patch_config.format_value(item, syntax) for item in value)
    if isinstance(value, float) and (syntax is None or syntax.format is None):
        return "%g" % value
    return patch_config.format_value(value, syntax)


def user_presets():
    return sorted(path.stem for path in USER_PRESETS.glob("*.config") if path.is_file())


def preset_path(name):
    return USER_PRESETS / (name + ".config")


def layer_label(layer):
    return LOCAL_FILE.name if layer.source == "local" else "preset " + layer.path.stem


class Tooltip:
    """Shows text from a callback after hovering a widget for a moment."""
    def __init__(self, widget, text):
        self.widget, self.text, self.tip, self.job = widget, text, None, None
        widget.bind("<Enter>", self.schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def schedule(self, _):
        self.hide()
        self.job = self.widget.after(500, self.show)

    def show(self):
        text = self.text()
        if not text:
            return
        x, y = self.widget.winfo_rootx() + 20, self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        tk.Label(self.tip, text=text, justify="left", background="#ffffe8", relief="solid", borderwidth=1,
                 padx=6, pady=4).pack()
        self.tip.update_idletasks()   # keep it on the screen
        x = min(x, self.tip.winfo_screenwidth() - self.tip.winfo_reqwidth() - 8)
        if y + self.tip.winfo_reqheight() > self.tip.winfo_screenheight() - 40:
            y = self.widget.winfo_rooty() - self.tip.winfo_reqheight() - 4
        self.tip.wm_geometry("+%d+%d" % (x, y))

    def hide(self, _=None):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.tip:
            self.tip.destroy()
            self.tip = None


def wrap_lines(text):
    return textwrap.fill(text, 90)


def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def build_command():
    """make binaries, through WSL on Windows (docs/guide/wsl_setup.md); None when make is not available."""
    if os.name == "nt":
        wsl = shutil.which("wsl.exe")
        return [wsl, "--cd", REPO, "--", "make", "binaries"] if wsl else None
    return ["make", "binaries"] if shutil.which("make") else None


WSL_TOOLS_HINT = "WSL needs openocd and usbutils: sudo apt install openocd usbutils (docs/guide/wsl_setup.md)."
LOG_HINTS = (   # output -> what to do about it, shown when the command ends
    ("run make binaries", "Click 'Build payloads' to run make binaries, then Patch again."),
    ("openocd: command not found", WSL_TOOLS_HINT),
    ("lsusb: command not found", WSL_TOOLS_HINT),
    ("Error: open failed", "OpenOCD found no adapter: check the programmer's USB cable and driver, or in WSL "
     "that usbipd shares it (docs/guide/openocd.md)."),
)


def find_openocd():
    """openocd on the PATH, else a known Windows install; empty when none is found."""
    found = shutil.which("openocd")
    if found:
        return found
    if os.name == "nt":
        for pattern in OPENOCD_GLOBS:
            hits = sorted(glob.glob(pattern), reverse=True)
            if hits:
                return os.path.normpath(hits[0])
    return ""


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def use_wsl():
    """Windows without the ARM toolchain: make and the patcher (which runs arm-none-eabi-nm, objdump and objcopy
    on the payload ELFs) run in WSL, where docs/guide/wsl_setup.md installs them."""
    return os.name == "nt" and not shutil.which("arm-none-eabi-nm") and bool(shutil.which("wsl.exe"))


def wsl_path(path):
    """The WSL path of a Windows path, or None when WSL cannot translate it."""
    path = os.path.realpath(path)   # also expands 8.3 names such as MICHIE~1, which WSL does not know
    try:
        result = subprocess.run([shutil.which("wsl.exe") or "wsl.exe", "--exec", "wslpath", "-a",
                                 path.replace("\\", "/")], capture_output=True, text=True, creationflags=NO_WINDOW)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


WSL_TOOLS = (("make", "make"), ("arm-none-eabi-gcc", "gcc-arm-none-eabi"), ("arm-none-eabi-nm", "binutils-arm-none-eabi"),
             ("python3", "python3"))   # (command, apt package) the build and the patcher need in WSL


def wsl_missing_packages():
    """apt packages of the WSL_TOOLS whose command is not in WSL; [] when all are there (or WSL cannot be asked)."""
    script = "for t in %s; do command -v $t >/dev/null || echo $t; done" % " ".join(t for t, _ in WSL_TOOLS)
    try:
        result = subprocess.run([shutil.which("wsl.exe"), "--exec", "bash", "-c", script], capture_output=True,
                                text=True, creationflags=NO_WINDOW)
    except OSError:
        return []
    missing = result.stdout.split()
    return [pkg for tool, pkg in WSL_TOOLS if tool in missing]


def patch_command(infile, outfile, preset, verbose):
    """patch-airsense.py INPUT OUTPUT PATCH --preset PRESET --overwrite: Windows Python, or python3 in WSL
    (use_wsl) with the paths translated. None when WSL cannot reach a file."""
    args = ["PATCH", "--preset", preset, "--overwrite"] + (["-v"] if verbose else [])
    if not use_wsl():
        return [python_exe(), "-u", PATCHER, infile, outfile] + args
    paths = [wsl_path(infile), wsl_path(outfile)]
    if None in paths:
        return None
    return [shutil.which("wsl.exe"), "--cd", REPO, "--exec", "python3", "-u", "python/patch-airsense.py"] + \
        paths + args


def python_exe():
    """python.exe, also when started through pythonw.exe, so the child has a console-less pipe-friendly stdout."""
    exe = sys.executable
    if os.path.basename(exe).lower() == "pythonw.exe":
        exe = os.path.join(os.path.dirname(exe), "python.exe")
    return exe


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.geometry("1280x900")
        self.settings = load_settings()
        self.enabled = {}   # patch option -> BooleanVar: patch selected
        self.params = {}    # parameter option -> StringVar with its value as typed
        self.param_widgets = {}   # parameter option -> its entry or combobox, disabled while the patch is off
        self.checks = {}    # patch option -> Checkbutton, bold when this preset sets it
        self.required_by = {patch.option: [other.option for other in PLATFORM.patches()
                                           if patch.option in other.requires] for patch in PLATFORM.patches()}
        self.name = ""          # the preset shown, presets/user/air10/NAME.config
        self.base = []          # presets this preset selects (--preset); they apply under it
        self.underlying = {}    # option -> value from the local options file and the base presets
        self.sources = {}       # option -> the file under this preset that sets it
        self.local_options = ()   # what patch-airsense.config sets, shown as a note
        self.foreign = False      # the preset file was not written by this window: ask before replacing it
        self.saved_text = None    # the preset file as last loaded or saved; None when it could not be read
        self.loading = False
        self.proc = None
        self.done = ""          # log text when the running command succeeds
        self.flashing = False   # the running command writes the device flash: ask before stopping it
        self.hints = []         # LOG_HINTS matched by the running command's output
        self.lines = queue.Queue()
        self.error = ""         # why shown() found an invalid value

        bold = tkfont.nametofont("TkDefaultFont").copy()
        bold.configure(weight="bold")
        self.bold = bold   # the style only keeps the font name
        ttk.Style(self).configure("Changed.TCheckbutton", font=bold)

        checklist = ttk.Frame(self)   # what is done, in the order to do it
        checklist.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(checklist, text="Steps:").pack(side="left", padx=(0, 10))
        self.steps = {}
        for key, text in STEPS:
            self.steps[key] = ttk.Label(checklist, text=text)
            self.steps[key].pack(side="left", padx=(0, 18))
        Tooltip(checklist, lambda: wrap_lines(
            "The steps in order. A tick means it is done: the options are saved, the payloads are built "
            "(build/), the patched firmware exists, a backup file exists, and the device was flashed from this "
            "window. Step 5 matters most: the stock dump is the only way to restore the device."))
        self.flashed = False   # the device was flashed from this window since the last patch
        self.running = ""      # title of the running command

        panes = ttk.PanedWindow(self, orient="vertical")   # top: options, bottom: patch firmware and log
        panes.pack(fill="both", expand=True, padx=8, pady=8)
        top = ttk.Frame(panes)
        bottom = ttk.Frame(panes)
        panes.add(top, weight=3)
        panes.add(bottom, weight=2)

        area = ttk.Frame(top)
        area.pack(fill="both", expand=True)
        canvas = tk.Canvas(area, highlightthickness=0)
        scroll = ttk.Scrollbar(area, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = ttk.Frame(canvas)
        window = canvas.create_window(0, 0, window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))

        def wheel(event):   # only scroll the options while the mouse is over them
            under = self.winfo_containing(event.x_root, event.y_root)
            if under is not None and str(under).startswith(str(canvas)):
                # X11 sends the wheel as buttons 4 and 5, Windows and macOS as <MouseWheel> with a delta
                up = event.num == 4 or (event.num != 5 and event.delta > 0)
                canvas.yview_scroll(-1 if up else 1, "units")
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(sequence, wheel)

        columns = [ttk.Frame(inner) for _ in range(2)]   # one LabelFrame per patch phase, in two columns
        for i, column in enumerate(columns):
            column.grid(row=1, column=i, sticky="nwe", padx=(0, 8) if i == 0 else (0, 4))
            inner.columnconfigure(i, weight=1, uniform="column")
        rows = [0, 0]
        for phase in PLATFORM.phases:
            i = rows.index(min(rows))
            rows[i] += len(phase.patches) + sum(len(p.parameters) for p in phase.patches) + 2
            frame = ttk.LabelFrame(columns[i], text=phase.name, padding=8)
            frame.pack(fill="x", pady=(0, 8))
            frame.columnconfigure(0, weight=1)
            for patch in phase.patches:
                self.add_option(frame, patch)

        bar = ttk.Frame(top)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Label(bar, text="Preset:").pack(side="left")
        self.preset_var = tk.StringVar()
        self.preset_box = ttk.Combobox(bar, textvariable=self.preset_var, width=18)
        self.preset_box.pack(side="left", padx=(4, 0))
        self.preset_box.bind("<<ComboboxSelected>>", lambda _: self.switch_preset(self.preset_var.get()))
        self.preset_box.bind("<Return>", lambda _: self.switch_preset(self.preset_var.get()))
        Tooltip(self.preset_box, lambda: wrap_lines(
            "The user preset this window edits: %s/NAME.config. Pick one, or type a new name and press Enter. "
            "Save writes it; a changed name saves a copy under that name."
            % os.path.relpath(USER_PRESETS, REPO).replace(os.sep, "/")))
        ttk.Label(bar, text="Based on:").pack(side="left", padx=(12, 0))
        self.base_var = tk.StringVar()
        self.base_box = ttk.Combobox(bar, textvariable=self.base_var, state="readonly", width=14)
        self.base_box.pack(side="left", padx=(4, 0))
        self.base_box.bind("<<ComboboxSelected>>", lambda _: self.base_changed())
        Tooltip(self.base_box, lambda: wrap_lines(
            "A preset this one builds on, such as plus (the patches of build/stm32-plus.bin). Its options apply "
            "first; this preset only stores what differs from it."))
        ttk.Button(bar, text="Save", command=self.save).pack(side="left", padx=(12, 0))
        ttk.Button(bar, text="Reload", command=self.reload).pack(side="left", padx=(6, 0))
        clear = ttk.Button(bar, text="Clear own options", command=self.clear)
        clear.pack(side="left", padx=(6, 0))
        Tooltip(clear, lambda: wrap_lines(
            "Removes the options this preset sets itself, so it shows its base preset (or the built-in "
            "defaults). Save writes the choice."))
        self.status = ttk.Label(bar, text="")
        self.status.pack(side="left", padx=12)
        self.local_note = ttk.Label(top, foreground="#b36b00", wraplength=1200, justify="left")
        self.local_note.pack(fill="x", pady=(6, 0))
        Tooltip(self.local_note, lambda: wrap_lines(
            "The local options file %s applies under every preset, also for make. It is edited by hand; see "
            "docs/patch_options.md." % LOCAL_FILE.name))
        line = ttk.Frame(top)
        line.pack(fill="x", pady=(6, 0))
        ttk.Label(line, text="Preset file:").pack(side="left")
        self.cmdline = tk.StringVar()   # the preset's options in CLI syntax
        ttk.Entry(line, textvariable=self.cmdline, state="readonly", font=("Consolas", 9)).pack(
            side="left", fill="x", expand=True, padx=(6, 0))

        settings = self.settings
        sections = ttk.Frame(bottom)   # left: patch an image, right: flash it to the device
        sections.pack(fill="x")
        patch = ttk.LabelFrame(sections, text="Patch firmware", padding=8)
        patch.pack(side="left", fill="both", expand=True)
        patch.columnconfigure(1, weight=1)
        self.infile = tk.StringVar(value=settings.get("input", ""))
        self.outfile = tk.StringVar(value=settings.get("output") or DEFAULT_OUTPUT)
        self.verbose = tk.BooleanVar(value=settings.get("verbose", False))
        for row, (label, var, saving) in enumerate((("Input firmware:", self.infile, False),
                                                    ("Output firmware:", self.outfile, True))):
            ttk.Label(patch, text=label).grid(row=row, column=0, sticky="w", pady=(0, 4))
            ttk.Entry(patch, textvariable=var).grid(row=row, column=1, sticky="we", padx=6, pady=(0, 4))
            ttk.Button(patch, text="Browse...", command=lambda v=var, s=saving: self.browse(v, s)).grid(
                row=row, column=2, pady=(0, 4))
        actions = ttk.Frame(patch)
        actions.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.patch_btn = ttk.Button(actions, text="Patch", command=self.patch)
        self.patch_btn.pack(side="left")
        self.build_btn = ttk.Button(actions, text="Build payloads (make binaries)", command=self.build)
        self.build_btn.pack(side="left", padx=(6, 0))
        Tooltip(self.build_btn, lambda: wrap_lines(
            "Compiles the payloads the patcher loads from build/ (graph, Custom VAuto, ...). Needed "
            "once, and again after changing patches/. Runs: %s" % " ".join(build_command() or ["make", "binaries"])))
        self.stop_btn = ttk.Button(actions, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(6, 0))
        ttk.Checkbutton(actions, text="Verbose (per-patch details)", variable=self.verbose).pack(side="left", padx=12)

        flash = ttk.LabelFrame(sections, text="Flash device (SWD, OpenOCD)", padding=8)
        flash.pack(side="left", fill="both", expand=True, padx=(8, 0))
        flash.columnconfigure(1, weight=1)
        found = find_openocd()
        mode = {"windows": "local"}.get(settings.get("ocd_mode"), settings.get("ocd_mode"))   # older settings files
        if os.name != "nt" or mode not in ("local", "wsl"):   # WSL is only an option from Windows
            mode = "local" if found or os.name != "nt" else "wsl"
        self.ocd_mode = tk.StringVar(value=mode)
        self.ocd_path = tk.StringVar(value=settings.get("ocd_path") or found)
        self.ocd_interface = tk.StringVar(value=settings.get("ocd_interface") or "stlink")
        self.flash_file = tk.StringVar(value=settings.get("flash_file") or self.outfile.get())
        self.backup = tk.StringVar(value=settings.get("backup") or DEFAULT_BACKUP)
        ttk.Label(flash, text="OpenOCD:").grid(row=0, column=0, sticky="w", pady=(0, 4))
        choices = (("local", "Windows openocd.exe"), ("wsl", "WSL (run-ocd.sh)")) if os.name == "nt" else (
            ("local", "OpenOCD on this system"),)
        modes = ttk.Frame(flash)
        modes.grid(row=0, column=1, columnspan=2, sticky="w", padx=6, pady=(0, 4))
        for value, text in choices:
            ttk.Radiobutton(modes, text=text, value=value, variable=self.ocd_mode,
                            command=self.ocd_mode_changed).pack(side="left", padx=(0, 12))
        ttk.Label(modes, text="Adapter:").pack(side="left")
        ttk.Combobox(modes, textvariable=self.ocd_interface, values=("stlink", "jlink"), state="readonly",
                     width=7).pack(side="left", padx=(4, 0))
        ttk.Label(flash, text="openocd.exe:" if os.name == "nt" else "openocd:").grid(
            row=1, column=0, sticky="w", pady=(0, 4))
        self.ocd_entry = ttk.Entry(flash, textvariable=self.ocd_path)
        self.ocd_entry.grid(row=1, column=1, sticky="we", padx=6, pady=(0, 4))
        self.ocd_browse = ttk.Button(flash, text="Browse...", command=self.browse_openocd)
        self.ocd_browse.grid(row=1, column=2, pady=(0, 4))
        for row, (label, var, saving) in enumerate((("Firmware:", self.flash_file, False),
                                                    ("Backup (dump):", self.backup, True)), start=2):
            ttk.Label(flash, text=label).grid(row=row, column=0, sticky="w", pady=(0, 4))
            ttk.Entry(flash, textvariable=var).grid(row=row, column=1, sticky="we", padx=6, pady=(0, 4))
            ttk.Button(flash, text="Browse...", command=lambda v=var, s=saving: self.browse(v, s)).grid(
                row=row, column=2, pady=(0, 4))
        ocd_actions = ttk.Frame(flash)
        ocd_actions.grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.ocd_buttons = []
        for text, command, tip in (
                ("Check device", self.ocd_check, "Connects and reports whether the device runs stock or patched "
                 "firmware."),
                ("Dump backup", self.ocd_dump, "Saves the whole 1 MB flash to the backup file (dump). Do this "
                 "once on stock firmware before flashing: it is the only way to restore the device."),
                ("Flash", self.ocd_flash, "Writes the firmware file to the device and verifies it (flash_new). "
                 "Takes about 30 seconds; the device reboots afterwards."),
                ("Verify", self.ocd_verify, "Compares the device flash with the firmware file "
                 "(flash verify_bank)."),
                ("Reset", self.ocd_reset, "Restarts the device (reset run).")):
            button = ttk.Button(ocd_actions, text=text, command=command)
            button.pack(side="left", padx=(0, 6))
            Tooltip(button, lambda t=tip: wrap_lines(t))
            self.ocd_buttons.append(button)
        self.ocd_mode_changed()

        self.log = tk.Text(bottom, state="disabled", wrap="none", font=("Consolas", 10), height=10)
        self.log.pack(fill="both", expand=True, pady=(8, 0))
        self.log.tag_configure("fail", foreground="#b00020")
        self.log.tag_configure("warn", foreground="#b36b00")
        self.log.tag_configure("pass", foreground="#1b7f2a")


        for var in (self.outfile, self.backup):
            var.trace_add("write", lambda *_: self.update_steps())
        self.load_preset(self.settings.get("preset") or DEFAULT_PRESET)
        self.after(100, self.pump)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def add_option(self, frame, patch):
        """A checkbox with the patch description and its option name, then one field per parameter."""
        row = frame.grid_size()[1]
        self.enabled[patch.option] = tk.BooleanVar()
        check = ttk.Checkbutton(frame, text=patch.description.rstrip("."), variable=self.enabled[patch.option],
                                command=lambda: self.toggled(patch.option))
        check.grid(row=row, column=0, sticky="w")
        name = ttk.Label(frame, text="--" + patch.option, foreground="#888888", font=("Consolas", 9))
        name.grid(row=row, column=1, sticky="e", padx=(8, 0))
        for widget in (check, name):
            Tooltip(widget, lambda: self.tooltip_text(patch))
        self.checks[patch.option] = check
        if patch.deprecated:
            ttk.Label(frame, text="Deprecated, only applied with --force-deprecated: " + patch.deprecated,
                      foreground="#666666").grid(row=row + 1, column=0, columnspan=2, sticky="w", padx=(22, 0))
        for parameter in patch.parameters:
            sub = ttk.Frame(frame)
            sub.grid(row=frame.grid_size()[1], column=0, columnspan=2, sticky="w", padx=(22, 0), pady=(0, 2))
            ttk.Label(sub, text="--%s" % parameter.option, font=("Consolas", 9)).pack(side="left")
            var = self.params[parameter.option] = tk.StringVar()
            var.trace_add("write", self.refresh)
            if parameter.value.choices is not None:
                widget = ttk.Combobox(sub, textvariable=var, width=12, state="readonly",
                                      values=[value_text(choice, parameter.value) for choice in parameter.value.choices])
            else:
                widget = ttk.Entry(sub, textvariable=var, width=24 if parameter.value.repeat else 12)
            widget.pack(side="left", padx=(6, 6))
            if parameter.value.metavar:
                ttk.Label(sub, text=parameter.value.metavar, foreground="#666666").pack(side="left")
            Tooltip(widget, lambda p=parameter: wrap_lines(p.description +
                    (" Several values are separated by spaces." if p.value.repeat else "")))
            self.param_widgets[parameter.option] = widget

    def tooltip_text(self, patch):
        """The patch's declaration: description, default, parameters, dependencies, and what sets it now."""
        parts = ["--%s (default: %s)" % (patch.option, "on" if patch.default else "off"),
                 wrap_lines(patch.description)]
        for parameter in patch.parameters:
            parts.append(wrap_lines("--%s: %s" % (parameter.option, parameter.description)))
        if patch.requires:
            parts.append("Requires: " + ", ".join("--" + o for o in patch.requires))
        if self.required_by[patch.option]:
            parts.append("Required by: " + ", ".join("--" + o for o in self.required_by[patch.option]))
        if patch.deprecated:
            parts.append(wrap_lines("Deprecated: " + patch.deprecated))
        values = self.shown()
        own = self.own_values(values) if values is not None else {}
        if patch.option in own:
            parts.append("Set by this preset")
        elif patch.option in self.sources:
            parts.append("Set by " + self.sources[patch.option])
        return "\n\n".join(parts)

    # Values: dicts from option name to the parsed value, as patch_config.layer_values() returns them.

    def layers(self, base):
        """Configuration layers under this preset, as the patcher builds them for make PATCH_ARGS='--preset
        NAME': the local options file (and the presets it selects), then the base presets."""
        preset_parser = patch_config.options_parser(PLATFORM)
        layers = patch_config.config_layers(PLATFORM.name, [], patch_config.local_options_parser(PLATFORM),
                                            preset_parser)[:-1]   # the empty command line
        layers += patch_config.preset_layers(PLATFORM.name, base, USER_PRESETS, preset_parser)
        if preset_path(self.name).resolve() in [layer.path for layer in layers]:
            raise ValueError("preset %s selects itself through %s" % (self.name, " + ".join(base)))
        return layers

    def set_base(self, base):
        """Reads what applies under this preset with these base presets. Raises OSError or ValueError."""
        layers = self.layers(base)
        args = vars(patch_config.effective_args(PLATFORM, layers))
        self.underlying = {option: args[patch_options.dest(option)] for option in OPTIONS}
        self.sources = {}
        for layer in layers:
            for option in patch_config.layer_values(PLATFORM, layer):
                if option in OPTIONS:
                    self.sources[option] = layer_label(layer)
        local = [layer for layer in layers if layer.source == "local"][0]
        self.local_options = tuple("--preset " + preset for preset in local.presets) + local.options
        self.base = list(base)

    def shown(self):
        """option -> value of every patch and parameter as shown, parsed by the patcher's own option parser;
        a parameter of an unticked patch keeps the value under this preset. None for an invalid value."""
        tokens = []
        for patch in PLATFORM.patches():
            tokens += ["--" + patch.option, "y" if self.enabled[patch.option].get() else "n"]
        typed = set()
        for parameter, patch in PARAMETERS:
            text = self.params[parameter.option].get().strip()
            if self.enabled[patch.option].get() and text:
                typed.add(parameter.option)
                for item in shlex.split(text) if parameter.value.repeat else [text]:
                    tokens += ["--" + parameter.option, item]
        try:
            args = vars(patch_config.options_parser(PLATFORM).parse_args(tokens))
        except ValueError as exc:
            self.error = str(exc)
            return None
        values = {option: args[patch_options.dest(option)] for option in OPTIONS}
        for parameter, patch in PARAMETERS:
            if parameter.option not in typed and not self.enabled[patch.option].get():
                values[parameter.option] = self.underlying[parameter.option]
        return values

    def own_values(self, values):
        """The options that differ from what applies under this preset: what the preset file stores."""
        return {option: value for option, value in values.items() if value != self.underlying[option]}

    def preset_text(self, own):
        return HEADER + "\n" + patch_config.option_text(PLATFORM, own, self.base)

    def apply(self, own):
        """Shows own (the options this preset sets) over what applies under it."""
        self.loading = True
        for patch in PLATFORM.patches():
            self.enabled[patch.option].set(bool(own.get(patch.option, self.underlying[patch.option])))
        for parameter, _ in PARAMETERS:
            self.params[parameter.option].set(value_text(own.get(parameter.option, self.underlying[parameter.option]),
                                                         parameter.value))
        self.base_var.set(" + ".join(self.base) or NO_BASE)
        self.loading = False
        self.refresh()

    def dirty(self):
        values = self.shown()
        return values is None or self.preset_text(self.own_values(values)) != self.saved_text

    def update_steps(self):
        """Ticks the checklist from what exists on disk and what this window has done."""
        if self.loading or not hasattr(self, "backup"):
            return
        done = {
            "save": preset_path(self.name).is_file() and not self.dirty(),
            "build": bool(glob.glob(os.path.join(REPO, "build", "*.elf"))),
            "patch": os.path.isfile(self.outfile.get().strip()),
            "backup": os.path.isfile(self.backup.get().strip()),
            "flash": self.flashed,
        }
        for key, text in STEPS:
            label = self.steps[key]
            if key == "choose":
                label.config(text=text)
            else:
                label.config(text=("✓ " if done[key] else "○ ") + text,
                             foreground="#1b7f2a" if done[key] else "#888888")

    def refresh(self, *_):
        """Parameter states, bold for options this preset sets, the preset file line and the title."""
        if self.loading or not self.name:
            return
        for parameter, patch in PARAMETERS:
            self.param_widgets[parameter.option].state(
                ["!disabled"] if self.enabled[patch.option].get() else ["disabled"])
        values = self.shown()
        if values is None:
            self.cmdline.set("Invalid value: %s" % self.error)
            return
        own = self.own_values(values)
        for patch in PLATFORM.patches():
            self.checks[patch.option].config(style="Changed.TCheckbutton" if patch.option in own else "TCheckbutton")
        self.cmdline.set(shlex.join(patch_config.option_args(PLATFORM, own, self.base)))
        self.local_note.config(text="%s also applies under this preset: %s" % (
            LOCAL_FILE.name, shlex.join(self.local_options)) if self.local_options else "")
        self.title("%s - preset %s%s" % (TITLE, self.name, " *" if self.dirty() else ""))
        self.update_steps()

    def toggled(self, option):
        changed = []
        on = self.enabled[option].get()
        self.follow(option, on, changed)
        self.status.config(text="Also %s: %s" % ("enabled" if on else "disabled", ", ".join("--" + o for o in changed))
                           if changed else "")
        self.refresh()

    def follow(self, option, on, changed):
        """Ticking a patch ticks what it requires; unticking one unticks the patches that require it."""
        related = PLATFORM.patch(option).requires if on else self.required_by[option]
        for other in related:
            if self.enabled[other].get() != on:
                self.enabled[other].set(on)
                changed.append(other)
                self.follow(other, on, changed)

    def load_preset(self, name):
        """Shows a user preset; a name without a file starts a new preset on the built-in defaults."""
        self.name = name
        self.preset_box.config(values=user_presets())
        self.preset_var.set(name)
        self.base_box.config(values=[NO_BASE] + [p for p in patch_config.preset_files(PLATFORM.name) if p != name])
        path = preset_path(name)
        base, own, self.foreign = [], {}, False
        try:
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                self.foreign = not text.startswith(HEADER)
                base, options = patch_config.split_presets(patch_config.read_options(path))
                own = patch_config.layer_values(PLATFORM, patch_config.Layer("preset", path, tuple(base),
                                                                             tuple(options)))
                status = "Loaded %s" % path
            else:
                status = "New preset %s: Save writes %s" % (name, path)
            self.set_base(base)
        except (OSError, ValueError) as exc:
            messagebox.showerror(TITLE, "%s could not be read:\n\n%s\n\nThe built-in defaults are shown; Save "
                                 "replaces the preset." % (path, exc))
            self.base, own, self.foreign = [], {}, True
            self.underlying = vars(patch_config.options_parser(PLATFORM).parse_args([]))
            self.underlying = {option: self.underlying[patch_options.dest(option)] for option in OPTIONS}
            self.sources, self.local_options = {}, ()
            status = "Could not read %s" % path.name
        own = {option: value for option, value in own.items() if value != self.underlying[option]}
        # an untouched new preset is not a change; one that could not be read always is
        self.saved_text = None if status.startswith("Could") else self.preset_text(own)
        self.status.config(text=status)
        self.apply(own)

    def switch_preset(self, name):
        name = name.strip()
        if name == self.name:
            return
        if not PRESET_NAME.match(name):
            messagebox.showerror(TITLE, "A preset name uses letters, digits, '.', '_' and '-' only.")
            self.preset_var.set(self.name)
            return
        if self.dirty():
            answer = messagebox.askyesnocancel(TITLE, "Save the changes to preset %s first?" % self.name)
            if answer is None or (answer and not self.save(self.name)):
                self.preset_var.set(self.name)
                return
        self.load_preset(name)
        self.save_settings()

    def base_changed(self):
        """Shows the new base preset with the options this preset sets itself on top."""
        values = self.shown()
        if values is None:
            messagebox.showerror(TITLE, "Fix the invalid value first:\n\n%s" % self.error)
            self.base_var.set(" + ".join(self.base) or NO_BASE)
            return
        own = self.own_values(values)
        choice = self.base_var.get()
        old = self.base
        try:
            self.set_base([] if choice == NO_BASE else [choice])
        except (OSError, ValueError) as exc:
            messagebox.showerror(TITLE, "Preset %s could not be used:\n\n%s" % (choice, exc))
            self.set_base(old)
        self.apply({option: value for option, value in own.items() if value != self.underlying[option]})

    def reload(self):
        if self.dirty() and not messagebox.askyesno(TITLE, "Discard the unsaved changes?"):
            return
        self.load_preset(self.name)

    def clear(self):
        self.apply({})
        self.status.config(text="Only the base preset shown; Save writes it")

    def save(self, name=None):
        """Writes the preset: its base presets and the options it sets itself. False when not saved."""
        name = (name or self.preset_var.get()).strip()
        if not PRESET_NAME.match(name):
            messagebox.showerror(TITLE, "Not saved: a preset name uses letters, digits, '.', '_' and '-' only.")
            return False
        values = self.shown()
        if values is None:
            messagebox.showerror(TITLE, "Not saved:\n\n%s" % self.error)
            return False
        own = self.own_values(values)
        path = preset_path(name)
        try:   # validate the whole configuration as the patcher will see it
            layer = patch_config.Layer("preset", path, tuple(self.base),
                                       tuple(patch_config.option_args(PLATFORM, own)))
            errors = PLATFORM.dependency_errors(
                patch_config.effective_args(PLATFORM, self.layers(self.base) + [layer]))
        except (OSError, ValueError) as exc:
            errors = [str(exc)]
        if errors:
            messagebox.showerror(TITLE, "Not saved:\n\n%s" % "\n".join(errors))
            return False
        if name in patch_config.preset_files(PLATFORM.name) and not path.is_file() and not messagebox.askyesno(
                TITLE, "A user preset named %s replaces the built-in preset %s, also for make.\n\nSave anyway?"
                % (name, name)):
            return False
        if (self.foreign or name != self.name) and path.is_file() and not messagebox.askyesno(
                TITLE, "%s %s. Its comments and layout will be replaced.\n\nSave anyway?" % (
                    path, "was not written by this window" if name == self.name else "already exists")):
            return False
        text = self.preset_text(own)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        except OSError as exc:
            messagebox.showerror(TITLE, "Not saved:\n\n%s" % exc)
            return False
        if name != self.name:
            self.name = name
            self.preset_box.config(values=user_presets())
            self.base_box.config(values=[NO_BASE] + [p for p in patch_config.preset_files(PLATFORM.name)
                                                     if p != name])
            self.save_settings()
        self.foreign = False
        self.saved_text = text
        self.status.config(text="Saved %s" % path)
        self.refresh()
        return True

    def browse(self, var, saving):
        start = os.path.dirname(var.get()) or REPO
        kwargs = dict(initialdir=start, filetypes=[("Firmware image", "*.bin"), ("All files", "*.*")])
        path = (filedialog.asksaveasfilename(defaultextension=".bin", **kwargs) if saving
                else filedialog.askopenfilename(**kwargs))
        if path:
            var.set(os.path.normpath(path))

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({"input": self.infile.get(), "output": self.outfile.get(),
                           "verbose": self.verbose.get(), "ocd_mode": self.ocd_mode.get(),
                           "ocd_path": self.ocd_path.get(), "ocd_interface": self.ocd_interface.get(),
                           "flash_file": self.flash_file.get(), "backup": self.backup.get(),
                           "preset": self.name}, f, indent=2)
        except OSError:
            pass

    def append(self, text, tag=None):
        if tag is None:
            tag = ("fail" if "[ERROR]" in text or ": error:" in text or "Error:" in text or text.startswith("Traceback")
                   else "warn" if "[WARN]" in text or "[SKIP]" in text or text.startswith("Warn :")
                   else "pass" if "[OK]" in text else "")
        self.log.config(state="normal")
        self.log.insert("end", text + "\n", tag)
        self.log.see("end")
        self.log.config(state="disabled")

    def patch(self):
        """Saves the preset, then runs patch-airsense.py with it."""
        infile, outfile = self.infile.get().strip(), self.outfile.get().strip()
        if not os.path.isfile(infile):
            messagebox.showerror(TITLE, "Choose the original firmware image to patch.")
            return
        if not outfile:
            messagebox.showerror(TITLE, "Choose where the patched image is written.")
            return
        if os.path.abspath(infile) == os.path.abspath(outfile):
            messagebox.showerror(TITLE, "The output would overwrite the original firmware image.")
            return
        if not self.ensure_wsl_tools():
            return
        if self.dirty() and not self.save():
            return
        self.save_settings()
        os.makedirs(os.path.dirname(os.path.abspath(outfile)), exist_ok=True)
        command = patch_command(infile, outfile, self.name, self.verbose.get())
        if command is None:
            messagebox.showerror(TITLE, "WSL cannot reach the firmware image or the output file. Move them to a "
                                 "local drive, or put the ARM toolchain (arm-none-eabi-nm) on the Windows PATH.")
            return
        self.run("Patching %s -> %s with preset %s%s" % (infile, outfile, self.name,
                                                          " (in WSL)" if use_wsl() else ""),
                 command, "%s written" % outfile)

    def ensure_wsl_tools(self):
        """False when WSL lacks make, the ARM toolchain or python3: offers to install them (as root, so no sudo
        password is needed) with the output in the log; click the action again when it is done."""
        packages = wsl_missing_packages() if use_wsl() else []
        if not packages:
            return True
        if messagebox.askyesno(TITLE, "WSL is missing: %s.\n\nInstall them now with apt (needs internet, takes a "
                               "minute)?" % ", ".join(packages)):
            self.run("Installing in WSL: %s" % " ".join(packages),
                     [shutil.which("wsl.exe"), "-u", "root", "--exec", "bash", "-c",
                      "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y " + " ".join(packages)],
                     "installed; click the button again")
        return False

    def build(self):
        """Builds the compiled payloads the patcher loads from build/ (make binaries)."""
        if not self.ensure_wsl_tools():
            return
        command = build_command()
        if command is None:
            messagebox.showerror(TITLE, "make was not found. On Windows the payloads are built in WSL with make and "
                                 "arm-none-eabi-gcc; see docs/guide/wsl_setup.md.")
            return
        self.run("Building payloads: %s" % " ".join(command[command.index("make"):]), command, "payloads built")

    def run(self, title, command, done, flashing=False, env=None):
        """Runs a command with its output in the log; one at a time, all action buttons disabled meanwhile."""
        self.append("=== %s ===" % title)
        self.done, self.flashing, self.hints, self.running = done, flashing, [], title
        if title.startswith("Patching"):
            self.flashed = False   # the device no longer has the newest patched image
        try:
            self.proc = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=REPO,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})}, creationflags=NO_WINDOW)
        except OSError as exc:
            self.append("Could not start %s: %s" % (command[0], exc), "fail")
            return
        threading.Thread(target=self.reader, args=(self.proc,), daemon=True).start()
        for button in self.action_buttons():
            button.config(state="disabled")
        self.stop_btn.config(state="normal")

    def action_buttons(self):
        return [self.patch_btn, self.build_btn] + self.ocd_buttons

    def stop(self, ask=True):
        if self.proc and self.proc.poll() is None:
            if self.flashing and ask and not messagebox.askyesno(
                    TITLE, "Flashing is in progress. Stopping now can leave the device without working firmware "
                    "until it is flashed again over SWD.\n\nStop anyway?", icon="warning"):
                return
            self.proc.terminate()

    def ocd_mode_changed(self):
        state = "normal" if self.ocd_mode.get() == "local" else "disabled"
        self.ocd_entry.config(state=state)
        self.ocd_browse.config(state=state)

    def browse_openocd(self):
        types = [("OpenOCD", "openocd*.exe"), ("All files", "*.*")] if os.name == "nt" else [("All files", "*")]
        path = filedialog.askopenfilename(initialdir=os.path.dirname(self.ocd_path.get()) or None, filetypes=types)
        if path:
            self.ocd_path.set(os.path.normpath(path))

    def tcl_path(self, path):
        """A file argument for the airsense.cfg commands: relative to the repo (OpenOCD runs there) when inside
        it, otherwise absolute, converted to a WSL path in WSL mode. Braced for Tcl. None, after telling the
        user, when WSL cannot reach the file."""
        path = os.path.realpath(path)
        try:
            rel = os.path.relpath(path, REPO)
        except ValueError:   # another drive
            rel = os.pardir
        if not rel.startswith(os.pardir):
            path = rel
        elif self.ocd_mode.get() == "wsl":
            translated = wsl_path(path)
            if translated is None:
                messagebox.showerror(TITLE, "WSL cannot reach %s. Move the file into the repository folder "
                                     "or use Windows openocd.exe." % path)
                return None
            path = translated
        return "{%s}" % path.replace("\\", "/")

    def openocd_command(self, commands):
        """OpenOCD with tcl/airsense.cfg, which connects and reports the device state, then these commands and
        shutdown. WSL mode goes through run-ocd.sh, which also attaches the adapter with usbipd."""
        commands = list(commands) + ["shutdown"]
        interface = self.ocd_interface.get()
        if self.ocd_mode.get() == "wsl":
            wsl = shutil.which("wsl.exe")
            if not wsl:
                messagebox.showerror(TITLE, "wsl.exe was not found; choose Windows openocd.exe instead.")
                return None
            args = [wsl, "--cd", REPO, "--exec", "bash", "run-ocd.sh", "--interface", interface]
        else:
            exe = self.ocd_path.get().strip()
            if not os.path.isfile(exe):
                messagebox.showerror(
                    TITLE, "Choose openocd.exe (OpenOCD for Windows, e.g. the xPack build), or use WSL." if os.name == "nt"
                    else "openocd was not found. Install OpenOCD (docs/guide/openocd.md) or choose its path.")
                return None
            args = [exe] + (["-f", "interface/stlink.cfg"] if interface == "stlink" else
                            ["-f", "interface/jlink.cfg", "-c", "transport select swd"])
            args += ["-f", "tcl/airsense.cfg"]
        for command in commands:
            args += ["-c", command]
        return args

    def run_openocd(self, title, commands, done, flashing=False):
        command = self.openocd_command(commands)
        if command:
            self.save_settings()
            self.run(title, command, done, flashing)

    def flash_image(self):
        """The firmware file to flash or verify, if it is a full 1 MB image."""
        path = self.flash_file.get().strip()
        if not os.path.isfile(path):
            messagebox.showerror(TITLE, "Choose the firmware image (e.g. the patched output).")
            return None
        if os.path.getsize(path) != FLASH_SIZE:
            messagebox.showerror(TITLE, "%s is %d bytes; a full 1 MB image (%d bytes) is needed."
                                 % (path, os.path.getsize(path), FLASH_SIZE))
            return None
        return path

    def ocd_check(self):
        self.run_openocd("Checking device", [], "device checked")

    def ocd_dump(self):
        path = self.backup.get().strip()
        if not path:
            messagebox.showerror(TITLE, "Choose where the backup is written.")
            return
        if os.path.exists(path) and not messagebox.askyesno(
                TITLE, "%s already exists. If it is your stock firmware dump, it is the only way to restore the "
                "device.\n\nOverwrite it?" % path, icon="warning", default="no"):
            return
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        target = self.tcl_path(path)
        if target:
            self.run_openocd("Dumping device flash to %s" % path, ["dump %s" % target], "%s written" % path)

    def ocd_flash(self):
        path = self.flash_image()
        if not path:
            return
        backup = self.backup.get().strip()
        if not os.path.isfile(backup) and not messagebox.askyesno(
                TITLE, "No backup found at %s.\n\nDumping the stock firmware before flashing is mandatory "
                "(docs/guide/openocd.md): it is the only way to restore the device. Flash anyway?" % backup,
                icon="warning", default="no"):
            return
        if not messagebox.askyesno(
                TITLE, "Flash %s to the device?\n\nThis replaces the whole firmware and takes about 30 seconds. "
                "Keep the device and the programmer connected until the log says Done." % path,
                icon="warning", default="no"):
            return
        image = self.tcl_path(path)
        if image:
            self.run_openocd("Flashing %s" % path, ["flash_new %s" % image],
                             "%s flashed and verified; the device reboots" % path, flashing=True)

    def ocd_verify(self):
        path = self.flash_image()
        image = path and self.tcl_path(path)
        if image:   # resume also after a mismatch, then report it
            self.run_openocd("Verifying device flash against %s" % path,
                             ["halt", "set r [catch {flash verify_bank 0 %s 0} msg]; resume; if {$r} {error $msg}"
                              % image], "device flash matches %s" % path)

    def ocd_reset(self):
        self.run_openocd("Resetting device", ["reset run"], "device reset")

    def reader(self, proc):
        for raw in proc.stdout:
            self.lines.put(raw.decode("utf-8", "replace").rstrip("\r\n"))
        self.lines.put(None)

    def pump(self):
        try:
            while True:
                line = self.lines.get_nowait()
                if line is None:
                    self.finished()
                else:
                    self.hints += [hint for needle, hint in LOG_HINTS if needle in line and hint not in self.hints]
                    self.append(line)
        except queue.Empty:
            pass
        self.after(100, self.pump)

    def finished(self):
        code = self.proc.wait()
        if code == 0:
            self.flashed = self.flashed or self.running.startswith("Flashing")
            self.append("=== Done: %s ===" % self.done, "pass")
        else:
            self.append("=== Failed (exit code %d) ===" % code, "fail")
        for hint in self.hints:
            self.append(hint, "warn")
        self.proc, self.flashing = None, False
        for button in self.action_buttons():
            button.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.update_steps()

    def on_close(self):
        if self.dirty():
            answer = messagebox.askyesnocancel(TITLE, "Save the changes to preset %s?" % self.name)
            if answer is None or (answer and not self.save()):
                return
        if self.flashing and not messagebox.askyesno(
                TITLE, "Flashing is in progress. Closing stops it and can leave the device without working "
                "firmware.\n\nClose anyway?", icon="warning", default="no"):
            return
        self.save_settings()
        self.stop(ask=False)
        self.destroy()

    def report_callback_exception(self, exc, value, tb):
        """There is no console under pythonw: show errors instead of losing them."""
        messagebox.showerror(TITLE, "".join(traceback.format_exception(exc, value, tb)))


def main():
    App().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

