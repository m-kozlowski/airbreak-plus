# AirSense/AirCurve 11 provider key page reader for OpenOCD.
#
# Self-contained, read-only, and intentionally small:
#   - reset-halt before touching SPI NOR
#   - configure only SPI5 pins/peripheral known from firmware:
#       SCK=PH6 MISO=PH7 MOSI=PF9 CS=PH5
#   - read one 32-byte slot from the provider OTA key page
#   - print the raw key as 64 hex characters
#   - reset-run after the read attempt
#

namespace eval as11_keys {
    variable GPIOF 0x58021400
    variable GPIOH 0x58021C00
    variable RCC_AHB4ENR  0x580244E0
    variable RCC_APB2ENR  0x580244F0
    variable RCC_APB2RSTR 0x58024498
    variable SPI5 0x40015000
    variable OTA_PAGE 0x100
    variable KEY_SIZE 0x20
    variable KEY_SLOTS 8
    variable OTA_INDEX 0

    proc _mrw {addr} {
        return [lindex [read_memory $addr 32 1] 0]
    }

    proc _rmw {addr clear set} {
        set v [_mrw $addr]
        mww $addr [expr {($v & ~$clear) | $set}]
    }

    proc _halted {} {
        set t [target current]
        if {[$t curstate] ne "halted"} {
            error "target is not halted"
        }
    }

    proc _cs_high {} {
        variable GPIOH
        mww [expr {$GPIOH + 0x18}] 0x00000020
    }

    proc _cs_low {} {
        variable GPIOH
        mww [expr {$GPIOH + 0x18}] 0x00200000
    }

    proc _wait {mask name} {
        variable SPI5
        set sr 0
        for {set i 0} {$i < 3000} {incr i} {
            set sr [_mrw [expr {$SPI5 + 0x14}]]
            if {($sr & $mask) != 0} {
                return
            }
        }
        error [format "SPI5 timeout waiting for %s; SR=0x%08X" $name $sr]
    }

    proc _setup_spi5 {} {
        variable GPIOF
        variable GPIOH
        variable RCC_AHB4ENR
        variable RCC_APB2ENR
        variable RCC_APB2RSTR
        variable SPI5

        _halted

        # GPIOFEN | GPIOHEN, then SPI5EN.
        _rmw $RCC_AHB4ENR 0 0x000000A0
        _rmw $RCC_APB2ENR 0 0x00100000
        _mrw $RCC_AHB4ENR
        _mrw $RCC_APB2ENR

        # PF9 = SPI5_MOSI AF5, pull-down.
        _rmw [expr {$GPIOF + 0x00}] 0x000C0000 0x00080000
        _rmw [expr {$GPIOF + 0x04}] 0x00000200 0
        _rmw [expr {$GPIOF + 0x08}] 0x000C0000 0x00040000
        _rmw [expr {$GPIOF + 0x0C}] 0x000C0000 0x00080000
        _rmw [expr {$GPIOF + 0x24}] 0x000000F0 0x00000050

        # PH6/PH7 = SPI5_SCK/MISO AF5, pull-down.
        _rmw [expr {$GPIOH + 0x00}] 0x0000F000 0x0000A000
        _rmw [expr {$GPIOH + 0x04}] 0x000000C0 0
        _rmw [expr {$GPIOH + 0x08}] 0x0000F000 0x00005000
        _rmw [expr {$GPIOH + 0x0C}] 0x0000F000 0x0000A000
        _rmw [expr {$GPIOH + 0x20}] 0xFF000000 0x55000000

        # PH5 = active-low CS GPIO output.
        _cs_high
        _rmw [expr {$GPIOH + 0x00}] 0x00000C00 0x00000400
        _rmw [expr {$GPIOH + 0x04}] 0x00000020 0
        _rmw [expr {$GPIOH + 0x08}] 0x00000C00 0x00000C00
        _rmw [expr {$GPIOH + 0x0C}] 0x00000C00 0

        set bit 0x00100000
        set v [_mrw $RCC_APB2RSTR]
        mww $RCC_APB2RSTR [expr {$v | $bit}]
        mww $RCC_APB2RSTR [expr {$v & ~$bit}]

        # STM32H7 SPI v3, 8-bit frames, 4-frame RX threshold, fPCLK/4, mode 0.
        mww [expr {$SPI5 + 0x00}] 0x00001000
        mww [expr {$SPI5 + 0x18}] 0xFFFFFFFF
        mww [expr {$SPI5 + 0x08}] 0x10000067
        mww [expr {$SPI5 + 0x0C}] 0x04400000
        mww [expr {$SPI5 + 0x04}] 0
    }

