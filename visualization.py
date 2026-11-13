"""Gymnasium rendering and saved-generation playback. No curve smoothing."""
from pathlib import Path
import time
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Slider, Button, RadioButtons

COLORS = ["#1751D0", "#E2661E", "#0E9E8F"]


def position_at(trace, elapsed):
    """Exact within each constant-acceleration segment of the physics model.

    This interpolates a particle's position in TIME, not the track's shape.
    """
    if trace is None:
        return None
    t = float(np.clip(elapsed, 0, trace['t'][-1]))
    i = min(int(np.searchsorted(trace['t'], t, side='right') - 1), len(trace['a']) - 1)
    i = max(i, 0)
    dt = t - trace['t'][i]
    ds = np.hypot(trace['x'][i+1] - trace['x'][i], trace['y'][i+1] - trace['y'][i])
    distance = trace['v'][i] * dt + .5 * trace['a'][i] * dt**2
    fraction = np.clip(distance / ds, 0, 1)
    return (trace['x'][i] + fraction * (trace['x'][i+1] - trace['x'][i]),
            trace['y'][i] + fraction * (trace['y'][i+1] - trace['y'][i]))


def style_axes(ax):
    ax.set_facecolor('#FDFDFF')
    ax.grid(True, color='#E2E6F0', linewidth=.6)
    ax.spines[['top', 'right']].set_visible(False)
    ax.tick_params(colors='#505A74')
    ax.set_xlabel('Horizontal distance x (m)')
    ax.set_ylabel('Height y (m)')


class EnvRenderer:
    def __init__(self, env, mode):
        self.env, self.mode = env, mode
        self.closed = False
        if mode == 'rgb_array':
            self.fig = Figure(figsize=(9, 5), dpi=100, facecolor='#FDFDFF')
            FigureCanvasAgg(self.fig)
        else:
            self.fig = plt.figure(figsize=(9, 5), facecolor='#FDFDFF')
            self.fig.canvas.mpl_connect('close_event', lambda event: setattr(self, 'closed', True))
            plt.show(block=False)
        self.ax = self.fig.add_subplot(111)
        style_axes(self.ax)
        from brachistochrone import cycloid_curve
        cy, _ = cycloid_curve(env.x, env.H, env.L, env.g)
        self.ax.plot(env.x, np.linspace(env.H, 0, env.N+1), '--', color=COLORS[0], label='Straight')
        self.ax.plot(env.x, cy, '-.', color=COLORS[1], label='Classical cycloid')
        self.line, = self.ax.plot(env.x, np.linspace(env.H, 0, env.N+1), color=COLORS[2], label='Current curve (no filter)')
        self.ax.set_xlim(-.02, env.L+.02)
        self.ax.set_ylim(-.3*env.H, 1.12*env.H)
        self.ax.legend(loc='upper right', fontsize=8, frameon=False)
        self.fig.tight_layout()

    def draw(self, y, caption=''):
        if self.closed:
            return None
        self.line.set_ydata(y)
        self.ax.set_title(caption or 'Gymnasium environment | unfiltered track', fontsize=10)
        self.fig.canvas.draw()
        if self.mode == 'rgb_array':
            return np.asarray(self.fig.canvas.buffer_rgba())[..., :3].copy()
        self.fig.canvas.flush_events()
        plt.pause(.001)
        return None

    def close(self):
        self.closed = True
        plt.close(self.fig)


