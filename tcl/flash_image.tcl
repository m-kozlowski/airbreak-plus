# Image file operations shared by the AirSense OpenOCD configurations.

# Copy part of an image file to a temporary file, for commands that take a
# whole file. The caller deletes the copy.
proc image_part {source offset length} {
	set input [::open $source rb]
	fconfigure $input -translation binary
	::seek $input $offset
	set data [::read $input $length]
	::close $input
	set part [file join [pwd] ".airbreak-part-[pid].bin"]
	set output [::open $part wb]
	fconfigure $output -translation binary
	::puts -nonewline $output $data
	::close $output
	return $part
}

# The flash banks the first length bytes of an image cover from the start of
# the first bank, as {bank offset length} for each.
proc image_banks {source length} {
	set banks {}
	set offset 0
	set count [llength [flash list]]
	for {set index 0} {$index < $count && $offset < $length} {incr index} {
		flash probe $index
		set bank [lindex [flash list] $index]
		if {$index == 0} {
			set start [dict get $bank base]
		} elseif {[dict get $bank base] != $start + $offset} {
			break
		}
		set part [expr {$length - $offset}]
		if {$part > [dict get $bank size]} {
			set part [dict get $bank size]
		}
		lappend banks [list $index $offset $part]
		incr offset $part
	}
	if {$offset < $length} {
		error "$source is larger than the flash memory"
	}
	return $banks
}

proc verify_bank_part {source bank offset length} {
	if {$offset == 0 && $length == [file size $source]} {
		flash verify_bank $bank $source 0
		return
	}
	set part [image_part $source $offset $length]
	set failed [catch {flash verify_bank $bank $part 0} result]
	file delete -force $part
	if {$failed} {
		error $result
	}
}

# Compare flash memory from the start of the first flash bank with an image
# file, or with its first length bytes. The image may span banks.
proc verify {path {length ""}} {
	set source [find $path]
	set size [file size $source]
	if {$size == 0} {
		error "$source is empty"
	}
	if {$length eq ""} {
		set length $size
	} elseif {$length > $size} {
		error "$source is shorter than $length bytes"
	}
	set length [expr {$length}]
	set banks [image_banks $source $length]
	# Halt a running CPU for the comparison and resume it, also after a mismatch.
	set running [expr {[[target current] curstate] eq "running"}]
	if {$running} {halt}
	echo "Comparing $length bytes of flash memory with $path..."
	set failed [catch {
		foreach bank $banks {
			verify_bank_part $source {*}$bank
		}
	} result]
	if {$running} {resume}
	if {$failed} {
		error $result
	}
	echo "Flash memory matches."
}
