#!/usr/bin/env python3

import argparse
import datetime
import os
import re
import subprocess
import sys


ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
SID_RE = re.compile(
    r'^(SX[0-9]{3}-[0-9]{4})([+!])([0-9A-Fa-f])([0-9A-Fa-f])'
    r'([0-9A-Za-z])([0-9A-Za-z])?$')


def hash_char(commit):
    return ALPHABET[int(commit[:8], 16) % len(ALPHABET)]


def decode_day(value):
    if value.isdigit():
        return int(value)
    return ord(value.upper()) - ord('A') + 10


def parse_sid(sid):
    match = SID_RE.fullmatch(sid)
    if not match:
        raise ValueError("expected SID in SXnnn-nnnn[+!]YMD[X] format")

    firmware, marker, year_code, month_code, day_code, commit_code = match.groups()
    if marker == '+' and commit_code is None:
        raise ValueError("'+' SID requires a commit code")
    year = 2020 + int(year_code, 16)
    month = int(month_code, 16)
    day = decode_day(day_code)
    date = datetime.date(year, month, day)
    return firmware, marker, date, commit_code


def find_commits(repo, date, code):
    try:
        output = subprocess.check_output(
            ['git', '-C', repo, 'log', '--all', '--format=%H%x09%ct%x09%s'],
            stderr=subprocess.DEVNULL).decode()
    except (OSError, subprocess.CalledProcessError):
        return None

    matches = []
    for line in output.splitlines():
        commit, epoch, subject = line.split('\t', 2)
        commit_date = datetime.datetime.fromtimestamp(
            int(epoch), datetime.timezone.utc).date()
        if commit_date == date and hash_char(commit) == code:
            matches.append((commit, subject))
    return matches


def main():
    parser = argparse.ArgumentParser(
        description='Decode an Air 10 patched firmware SID and find matching commits.')
    parser.add_argument('sid')
    parser.add_argument(
        '--repo', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        help='Git repository to search (default: script repository)')
    args = parser.parse_args()

    try:
        firmware, marker, date, code = parse_sid(args.sid)
    except ValueError as error:
        parser.error(str(error))

    print("Firmware: %s" % firmware)
    if marker == '+':
        source = 'clean/archive'
    elif code is None:
        source = 'unversioned'
    else:
        source = 'dirty'
    print("Source:   %s" % source)
    print("Date:     %s UTC" % date.isoformat())
    if code is None:
        print("Commit:   unavailable")
        return 0

    print("Code:     %s" % code)
    matches = find_commits(args.repo, date, code)
    if matches is None:
        print("Commits:  repository history unavailable")
        return 0
    if not matches:
        print("Commits:  no match")
        return 1

    print("Commits:")
    for commit, subject in matches:
        print("  %s  %s" % (commit, subject))
    return 0


if __name__ == '__main__':
    sys.exit(main())
