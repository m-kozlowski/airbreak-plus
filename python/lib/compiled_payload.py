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


def elf_symbol_size(path, symbol):
    """Return the linked size of one ELF symbol."""
    matches = []
    for line in _tool_output(["arm-none-eabi-nm", "-S", path]).splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[3] == symbol:
            matches.append(int(fields[1], 16))
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
    PAYLOAD_CAVES_FILE = None

    def _init_compiled_payloads(self):
        self.payload_layouts = {}
        self.applied_payloads = set()
        self.written_payload_slots = set()

    def _payload_version_key(self, region=None):
        raise NotImplementedError

    def _payload_layout_template(self, region=None):
        return self.PAYLOAD_LAYOUT_TEMPLATE

    def _payload_flash_range(self, region=None):
        raise NotImplementedError

    def _payload_repo_dir(self):
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _versioned_artifact_path(self, name, ext, ver=None):
        if ver is None:
            ver = self._payload_version_key()
        return os.path.join(
            self._payload_repo_dir(), "build", "%s_%s.%s" % (name, ver, ext)
        )

    def _require_versioned_artifact(self, name, ext, ver=None):
        """Return one versioned build artifact or fail with a build hint."""
        path = self._versioned_artifact_path(name, ext, ver)
        if not os.path.exists(path):
            raise CompiledPayloadError(
                "%s: %s not found (run %s)" %
                (name, os.path.relpath(path, self._payload_repo_dir()),
                 self.PAYLOAD_BUILD_COMMAND)
            )
        return path

    def _load_versioned_bin(self, name, region=None):
        """Load a per-version binary or fail with a build hint."""
        ver = self._payload_version_key(region)
        bin_path = self._require_versioned_artifact(name, "bin", ver)
        with open(bin_path, "rb") as f:
            return f.read(), ver

    def _load_versioned_payload(self, name, region=None):
        """Load a payload binary and require its matching ELF metadata."""
        data, ver = self._load_versioned_bin(name, region=region)
        elf_path = self._require_versioned_artifact(name, "elf", ver)
        return data, ver, elf_path

    def _read_payload_layout(self, template, ver, storage_range):
        """Read one generated layout with separate storage and runtime addresses."""
        path = os.path.join(
            self._payload_repo_dir(), "build", template % ver
        )
        if not os.path.exists(path):
            raise CompiledPayloadError(
                "payload layout not found: %s (run %s)" %
                (os.path.relpath(path, self._payload_repo_dir()), self.PAYLOAD_BUILD_COMMAND)
            )

        range_start, range_end = storage_range
        layout = {}
        with open(path, "r", encoding="ascii") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                fields = line.split()
                if len(fields) != 6:
                    raise CompiledPayloadError(
                        "payload layout: malformed row %d in %s" % (lineno, path)
                    )
                (name, runtime_text, size_text, runtime_end_text,
                 storage_text, storage_end_text) = fields
                if name in layout:
                    raise CompiledPayloadError("payload layout: duplicate payload %s" % name)
                runtime = int(runtime_text, 0)
                size = int(size_text, 0)
                runtime_end = int(runtime_end_text, 0)
                storage = int(storage_text, 0)
                storage_end = int(storage_end_text, 0)
                if (runtime % 4 or storage % 4 or size <= 0 or
                        runtime + size != runtime_end or
                        storage + size != storage_end):
                    raise CompiledPayloadError("payload layout: invalid range for %s" % name)
                if storage < range_start or storage_end > range_end:
                    raise CompiledPayloadError(
                        "payload layout: %s lies outside the payload region" % name
                    )
                layout[name] = {
                    "runtime": runtime,
                    "storage": storage,
                    "size": size,
                }
        return layout

    def _load_payload_layout(self, region=None):
        """Load generated payload addresses and measured sizes."""
        ver = self._payload_version_key(region)
        template = self._payload_layout_template(region)
        storage_range = self._payload_flash_range(region)
        key = (template, ver, storage_range)
        if key not in self.payload_layouts:
            self.payload_layouts[key] = self._read_payload_layout(
                template, ver, storage_range
            )
        return ver, self.payload_layouts[key]

    def _elf_symbol_addr(self, elf_path, symbol):
        return elf_symbol_address(elf_path, symbol)

    def _elf_symbol_size(self, elf_path, symbol):
        return elf_symbol_size(elf_path, symbol)

    def _validate_payload(self, name, data, region=None, empty_byte=0xff, abi=None):
        """Check a payload and ABI values; return storage, offset and final bytes."""
        data = bytes(data)
        ver, layout = self._load_payload_layout(region)
        if name not in layout:
            raise CompiledPayloadError(
                "payload layout: %s not allocated for %s" %
                (name, ver)
            )
        entry = layout[name]
        runtime = entry["runtime"]
        storage = entry["storage"]
        expected_size = entry["size"]
        if self.PAYLOAD_CAVES_FILE:
            # Check the stored/executed mapping against the allocator's source
            # table, rather than repeating firmware addresses in each patch.
            path = os.path.join(self._payload_repo_dir(), self.PAYLOAD_CAVES_FILE)
            with open(path, "r", encoding="ascii") as caves:
                for line in caves:
                    fields = line.split()
                    if not fields or fields[0] != ver:
                        continue
                    if len(fields) != 7:
                        raise CompiledPayloadError("malformed code cave in %s" % path)
                    begin, end, image_base, runtime_base = (int(x, 0) for x in fields[2:6])
                    if (begin <= storage and storage + expected_size <= end and
                            runtime == runtime_base + storage - image_base):
                        break
                else:
                    raise CompiledPayloadError(
                        "%s: layout is outside the code caves or has an invalid runtime mapping" % name)
        if len(data) != expected_size:
            raise CompiledPayloadError(
                "%s: binary size %dB differs from layout %dB (run %s)" %
                (name, len(data), expected_size, self.PAYLOAD_BUILD_COMMAND)
            )

        # Validate the execution address, then install the bytes at their
        # storage address. These differ for payloads copied into SRAM.
        elf_path = self._require_versioned_artifact(name, "elf", ver)
        linked_text = elf_text_address(elf_path)
        if linked_text != runtime:
            raise CompiledPayloadError(
                "%s: ELF .text is linked at 0x%08X, layout assigns 0x%08X "
                "(run %s)" %
                (name, linked_text, runtime, self.PAYLOAD_BUILD_COMMAND)
            )
        if elf_binary_data(elf_path) != data:
            raise CompiledPayloadError(
                "%s: binary does not match %s (run %s)" %
                (name, os.path.basename(elf_path), self.PAYLOAD_BUILD_COMMAND)
            )

        if abi:
            prepared = bytearray(data)
            for symbol, value in abi.items():
                slot = elf_symbol_address(elf_path, symbol) - runtime
                size = elf_symbol_size(elf_path, symbol)
                if len(value) != size or slot < 0 or slot + size > len(data):
                    raise CompiledPayloadError("%s: invalid ABI slot %s" % (name, symbol))
                prepared[slot:slot + size] = value
            data = bytes(prepared)
        off = storage - self.asf.FLASH_BASE
        if bytes(self.asf.fw[off:off + len(data)]) != data:
            if bytes(self.asf.fw[off:off + len(data)]) != bytes([empty_byte]) * len(data):
                raise CompiledPayloadError(
                    "%s: payload area at 0x%08X is not empty" % (name, storage))
        return storage, off, data

    def _inject_payload(self, name, data, region=None, empty_byte=0xff, abi=None):
        """Validate and inject one payload at its generated layout address."""
        data = bytes(data)
        storage, off, data = self._validate_payload(name, data, region, empty_byte, abi)
        if bytes(self.asf.fw[off:off + len(data)]) != bytes(data):
            self.asf.patch(data, off, checkempty=empty_byte == 0xff,
                           clobber=empty_byte != 0xff, verbose=False)
        self.applied_payloads.add(name)
        return storage, off

    def _write_payload_u16(self, payload, symbol, value):
        """Write one u16 ABI value at a named symbol of an applied payload; return its address."""
        if payload not in self.applied_payloads:
            raise ValueError("payload %s was not applied" % payload)
        if (payload, symbol) in self.written_payload_slots:
            raise ValueError("payload slot %s:%s written twice" % (payload, symbol))
        self.written_payload_slots.add((payload, symbol))
        elf_path = self._require_versioned_artifact(payload, "elf")
        address = self._elf_symbol_addr(elf_path, symbol)
        self.asf.write_u16(address - self.asf.FLASH_BASE, value)
        return address
