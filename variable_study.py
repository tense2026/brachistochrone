"""One-effect-at-a-time study and combined-effects comparison.
Run python variable_study.py; replay: --replay-only --output-dir variable_results/06_all
All cases share endpoints, mass and numerical resolution. No moving-average filter.
"""
import argparse
import csv
import json
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from brachistochrone import BrachistochroneEnv, cycloid_curve, train_and_get_curve

GRAVITY = 10.0  # must match BrachistochroneEnv.g

COLORS=['#1751D0','#E2661E','#0E9E8F','#C08A00','#D95D8F','#2E7D32','#9117D0']
CASES=[
 ('00_ideal','Ideal reference',dict(R=0.,track_radius=0.,mu=0.,use_rotation=False,use_air_drag=False,use_magnus=False)),
 ('01_radius','Finite radius only',dict(R=.02,track_radius=.02,mu=0.,use_rotation=False,use_air_drag=False,use_magnus=False)),
 ('02_friction','Sliding friction only',dict(R=0.,track_radius=0.,mu=.15,use_rotation=False,use_air_drag=False,use_magnus=False)),
 ('03_drag','Air drag only',dict(R=.02,track_radius=0.,mu=0.,use_rotation=False,use_air_drag=True,use_magnus=False)),
 ('04_rotation','Pure rolling only',dict(R=.02,track_radius=0.,mu=100.,use_rotation=True,use_air_drag=False,use_magnus=False)),
 ('05_magnus','Magnus only (free spin)',dict(R=.02,track_radius=0.,mu=0.,use_rotation=True,use_air_drag=False,use_magnus=True,omega0=-100.)),
 ('06_all','All effects',dict(R=.02,track_radius=.02,mu=.15,use_rotation=True,use_air_drag=True,use_magnus=True)),
]


def axes_style(ax):
    ax.set_facecolor('#FDFDFF');ax.grid(True,color='#E2E6F0',linewidth=.6)
    ax.spines[['top','right']].set_visible(False)
    ax.set_xlabel('Horizontal distance x (m)');ax.set_ylabel('Height y (m)')


def config_for(case,args):
    return dict(k=2/3, dynamic_spin=True, mass=args.mass,height=args.height,
                length=args.length,physics_dt=args.dt,**case)


