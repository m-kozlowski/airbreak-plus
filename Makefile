# stm32-unlocked.bin: patch-airsense
# 	./patch-airsense stm32.bin $@

SRC=patches
BUILD=build
PATCH_STUBS=$(SRC)/stubs
MAKE_LOG ?= make.log
AIR10_PATCH_ARGS ?= $(PATCH_ARGS)
AIR10_FIRMWARE ?= stm32.bin

PATCHER_OUTPUT_ARGS := --overwrite --log-file '$(abspath $(MAKE_LOG))'
ifeq ($(V),1)
PATCHER_OUTPUT_ARGS += --verbose
endif

# Use all cores unless the caller selected -j, and keep output lines intact.
JOBS ?= $(shell nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 1)
ifeq ($(MAKELEVEL),0)
ifeq ($(filter -j%,$(MAKEFLAGS)),)
MAKEFLAGS += -j$(JOBS)
endif
endif

# Print compact build steps by default. Use `make V=1` for full commands.
ifneq ($(V),1)
.SILENT:
endif

BLX_PAYLOAD_VERSIONS := SX577-0200 SX585-0200
PAYLOAD_LAYOUT_VERSIONS := 0204 0205 0302 0305 0306 0401 0402 $(BLX_PAYLOAD_VERSIONS)
$(foreach v,$(BLX_PAYLOAD_VERSIONS),$(eval PAYLOADS_$(v) := blx_dump blx_dump_tail blx_eeprom))
PAYLOADS_0204 := target_rh mop_callback_dispatcher variable_callback_dispatcher button_hooks keep_backlight gui_objects custom_menu_hooks uart_stream_schema backlight_adapt header_clock s10_lcd_ili9325 asv_task_wrapper fall_time
PAYLOADS_0205 := $(PAYLOADS_0204)
PAYLOADS_0302 := mop_callback_dispatcher variable_callback_dispatcher button_hooks keep_backlight vid_spoof squarewave asv_task_wrapper \
	breath_tracking backlight_adapt wrapper_limit_max_pdiff s10_lcd_ili9325 gui_objects custom_menu_hooks \
	uart_stream_schema language_fonts target_rh header_clock fall_time st_ibr autoepap therapy_screen learn_targets ivaps_preview
PAYLOADS_0305 := $(PAYLOADS_0302)
PAYLOADS_0306 := $(PAYLOADS_0302)
PAYLOADS_0401 := $(PAYLOADS_0302)
PAYLOADS_0402 := $(PAYLOADS_0401)

payload_versions = $(foreach v,$(PAYLOAD_LAYOUT_VERSIONS),$(if $(filter $(1),$(PAYLOADS_$(v))),$(v)))
payload_bins = $(foreach v,$(call payload_versions,$(1)),$(BUILD)/$(1)_$(v).bin)

PAYLOAD_NAMES := $(sort $(foreach v,$(PAYLOAD_LAYOUT_VERSIONS),$(PAYLOADS_$(v))))
PAYLOAD_STAMPS := $(foreach p,$(PAYLOAD_NAMES),$(BUILD)/payload_$(p).stamp)
PAYLOAD_LAYOUT_TSVS := $(foreach v,$(PAYLOAD_LAYOUT_VERSIONS),$(BUILD)/payload_layout_$(v).tsv)

PAYLOAD_TARGETS := $(PAYLOAD_STAMPS) $(PAYLOAD_LAYOUT_TSVS)

BUILD_VARIANTS = \
	$(BUILD)/stm32-patched.bin \
	$(BUILD)/stm32-plus.bin

# Rebuild firmware when the patcher or its helpers change
S10_PATCHER_DEPS := \
	python/patch-airsense.py \
	python/edf_ccx_merge.py \
	python/lib/as10_patch_options.py \
	python/lib/as10_firmware.py \
	python/lib/as10_languages.py \
	python/lib/language_tsv.py \
	python/lib/custom_menu.py \
	python/lib/custom_menu_stock.py \
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

# Image $(1) for platform $(2), patched by python/$(3) from input image $(4)
# with the options $(5) of this image, followed by the variable named $(6).
# The $(1).config state file records the options with those of the local
# options file and the selected presets; a change rebuilds the image.
.PHONY: patch-config-force
define patch_image_rule
$(1): $(4) $(1).config Makefile python/lib/patch_config.py python/lib/patch_options.py python/lib/patch_runner.py python/lib/firmware_io.py | $(BUILD)
	$$(announce_image)
	python3 python/$(3) '$(4)' '$$@' PATCH $$(PATCHER_OUTPUT_ARGS) $(5) $$($(6))
