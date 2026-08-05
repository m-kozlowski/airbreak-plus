# stm32-unlocked.bin: patch-airsense
# 	./patch-airsense stm32.bin $@

SRC=patches
BUILD=build
PATCH_STUBS=$(SRC)/stubs
MAKE_LOG ?= make.log

PATCHER_OUTPUT_ARGS := --log-file $(abspath $(MAKE_LOG))
ifeq ($(V),1)
PATCHER_OUTPUT_ARGS += --verbose
endif

# Use all cores unless the caller selected -j, and keep output lines intact.
JOBS ?= $(shell nproc)
ifeq ($(MAKELEVEL),0)
ifeq ($(filter -j%,$(MAKEFLAGS)),)
MAKEFLAGS += -j$(JOBS)
endif
endif

# Print compact build steps by default. Use `make V=1` for full commands.
ifneq ($(V),1)
.SILENT:
endif

PAYLOAD_LAYOUT_VERSIONS := 0302 0305 0306 0401 0402
PAYLOADS_0302 := mop_callback_dispatcher vid_spoof graph squarewave asv_task_wrapper \
	common_code backlight_adapt wrapper_limit_max_pdiff s10_lcd_ili9325 custom_menu_hooks
PAYLOADS_0305 := $(PAYLOADS_0302)
PAYLOADS_0306 := $(PAYLOADS_0302)
PAYLOADS_0401 := mop_callback_dispatcher vid_spoof graph squarewave asv_task_wrapper \
	common_code backlight_adapt wrapper_limit_max_pdiff s10_lcd_ili9325 custom_menu_hooks
PAYLOADS_0402 := $(PAYLOADS_0401)

payload_versions = $(foreach v,$(PAYLOAD_LAYOUT_VERSIONS),$(if $(filter $(1),$(PAYLOADS_$(v))),$(v)))
payload_bins = $(foreach v,$(call payload_versions,$(1)),$(BUILD)/$(1)_$(v).bin)

PAYLOAD_NAMES := $(sort $(foreach v,$(PAYLOAD_LAYOUT_VERSIONS),$(PAYLOADS_$(v))))
PAYLOAD_STAMPS := $(foreach p,$(PAYLOAD_NAMES),$(BUILD)/payload_$(p).stamp)
S10_CODE_VERSIONS := $(call payload_versions,common_code)
S10_STANDALONE_PAYLOADS := asv_task_wrapper backlight_adapt vid_spoof
PAYLOAD_LAYOUT_TSVS := $(foreach v,$(PAYLOAD_LAYOUT_VERSIONS),$(BUILD)/payload_layout_$(v).tsv)

# SX577-0200 BLX is relocated to SRAM and has one fixed, zero-filled code cave.
BLX_DUMP_RUNTIME := 0x20003AE0
BLX_DUMP_BIN := $(BUILD)/blx_dump.bin
PAYLOAD_TARGETS := $(PAYLOAD_STAMPS) $(PAYLOAD_LAYOUT_TSVS) $(BLX_DUMP_BIN)

BUILD_VARIANTS = \
	$(BUILD)/stm32-patched.bin \
	$(BUILD)/stm32-graph.bin \
	$(BUILD)/stm32-asv-plus.bin \
	$(BUILD)/stm32-asv-plus_no-squarewave.bin \
	$(BUILD)/stm32-asv-plus_with-backup.bin

# Rebuild firmware when the patcher or its helpers change
S10_PATCHER_DEPS := \
	patch-airsense \
	python/patch-airsense.py \
	python/edf_ccx_merge.py \
	python/lib/compiled_payload.py

# Payloads build in parallel; firmware patchers run serially for streaming output.
.PHONY: all binaries
all:
	@: > '$(MAKE_LOG)'
	@if $(MAKE) --no-print-directory -q $(PAYLOAD_TARGETS); then \
		:; \
	else \
		status=$$?; \
		[ "$$status" -eq 1 ] || exit "$$status"; \
		printf 'Building payloads\n'; \
		$(MAKE) --no-print-directory binaries; \
	fi
	set -e; for image in $(BUILD_VARIANTS); do \
		$(MAKE) --no-print-directory "$$image"; \
	done
	@{ \
		printf '\nFirmware images:\n'; \
		for image in $(BUILD_VARIANTS); do printf '  %s\n' "$$image"; done; \
	} | tee -a '$(MAKE_LOG)'

