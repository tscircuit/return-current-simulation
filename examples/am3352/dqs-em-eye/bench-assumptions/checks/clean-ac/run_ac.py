"""Independent native AC probe-loading and causal scope groundcheck.

The passive network is imported unchanged from stress-dqs-bandwidth.py. Only
the declared 0.2 pF shunt per receiver pad is added. Normalized complementary
AC sources provide 2 V differential; analytic 1 ps source Fourier phasors then
predict the periodic clean waveform. Harmonics above 5 GHz are mathematical
checks of the stated model, not additional physically extracted channel data.
"""

from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np


FUNDAMENTAL_HZ = 5e9
DT_S = 2e-12
SCOPE_CORNER_HZ = 12e9
SOURCE_CENTER_S = 5e-9 + 0.5e-12
MAX_HARMONIC = 401


def scope_transfer(frequency):
    """Independent bilinear/prewarped Butterworth response, causal sign."""
    omega_c = 2 / DT_S * np.tan(np.pi * SCOPE_CORNER_HZ * DT_S)
    # z=exp(j*2*pi*f*dt); this remains periodic for aliased input harmonics.
    inverse_z = np.exp(-2j * np.pi * frequency * DT_S)
    s = (2 / DT_S) * (1 - inverse_z) / (1 + inverse_z)
    return omega_c**2 / (s*s + np.sqrt(2)*omega_c*s + omega_c**2)


