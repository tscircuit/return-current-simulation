from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import time
import numpy as np

folder=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description="Compare all native adaptive/linearized PWL fixture outputs byte-for-byte")
parser.add_argument('--original',default='/workspace/work/tools/ngspice-44.2-install/bin/ngspice')
parser.add_argument('--fast',default='/workspace/work/tools/ngspice-44.2-fast-pwl/bin/ngspice')
args=parser.parse_args()
binaries={'original':str(Path(args.original).resolve()),'fast':str(Path(args.fast).resolve())}
records=[]
for name in ('strict','repeat_delay','duplicates','descending'):
    casefolder=folder/'native-cases'/name
    deck=(casefolder/'case.cir').read_text()
    line=next(line for line in deck.splitlines() if line.startswith('wrdata capture.dat '))
    vectors=line.removeprefix('wrdata capture.dat ')
    if 'linearized.dat' not in deck:
        deck=deck.replace(line,line+'\nlinearize '+vectors+'\nwrdata linearized.dat '+vectors)
    for label,binary in binaries.items():
        dest=casefolder/label;dest.mkdir(exist_ok=True)
        # Preserve previously completed unmodified native baseline scratch files.
        if label=='original':
            for fname in ('case.cir','ngspice.log','capture.dat'):
                old=dest/fname
                if old.exists() and not (dest/('initial-'+fname)).exists():
                    shutil.copyfile(old,dest/('initial-'+fname))
        (dest/'case.cir').write_text(deck)
        started=time.monotonic()
        with (dest/'ngspice.log').open('w') as stream:
            result=subprocess.run([binary,'-b','case.cir'],cwd=dest,stdout=stream,stderr=subprocess.STDOUT,timeout=15)
        log=(dest/'ngspice.log').read_text()
        if result.returncode or 'PWL_CASE_COMPLETE' not in log:
            raise RuntimeError((name,label,result.returncode,log))
        print(json.dumps({'case':name,'binary':label,'completed':True,'elapsed_s':time.monotonic()-started}),flush=True)
    outputs=[]
    for filename in ('capture.dat','linearized.dat'):
        a=(casefolder/'original'/filename).read_bytes();b=(casefolder/'fast'/filename).read_bytes()
        aa=np.loadtxt(casefolder/'original'/filename,skiprows=1,ndmin=2)
        bb=np.loadtxt(casefolder/'fast'/filename,skiprows=1,ndmin=2)
        result={'file':filename,'byte_identical':a==b,'shape_original':list(aa.shape),'shape_fast':list(bb.shape),'finite_original':bool(np.isfinite(aa).all()),'finite_fast':bool(np.isfinite(bb).all()),'original_sha256':hashlib.sha256(a).hexdigest(),'fast_sha256':hashlib.sha256(b).hexdigest()}
        if aa.shape==bb.shape:
            result.update(time_array_identical=bool(np.array_equal(aa[:,0],bb[:,0])),all_values_identical=bool(np.array_equal(aa,bb)),maximum_absolute_time_difference_s=float(np.max(abs(aa[:,0]-bb[:,0]))),maximum_absolute_value_difference=float(np.max(abs(aa[:,1:]-bb[:,1:]))))
        outputs.append(result)
    baselinefile=casefolder/'original/initial-capture.dat'
    initial_matches_rerun=baselinefile.read_bytes()==(casefolder/'original/capture.dat').read_bytes() if baselinefile.exists() else None
    records.append({'case':name,'same_deck_byte_identical':(casefolder/'original/case.cir').read_bytes()==(casefolder/'fast/case.cir').read_bytes(),'initial_adaptive_baseline_matches_rerun':initial_matches_rerun,'outputs':outputs})
summary={'binaries':{name:{'path':binary,'sha256':hashlib.sha256(Path(binary).read_bytes()).hexdigest()} for name,binary in binaries.items()},'cases':records,'all_output_files_byte_identical':all(out['byte_identical'] for case in records for out in case['outputs'])}
(folder/'native-equivalence.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
