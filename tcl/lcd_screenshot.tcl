# Host-side LCD GRAM capture for AirSense/AirCurve 10.
#
# Usage from an OpenOCD console initialized with tcl/airsense.cfg:
#   source tcl/lcd_screenshot.tcl
#   lcd_screenshot tmp/lcd.ppm

if {[llength [info commands binary]] == 0} {
	if {[catch {find tcl/binary.tcl} binary_tcl]} {
		error "lcd_screenshot: tcl/binary.tcl not found"
	}
	source $binary_tcl
}

set LCDSHOT_CMD       0x64000000
set LCDSHOT_DATA      0x64000002
set LCDSHOT_WIDTH     240
set LCDSHOT_HEIGHT    320
set LCDSHOT_GPIOF_MODER 0x40021400
set LCDSHOT_GPIOF_ODR   0x40021414
set LCDSHOT_GPIOF_BSRR  0x40021418
set LCDSHOT_GPIOF_AFRL  0x40021420

proc lcdshot_write_cmd {value} {
	mwh $::LCDSHOT_CMD [expr {$value & 0xffff}]
}

proc lcdshot_write_data {value} {
	mwh $::LCDSHOT_DATA [expr {$value & 0xffff}]
}

proc lcdshot_read16 {} {
	return [lindex [read_memory $::LCDSHOT_DATA 16 1] 0]
}

proc lcdshot_read32 {address} {
	return [lindex [read_memory $address 32 1] 0]
}

proc lcdshot_write_reg {reg value} {
	lcdshot_write_cmd $reg
	lcdshot_write_data $value
}

proc lcdshot_rgb565_bytes {pixel} {
	set r5 [expr {($pixel >> 11) & 0x1f}]
	set g6 [expr {($pixel >> 5) & 0x3f}]
	set b5 [expr {$pixel & 0x1f}]
	set r8 [expr {($r5 << 3) | ($r5 >> 2)}]
	set g8 [expr {($g6 << 2) | ($g6 >> 4)}]
	set b8 [expr {($b5 << 3) | ($b5 >> 2)}]

	set bytes [binary format c $r8]
	append bytes [binary format c $g8]
	append bytes [binary format c $b8]
	return $bytes
}

# CPU address bit 1 is FSMC A0 on a 16-bit bus. Air 10 uses that line as
# LCD command/data select, hence the command and data addresses differ by 2.
# Holding PF0 high makes sequential 32-bit reads act as a bulk read from the
# data port; each word still produces two 16-bit FSMC bus cycles.
proc lcdshot_validate_rs_line {} {
	set moder [lcdshot_read32 $::LCDSHOT_GPIOF_MODER]
	set odr [lcdshot_read32 $::LCDSHOT_GPIOF_ODR]
	set afrl [lcdshot_read32 $::LCDSHOT_GPIOF_AFRL]

	if {($moder & 3) != 2 || ($afrl & 0xf) != 12} {
		return -code error [format \
			"lcd_screenshot: PF0 is not FSMC_A0 (MODER=0x%08X AFRL=0x%08X)" \
			$moder $afrl]
	}
	return [list $moder $odr]
}

proc lcdshot_force_rs_data {state} {
	set moder [lindex $state 0]
	mww $::LCDSHOT_GPIOF_BSRR 1
	mww $::LCDSHOT_GPIOF_MODER [expr {($moder & ~3) | 1}]
}

proc lcdshot_restore_rs_line {state} {
	set moder [lindex $state 0]
	set odr [lindex $state 1]

	mww $::LCDSHOT_GPIOF_MODER $moder
	if {$odr & 1} {
		mww $::LCDSHOT_GPIOF_BSRR 1
	} else {
		mww $::LCDSHOT_GPIOF_BSRR 0x00010000
	}
}

# Match the stock ILI9341 FlexColor full-screen window setup.
proc lcdshot_prepare_ili9341 {} {
	set x1 [expr {$::LCDSHOT_WIDTH - 1}]
	set y1 [expr {$::LCDSHOT_HEIGHT - 1}]

	lcdshot_write_cmd 0x2a
	lcdshot_write_data 0
	lcdshot_write_data 0
	lcdshot_write_data [expr {$x1 >> 8}]
	lcdshot_write_data [expr {$x1 & 0xff}]

	lcdshot_write_cmd 0x2b
	lcdshot_write_data 0
	lcdshot_write_data 0
	lcdshot_write_data [expr {$y1 >> 8}]
	lcdshot_write_data [expr {$y1 & 0xff}]

	lcdshot_write_cmd 0x2e
	lcdshot_read16
}

# Match the replacement-driver ILI9325/ILI9328 window setup for one row.
proc lcdshot_prepare_row_ili932x {y} {
	set x1 [expr {$::LCDSHOT_WIDTH - 1}]

	lcdshot_write_reg 0x50 0
	lcdshot_write_reg 0x51 $x1
	lcdshot_write_reg 0x52 $y
	lcdshot_write_reg 0x53 $y
	lcdshot_write_reg 0x20 0
	lcdshot_write_reg 0x21 $y
	lcdshot_write_cmd 0x22
	lcdshot_read16
}

