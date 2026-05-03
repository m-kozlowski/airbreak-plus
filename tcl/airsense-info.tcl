proc float_to_bytes {val} {
	return [format "0x%s" [exec perl -e "print pack('f>', $val)" | xxd -p]]
}

proc bytes_to_float {val_} {
	return [exec perl -e "print unpack('f>', pack('H*', '[format "%0x" $val_]'))"]
}

proc hackcheck {} {
	global IS_ORIG
	if {$IS_ORIG == 1} {
		echo "That won't work without uploading hacked firmware!"
		return 0
	}
	return 1
}
proc p {} {
	if {[hackcheck] == 0} return 
	mem2array val 32 0x20001f00 4
	set HIGHP_OVERRIDE $val(0)
	set LOWP_OVERRIDE $val(1)
	set HIGHT_OVERRIDE $val(2)
	set LOWT_OVERRIDE $val(3)
	#echo [format "override registers: HP=0x%x LP=0x%x HT=0x%x LT=0x%x" $HIGHP_OVERRIDE $LOWP_OVERRIDE $HIGHT_OVERRIDE $LOWT_OVERRIDE]
	if {$LOWP_OVERRIDE != 0} {
		echo [format "low pressure: %.1f cm-h2O (set by debugger)" [eval bytes_to_float $LOWP_OVERRIDE]]
	} else {
		echo "low pressure: 4.0 cm-h2O (default)"
	}
	if {$HIGHP_OVERRIDE != 0} {
		echo [format "high pressure: %.1f cm-h2O (set via debugger)" [eval bytes_to_float $HIGHP_OVERRIDE]]
	} else {
		echo [format "high pressure: %.1f cm-h2O (set by clinician menu)" [eval bytes_to_float [mrw 0x2000e96c]]]
	}
	set ms_per_breath [expr {.25 * [bytes_to_float [mrw 0x2000e970]]}]
	if {$HIGHT_OVERRIDE != 0} {
		echo [format "high pressure time: %.1f seconds (set via debugger)" [expr {.000001 * [mrw 0x20001f08]}]]
	} else {
		echo [format "high pressure time: %.1f seconds (set via clinician menu)" $ms_per_breath]
	}
	if {$LOWT_OVERRIDE != 0} {
		echo [format "low pressure time: %.1f seconds (set via debugger)" [expr {.000001 * [mrw 0x20001f0c]}]]
	} else {
		echo [format "low pressure time: %.1f seconds (set via clinician menu)" $ms_per_breath]
	}
}

proc lp {arg} {
	if {[hackcheck] == 0} return 
	echo "Setting low pressure value to $arg cm-h2O..."
	mww 0x20001f04 [float_to_bytes $arg]
	p
}

proc hp {arg} {
	if {[hackcheck] == 0} return 
	echo "Setting high pressure value to $arg cm-h2O..."	
	mww 0x20001f00 [float_to_bytes $arg]
	p
}

proc ht {arg} {
	if {[hackcheck] == 0} return 
	echo "Setting high time to $arg seconds..."	
	set ms_tm [format %d [expr {round($arg * 1000000)}]]
	mww 0x20001f08 [format 0x%08x $ms_tm]
	p
}
proc lt {arg} {
	if {[hackcheck] == 0} return 
	echo "Setting low time to $arg seconds..."	
	set ms_tm [format %d [expr {round($arg * 1000000)}]]
	mww 0x20001f0c [format 0x%08x $ms_tm]
	p
}

proc ra {} {
	if {[hackcheck] == 0} return 
	echo "Clearing setting overrides..."
	mwd 0x20001f00 0
	mwd 0x20001f08 0
	p
}

set MAGIC_PTR_ADDR 0x20000be0
set PTR_FEATURES 4
set PTR_TRIGGERCYCLE 5
# vauto_debug_t is embedded after features_t.eps and features_t.ips_fa.
# This avoids guessed fixed RAM addresses and avoids changing the shared pointer table layout.
set FEATURE_DEBUG_OFFSET 8
set VAUTO_DEBUG_FIELDS {
	mode st_inhaling st_just_started st_pre_trigger current_eps ps ps1 new_ps
	returned_ps feat_eps feat_ips_fa asv_factor final_ips volume volume_max ti te
}
# The runtime trigger/cycle fvars are actively overwritten by custom trigger/cycle code:
#   trigger: -5.0 guarantees trigger, 999.0 suppresses trigger
#   cycle:    0.95 guarantees cycle, -0.5 suppresses cycle
# The set_* values are read from triggercycle_t.real_trigger/real_cycle.
# The pressure bounds are runtime values; UI values are estimated as bound +/- PS/2.
set VAUTO_SETTING_FIELDS {
	runtime_trigger_lpm set_trigger_lpm runtime_cycle_raw set_cycle_raw runtime_ipap_bound runtime_epap_bound ps ui_max_ipap_est ui_min_epap_est ti_min_s ti_max_s
}

proc u32_to_float {val} {
	binary scan [binary format i $val] f result
	return $result
}

proc u32_at {addr} {
	return [lindex [read_memory $addr 32 1] 0]
}

proc read_fvar {index} {
	# 0401 fvars base. For 0402 this is 0x2000e954; update if using an SX567-0402 image.
	set raw [lindex [read_memory [expr {0x2000e948 + ($index * 4)}] 32 1] 0]
	return [u32_to_float $raw]
}

