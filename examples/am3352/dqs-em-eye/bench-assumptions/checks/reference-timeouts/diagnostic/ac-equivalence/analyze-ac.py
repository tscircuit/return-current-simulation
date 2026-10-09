from pathlib import Path
import json
import math
import numpy as np

p=Path(__file__).resolve().parent
names=('source','transmitter','receiver_die','channel_input','channel_output','receiver_pin')
def phasors(data):
 return np.column_stack([data[:,1+2*i]+1j*data[:,2+2*i] for i in range(6)])
def desc(z):
 return {'real':float(z.real),'imag':float(z.imag),'magnitude':float(abs(z)),'db':float(20*np.log10(abs(z))),'phase_deg':float(np.angle(z,deg=True))}
records={}
for label in ('t','ltra'):
 f=np.loadtxt(p/label/'fundamental.dat',skiprows=1,ndmin=2)
 v=phasors(f)[0]
 records[label]={'frequency_hz':float(f[0,0]),'transmitter_H':desc(v[1]/v[0]),'receiver_die_H':desc(v[2]/v[0]),'receiver_pin_H':desc(v[5]/v[0]),'loaded_channel_H':desc(v[4]/v[3])}

gt=np.loadtxt(p/'t/grid.dat',skiprows=1,ndmin=2)
go=np.loadtxt(p/'ltra/grid.dat',skiprows=1,ndmin=2)
assert np.array_equal(gt[:,0],go[:,0])
a,b=phasors(gt),phasors(go)
comparisons={}
for name,index in (('transmitter',1),('receiver_die',2),('receiver_pin',5)):
 x=a[:,index]/a[:,0];y=b[:,index]/b[:,0];ratio=y/x
 comparisons[name]={'maximum_absolute_complex_difference':float(max(abs(y-x))),'maximum_relative_complex_difference':float(max(abs(ratio-1))),'maximum_relative_amplitude_difference':float(max(abs(abs(ratio)-1))),'maximum_phase_difference_deg':float(max(abs(np.angle(ratio,deg=True))))}
x=a[:,4]/a[:,3];y=b[:,4]/b[:,3];ratio=y/x
comparisons['loaded_channel']={'maximum_absolute_complex_difference':float(max(abs(y-x))),'maximum_relative_complex_difference':float(max(abs(ratio-1))),'maximum_relative_amplitude_difference':float(max(abs(abs(ratio)-1))),'maximum_phase_difference_deg':float(max(abs(np.angle(ratio,deg=True))))}
srcfirst=6/math.pi*np.sinc(.005)
summary={'fundamental':records,'frequency_grid_hz':[float(gt[0,0]),float(gt[-1,0])],'grid_points':len(gt),'grid_step_hz':float(gt[1,0]-gt[0,0]),'grid_comparisons':comparisons,'expected_5GHz_receiver_clock_firstharmonic_peak_v':srcfirst*records['t']['receiver_die_H']['magnitude'],'matched_line_derived':{'impedance_ohms':math.sqrt(40e-9/4e-12),'delay_s':math.sqrt(40e-9*4e-12),'lossless_LTRA_R':0,'lossless_LTRA_G':0,'native_case':'LTRA_MOD_LC; attenuation1; realpropagationconstant0'},'scope':'AC transfer equivalence with exact supplied bench, including0.2pF per-leg probe loading and physical seriesnoise sources setDC0. No transient integration equivalence claim.'}
(p/'results.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
