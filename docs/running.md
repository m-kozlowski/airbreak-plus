# Make everything

`make`

# Patch the bin

./patch-airsense stm32.bin stm32-toph.bin

# Pass usbipd to WSL

.\bind-stlink-wsl.ps1

# Run OpenOCD

sudo openocd -f interface/stlink-v2.cfg -f 'tcl/airsense.cfg'

# Connect to machine

telnet localhost 4444

# Flash it

flash_new stm32-asv-plus.bin

# Running notes

These notes cover the WSL/OpenOCD workflow used for dumping, patching, and flashing an AirCurve/AirSense 10 image from this checkout.

## Safety baseline

Only patch a known 0401 firmware image. The required source image for this run was:

```text
7071d0ea64ef4b51466abfeb075015f4606e803140a08423e0134a5db372db36  stm32.bin
```

The patcher now checks the input hash before copying or modifying anything. For this hash it should print:

```text
stm32.bin: AirCurve 10 VAuto 37164-SX567-0401 binary identified
```

If the machine reports "not modified" in OpenOCD, do not treat that as proof that the flash is stock. In this session, one dumped image reported as stock but had this unexpected hash:

```text
c763360877ee2131878eb287eed80d3d2149dddc3ae4fa15fec33062a6dc4283  stm32.bin
```

That hash was later also produced by `build/stm32-asv-plus_no-squarewave.bin`, so it was not a safe source image to patch as if it were stock.

## WSL and ST-Link setup

From PowerShell in the repo root, attach the ST-Link to WSL:

```powershell
.\bind-stlink-wsl.ps1
```

In WSL, confirm the ST-Link is visible:

```bash
lsusb
```

Expected device line:

```text
0483:3748 STMicroelectronics ST-LINK/V2
```

If OpenOCD fails with `Error: open failed`, WSL does not have the ST-Link attached yet. Run the PowerShell bind script again or check `usbipd list` on Windows.

## OpenOCD

Start OpenOCD from WSL in the repo root:

```bash
cd /mnt/e/Github/airbreak-kozlowski
openocd -f interface/stlink.cfg -f tcl/airsense.cfg
```

The checked-in `run-ocd.sh` may fail in WSL if it has CRLF line endings. The direct `openocd` command above avoids that issue.

Successful startup should include lines like:

```text
STLINK V2J29S7 (API v2) VID:PID 0483:3748
Target voltage: 3.228458
[stm32f4x.cpu] Cortex-M4 r0p1 processor detected
Listening on port 4444 for telnet connections
```

The repo's Tcl commands are then available on the OpenOCD console.

## Dump firmware

With OpenOCD still running, connect in another terminal:

```bash
telnet localhost 4444
```

At the OpenOCD prompt:

```text
dump
```

This writes `stm32.bin` in OpenOCD's working directory. Verify size and hash in WSL:

```bash
cd /mnt/e/Github/airbreak-kozlowski
ls -l stm32.bin
wc -c < stm32.bin
sha256sum stm32.bin
```

The dump must be exactly `1048576` bytes.

For scripted console commands, `nc` worked better than `telnet` once newline quoting was kept simple:

```bash
(echo dump; echo exit) | nc -w 5 127.0.0.1 4444
```

## Build everything

Plain `make` should create all default firmware variants:

```bash
make
```

Because the local shell scripts had CRLF endings during this run, plain WSL `make` could not execute `./patch-airsense` directly. The workaround was to build from a temporary LF-normalized copy and copy the generated images back:

```bash
rm -rf /tmp/airbreak-make
mkdir -p /tmp/airbreak-make
tar --exclude=.git -cf - . | tar -C /tmp/airbreak-make -xf -
cd /tmp/airbreak-make
find . -type f \( -name 'patch-airsense*' -o -name '*.sh' \) -exec perl -pi -e 's/\r\n/\n/g' {} +
chmod +x patch-airsense patch-airsense-s9 patch-airsense-s11 run-ocd.sh run-gdb.sh usbattach.sh 2>/dev/null || true
make
cp build/stm32*.bin /mnt/e/Github/airbreak-kozlowski/build/
```

Generated images from the known source image:

```text
d4393ce8f51f6aca9c26107f27b84151cbbb9b2d9fc538a1c531beb99ced9550  build/stm32-patched.bin
e70d3090e7c15df11c7ce72733cc1b26776ff77db23b3199a42acb9ffb167fc9  build/stm32-graph.bin
a34eb062b63375851b1a133b0345e96d717bc34b1e3f414491cde5b76496889f  build/stm32-asv-plus.bin
c763360877ee2131878eb287eed80d3d2149dddc3ae4fa15fec33062a6dc4283  build/stm32-asv-plus_no-squarewave.bin
ea6575d78c507b6c0df250e542551f915919863017b640eee76db866946de3f9  build/stm32-asv-plus_with-backup.bin
```

All of these were `1048576` bytes.

## Build only ASV Plus

To build only the ASV Plus image:

```bash
PATCH_CODE=1 PATCH_ASV_TASK_WRAPPER=1 PATCH_VAUTO_WRAPPER=1 PATCH_S=1 ./patch-airsense stm32.bin build/stm32-asv-plus.bin
```

If CRLF line endings are still present, run through an LF-normalized temporary copy:

```bash
perl -pe 's/\r\n/\n/g' patch-airsense > /tmp/patch-airsense-lf
chmod +x /tmp/patch-airsense-lf
PATCH_CODE=1 PATCH_ASV_TASK_WRAPPER=1 PATCH_VAUTO_WRAPPER=1 PATCH_S=1 /tmp/patch-airsense-lf stm32.bin build/stm32-asv-plus.bin
```

The expected ASV Plus output from the known source image is:

```text
a34eb062b63375851b1a133b0345e96d717bc34b1e3f414491cde5b76496889f  build/stm32-asv-plus.bin
```

## Flash firmware

With OpenOCD running and the machine connected, use the OpenOCD console:

```bash
telnet localhost 4444
```

Flash the ASV Plus image:

```text
flash_new build/stm32-asv-plus.bin
```

The Tcl command handles watchdog setup, erasing/writing flash, verification, watchdog reset, and reboot.

To restore the source image:

```text
flash_new stm32.bin
```
