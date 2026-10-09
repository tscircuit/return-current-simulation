# Independent PWL bracket-search review

The optimization is valid for finite, nondecreasing, complete `(time,value)` pairs when all outer native branches and interpolation/breakpoint arithmetic remain unchanged.

Load: search point indices `[1,N)` for the first `t[i] >= time`. Use lower_bound (`if t[mid] < time, lo=mid+1; else hi=mid`). The existing `time <= t[0]` first-value shortcut must remain before the search. Existing `time > t[N-1]` final-hold / repeat handling must remain unchanged. Keep the interpolation sequence `time-=t[i-1]; time/=t[i]-t[i-1]; value=y[i-1]; value+=time*(y[i]-y[i-1])` unchanged to preserve rounding.

Accept: search `[0,N)` for the first `t[i] > atime`, where `atime = transformed_time + CKTminBreak` exactly as before. Use upper_bound (`if t[mid] <= atime, lo=mid+1; else hi=mid`). Preserve the existing `CKTtime >= VSRCbreak_time` gate, repeat/delay transformation, `CKTsetBreak` call and `break_time -= CKTminBreak` sequence. If no point remains, perform no new breakpoint assignment, matching the old loop.

Boundary families:

- N=1: the first/end shortcuts cover all finite times; no load interval should be evaluated. N=2: search can only select interval index1.
- Before/equal first point: first ordinate is held, including duplicated first times. Immediately after a duplicated first time: interval begins at the last first-time duplicate.
- Equal interior duplicated time: lower_bound chooses its first duplicate (left ordinate). Immediately after it: lower_bound skips all duplicates, so the next interval begins at the final duplicate (right ordinate). This avoids zero-length interpolation intervals on valid sorted finite queries.
- Equal final duplicated time: lower_bound chooses the first final duplicate. Strictly after the final time: existing final-hold branch selects the last ordinate. Preserve this discontinuity at the final point.
- Repeat boundary: wrapping applies only for strict `time > end_time`; equality does not wrap. Repetition coefficient matches the first occurrence found by unchanged native `VSRC_R` handling. Delay subtracts before endpoint checks / repetition.
- Accept atime equality: upper_bound must skip all points equal to `time+minBreak`; using lower_bound here would change accepted-grid semantics.
- Queries immediately below/above knots must retain IEEE comparison semantics, including `nextafter` cases.
- Search coordinates must be point indices, multiplied by2 only when indexing the interleaved coefficient array. Direct midpoint calculation in coefficient indices can produce an odd ordinate index. Use `lo+(hi-lo)/2` to avoid addition overflow.

Input limitation: `vsrcpar.c:110-115` warns on `next_time <= previous_time`, rather than rejecting it. Duplicates are supported by the bracket rules above despite that warning. Descending or nonfinite times are outside sorted-search assumptions; preserve them via an original linear fallback or explicitly limit the fast binary's supported input scope. Do not claim equivalence for every warning-accepted malformed source solely from valid sorted cases.

`check-search-semantics.py` independently compared old and new index algorithms across79,854 finite sorted queries (strict and duplicated, negative/zero/positive times, exact endpoints and nextafter values), plus144 repeat/delay/minBreak combinations. It writes `search-semantics.json`.

Three short native baseline decks under `native-cases/` contain15 synthetic sources covering strict, first-future, negative-time, one-point, two-point, whole/interior repeat, delay, disabled repeat, interior/first/final/multiple duplicates and duplicated repeat start. Each drives the same simple R/C load. Full accepted time/source/load/current captures from the unchanged native binary are preserved under each `original/` directory. No full benchmark capture was run here.


## Completed native equivalence result

The completed four-file patch caches `VSRCpwlSorted` once when PWL parameters are assigned, allowing finite nondecreasing complete pairs onto the binary-search path. Descending, nonfinite or odd-length arrays retain the original scan fallback. Existing duplicate-time warnings remain unchanged. Independent review confirmed the new comparisons, point-coordinate bounds and unchanged interpolation/breakpoint arithmetic.

The original native binary and the separate optimized native binary ran byte-identical private decks for strict, repeat/delay, duplicate and descending-fallback families (16 synthetic sources). Every adaptive and linearized time/value/current file is byte-for-byte identical, all values finite, with exact accepted-grid equality and zero maximum numeric difference. Original accepted row counts are187,330,215 and130; linearized outputs have309rows each. Eight output-file hashes are recorded in `native-equivalence.json`; `native-equivalence.log` and all paired decks/logs/captures remain preserved under `native-cases/*/{original,fast}`. Earlier baseline scratch files were retained as `initial-*`.

Original binary SHA256: `18cf37b7ddf399ed68752371e8dbc12aa594f00dab459cffaa3a82921181cfa4`.
Optimized binary SHA256: `371046ceac2ab7cea9f01aeb393e3958d8dc57b8d5508e40f3f0e155457f8d2c`.

This is short source/solver equivalence evidence for the relevant boundaries and fallback; no full benchmark capture was run by this audit agent.
