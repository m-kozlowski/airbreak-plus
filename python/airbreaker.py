"""AirBreaker: Air10 and Air11 patch selection, builds and SWD flashing.

Patch declarations and configuration come from lib.patch_options and lib.patch_config.
Build passes the full form selection to Make; saving a preset is a separate operation
that retains only its own options and base preset selections. SWD actions use run-ocd.sh
and the selected platform's Tcl commands. On Windows, Make and OpenOCD run in WSL.
"""
import filecmp
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
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))   # <repo>/python
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from lib import patch_config, patch_options  # noqa: E402

TITLE = "AirBreaker"
DEFAULT_PRESET = "airbreaker"
PRESET_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")   # also in make PATCH_ARGS: no spaces, quotes, leading dash
PRESET_NAME_RULE = "a preset name starts with a letter or digit and uses letters, digits, '.', '_' and '-' only."
HEADER = "# Written by AirBreaker (python/airbreaker.py): the options this preset sets itself."
NO_BASE = "(none)"
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".airbreaker.json")
# Build targets and SWD entry points; patch definitions remain in patch_options.
TARGETS = {
    "Air10": dict(platform="air10", firmware="AIR10_FIRMWARE", patch_args="AIR10_PATCH_ARGS",
                  output="build/stm32-patched.bin", config="airsense", backup="stm32.bin", size=0x100000),
    "Air11": dict(platform="air11", firmware="AS11_FIRMWARE", patch_args="AIR11_PATCH_ARGS",
                  output="build/as11-patched.bin", config="as11", backup="as11.bin", size=0x200000),
}
STEPS = (("choose", "1 Choose patches"), ("patch", "2 Build"), ("backup", "3 Dump backup"),
         ("flash", "4 Flash"))


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


def user_presets(platform):
    directory = patch_config.REPO / patch_config.preset_dirs(platform.name)[0]
    return sorted(path.stem for path in directory.glob("*.config") if path.is_file())


def preset_path(platform, name):
    return patch_config.REPO / patch_config.preset_dirs(platform.name)[0] / (name + ".config")


def layer_label(layer):
    return layer.path.name if layer.source == "local" else "preset " + layer.path.stem


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


def ocd_interfaces():
    """The adapters run-ocd.sh knows, its default first; [] when it cannot be asked (no WSL, no bash)."""
    command = ["bash", "run-ocd.sh", "--list-interfaces"]
    if use_wsl():
        wsl = wsl_exe()
        if not wsl:
            return []
        command = [wsl, "--cd", REPO, "--exec"] + command
    try:
        result = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=60,
                                creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return []
    return result.stdout.split() if result.returncode == 0 else []


def use_wsl():
    """Whether tools run through WSL. The one toolchain rule: on Windows, make and the tools it runs (the ARM
    toolchain, the patcher, OpenOCD) run in WSL (docs/guide/wsl_setup.md); elsewhere they run on this system."""
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
    if not use_wsl():
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
    """The firmware as make gets it (repo-relative inside the repository, else a WSL or
    absolute path); None when the path cannot be passed to make."""
    path = os.path.realpath(firmware)
    try:
        rel = os.path.relpath(path, REPO)
    except ValueError:   # another drive
        rel = os.pardir
    if not rel.startswith(os.pardir):
        path = rel.replace(os.sep, "/")
    elif use_wsl():
        path = wsl_path(path)
    if path is None or any(c.isspace() or c in "'\"$#:;=%" for c in path):
        return None
    return path


def make_command(target, path, options, verbose):
    """Pass the form selection through the platform-specific Make variable, overriding its environment value."""
    # Make expands dollars before the recipe shell interprets the quoted arguments.
    arguments = shlex.join(options).replace("$", "$$")
    args = ["make", target["firmware"] + "=" + path, target["patch_args"] + "=" + arguments]
    return tool_command(args + (["V=1"] if verbose else []) + [target["output"]])


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