proc read_ivar {index} {
	# 0401 ivars base. For 0402 this is 0x2000e75c; update if using an SX567-0402 image.
	return [u32_at [expr {0x2000e750 + ($index * 4)}]]
}

proc ptr_table_entry {index} {
	global MAGIC_PTR_ADDR
	set table [u32_at [expr {$MAGIC_PTR_ADDR + 4}]]
	return [u32_at [expr {$table + ($index * 4)}]]
}

proc read_float_at {addr} {
	return [u32_to_float [u32_at $addr]]
}

proc triggercycle_addr {} {
	global PTR_TRIGGERCYCLE
	set addr [ptr_table_entry $PTR_TRIGGERCYCLE]
	if {$addr == 0} {
		error "trigger/cycle state is not allocated yet; start therapy first"
	}
	return $addr
}

proc vdbg_settings {} {
	# fvars[0x7]/[0x8] are the active runtime thresholds and may be sentinel values.
	set runtime_trigger [read_fvar 0x7]
	set runtime_cycle [read_fvar 0x8]
	set trc [triggercycle_addr]
	# real_trigger/real_cycle preserve the underlying user-selected thresholds.
	set real_trigger [read_float_at [expr {$trc + 4}]]
	set real_cycle [read_float_at [expr {$trc + 12}]]
	# fvars[0x9]/[0xa] are PS-adjusted runtime bounds, not direct UI config storage.
	set eff_ipap_max [read_fvar 0x9]
	set eff_epap_min [read_fvar 0xa]
	set ps [read_fvar 0xb]
	set values ""
	lappend values $runtime_trigger
	lappend values $real_trigger
	lappend values $runtime_cycle
	lappend values $real_cycle
	lappend values $eff_ipap_max
	lappend values $eff_epap_min
	lappend values $ps
	lappend values [expr {$eff_ipap_max + ($ps / 2.0)}]
	lappend values [expr {$eff_epap_min - ($ps / 2.0)}]
	lappend values [expr {[read_ivar 0x5] * 0.01}]
	lappend values [expr {[read_ivar 0x6] * 0.01}]
	return $values
}

proc print_table {title names values} {
	echo $title
	echo "+----------------------+------------+"
	echo "| field                | value      |"
	echo "+----------------------+------------+"
	foreach name $names value $values {
		echo [format "| %-20s | %10.4f |" $name $value]
	}
	echo "+----------------------+------------+"
}

proc vdbg_addr {} {
	global MAGIC_PTR_ADDR PTR_FEATURES FEATURE_DEBUG_OFFSET
	set magic [u32_at $MAGIC_PTR_ADDR]
	if {$magic != 0x07e49002} {
		error "debug pointer table is not initialized yet; start therapy with the debug firmware first"
	}
	set table [u32_at [expr {$MAGIC_PTR_ADDR + 4}]]
	set features [u32_at [expr {$table + ($PTR_FEATURES * 4)}]]
	if {$features == 0} {
		error "VAuto feature/debug state is not allocated yet; start therapy in VAuto first"
	}
	return [expr {$features + $FEATURE_DEBUG_OFFSET}]
}

proc vdbg {{samples 1} {delay 100}} {
	global VAUTO_DEBUG_FIELDS VAUTO_SETTING_FIELDS
	for {set j 0} {$j < $samples} {incr j} {
		set raw_values [read_memory [vdbg_addr] 32 [llength $VAUTO_DEBUG_FIELDS]]
		set debug_values ""
		foreach raw $raw_values {
			lappend debug_values [u32_to_float $raw]
		}
		if {$samples > 1} {
			echo [format "sample %d/%d" [expr {$j + 1}] $samples]
		}
		print_table "VAuto settings" $VAUTO_SETTING_FIELDS [vdbg_settings]
		print_table "VAuto debug" $VAUTO_DEBUG_FIELDS $debug_values
		after $delay
	}
}

proc vdbg_csv {{samples 200} {delay 100} {fname ""}} {
	global VAUTO_DEBUG_FIELDS VAUTO_SETTING_FIELDS
	if {$fname eq ""} {
		set channel stdout
	} else {
		set channel [open $fname w]
	}
	puts $channel "time_ms,[join $VAUTO_SETTING_FIELDS ,],[join $VAUTO_DEBUG_FIELDS ,]"
	for {set j 0} {$j < $samples} {incr j} {
		set values [read_memory [vdbg_addr] 32 [llength $VAUTO_DEBUG_FIELDS]]
		set row [clock milliseconds]
		foreach value [vdbg_settings] {
			append row [format ",%.6f" $value]
		}
		foreach raw $values {
			append row [format ",%.6f" [u32_to_float $raw]]
		}
		puts $channel $row
		after $delay
	}
	if {$fname ne ""} {
		close $channel
		echo "Wrote $fname"
	}
}

proc h {} {
	echo "Airsense S10 Custom Firmware Debug Commands:"
	echo "\tlt \[val\] : set low pressure time interval (seconds)"
	echo "\tht \[val\] : set high pressure time interval (seconds)"
	echo "\thp \[val\] : set high pressure value (cm-h2O, 0-30))"
	echo "\tlp \[val\] : set low pressure value (cm-h2O, 0-30))"
	echo "\tra       : reset override values to clinician menu settings"
	echo "\tp        : print all values"
	echo "\tvdbg \[samples\] \[delay_ms\] : print VAuto debug snapshot(s)"
	echo "\tvdbg_csv \[samples\] \[delay_ms\] \[file\] : dump VAuto debug snapshots as CSV"
	echo "\th        : show this help screen"
}