$(1).config: patch-config-force
	python3 python/lib/patch_config.py '$(2)' '$(4)' '$$@' $(5) $$($(6))
endef

$(BUILD):
	mkdir -p $(BUILD)

# Air 10 image $(1) with the options $(2) of this image.
air10_image = $(eval $(call patch_image_rule,$(1),air10,patch-airsense.py,$(AIR10_FIRMWARE),$(2),AIR10_PATCH_ARGS))

$(BUILD_VARIANTS): $(S10_PATCHER_DEPS) $(PAYLOAD_TARGETS)

# unlocked stock-ish
$(call air10_image,$(BUILD)/stm32-patched.bin)

# Optional therapy payloads, with their custom settings
$(call air10_image,$(BUILD)/stm32-plus.bin,--preset plus)

binaries: $(PAYLOAD_TARGETS)

define PAYLOAD_STAMP_template
$(BUILD)/payload_$(1).stamp: $(call payload_bins,$(1)) Makefile | $(BUILD)
	@printf '  %-8s %-30s [%s]\n' PAYLOAD $(1) '$(call payload_versions,$(1))'
	@touch $$@
endef

$(foreach p,$(PAYLOAD_NAMES),$(eval $(call PAYLOAD_STAMP_template,$(p))))


# Per-version S10 code patches
# Each version has its own stubs.S with platform-specific addresses.
# Binaries are built per-version: breath_tracking_0401.bin, therapy_screen_0402.bin, etc.

payload_linker_script = $(wildcard $(SRC)/$(1).ld)
payload_region = $(or $(S10_PAYLOAD_REGION_$(1)),$(if $(filter blx_%,$(1)),blx,cdx))
probe_addr = awk -v version=$(2) -v region=$(call payload_region,$(1)) '$$$$1 == version && $$$$2 == region { print $$$$6; found=1; exit } END { if (!found) exit 1 }' $(SRC)/s10_code_caves.tsv
layout_addr = awk -v name=$(1) '$$$$1 == name { print $$$$2; found=1; exit } END { if (!found) exit 1 }' $(BUILD)/payload_layout_$(2).tsv
allocated_payloads = $(foreach p,$(PAYLOADS_$(1)),$(if $(call payload_linker_script,$(p)),,$(p)))

define PAYLOAD_LAYOUT_template
PAYLOAD_PROBE_BINS_$(1) := $$(foreach p,$$(call allocated_payloads,$(1)),$$(BUILD)/$$(p)_$(1).probe.bin)

$$(BUILD)/payload_sizes_$(1).tsv: $$(PAYLOAD_PROBE_BINS_$(1)) Makefile | $$(BUILD)
	@rm -f $$@.tmp
	@set -e; $(foreach p,$(call allocated_payloads,$(1)),\
		size=$$$$(wc -c < "$(BUILD)/$(p)_$(1).probe.bin"); \
		printf '%s\t%s\t%s\n' '$(p)' "$$$$size" \
		'$(call payload_region,$(p))' >> $$@.tmp;)
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

$(BUILD)/s10_%_stubs.o: $(SRC)/s10_%_stubs.S Makefile $(BUILD)/asm.flags | $(BUILD)
	$(AS) $(ASFLAGS) $(DEPFLAGS) -c -o $@ $<

define S10_VERSIONED_OBJECTS_template
$(BUILD)/%_$(1).o: $(SRC)/%.c Makefile $(BUILD)/c.flags | $(BUILD)
	$$(CC) $$(CFLAGS) $$(DEPFLAGS) $(if $(filter $(1),$(BLX_PAYLOAD_VERSIONS)),-mno-unaligned-access) \
		-D$(if $(filter SX%,$(1)),BLX,CDX)_VER_$(subst -,_,$(1)) -c -o $$@ $$<

$(BUILD)/%_$(1).o: $(SRC)/%.S Makefile $(BUILD)/asm.flags | $(BUILD)
	$$(AS) $$(ASFLAGS) $$(DEPFLAGS) -D$(if $(filter SX%,$(1)),BLX,CDX)_VER_$(subst -,_,$(1)) -c -o $$@ $$<
endef

