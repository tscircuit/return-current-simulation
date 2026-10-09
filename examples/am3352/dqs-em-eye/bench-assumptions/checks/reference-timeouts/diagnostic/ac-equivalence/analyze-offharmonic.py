from pathlib import Path
import json
import numpy as np

p=Path(__file__).resolve().parent

def phasors(row):
 return [complex(row[1+2*i],row[2+2*i]) for i in range(6)]

def desc(z):
 return {'real':z.real,'imag':z.imag,'magnitude':abs(z),'phase_deg':float(np.angle(z,deg=True))}

grid={n:np.loadtxt(p/n/'grid.dat',skiprows=1,ndmin=2) for n in ('t','ltra')}
rows=[]
for frequency in (.4e9,4.5e9,4.9e9,5.1e9,5.5e9):
 record={'frequency_hz':frequency}
 hs={};hc={}
 for label in ('t','ltra'):
  if frequency==.4e9:data=np.loadtxt(p/label/'low-frequency.dat',skiprows=1,ndmin=2)[0]
  else:
   index=int(np.argmin(abs(grid[label][:,0]-frequency)))
   data=grid[label][index]
   assert abs(data[0]-frequency)<1e-3
  v=phasors(data);hs[label]=v[2]/v[0];hc[label]=v[4]/v[3]
  record[label]={'actual_frequency_hz':float(data[0]),'receiver_die_H':desc(hs[label]),'loaded_channel_H':desc(hc[label])}
 record['receiver_relative_complex_difference']=abs(hs['ltra']/hs['t']-1)
 record['receiver_relative_amplitude_difference']=abs(abs(hs['ltra']/hs['t'])-1)
 record['receiver_phase_difference_deg']=float(abs(np.angle(hs['ltra']/hs['t'],deg=True)))
 record['channel_relative_complex_difference']=abs(hc['ltra']/hc['t']-1)
 rows.append(record)
summary={'low_frequency_and_sidebands':rows,'maximum_receiver_relative_complex_difference':max(r['receiver_relative_complex_difference'] for r in rows),'maximum_receiver_phase_difference_deg':max(r['receiver_phase_difference_deg'] for r in rows),'scope':'Exact same bench with0.2pF per-leg probe; off-harmonic frequencies independently demonstrate that equivalence does not rely on5GHz400psdelay integer-period identity.'}
(p/'offharmonic-results.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
