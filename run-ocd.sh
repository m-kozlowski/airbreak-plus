#!/bin/bash

usage() {
    echo "Usage: $0 [-s SERIAL] [--interface stlink|jlink] [--jlink] [config]"
}

adapter_serial=
interface=stlink
positional=()
while (( $# > 0 )); do
    case "$1" in
        -s)
            (( $# >= 2 )) || { usage >&2; exit 2; }
            adapter_serial=$2
            shift 2
            ;;
        --interface)
            (( $# >= 2 )) || { usage >&2; exit 2; }
            interface=$2
            shift 2
            ;;
        --jlink)
            interface=jlink
            shift
            ;;
        -h)
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

case "$interface" in
    stlink|jlink) ;;
    *) usage >&2; exit 2 ;;
esac

adapter_filter() {
    case "$interface" in
        stlink) echo 'ST-?Link' ;;
        jlink) echo 'J-Link|SEGGER' ;;
    esac
}

adapter_available() {
    lsusb | grep -qiE "$(adapter_filter)"
}

# WSL2
if [[ $(uname -r) == *microsoft-standard-WSL2* ]]; then
    if [[ -n "$adapter_serial" ]] || ! adapter_available; then
        ./usbattach.sh "$(adapter_filter)" || exit
    fi
    adapter_available || { echo "No $interface adapter available in WSL" >&2; exit 1; }
fi

case "$interface" in
    stlink)
        openocd_args=(-f interface/stlink.cfg)
        ;;
    jlink)
        openocd_args=(-f interface/jlink.cfg -c "transport select swd")
        ;;
esac
if [[ -n "$adapter_serial" ]]; then
    openocd_args+=(-c "adapter serial $adapter_serial")
fi
openocd_args+=(-f "tcl/${cfg}.cfg")

openocd "${openocd_args[@]}"