$(foreach v,$(PAYLOAD_LAYOUT_VERSIONS),$(eval $(call S10_VERSIONED_OBJECTS_template,$(v))))

S10_PAYLOAD_ENTRY_breath_tracking := 0
S10_PAYLOAD_ENTRY_custom_menu_hooks := custom_menu_hook_append
S10_PAYLOAD_ENTRY_gui_objects := gui_destroy
S10_PAYLOAD_ENTRY_learn_targets := learn_targets_page_hook
S10_PAYLOAD_ENTRY_ivaps_preview := ivaps_preview_mv
S10_PAYLOAD_ENTRY_s10_lcd_ili9325 := lcd_board_init
S10_PAYLOAD_OBJECTS_custom_menu_hooks := custom_menu_hooks_entry custom_menu_hooks custom_menu_editors custom_menu_previews
S10_PAYLOAD_OBJECTS_therapy_screen := therapy_screen therapy_screen_abi graph graph_abi
S10_PAYLOAD_STUBS_mop_callback_dispatcher :=
S10_PAYLOAD_IMPORTS_squarewave := breath_tracking
S10_PAYLOAD_IMPORTS_wrapper_limit_max_pdiff := breath_tracking
S10_PAYLOAD_IMPORTS_custom_menu_hooks := gui_objects
S10_PAYLOAD_IMPORTS_therapy_screen := gui_objects

S10_PAYLOAD_REGION_blx_dump_tail := blx_tail
S10_PAYLOAD_ENTRY_blx_dump_tail := blx_dump_reply
S10_PAYLOAD_IMPORTS_blx_dump := blx_dump_tail blx_eeprom
S10_PAYLOAD_IMPORTS_blx_dump_tail := blx_eeprom

$(foreach v,$(PAYLOAD_LAYOUT_VERSIONS),$(eval $(call PAYLOAD_LAYOUT_template,$(v))))

s10_payload_objects = $(foreach o,$(S10_PAYLOAD_OBJECTS_$(1)),$(BUILD)/$(o)_$(2).o) $(foreach s,$(S10_PAYLOAD_STUBS_$(1)),$(BUILD)/$(s)_$(2)_stubs.o)
s10_payload_imports = $(foreach p,$(S10_PAYLOAD_IMPORTS_$(1)),$(BUILD)/$(p)_$(2)$(3).elf)

# $(1): payload, $(2): version. Declare only exceptions to these defaults above.
define S10_PAYLOAD_template
S10_PAYLOAD_ENTRY_$(1) ?= start
S10_PAYLOAD_OBJECTS_$(1) ?= $(1) $(if $(wildcard $(SRC)/$(1)_abi.S),$(1)_abi)
S10_PAYLOAD_STUBS_$(1) ?= $(if $(filter blx_%,$(1)),blx,s10)
S10_PAYLOAD_LDFLAGS_$(1) ?= --sort-section=name

$(foreach p,$(S10_PAYLOAD_IMPORTS_$(1)),$(if $(filter $(p),$(PAYLOADS_$(2))),,$(error $(1)_$(2) requires payload $(p) in PAYLOADS_$(2))))

$(BUILD)/$(1)_$(2).bin: PAYLOAD_LINKER_SCRIPT := $(call payload_linker_script,$(1))

$(BUILD)/$(1)_$(2).probe.elf: $$(call s10_payload_objects,$(1),$(2)) $$(call s10_payload_imports,$(1),$(2),.probe) $(or $(call payload_linker_script,$(1)),$(SRC)/s10_code_caves.tsv) | $(BUILD)
	@set -e; $(if $(call payload_linker_script,$(1)),,addr=$$$$($(call probe_addr,$(1),$(2)));) \
	$$(LD) --nostdlib --no-dynamic-linker \
		$(if $(call payload_linker_script,$(1)),-T $(call payload_linker_script,$(1)),--Ttext $$$$addr --entry $$(S10_PAYLOAD_ENTRY_$(1))) \
		$$(addprefix --just-symbols=,$$(call s10_payload_imports,$(1),$(2),.probe)) \
		$$(S10_PAYLOAD_LDFLAGS_$(1)) \
		-o $$@ $$(filter %.o,$$^)

