"""Compare lift on/off on IDENTICAL saved tracks. This does not re-optimize them.
Usage: python compare_magnus.py --output-dir magnus_example
"""
import argparse
import csv
from pathlib import Path
import numpy as np
from brachistochrone import BrachistochroneEnv, cycloid_curve


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',default='results')
    a=p.parse_args(); out=Path(a.output_dir)
    with np.load(out/'snapshots_rotation.npz') as z:
        x=z['x'].copy(); learned=z['y'][-1].copy()
        config={k:z[k].item() for k in ('R','mu','k','use_air_drag','lift_slope','lift_cap','physics_dt','omega0') if k in z}
    curves={'straight':np.linspace(.5,0,len(x)), 'cycloid':cycloid_curve(x)[0], 'learned_fixed':learned}
    rows=[]
    # Independent initial conditions; their initial rotational energies differ.
    for omega0 in (0.,100.,-100.):
        for name,y in curves.items():
            for lift in (False,True):
                cfg=dict(config); cfg['omega0']=omega0
                e=BrachistochroneEnv(**cfg,n_segments=len(x)-1,use_rotation=True,dynamic_spin=True,use_magnus=lift)
                t,ok=e.simulate_physics(y); tr=e._last_trace
                peak=float(np.max(np.abs(tr['magnus'])))/(e.m*e.g) if ok else ''
                rows.append([name,omega0,lift,ok,t if ok else '',peak,e.last_failure])
    with open(out/'magnus_sensitivity.csv','w',newline='') as f:
        w=csv.writer(f);w.writerow(['fixed_track','omega0_rad_s','lift_enabled','success','time_s','peak_abs_lift_over_mg','failure']);w.writerows(rows)
    print('Fixed-track sensitivity, no reoptimization:')
    for r in rows: print(r)
    # Time-step convergence on a fixed geometry, including the force-off case.
    with open(out/'timestep_check.csv','w',newline='') as f:
        w=csv.writer(f);w.writerow(['dt_s','lift_enabled','success','time_s'])
        for dt in (.01,.005,.0025,.00125):
            for lift in (False,True):
                cfg=dict(config);cfg['physics_dt']=dt
                e=BrachistochroneEnv(**cfg,n_segments=len(x)-1,use_rotation=True,dynamic_spin=True,use_magnus=lift)
                t,ok=e.simulate_physics(learned)
                w.writerow([dt,lift,ok,t if ok else ''])
    print('Saved magnus_sensitivity.csv and timestep_check.csv')

if __name__=='__main__': main()