class ReplayViewer:
    """Evolution playback and same-physics particle race, using saved generations."""
    def __init__(self, output_dir):
        self.directory = Path(output_dir)
        self.datasets = {}
        for mode in ('no_rotation', 'rotation'):
            path = self.directory / f'snapshots_{mode}.npz'
            if path.exists():
                with np.load(path) as data:
                    self.datasets[mode] = {key: data[key].copy() for key in data.files}
        if not self.datasets:
            raise FileNotFoundError(f'No snapshots in {self.directory}. Run training first.')
        self.mode = next(iter(self.datasets))
        self.playing = True
        self.evolution = True
        self.cursor = 0.0
        self.elapsed = 0.0
        self.last_clock = time.perf_counter()
        self.fig = plt.figure(figsize=(12, 7), facecolor='#FDFDFF')
        self.fig.subplots_adjust(left=.08, right=.96, top=.88, bottom=.34, wspace=.27)
        self.ax = self.fig.add_subplot(121)
        self.progress_ax = self.fig.add_subplot(122)
        style_axes(self.ax)
        self.progress_ax.set(xlabel='Generation', ylabel='Best time (s)')
        self.progress_ax.grid(True, color='#E2E6F0')
        self.lines = [self.ax.plot([], [], style, color=c, linewidth=1.7)[0]
                      for c, style in zip(COLORS, ['--', '-.', '-'])]
        self.balls = [self.ax.plot([], [], 'o', color=c, markersize=7)[0] for c in COLORS]
        self.history_line, = self.progress_ax.plot([], [], color=COLORS[2])
        self.marker = self.progress_ax.axvline(0, color='#505A74', linestyle='--')
        self.status = self.fig.text(.08, .94, '', fontsize=10, color='#1E2433')
        self.force_text = self.fig.text(.57, .075, '', fontsize=8, color='#1E2433')
        self.fig.text(.08, .89, 'Markers follow the simulated track coordinates, not exact sphere-center offsets.', fontsize=8, color='#505A74')
        self.speed = Slider(self.fig.add_axes([.17, .22, .53, .03]), 'Speed', .25, 20, valinit=1, valfmt='%.2fx')
        self.generation = Slider(self.fig.add_axes([.17, .28, .53, .03]), 'Generation', 0, 1, valinit=0, valstep=1)
        self.generation.on_changed(self.seek)
        self.pause = Button(self.fig.add_axes([.08, .08, .13, .06]), 'Pause / Play')
        self.pause.on_clicked(self.toggle_play)
        self.race = Button(self.fig.add_axes([.23, .08, .16, .06]), 'Race / Evolution')
        self.race.on_clicked(self.toggle_mode)
        self.restart = Button(self.fig.add_axes([.41, .08, .13, .06]), 'Restart')
        self.restart.on_clicked(self.restart_playback)
        self.conditions = RadioButtons(self.fig.add_axes([.76, .07, .2, .17]), list(self.datasets), active=0)
        self.conditions.on_clicked(self.switch_condition)
        self.fig.text(.08, .025, 'Evolution: 10 generations/s at 1x. Race: physical seconds at 1x. Speed changes playback, not training compute.', fontsize=8)
        self.configure()
        self.animation = FuncAnimation(self.fig, self.tick, interval=33, blit=False, cache_frame_data=False)
        self.fig.canvas.mpl_connect('close_event', lambda event: self.animation.event_source.stop())

    def configure(self):
        from brachistochrone import BrachistochroneEnv, cycloid_curve
        self.data = self.datasets[self.mode]
        self.x = self.data['x']
        self.env = BrachistochroneEnv(R=float(self.data['R']), mu=float(self.data['mu']),
                    k=float(self.data['k']), use_rotation=bool(self.data['use_rotation']),
                    use_air_drag=bool(self.data['use_air_drag']), n_segments=len(self.x)-1)
        for key, attr in [('mass','m'),('height','H'),('length','L')]:
            if key in self.data:
                setattr(self.env, attr, float(self.data[key]))
        self.env.x = self.x.copy()
        self.env.dx = self.env.L / self.env.N
        for key in ('use_magnus', 'dynamic_spin', 'lift_slope', 'lift_cap', 'omega0', 'physics_dt', 'track_radius'):
            if key in self.data:
                setattr(self.env, key, self.data[key].item())
        self.cycloid, _ = cycloid_curve(self.x, self.env.H, self.env.L)
        self.straight = np.linspace(self.env.H, 0, len(self.x))
        self.max_gen = len(self.data['y'])-1
        self.generation.valmax = max(1, self.max_gen)
        self.generation.ax.set_xlim(0, max(1, self.max_gen))
        self.cursor, self.elapsed = 0.0, 0.0
        self.history_line.set_data(self.data['generations'], self.data['times'])
        self.progress_ax.relim()
        self.progress_ax.autoscale_view()
        self.ax.set_xlim(-.02, self.env.L+.02)
        valid_y = self.data['y'][np.isfinite(self.data['y'])]
        low = min(float(valid_y.min()) if len(valid_y) else 0, float(self.cycloid.min()))
        self.ax.set_ylim(low-.04, self.env.H+.06)
        self.generation.set_val(0)

    def seek(self, value):
        self.cursor = float(np.clip(value, 0, self.max_gen))
        self.elapsed = 0.0
        self.refresh_curves()

    def refresh_curves(self):
        index = int(self.cursor)
        curves = [self.straight, self.cycloid, self.data['y'][index]]
        names = ['Straight', 'Classical cycloid', 'Learned (ES, no filter)']
        self.traces, labels = [], []
        for line, y, name in zip(self.lines, curves, names):
            line.set_data(self.x, y)
            if np.all(np.isfinite(y)):
                t, ok = self.env.simulate_physics(y)
            else:
                t, ok = None, False
            self.traces.append(self.env._last_trace if ok else None)
            labels.append(f'{name}: {t:.6f}s' if ok else f'{name}: infeasible')
        for line, label in zip(self.lines, labels):
            line.set_label(label)
        self.ax.legend(loc='upper right', fontsize=8, frameon=False)
        self.marker.set_xdata([index, index])
        self.draw_particles()
        self.update_status()

    def update_status(self):
        label = 'EVOLUTION (saved best paths)' if self.evolution else 'RACE (selected generation frozen)'
        self.status.set_text(f'{self.mode} | Magnus={self.env.use_magnus} | {label} | generation {int(self.cursor)}/{self.max_gen} | {self.speed.val:.2f}x')

    def draw_particles(self):
        valid = [tr['t'][-1] for tr in self.traces if tr is not None]
        cycle = max(valid, default=1) + .4
        for ball, trace in zip(self.balls, self.traces):
            pos = position_at(trace, self.elapsed % cycle)
            ball.set_data([], []) if pos is None else ball.set_data([pos[0]], [pos[1]])
        trace = self.traces[-1]
        if trace is not None and 'omega' in trace:
            t = min(self.elapsed % cycle, trace['t'][-1])
            j = min(max(int(np.searchsorted(trace['t'], t, side='right')-1), 0), len(trace['a'])-1)
            self.force_text.set_text(f"Learned track\nomega = {trace['omega'][j]:+.2f} rad/s\nF_M = {trace['magnus'][j]:+.5f} N\nN = {trace['normal'][j]:.4f} N")
        else:
            self.force_text.set_text('')

    def tick(self, _frame):
        now = time.perf_counter()
        dt = min(max(now-self.last_clock, 0), .2)
        self.last_clock = now
        if self.playing:
            if self.evolution:
                new = min(self.cursor + dt*self.speed.val*10, self.max_gen)
                # set_val triggers seek, which redraws the matching raw saved curve.
                if int(new) != int(self.cursor):
                    self.generation.set_val(int(new))
                self.cursor = new
                if new >= self.max_gen:
                    self.evolution = False
                    self.elapsed = 0
            self.elapsed += dt*self.speed.val
            self.draw_particles()
        self.update_status()
        return self.lines + self.balls

    def toggle_play(self, _event=None):
        self.playing = not self.playing
        self.last_clock = time.perf_counter()

    def toggle_mode(self, _event=None):
        self.evolution = not self.evolution
        if self.evolution and self.cursor >= self.max_gen:
            self.generation.set_val(0)
        self.elapsed = 0.0

    def restart_playback(self, _event=None):
        self.elapsed = 0.0
        if self.evolution:
            self.generation.set_val(0)
        self.playing = True

    def switch_condition(self, mode):
        self.mode = mode
        self.configure()
