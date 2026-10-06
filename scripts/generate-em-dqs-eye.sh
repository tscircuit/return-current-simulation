#!/usr/bin/env bash
# Experimental AM3352 DQS0 example. Run from the repository root.
set -eu
si_python=${SI_PYTHON:-python3}
si_ngspice=${SI_NGSPICE:-ngspice}
si_ibis=${1:?Usage: scripts/generate-em-dqs-eye.sh /path/to/sprm552c.ibs [output-directory]}
si_output=${2:-work/am3352-em-eye}
si_cell=${CELL_MM:-0.1}
si_max_ns=${FIELD_MAX_NS:-1.5}
mkdir -p "$si_output"
si_output=$(realpath "$si_output")
si_repo=$(pwd)
bun scripts/prepare-am3352-example.ts "$si_output/input"
"$si_python" scripts/si/export-openems-copper.py "$si_output/input/case/model.json" --out "$si_output/copper.json"
docker build -t simulate-return-current-openems:0.0.35 -f scripts/si/Dockerfile .
docker run --rm --mount "type=bind,src=$si_repo,dst=/repo,readonly" --mount "type=bind,src=$si_output,dst=/case" simulate-return-current-openems:0.0.35 python3 /repo/scripts/si/compact-openems-copper.py /case/copper.json --out /case/copper-compact.json
for si_port in 1 2; do
  docker run --rm --mount "type=bind,src=$si_repo,dst=/repo,readonly" --mount "type=bind,src=$si_output,dst=/case" simulate-return-current-openems:0.0.35 python3 /repo/scripts/si/extract-openems.py --board /case/input/board.json --model /case/input/case/model.json --copper /case/copper.json --compact-copper /case/copper-compact.json --lane 0 --excite "$si_port" --cell "$si_cell" --max-ns "$si_max_ns" --out "/case/port$si_port" > "$si_output/port$si_port.log" 2>&1
done
"$si_python" scripts/si/fit-channel.py "$si_output/port1/s-column.csv" "$si_output/port2/s-column.csv" --out "$si_output/channel"
"$si_python" scripts/si/prepare-ibis-drivers.py "$si_ibis" --out "$si_output/driver"
for si_mode in clock prbs; do
  si_prefix=""
  if [ "$si_mode" = prbs ]; then si_prefix="prbs-"; fi
  for si_case in routed reference; do
    si_control=()
    if [ "$si_case" = reference ]; then si_control=(--matched-reference); fi
    "$si_python" scripts/si/simulate-dqs-eye.py --channel "$si_output/channel/channel.sp" --driver "$si_output/driver/positive.sp" --negative-driver "$si_output/driver/negative.sp" --ngspice "$si_ngspice" --mode "$si_mode" --ui-count 256 --rj-ps "${RJ_PS:-10}" --pj-ps "${PJ_PS:-5}" --noise-mv "${NOISE_MV:-2}" --out "$si_output/$si_prefix$si_case" "${si_control[@]}"
    if [ "$si_mode" = clock ]; then
      "$si_python" scripts/analyze-ddr-waveforms.py "$si_output/$si_case/waveforms.csv" --provenance "$si_output/$si_case/provenance.json" --rate-mts 800 --start-ns 20 --stop-ns 310 --output "$si_output/$si_case/analysis"
    fi
  done
  "$si_python" scripts/si/compare-eyes.py "$si_output/${si_prefix}routed" "$si_output/${si_prefix}reference" --out "$si_output/${si_prefix}comparison" --channel-npz "$si_output/channel/channel.npz"
done
