"""AirBreaker: a window for the Air 10 patch options, patching and flashing.

The patches, their phases, descriptions, defaults, parameters and dependencies come from the shared option
declarations (python/lib/as10_patch_options.py through patch_options.load("air10")). Presets and option files
are read, validated and written with python/lib/patch_config.py, the code the patcher and make use too.
The window edits a user preset, presets/user/air10/NAME.config, which can build on another preset such as the
built-in plus. Ticking a patch also ticks the patches it requires; unticking one unticks the patches that
require it. Options the preset sets itself are shown bold, and Save writes only those. The local options file
patch-airsense.config is edited by hand and applies under every preset, so the window shows what it sets.
Build runs make AIR10_FIRMWARE=INPUT PATCH_ARGS='--preset NAME' build/stm32-patched.bin, with its output in
the log: make builds the payloads, patches the image and tracks the options and the input image in the image's
.config state file. Flash device does over SWD what docs/guide/flashing.md does in the OpenOCD telnet console:
each button runs run-ocd.sh once with the adapter (and its serial number, if given) and one of the
tcl/airsense.cfg commands (dump, flash_new, verify, ...); the exit code tells whether it worked. On Windows
make and run-ocd.sh run in WSL. The paths and choices are remembered in
~/.airbreak_patch_gui.json. Needs only Python with tkinter (included in the Windows installer). Start it with
airbreaker.bat (no console) or python python/airbreaker.py.
"""
import json
import os
import queue
import re
import shlex
import shutil
import signal
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
sys.path.insert(0, HERE)
from lib import patch_config, patch_options  # noqa: E402

TITLE = "AirBreaker"
PLATFORM = patch_options.load("air10")
LOCAL_FILE = patch_config.REPO / patch_config.LOCAL_FILES[PLATFORM.name]
USER_PRESETS = patch_config.REPO / patch_config.preset_dirs(PLATFORM.name)[0]   # presets/user/air10
DEFAULT_PRESET = "airbreaker"
PRESET_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")   # also in make PATCH_ARGS: no spaces, quotes, leading dash
HEADER = "# Written by AirBreaker (python/airbreaker.py): the options this preset sets itself."
NO_BASE = "(none)"
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".airbreak_patch_gui.json")
# The one fact about the Makefile this window needs: the target that builds the image from AIR10_FIRMWARE and
# PATCH_ARGS (documented in docs/patch_options.md). Its options and input are tracked by make, not here.
OUTPUT_TARGET = "build/stm32-patched.bin"
OUTPUT = os.path.join(REPO, *OUTPUT_TARGET.split("/"))
INPUT_COPY = "airbreaker-input.bin"   # copy of an input firmware whose path make cannot take
DEFAULT_BACKUP = os.path.join(REPO, "stm32.bin")   # where docs/guide/openocd.md has the stock dump
STEPS = (("choose", "1 Choose patches"), ("save", "2 Save"), ("patch", "3 Build"), ("backup", "4 Dump backup"),
         ("flash", "5 Flash"))   # the checklist above the options


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


def file_id(path):
    """Identifies the contents of a file for the checklist: its real path and modification time; None when it
    does not exist."""
    try:
        path = os.path.realpath(path)
        return path, os.stat(path).st_mtime_ns
    except (OSError, ValueError):
        return None


def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def in_wsl():
    """The one toolchain rule: on Windows, make and the tools it runs (the ARM toolchain, the patcher, OpenOCD)
    run in WSL (docs/guide/wsl_setup.md); elsewhere they run on this system."""
    return os.name == "nt"


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
WSL_PIDFILE = "/tmp/airbreaker-%d.pid" % os.getpid()   # process group of the command running in WSL
# In WSL: a new session (-w: setsid waits and passes on the exit code; without it setsid forks when it is
# already a group leader, as under wsl --exec, and returns 0 at once), whose process group id goes to the pid
# file for stop_in_wsl(). The pid file is removed when the command ends by itself.
WSL_WRAPPER = ["setsid", "-w", "bash", "-c", 'echo $$ > "$0"; "$@"; code=$?; rm -f "$0"; exit $code', WSL_PIDFILE]
# Waits briefly for the pid file of a command that has only just started, then ends its process group.
WSL_STOP = ('for _ in 1 2 3 4 5 6 7 8 9 10; do [ -s "$0" ] && break; sleep 0.2; done; '
            '[ -s "$0" ] && kill -s TERM -- "-$(cat "$0")"; rm -f "$0"')


