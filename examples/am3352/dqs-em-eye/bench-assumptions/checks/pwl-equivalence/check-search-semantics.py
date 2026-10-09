from pathlib import Path
import bisect
import json
import math
import random

folder=Path(__file__).resolve().parent
rng=random.Random(4442)

def old_load_index(t,q):
    return next((i for i in range(1,len(t)) if t[i]>=q),len(t))

def new_load_index(t,q):
    lo,hi=1,len(t)
    while lo<hi:
        mid=lo+(hi-lo)//2
        if t[mid]<q:lo=mid+1
        else:hi=mid
    return lo

def old_accept_index(t,q):
    return next((i for i in range(len(t)) if t[i]>q),len(t))

def new_accept_index(t,q):
    lo,hi=0,len(t)
    while lo<hi:
        mid=lo+(hi-lo)//2
        if t[mid]<=q:lo=mid+1
        else:hi=mid
    return lo

cases=[]
for t in ([0.], [0.,1.], [1.,2.], [-2.,-1.,0.,1.], [0.,0.,1.], [0.,1.,1.,2.], [0.,1.,2.,2.], [0.,0.,1.,1.,2.,2.]):
    qlist=[-10.,10.]
    for q in t:
        qlist.extend((math.nextafter(q,-math.inf),q,math.nextafter(q,math.inf)))
    for q in qlist:
        a=old_load_index(t,q);b=new_load_index(t,q);c=old_accept_index(t,q);d=new_accept_index(t,q)
        assert (a,c)==(b,d),(t,q,a,b,c,d)
        cases.append({'times':t,'query':q,'load_index':a,'accept_index':c})
checks=len(cases)
for _ in range(1000):
    n=rng.randint(1,500)
    t=sorted(rng.choice((rng.uniform(-2e-9,6e-9),0.,1e-9,2e-9,3e-9)) for _ in range(n))
    queries=[rng.uniform(-3e-9,7e-9) for _ in range(50)]
    for q in rng.sample(t,min(10,n)):
        queries.extend((q,math.nextafter(q,-math.inf),math.nextafter(q,math.inf)))
    for q in queries:
        assert old_load_index(t,q)==new_load_index(t,q)
        assert old_accept_index(t,q)==new_accept_index(t,q)
        checks+=1
# All outer transformations are intentionally identical: only bracket selection differs.
repeat_checks=0
for t in ([0.,1e-9,2e-9,3e-9],[0.,1e-9,1e-9,3e-9]):
    end=t[-1]
    for start in (0.,1e-9):
        for delay in (0.,.37e-9):
            for ckttime in (0.,start+delay,end+delay,math.nextafter(end+delay,math.inf),end+delay+.5e-9,20e-9):
                q=ckttime-delay
                if q> end:
                    period=end-start;q-=start;q-=period*math.floor(q/period);q+=start
                assert old_load_index(t,q)==new_load_index(t,q)
                for minbreak in (0.,1e-15,1e-12):
                    assert old_accept_index(t,q+minbreak)==new_accept_index(t,q+minbreak)
                    repeat_checks+=1
out={'finite_nondecreasing_search_query_checks':checks,'repeat_delay_minbreak_checks':repeat_checks,'explicit_cases':cases,'scope':'Index equivalence on finite nondecreasing knots; existing first/end/repeat/delay branches and interpolation arithmetic remain unchanged. Descending or NaN knots require original fallback or explicit unsupported-input limitation.'}
(folder/'search-semantics.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({k:v for k,v in out.items() if k!='explicit_cases'}))
