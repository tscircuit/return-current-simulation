#!/usr/bin/env python3
"""Read-only finite sorted-PWL index-equivalence evidence for ngspice 44.2."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path
import tarfile


ROOT = Path('/workspace/work/tools')
SOURCE = ROOT / 'ngspice-44.2'
PATCH = Path('/workspace/work/simulate-return-current/scripts/si/ngspice-pwl-binary-search.patch')
OUTPUT = Path(__file__).with_name('results.json')


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def binary(times: tuple[float, ...], query: float, first: int, strict: bool) -> int:
    lower, upper = first, len(times)
    while lower < upper:
        middle = lower + (upper - lower) // 2
        hit = times[middle] > query if strict else times[middle] >= query
        if hit:
            upper = middle
        else:
            lower = middle + 1
    return lower


def linear(times: tuple[float, ...], query: float, first: int, strict: bool) -> int:
    return next(
        (i for i in range(first, len(times))
         if (times[i] > query if strict else times[i] >= query)),
        len(times),
    )


def eligible(times: tuple[float, ...], coefficient_count: int | None = None) -> bool:
    count = 2 * len(times) if coefficient_count is None else coefficient_count
    return (count % 2 == 0 and all(math.isfinite(t) for t in times)
            and all(b >= a for a, b in zip(times, times[1:])))


def patched(times: tuple[float, ...], query: float, first: int, strict: bool,
            coefficient_count: int | None = None) -> int:
    selector = binary if eligible(times, coefficient_count) else linear
    return selector(times, query, first, strict)


def main() -> None:
    checks = 0
    duplicate_arrays = 0
    for length in range(1, 9):
        for times in itertools.combinations_with_replacement((0., 1., 2., 3.), length):
            duplicate_arrays += len(set(times)) != len(times)
            queries = {-1., .5, 1.5, 2.5, 4.}
            for knot in times:
                queries.update((math.nextafter(knot, -math.inf), knot,
                                math.nextafter(knot, math.inf)))
            for query in queries:
                for first, strict in ((1, False), (0, True)):
                    expected = linear(times, query, first, strict)
                    actual = binary(times, query, first, strict)
                    assert actual == expected, (times, query, first, strict, expected, actual)
                    checks += 1

    dispatch_checks = 0
    unsorted_checks = 0
    odd_dispatch_checks = 0
    for length in range(1, 7):
        for times in itertools.product((0., 1., 2., 3.), repeat=length):
            for query in (-1., 0., .5, 1., 1.5, 2., 2.5, 3., 4.):
                for first, strict in ((1, False), (0, True)):
                    expected = linear(times, query, first, strict)
                    assert patched(times, query, first, strict) == expected
                    dispatch_checks += 1
                    unsorted_checks += not eligible(times)
                    assert not eligible(times, 2 * length + 1)
                    assert patched(times, query, first, strict, 2 * length + 1) == expected
                    odd_dispatch_checks += 1

    nonfinite_checks = 0
    for times in ((math.nan, 1., 2.), (0., math.nan, 2.),
                  (0., 1., math.nan), (-math.inf, 1., 2.),
                  (0., math.inf, 2.), (0., 1., math.inf)):
        assert not eligible(times)
        for query in (-1., 0., 1., 1.5, 2., 3., math.nan, math.inf, -math.inf):
            for first, strict in ((1, False), (0, True)):
                assert patched(times, query, first, strict) == linear(times, query, first, strict)
                nonfinite_checks += 1

    hashes = {}
    archive_path = ROOT / 'ngspice-44.2.tar.gz'
    with tarfile.open(archive_path) as archive:
        for filename in ('vsrcdefs.h', 'vsrcpar.c', 'vsrcload.c', 'vsrcacct.c'):
            relative = 'src/spicelib/devices/vsrc/' + filename
            original = archive.extractfile('ngspice-44.2/' + relative).read()
            current = (SOURCE / relative).read_bytes()
            hashes[filename + '_original_sha256'] = digest(original)
            hashes[filename + '_current_sha256'] = digest(current)

        parameter_source = archive.extractfile(
            'ngspice-44.2/src/spicelib/devices/vsrc/vsrcpar.c').read()
        assert b'has non-increasing PWL time points.' in parameter_source

    unsorted = (0., 2., 1., 3.)
    counterexample = {
        'times': list(unsorted),
        'query': 1.5,
        'load_linear_index': linear(unsorted, 1.5, 1, False),
        'load_binary_index': binary(unsorted, 1.5, 1, False),
        'accept_linear_index': linear(unsorted, 1.5, 0, True),
        'accept_binary_index': binary(unsorted, 1.5, 0, True),
        'load_patched_index': patched(unsorted, 1.5, 1, False),
        'accept_patched_index': patched(unsorted, 1.5, 0, True),
    }
    assert counterexample['load_linear_index'] != counterexample['load_binary_index']
    assert counterexample['accept_linear_index'] != counterexample['accept_binary_index']

    results = {
        'purpose': 'Scalar read-only algorithm evidence; not an electrical waveform simulation',
        'load_selector': 'First knot >= query, beginning at knot index 1',
        'accept_selector': 'First knot > query, beginning at knot index 0; query = time + CKTminBreak',
        'equivalent_index_checks': checks,
        'duplicate_knot_arrays_checked': duplicate_arrays,
        'patched_dispatch_checks': dispatch_checks,
        'unsorted_fallback_checks': unsorted_checks,
        'odd_length_fallback_dispatch_checks': odd_dispatch_checks,
        'nonfinite_fallback_checks': nonfinite_checks,
        'scope': 'Finite nondecreasing time knots in complete time/value pairs',
        'duplicate_note': 'Index equality includes duplicates; original zero-width-interval behavior is not repaired',
        'source_inspection': 'TD, repetition fold, endpoint guards, interpolation arithmetic and breakpoint cache update unchanged',
        'unsorted_note': 'Original parser warns but accepts decreasing time knots; patch retains linear-scan fallback for these',
        'fallback_scope': 'Cached eligibility rejects decreasing/nonfinite time knots and odd coefficient counts',
        'unsorted_counterexample': counterexample,
        'hashes': hashes,
        'patch_path': str(PATCH),
        'patch_sha256': digest(PATCH.read_bytes()) if PATCH.exists() else None,
        'limitation': 'Checks selector indices/dispatch using independently transcribed algorithms; does not compile C or execute malformed odd-length interpolation',
    }
    OUTPUT.write_text(json.dumps(results, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'results': str(OUTPUT), 'checks': checks,
                      'patch_sha256': results['patch_sha256']}, sort_keys=True))


if __name__ == '__main__':
    main()