def native_case(case, stress, repo, out, channel, ngspice):
    matched = case == 'reference'
    destination = out / case
    destination.mkdir(parents=True, exist_ok=True)
    deck = f'''Independent clean probe-loaded ideal-source native AC groundcheck
Vpositive srcp 0 DC 0 AC 1 0
Vnegative srcn 0 DC 1.5 AC 1 180
Rsourcep srcp diep 50
Rsourcen srcn dien 50
{stress.passive_network(channel, matched)}
Cprobep rxp 0 .2p
Cproben rxn 0 .2p
.options reltol=1e-7 abstol=1e-12 vntol=1e-9
.control
set wr_vecnames
set wr_singlescale
set numdgt=17
ac lin {(MAX_HARMONIC + 1)//2} 5e9 {MAX_HARMONIC*FUNDAMENTAL_HZ:.17e}
let tx_difference = v(txp)-v(txn)
let pad_difference = v(rxp)-v(rxn)
let die_difference = v(rdiep)-v(rdien)
wrdata ac-response.dat tx_difference pad_difference die_difference v(csrc) v(cload)
echo BENCH_AC_COMPLETE
quit
.endc
.end
'''
    (destination / 'ac.cir').write_text(deck)
    run = subprocess.run([str(ngspice), '-b', 'ac.cir'], cwd=destination,
                         capture_output=True, text=True, timeout=60)
    log = run.stdout + run.stderr
    (destination / 'ngspice.log').write_text(log)
    if run.returncode != 0 or 'BENCH_AC_COMPLETE' not in log or stress.NATIVE_ERROR.search(log):
        raise RuntimeError(log)
    values = np.loadtxt(destination / 'ac-response.dat', skiprows=1, ndmin=2)
    if values.shape != ((MAX_HARMONIC+1)//2, 11) or not np.isfinite(values).all():
        raise RuntimeError(f'invalid native AC response {values.shape}')
    harmonics = []
    pad_phasors = []
    frequencies = []
    for row in values:
        frequency = float(row[0])
        harmonic = int(round(frequency / FUNDAMENTAL_HZ))
        source_peak = 4 * 1.5 / (np.pi*harmonic) * np.sinc(frequency*1e-12)
        source_phasor = source_peak * np.exp(-1j*(np.pi/2 + 2*np.pi*frequency*SOURCE_CENTER_S))
        signals = {}
        for name, column in [('transmitterBgaDifferential', 1), ('receiverPadDifferential', 3),
                             ('receiverDieDifferential', 5), ('channelInput', 7), ('channelOutput', 9)]:
            transfer = (row[column] + 1j*row[column+1])/2
            phasor = transfer*source_phasor
            signals[name] = {
                'transferReal': float(transfer.real), 'transferImag': float(transfer.imag),
                'expectedPeakV': float(abs(phasor)), 'expectedAbsolutePhaseRad': float(np.angle(phasor)),
                'expectedPhasorRealV': float(phasor.real), 'expectedPhasorImagV': float(phasor.imag),
            }
            if name == 'receiverPadDifferential':
                pad_phasors.append(phasor)
        observed = pad_phasors[-1]*scope_transfer(frequency)
        signals['scopeObservedPadDifferential'] = {
            'expectedPeakV': float(abs(observed)), 'expectedAbsolutePhaseRad': float(np.angle(observed)),
            'expectedPhasorRealV': float(observed.real), 'expectedPhasorImagV': float(observed.imag),
        }
        frequencies.append(frequency)
        harmonics.append({'frequencyHz': frequency, 'harmonicNumber': harmonic,
                          'outsideExtractedChannelBand': frequency > 5e9,
                          'sourceDifferentialFourierPeakV': float(source_peak), 'signals': signals})
    frequencies = np.asarray(frequencies)
    pad_phasors = np.asarray(pad_phasors)
    # This physical-grid phase matches analysis starting at an integer 200 ps period.
    times = np.arange(100)*DT_S
    basis = np.exp(2j*np.pi*frequencies[:, None]*times[None, :])
    raw = np.real(pad_phasors[:, None]*basis).sum(axis=0)
    filtered = np.real((pad_phasors*scope_transfer(frequencies))[:, None]*basis).sum(axis=0)
    direct_fundamental = pad_phasors[0]*scope_transfer(FUNDAMENTAL_HZ)
    sampled_fundamental = 2*np.mean(filtered*np.exp(-2j*np.pi*FUNDAMENTAL_HZ*times))
    sampled_results = {}
    for name, waveform in [('rawPad', raw), ('scopeObservedPad', filtered)]:
        sampled_results[name] = {'meanV': float(waveform.mean()), 'acRmsV': float(waveform.std()),
                                'halfPeakToPeakV': float(np.ptp(waveform)/2)}
    report = {
        'case': case, 'channelSpiceSha256': hashlib.sha256(channel.read_bytes()).hexdigest(),
        'ngspiceBinary': str(ngspice),
        'ngspiceBinarySha256': hashlib.sha256(ngspice.read_bytes()).hexdigest(),
        'auditScriptSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'passiveNetworkSourceSha256': hashlib.sha256((repo/'scripts/si/stress-dqs-bandwidth.py').read_bytes()).hexdigest(),
        'netlistSha256': hashlib.sha256(deck.encode()).hexdigest(),
        'normalizedAcSourceDifferentialPeakV': 2,
        'probeCapacitancePfPerLeg': 0.2, 'measurementPlane': 'receiver package pads rxp/rxn',
        'phasorConvention': 'cosine coefficient minus j*sine coefficient, absolute timestamps',
        'sourceFormula': '4*1.5/(pi*n)*sinc(f*1ps)*exp(-j*(pi/2+2*pi*f*5000.5ps)), odd n=f/5GHz',
        'scopeFormula': 'Omega_c^2/(s^2+sqrt(2)*Omega_c*s+Omega_c^2), Omega_c=2/dt*tan(pi*12GHz*dt), s=2/dt*(1-z^-1)/(1+z^-1), z=exp(j*2*pi*f*dt)',
        'scopeSampleIntervalPs': 2, 'scopeCornerGHz': 12, 'scopeNoiseRmsMv': 0,
        'scopeFundamentalAmplitudeRatio': float(abs(scope_transfer(FUNDAMENTAL_HZ))),
        'scopeFundamentalPhaseRad': float(np.angle(scope_transfer(FUNDAMENTAL_HZ))),
        'maximumReconstructedHarmonicNumber': MAX_HARMONIC,
        'mathematicalAliasedFundamentalChangeV': float(abs(sampled_fundamental-direct_fundamental)),
        'sumIncludedOverNyquistScopeHarmonicPeakV': float(np.abs((pad_phasors*scope_transfer(frequencies))[frequencies>250e9]).sum()),
        'periodicGridStatistics': sampled_results,
        'harmonics': harmonics,
        'limitations': ['Native AC checks the declared linear model, not physical channel/device accuracy.',
                        'Only 5GHz lies at the extracted channel band edge; all higher harmonics use the stated model beyond available channel data.',
                        'No stochastic sources are present; startup modes are absent from steady-state AC.',
                        'Periodic waveform reconstruction is truncated at the stated odd harmonic; above-Nyquist terms are included to estimate mathematical sampling aliases.'],
    }
    np.savetxt(destination/'periodic-grid.csv', np.column_stack([times,raw,filtered]), delimiter=',',
               header='absolute_period_time_s,pad_differential_v,scope_observed_differential_v', comments='')
    (destination/'results.json').write_text(json.dumps(report, indent=2)+'\n')
    return {'case':case, 'fundamental':harmonics[0], 'periodicGridStatistics':sampled_results,
            'scopeFundamentalAmplitudeRatio':report['scopeFundamentalAmplitudeRatio'],
            'scopeFundamentalPhaseRad':report['scopeFundamentalPhaseRad'],
            'mathematicalAliasedFundamentalChangeV':report['mathematicalAliasedFundamentalChangeV'],
            'sumIncludedOverNyquistScopeHarmonicPeakV':report['sumIncludedOverNyquistScopeHarmonicPeakV']}


def infer_repo():
    for start in (Path.cwd(),Path(__file__).resolve().parent):
        for candidate in (start,*start.parents):
            if (candidate/'scripts/si/stress-dqs-bandwidth.py').is_file():
                return candidate
    return Path.cwd()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=infer_repo(),help='repository root; inferred from cwd or script ancestors')
    parser.add_argument('--out',type=Path,required=True,help='dedicated output directory for decks, logs and results')
    parser.add_argument('--ngspice',default='ngspice',help='native executable path or name on PATH')
    args=parser.parse_args()
    repo,out=args.repo.resolve(),args.out.resolve()
    channel=repo/'examples/am3352/dqs-em-eye/channel/channel.sp'
    source=repo/'scripts/si/stress-dqs-bandwidth.py'
    binary=shutil.which(args.ngspice)
    if binary is None:
        parser.error('ngspice executable was not found; provide --ngspice')
    ngspice=Path(binary).resolve()
    if not source.is_file() or not channel.is_file():
        parser.error('--repo must contain the passive-network script and saved channel')
    out.mkdir(parents=True,exist_ok=True)
    spec = importlib.util.spec_from_file_location('independent_bandwidth_stress', source)
    stress = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stress)
    with ThreadPoolExecutor(max_workers=2) as workers:
        summaries = list(workers.map(lambda case:native_case(case,stress,repo,out,channel,ngspice), ('routed','reference')))
    (out/'results.json').write_text(json.dumps(summaries,indent=2)+'\n')
    print(json.dumps(summaries,indent=2))


if __name__ == '__main__':
    main()
