"""Read completed clean bench captures; compare with independent native AC.

No solver is invoked and no supplied capture is modified. Absent waveforms or
provenance are reported as pending, so this can be prepared before jobs finish.
Fits use absolute timestamps, without phase alignment. Analysis is 3000--3500
ns with 20 ns and eight-cycle early/middle/late blocks.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


FREQUENCY = 5e9
DT = 2e-12
WINDOW = (3000e-9, 3500e-9)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metrics(time, voltage):
    if len(time) < 16 or not np.isfinite(voltage).all():
        raise ValueError('insufficient or nonfinite voltage samples')
    phase = 2*np.pi*FREQUENCY*time
    basis = np.column_stack([np.cos(phase), np.sin(phase), np.ones_like(time)])
    cosine, sine, offset = np.linalg.lstsq(basis, voltage, rcond=None)[0]
    phasor = cosine - 1j*sine
    return {'samples':len(time), 'meanV':float(voltage.mean()), 'acRmsV':float(voltage.std()),
            'halfPeakToPeakV':float(np.ptp(voltage)/2),
            'fundamentalPeakV':float(abs(phasor)), 'fundamentalPhaseRad':float(np.angle(phasor)),
            'fundamentalPhasorRealV':float(phasor.real), 'fundamentalPhasorImagV':float(phasor.imag),
            'fittedOffsetV':float(offset), 'nonFundamentalAcRmsV':float(np.std(voltage-basis[:,:2]@np.array([cosine,sine])))}


def select(time, bounds):
    # Only compensate floating-point ambiguity exactly at a declared endpoint.
    tolerance = DT*1e-6
    selected = (time >= bounds[0]-tolerance) & (time < bounds[1]-tolerance)
    if np.count_nonzero(selected) < 16:
        raise ValueError(f'capture does not cover window {bounds}')
    if time[selected][0] > bounds[0]+DT or time[selected][-1] < bounds[1]-2*DT:
        raise ValueError(f'incomplete capture window {bounds}')
    return selected


def comparison(actual, expected):
    phase_error = float(np.angle(np.exp(1j*(actual['fundamentalPhaseRad']-expected['expectedAbsolutePhaseRad']))))
    return {'fundamentalPeakRelativeError':actual['fundamentalPeakV']/expected['expectedPeakV']-1,
            'fundamentalPhaseErrorRad':phase_error,
            'fundamentalPhaseErrorEquivalentPs':phase_error/(2*np.pi*FREQUENCY)*1e12,
            'fundamentalComplexErrorV':float(abs(complex(actual['fundamentalPhasorRealV'],actual['fundamentalPhasorImagV'])-
                complex(expected['expectedPhasorRealV'],expected['expectedPhasorImagV'])))}


def harmonic_prediction(time, expected, signal):
    """Evaluate stored absolute AC phasors at actual timestamps, in small chunks."""
    harmonics = np.array([h['harmonicNumber'] for h in expected['harmonics']])
    coefficients = np.array([
        complex(h['signals'][signal]['expectedPhasorRealV'],h['signals'][signal]['expectedPhasorImagV'])
        for h in expected['harmonics']])
    prediction = np.empty(len(time))
    for first in range(0,len(time),4096):
        last=min(first+4096,len(time))
        # Reduction by the exact nominal period limits large-angle rounding.
        phase_fraction = np.remainder(time[first:last]*FREQUENCY,1)
        basis=np.exp(2j*np.pi*harmonics[:,None]*phase_fraction[None,:])
        prediction[first:last]=np.real(coefficients[:,None]*basis).sum(axis=0)
    return prediction


def audit_capture(case, kind, root, ac_root):
    destination = root / kind / f'5ghz-clean-{case}'
    inputs = [destination/'waveforms.npz', destination/'provenance.json']
    absent = [str(p) for p in inputs if not p.is_file()]
    if absent:
        return {'case':case, 'kind':kind, 'status':'pending', 'missing':absent}
    metadata = json.loads(inputs[1].read_text())
    with np.load(inputs[0]) as saved:
        waveforms = {k:saved[k] for k in saved.files}
    time = waveforms['time_s']
    if len(time) < 16 or not np.isfinite(time).all() or np.any(np.diff(time)<=0):
        raise ValueError('capture time must be finite and increasing')
    if not np.allclose(np.diff(time), DT, rtol=1e-6, atol=1e-18):
        raise ValueError('expected the declared 2 ps observation grid')
    if metadata['strobeGHz'] != 5 or not np.allclose(
            [metadata['analysisStartNs'],metadata['analysisStopNs']],[3000,3500],rtol=0,atol=1e-6):
        raise ValueError('expected a 5 GHz capture with the 3000--3500 ns analysis window')
    if metadata.get('jitter',{}).get('configuredInputRjRmsPs',0) != 0 or metadata.get('jitter',{}).get('configuredPeriodicJitterPeakPs',0) != 0:
        raise ValueError('this audit expects clean source timing')
    if metadata.get('noise',{}).get('configuredRmsMv',0) != 0:
        raise ValueError('this audit expects zero commanded receiver noise')
    if kind == 'observations':
        observation = metadata.get('observation',{})
        if observation.get('plane') != 'receiver package pads' or observation.get('scopeNoiseRmsMv') != 0:
            raise ValueError('expected a clean receiver-pad scope observation')
        voltage = waveforms['dqs_p_v']-waveforms['dqs_n_v']
        signal = 'scopeObservedPadDifferential'
        grid_column = 2
        stats_key = 'scopeObservedPad'
    else:
        if 'observation' in metadata:
            raise ValueError('native input unexpectedly contains scope observation')
        voltage = waveforms['pad_p_v']-waveforms['pad_n_v']
        signal = 'receiverPadDifferential'
        grid_column = 1
        stats_key = 'rawPad'
    expected = json.loads((ac_root/case/'results.json').read_text())
    if metadata.get('ioModels',{}).get('probeCapacitancePfPerLeg') != 0.2:
        raise ValueError('AC comparison requires the declared 0.2 pF probe on each leg')
    if metadata.get('channel',{}).get('suppliedModelSha256') != expected['channelSpiceSha256']:
        raise ValueError('capture and AC audit use different supplied channel files')
    channel_model = metadata.get('channel',{}).get('model')
    if (case == 'reference') != (channel_model == 'ideal matched 100 ohm, 400ps control'):
        raise ValueError('capture channel selection does not match the AC case')
    expected_fundamental = expected['harmonics'][0]['signals'][signal]
    expected_stats = expected['periodicGridStatistics'][stats_key]
    periodic = np.loadtxt(ac_root/case/'periodic-grid.csv',delimiter=',',skiprows=1)
    grid_metrics = metrics(periodic[:,0],periodic[:,grid_column])
    sampled_fundamental = {
        'expectedPeakV':grid_metrics['fundamentalPeakV'],
        'expectedAbsolutePhaseRad':grid_metrics['fundamentalPhaseRad'],
        'expectedPhasorRealV':grid_metrics['fundamentalPhasorRealV'],
        'expectedPhasorImagV':grid_metrics['fundamentalPhasorImagV'],
    }
    # Record tiny timestamp drift, but evaluate the AC waveform at the actual
    # captured times. No edge movement, receiver phase estimate or resampling.
    indices = np.rint(time/DT).astype(np.int64)
    grid_time_error = float(np.max(np.abs(time-indices*DT)))
    predicted = harmonic_prediction(time,expected,signal)
    start,stop = WINDOW
    windows = [('full',start,stop),('early20ns',start,start+20e-9),
               ('middle20ns',(start+stop)/2-10e-9,(start+stop)/2+10e-9),
               ('late20ns',stop-20e-9,stop),('early8cycles',start,start+8/FREQUENCY),
               ('middle8cycles',(start+stop)/2-4/FREQUENCY,(start+stop)/2+4/FREQUENCY),
               ('late8cycles',stop-8/FREQUENCY,stop)]
    result_windows = []
    for label,a,b in windows:
        mask = select(time,(a,b))
        actual = metrics(time[mask],voltage[mask])
        expected_window = metrics(time[mask],predicted[mask])
        expected_window_fundamental = {
            'expectedPeakV':expected_window['fundamentalPeakV'],
            'expectedAbsolutePhaseRad':expected_window['fundamentalPhaseRad'],
            'expectedPhasorRealV':expected_window['fundamentalPhasorRealV'],
            'expectedPhasorImagV':expected_window['fundamentalPhasorImagV'],
        }
        difference = voltage[mask]-predicted[mask]
        result_windows.append({'label':label,'startNs':a*1e9,'stopNs':b*1e9,'actual':actual,
            'acPredictionOnActualTimestamps':expected_window,
            'versusSampledACFundamental':comparison(actual,expected_window_fundamental),
            'versusAC':{**comparison(actual,expected_fundamental),
                'acRmsRelativeError':actual['acRmsV']/expected_window['acRmsV']-1,
                'halfPeakToPeakRelativeError':actual['halfPeakToPeakV']/expected_window['halfPeakToPeakV']-1,
                'waveformMaximumAbsoluteErrorV':float(abs(difference).max()),
                'waveformRmsErrorV':float(np.sqrt(np.mean(difference**2)))}})
    block20 = [v['actual'] for v in result_windows if v['label'].endswith('20ns')]
    block8 = [v['actual'] for v in result_windows if v['label'].endswith('8cycles')]
    def block_consistency(blocks):
        phase_error = np.unwrap([b['fundamentalPhaseRad'] for b in blocks])
        return {'fundamentalPeakRangeV':float(np.ptp([b['fundamentalPeakV'] for b in blocks])),
                'fundamentalPeakRelativeRange':float(np.ptp([b['fundamentalPeakV'] for b in blocks])/expected_fundamental['expectedPeakV']),
                'fundamentalPhaseRangeRad':float(np.ptp(phase_error)),
                'fundamentalPhaseEquivalentTimeRangePs':float(np.ptp(phase_error)/(2*np.pi*FREQUENCY)*1e12),
                'acRmsRangeV':float(np.ptp([b['acRmsV'] for b in blocks])),
                'halfPeakToPeakRangeV':float(np.ptp([b['halfPeakToPeakV'] for b in blocks])),
                'meanRangeV':float(np.ptp([b['meanV'] for b in blocks]))}
    late = select(time,(stop-8/FREQUENCY,stop))
    selected_indices = np.flatnonzero(late)
    previous_indices = selected_indices-100
    repeat_error = voltage[selected_indices]-voltage[previous_indices]
    return {'case':case,'kind':kind,'status':'complete','capture':str(destination),
            'waveformsSha256':sha256(inputs[0]),'provenanceSha256':sha256(inputs[1]),
            'acResultsSha256':sha256(ac_root/case/'results.json'),
            'electricalTimeStepPs':metadata.get('electricalTimeStepPs'),
            'sampleIntervalPs':2,'maximumAbsoluteGridTimeErrorS':grid_time_error,
            'expectedFundamental':expected_fundamental,'expectedGridStatistics':expected_stats,
            'expectedSampledGridFundamental':sampled_fundamental,
            'windows':result_windows,'block20nsConsistency':block_consistency(block20),
            'block8cycleConsistency':block_consistency(block8),
            'lateCycleRepeat':{'cycleSamples':100,'maximumAbsoluteDifferenceV':float(abs(repeat_error).max()),
                               'rmsDifferenceV':float(np.sqrt(np.mean(repeat_error**2)))},
            'comparisonAlignment':'same absolute physical time; no phase fit or alignment applied to waveform comparisons',
            'limitations':['Native AC establishes model consistency, not physical accuracy.',
                           'Higher routed harmonics in the waveform prediction extrapolate beyond 5GHz.',
                           'No absolute numerical pass/fail tolerance is inferred from agreement.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True,help='capture work root containing captures/ and observations/')
    parser.add_argument('--ac-root',type=Path,default=Path(__file__).resolve().parent,help='AC evidence root containing routed/ and reference/')
    parser.add_argument('--out',type=Path,required=True,help='output JSON, outside supplied capture directories')
    parser.add_argument('--reference-unavailable-reason',help='record why absent reference captures are unavailable rather than pending')
    args=parser.parse_args()
    root,ac_root=args.root.resolve(),args.ac_root.resolve()
    if any(args.out.resolve().is_relative_to(root/kind) for kind in ('captures','observations')):
        parser.error('--out must be outside the supplied capture directories')
    audits=[audit_capture(case,kind,root,ac_root) for case in ('routed','reference') for kind in ('captures','observations')]
    if args.reference_unavailable_reason is not None:
        if not args.reference_unavailable_reason.strip():
            parser.error('--reference-unavailable-reason must be nonempty')
        for result in audits:
            if result['case']=='reference' and result['status']=='pending':
                result.update(status='unavailable',reason=args.reference_unavailable_reason)
    report={'analysisStartNs':3000,'analysisStopNs':3500,'fundamentalHz':FREQUENCY,
            'auditScriptSha256':sha256(__file__),'captures':audits}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    brief=[{'case':a['case'],'kind':a['kind'],'status':a['status'],
            **({'full':a['windows'][0],'block20nsConsistency':a['block20nsConsistency'],
                'block8cycleConsistency':a['block8cycleConsistency'],'lateCycleRepeat':a['lateCycleRepeat']}
               if a['status']=='complete' else {'missing':a['missing'],**({'reason':a['reason']} if 'reason' in a else {})})} for a in audits]
    print(json.dumps(brief,indent=2,allow_nan=False))


if __name__ == '__main__':
    main()