$(BUILD)/$(1)_$(2).elf: $$(call s10_payload_objects,$(1),$(2)) $$(call s10_payload_imports,$(1),$(2)) $(or $(call payload_linker_script,$(1)),$(BUILD)/payload_layout_$(2).tsv) | $(BUILD)
	@set -e; $(if $(call payload_linker_script,$(1)),,addr=$$$$($(call layout_addr,$(1),$(2)));) \
	$$(LD) --nostdlib --no-dynamic-linker \
		$(if $(call payload_linker_script,$(1)),-T $(call payload_linker_script,$(1)),--Ttext $$$$addr --entry $$(S10_PAYLOAD_ENTRY_$(1))) \
		$$(addprefix --just-symbols=,$$(call s10_payload_imports,$(1),$(2))) \
		$$(S10_PAYLOAD_LDFLAGS_$(1)) \
		-o $$@ $$(filter %.o,$$^)
endef

$(foreach p,$(PAYLOAD_NAMES),\
	$(foreach v,$(call payload_versions,$(p)),\
		$(eval $(call S10_PAYLOAD_template,$(p),$(v)))))



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

# Generate dependencies even when the caller overrides CFLAGS or ASFLAGS.
DEPFLAGS = -MMD -MP -MF $(basename $@).d -MT $@

# Rewrite a configuration file only when the compiler or flags change.
# Conditional PHONY also lets make -q detect changes without writing files.
# $(1): file stem, $(2): compiler/flag variable names
define compiler_config
compile_config_$(1) := $$(foreach name,$(2),$$(name)=$$($$(name)))
ifneq ($$(shell cat '$(BUILD)/$(1).flags' 2>/dev/null),$$(compile_config_$(1)))
.PHONY: $(BUILD)/$(1).flags
endif
$(BUILD)/$(1).flags: | $(BUILD)
	printf '%s' '$$(subst ','"'"',$$(compile_config_$(1)))' > $$@
endef

$(eval $(call compiler_config,c,CC CFLAGS))
$(eval $(call compiler_config,asm,AS ASFLAGS))

$(BUILD)/%.o: $(SRC)/%.c Makefile $(BUILD)/c.flags | $(BUILD)
	$(CC) $(CFLAGS) $(DEPFLAGS) -c -o $@ $<
$(BUILD)/%.o: $(SRC)/%.S Makefile $(BUILD)/asm.flags | $(BUILD)
	$(AS) $(ASFLAGS) $(DEPFLAGS) -c -o $@ $<

$(BUILD)/%.bin: $(BUILD)/%.elf
	$(OBJCOPY) -Obinary $< $@
	@set -e; stem='$*'; ver=$${stem##*_}; payload=$${stem%_*}; \
		layout=$(BUILD)/payload_layout_$$ver.tsv; \
		if [ -f "$$layout" ] && [ -z "$(PAYLOAD_LINKER_SCRIPT)" ]; then \
			expected=$$(awk -v name="$$payload" '$$1 == name { print $$3; found=1; exit } END { if (!found) exit 1 }' "$$layout") || { \
				echo "$@: no payload row for $$payload in $$layout" >&2; \
				exit 1; \
			}; \
			actual=$$(wc -c < "$@"); \
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

$(BUILD)/eeprom_stub.o: $(EEPROM_STUB_SRC) Makefile $(BUILD)/c.flags | $(BUILD)
	$(CC) $(CFLAGS) $(DEPFLAGS) -c -o $@ $<

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


# S10 LCD patch - ILI9325/ILI9328 driver for AirSense 10
#
# Build: make s10_lcd_ili9325
# Usage: ./patch-airsense stm32.bin output.bin --patch-fw-lcd y

s10_lcd_ili9325: $(call payload_bins,s10_lcd_ili9325)
	@echo "S10 LCD patches built:"
	@$(foreach v,$(call payload_versions,s10_lcd_ili9325),echo "  $(BUILD)/s10_lcd_ili9325_$(v).bin";)


#
# MOP callback dispatcher
#

mop_callback_dispatcher: $(call payload_bins,mop_callback_dispatcher)
	@echo "MOP callback dispatcher patches built:"
	@$(foreach v,$(call payload_versions,mop_callback_dispatcher),echo "  $(BUILD)/mop_callback_dispatcher_$(v).bin";)


vid_spoof: $(call payload_bins,vid_spoof)
	@echo "VID spoof patches built:"
	@$(foreach v,$(call payload_versions,vid_spoof),echo "  $(BUILD)/vid_spoof_$(v).bin";)

clean:
	$(RM) $(BUILD)/*

-include Makefile.s9
-include Makefile.as11

-include $(wildcard $(BUILD)/*.d)