define announce_image
	@if [ '$(MAKELEVEL)' -eq 0 ]; then : > '$(MAKE_LOG)'; fi; \
	printf '\nBuilding image: %s\n' '$@'; \
	printf '\nBuilding image: %s\n' '$@' >> '$(MAKE_LOG)'
endef

$(BUILD):
	mkdir -p $(BUILD)

# unlocked stock-ish
$(BUILD)/stm32-patched.bin: $(S10_PATCHER_DEPS) $(PAYLOAD_STAMPS) $(PAYLOAD_LAYOUT_TSVS) $(BLX_DUMP_BIN)
	$(announce_image)
	./patch-airsense stm32.bin $@ $(PATCHER_OUTPUT_ARGS)

# graph overlay injected
$(BUILD)/stm32-graph.bin: $(S10_PATCHER_DEPS) $(PAYLOAD_STAMPS) $(PAYLOAD_LAYOUT_TSVS) $(BLX_DUMP_BIN)
	$(announce_image)
	PATCH_CODE=1 ./patch-airsense stm32.bin $@ $(PATCHER_OUTPUT_ARGS)

# Custom ASV algorithm in VAuto slot + ASV backup-rate suppression + squarewave mode
$(BUILD)/stm32-asv-plus.bin: $(S10_PATCHER_DEPS) $(PAYLOAD_STAMPS) $(PAYLOAD_LAYOUT_TSVS) $(BLX_DUMP_BIN)
	$(announce_image)
	PATCH_CODE=1 PATCH_ASV_TASK_WRAPPER=1 PATCH_VAUTO_WRAPPER=1 PATCH_S=1 ./patch-airsense stm32.bin $@ $(PATCHER_OUTPUT_ARGS)

# Custom ASV in VAuto slot + backup-rate suppression, no squarewave
$(BUILD)/stm32-asv-plus_no-squarewave.bin: $(S10_PATCHER_DEPS) $(PAYLOAD_STAMPS) $(PAYLOAD_LAYOUT_TSVS) $(BLX_DUMP_BIN)
	$(announce_image)
	PATCH_CODE=1 PATCH_ASV_TASK_WRAPPER=1 PATCH_VAUTO_WRAPPER=1 ./patch-airsense stm32.bin $@ $(PATCHER_OUTPUT_ARGS)

# Custom ASV in VAuto slot + squarewave, stock ASV backup-rate preserved
$(BUILD)/stm32-asv-plus_with-backup.bin: $(S10_PATCHER_DEPS) $(PAYLOAD_STAMPS) $(PAYLOAD_LAYOUT_TSVS) $(BLX_DUMP_BIN)
	$(announce_image)
	PATCH_CODE=1 PATCH_VAUTO_WRAPPER=1 PATCH_S=1 ./patch-airsense stm32.bin $@ $(PATCHER_OUTPUT_ARGS)

binaries: $(PAYLOAD_TARGETS)

$(BUILD)/blx_dump.o: $(SRC)/blx_dump.c | $(BUILD)
	$(CC) $(CFLAGS) -mno-unaligned-access -c -o $@ $<

$(BUILD)/blx_dump_stubs.o: $(SRC)/blx_dump_stubs.S | $(BUILD)
	$(AS) $(ASFLAGS) -c -o $@ $<

$(BUILD)/blx_dump.elf: $(BUILD)/blx_dump.o $(BUILD)/blx_dump_stubs.o | $(BUILD)
	$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $(BLX_DUMP_RUNTIME) --entry start --sort-section=name \
		-o $@ $^

$(BUILD)/blx_dump.bin: $(BUILD)/blx_dump.elf
	$(OBJCOPY) -Obinary $< $@
	@size=$$(stat -c %s $@); [ $$size -le 416 ] || { \
		echo "$@: payload is $${size}B, BLX cave is 416B" >&2; exit 1; }
	@printf '  %-8s %-30s [%s]\n' PAYLOAD blx_dump SX577-0200

define PAYLOAD_STAMP_template
$(BUILD)/payload_$(1).stamp: $(call payload_bins,$(1)) Makefile | $(BUILD)
	@printf '  %-8s %-30s [%s]\n' PAYLOAD $(1) '$(call payload_versions,$(1))'
	@touch $$@
endef