proc lcdshot_read_row_ili9341 {address} {
	set words {}
	set transfers {}
	set row ""
	set transfer_count [expr {$::LCDSHOT_WIDTH * 3 / 2}]
	set word_count [expr {($transfer_count + 1) / 2}]
	set words [read_memory $address 32 $word_count]

	# ILI9341 RAMRD with a 16-bit bus and MDT=00 packs two RGB666 pixels into
	# three transfers: R0/G0, B0/R1, G1/B1. A 32-bit FSMC read supplies two
	# consecutive transfers.
	for {set i 0} {$i < $word_count} {incr i} {
		set word [lindex $words $i]
		lappend transfers [expr {$word & 0xffff}]
		lappend transfers [expr {($word >> 16) & 0xffff}]
	}

	for {set x 0} {$x < $::LCDSHOT_WIDTH} {incr x 2} {
		set i [expr {$x * 3 / 2}]
		set a [lindex $transfers $i]
		set b [lindex $transfers [expr {$i + 1}]]
		set c [lindex $transfers [expr {$i + 2}]]

		set r0 [expr {($a >> 10) & 0x3f}]
		set g0 [expr {($a >> 2) & 0x3f}]
		set b0 [expr {($b >> 10) & 0x3f}]
		set r1 [expr {($b >> 2) & 0x3f}]
		set g1 [expr {($c >> 10) & 0x3f}]
		set b1 [expr {($c >> 2) & 0x3f}]

		# The active panel configuration exposes RAMRD red/blue fields in the
		# opposite order from the GUI color values; emit host RGB accordingly.
		set pixel0 [expr {(($b0 >> 1) << 11) | ($g0 << 5) | ($r0 >> 1)}]
		set pixel1 [expr {(($b1 >> 1) << 11) | ($g1 << 5) | ($r1 >> 1)}]
		append row [lcdshot_rgb565_bytes $pixel0]
		append row [lcdshot_rgb565_bytes $pixel1]
	}
	return $row
}

proc lcdshot_read_row_ili932x {address} {
	set words {}
	set row ""
	set word_count [expr {$::LCDSHOT_WIDTH / 2}]
	set words [read_memory $address 32 $word_count]

	for {set x 0} {$x < $word_count} {incr x} {
		set word [lindex $words $x]
		append row [lcdshot_rgb565_bytes [expr {$word & 0xffff}]]
		append row [lcdshot_rgb565_bytes [expr {($word >> 16) & 0xffff}]]
	}
	return $row
}

proc lcdshot_detect_controller {} {
	lcdshot_write_cmd 0
	set id [lcdshot_read16]
	if {$id == 0x9325 || $id == 0x9328} {
		return [list ili932x $id]
	}

	# ILI9341 command 0 is NOP, so its read value is stale bus data. RDDID4
	# returns a dummy byte followed by 00 93 41 on the stock controller.
	lcdshot_write_cmd 0xd3
	set id_bytes {}
	for {set i 0} {$i < 4} {incr i} {
		lappend id_bytes [expr {[lcdshot_read16] & 0xff}]
	}
	set id [expr {([lindex $id_bytes 2] << 8) | [lindex $id_bytes 3]}]
	return [list ili9341 $id]
}

proc lcd_screenshot {{path "lcd.ppm"} {controller "auto"}} {
	if {$controller ne "auto" && $controller ne "ili9341" && $controller ne "ili932x"} {
		return -code error "lcd_screenshot: controller must be auto, ili9341, or ili932x"
	}

	halt

	if {$controller eq "auto"} {
		set detected [lcdshot_detect_controller]
		set controller [lindex $detected 0]
		set id [lindex $detected 1]
		echo [format "LCD controller: %s (ID read 0x%04X)" $controller $id]
	} else {
		echo "LCD controller: $controller (forced)"
	}

	echo "Capturing $::LCDSHOT_WIDTH x $::LCDSHOT_HEIGHT to $path"

	set out [::open $path wb]
	fconfigure $out -translation binary
	::puts -nonewline $out "P6\n$::LCDSHOT_WIDTH $::LCDSHOT_HEIGHT\n255\n"

	set rs_state {}
	set status [catch {
		set rs_state [lcdshot_validate_rs_line]
		if {$controller eq "ili9341"} {
			lcdshot_prepare_ili9341
			lcdshot_force_rs_data $rs_state
		}

		for {set y 0} {$y < $::LCDSHOT_HEIGHT} {incr y} {
			if {$controller eq "ili932x"} {
				lcdshot_prepare_row_ili932x $y
				lcdshot_force_rs_data $rs_state
				set row [lcdshot_read_row_ili932x $::LCDSHOT_CMD]
				lcdshot_restore_rs_line $rs_state
			} else {
				set row [lcdshot_read_row_ili9341 $::LCDSHOT_CMD]
			}
			::puts -nonewline $out $row
			if {(($y & 0x1f) == 0x1f) || ($y == $::LCDSHOT_HEIGHT - 1)} {
				echo [format "  rows: %d/%d" [expr {$y + 1}] $::LCDSHOT_HEIGHT]
			}
		}
		if {$controller eq "ili9341"} {
			lcdshot_restore_rs_line $rs_state
		}
	} message]

	if {[llength $rs_state] == 2} {
		set restore_status [catch {lcdshot_restore_rs_line $rs_state} restore_message]
		if {$restore_status != 0 && $status == 0} {
			set status $restore_status
			set message "lcd_screenshot: failed to restore PF0: $restore_message"
		}
	}

	catch {::close $out}
	if {$status != 0} {
		return -code error $message
	}

	echo "LCD capture complete: $path"
    resume
}

echo "Loaded lcd_screenshot ?path? ?auto|ili9341|ili932x?"
