# Fast full-chip read of the external SPI-NOR over SWD -- RAM-stub driver
# (the stub only issues READ 0x03; it never writes or erases).
# Requires: target connected; as11-keys.tcl sourced (as11.cfg does this
#           automatically); nor_stub.bin present in the OpenOCD start
#           directory (airbreak-plus root).
# Usage:
#   nor_fast::nor_id                       read chip id + capacity (fast, read-only)
#   nor_fast::nor_test <file> [off] [len]  single-chunk self-test (default 256KB @ offset 0)
#   nor_fast::nor_dump <outdir> [size]     full chip: each chunk dumped to outdir/nor_NNNN.bin
# Flow: halt -> _setup_spi5 -> load stub -> per chunk {set r0/r1/r2/pc/sp, resume, wait_halt, dump_image}
# The stub clobbers RAM (stub code + buffer + stack), so after reading you
# MUST reset / power-cycle -- do not resume the firmware.

namespace eval nor_fast {
    variable STUB    0x24000000   ;# stub load address (start of AXI SRAM)
    variable BUF     0x24010000   ;# read buffer (after the stub, 64KB gap)
    variable CHUNK   0x40000      ;# 256KB per chunk (buffer fits it; #chunks = size/256K)
    variable STACK   0x20020000   ;# top of DTCM, used as the stub's stack
    variable STUBBIN nor_stub.bin   ;# in airbreak-plus root (openocd cwd); stub source/build kept separately

    proc _prep {} {
        variable STUB; variable STUBBIN
        halt
        catch {freeze_iwdg}      ;# freeze the watchdog while halted
        as11_keys::_setup_spi5
        load_image $STUBBIN $STUB bin
        mww 0xE000ED94 0    ;# disable MPU_CTRL (firmware may mark AXI SRAM XN -> exec fault)
    }

    proc _readchunk {off len} {
        variable STUB; variable BUF; variable STACK
        mww 0x58004800 0x0000AAAA  ;# kick IWDG (each stub run ~85ms; else it would eventually reset)
        reg control 0            ;# privileged + use MSP
        reg xpsr 0x01000000      ;# Thumb bit set, IPSR=0 (thread mode)
        reg msp $STACK
        reg sp  $STACK
        reg r0  $off
        reg r1  $len
        reg r2  $BUF
        reg pc  $STUB
        resume
        wait_halt 15000
    }

    # single-chunk self-test: read len bytes at NOR offset off -> outfile (default 256KB @ 0)
    proc nor_test {outfile {off 0} {len 0x40000}} {
        variable BUF
        _prep
        _readchunk $off $len
        dump_image $outfile $BUF $len
        echo [format "nor_test: NOR 0x%X +0x%X -> %s" $off $len $outfile]
    }

    # read chip id + capacity (read-only, fast; does not run the stub)
    proc nor_id {} {
        halt
        catch {freeze_iwdg}
        as11_keys::_setup_spi5
        set id [as11_keys::_jedec]
        set cap [lindex $id 2]
        echo [format "JEDEC ID: manuf=0x%02X type=0x%02X cap=0x%02X" [lindex $id 0] [lindex $id 1] $cap]
        set sz [as11_keys::_capacity $cap]
        if {$sz > 0} {
            echo [format "  capacity = %d bytes (%d MB)" $sz [expr {$sz / 1048576}]]
        } else {
            echo "  capacity byte looks wrong (JEDEC not read correctly)"
        }
        catch {resume}
    }

    # full-chip fast read: size=0 -> use the JEDEC capacity
    proc nor_dump {outdir {size 0}} {
        variable BUF; variable CHUNK
        _prep
        if {$size == 0} {
            set size [as11_keys::_capacity [lindex [as11_keys::_jedec] 2]]
            if {$size == 0} { error "JEDEC could not determine capacity; pass size manually" }
        }
        set nchunk [expr {($size + $CHUNK - 1) / $CHUNK}]
        echo [format "RAM-stub full read: %d bytes = %d chunks x %dKB -> %s/" $size $nchunk [expr {$CHUNK/1024}] $outdir]
        set idx 0
        for {set a 0} {$a < $size} {incr a $CHUNK} {
            set n $CHUNK
            if {[expr {$a + $n}] > $size} { set n [expr {$size - $a}] }
            _readchunk $a $n
            dump_image [format "%s/nor_%04d.bin" $outdir $idx] $BUF $n
            if {($idx % 8) == 0} { echo [format "  ... chunk %d/%d @0x%06X" $idx $nchunk $a] }
            incr idx
        }
        echo [format "Done. %d chunks -> %s/. On host: cat %s/nor_*.bin > full.bin" $idx $outdir $outdir]
    }
}
