# Air11 external SPI NOR dumper for OpenOCD
#
# SPI5_SCK  = PH6  AF5
# SPI5_MISO = PH7  AF5
# SPI5_MOSI = PF9  AF5
# NOR_CS    = PH5  GPIO output, active low
#
# The script configures SPI5, loads build/as11-nor-sram-reader.bin into AXI
# SRAM, and uses the target-resident reader to copy the 16 MiB NOR into SRAM
# chunks. OpenOCD then writes each chunk to the output file.
#
# Typical use:
#   make as11-nor-sram-reader
#   ./run-ocd.sh as11
#   > source tcl/as11-nor-flash.tcl
#   > as11_nor_dump as11-nor.bin

namespace eval as11_nor {

variable AS11_NOR_GPIOF_BASE   0x58021400
variable AS11_NOR_GPIOH_BASE   0x58021C00
variable AS11_NOR_RCC_AHB4ENR  0x580244E0
variable AS11_NOR_RCC_APB2ENR  0x580244F0
variable AS11_NOR_RCC_APB2RSTR 0x58024498
variable AS11_NOR_DBGMCU_CR    0x5C001004
variable AS11_NOR_MPU_CTRL     0xE000ED94
variable AS11_NOR_SPI5_BASE    0x40015000

variable AS11_NOR_SIZE         0x01000000
variable AS11_NOR_STUB_ADDR    0x24000000
variable AS11_NOR_STUB_BUFFER  0x24001000
variable AS11_NOR_STUB_BUFSIZE 0x0007D000
variable AS11_NOR_STUB_STACK   0x24080000
variable AS11_NOR_STUB_DONE_PC -1

variable AS11_NOR_MODER   0x00
variable AS11_NOR_OTYPER  0x04
variable AS11_NOR_OSPEEDR 0x08
variable AS11_NOR_PUPDR   0x0C
variable AS11_NOR_BSRR    0x18
variable AS11_NOR_AFRL    0x20
variable AS11_NOR_AFRH    0x24

variable AS11_SPI_CR1  0x00
variable AS11_SPI_CR2  0x04
variable AS11_SPI_CFG1 0x08
variable AS11_SPI_CFG2 0x0C
variable AS11_SPI_SR   0x14
variable AS11_SPI_IFCR 0x18

variable AS11_NOR_STUB_PATH [file join \
    [file normalize [file join [file dirname [info script]] ..]] \
    build as11-nor-sram-reader.bin]

proc _mrw {addr} {
    return [lindex [read_memory $addr 32 1] 0]
}

proc _rmw {addr clear_mask set_bits} {
    set value [_mrw $addr]
    mww $addr [expr {($value & ~$clear_mask) | $set_bits}]
}

proc _enable_clocks {} {
    variable AS11_NOR_RCC_AHB4ENR
    variable AS11_NOR_RCC_APB2ENR

    # GPIOFEN bit 5, GPIOHEN bit 7, SPI5EN bit 20.
    _rmw $AS11_NOR_RCC_AHB4ENR 0 0x000000A0
    _rmw $AS11_NOR_RCC_APB2ENR 0 0x00100000

    # Read back to let the clock enables settle before peripheral accesses.
    _mrw $AS11_NOR_RCC_AHB4ENR
    _mrw $AS11_NOR_RCC_APB2ENR
}

proc _reset_spi5 {} {
    variable AS11_NOR_RCC_APB2RSTR

    set reset_bit 0x00100000
    set value [_mrw $AS11_NOR_RCC_APB2RSTR]
    mww $AS11_NOR_RCC_APB2RSTR [expr {$value | $reset_bit}]
    mww $AS11_NOR_RCC_APB2RSTR [expr {$value & ~$reset_bit}]
}

proc _config_gpio {} {
    variable AS11_NOR_GPIOF_BASE
    variable AS11_NOR_GPIOH_BASE
    variable AS11_NOR_MODER
    variable AS11_NOR_OTYPER
    variable AS11_NOR_OSPEEDR
    variable AS11_NOR_PUPDR
    variable AS11_NOR_BSRR
    variable AS11_NOR_AFRL
    variable AS11_NOR_AFRH

    # PF9 -> SPI5 MOSI, AF5.
    _rmw [expr {$AS11_NOR_GPIOF_BASE + $AS11_NOR_MODER}]   0x000C0000 0x00080000
    _rmw [expr {$AS11_NOR_GPIOF_BASE + $AS11_NOR_OTYPER}]  0x00000200 0x00000000
    _rmw [expr {$AS11_NOR_GPIOF_BASE + $AS11_NOR_OSPEEDR}] 0x000C0000 0x00040000
    _rmw [expr {$AS11_NOR_GPIOF_BASE + $AS11_NOR_PUPDR}]   0x000C0000 0x00080000
    _rmw [expr {$AS11_NOR_GPIOF_BASE + $AS11_NOR_AFRH}]    0x000000F0 0x00000050

    # PH6/PH7 -> SPI5 SCK/MISO, AF5.
    _rmw [expr {$AS11_NOR_GPIOH_BASE + $AS11_NOR_MODER}]   0x0000F000 0x0000A000
    _rmw [expr {$AS11_NOR_GPIOH_BASE + $AS11_NOR_OTYPER}]  0x000000C0 0x00000000
    _rmw [expr {$AS11_NOR_GPIOH_BASE + $AS11_NOR_OSPEEDR}] 0x0000F000 0x00005000
    _rmw [expr {$AS11_NOR_GPIOH_BASE + $AS11_NOR_PUPDR}]   0x0000F000 0x0000A000
    _rmw [expr {$AS11_NOR_GPIOH_BASE + $AS11_NOR_AFRL}]    0xFF000000 0x55000000

    # PH5 -> push-pull GPIO output for active-low chip select. Set it high
    # before switching the pin to output mode.
    mww [expr {$AS11_NOR_GPIOH_BASE + $AS11_NOR_BSRR}] 0x00000020
    _rmw [expr {$AS11_NOR_GPIOH_BASE + $AS11_NOR_MODER}]   0x00000C00 0x00000400
    _rmw [expr {$AS11_NOR_GPIOH_BASE + $AS11_NOR_OTYPER}]  0x00000020 0x00000000
    _rmw [expr {$AS11_NOR_GPIOH_BASE + $AS11_NOR_OSPEEDR}] 0x00000C00 0x00000C00
    _rmw [expr {$AS11_NOR_GPIOH_BASE + $AS11_NOR_PUPDR}]   0x00000C00 0x00000000
}

proc _config_spi5 {} {
    variable AS11_NOR_SPI5_BASE
    variable AS11_SPI_CR1
    variable AS11_SPI_CR2
    variable AS11_SPI_CFG1
    variable AS11_SPI_CFG2
    variable AS11_SPI_SR
    variable AS11_SPI_IFCR

    # STM32H7 SPI v3: 8-bit frames, four-frame FIFO threshold, fPCLK/4,
    # software NSS, mode 0, full duplex.
    mww [expr {$AS11_NOR_SPI5_BASE + $AS11_SPI_CR1}]  0x00000000
    mww [expr {$AS11_NOR_SPI5_BASE + $AS11_SPI_IFCR}] 0xFFFFFFFF
    mww [expr {$AS11_NOR_SPI5_BASE + $AS11_SPI_CR1}]  0x00001000
    mww [expr {$AS11_NOR_SPI5_BASE + $AS11_SPI_CFG1}] 0x10000067
    mww [expr {$AS11_NOR_SPI5_BASE + $AS11_SPI_CFG2}] 0x04400000
    mww [expr {$AS11_NOR_SPI5_BASE + $AS11_SPI_CR2}]  0x00000000

    set cfg2 [_mrw [expr {$AS11_NOR_SPI5_BASE + $AS11_SPI_CFG2}]]
    if {($cfg2 & 0x00400000) == 0} {
        set cr1 [_mrw [expr {$AS11_NOR_SPI5_BASE + $AS11_SPI_CR1}]]
        set sr [_mrw [expr {$AS11_NOR_SPI5_BASE + $AS11_SPI_SR}]]
        error [format "SPI5 MASTER did not stick: CR1=0x%08X CFG2=0x%08X SR=0x%08X" $cr1 $cfg2 $sr]
    }
}

proc _prepare_hardware {} {
    variable AS11_NOR_DBGMCU_CR
    variable AS11_NOR_MPU_CTRL

    halt
    # Freeze IWDG1 while the core is halted between SRAM-reader chunks.
    _rmw $AS11_NOR_DBGMCU_CR 0 0x00000010
    # The reader executes from AXI SRAM. Disable any firmware MPU setup that
    # could leave that SRAM region marked non-executable; reset restores state.
    mww $AS11_NOR_MPU_CTRL 0
    _enable_clocks
    _config_gpio
    _reset_spi5
    _config_spi5
    echo "Air11 NOR SPI5 ready: SCK=PH6 MISO=PH7 MOSI=PF9 CS=PH5"
}

proc _load_stub {} {
    variable AS11_NOR_STUB_ADDR
    variable AS11_NOR_STUB_BUFFER
    variable AS11_NOR_STUB_DONE_PC
    variable AS11_NOR_STUB_PATH

    if {![file exists $AS11_NOR_STUB_PATH]} {
        error "SRAM reader stub not found: $AS11_NOR_STUB_PATH; run: make as11-nor-sram-reader"
    }

    set fh [open $AS11_NOR_STUB_PATH r]
    fconfigure $fh -translation binary
    set data [read $fh]
    close $fh

    set stub_size [string length $data]
    set stub_limit [expr {$AS11_NOR_STUB_BUFFER - $AS11_NOR_STUB_ADDR}]
    if {$stub_size <= 0 || $stub_size > $stub_limit} {
        error [format "invalid SRAM reader size: %d bytes, maximum %d" $stub_size $stub_limit]
    }

    set bkpt [binary format H* "abbe"]
    set bkpt_off [string first $bkpt $data]
    if {$bkpt_off < 0} {
        error "SRAM reader stub has no BKPT #0xAB marker: $AS11_NOR_STUB_PATH"
    }
    if {[string first $bkpt $data [expr {$bkpt_off + 1}]] >= 0} {
        error "SRAM reader stub has multiple BKPT #0xAB markers: $AS11_NOR_STUB_PATH"
    }

    set AS11_NOR_STUB_DONE_PC [expr {$AS11_NOR_STUB_ADDR + $bkpt_off}]
    load_image $AS11_NOR_STUB_PATH $AS11_NOR_STUB_ADDR bin
}

proc _set_reg {names value} {
    foreach name $names {
        if {![catch {reg $name $value}]} {
            return
        }
    }
    error "cannot set CPU register [join $names /]"
}

proc _read_reg {names} {
    foreach name $names {
        if {[catch {set text [capture "reg $name"]}]} {
            continue
        }
        if {[regexp {0x[0-9A-Fa-f]+} $text value]} {
            return [expr {$value}]
        }
    }
    error "cannot read CPU register [join $names /]"
}

proc _prepare_stub_context {} {
    variable AS11_NOR_STUB_STACK

    # Start in Thread mode with an MSP-backed stack. This avoids carrying a
    # Handler-mode IPSR into the blob when the firmware was halted in an ISR.
    _set_reg {xPSR xpsr} 0x01000000
    _set_reg {control CONTROL} 0
    _set_reg {faultmask FAULTMASK} 0
    _set_reg {basepri BASEPRI} 0
    _set_reg {msp MSP} $AS11_NOR_STUB_STACK
    _set_reg {psp PSP} $AS11_NOR_STUB_STACK
    _set_reg {sp SP} $AS11_NOR_STUB_STACK
    _set_reg {primask PRIMASK} 1
}

proc _run_stub {addr len} {
    variable AS11_NOR_STUB_ADDR
    variable AS11_NOR_STUB_BUFFER
    variable AS11_NOR_STUB_BUFSIZE
    variable AS11_NOR_STUB_DONE_PC

    if {$len <= 0 || $len > $AS11_NOR_STUB_BUFSIZE} {
        error [format "stub read length out of range: %d, maximum %d" $len $AS11_NOR_STUB_BUFSIZE]
    }

    _prepare_stub_context
    reg r0 $addr
    reg r1 $len
    reg r2 $AS11_NOR_STUB_BUFFER
    resume [expr {$AS11_NOR_STUB_ADDR | 1}]
    wait_halt 10000

    set pc [_read_reg {pc PC}]
    if {$pc != $AS11_NOR_STUB_DONE_PC && $pc != [expr {$AS11_NOR_STUB_DONE_PC + 2}]} {
        error [format "SRAM reader stopped unexpectedly at pc=0x%08X, expected BKPT at 0x%08X" $pc $AS11_NOR_STUB_DONE_PC]
    }
}

proc dump {outfile} {
    variable AS11_NOR_SIZE
    variable AS11_NOR_STUB_BUFFER
    variable AS11_NOR_STUB_BUFSIZE

    if {$outfile eq ""} {
        error "output filename must not be empty"
    }

    set tmp [format "%s.chunk" $outfile]
    set output ""
    set t0 [clock milliseconds]

    set failed [catch {
        _prepare_hardware
        _load_stub

        set output [open $outfile w]
        fconfigure $output -translation binary
        echo [format "Dumping Air11 NOR: %d bytes to %s (%d-byte SRAM chunks)" $AS11_NOR_SIZE $outfile $AS11_NOR_STUB_BUFSIZE]

        set next_report 0x100000
        for {set addr 0} {$addr < $AS11_NOR_SIZE} {incr addr $AS11_NOR_STUB_BUFSIZE} {
            set len $AS11_NOR_STUB_BUFSIZE
            if {[expr {$addr + $len}] > $AS11_NOR_SIZE} {
                set len [expr {$AS11_NOR_SIZE - $addr}]
            }

            _run_stub $addr $len
            dump_image $tmp $AS11_NOR_STUB_BUFFER $len

            set chunk [open $tmp r]
            fconfigure $chunk -translation binary
            puts -nonewline $output [read $chunk]
            close $chunk
            file delete $tmp

            set done [expr {$addr + $len}]
            if {$addr == 0 || $done >= $next_report || $done >= $AS11_NOR_SIZE} {
                set pct [expr {100.0 * $done / $AS11_NOR_SIZE}]
                set elapsed [expr {([clock milliseconds] - $t0) / 1000.0}]
                echo [format "  0x%06X / 0x%06X  %5.1f%%  %.0fs" $done $AS11_NOR_SIZE $pct $elapsed]
                while {$next_report <= $done} {
                    incr next_report 0x100000
                }
            }
        }
    } failure]

    if {$output ne ""} {
        catch {close $output}
    }
    catch {file delete $tmp}

    # AXI SRAM now contains the reader and NOR data. Never resume the saved
    # firmware context; restart the device from reset on every exit path.
    echo "Resetting target after NOR dump..."
    set reset_failed [catch {reset run} reset_failure]

    if {$failed} {
        if {$reset_failed} {
            error "$failure; target reset also failed: $reset_failure"
        }
        error $failure
    }
    if {$reset_failed} {
        error "NOR dump completed, but target reset failed: $reset_failure"
    }

    set elapsed [expr {([clock milliseconds] - $t0) / 1000.0}]
    echo [format "NOR dump complete: %d bytes in %.0fs -> %s" $AS11_NOR_SIZE $elapsed $outfile]
}

}

proc ::as11_nor_dump {outfile} {
    ::as11_nor::dump $outfile
}

echo "Loaded Air11 SPI5 NOR dumper. Run: as11_nor_dump <outfile>"
