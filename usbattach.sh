#!/bin/bash

rx='^([0-9]+-[0-9]+)[[:space:]]+([0-9a-f]{4}:[0-9a-f]{4})[[:space:]]+(.*)[[:space:]]+(Shared|Not shared)'

TIMEOUT=10
failed=0
name_filter=${1:-}

usb_count() {
    lsusb | grep -ci "$1"
}

mapfile -t devices < <(usbipd.exe list)

for line in "${devices[@]}"; do
    if [[ $line =~ $rx ]]; then
        busid="${BASH_REMATCH[1]}"
        vidpid="${BASH_REMATCH[2]}"
        name="${BASH_REMATCH[3]}"
        state="${BASH_REMATCH[4]}"

        [[ -z "$name_filter" || $name =~ $name_filter ]] || continue

        # attach only previously shared devices
        if [[ "$state" == "Shared" ]] ; then
            printf 'Attaching %s [%s] %s\n' "$busid" "$vidpid" "$name"
            attached_before=$(usb_count "$vidpid")
            if ! usbipd.exe usbipd attach --wsl --busid "$busid"; then
                failed=1
                continue
            fi

            echo "Waiting for USB device ${vidpid}..."
            started=$SECONDS
            until (( $(usb_count "$vidpid") > attached_before )); do
                sleep 1
                if (( SECONDS - started >= TIMEOUT )); then
                    echo "Timeout waiting for USB device ${busid}"
                    failed=1
                    break
                fi
            done
        fi
    fi
done

exit "$failed"