def evaluate(env,y):
    t,ok=env.simulate_physics(y)
    return t if ok else None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--episodes',type=int,default=200)
    p.add_argument('--pop-size',type=int,default=20)
    p.add_argument('--segments',type=int,default=30)
    p.add_argument('--dt',type=float,default=.01)
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--mass',type=float,default=.0027)
    p.add_argument('--height',type=float,default=5.)
    p.add_argument('--length',type=float,default=10.)
    p.add_argument('--output-dir',default='variable_results')
    p.add_argument('--no-show',action='store_true')
    p.add_argument('--visualize',action='store_true',help='show best track during optimization')
    a=p.parse_args();out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
    (out/'settings.json').write_text(json.dumps(vars(a),indent=2))
    records=[];learned_curves=[]; configurations={}
    x=np.linspace(0,a.length,a.segments+1)
    cycloid,ideal_exact=cycloid_curve(x,a.height,a.length,GRAVITY)
    # Transparent analytic warm start, NOT evidence of learning a cycloid from scratch.
    drops=(cycloid[:-1]-cycloid[1:])/a.height
    weights=(drops+.5/a.segments)/1.5
    seed_action=np.log(np.maximum(weights,1e-12))
    seed_action-=.5*(seed_action.max()+seed_action.min())
    if seed_action.max()>6 or seed_action.min()<-6:
        raise ValueError('Cycloid not representable within action bounds at these endpoints')
    for index,(key,label,case) in enumerate(CASES):
        config=config_for(case,a); configurations[key]=config
        env=BrachistochroneEnv(**config,n_segments=a.segments)
        initial=seed_action if evaluate(env,cycloid) is not None else np.zeros(a.segments)
        xx,y,t=train_and_get_curve(**config, episodes=a.episodes,pop_size=a.pop_size,
            seed=a.seed,n_segments=a.segments,output_dir=out/key,initial_action=initial,
            visualize=a.visualize,render_every=20)
        tc=evaluate(env,cycloid)
        learned_curves.append(y)
        # Measure ALL geometry comparisons in the case's OWN physics.
        improvement=100*(tc-t)/tc if tc is not None else None
        records.append([key,label,tc,t,tc-t if tc is not None else None,improvement])
        fig,(ax,delta)=plt.subplots(1,2,figsize=(12,4.8),facecolor='#FDFDFF')
        axes_style(ax)
        ax.plot(x,cycloid,'--',color=COLORS[0],label='Classical cycloid')
        ax.plot(x,y,color=COLORS[index],label='Best found in this case')
        ax.set_title(label)
        ax.legend(frameon=False,fontsize=8)
        delta.plot(x,y-cycloid,color=COLORS[index]);delta.axhline(0,color='#737D96',linewidth=.7)
        delta.set(xlabel='Horizontal distance x (m)',ylabel='y_best - y_cycloid (m)',title='Actual displacement (not normalized)')
        delta.grid(True,color='#E2E6F0')
        note=f'Cycloid: {tc:.6f}s | best: {t:.6f}s | gain: {improvement:.3f}%' if tc is not None else f'Cycloid infeasible | best {t:.6f}s'
        fig.suptitle(note,fontsize=10);fig.tight_layout();fig.savefig(out/f'{key}.png',dpi=160);plt.close(fig)
        np.savetxt(out/f'{key}_coordinates.csv',np.c_[x,y,cycloid,y-cycloid],delimiter=',',header='x_m,best_y_m,cycloid_y_m,delta_y_m',comments='')
    with open(out/'summary.csv','w',newline='') as f:
        w=csv.writer(f);w.writerow(['case','label','cycloid_time_s','best_time_s','improvement_s','improvement_percent']);w.writerows(records)
    (out/'case_parameters.json').write_text(json.dumps(configurations,indent=2))
    fig,(ax,delta)=plt.subplots(1,2,figsize=(14,6),facecolor='#FDFDFF')
    axes_style(ax)
    for i,((key,label,_),y) in enumerate(zip(CASES,learned_curves)):
        ax.plot(x,y,color=COLORS[i],linewidth=1.6,linestyle=['-','--','-.',':','--','-.','-'][i],label=label)
        delta.plot(x,y-cycloid,color=COLORS[i],linewidth=1.5,label=label)
    ax.set_title('All individually optimized cases')
    ax.legend(frameon=False,fontsize=8)
    delta.axhline(0,color='#737D96',linewidth=.7)
    delta.set(xlabel='Horizontal distance x (m)',ylabel='y_best - y_cycloid (m)',title='Displacement from classical cycloid')
    delta.grid(True,color='#E2E6F0')
    fig.suptitle(f'Light hollow sphere | mass={a.mass*1000:g}g | H={a.height:g}m, L={a.length:g}m\nAnalytic cycloid warm start; fixed-grid best found, not a global optimum',fontsize=11)
    fig.tight_layout();fig.savefig(out/'combined.png',dpi=170)
    # Cross-evaluate every learned geometry in every physical environment.
    with open(out/'cross_evaluation.csv','w',newline='') as f:
        w=csv.writer(f);w.writerow(['physics_case']+[c[0] for c in CASES]+['classical_cycloid'])
        for key,label,case in CASES:
            env=BrachistochroneEnv(**config_for(case,a),n_segments=a.segments)
            w.writerow([key]+[evaluate(env,y) for y in learned_curves]+[evaluate(env,cycloid)])
    # Check temporal resolution on the exact SAME all-effects geometry.
    with open(out/'all_timestep_check.csv','w',newline='') as f:
        w=csv.writer(f);w.writerow(['dt_s','cycloid_s','learned_s','gain_s'])
        for dt in (a.dt,a.dt/2,a.dt/4):
            cfg=config_for(CASES[-1][2],a);cfg['physics_dt']=dt
            env=BrachistochroneEnv(**cfg,n_segments=a.segments)
            tc=evaluate(env,cycloid);tb=evaluate(env,learned_curves[-1])
            w.writerow([dt,tc,tb,tc-tb if tc is not None and tb is not None else None])
    print('\nRESULTS:');print(*records,sep='\n')
    print('Exact ideal point-mass cycloid time:',ideal_exact)
    if not a.no_show: plt.show()
    else: plt.close('all')

if __name__=='__main__': main()
