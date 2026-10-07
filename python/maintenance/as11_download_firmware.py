#!/usr/bin/env python3
"""Fetch firmware variants through AirbreakDownload and extract each OTA from NOR."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit

PYTHON_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_DIR))
from lib.as11_nor import As11NorImage

# OTA suffix candidates from the ResScan variant catalog; availability is
# established by downloading, not by the catalog entry.
VARIANT_SUFFIXES = {
    1: 'CPAP', 2: 'Elite', 3: 'AutoSet',
    5: 'VAutoEU', 6: 'VAutoAmericas', 7: 'VAutoGermany',
    8: 'VPAPSAmericas', 9: 'VPAPSGermany', 10: 'VPAPST', 12: 'AutoCSSleep',
}
KNOWN_PACKAGES = {'15.8.4.0': 'FG28.2', '16.8.5.0': 'FG29.2', '17.8.6.0': 'FG30.1'}


def requested_jobs(args):
    if args.urls:
        urls = list(dict.fromkeys(line.strip() for line in args.urls.read_text(encoding='utf-8').splitlines()
                                 if line.strip() and not line.lstrip().startswith('#')))
        entries = [(url, url) for url in urls]
    else:
        if not args.version or not re.fullmatch(r'\d+\.\d+\.\d+\.\d+', args.version):
            raise ValueError('supply the full release, e.g. 17.8.6.0, or --urls FILE')
        if not args.git or not re.fullmatch(r'[0-9a-fA-F]{7,40}', args.git):
            raise ValueError('--git must contain the firmware git identifier')
        packages = args.package
        if not packages:
            known = KNOWN_PACKAGES.get(args.version)
            # Observed FG generations are data_version + 13. Revisions are
            # independent: try .1/.2 as candidates, never as a verified map.
            major = int(args.version.split('.')[0]) + 13
            packages = [known] if known else [f'FG{major}.1', f'FG{major}.2']
        if any(not re.fullmatch(r'FG\d+\.\d+', item) for item in packages):
            raise ValueError('--package expects FG<number>.<revision>')
        variants = args.vids or list(VARIANT_SUFFIXES)
        entries = []
        for vid in dict.fromkeys(variants):
            if vid not in VARIANT_SUFFIXES:
                raise ValueError(f'no suffix for VID {vid}; use --urls for an explicit URL')
            for package in dict.fromkeys(packages):
                filename = f'{package}-{args.git.lower()}-CS04600.{args.version}.{vid:02d}.00.{VARIANT_SUFFIXES[vid]}.ota'
                entries.append((vid, args.server.rstrip('/') + '/' + filename))
    if not entries:
        raise ValueError('URL list is empty')
    jobs = []
    filenames = set()
    for variant, url in entries:
        parsed = urlsplit(url)
        filename = Path(parsed.path).name
        if parsed.scheme != 'http' or not parsed.hostname or filename in ('', '.', '..'):
            raise ValueError(f'expected an HTTP URL with a filename: {url}')
        filename = str(Path(filename).with_suffix('.abc'))
        if filename in filenames:
            raise ValueError(f'two URLs would write {filename}')
        filenames.add(filename)
        jobs.append({'variant': variant, 'url': url, 'file': filename, 'state': 'pending'})
    return jobs


def run_tool(tool, device, *arguments, capture=False):
    command = [sys.executable, str(PYTHON_DIR / tool), '-d', device, *arguments]
    return subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE if capture else None).stdout


def config_json(device, *arguments):
    response = json.loads(run_tool('as11_config.py', device, *arguments, capture=True))
    if 'error' in response:
        raise RuntimeError(f"{arguments[0]}: {response['error']}")
    return response


def rpc(device, method, value=None):
    arguments = [method, 'AirbreakDownload']
    if value is not None:
        arguments += [json.dumps(value), '--type', 'json']
    response = config_json(device, *arguments)
    return response['result']['AirbreakDownload']


def record_download_error(device, job, output):
    # Use the device clock, since event timestamps need not match the host.
    # These are events in the attempt's time window, not request-ID correlation.
    if 'fromDateTime' not in job:
        print('  no event boundary saved for this attempt', flush=True)
        return
    try:
        decoded = config_json(device, 'spool', 'CellularActivityEvents',
                              '--from-dt', job['fromDateTime'], '--format', 'json')
        event_file = output / (job['file'] + '.cellular.json')
        event_file.write_text(json.dumps(decoded, indent=2) + '\n', encoding='utf-8')
        job['cellularEventsFile'] = event_file.name
        job['httpStatuses'] = [field['raw'] for event in decoded['records']
                               if event['name'] == 'HttpResponseStatus'
                               for field in event['extraFields'] if field['name'] == 'http_status']
        job['networkEvents'] = [event['name'] for event in decoded['records']
                                if event['name'] in ('TcpConnectStarted', 'TcpConnected', 'TcpConnectFailed',
                                                     'TcpDisconnected', 'HttpResponseTimeout')]
        statuses = ', '.join(str(value) for value in job['httpStatuses']) or 'no status recorded'
        print(f"  HTTP: {statuses}; stored: {job['bytesStored']} bytes", flush=True)
        if job['networkEvents']:
            print('  Network: ' + ' -> '.join(job['networkEvents']), flush=True)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        job['cellularEventsError'] = str(exc)
        print(f'  could not read cellular events: {exc}', file=sys.stderr)


def service(device, *arguments):
    run_tool('as11_flash.py', device, 'service', *arguments)


def save_queue(path, queue):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(queue, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def load_queue(jobs, output, device):
    path = output / 'downloads.json'
    if path.exists():
        queue = json.loads(path.read_text(encoding='utf-8'))
        if queue['device'] != device:
            raise ValueError('this output directory belongs to a different device selection')
    else:
        queue = {'device': device, 'jobs': []}
    previous = {job['url']: job for job in queue['jobs']}
    selected = []
    for request in jobs:
        job = previous.get(request['url'])
        if job is None:
            job = request
            if (output / job['file']).exists():
                raise ValueError(f"output already exists: {job['file']}")
            queue['jobs'].append(job)
        elif job['state'] in ('error', 'skipped', 'partial'):
            attempt = job.get('attempt', 0)
            job.clear()
            job.update(request)
            job['attempt'] = attempt
        job['variant'] = request['variant']
        selected.append(job)
    return path, queue, selected


def wait_for_rpc(device, timeout, interval):
    deadline = time.monotonic() + timeout
    while True:
        try:
            status = rpc(device, 'get')
            if status['state'] != 'unavailable':
                return status
        except (subprocess.CalledProcessError, RuntimeError, KeyError, json.JSONDecodeError):
            pass
        if time.monotonic() >= deadline:
            raise TimeoutError('application RPC did not become ready')
        time.sleep(interval)


def wait_for_download(device, timeout, interval):
    deadline = time.monotonic() + timeout
    previous = None
    while True:
        status = rpc(device, 'get')
        progress = (status['state'], status['bytesStored'])
        if progress != previous:
            print(f"  {progress[0]}: {progress[1]} bytes", flush=True)
            previous = progress
        if status['state'] in ('complete', 'error'):
            return status
        if status['state'] not in ('queued', 'downloading', 'unavailable'):
            raise RuntimeError(f"download left the local queue: {status['state']}")
        if time.monotonic() >= deadline:
            raise TimeoutError('download timeout; progress saved, rerun to continue waiting')
        time.sleep(interval)


def download_queue(args):
    output = args.output
    if not args.device.startswith(('can:', 'tcp:')):
        raise ValueError('-d requires a CAN adapter or TCP bridge')
    state_path, queue, jobs = load_queue(requested_jobs(args), output, args.device)
    # The staging file is shared by every URL. Finish saving an earlier job
    # even when it was omitted from the new VID selection.
    unfinished = [job for job in queue['jobs'] if job['state'] in ('downloading', 'downloaded', 'dumped', 'extracted')]
    work = unfinished + [job for job in jobs if job not in unfinished]
    if args.dry_run:
        for job in work:
            print(f"{job['state']:12} {job['url']} -> {job['file']}")
        return 0
    output.mkdir(parents=True, exist_ok=True)
    save_queue(state_path, queue)

    def checkpoint(job, state):
        job['state'] = state
        save_queue(state_path, queue)

    for number, job in enumerate(work, 1):
        if job['state'] in ('done', 'error', 'skipped'):
            continue
        if job['state'] == 'pending' and any(other['variant'] == job['variant'] and other['state'] == 'done' for other in jobs):
            checkpoint(job, 'skipped')
            continue
        print(f"[{number}/{len(work)}] {job['url']}", flush=True)
        if job['state'] == 'pending':
            status = wait_for_rpc(args.device, args.boot_timeout, args.poll_interval)
            if status['state'] not in ('idle', 'complete', 'error'):
                raise RuntimeError(f"upgrade path is occupied: {status['state']}")
            job['attempt'] = job.get('attempt', 0) + 1
            job['fromDateTime'] = config_json(args.device, 'gettime')['result']['dateTime']
            rpc(args.device, 'set', {'url': job['url']})
            checkpoint(job, 'downloading')

        if job['state'] == 'downloading':
            for retry in range(args.retries + 1):
                status = wait_for_download(args.device, args.download_timeout, args.poll_interval)
                if status['state'] != 'error' or not status.get('retryable') or retry == args.retries:
                    break
                # The provider retains the URL and committed NOR offset. Set
                # the same URL to resume; older providers cannot do this.
                print(f"  retry {retry + 1}/{args.retries} from {status['bytesStored']} bytes in {args.retry_delay:g}s", flush=True)
                time.sleep(args.retry_delay)
                rpc(args.device, 'set', {'url': job['url']})
            job['bytesStored'] = status['bytesStored']
            job['size'] = status['size']
            if status['state'] == 'error':
                record_download_error(args.device, job, output)
                if not job['bytesStored']:
                    checkpoint(job, 'error')
                    continue
                job['incomplete'] = True
                name = Path(job['file'])
                job['artifactFile'] = f"{name.stem}.partial-{job.get('attempt', 1)}{name.suffix}"
            checkpoint(job, 'downloaded')

        # Each URL overwrites the one native staging file. Extract it before
        # returning to the application and submitting the next request.
        artifact = job.get('artifactFile', job['file'])
        nor_file = output / (artifact + '.nor.bin')
        if job['state'] == 'downloaded':
            service(args.device, 'enter')
            service(args.device, 'read-nor', str(nor_file), 'upgrade')
            checkpoint(job, 'dumped')
        if job['state'] == 'dumped':
            container = As11NorImage.from_file(nor_file).staged_upgrade().container
            if job.get('incomplete'):
                container = container[:job['bytesStored']]
            destination = output / artifact
            temporary = destination.with_suffix('.part')
            temporary.write_bytes(container)
            temporary.replace(destination)
            checkpoint(job, 'extracted')

        if job['state'] == 'extracted':
            # On restart, the previous RESET may already have reached APPL.
            # ENTER handles either state, so retrying this phase is harmless.
            service(args.device, 'enter')
            service(args.device, 'reset')
            wait_for_rpc(args.device, args.boot_timeout, args.poll_interval)
            checkpoint(job, 'partial' if job.get('incomplete') else 'done')
            print(f"  saved {output / artifact}", flush=True)
            if job['state'] == 'partial':
                print('Partial download preserved; stopping before the next URL.', flush=True)
                return 1

    variants = {job['variant'] for job in jobs}
    done = {job['variant'] for job in jobs if job['state'] == 'done'}
    print(f"Downloaded: {len(done)}; unresolved: {len(variants - done)}")
    return 1 if variants - done else 0


def positive_seconds(text):
    value = float(text)
    if value <= 0:
        raise argparse.ArgumentTypeError('must be positive')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version', nargs='?', help='full target release, e.g. 17.8.6.0')
    parser.add_argument('--git', help='target firmware git identifier')
    parser.add_argument('--vids', type=int, nargs='+', help='variants to download; default: all catalogued variants')
    parser.add_argument('--package', action='append', help='FG package prefix; repeat to try several candidates')
    parser.add_argument('--server', default='http://ota203.p.ngcs.local:9010', help='HTTP server base URL')
    parser.add_argument('--urls', type=Path, help='use complete URLs from a text file instead of generating them')
    parser.add_argument('-d', '--device', required=True, help='CAN/TCP device for application RPC and bootloader service')
    parser.add_argument('-o', '--output', type=Path, required=True, help='output directory and persistent queue state')
    parser.add_argument('--poll-interval', type=positive_seconds, default=5, metavar='SECONDS')
    parser.add_argument('--download-timeout', type=positive_seconds, default=3600, metavar='SECONDS')
    parser.add_argument('--boot-timeout', type=positive_seconds, default=180, metavar='SECONDS')
    parser.add_argument('--retries', type=int, default=3, help='transport retries per file; 0 disables retries (default: 3)')
    parser.add_argument('--retry-delay', type=positive_seconds, default=30, metavar='SECONDS')
    parser.add_argument('--dry-run', action='store_true', help='show the queue without contacting a device or writing files')
    args = parser.parse_args(argv)
    if args.retries < 0:
        parser.error('--retries must be nonnegative')
    if args.urls and (args.version or args.git or args.vids or args.package):
        parser.error('--urls cannot be combined with version, --git, --vids or --package')
    return download_queue(args)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\nInterrupted; rerun with the same arguments to resume.', file=sys.stderr)
        sys.exit(130)
    except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.CalledProcessError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        sys.exit(1)
