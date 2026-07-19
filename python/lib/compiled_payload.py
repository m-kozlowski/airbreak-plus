import os
import subprocess
import tempfile


class CompiledPayloadError(ValueError):
    pass


def _tool_output(args):
    try:
        return subprocess.check_output(
            args, stderr=subprocess.STDOUT, universal_newlines=True
        )
    except OSError as exc:
        raise CompiledPayloadError("failed to run %s: %s" % (args[0], exc))
    except subprocess.CalledProcessError as exc:
        detail = (exc.output or "").strip()
        if detail:
            raise CompiledPayloadError("%s failed: %s" % (args[0], detail))
        raise CompiledPayloadError("%s failed with exit status %d" % (args[0], exc.returncode))


def elf_symbol_address(path, symbol):
    """Return the linked address of one ELF symbol."""
    matches = []
    for line in _tool_output(["arm-none-eabi-nm", path]).splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[2] == symbol:
            matches.append(int(fields[0], 16))
    if len(matches) != 1:
        raise CompiledPayloadError(
            "expected one %s symbol in %s, found %d" %
            (symbol, path, len(matches))
        )
    return matches[0]


def elf_text_address(path):
    """Return the VMA of the ELF .text section."""
    matches = []
    for line in _tool_output(["arm-none-eabi-objdump", "-h", path]).splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[1] == ".text":
            matches.append(int(fields[3], 16))
    if len(matches) != 1:
        raise CompiledPayloadError(
            "expected one .text section in %s, found %d" % (path, len(matches))
        )
    return matches[0]


def elf_binary_data(path):
    """Return the flat binary produced from an ELF by the build toolchain."""
    tmp = tempfile.NamedTemporaryFile(prefix="airbreak-payload-", suffix=".bin", delete=False)
    tmp_path = tmp.name
    tmp.close()
    try:
        _tool_output(["arm-none-eabi-objcopy", "-O", "binary", path, tmp_path])
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


class CompiledPayloadMixin(object):
    """Generated-layout support shared by the Python firmware patchers."""

    PAYLOAD_LAYOUT_TEMPLATE = "payload_layout_%s.tsv"
    PAYLOAD_BUILD_COMMAND = "make binaries"

    def _init_compiled_payloads(self):
        self.payload_layout = None
        self.payload_layout_version = None

    def _payload_version_key(self):
        raise NotImplementedError

    def _payload_flash_range(self):
        raise NotImplementedError

    def _payload_repo_dir(self):
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _versioned_artifact_path(self, name, ext, ver=None):
        if ver is None:
            ver = self._payload_version_key()
        return os.path.join(
            self._payload_repo_dir(), "build", "%s_%s.%s" % (name, ver, ext)
        )

    def _load_versioned_bin(self, name, required=False):
        """Load a per-version binary, optionally failing when unavailable."""
        ver = self._payload_version_key()
        bin_path = self._versioned_artifact_path(name, "bin", ver)
        if not os.path.exists(bin_path):
            message = "%s: build/%s_%s.bin not found (run %s)" % (
                name, name, ver, self.PAYLOAD_BUILD_COMMAND
            )
            if required:
                raise CompiledPayloadError(message)
            print("  " + message)
            return None, ver
        with open(bin_path, "rb") as f:
            return f.read(), ver

    def _load_payload_layout(self):
        """Load generated payload addresses and measured sizes."""
        ver = self._payload_version_key()
        if self.payload_layout_version == ver:
            return

        path = os.path.join(
            self._payload_repo_dir(), "build", self.PAYLOAD_LAYOUT_TEMPLATE % ver
        )
        if not os.path.exists(path):
            raise CompiledPayloadError(
                "payload layout not found: %s (run %s)" %
                (os.path.relpath(path, self._payload_repo_dir()), self.PAYLOAD_BUILD_COMMAND)
            )

        range_start, range_end = self._payload_flash_range()
        layout = {}
        with open(path, "r", encoding="ascii") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                fields = line.split()
                if len(fields) != 4:
                    raise CompiledPayloadError(
                        "payload layout: malformed row %d in %s" % (lineno, path)
                    )
                name, flash_text, size_text, end_text = fields
                if name in layout:
                    raise CompiledPayloadError("payload layout: duplicate payload %s" % name)
                flash = int(flash_text, 0)
                size = int(size_text, 0)
                end = int(end_text, 0)
                if flash % 4 or size <= 0 or flash + size != end:
                    raise CompiledPayloadError("payload layout: invalid range for %s" % name)
                if flash < range_start or end > range_end:
                    raise CompiledPayloadError(
                        "payload layout: %s lies outside the payload region" % name
                    )
                layout[name] = (flash, size)

        self.payload_layout = layout
        self.payload_layout_version = ver

    def _elf_symbol_addr(self, elf_path, symbol):
        return elf_symbol_address(elf_path, symbol)

    def _inject_payload(self, name, data):
        """Validate and inject one payload at its generated layout address."""
        data = bytes(data)
        self._load_payload_layout()
        if name not in self.payload_layout:
            raise CompiledPayloadError(
                "payload layout: %s not allocated for %s" %
                (name, self._payload_version_key())
            )
        flash, expected_size = self.payload_layout[name]
        if len(data) != expected_size:
            raise CompiledPayloadError(
                "%s: binary size %dB differs from layout %dB (run %s)" %
                (name, len(data), expected_size, self.PAYLOAD_BUILD_COMMAND)
            )

        elf_path = self._versioned_artifact_path(name, "elf")
        if not os.path.exists(elf_path):
            raise CompiledPayloadError(
                "%s: %s not found (run %s)" %
                (name, os.path.relpath(elf_path, self._payload_repo_dir()),
                 self.PAYLOAD_BUILD_COMMAND)
            )
        linked_text = elf_text_address(elf_path)
        if linked_text != flash:
            raise CompiledPayloadError(
                "%s: ELF .text is linked at 0x%08X, layout assigns 0x%08X "
                "(run %s)" %
                (name, linked_text, flash, self.PAYLOAD_BUILD_COMMAND)
            )
        if elf_binary_data(elf_path) != data:
            raise CompiledPayloadError(
                "%s: binary does not match %s (run %s)" %
                (name, os.path.basename(elf_path), self.PAYLOAD_BUILD_COMMAND)
            )

        off = flash - self.asf.FLASH_BASE
        self.asf.patch(data, off, checkempty=True, verbose=False)
        return flash, off
