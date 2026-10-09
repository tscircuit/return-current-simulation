#!/usr/bin/env bash
# Ideal-source bandwidth diagnostic; no vendor files or new EM extraction.
set -eu
si_python=${SI_PYTHON:-python3}
si_ngspice=${SI_NGSPICE:-ngspice}
si_channel=${1:-examples/am3352/dqs-em-eye/channel/channel.sp}
si_output=${2:-work/dqs-frequency-stress}

for si_frequency in 400mhz 20ghz; do
  if [ "$si_frequency" = 400mhz ]; then
    si_ghz=0.4
    si_ui_count=128
    si_step_ps=0.5
    si_window=()
    si_label='Routed DQS0: ideal source, 400 MHz control'
  else
    si_ghz=20
    si_ui_count=120000
    si_step_ps=0.25
    si_window=(--analysis-start-ns 2980 --analysis-stop-ns 3000)
    si_label='Routed DQS0: ideal source, 20 GHz fit extrapolation'
  fi
  for si_case in routed reference; do
    si_control=()
    if [ "$si_case" = reference ]; then si_control=(--matched-reference); fi
    "$si_python" scripts/si/stress-dqs-bandwidth.py \
      --channel "$si_channel" --ngspice "$si_ngspice" \
      --strobe-ghz "$si_ghz" --ui-count "$si_ui_count" --dt-ps "$si_step_ps" \
      --out "$si_output/captures/$si_frequency-$si_case" "${si_control[@]}" "${si_window[@]}"
  done
  "$si_python" scripts/si/compare-eyes.py \
    "$si_output/captures/$si_frequency-routed" \
    "$si_output/captures/$si_frequency-reference" \
    --out "$si_output/$si_frequency" --label "$si_label"
done
