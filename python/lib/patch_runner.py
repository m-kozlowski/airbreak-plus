"""Patch execution and reporting shared by the patchers."""

from contextlib import redirect_stdout
from dataclasses import dataclass
import io
import sys

from .firmware_io import paths_alias
from .patch_config import parse_patch_args


@dataclass(frozen=True)
class PatchOutcome:
    status: str = 'OK'
    summary: str = None
    details: tuple = ()

    @classmethod
    def ok(cls, summary=None, *details):
        return cls('OK', summary, details)

    @classmethod
    def warn(cls, summary, *details):
        return cls('WARN', summary, details)

    @classmethod
    def skip(cls, summary):
        return cls('SKIP', summary)


class PatchVersionUnavailable(ValueError):
    """Version data cannot supply a patch; reported with the given status."""

    def __init__(self, status, summary):
        super().__init__(summary)
        self.status = status


class TeeStream:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
        return len(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def print_patch_output(text, stream=None):
    for line in text.rstrip('\n').splitlines():
        # Existing patch messages already use the standard two-space indent.
        if line.startswith('  '):
            line = line[2:]
        print(('  ' + line) if line else '', file=stream)


def print_patch_details(output, outcome, stream=None, include_summary=True):
    print_patch_output(output, stream)
    for detail in outcome.details:
        print('  ' + detail, file=stream)
    if include_summary and outcome.summary:
        print('  ' + outcome.summary, file=stream)


def apply_reported_patch(option, method, args, detail_log=None, deprecated=None):
    if deprecated and not args.force_deprecated:
        print('PATCH: %s [SKIP]' % option)
        print('  ' + deprecated)
        return PatchOutcome.skip(deprecated)

    output = io.StringIO()
    try:
        with redirect_stdout(output):
            outcome = method()
        if not isinstance(outcome, PatchOutcome):
            raise TypeError("%s returned %s instead of PatchOutcome" %
                            (option, type(outcome).__name__))
    except PatchVersionUnavailable as exc:
        outcome = PatchOutcome(exc.status, str(exc))
    except Exception:
        print('PATCH: %s [ERROR]' % option)
        if args.verbose or detail_log is None:
            print_patch_output(output.getvalue())
        else:
            print_patch_output(output.getvalue(), detail_log)
        raise

    if deprecated and outcome.status == 'OK':
        outcome = PatchOutcome.warn(outcome.summary, *outcome.details)

    print('PATCH: %s [%s]' % (option, outcome.status))
    if deprecated:
        print('  deprecated: ' + deprecated)
    if args.verbose:
        print_patch_details(output.getvalue(), outcome)
    else:
        show_summary = outcome.status in ('WARN', 'SKIP')
        if detail_log is not None:
            print_patch_details(output.getvalue(), outcome, detail_log, include_summary=not show_summary)
        if show_summary and outcome.summary:
            print('  ' + outcome.summary)
    return outcome


def run_unreported_step(step, args, detail_log=None):
    """Run a step without a status line; its output goes where patch details go."""
    output = io.StringIO()
    try:
        with redirect_stdout(output):
            step()
    except Exception:
        print(output.getvalue(), end='', file=None if args.verbose or detail_log is None else detail_log)
        raise

    if args.verbose:
        print(output.getvalue(), end='')
    elif detail_log is not None:
        print(output.getvalue(), end='', file=detail_log)


def apply_patch_phases(platform, patches, args, detail_log=None):
    """Apply the selected patches phase by phase; return their outcomes by option."""
    outcomes = {}
    for phase in platform.phases:
        selected = [patch for patch in phase.patches if platform.selected(args, patch)]
        if not selected:
            continue

        print('\n=== ' + phase.name)
        for patch in selected:
            outcomes[patch.option] = apply_reported_patch(
                patch.option, getattr(patches, patch.method), args, detail_log, patch.deprecated)
    return outcomes


def run_main(parser, platform, run_patcher, argv=None):
    """Parse the patcher command line, then check dependencies and run with an optional log."""
    args = parse_patch_args(parser, argv, platform)

    def run(detail_log=None):
        errors = platform.dependency_errors(args) if args.OPERATION == 'PATCH' else ()
        if errors:
            raise ValueError('; '.join(errors))
        return run_patcher(args, detail_log)

    if args.log_file is None:
        return run()

    if any(paths_alias(args.log_file, image) for image in (args.INFILE, args.OUTFILE)):
        raise ValueError('log file must differ from input and output images')
    with open(args.log_file, 'a', encoding='utf-8') as detail_log:
        with redirect_stdout(TeeStream(sys.stdout, detail_log)):
            try:
                return run(detail_log)
            except BrokenPipeError:
                raise
            except Exception as exc:
                print('error: %s' % exc, file=detail_log)
                raise


def exit_with(main):
    """Run a patcher entry point and turn errors into a short message and exit status."""
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(1)
    except Exception as exc:
        print('error: %s' % exc, file=sys.stderr)
        raise SystemExit(2)
