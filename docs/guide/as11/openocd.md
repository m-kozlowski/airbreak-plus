# Air11 OpenOCD and Firmware Dump

Using OpenOCD to connect to the Air11 processor and back up its firmware, with
optional OTA-key retrieval and hardware RTC correction.

## Start OpenOCD

Connect and power the device as described in [Connection](connection.md#swd),
then start OpenOCD from the repository root:

```bash
./run-ocd.sh as11
```

The configuration initializes the STM32H753 target and loads the Air11 helper
commands. In another terminal, open the OpenOCD console:

```bash
telnet localhost 4444
```

## Dump the Firmware

At the OpenOCD prompt:

```tcl
dump
```

This writes the complete internal flash to `as11.bin` in the directory where
OpenOCD was started. Preserve an unchanged copy under a device-specific private
filename before patching.

## Optional: Retrieve the OTA Key

If you plan to flash future updates over Bluetooth, the current SWD session can
also be used to
[retrieve the device OTA key](../../as11/ota_protocol.md#retrieving-the-local-ota-key).

## Optional: Sync the RTC

Since the device is already open and connected over SWD, you can also check or
correct its hardware clock. This optional maintenance step is independent of
the firmware dump, patching, and flashing workflow.

Read the hardware RTC:

```tcl
rtc::now
```

Set it from the host UTC clock:

```tcl
rtc::sync
```

Or set an explicit UTC date and time:

```tcl
rtc::set_time YYYY-MM-DD HH:MM:SS
```

Continue with [Patching](patching.md).