# (command, apt package) the build and the patcher need in WSL: the one list of them; airbreaker.bat installs
# only what opens the window.
WSL_TOOLS = (("make", "make"), ("arm-none-eabi-gcc", "gcc-arm-none-eabi"),
             ("arm-none-eabi-nm", "binutils-arm-none-eabi"), ("python3", "python3"))


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
        # Older settings files describe Air10 only.
        self.platform_settings = self.settings.setdefault("platforms", {})
        if "air10" not in self.platform_settings:
            self.platform_settings["air10"] = {key: self.settings[key] for key in
                ("input", "flash_file", "backup", "preset") if key in self.settings}
        platform_name = self.settings.get("platform", "Air10")
        if platform_name not in TARGETS:
            platform_name = "Air10"
        self.configure_platform(platform_name)
        self.enabled = {}   # patch option -> BooleanVar: patch selected
        self.params = {}    # parameter option -> StringVar with its value as typed
        self.param_widgets = {}   # parameter option -> its entry or combobox, disabled while the patch is off
        self.inherited_labels = {}   # inherited entries of repeatable parameters
        self.checks = {}    # patch option -> Checkbutton, bold when this preset sets it
        self.name = ""          # empty for a form that has not been named as a preset
        self.base = []          # presets this preset selects (--preset); they apply under it
        self.underlying = {}    # option -> value from the local options file and the base presets
        self.explicit = set()   # options the preset file sets itself: kept even where they equal self.underlying
        self.platform_values = {}   # e.g. an existing preset's --all-patches fallback
        self.sources = {}       # option -> the file under this preset that sets it
        self.local_options = ()   # what the platform's local options file sets, shown as a note
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
        ttk.Style(self).configure("Patch.TCheckbutton", wraplength=520)
        ttk.Style(self).configure("Changed.Patch.TCheckbutton", font=bold, wraplength=520)

        platform_bar = ttk.Frame(self)
        platform_bar.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(platform_bar, text="Platform:").pack(side="left")
        self.platform_var = tk.StringVar(value=platform_name)
        self.platform_box = ttk.Combobox(platform_bar, textvariable=self.platform_var,
                                         values=list(TARGETS), state="readonly", width=10)
        self.platform_box.pack(side="left", padx=6)
        self.platform_box.bind("<<ComboboxSelected>>", lambda _: self.switch_platform())

        checklist = ttk.Frame(self)   # what is done, in the order to do it
        checklist.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(checklist, text="Steps:").pack(side="left", padx=(0, 10))
        self.steps = {}
        for key, text in STEPS:
            self.steps[key] = ttk.Label(checklist, text=text)
            self.steps[key].pack(side="left", padx=(0, 18))
        self.flashed = None    # file_id() of the image last flashed from this window
        self.built = None      # platform, effective option arguments and input identity of the last build
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
        self.option_area = inner
        window = canvas.create_window(0, 0, window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        def resize_options(event):
            canvas.itemconfigure(window, width=event.width)
            width = max(200, (event.width - 100) // 2)
            ttk.Style(self).configure("Patch.TCheckbutton", wraplength=width)
            ttk.Style(self).configure("Changed.Patch.TCheckbutton", wraplength=width)
        canvas.bind("<Configure>", resize_options)

        def wheel(event):   # only scroll the options while the mouse is over them
            under = self.winfo_containing(event.x_root, event.y_root)
            if under is not None and str(under).startswith(str(canvas)):
                # X11 sends the wheel as buttons 4 and 5, Windows and macOS as <MouseWheel> with a delta
                up = event.num == 4 or (event.num != 5 and event.delta > 0)
                canvas.yview_scroll(-1 if up else 1, "units")
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(sequence, wheel)

        self.render_options()

        bar = ttk.Frame(top)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Label(bar, text="Preset (optional):").pack(side="left")
        self.preset_var = tk.StringVar()
        self.preset_box = ttk.Combobox(bar, textvariable=self.preset_var, width=18)
        self.preset_box.pack(side="left", padx=(4, 0))
        self.preset_box.bind("<<ComboboxSelected>>", lambda _: self.switch_preset(self.preset_var.get()))
        self.preset_box.bind("<Return>", lambda _: self.switch_preset(self.preset_var.get()))
        Tooltip(self.preset_box, lambda: wrap_lines(
            "The user preset this window edits: %s/NAME.config. Pick one, or type a new name and press Enter. "
            "Save writes it; a changed name saves a copy under that name."
            % os.path.relpath(self.user_presets_dir, REPO).replace(os.sep, "/")))
        ttk.Label(bar, text="Based on:").pack(side="left", padx=(12, 0))
        self.base_var = tk.StringVar()
        self.base_box = ttk.Combobox(bar, textvariable=self.base_var, state="readonly", width=14)
        self.base_box.pack(side="left", padx=(4, 0))
        self.base_box.bind("<<ComboboxSelected>>", lambda _: self.base_changed())
        Tooltip(self.base_box, lambda: wrap_lines(
            "The base preset. Its options apply first; saved overrides take precedence."))
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
            "docs/patch_options.md." % self.local_file.name))
        line = ttk.Frame(top)
        line.pack(fill="x", pady=(6, 0))
        ttk.Label(line, text="Preset file:").pack(side="left")
        self.cmdline = tk.StringVar()   # the preset's options in CLI syntax
        ttk.Entry(line, textvariable=self.cmdline, state="readonly", font=("Consolas", 9)).pack(
            side="left", fill="x", expand=True, padx=(6, 0))

        settings = self.platform_settings.get(self.platform.name, {})
        sections = ttk.Frame(bottom)   # left: patch an image, right: flash it to the device
        sections.pack(fill="x")
        patch = ttk.LabelFrame(sections, text="Build firmware (make)", padding=8)
        patch.pack(side="left", fill="both", expand=True)
        patch.columnconfigure(1, weight=1)
        self.infile = tk.StringVar(value=settings.get("input", ""))
        self.outfile = tk.StringVar(value=self.output)   # the Makefile target; make keeps it in step with its inputs
        self.verbose = tk.BooleanVar(value=self.settings.get("verbose", False))
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
            "Build %s from the current patch selection." % self.target["output"]))
        self.stop_btn = ttk.Button(actions, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(6, 0))
        ttk.Checkbutton(actions, text="Verbose (per-patch details, V=1)", variable=self.verbose).pack(
            side="left", padx=12)

        flash = ttk.LabelFrame(sections, text="Flash device (SWD, OpenOCD)", padding=8)
        flash.pack(side="left", fill="both", expand=True, padx=(8, 0))
        flash.columnconfigure(1, weight=1)
        self.ocd_interface = tk.StringVar(value=self.settings.get("ocd_interface", ""))
        self.ocd_serial = tk.StringVar(value=self.settings.get("ocd_serial", ""))
        self.flash_file = tk.StringVar(value=settings.get("flash_file") or self.output)
        self.backup = tk.StringVar(value=settings.get("backup") or self.default_backup)
        ttk.Label(flash, text="Adapter:").grid(row=0, column=0, sticky="w", pady=(0, 4))
        adapter = ttk.Frame(flash)
        adapter.grid(row=0, column=1, columnspan=2, sticky="w", padx=6, pady=(0, 4))
        # run-ocd.sh owns the list of adapters. It is asked in the background, as WSL can take a while to start.
        self.adapters = ttk.Combobox(adapter, textvariable=self.ocd_interface, state="readonly", width=7)
        self.adapters.pack(side="left")
        self.adapter_names = None   # set by the thread below, shown by pump()
        threading.Thread(target=lambda: setattr(self, "adapter_names", ocd_interfaces()), daemon=True).start()
        ttk.Label(adapter, text="Serial (optional):").pack(side="left", padx=(12, 4))
        serial = ttk.Entry(adapter, textvariable=self.ocd_serial, width=26)
        serial.pack(side="left")
        Tooltip(serial, lambda: wrap_lines(
            "Selects one of several connected adapters by its serial number (run-ocd.sh -s SERIAL). Leave empty "
            "with a single adapter."))
        ttk.Label(adapter, text="via run-ocd.sh%s" % (" in WSL" if use_wsl() else ""), foreground="#888888").pack(
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
                ("Check device", self.ocd_check, "Connect to the selected platform and report device information."),
                ("Dump backup", self.ocd_dump, "Save the complete firmware to the backup file."),
                ("Flash", self.ocd_flash, "Writes the firmware file to the device and verifies it (flash_new). "
                 "The device reboots afterwards."),
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

        for var in (self.backup, self.infile):
            var.trace_add("write", lambda *_: self.update_steps())
        self.load_preset(settings.get("preset") or "")
        self.after(100, self.pump)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def configure_platform(self, name):
        self.target = TARGETS[name]
        self.platform = patch_options.load(self.target["platform"])
        self.local_file = patch_config.REPO / patch_config.LOCAL_FILES[self.platform.name]
        self.user_presets_dir = patch_config.REPO / patch_config.preset_dirs(self.platform.name)[0]
        self.output = os.path.join(REPO, *self.target["output"].split("/"))
        self.default_backup = os.path.join(REPO, self.target["backup"])
        self.parameters = [(parameter, patch) for patch in self.platform.patches() for parameter in patch.parameters]
        self.options = [patch.option for patch in self.platform.patches()] + [p.option for p, _ in self.parameters]
        self.required_by = {p.option: [other.option for other in self.platform.patches() if p.option in other.requires]
                            for p in self.platform.patches()}

    def render_options(self):
        self.option_area.master.yview_moveto(0)
        for widget in self.option_area.winfo_children():
            widget.destroy()
        self.enabled.clear()
        self.params.clear()
        self.param_widgets.clear()
        self.inherited_labels.clear()
        self.checks.clear()
        if len(self.platform.phases) == 1:
            frame = ttk.LabelFrame(self.option_area, text=self.platform.phases[0].name, padding=8)
            frame.pack(fill="x")
            columns = [ttk.Frame(frame) for _ in range(2)]
            rows = [0, 0]
            for i, column in enumerate(columns):
                column.grid(row=0, column=i, sticky="nwe", padx=(0, 8))
                frame.columnconfigure(i, weight=1, uniform="column")
            for patch in self.platform.patches():
                i = rows.index(min(rows))
                self.add_option(columns[i], patch)
                rows[i] += 1 + len(patch.parameters)
        else:
            columns = [ttk.Frame(self.option_area) for _ in range(2)]
            rows = [0, 0]
            for i, column in enumerate(columns):
                column.grid(row=0, column=i, sticky="nwe", padx=(0, 8))
                self.option_area.columnconfigure(i, weight=1, uniform="column")
            for phase in self.platform.phases:
                i = rows.index(min(rows))
                rows[i] += len(phase.patches) + sum(len(p.parameters) for p in phase.patches) + 2
                frame = ttk.LabelFrame(columns[i], text=phase.name, padding=8)
                frame.pack(fill="x", pady=(0, 8))
                frame.columnconfigure(0, weight=1)
                for patch in phase.patches:
                    self.add_option(frame, patch)

    def switch_platform(self):
        name = self.platform_var.get()
        previous = next(label for label, target in TARGETS.items() if target is self.target)
        if name == previous:
            return
        if self.proc or not self.confirm_preset_change():
            self.platform_var.set(previous)
            return
        self.save_settings()
        self.loading = True
        self.configure_platform(name)
        self.render_options()
        settings = self.platform_settings.get(self.platform.name, {})
        self.infile.set(settings.get("input", ""))
        self.outfile.set(self.output)
        self.flash_file.set(settings.get("flash_file") or self.output)
        self.backup.set(settings.get("backup") or self.default_backup)
        self.built = self.flashed = None
        self.load_preset(settings.get("preset") or "")
        self.save_settings()

    def add_option(self, frame, patch):
        """A checkbox with the patch description, then one field per parameter."""
        row = frame.grid_size()[1]
        self.enabled[patch.option] = tk.BooleanVar()
        check = ttk.Checkbutton(frame, text=patch.description.rstrip("."), variable=self.enabled[patch.option],
                                style="Patch.TCheckbutton",
                                command=lambda: self.toggled(patch.option))
        check.grid(row=row, column=0, sticky="w")
        Tooltip(check, lambda: self.tooltip_text(patch))   # shows the option name
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
                                      values=[value_text(choice, parameter.value)
                                              for choice in parameter.value.choices])
            else:
                widget = ttk.Entry(sub, textvariable=var, width=24 if parameter.value.repeat else 12)
            widget.pack(side="left", padx=(6, 6))
            if parameter.value.metavar:
                ttk.Label(sub, text=parameter.value.metavar, foreground="#666666").pack(side="left")
            Tooltip(widget, lambda p=parameter: wrap_lines(p.description +
                    (" Several values are separated by spaces." if p.value.repeat else "")))
            self.param_widgets[parameter.option] = widget
            if parameter.value.repeat:
                inherited = ttk.Label(frame, foreground="#666666", wraplength=520)
                inherited.grid(row=frame.grid_size()[1], column=0, sticky="w", padx=(22, 0))
                self.inherited_labels[parameter.option] = inherited

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
        """Local configuration followed by the selected base presets."""
        preset_parser = patch_config.options_parser(self.platform)
        layers = [layer for layer in patch_config.config_layers(
            self.platform.name, [], patch_config.local_options_parser(self.platform), preset_parser)
            if layer.source != "command line"]
        base_layers = patch_config.preset_layers(self.platform.name, base, self.user_presets_dir, preset_parser)
        name = name or self.name
        # the local options file may select this preset too, as make allows; a base preset may not
        if name and (name in base or preset_path(self.platform, name).resolve() in [layer.path for layer in base_layers]):
            raise ValueError("preset %s selects itself through %s" % (name, " + ".join(base)))
        return layers + base_layers

    def set_base(self, base):
        """Reads what applies under this preset with these base presets. Raises OSError or ValueError."""
        layers = self.layers(base)
        # Keep a preset's global fallback (e.g. --all-patches n) without turning
        # its inherited switch values into explicit overrides when it is saved.
        fallback = patch_config.Layer("preset", None, (),
                                      tuple(patch_config.option_args(self.platform, self.platform_values)))
        args = patch_config.effective_args(self.platform, layers + [fallback])
        self.underlying = {p.option: self.platform.selected(args, p) for p in self.platform.patches()}
        self.underlying.update((p.option, getattr(args, patch_options.dest(p.option))) for p, _ in self.parameters)
        self.sources = {}
        for layer in layers:
            for option in patch_config.layer_values(self.platform, layer):
                if option in self.options:
                    self.sources[option] = layer_label(layer)
        local = [layer for layer in layers if layer.source == "local"][0]
        self.local_options = tuple("--preset " + preset for preset in local.presets) + local.options
        self.base = list(base)

    def shown(self):
        """Full effective form values, parsed with the shared option declarations; None for invalid input."""
        tokens = []
        for patch in self.platform.patches():
            tokens += ["--" + patch.option, "y" if self.enabled[patch.option].get() else "n"]
        for parameter, patch in self.parameters:
            text = self.params[parameter.option].get().strip()
            if parameter.value.repeat:
                for item in self.underlying[parameter.option] or ():
                    tokens += ["--" + parameter.option, patch_config.format_value(item, parameter.value)]
            if text:
                try:
                    items = shlex.split(text) if parameter.value.repeat else [text]
                except ValueError as exc:
                    self.error = "--%s: %s" % (parameter.option, exc)
                    return None
                for item in items:
                    tokens += ["--" + parameter.option, item]
        try:
            args = vars(patch_config.options_parser(self.platform).parse_args(tokens))
        except ValueError as exc:
            self.error = str(exc)
            return None
        values = {option: args[patch_options.dest(option)] for option in self.options}
        return values

    def own_values(self, values):
        """What the preset file stores: the options it sets itself and those that differ from what applies
        under it."""
        own = {option: value for option, value in values.items()
               if option in self.explicit or value != self.underlying[option]}
        for parameter, _ in self.parameters:
            if parameter.value.repeat:
                # Repeated options append to the base; the field edits only the additions.
                added = (values[parameter.option] or [])[len(self.underlying[parameter.option] or ()):]
                if added:
                    own[parameter.option] = added
                else:
                    own.pop(parameter.option, None)
        return {**self.platform_values, **own}

    def preset_text(self, own):
        return HEADER + "\n" + patch_config.option_text(self.platform, own, self.base)

    def apply(self, own):
        """Shows own (the options this preset sets) over what applies under it."""
        self.loading = True
        for patch in self.platform.patches():
            self.enabled[patch.option].set(bool(own.get(patch.option, self.underlying[patch.option])))
        for parameter, _ in self.parameters:
            inherited = self.underlying[parameter.option]
            value = own.get(parameter.option, None if parameter.value.repeat else inherited)
            self.params[parameter.option].set(value_text(value, parameter.value))
            if parameter.value.repeat:
                self.inherited_labels[parameter.option].config(
                    text="Inherited: " + value_text(inherited, parameter.value) if inherited else "")
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
            "patch": self.built is not None and os.path.isfile(self.outfile.get().strip())
                     and self.built == self.build_key(),
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
        if self.loading:
            return
        for parameter, patch in self.parameters:
            self.param_widgets[parameter.option].state(
                ["!disabled"] if self.enabled[patch.option].get() else ["disabled"])
        values = self.shown()
        if values is None:
            self.cmdline.set("Invalid value: %s" % self.error)
            return
        own = self.own_values(values)
        for patch in self.platform.patches():
            self.checks[patch.option].config(style="Changed.Patch.TCheckbutton" if patch.option in own else "Patch.TCheckbutton")
        self.cmdline.set(shlex.join(patch_config.option_args(self.platform, own, self.base)))
        self.local_note.config(text="%s also applies under this preset: %s" % (
            self.local_file.name, shlex.join(self.local_options)) if self.local_options else "")
        self.title("%s - %s%s%s" % (TITLE, self.platform.name,
                   " - " + self.name if self.name else "", " *" if self.dirty() else ""))
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
        related = self.platform.patch(option).requires if on else self.required_by[option]
        for other in related:
            if self.enabled[other].get() != on:
                self.enabled[other].set(on)
                changed.append(other)
                self.follow(other, on, changed)

    def load_preset(self, name):
        """Load a user preset, or show the local configuration when no preset is selected."""
        self.loading = True
        self.name = name
        self.preset_box.config(values=user_presets(self.platform))
        self.preset_var.set(name)
        self.base_box.config(values=[NO_BASE] + [p for p in patch_config.preset_files(self.platform.name) if p != name])
        path = preset_path(self.platform, name)
        base, own, self.foreign = [], {}, False
        self.platform_values = {}
        try:
            if name and path.is_file():
                text = path.read_text(encoding="utf-8")
                self.foreign = not text.startswith(HEADER)
                base, options = patch_config.split_presets(patch_config.read_options(path))
                own = patch_config.layer_values(self.platform, patch_config.Layer("preset", path, tuple(base),
                                                                             tuple(options)))
                status = "Loaded %s" % path
            else:
                status = "New preset %s" % name if name else ""
            self.platform_values = {p.option: own[p.option] for p in self.platform.parameters if p.option in own}
            self.set_base(base)
        except (OSError, ValueError) as exc:
            messagebox.showerror(TITLE, "%s could not be read:\n\n%s\n\nThe built-in defaults are shown; Save "
                                 "replaces the preset." % (path, exc))
            self.base, own, self.foreign = [], {}, True
            self.platform_values = {}
            defaults = patch_config.options_parser(self.platform).parse_args([])
            self.underlying = {p.option: self.platform.selected(defaults, p) for p in self.platform.patches()}
            self.underlying.update((p.option, getattr(defaults, patch_options.dest(p.option)))
                                   for p, _ in self.parameters)
            self.sources, self.local_options = {}, ()
            status = "Could not read %s" % path.name
        own = {option: value for option, value in own.items()
               if option in self.options or option in self.platform_values}
        self.explicit = set(own)
        # an untouched new preset is not a change; one that could not be read always is
        self.saved_text = None if status.startswith("Could") else self.preset_text(own)
        self.status.config(text=status)
        self.apply(own)

    def switch_preset(self, name):
        name = name.strip()
        if name == self.name:
            return
        if name and not PRESET_NAME.match(name):
            messagebox.showerror(TITLE, PRESET_NAME_RULE[0].upper() + PRESET_NAME_RULE[1:])
            self.preset_var.set(self.name)
            return
        if not self.confirm_preset_change():
            self.preset_var.set(self.name)
            return
        self.load_preset(name)
        self.save_settings()

    def confirm_preset_change(self):
        if not self.dirty():
            return True
        question = "Save the changes to preset %s?" % self.name if self.name else "Save these options as a preset?"
        answer = messagebox.askyesnocancel(TITLE, question)
        return answer is not None and (not answer or self.save(self.name))

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
        previous = self.platform_values
        self.platform_values = {}
        try:
            self.set_base(self.base)
        except (OSError, ValueError) as exc:
            self.platform_values = previous
            messagebox.showerror(TITLE, str(exc))
            return
        self.explicit = set()
        self.apply({})
        self.status.config(text="Only the base preset shown; Save writes it")

    def save(self, name=None):
        """Writes the preset: its base presets and the options it sets itself. False when not saved."""
        name = (name or self.preset_var.get()).strip()
        if not name:
            name = simpledialog.askstring(TITLE, "Preset name:", initialvalue=DEFAULT_PRESET, parent=self)
            if name is None:
                return False
            name = name.strip()
        if not PRESET_NAME.match(name):
            messagebox.showerror(TITLE, "Not saved: " + PRESET_NAME_RULE)
            return False
        values = self.shown()
        if values is None:
            messagebox.showerror(TITLE, "Not saved:\n\n%s" % self.error)
            return False
        own = self.own_values(values)
        path = preset_path(self.platform, name)
        try:   # validate the whole configuration as the patcher will see it
            layer = patch_config.Layer("preset", path, tuple(self.base),
                                       tuple(patch_config.option_args(self.platform, own)))
            errors = self.platform.dependency_errors(
                patch_config.effective_args(self.platform, self.layers(self.base, name) + [layer]))
        except (OSError, ValueError) as exc:
            errors = [str(exc)]
        if errors:
            messagebox.showerror(TITLE, "Not saved:\n\n%s" % "\n".join(errors))
            return False
        if name in patch_config.preset_files(self.platform.name) and not path.is_file() and not messagebox.askyesno(
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
            self.preset_var.set(name)
            self.preset_box.config(values=user_presets(self.platform))
            self.base_box.config(values=[NO_BASE] + [p for p in patch_config.preset_files(self.platform.name)
                                                     if p != name])
            self.save_settings()
        self.foreign = False
        self.explicit = set(own)
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
        self.platform_settings[self.platform.name] = {
            "input": self.infile.get(), "flash_file": self.flash_file.get(),
            "backup": self.backup.get(), "preset": self.name,
        }
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({"platform": next(label for label, target in TARGETS.items() if target is self.target),
                           "platforms": self.platform_settings,
                           "verbose": self.verbose.get(), "ocd_interface": self.ocd_interface.get(),
                           "ocd_serial": self.ocd_serial.get()}, f, indent=2)
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
        """Build the current form selection, independently of preset saving."""
        infile = self.infile.get().strip()
        if not os.path.isfile(infile):
            messagebox.showerror(TITLE, "Choose the original firmware image to patch.")
            return
        if os.path.realpath(infile) == os.path.realpath(self.output):
            messagebox.showerror(TITLE, "%s is what make builds; choose the original firmware image." % self.target["output"])
            return
        if use_wsl() and not wsl_exe():
            messagebox.showerror(TITLE, "wsl.exe was not found. make runs in WSL on Windows; see "
                                 "docs/guide/wsl_setup.md.")
            return
        if not self.ensure_wsl_tools():
            return
        values = self.shown()
        if values is None:
            messagebox.showerror(TITLE, self.error)
            return
        options = patch_config.option_args(self.platform, values)
        errors = self.platform.dependency_errors(patch_config.options_parser(self.platform).parse_args(options))
        if errors:
            messagebox.showerror(TITLE, "Cannot build:\n\n" + "\n".join(errors))
            return
        self.save_settings()
        path = make_input(infile)
        if path is None:   # make cannot take the path (spaces, special characters): work from a copy
            copy_name = "airbreaker-%s-input.bin" % self.platform.name
            copy = os.path.join(REPO, "build", copy_name)
            try:
                os.makedirs(os.path.dirname(copy), exist_ok=True)
                # an unchanged copy keeps its time, so make does not rebuild the image for it
                if not (os.path.isfile(copy) and filecmp.cmp(infile, copy, shallow=False)):
                    shutil.copyfile(infile, copy)
            except OSError as exc:
                messagebox.showerror(TITLE, "Could not copy %s to %s: %s" % (infile, copy, exc))
                return
            self.append("make cannot take the path of %s; building from a copy, build/%s" % (infile, copy_name),
                        "warn")
            path = make_input(copy)
            if path is None:
                messagebox.showerror(TITLE, "WSL cannot reach the repository folder %s." % REPO)
                return
        command = make_command(self.target, path, options, self.verbose.get())
        self.pending = self.build_key(values)
        self.run("Building %s from %s%s" % (self.target["output"], infile,
                                             " (in WSL)" if use_wsl() else ""),
                 command, "%s built" % self.target["output"], kind="build")

    def build_key(self, values=None):
        values = self.shown() if values is None else values
        if values is None:
            return None
        return (self.platform.name, tuple(patch_config.option_args(self.platform, values)),
                file_id(self.infile.get().strip()))

    def ensure_wsl_tools(self):
        """False when WSL lacks make, the ARM toolchain or python3. Shows the command that installs them and, on a
        WSL distribution with apt-get, offers to run it in a console window, where sudo asks for the password.
        Nothing is installed without asking. Click the action again when it is done."""
        packages = wsl_missing_packages() if use_wsl() else []
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
                start_new_session=not use_wsl())   # its own process group, which stop() ends as a whole
        except OSError as exc:
            self.append("Could not start %s: %s" % (command[0], exc), "fail")
            return
        self.flashing = flashing
        self.platform_box.config(state="disabled")
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
            if use_wsl():
                stop_in_wsl()
                self.proc.terminate()
            else:   # make or run-ocd.sh and everything they started, such as the patcher or openocd
                try:
                    os.killpg(self.proc.pid, signal.SIGTERM)
                except OSError:
                    pass

    def tcl_path(self, path):
        """A file argument for the platform's Tcl commands: relative to the repo (OpenOCD runs there) when inside
        it, otherwise absolute, as a WSL path on Windows. Braced for Tcl. None, after telling the user, when
        WSL cannot reach the file."""
        path = os.path.realpath(path)
        try:
            rel = os.path.relpath(path, REPO)
        except ValueError:   # another drive
            rel = os.pardir
        if not rel.startswith(os.pardir):
            path = rel
        elif use_wsl():
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
        """Selected platform and adapter, followed by Tcl actions and shutdown."""
        args = ["bash", "run-ocd.sh", self.target["config"]]
        if self.ocd_interface.get():
            args += ["--interface", self.ocd_interface.get()]
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
        """Require a complete image for the selected platform before starting OpenOCD."""
        path = self.flash_file.get().strip()
        if not os.path.isfile(path):
            messagebox.showerror(TITLE, "Choose the firmware image (e.g. the patched output).")
            return None
        if os.path.getsize(path) != self.target["size"]:
            messagebox.showerror(TITLE, "Expected a complete %d MB %s firmware image." % (
                self.target["size"] // 0x100000, self.platform.name))
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
                TITLE, "Flash %s to the %s device?\n\nThis replaces the whole firmware. "
                "Keep the device and the programmer connected until the log says Done." % (path, self.platform.name),
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
        if self.adapter_names is not None:
            names, self.adapter_names = self.adapter_names, None
            self.adapters["values"] = names
            if names and self.ocd_interface.get() not in names:
                self.ocd_interface.set(names[0])
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
        self.platform_box.config(state="readonly")
        for button in self.action_buttons():
            button.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.update_steps()

    def on_close(self):
        if not self.confirm_preset_change():
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

