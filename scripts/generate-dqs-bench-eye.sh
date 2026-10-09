#!/usr/bin/env bash
# Assumed 5 GHz bench observation; no vendor files or new EM extraction.
set -eu
si_python=${SI_PYTHON:-python3}
si_ngspice=${SI_NGSPICE:-ngspice}
si_channel=${1:-examples/am3352/dqs-em-eye/channel/channel.sp}
si_output=${2:-work/dqs-bench-assumptions}

for si_budget in clean noisy; do
  si_noise=(--rj-ps 3 --pj-ps 3 --noise-mv 5)
  si_scope_noise=2
  if [ "$si_budget" = clean ]; then
    si_noise=(--rj-ps 0 --pj-ps 0 --noise-mv 0)
    si_scope_noise=0
  fi
  si_capture="$si_output/captures/5ghz-$si_budget-routed"
  si_observation="$si_output/observations/5ghz-$si_budget-routed"
  "$si_python" scripts/si/simulate-dqs-bench.py \
    --channel "$si_channel" --ngspice "$si_ngspice" \
    --strobe-ghz 5 --ui-count 35000 --dt-ps 0.5 --sample-ps 2 \
    --capture-start-ns 2990 --analysis-start-ns 3000 --analysis-stop-ns 3500 \
    --method trap --rj-corner-mhz 500 --pj-mhz 100 \
    --noise-corner-ghz 1 --noise-grid-ps 10 --probe-pf 0.2 \
    --timeout-seconds 1800 \
    --timing-seed 50701 --noise-seed 50702 \
    --out "$si_capture" "${si_noise[@]}"
  "$si_python" scripts/si/bench_observation.py "$si_capture" \
    --out "$si_observation" --plane pads \
    --scope-noise-mv "$si_scope_noise" --seed 50703
done

"$si_python" scripts/si/compare-eyes.py \
  "$si_output/observations/5ghz-clean-routed" \
  "$si_output/observations/5ghz-noisy-routed" \
  --out "$si_output/5ghz/routed-clean-vs-noisy" \
  --label 'Clean routed DQS0: assumed 5 GHz bench' \
  --reference-label 'Noisy routed DQS0: assumed 5 GHz bench' \
  --budget-caption 'Clean: zero injected jitter/noise · Noisy: RJ 3 ps RMS (500 MHz corner) + PJ 3 ps peak (100 MHz) · Pad series noise 5 mV RMS (1 GHz) · Scope noise 2 mV RMS (12 GHz) · Both: probe 0.2 pF/pin and 12 GHz scope response'