def wsl_exe():
    """Path of wsl.exe, or None when WSL is not installed."""
    return shutil.which("wsl.exe")


def tool_command(args):
    """A command run in the repository, through WSL on Windows; None when WSL is not installed. In WSL it runs
    in its own process group, recorded in WSL_PIDFILE, so that stop_in_wsl() can end the whole command."""
    if not in_wsl():
        return list(args)
    wsl = wsl_exe()
    if not wsl:
        return None
    return [wsl, "--cd", REPO, "--exec"] + WSL_WRAPPER + list(args)


def stop_in_wsl():
    """Ends the command tool_command() started in WSL. Ending wsl.exe alone does not stop what runs inside."""
    wsl = wsl_exe()
    if not wsl:
        return
    try:
        subprocess.run([wsl, "--exec", "sh", "-c", WSL_STOP, WSL_PIDFILE], capture_output=True,
                       creationflags=NO_WINDOW, timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass


def make_input(firmware):
    """The firmware as make gets it in AIR10_FIRMWARE (repo-relative inside the repository, else a WSL or
    absolute path); None when the path cannot be passed to make."""
    path = os.path.realpath(firmware)
    try:
        rel = os.path.relpath(path, REPO)
    except ValueError:   # another drive
        rel = os.pardir
    if not rel.startswith(os.pardir):
        path = rel.replace(os.sep, "/")
    elif in_wsl():
        path = wsl_path(path)
    if path is None or any(c.isspace() or c in "'\"$#:;=%" for c in path):
        return None
    return path


def make_command(path, preset, verbose):
    """make building OUTPUT_TARGET from the input path (see make_input) with the preset; the Makefile tracks
    the options and the input in its .config state file."""
    args = ["make", "AIR10_FIRMWARE=" + path, "PATCH_ARGS=--preset " + preset]   # make picks the jobs
    return tool_command(args + (["V=1"] if verbose else []) + [OUTPUT_TARGET])


WSL_TOOLS_HINT = "WSL needs openocd and lsusb (usbutils); see docs/guide/wsl_setup.md."
LOG_HINTS = (   # output -> what to do about it, shown when the command ends
    ("openocd: command not found", WSL_TOOLS_HINT),
    ("lsusb: command not found", WSL_TOOLS_HINT),
    ("Error: open failed", "OpenOCD found no adapter: check the programmer's USB cable and driver, or in WSL "
     "that usbipd shares it (docs/guide/openocd.md)."),
)


def wsl_path(path):
    """The WSL path of a Windows path, or None when WSL cannot translate it."""
    path = os.path.realpath(path)   # also expands 8.3 names such as MICHIE~1, which WSL does not know
    try:
        result = subprocess.run([wsl_exe() or "wsl.exe", "--exec", "wslpath", "-a",
                                 path.replace("\\", "/")], capture_output=True, text=True, creationflags=NO_WINDOW)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


# The one list of what the build needs in WSL; airbreaker.bat installs only what opens the window.
WSL_TOOLS = (("make", "make"), ("arm-none-eabi-gcc", "gcc-arm-none-eabi"), ("arm-none-eabi-nm", "binutils-arm-none-eabi"),
             ("python3", "python3"))   # (command, apt package) the build and the patcher need in WSL


def wsl_has_apt():
    """Whether the default WSL distribution has apt-get (Debian, Ubuntu and their derivatives)."""
    wsl = wsl_exe()
    if not wsl:
        return False
    try:
        return subprocess.run([wsl, "--exec", "sh", "-c", "command -v apt-get"],
                              capture_output=True, creationflags=NO_WINDOW).returncode == 0
    except OSError:
        return False


def wsl_missing_packages():
    """apt packages of the WSL_TOOLS whose command is not in WSL; [] when all are there (or WSL cannot be asked)."""
    script = "for t in %s; do command -v $t >/dev/null || echo $t; done" % " ".join(t for t, _ in WSL_TOOLS)
    wsl = wsl_exe()
    if not wsl:
        return []
    try:
        result = subprocess.run([wsl, "--exec", "bash", "-c", script], capture_output=True,
                                text=True, creationflags=NO_WINDOW)
    except OSError:
        return []
    missing = result.stdout.split()
    return [pkg for tool, pkg in WSL_TOOLS if tool in missing]


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
        self.explicit = set()   # options the preset file sets itself: kept even where they equal self.underlying
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
            "The steps in order. A tick means it is done: the options are saved, make built the image from this "
            "window with the saved options and this input firmware, a backup file exists, and the device was "
            "flashed from this window with that image. Step 4 matters most: the stock dump is the only way to "
            "restore the device."))
        self.flashed = None    # file_id() of the image last flashed from this window
        self.built = None      # (preset, saved text, input) of the last successful build in this window
        self.kind = None       # "build" or "flash" for the running command, whose success updates the checklist
        self.pending = None    # what self.built or self.flashed becomes when the running command succeeds

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
            "A preset this one builds on, such as plus. Its options apply "
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
        patch = ttk.LabelFrame(sections, text="Build firmware (make)", padding=8)
        patch.pack(side="left", fill="both", expand=True)
        patch.columnconfigure(1, weight=1)
        self.infile = tk.StringVar(value=settings.get("input", ""))
        self.outfile = tk.StringVar(value=OUTPUT)   # the Makefile target; make keeps it in step with its inputs
        self.verbose = tk.BooleanVar(value=settings.get("verbose", False))
        ttk.Label(patch, text="Input firmware:").grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Entry(patch, textvariable=self.infile).grid(row=0, column=1, sticky="we", padx=6, pady=(0, 4))
        ttk.Button(patch, text="Browse...", command=lambda: self.browse(self.infile, False)).grid(
            row=0, column=2, pady=(0, 4))
        ttk.Label(patch, text="Output firmware:").grid(row=1, column=0, sticky="w", pady=(0, 4))
        ttk.Entry(patch, textvariable=self.outfile, state="readonly").grid(
            row=1, column=1, columnspan=2, sticky="we", padx=6, pady=(0, 4))
        actions = ttk.Frame(patch)
        actions.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.patch_btn = ttk.Button(actions, text="Build", command=self.patch)
        self.patch_btn.pack(side="left")
        Tooltip(self.patch_btn, lambda: wrap_lines(
            "Saves the preset, then builds %s with make: the payloads (needed once, and again after changing "
            "patches/), then the patched image. make decides what is out of date. Runs%s: make AIR10_FIRMWARE=INPUT PATCH_ARGS='--preset %s' %s"
            % (OUTPUT_TARGET, " in WSL" if in_wsl() else "", self.name, OUTPUT_TARGET)))
        self.stop_btn = ttk.Button(actions, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(6, 0))
        ttk.Checkbutton(actions, text="Verbose (per-patch details, V=1)", variable=self.verbose).pack(
            side="left", padx=12)

        flash = ttk.LabelFrame(sections, text="Flash device (SWD, OpenOCD)", padding=8)
        flash.pack(side="left", fill="both", expand=True, padx=(8, 0))
        flash.columnconfigure(1, weight=1)
        self.ocd_interface = tk.StringVar(value=settings.get("ocd_interface") or "stlink")
        self.ocd_serial = tk.StringVar(value=settings.get("ocd_serial", ""))
        self.flash_file = tk.StringVar(value=settings.get("flash_file") or OUTPUT)
        self.backup = tk.StringVar(value=settings.get("backup") or DEFAULT_BACKUP)
        ttk.Label(flash, text="Adapter:").grid(row=0, column=0, sticky="w", pady=(0, 4))
        adapter = ttk.Frame(flash)
        adapter.grid(row=0, column=1, columnspan=2, sticky="w", padx=6, pady=(0, 4))
        ttk.Combobox(adapter, textvariable=self.ocd_interface, values=("stlink", "jlink"), state="readonly",
                     width=7).pack(side="left")
        ttk.Label(adapter, text="Serial (optional):").pack(side="left", padx=(12, 4))
        serial = ttk.Entry(adapter, textvariable=self.ocd_serial, width=26)
        serial.pack(side="left")
        Tooltip(serial, lambda: wrap_lines(
            "Selects one of several connected adapters by its serial number (run-ocd.sh -s SERIAL). Leave empty "
            "with a single adapter."))
        ttk.Label(adapter, text="via run-ocd.sh%s" % (" in WSL" if in_wsl() else ""), foreground="#888888").pack(
            side="left", padx=(12, 0))
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
                ("Verify", self.ocd_verify, "Compares the device flash with the firmware file (verify)."),
                ("Reset", self.ocd_reset, "Restarts the device (reset run).")):
            button = ttk.Button(ocd_actions, text=text, command=command)
            button.pack(side="left", padx=(0, 6))
            Tooltip(button, lambda t=tip: wrap_lines(t))
            self.ocd_buttons.append(button)

        self.log = tk.Text(bottom, state="disabled", wrap="none", font=("Consolas", 10), height=10)
        self.log.pack(fill="both", expand=True, pady=(8, 0))
        self.log.tag_configure("fail", foreground="#b00020")
        self.log.tag_configure("warn", foreground="#b36b00")
        self.log.tag_configure("pass", foreground="#1b7f2a")


        for var in (self.outfile, self.backup, self.infile):
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

    def layers(self, base, name=None):
        """Configuration layers under this preset, as the patcher builds them for make PATCH_ARGS='--preset
        NAME': the local options file (and the presets it selects), then the base presets."""
        preset_parser = patch_config.options_parser(PLATFORM)
        layers = [layer for layer in patch_config.config_layers(
            PLATFORM.name, [], patch_config.local_options_parser(PLATFORM), preset_parser)
            if layer.source != "command line"]
        layers += patch_config.preset_layers(PLATFORM.name, base, USER_PRESETS, preset_parser)
        name = name or self.name
        if name in base or preset_path(name).resolve() in [layer.path for layer in layers]:
            raise ValueError("preset %s selects itself through %s" % (name, " + ".join(base)))
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
        a parameter of an unticked patch keeps the value under this preset, or the preset's own value when it
        sets one. None for an invalid value."""
        tokens = []
        for patch in PLATFORM.patches():
            tokens += ["--" + patch.option, "y" if self.enabled[patch.option].get() else "n"]
        typed = set()
        for parameter, patch in PARAMETERS:
            text = self.params[parameter.option].get().strip()
            if (self.enabled[patch.option].get() or parameter.option in self.explicit) and text:
                typed.add(parameter.option)
                try:
                    items = shlex.split(text) if parameter.value.repeat else [text]
                except ValueError as exc:
                    self.error = "--%s: %s" % (parameter.option, exc)
                    return None
                for item in items:
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
        """What the preset file stores: the options it sets itself and those that differ from what applies
        under it."""
        return {option: value for option, value in values.items()
                if option in self.explicit or value != self.underlying[option]}

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
            "patch": os.path.isfile(self.outfile.get().strip()) and self.built == (
                self.name, self.saved_text, self.infile.get().strip()),
            "backup": os.path.isfile(self.backup.get().strip()),
            "flash": self.flashed is not None and self.flashed == file_id(self.outfile.get().strip()),
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
        own = {option: value for option, value in own.items() if option in OPTIONS}
        self.explicit = set(own)
        # an untouched new preset is not a change; one that could not be read always is
        self.saved_text = None if status.startswith("Could") else self.preset_text(own)
        self.status.config(text=status)
        self.apply(own)

    def switch_preset(self, name):
        name = name.strip()
        if name == self.name:
            return
        if not PRESET_NAME.match(name):
            messagebox.showerror(TITLE, "A preset name starts with a letter or digit and uses letters, digits, '.', '_' and '-' only.")
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
            try:
                self.set_base(old)
            except (OSError, ValueError):   # the old base changed on disk as well
                self.load_preset(self.name)
                return
        self.apply({option: value for option, value in own.items()
                    if option in self.explicit or value != self.underlying[option]})

    def reload(self):
        if self.dirty() and not messagebox.askyesno(TITLE, "Discard the unsaved changes?"):
            return
        self.load_preset(self.name)

    def clear(self):
        self.explicit = set()
        self.apply({})
        self.status.config(text="Only the base preset shown; Save writes it")

    def save(self, name=None):
        """Writes the preset: its base presets and the options it sets itself. False when not saved."""
        name = (name or self.preset_var.get()).strip()
        if not PRESET_NAME.match(name):
            messagebox.showerror(TITLE, "Not saved: a preset name starts with a letter or digit and uses letters, digits, '.', '_' and '-' only.")
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
                patch_config.effective_args(PLATFORM, self.layers(self.base, name) + [layer]))
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
                json.dump({"input": self.infile.get(),
                           "verbose": self.verbose.get(), "ocd_interface": self.ocd_interface.get(),
                           "ocd_serial": self.ocd_serial.get(),
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
        """Saves the preset, then builds OUTPUT_TARGET from the input firmware with make."""
        infile = self.infile.get().strip()
        if not os.path.isfile(infile):
            messagebox.showerror(TITLE, "Choose the original firmware image to patch.")
            return
        if os.path.realpath(infile) == os.path.realpath(OUTPUT):
            messagebox.showerror(TITLE, "%s is what make builds; choose the original firmware image." % OUTPUT_TARGET)
            return
        if in_wsl() and not wsl_exe():
            messagebox.showerror(TITLE, "wsl.exe was not found. make runs in WSL on Windows; see "
                                 "docs/guide/wsl_setup.md.")
            return
        if not self.ensure_wsl_tools():
            return
        if self.dirty() and not self.save():
            return
        if not preset_path(self.name).is_file() and not self.save():   # make reads the preset from its file
            return
        self.save_settings()
        path = make_input(infile)
        if path is None:   # make cannot take the path (spaces, special characters): work from a copy
            copy = os.path.join(REPO, "build", INPUT_COPY)
            try:
                os.makedirs(os.path.dirname(copy), exist_ok=True)
                shutil.copyfile(infile, copy)
            except OSError as exc:
                messagebox.showerror(TITLE, "Could not copy %s to %s: %s" % (infile, copy, exc))
                return
            self.append("make cannot take the path of %s; building from a copy, build/%s" % (infile, INPUT_COPY),
                        "warn")
            path = make_input(copy)
            if path is None:
                messagebox.showerror(TITLE, "WSL cannot reach the repository folder %s." % REPO)
                return
        command = make_command(path, self.name, self.verbose.get())
        # what is built: the options as saved now and this input, also when they change while make runs
        self.pending = (self.name, self.saved_text, infile)
        self.run("Building %s from %s with preset %s%s" % (OUTPUT_TARGET, infile, self.name,
                                                           " (in WSL)" if in_wsl() else ""),
                 command, "%s built" % OUTPUT_TARGET, kind="build")

    def ensure_wsl_tools(self):
        """False when WSL lacks make, the ARM toolchain or python3. Shows the command that installs them and, on a
        WSL distribution with apt-get, offers to run it in a console window, where sudo asks for the password.
        Nothing is installed without asking. Click the action again when it is done."""
        packages = wsl_missing_packages() if in_wsl() else []
        if not packages:
            return True
        if not wsl_has_apt():
            messagebox.showerror(TITLE, "WSL is missing: %s.\n\nInstall make, python3 and the ARM GCC toolchain "
                                 "with the package manager of your WSL distribution (docs/guide/wsl_setup.md), "
                                 "then click the button again." % ", ".join(packages))
            return False
        command = "sudo apt-get update && sudo apt-get install %s" % " ".join(packages)
        if messagebox.askyesno(TITLE, "WSL is missing: %s.\n\nOpen a WSL console window that runs:\n\n%s\n\n"
                               "sudo asks for your WSL password there, and apt-get asks before installing. Click "
                               "the button again when it is done." % (", ".join(packages), command)):
            try:
                subprocess.Popen([wsl_exe(), "--exec", "bash", "-c",
                                  command + "; echo; read -r -p 'Press Enter to close this window. '"],
                                 creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            except OSError as exc:
                messagebox.showerror(TITLE, "Could not start WSL: %s" % exc)
        else:
            self.append("To install them yourself, run in WSL: " + command, "warn")
        return False

    def run(self, title, command, done, kind=None, flashing=False, env=None):
        """Runs a command with its output in the log; one at a time, all action buttons disabled meanwhile.
        kind is "build" or "flash" when its success updates the checklist with self.pending."""
        self.append("=== %s ===" % title)
        self.done, self.hints, self.kind = done, [], kind
        try:
            self.proc = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=REPO,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})}, creationflags=NO_WINDOW,
                start_new_session=not in_wsl())   # its own process group, which stop() ends as a whole
        except OSError as exc:
            self.append("Could not start %s: %s" % (command[0], exc), "fail")
            return
        self.flashing = flashing
        threading.Thread(target=self.reader, args=(self.proc,), daemon=True).start()
        for button in self.action_buttons():
            button.config(state="disabled")
        self.stop_btn.config(state="normal")

    def action_buttons(self):
        return [self.patch_btn] + self.ocd_buttons

    def stop(self, ask=True):
        if self.proc and self.proc.poll() is None:
            if self.flashing and ask and not messagebox.askyesno(
                    TITLE, "Flashing is in progress. Stopping now can leave the device without working firmware "
                    "until it is flashed again over SWD.\n\nStop anyway?", icon="warning"):
                return
            if in_wsl():
                stop_in_wsl()
                self.proc.terminate()
            else:   # make or run-ocd.sh and everything they started, such as the patcher or openocd
                try:
                    os.killpg(self.proc.pid, signal.SIGTERM)
                except OSError:
                    pass

    def tcl_path(self, path):
        """A file argument for the airsense.cfg commands: relative to the repo (OpenOCD runs there) when inside
        it, otherwise absolute, as a WSL path on Windows. Braced for Tcl. None, after telling the user, when
        WSL cannot reach the file."""
        path = os.path.realpath(path)
        try:
            rel = os.path.relpath(path, REPO)
        except ValueError:   # another drive
            rel = os.pardir
        if not rel.startswith(os.pardir):
            path = rel
        elif in_wsl():
            translated = wsl_path(path)
            if translated is None:
                messagebox.showerror(TITLE, "WSL cannot reach %s. Move the file into the repository folder." % path)
                return None
            path = translated
        if "{" in path or "}" in path:
            messagebox.showerror(TITLE, "OpenOCD cannot take a path with braces: %s" % path)
            return None
        return "{%s}" % path.replace("\\", "/")

    def openocd_command(self, commands):
        """run-ocd.sh with the adapter, which connects with tcl/airsense.cfg and reports the device state, then
        these commands and shutdown. run-ocd.sh also attaches the adapter to WSL with usbipd."""
        args = ["bash", "run-ocd.sh", "--interface", self.ocd_interface.get()]
        serial = self.ocd_serial.get().strip()
        if serial:
            args += ["-s", serial]
        for command in list(commands) + ["shutdown"]:
            args += ["-c", command]
        command = tool_command(args)
        if command is None:
            messagebox.showerror(TITLE, "wsl.exe was not found. OpenOCD runs in WSL on Windows; see "
                                 "docs/guide/wsl_setup.md.")
        return command

    def run_openocd(self, title, commands, done, kind=None, flashing=False):
        command = self.openocd_command(commands)
        if command:
            self.save_settings()
            self.run(title, command, done, kind, flashing)

    def flash_image(self):
        """The firmware file to flash or verify; flash_new itself rejects anything but a full image."""
        path = self.flash_file.get().strip()
        if not os.path.isfile(path):
            messagebox.showerror(TITLE, "Choose the firmware image (e.g. the patched output).")
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
            self.pending = file_id(path)
            self.run_openocd("Flashing %s" % path, ["flash_new %s" % image],
                             "%s flashed and verified; the device reboots" % path, kind="flash", flashing=True)

    def ocd_verify(self):
        path = self.flash_image()
        image = path and self.tcl_path(path)
        if image:
            self.run_openocd("Verifying device flash against %s" % path, ["verify %s" % image],
                             "device flash matches %s" % path)

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
            if self.kind == "build":
                self.built = self.pending
            elif self.kind == "flash":
                self.flashed = self.pending
            self.append("=== Done: %s ===" % self.done, "pass")
        else:
            self.append("=== Failed (exit code %d) ===" % code, "fail")
        for hint in self.hints:
            self.append(hint, "warn")
        self.proc, self.flashing, self.kind, self.pending = None, False, None, None
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