$(foreach p,$(PAYLOAD_NAMES),$(eval $(call PAYLOAD_STAMP_template,$(p))))


# Per-version S10 code patches
# Each version has its own stubs.S with platform-specific addresses.
# Binaries are built per-version: common_code_0401.bin, graph_0402.bin, etc.

PROBE_LINK_ADDR := 0x08000000

define PAYLOAD_LAYOUT_template
PAYLOAD_PROBE_BINS_$(1) := $$(foreach p,$$(PAYLOADS_$(1)),$$(BUILD)/$$(p)_$(1).probe.bin)

$$(BUILD)/payload_sizes_$(1).tsv: $$(PAYLOAD_PROBE_BINS_$(1)) Makefile | $$(BUILD)
	@rm -f $$@.tmp
	@for bin in $$(filter %.probe.bin,$$^); do \
		base=$$$${bin##*/}; \
		name=$$$${base%.probe.bin}; \
		name=$$$${name%_$(1)}; \
		printf '%s\t%s\n' "$$$$name" "$$$$(stat -c %s "$$$$bin")" >> $$@.tmp; \
	done
	@mv $$@.tmp $$@

$$(BUILD)/payload_layout_$(1).tsv: \
		$$(BUILD)/payload_sizes_$(1).tsv $$(SRC)/s10_code_caves.tsv \
		$$(SRC)/generate_payload_layout.awk | $$(BUILD)
	@awk -v version=$(1) \
		-f $$(SRC)/generate_payload_layout.awk \
		$$(SRC)/s10_code_caves.tsv $$(BUILD)/payload_sizes_$(1).tsv \
		> $$(BUILD)/payload_layout_$(1).tsv.tmp
	@mv $$(BUILD)/payload_layout_$(1).tsv.tmp $$(BUILD)/payload_layout_$(1).tsv
endef

$(foreach v,$(PAYLOAD_LAYOUT_VERSIONS),$(eval $(call PAYLOAD_LAYOUT_template,$(v))))

$(BUILD)/s10_%_stubs.o: $(SRC)/s10_%_stubs.S | $(BUILD)
	$(AS) $(ASFLAGS) -c -o $@ $<

define S10_VERSIONED_OBJECTS_template
$(BUILD)/%_$(1).o: $(SRC)/%.c $(SRC)/common_code.h $(SRC)/s10_vars.h $(SRC)/s10_vars_$(1).h | $(BUILD)
	$$(CC) $$(CFLAGS) -DCDX_VER_$(1) -c -o $$@ $$<

$(BUILD)/%_$(1).o: $(SRC)/%.S $(SRC)/s10_vars.h $(SRC)/s10_vars_$(1).h | $(BUILD)
	$$(AS) $$(ASFLAGS) -DCDX_VER_$(1) -c -o $$@ $$<
endef

$(foreach v,$(PAYLOAD_LAYOUT_VERSIONS),$(eval $(call S10_VERSIONED_OBJECTS_template,$(v))))

define S10_CODE_VERSION_template

# common_code provides shared symbols and has no executable entry point.
$(BUILD)/common_code_$(1).probe.elf: $(BUILD)/common_code_$(1).o $(BUILD)/s10_$(1)_stubs.o | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $(PROBE_LINK_ADDR) --entry 0 --sort-section=name \
		-o $$@ $$^

$(BUILD)/graph_$(1).probe.elf: $(BUILD)/graph_$(1).o $(BUILD)/graph_abi_$(1).o $(BUILD)/s10_$(1)_stubs.o $(BUILD)/common_code_$(1).probe.elf | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $(PROBE_LINK_ADDR) \
		--just-symbols=$$(BUILD)/common_code_$(1).probe.elf \
		--entry start --sort-section=name -o $$@ $(BUILD)/graph_$(1).o $(BUILD)/graph_abi_$(1).o $(BUILD)/s10_$(1)_stubs.o

$(BUILD)/squarewave_$(1).probe.elf: $(BUILD)/squarewave_$(1).o $(BUILD)/squarewave_abi_$(1).o $(BUILD)/s10_$(1)_stubs.o $(BUILD)/common_code_$(1).probe.elf | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $(PROBE_LINK_ADDR) \
		--just-symbols=$$(BUILD)/common_code_$(1).probe.elf \
		--entry start --sort-section=name -o $$@ $(BUILD)/squarewave_$(1).o $(BUILD)/squarewave_abi_$(1).o $(BUILD)/s10_$(1)_stubs.o

$(BUILD)/wrapper_limit_max_pdiff_$(1).probe.elf: $(BUILD)/wrapper_limit_max_pdiff_$(1).o $(BUILD)/wrapper_limit_max_pdiff_abi_$(1).o $(BUILD)/s10_$(1)_stubs.o $(BUILD)/common_code_$(1).probe.elf | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $(PROBE_LINK_ADDR) \
		--just-symbols=$$(BUILD)/common_code_$(1).probe.elf \
		--entry start --sort-section=name -o $$@ $(BUILD)/wrapper_limit_max_pdiff_$(1).o $(BUILD)/wrapper_limit_max_pdiff_abi_$(1).o $(BUILD)/s10_$(1)_stubs.o

$(BUILD)/custom_menu_hooks_$(1).probe.elf: $(BUILD)/custom_menu_hooks_entry_$(1).o $(BUILD)/custom_menu_hooks_$(1).o $(BUILD)/s10_$(1)_stubs.o | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $(PROBE_LINK_ADDR) \
		--entry custom_menu_hook_therapy -o $$@ $$^

$(BUILD)/common_code_$(1).elf: $(BUILD)/common_code_$(1).o $(BUILD)/s10_$(1)_stubs.o $(BUILD)/payload_layout_$(1).tsv | $(BUILD)
	@set -e; addr=$$$$(awk -v name=common_code '$$$$1 == name { print $$$$2; found=1; exit } END { if (!found) exit 1 }' $(BUILD)/payload_layout_$(1).tsv); \
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $$$$addr --entry 0 --sort-section=name \
		-o $$@ $(BUILD)/common_code_$(1).o $(BUILD)/s10_$(1)_stubs.o

$(BUILD)/graph_$(1).elf: $(BUILD)/graph_$(1).o $(BUILD)/graph_abi_$(1).o $(BUILD)/s10_$(1)_stubs.o $(BUILD)/common_code_$(1).elf $(BUILD)/payload_layout_$(1).tsv | $(BUILD)
	@set -e; addr=$$$$(awk -v name=graph '$$$$1 == name { print $$$$2; found=1; exit } END { if (!found) exit 1 }' $(BUILD)/payload_layout_$(1).tsv); \
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $$$$addr \
		--just-symbols=$$(BUILD)/common_code_$(1).elf \
		--entry start --sort-section=name -o $$@ $(BUILD)/graph_$(1).o $(BUILD)/graph_abi_$(1).o $(BUILD)/s10_$(1)_stubs.o

$(BUILD)/squarewave_$(1).elf: $(BUILD)/squarewave_$(1).o $(BUILD)/squarewave_abi_$(1).o $(BUILD)/s10_$(1)_stubs.o $(BUILD)/common_code_$(1).elf $(BUILD)/payload_layout_$(1).tsv | $(BUILD)
	@set -e; addr=$$$$(awk -v name=squarewave '$$$$1 == name { print $$$$2; found=1; exit } END { if (!found) exit 1 }' $(BUILD)/payload_layout_$(1).tsv); \
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $$$$addr \
		--just-symbols=$$(BUILD)/common_code_$(1).elf \
		--entry start --sort-section=name -o $$@ $(BUILD)/squarewave_$(1).o $(BUILD)/squarewave_abi_$(1).o $(BUILD)/s10_$(1)_stubs.o

$(BUILD)/wrapper_limit_max_pdiff_$(1).elf: $(BUILD)/wrapper_limit_max_pdiff_$(1).o $(BUILD)/wrapper_limit_max_pdiff_abi_$(1).o $(BUILD)/s10_$(1)_stubs.o $(BUILD)/common_code_$(1).elf $(BUILD)/payload_layout_$(1).tsv | $(BUILD)
	@set -e; addr=$$$$(awk -v name=wrapper_limit_max_pdiff '$$$$1 == name { print $$$$2; found=1; exit } END { if (!found) exit 1 }' $(BUILD)/payload_layout_$(1).tsv); \
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $$$$addr \
		--just-symbols=$$(BUILD)/common_code_$(1).elf \
		--entry start --sort-section=name -o $$@ $(BUILD)/wrapper_limit_max_pdiff_$(1).o $(BUILD)/wrapper_limit_max_pdiff_abi_$(1).o $(BUILD)/s10_$(1)_stubs.o

$(BUILD)/custom_menu_hooks_$(1).elf: $(BUILD)/custom_menu_hooks_entry_$(1).o $(BUILD)/custom_menu_hooks_$(1).o $(BUILD)/s10_$(1)_stubs.o $(BUILD)/payload_layout_$(1).tsv | $(BUILD)
	@set -e; addr=$$$$(awk -v name=custom_menu_hooks '$$$$1 == name { print $$$$2; found=1; exit } END { if (!found) exit 1 }' $(BUILD)/payload_layout_$(1).tsv); \
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $$$$addr \
		--entry custom_menu_hook_therapy -o $$@ $(BUILD)/custom_menu_hooks_entry_$(1).o $(BUILD)/custom_menu_hooks_$(1).o $(BUILD)/s10_$(1)_stubs.o

endef

$(foreach v,$(S10_CODE_VERSIONS),$(eval $(call S10_CODE_VERSION_template,$(v))))

define S10_STANDALONE_PAYLOAD_template
$(BUILD)/$(1)_$(2).probe.elf: $(BUILD)/$(1)_$(2).o $(if $(wildcard $(SRC)/$(1)_abi.S),$(BUILD)/$(1)_abi_$(2).o) $(BUILD)/s10_$(2)_stubs.o | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $(PROBE_LINK_ADDR) --entry start --sort-section=name \
		-o $$@ $$^

$(BUILD)/$(1)_$(2).elf: $(BUILD)/$(1)_$(2).o $(if $(wildcard $(SRC)/$(1)_abi.S),$(BUILD)/$(1)_abi_$(2).o) $(BUILD)/s10_$(2)_stubs.o $(BUILD)/payload_layout_$(2).tsv | $(BUILD)
	@set -e; addr=$$$$(awk -v name=$(1) '$$$$1 == name { print $$$$2; found=1; exit } END { if (!found) exit 1 }' $(BUILD)/payload_layout_$(2).tsv); \
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $$$$addr --entry start --sort-section=name \
		-o $$@ $(BUILD)/$(1)_$(2).o $(if $(wildcard $(SRC)/$(1)_abi.S),$(BUILD)/$(1)_abi_$(2).o) $(BUILD)/s10_$(2)_stubs.o
endef

$(foreach p,$(S10_STANDALONE_PAYLOADS),\
	$(foreach v,$(call payload_versions,$(p)),\
		$(eval $(call S10_STANDALONE_PAYLOAD_template,$(p),$(v)))))



CROSS ?= arm-none-eabi-
CC := $(CROSS)gcc
AS := $(CC)
LD := $(CROSS)ld
OBJCOPY := $(CROSS)objcopy

CFLAGS ?= \
	-g \
	-Os \
	-mcpu=cortex-m4 \
	-mhard-float \
	-mfp16-format=ieee \
	-mthumb \
	-W \
	-Wall \
	-Wno-unused-result \
	-Wno-unused-parameter \
	-Wno-unused-variable \
	-nostdlib \
	-nostdinc \
	-ffreestanding \

ASFLAGS ?= $(CFLAGS)

LDFLAGS ?= \
	--nostdlib \
	--no-dynamic-linker \
	--Ttext $($*-offset) \
	$($*-extra) \
	--entry start \
	--sort-section=name \


# $(BUILD)/shared_code.o: $(BUILD)/shared_code.c
# 	$(CC) $(CFLAGS) -static -shared -c -o $@ $<
$(BUILD)/%.o: $(SRC)/%.c | $(BUILD)
	$(CC) $(CFLAGS) -c -o $@ $<
$(BUILD)/%.o: $(SRC)/%.S | $(BUILD)
	$(AS) $(ASFLAGS) -c -o $@ $<
$(BUILD)/%.elf: | $(BUILD)
	$(LD) $(LDFLAGS) -o $@ $^

$(BUILD)/%.bin: $(BUILD)/%.elf
	$(OBJCOPY) -Obinary $< $@
	@set -e; stem='$*'; ver=$${stem##*_}; payload=$${stem%_*}; \
		layout=$(BUILD)/payload_layout_$$ver.tsv; \
		if [ -f "$$layout" ]; then \
			expected=$$(awk -v name="$$payload" '$$1 == name { print $$3; found=1; exit } END { if (!found) exit 1 }' "$$layout") || { \
				echo "$@: no payload row for $$payload in $$layout" >&2; \
				exit 1; \
			}; \
			actual=$$(stat -c %s "$@"); \
			[ "$$actual" -eq "$$expected" ] || { \
				echo "$@: final size $$actual differs from layout size $$expected" >&2; \
				exit 1; \
			}; \
		fi


# eeprom_stub - standalone CDX replacement for s10 platform
#
# Build: make eeprom_stub
# Output: build/eeprom_stub_nocrc.bin (raw, for patched bootloader)
#         build/eeprom_stub_full.bin  (768KB + CRC, for stock bootloader)

EEPROM_STUB_OFFSET ?= 0x08040000

EEPROM_STUB_SRC := $(PATCH_STUBS)/eeprom_stub.c
EEPROM_STUB_OBJS := $(BUILD)/eeprom_stub.o

$(BUILD)/eeprom_stub.o: $(EEPROM_STUB_SRC) $(PATCH_STUBS)/eeprom_stub.h | $(BUILD)
	$(CC) $(CFLAGS) -c -o $@ $<

# The stub uses its own linker script
$(BUILD)/eeprom_stub.elf: $(EEPROM_STUB_OBJS) $(PATCH_STUBS)/eeprom_stub.ld | $(BUILD)
	$(LD) --nostdlib \
		-T $(PATCH_STUBS)/eeprom_stub.ld \
		--defsym=STUB_FLASH_ORIGIN=$(EEPROM_STUB_OFFSET) \
		-o $@ $(EEPROM_STUB_OBJS)

$(BUILD)/eeprom_stub_nocrc.bin: $(BUILD)/eeprom_stub.elf
	$(OBJCOPY) -Obinary $< $@

eeprom_stub: $(BUILD)/eeprom_stub_nocrc.bin $(BUILD)/eeprom_stub_full.bin
	@echo "EEPROM stub built:"
	@echo "  $(BUILD)/eeprom_stub_nocrc.bin  (raw, for patched bootloader)"
	@echo "  $(BUILD)/eeprom_stub_full.bin   (768KB + CRC, for stock bootloader)"
	@$(CROSS)size $(BUILD)/eeprom_stub.elf

# Full CDX image: pad to region size, fix CRC16 for bootloader validation
$(BUILD)/eeprom_stub_full.bin: $(BUILD)/eeprom_stub_nocrc.bin
	@python3 python/fix_crc.py $< -o $@ --pad 0xC0000


# S9 LCD patch - ILI9225 driver for SX474-09xx boards
#
# Build: make s9_lcd_ili9225
# Usage: PATCH_S9_LCD=1 ./patch-airsense-s9 stm32-s9.bin output.bin
#
# S9 is STM32F103 (Cortex-M3), different flags from S10 (Cortex-M4)
# One binary per CDX version (stub addresses differ)

S9_CFLAGS := -Os -mcpu=cortex-m3 -mthumb \
	-W -Wall -Wno-unused-variable \
	-nostdlib -nostdinc -ffreestanding

S9_LCD_OFFSET := 0x080d8000
S9_VERSIONS := 1201 1203 1301

$(BUILD)/s9_lcd_ili9225.o: $(SRC)/s9_lcd_ili9225.c | $(BUILD)
	$(CC) $(S9_CFLAGS) -c -o $@ $<

# Generate per-version stubs + link + objcopy rules
define S9_LCD_VERSION_template
$(BUILD)/s9_$(1)_stubs.o: $(SRC)/s9_$(1)_stubs.S | $(BUILD)
	$$(CC) $$(S9_CFLAGS) -c -o $$@ $$<

$(BUILD)/s9_lcd_ili9225_$(1).elf: $(BUILD)/s9_lcd_ili9225.o $(BUILD)/s9_$(1)_stubs.o | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $$(S9_LCD_OFFSET) --entry ili9225_lcd_init --sort-section=name \
		-o $$@ $$^

$(BUILD)/s9_lcd_ili9225_$(1).bin: $(BUILD)/s9_lcd_ili9225_$(1).elf
	$$(OBJCOPY) -Obinary $$< $$@
endef

$(foreach v,$(S9_VERSIONS),$(eval $(call S9_LCD_VERSION_template,$(v))))

s9_lcd_ili9225: $(foreach v,$(S9_VERSIONS),$(BUILD)/s9_lcd_ili9225_$(v).bin)
	@echo "S9 LCD patches built:"
	@$(foreach v,$(S9_VERSIONS),echo "  $(BUILD)/s9_lcd_ili9225_$(v).bin";)

s9: $(BUILD)/stm32-s9.bin

s9_lcd: $(BUILD)/stm32-s9-lcd.bin

$(BUILD)/stm32-s9.bin: patch-airsense-s9 | $(BUILD)
	./patch-airsense-s9 stm32-s9.bin $@

$(BUILD)/stm32-s9-lcd.bin: patch-airsense-s9 s9_lcd_ili9225 | $(BUILD)
	PATCH_S9_LCD=1 ./patch-airsense-s9 stm32-s9.bin $@


# S10 LCD patch - ILI9325/ILI9328 driver for AirSense 10
#
# Build: make s10_lcd_ili9325
# Usage: PATCH_S10_LCD=1 ./patch-airsense stm32.bin output.bin

define S10_LCD_VERSION_template
$(BUILD)/s10_lcd_ili9325_$(1).probe.elf: $(BUILD)/s10_lcd_ili9325_$(1).o $(BUILD)/s10_$(1)_stubs.o | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $(PROBE_LINK_ADDR) --entry lcd_board_init --sort-section=name \
		-o $$@ $$^

$(BUILD)/s10_lcd_ili9325_$(1).elf: $(BUILD)/s10_lcd_ili9325_$(1).o $(BUILD)/s10_$(1)_stubs.o $(BUILD)/payload_layout_$(1).tsv | $(BUILD)
	@set -e; addr=$$$$(awk -v name=s10_lcd_ili9325 '$$$$1 == name { print $$$$2; found=1; exit } END { if (!found) exit 1 }' $(BUILD)/payload_layout_$(1).tsv); \
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $$$$addr --entry lcd_board_init --sort-section=name \
		-o $$@ $(BUILD)/s10_lcd_ili9325_$(1).o $(BUILD)/s10_$(1)_stubs.o
endef

$(foreach v,$(call payload_versions,s10_lcd_ili9325),$(eval $(call S10_LCD_VERSION_template,$(v))))

s10_lcd_ili9325: $(call payload_bins,s10_lcd_ili9325)
	@echo "S10 LCD patches built:"
	@$(foreach v,$(call payload_versions,s10_lcd_ili9325),echo "  $(BUILD)/s10_lcd_ili9325_$(v).bin";)


#
# MOP callback dispatcher
#

define mop_callback_dispatcher_build_template
$(BUILD)/mop_callback_dispatcher_$(1).o: $(SRC)/mop_callback_dispatcher.S | $(BUILD)
	$$(AS) $$(ASFLAGS) -c -o $$@ $$<

$(BUILD)/mop_callback_dispatcher_$(1).probe.elf: $(BUILD)/mop_callback_dispatcher_$(1).o | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $(PROBE_LINK_ADDR) --entry start --sort-section=name \
		-o $$@ $$^

$(BUILD)/mop_callback_dispatcher_$(1).elf: $(BUILD)/mop_callback_dispatcher_$(1).o $(BUILD)/payload_layout_$(1).tsv | $(BUILD)
	@set -e; addr=$$$$(awk -v name=mop_callback_dispatcher '$$$$1 == name { print $$$$2; found=1; exit } END { if (!found) exit 1 }' $(BUILD)/payload_layout_$(1).tsv); \
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $$$$addr --entry start --sort-section=name \
		-o $$@ $(BUILD)/mop_callback_dispatcher_$(1).o
endef

$(foreach v,$(call payload_versions,mop_callback_dispatcher),$(eval $(call mop_callback_dispatcher_build_template,$(v))))

mop_callback_dispatcher: $(call payload_bins,mop_callback_dispatcher)
	@echo "MOP callback dispatcher patches built:"
	@$(foreach v,$(call payload_versions,mop_callback_dispatcher),echo "  $(BUILD)/mop_callback_dispatcher_$(v).bin";)


vid_spoof: $(call payload_bins,vid_spoof)
	@echo "VID spoof patches built:"
	@$(foreach v,$(call payload_versions,vid_spoof),echo "  $(BUILD)/vid_spoof_$(v).bin";)

clean:
	$(RM) $(BUILD)/*

-include Makefile.as11
