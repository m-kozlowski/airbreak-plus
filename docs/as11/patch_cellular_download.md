# AirbreakDownload

`patch-cellular-download` adds the `AirbreakDownload` root to JSON RPC. It
uses the firmware's cellular HTTP client and upgrade staging storage to fetch
one file into `nor:2:\UPGRADE\Upgrade.abc`.

The patch downloads and retains the file. It does not validate or install it.

## Start a download

Set `AirbreakDownload` to an object containing the complete HTTP URL:

```bash
./python/as11_config.py -d can:/dev/ttyACM0 set AirbreakDownload \
    '{"url":"http://server.example/file.ota"}' \
    --type json
```

Only plain `http://` URLs are accepted. The URL must contain a host and an
absolute path; an optional port may follow the host. The server must return a
`Content-Length` header, and the response may contain up to 2252800 bytes.

A request is rejected while another local or cloud firmware download occupies
the native upgrade path. Local requests do not require cloud registration or
a pending broker command.

## Read the state

```bash
./python/as11_config.py -d can:/dev/ttyACM0 get AirbreakDownload
```

The result has this form:

```json
{
  "state": "downloading",
  "bytesStored": 524288,
  "size": 0
}
```

| `state` | Meaning |
|---------|---------|
| `idle` | No request has been made. |
| `queued` | The request is waiting for the cellular FileFetcher. |
| `downloading` | The native FileFetcher has accepted the request. |
| `complete` | The complete response has been stored in upgrade staging. |
| `error` | The native fetch or storage path failed. |
| `external` | Stock firmware-change metadata occupies the upgrade path. |
| `unavailable` | The cellular FileFetcher task is not available. |

`bytesStored` is the native persistent transfer counter. `size` is zero while
the response length is not yet known and contains the complete downloaded size
after `state` becomes `complete`. A download interrupted by a transport failure
or restart remains resumable through the native HTTP range-fetch path.

## Extract the file

After the state becomes `complete`, enter the bootloader service and read the
external NOR:

```bash
./python/as11_flash.py -d can:/dev/ttyACM0 service read-nor nor.bin
./python/as11_nor_tool.py nor.bin upgrade-get downloaded.abc
```

The bootloader service commands are documented in
[as11_flash](../tools/as11_flash.md#bootloader-service). The staging format and
extraction commands are documented in
[as11_nor_tool](../tools/as11_nor_tool.md#staged-upgrade).

## Firmware support

The patch supports application version 8.6.0 and requires the shared
[RPC dispatcher](patch_rpc_dispatcher.md).
