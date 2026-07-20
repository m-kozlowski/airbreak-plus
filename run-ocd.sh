#!/bin/bash

usage() {
    echo "Usage: $0 [-s SERIAL] [config]"
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

stlink_available() {
    lsusb | grep -qiE 'st-?link'
}

# WSL2
if [[ $(uname -r) == *microsoft-standard-WSL2* ]]; then
    if [[ -n "$adapter_serial" ]] || ! stlink_available; then
        ./usbattach.sh 'ST-?Link' || exit
    fi
    stlink_available || { echo "No ST-Link available in WSL" >&2; exit 1; }
fi

openocd_args=(-f interface/stlink.cfg)
if [[ -n "$adapter_serial" ]]; then
    openocd_args+=(-c "adapter serial $adapter_serial")
fi
openocd_args+=(-f "tcl/${cfg}.cfg")

openocd "${openocd_args[@]}"
