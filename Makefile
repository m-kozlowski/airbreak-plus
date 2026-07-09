# stm32-unlocked.bin: patch-airsense
# 	./patch-airsense stm32.bin $@

SRC=patches
BUILD=build

MOP_CALLBACK_DISPATCHER_VERSIONS := 0401 0306 0305 0302 0402
MOP_CALLBACK_DISPATCHER_BINS = $(foreach v,$(MOP_CALLBACK_DISPATCHER_VERSIONS),$(BUILD)/mop_callback_dispatcher_$(v).bin)
VID_SPOOF_VERSIONS := 0401 0306 0305 0302 0402
VID_SPOOF_BINS = $(foreach v,$(VID_SPOOF_VERSIONS),$(BUILD)/vid_spoof_$(v).bin)

S10_CODE_VERSIONS := 0401 0402
S10_CODE_BINS = $(foreach v,$(S10_CODE_VERSIONS),\
	$(BUILD)/common_code_$(v).bin \
	$(BUILD)/graph_$(v).bin \
	$(BUILD)/squarewave_$(v).bin \
	$(BUILD)/asv_task_wrapper_$(v).bin \
	$(BUILD)/wrapper_limit_max_pdiff_$(v).bin \
	$(BUILD)/custom_menu_hooks_$(v).bin \
	$(BUILD)/backlight_adapt_$(v).bin)

BUILD_VARIANTS = \
	$(BUILD)/stm32-patched.bin \
	$(BUILD)/stm32-graph.bin \
	$(BUILD)/stm32-asv-plus.bin \
	$(BUILD)/stm32-asv-plus_no-squarewave.bin \
	$(BUILD)/stm32-asv-plus_with-backup.bin

all: $(BUILD_VARIANTS)

$(BUILD):
	mkdir -p $(BUILD)

# unlocked stock-ish
$(BUILD)/stm32-patched.bin: patch-airsense $(S10_CODE_BINS) $(MOP_CALLBACK_DISPATCHER_BINS) $(VID_SPOOF_BINS)
	./patch-airsense stm32.bin $@

# graph overlay injected
$(BUILD)/stm32-graph.bin: patch-airsense $(S10_CODE_BINS) $(MOP_CALLBACK_DISPATCHER_BINS) $(VID_SPOOF_BINS)
	PATCH_CODE=1 ./patch-airsense stm32.bin $@

# Custom ASV algorithm in VAuto slot + ASV backup-rate suppression + squarewave mode
$(BUILD)/stm32-asv-plus.bin: patch-airsense $(S10_CODE_BINS) $(MOP_CALLBACK_DISPATCHER_BINS) $(VID_SPOOF_BINS)
	PATCH_CODE=1 PATCH_ASV_TASK_WRAPPER=1 PATCH_VAUTO_WRAPPER=1 PATCH_S=1 ./patch-airsense stm32.bin $@

# Custom ASV in VAuto slot + backup-rate suppression, no squarewave
$(BUILD)/stm32-asv-plus_no-squarewave.bin: patch-airsense $(S10_CODE_BINS) $(MOP_CALLBACK_DISPATCHER_BINS) $(VID_SPOOF_BINS)
	PATCH_CODE=1 PATCH_ASV_TASK_WRAPPER=1 PATCH_VAUTO_WRAPPER=1 ./patch-airsense stm32.bin $@

# Custom ASV in VAuto slot + squarewave, stock ASV backup-rate preserved
$(BUILD)/stm32-asv-plus_with-backup.bin: patch-airsense $(S10_CODE_BINS) $(MOP_CALLBACK_DISPATCHER_BINS) $(VID_SPOOF_BINS)
	PATCH_CODE=1 PATCH_VAUTO_WRAPPER=1 PATCH_S=1 ./patch-airsense stm32.bin $@

binaries: $(S10_CODE_BINS) $(MOP_CALLBACK_DISPATCHER_BINS) $(VID_SPOOF_BINS)


# There are decent distances between the different patches, 
# but if you substantially increase the amount of code, beware collisions.
# I've already had several happen in the past, whoops :F

# Per-version S10 code patches
# Each version has its own stubs.S with platform-specific addresses.
# Binaries are built per-version: common_code_0401.bin, graph_0402.bin, etc.
#
# Code cave layout
#   0x80fcf98  mop_callback_dispatcher  (  44 B)
#   0x80fcfc4  vid_spoof                (  60 B)
#   0x80fd000  graph                    (1024 B)
#   0x80fd400  squarewave               ( 768 B)
#   0x80fd700  asv_task_wrapper         ( 256 B)
#   0x80fd800  common_code              (5120 B)
#   0x80fec00  backlight_adapt          (1024 B)
#   0x80ff000  wrapper_limit_max_pdiff  (2048 B)
#   0x80ff800  s10_lcd_ili9325          (1024 B)
#   0x80ffc00  custom_menu_hooks        (1022 B, leaves CDX CRC)