    proc _read32 {addr} {
        variable SPI5
        set len 32
        set frames [expr {$len + 4}]
        set words [expr {$frames / 4}]
        set cmd [expr {0x03 | ((($addr >> 16) & 0xff) << 8) | ((($addr >> 8) & 0xff) << 16) | (($addr & 0xff) << 24)}]
        set out {}

        _cs_low
        set status [catch {
            mww [expr {$SPI5 + 0x00}] 0x00001000
            mww [expr {$SPI5 + 0x18}] 0xFFFFFFFF
            mww [expr {$SPI5 + 0x04}] $frames
            mww [expr {$SPI5 + 0x00}] 0x00001001

            for {set wi 0} {$wi < $words} {incr wi} {
                if {$wi == 0} {
                    set tx $cmd
                } else {
                    set tx 0
                }
                _wait 0x00000002 "TXP"
                mww [expr {$SPI5 + 0x20}] $tx
                if {$wi == 0} {
                    mww [expr {$SPI5 + 0x00}] 0x00001201
                }
                _wait 0x00000001 "RXP"
                set rx [_mrw [expr {$SPI5 + 0x30}]]
                if {$wi != 0} {
                    for {set j 0} {$j < 4} {incr j} {
                        lappend out [expr {($rx >> ($j * 8)) & 0xff}]
                    }
                }
            }
            _wait 0x00000008 "EOT"
            mww [expr {$SPI5 + 0x18}] 0xFFFFFFFF
            mww [expr {$SPI5 + 0x00}] 0x00001000
        } err]
        _cs_high
        if {$status != 0} {
            error $err
        }
        return $out
    }

    proc _all_same {bytes value} {
        foreach b $bytes {
            if {($b & 0xff) != $value} {
                return 0
            }
        }
        return 1
    }

    proc _hex {bytes} {
        set hex ""
        foreach b $bytes {
            append hex [format "%02X" [expr {$b & 0xff}]]
        }
        return $hex
    }

    proc _resolve_key_index {index} {
        variable KEY_SLOTS
        variable OTA_INDEX

        set name [string toupper $index]
        if {$name eq "OTA"} {
            return $OTA_INDEX
        }

        if {[catch {expr {int($index)}} idx] != 0} {
            error "invalid provider key index: $index"
        }
        if {$idx < 0 || $idx >= $KEY_SLOTS} {
            error [format "provider key index out of range: %d (valid 0..%d)" $idx [expr {$KEY_SLOTS - 1}]]
        }
        return $idx
    }

    proc _key_offset {idx} {
        variable OTA_PAGE
        variable KEY_SIZE
        return [expr {$OTA_PAGE + ($idx * $KEY_SIZE)}]
    }

    proc key {{index OTA}} {
        set idx [_resolve_key_index $index]
        set addr [_key_offset $idx]

        set status [catch {
            # Prefer a reset-halt for a clean state; fall back to a plain halt
            # if reset-halt does not land (observed on secure boot / some debuggers).
            catch {reset halt}
            set _t [target current]
            if {[$_t curstate] ne "halted"} { halt }
            if {[llength [info commands freeze_iwdg]] != 0} {
                catch {freeze_iwdg}
            }
            _setup_spi5

            set key [_read32 $addr]
            if {[llength $key] != 32} {
                error "short provider key read"
            }
            if {[_all_same $key 0] || [_all_same $key 0xff]} {
                error "refusing suspicious all-00/all-ff provider key slot read"
            }

            set hex [_hex $key]
            echo $hex
            set hex
        } result opts]

        catch {reset run}
        if {$status != 0} {
            error $result
        }
        return ""
    }

    proc help {} {
        echo {AS11 provider key page reader (::as11_keys)}
        echo {===================================================}
        echo ""
        echo {  as11_keys::key          read OTA key slot, print hex, reset run}
        echo {  as11_keys::key OTA      same as above}
        echo {  as11_keys::key <index>  read provider key slot 0..7}
    }
}

if {[info level] == 0} {
    as11_keys::help
} else {
    echo "[info script] loaded."
    echo {    as11_keys::key to fetch OTA key}
    echo {    as11_keys::help for instructions}
}
