#!/bin/bash
# run-ocd-jlink.sh -- a J-Link variant of run-ocd.sh.
# run-ocd.sh hardcodes ST-Link (interface/stlink.cfg); this uses J-Link + SWD.
#
# Usage:  ./run-ocd-jlink.sh [-s SERIAL] [config]
#   config     OpenOCD target config name (loads tcl/<config>.cfg), default airsense.
#              For AirSense/AirCurve 11 use as11:   ./run-ocd-jlink.sh as11
#   -s SERIAL  select a specific J-Link by serial (only needed with multiple adapters).
#
# Once up, OpenOCD stays running (telnet 4444 / gdb 3333). In another terminal:
#   nc localhost 4444        # macOS has no telnet; use nc for the interactive console
# then type identify / flash info 0 / dump etc. Ctrl-C stops the server.
#
# For a single one-shot command you don't need this script; just:
#   openocd -f interface/jlink.cfg -c "transport select swd" \
#           -f tcl/as11.cfg -c "<command>" -c "shutdown"

# Always run from the script's own directory (repo root) so tcl/ paths resolve.
cd "$(dirname "$0")" || exit 1

usage() {
    echo "Usage: $0 [-s SERIAL] [config]   (config defaults to airsense; use as11 for AS11/AC11)"
}

adapter_serial=
positional=()
while (( $# > 0 )); do
    case "$1" in
        -s)
            (( $# >= 2 )) || { usage >&2; exit 2; }
            adapter_serial=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -*)
            usage >&2
            exit 2
            ;;
        *)
            positional+=("$1")
            shift
            ;;
    esac
done
(( ${#positional[@]} <= 1 )) || { usage >&2; exit 2; }
cfg=${positional[0]:-airsense}

if [[ ! -f "tcl/${cfg}.cfg" ]]; then
    echo "config not found: tcl/${cfg}.cfg (cwd $(pwd))" >&2
    exit 1
fi

command -v openocd >/dev/null 2>&1 || {
    echo "openocd not found; install it first (e.g. brew install open-ocd)" >&2
    exit 1
}

openocd_args=(-f interface/jlink.cfg -c "transport select swd")
if [[ -n "$adapter_serial" ]]; then
    openocd_args+=(-c "adapter serial $adapter_serial")
fi
openocd_args+=(-f "tcl/${cfg}.cfg")

echo "+ openocd ${openocd_args[*]}"
exec openocd "${openocd_args[@]}"