graph-offset := 0x80fd000
squarewave-offset := 0x80fd400
asv_task_wrapper-offset := 0x80fd700
common_code-offset := 0x80fd800
backlight_adapt-offset := 0x80fec00
wrapper_limit_max_pdiff-offset := 0x80ff000
custom_menu_hooks-offset := 0x80ffc00
mop_callback_dispatcher-offset := 0x80fcf98
vid_spoof-offset := 0x80fcfc4

$(BUILD)/s10_%_stubs.o: $(SRC)/s10_%_stubs.S | $(BUILD)
	$(AS) $(ASFLAGS) -c -o $@ $<

define S10_CODE_VERSION_template
$(BUILD)/%_$(1).o: $(SRC)/%.c $(SRC)/s10_vars.h $(SRC)/s10_vars_$(1).h | $(BUILD)
	$$(CC) $$(CFLAGS) -DCDX_VER_$(1) -c -o $$@ $$<

$(BUILD)/%_$(1).o: $(SRC)/%.S $(SRC)/s10_vars.h $(SRC)/s10_vars_$(1).h | $(BUILD)
	$$(AS) $$(ASFLAGS) -DCDX_VER_$(1) -c -o $$@ $$<

$(BUILD)/common_code_$(1).elf: $(BUILD)/common_code_$(1).o $(BUILD)/s10_$(1)_stubs.o | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $(common_code-offset) --entry start --sort-section=name \
		-o $$@ $$^

$(BUILD)/graph_$(1).elf: $(BUILD)/graph_$(1).o $(BUILD)/s10_$(1)_stubs.o $(BUILD)/common_code_$(1).elf | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $(graph-offset) \
		--just-symbols=$$(BUILD)/common_code_$(1).elf \
		--entry start --sort-section=name -o $$@ $(BUILD)/graph_$(1).o $(BUILD)/s10_$(1)_stubs.o

$(BUILD)/squarewave_$(1).elf: $(BUILD)/squarewave_$(1).o $(BUILD)/squarewave_abi_$(1).o $(BUILD)/s10_$(1)_stubs.o $(BUILD)/common_code_$(1).elf | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $(squarewave-offset) \
		--just-symbols=$$(BUILD)/common_code_$(1).elf \
		--entry start --sort-section=name -o $$@ $(BUILD)/squarewave_$(1).o $(BUILD)/squarewave_abi_$(1).o $(BUILD)/s10_$(1)_stubs.o

$(BUILD)/asv_task_wrapper_$(1).elf: $(BUILD)/asv_task_wrapper_$(1).o $(BUILD)/s10_$(1)_stubs.o $(BUILD)/common_code_$(1).elf | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $(asv_task_wrapper-offset) \
		--just-symbols=$$(BUILD)/common_code_$(1).elf \
		--entry start --sort-section=name -o $$@ $(BUILD)/asv_task_wrapper_$(1).o $(BUILD)/s10_$(1)_stubs.o

$(BUILD)/wrapper_limit_max_pdiff_$(1).elf: $(BUILD)/wrapper_limit_max_pdiff_$(1).o $(BUILD)/wrapper_limit_max_pdiff_abi_$(1).o $(BUILD)/s10_$(1)_stubs.o $(BUILD)/common_code_$(1).elf | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $(wrapper_limit_max_pdiff-offset) \
		--just-symbols=$$(BUILD)/common_code_$(1).elf \
		--entry start --sort-section=name -o $$@ $(BUILD)/wrapper_limit_max_pdiff_$(1).o $(BUILD)/wrapper_limit_max_pdiff_abi_$(1).o $(BUILD)/s10_$(1)_stubs.o

$(BUILD)/custom_menu_hooks_$(1).elf: $(BUILD)/custom_menu_hooks_entry_$(1).o $(BUILD)/custom_menu_hooks_$(1).o $(BUILD)/s10_$(1)_stubs.o | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $(custom_menu_hooks-offset) \
		--entry custom_menu_hook_therapy -o $$@ $$^

$(BUILD)/backlight_adapt_$(1).elf: $(BUILD)/backlight_adapt_$(1).o $(BUILD)/s10_$(1)_stubs.o | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $(backlight_adapt-offset) \
		--entry start --sort-section=name -o $$@ $$^
endef

$(foreach v,$(S10_CODE_VERSIONS),$(eval $(call S10_CODE_VERSION_template,$(v))))



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


# eeprom_stub - standalone CDX replacement for s10 platform
#
# Build: make eeprom_stub
# Output: build/eeprom_stub_nocrc.bin (raw, for patched bootloader)
#         build/eeprom_stub_full.bin  (768KB + CRC, for stock bootloader)

EEPROM_STUB_OFFSET ?= 0x08040000

EEPROM_STUB_OBJS := $(patsubst $(SRC)/%.c,$(BUILD)/%.o,$(wildcard $(SRC)/eeprom_stub*.c))

# The stub uses its own linker script
$(BUILD)/eeprom_stub.elf: $(EEPROM_STUB_OBJS) | $(BUILD)
	$(LD) --nostdlib \
		-T $(SRC)/eeprom_stub.ld \
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

S10_LCD_OFFSET ?= 0x080FF800
S10_LCD_VERSIONS := 0401 0402

define S10_LCD_VERSION_template
$(BUILD)/s10_lcd_ili9325_$(1).elf: $(BUILD)/s10_lcd_ili9325_$(1).o $(BUILD)/s10_$(1)_stubs.o | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $$(S10_LCD_OFFSET) --entry lcd_board_init --sort-section=name \
		-o $$@ $$^

$(BUILD)/s10_lcd_ili9325_$(1).bin: $(BUILD)/s10_lcd_ili9325_$(1).elf
	$$(OBJCOPY) -Obinary $$< $$@
endef

$(foreach v,$(S10_LCD_VERSIONS),$(eval $(call S10_LCD_VERSION_template,$(v))))

s10_lcd_ili9325: $(foreach v,$(S10_LCD_VERSIONS),$(BUILD)/s10_lcd_ili9325_$(v).bin)
	@echo "S10 LCD patches built:"
	@$(foreach v,$(S10_LCD_VERSIONS),echo "  $(BUILD)/s10_lcd_ili9325_$(v).bin";)
	@echo "Inject offset: $(S10_LCD_OFFSET)"


#
# MOP callback dispatcher
#

define mop_callback_dispatcher_build_template
$(BUILD)/mop_callback_dispatcher_$(1).o: $(SRC)/mop_callback_dispatcher.S | $(BUILD)
	$$(AS) $$(ASFLAGS) -c -o $$@ $$<

$(BUILD)/mop_callback_dispatcher_$(1).elf: $(BUILD)/mop_callback_dispatcher_$(1).o | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $(mop_callback_dispatcher-offset) --entry start --sort-section=name \
		-o $$@ $$^

$(BUILD)/mop_callback_dispatcher_$(1).bin: $(BUILD)/mop_callback_dispatcher_$(1).elf
	$$(OBJCOPY) -Obinary $$< $$@
endef

$(foreach v,$(MOP_CALLBACK_DISPATCHER_VERSIONS),$(eval $(call mop_callback_dispatcher_build_template,$(v))))

mop_callback_dispatcher: $(MOP_CALLBACK_DISPATCHER_BINS)
	@echo "MOP callback dispatcher patches built:"
	@$(foreach v,$(MOP_CALLBACK_DISPATCHER_VERSIONS),echo "  $(BUILD)/mop_callback_dispatcher_$(v).bin";)


#
# VID Spoof - MOP-based Variant ID override handler
#

define vid_spoof_build_template
$(BUILD)/vid_spoof_$(1).o: $(SRC)/vid_spoof.c $(SRC)/s10_vars.h $(SRC)/s10_vars_$(1).h | $(BUILD)
	$$(CC) $$(CFLAGS) \
		-DCDX_VER_$(1) \
		-c -o $$@ $$<

$(BUILD)/vid_spoof_$(1).elf: $(BUILD)/vid_spoof_$(1).o $(BUILD)/s10_$(1)_stubs.o | $(BUILD)
	$$(LD) --nostdlib --no-dynamic-linker \
		--Ttext $(vid_spoof-offset) --entry vid_spoof_apply_current_mop --sort-section=name \
		-o $$@ $$^

$(BUILD)/vid_spoof_$(1).bin: $(BUILD)/vid_spoof_$(1).elf
	$$(OBJCOPY) -Obinary $$< $$@
endef

$(foreach v,$(VID_SPOOF_VERSIONS),$(eval $(call vid_spoof_build_template,$(v))))

vid_spoof: $(VID_SPOOF_BINS)
	@echo "VID spoof patches built:"
	@$(foreach v,$(VID_SPOOF_VERSIONS),echo "  $(BUILD)/vid_spoof_$(v).bin";)


backlight_adapt: $(foreach v,$(S10_CODE_VERSIONS),$(BUILD)/backlight_adapt_$(v).bin)


clean:
	$(RM) $(BUILD)/*

-include Makefile.as11
