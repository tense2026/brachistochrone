# Gymnasium is optional for the standalone NumPy optimizer.
try:
    import gymnasium as gym
    from gymnasium import spaces
    EnvBase = gym.Env
except ImportError:
    gym = None
    spaces = None
    EnvBase = object
import numpy as np
import matplotlib.pyplot as plt
import argparse
import csv
from pathlib import Path


class BrachistochroneEnv(EnvBase):
    """
    현실적 물리변수(부피 R, 공기저항, 마찰 mu, 회전 k)가 모두 반영된 최적강하선 탐색 환경
    """
    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": 30}

    def __init__(self, R=0.015, mu=0.2, k=0.4, use_rotation=True, use_air_drag=True, n_segments=30, render_mode=None, use_magnus=False, dynamic_spin=False,
                 lift_slope=0.5, lift_cap=0.5, omega0=0.0, physics_dt=0.005, mass=0.05, height=0.5, length=1.0, track_radius=None):
        super().__init__()
        if render_mode not in (None, "human", "rgb_array"):
            raise ValueError("render_mode must be None, human, or rgb_array")
        self.use_magnus = bool(use_magnus)
        self.dynamic_spin = bool(dynamic_spin or use_magnus)
        self.lift_slope, self.lift_cap = float(lift_slope), float(lift_cap)
        self.omega0, self.physics_dt = float(omega0), float(physics_dt)
        if not all(np.isfinite(q) for q in (R, mu, k, lift_slope, lift_cap, omega0, physics_dt)):
            raise ValueError("Physics parameters must be finite")
        if R < 0 or mu < 0 or k < 0 or lift_slope < 0 or lift_cap < 0 or physics_dt <= 0:
            raise ValueError("Invalid physics parameter")
        if self.dynamic_spin and use_rotation and (R <= 0 or k <= 0):
            raise ValueError("Dynamic spin requires R>0 and k>0")
        self.last_failure = ""
        self.render_mode = render_mode
        self._renderer = None
        self._render_y = None
        self._render_caption = ""
        self._last_trace = None
        
        # 1. 통제변인 설정
        self.H = float(height)              # 출발 높이 (m)
        self.L = float(length)              # 수평 이동 거리 (m)
        self.g = 10.0             # 중력가속도 (m/s^2)
        self.m = float(mass)             # 구의 질량 (kg, 50g)
        if min(self.H, self.L, self.m) <= 0:
            raise ValueError("height, length, mass must be positive")
        self.rho_air = 1.2        # 공기 밀도 (kg/m^3)
        self.Cd = 0.47            # 구형 물체의 공기저항 항력 계수
        
        # 2. 조작변인 설정
        self.track_radius = R if track_radius is None else float(track_radius)
        self.R = R                # 물체의 반지름 (m) -> 부피 V = (4/3)*pi*R^3
        self.mu = mu              # 강하선의 마찰 계수
        self.use_rotation = use_rotation      # 회전 고려 여부 (True/False)
        self.k = k if use_rotation else 0.0   # 관성모멘트 계수 (꽉 찬 구: 0.4, 속 빈 구: 0.67)
        self.use_air_drag = use_air_drag      # 공기저항 고려 여부 (기본값 True)
        
        # 3. 구간 분할 설정
        self.N = n_segments
        self.dx = self.L / self.N
        self.x = np.linspace(0, self.L, self.N + 1)
        
        if spaces is not None:
            self.action_space = spaces.Box(low=-6.0, high=6.0, shape=(self.N,), dtype=np.float32)
            self.observation_space = spaces.Box(low=0.0, high=np.inf, shape=(3,), dtype=np.float32)

    def reset(self, seed=None, options=None):
        if gym is not None:
            super().reset(seed=seed)
        self._render_y = np.linspace(self.H, 0, self.N + 1)
        if self.render_mode == "human":
            self.render()
        return np.array([self.R, self.mu, self.k], dtype=np.float32), {}

    def _action_to_curve(self, action):
        """Raw actions -> signed height drops. No averaging/interpolation filter.

        Subtracting a uniform offset permits a short rising section, unlike the
        old strictly descending parameterization. Endpoints remain fixed.
        """
        action = np.asarray(action, dtype=float)
        if action.shape != (self.N,) or not np.all(np.isfinite(action)):
            raise ValueError("action must be a finite vector of length N")
        z = np.clip(action, -6.0, 6.0)
        weights = np.exp(z - z.max())
        ratios = 1.5 * weights / weights.sum() - 0.5 / self.N
        y = np.r_[self.H, self.H - np.cumsum(self.H * ratios)]
        y[-1] = 0.0
        return y

    def render(self):
        if self.render_mode is None:
            return None
        from visualization import EnvRenderer
        if self._renderer is None:
            self._renderer = EnvRenderer(self, self.render_mode)
        y = self._render_y if self._render_y is not None else np.linspace(self.H, 0, self.N + 1)
        return self._renderer.draw(y, self._render_caption)

    def close(self):
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None

    def simulate_physics(self, y):
        if self.dynamic_spin:
            from magnus_physics import simulate
            return simulate(self, y)
        self._last_trace = None
        self.last_failure = ""
        trace_t, trace_v, trace_a = [0.0], [0.0], []
        v = 0.0
        total_time = 0.0
        
        dy_dx = np.gradient(y, self.dx)
        d2y_dx2 = np.gradient(dy_dx, self.dx)
        
        for i in range(self.N):
            dy = y[i] - y[i+1]
            ds = np.sqrt(self.dx**2 + dy**2)
            
            sin_theta = dy / ds
            cos_theta = self.dx / ds
            
            # --- [수식 1] 곡률 반경(rho_track) 및 질량중심 오프셋(R) 반영 ---
            y_prime = (dy_dx[i] + dy_dx[i+1]) / 2.0
            y_double_prime = (d2y_dx2[i] + d2y_dx2[i+1]) / 2.0
            kappa = y_double_prime / ((1.0 + y_prime**2)**1.5)
            
            if abs(kappa) > 1e-6:
                rho_track = 1.0 / abs(kappa)
                if kappa > 0:
                    if rho_track <= self.R * 1.05:
                        self.last_failure = "radius_constraint"
                        return None, False
                    rho_c = rho_track - self.R
                    centripetal_acc = (v**2) / rho_c
                else:
                    rho_c = rho_track + self.R
                    centripetal_acc = -(v**2) / rho_c
            else:
                centripetal_acc = 0.0

            N_force = self.m * self.g * cos_theta + self.m * centripetal_acc
            if N_force < 0:
                self.last_failure = "contact_lost"
                return None, False

            # --- [수식 2] 부피(반지름 R)에 따른 공기저항력(F_drag) 반영 ---
            if self.use_air_drag:
                area = np.pi * (self.R ** 2)
                F_drag = 0.5 * self.Cd * self.rho_air * area * (v ** 2)
            else:
                F_drag = 0.0

            # --- [수식 3] 회전 고려 유무 및 마찰력 반영 ---
            if not self.use_rotation:
                a = self.g * sin_theta - (self.mu * N_force) / self.m - (F_drag / self.m)
            else:
                a_roll = (self.g * sin_theta - (F_drag / self.m)) / (1.0 + self.k)
                f_needed = self.k * self.m * max(a_roll, 0.0)
                f_max = self.mu * N_force
                
                if f_needed <= f_max:
                    a = a_roll
                else:
                    a = self.g * sin_theta - (f_max / self.m) - (F_drag / self.m)

            # --- [수식 4] 등가속도 공식으로 나중 속력(v_next)과 시간(dt) 계산 ---
            v_next_sq = v**2 + 2 * a * ds
            if v_next_sq <= 1e-8:
                self.last_failure = "stalled_or_reversed"
                return None, False
                
            v_next = np.sqrt(v_next_sq)
            dt = (2.0 * ds) / (v + v_next)
            
            total_time += dt
            trace_t.append(total_time)
            trace_v.append(v_next)
            trace_a.append(a)
            v = v_next
            
        self._last_trace = {"t": np.array(trace_t), "v": np.array(trace_v),
                            "a": np.array(trace_a), "x": self.x.copy(),
                            "y": np.asarray(y).copy()}
        return total_time, True

    def step(self, action):
        y = self._action_to_curve(action)
        total_time, success = self.simulate_physics(y)
        self._render_y = y.copy()
        if self.render_mode == "human":
            self.render()
        
        # Optimize travel time only: no smoothness reward or filter.
        reward = -float(total_time) if success else -100.0

        obs = np.array([self.R, self.mu, self.k], dtype=np.float32)
        info = {"total_time": total_time, "y_coords": y, "success": success, "failure_reason": self.last_failure}
        return obs, reward, True, False, info


def cycloid_curve(x, H=0.5, L=1.0, g=10.0):
    """Classical frictionless point-mass brachistochrone, endpoints (0,H),(L,0).

    Solve (theta-sin(theta))/(1-cos(theta))=L/H by bisection.
    Solve x(theta) at each requested x, without interpolating the learned curve.
    Returns (y, analytic_time). `g` must match the caller's gravity, otherwise the
    returned analytic time does not correspond to the simulated physics.
    """
    lo, hi = 1e-5, 2 * np.pi - 1e-5
    for _ in range(100):
        theta = (lo + hi) / 2
        if (theta - np.sin(theta)) / (1 - np.cos(theta)) < L / H:
            lo = theta
        else:
            hi = theta
    theta_end = (lo + hi) / 2
    radius = H / (1 - np.cos(theta_end))
    left = np.zeros_like(np.asarray(x, dtype=float))
    right = np.full_like(left, theta_end)
    for _ in range(80):
        mid = (left + right) / 2
        mask = radius * (mid - np.sin(mid)) < x
        left = np.where(mask, mid, left)
        right = np.where(mask, right, mid)
    y = H - radius * (1 - np.cos((left + right) / 2))
    y[0], y[-1] = H, 0.0
    return y, theta_end * np.sqrt(radius / float(g))


def train_and_get_curve(R, mu, k, use_rotation, episodes=1500, pop_size=32,
                        seed=42, output_dir="results", use_air_drag=True,
                        n_segments=30, visualize=False, render_every=20, initial_action=None, **physics):
    """Elitist (1+lambda) evolution strategy on a one-step Gymnasium task.

    This is derivative-free policy search, NOT PPO/SAC or a neural-network agent.
    All evaluated successful candidates can update the archive. No smoothing.
    """
    if episodes < 1 or pop_size < 2 or n_segments < 3:
        raise ValueError("episodes>=1, pop_size>=2, n_segments>=3 required")
    env = BrachistochroneEnv(R=R, mu=mu, k=k, use_rotation=use_rotation,
                            use_air_drag=use_air_drag, n_segments=n_segments, **physics)
    rng = np.random.default_rng(seed)
    mean = np.zeros(env.N) if initial_action is None else np.asarray(initial_action, dtype=float).copy()
    _, best_reward, _, _, initial = env.step(mean)
    best_time = initial["total_time"] if initial["success"] else float("inf")
    best_y = initial["y_coords"].copy() if initial["success"] else None
    initial_time = best_time
    updates = 0
    evaluations = 1
    mode = "rotation" if use_rotation else "no_rotation"
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    history = []
    snapshot_y = [initial["y_coords"].copy()]
    snapshot_t = [best_time]
    # A separate display environment avoids rendering each candidate evaluation.
    display = BrachistochroneEnv(R=R, mu=mu, k=k, use_rotation=use_rotation,
                                use_air_drag=use_air_drag, n_segments=n_segments,
                                render_mode="human", **physics) if visualize else None
    if best_y is not None:
        np.savetxt(out / f"initial_{mode}.csv", np.c_[env.x, best_y],
                   delimiter=",", header="x_m,y_m", comments="")
    for ep in range(1, episodes + 1):
        # Sparse, pairwise, and full-dimensional mutations are search proposals,
        # not filters: raw action entries are changed directly.
        sigma = 0.35 * (0.025 / 0.35) ** ((ep - 1) / max(episodes - 1, 1))
        count = (1, 2, 4, env.N)[(ep - 1) % 4]
        noise = np.zeros((pop_size, env.N))
        for i in range(0, pop_size, 2):
            idx = rng.choice(env.N, size=min(count, env.N), replace=False)
            noise[i, idx] = rng.normal(size=len(idx))
            if i + 1 < pop_size:
                noise[i + 1] = -noise[i]
        # Evaluate whole population around the SAME parent before updating it.
        candidates = np.clip(mean + sigma * noise, -6.0, 6.0)
        winner = None
        generation_reward = best_reward
        valid = 0
        generation_times = []
        for action in candidates:
            _, reward, _, _, info = env.step(action)
            evaluations += 1
            if info["success"]:
                valid += 1
                generation_times.append(info["total_time"])
                if reward > generation_reward:
                    generation_reward = reward
                    winner = (action.copy(), info)
        if winner is not None:
            mean, info = winner
            best_reward = generation_reward
            best_time = info["total_time"]
            best_y = info["y_coords"].copy()
            updates += 1
        snapshot_y.append(best_y.copy() if best_y is not None else np.full(env.N + 1, np.nan))
        snapshot_t.append(best_time)
        if display is not None and (ep == 1 or ep % max(1, render_every) == 0 or ep == episodes):
            if best_y is not None:
                display._render_y = best_y
            display._render_caption = f"{mode} | generation {ep}/{episodes} | best {best_time:.8f}s | valid {valid}/{pop_size}"
            display.render()
        history.append([ep, evaluations, best_time,
                        np.mean(generation_times) if generation_times else np.nan,
                        valid / pop_size, sigma, updates])
        if ep == 1 or ep % max(1, episodes // 10) == 0 or ep == episodes:
            print(f"[{mode}] generation {ep}/{episodes} | best={best_time:.8f}s "
                  f"| valid={valid}/{pop_size} | updates={updates} | sigma={sigma:.5f}")
    if display is not None:
        display.close()
    np.savez_compressed(out / f"snapshots_{mode}.npz", x=env.x,
                        y=np.asarray(snapshot_y), times=np.asarray(snapshot_t),
                        generations=np.arange(episodes + 1), R=R, mu=mu, k=k,
                        use_rotation=use_rotation, use_air_drag=use_air_drag,
                        use_magnus=env.use_magnus, dynamic_spin=env.dynamic_spin,
                        lift_slope=env.lift_slope, lift_cap=env.lift_cap,
                        omega0=env.omega0, physics_dt=env.physics_dt, mass=env.m, height=env.H, length=env.L, track_radius=env.track_radius)
    with open(out / f"history_{mode}.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["generation", "evaluations", "best_time_s", "valid_mean_time_s",
                         "success_fraction", "sigma", "record_updates"])
        writer.writerows(history)
    if best_y is None:
        raise RuntimeError("No valid path found. Change seed/parameters; no fake curve is returned.")
    np.savetxt(out / f"best_{mode}.csv", np.c_[env.x, best_y],
               delimiter=",", header="x_m,y_m", comments="")
    np.save(out / f"best_action_{mode}.npy", mean)
    if np.isfinite(initial_time):
        print(f"[{mode}] initial={initial_time:.8f}s -> best={best_time:.8f}s "
              f"({100 * (initial_time - best_time) / initial_time:.3f}% improvement)")
    return env.x, best_y, best_time


def main():
    parser = argparse.ArgumentParser(description="Unfiltered ES curve search and cycloid comparison")
    parser.add_argument("--episodes", type=int, default=1500, help="population generations, not individual evaluations")
    parser.add_argument("--pop-size", type=int, default=32)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--segments", type=int, default=30)
    parser.add_argument("--output-dir", default="results")
    parser.add_argument("--no-show", action="store_true")
    parser.add_argument("--visualize", action="store_true", help="explicitly enable live rendering (default unless --no-show)")
    parser.add_argument("--render-every", type=int, default=20, help="live display generation interval")
    parser.add_argument("--replay-only", action="store_true", help="open saved snapshots without training")
    parser.add_argument("--no-magnus", action="store_true", help="disable lift only; retain dynamic spin model")
    parser.add_argument("--lift-slope", type=float, default=0.5, help="assumed C_L slope, NOT a measured coefficient")
    parser.add_argument("--lift-cap", type=float, default=0.5)
    parser.add_argument("--omega0", type=float, default=0.0, help="initial spin rad/s; positive=backspin, negative=topspin")
    parser.add_argument("--physics-dt", type=float, default=0.005)
    args = parser.parse_args()
    if args.replay_only:
        from visualization import ReplayViewer
        viewer = ReplayViewer(args.output_dir)
        plt.show()
        return
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    common = dict(R=0.015, mu=0.2, k=0.4, dynamic_spin=True,
                  use_magnus=not args.no_magnus, lift_slope=args.lift_slope,
                  lift_cap=args.lift_cap, omega0=args.omega0, physics_dt=args.physics_dt)
    results = []
    rows = []
    colors = ["#1751D0", "#E2661E", "#0E9E8F", "#C08A00"]
    trained = []
    for rotation in [False, True]:
        x, learned, best_time = train_and_get_curve(
            **common, use_rotation=rotation, episodes=args.episodes,
            pop_size=args.pop_size, seed=args.seed, n_segments=args.segments,
            output_dir=out, visualize=not args.no_show, render_every=args.render_every)
        trained.append((rotation, x, learned, best_time))
    ideal_time = float("nan")
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True, facecolor="#FDFDFF")
    for ax, (rotation, x, learned, best_time) in zip(axes, trained):
        env = BrachistochroneEnv(**common, use_rotation=rotation, n_segments=args.segments)
        straight = np.linspace(env.H, 0, env.N + 1)
        cycloid, ideal_time = cycloid_curve(x, env.H, env.L, env.g)
        # ALL reported comparison times use the SAME physics and x-grid.
        curves = [("Straight", straight, "--"), ("Classical cycloid", cycloid, "-."),
                  ("Learned (ES, no filter)", learned, "-")]
        for (name, y, style), color in zip(curves, colors):
            t, ok = env.simulate_physics(y)
            label = f"{name}: {t:.6f}s" if ok else f"{name}: infeasible"
            ax.plot(x, y, style, color=color, linewidth=1.8, label=label)
            rows.append(["rotation" if rotation else "no_rotation", name, ok, t if ok else ""])
        if rotation:
            from magnus_physics import simulate
            env.use_magnus = False
            for name, y, _ in curves:
                t, ok = env.simulate_physics(y)
                rows.append(["rotation_lift_off_same_path", name, ok, t if ok else ""])
            env.use_magnus = not args.no_magnus
        ax.set_title("Dynamic spin + Magnus" if rotation and not args.no_magnus else
                     ("Dynamic spin, lift off" if rotation else "Non-rotating sliding"))
        ax.set_xlabel("Horizontal distance x (m)")
        ax.set_facecolor("#FDFDFF")
        ax.grid(True, color="#E2E6F0", linewidth=0.6)
        ax.legend(fontsize=8, frameon=False)
        results.append((rotation, best_time))
    axes[0].set_ylabel("Height y (m)")
    fig.suptitle("Same-physics comparison | piecewise-linear, unfiltered curves")
    fig.tight_layout()
    fig.savefig(out / "curve_comparison.png", dpi=160)
    with open(out / "comparison.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["physics_mode", "curve", "success", "time_s"])
        writer.writerows(rows)
    print("\nSame-physics comparison:")
    for row in rows:
        print(row)
    print(f"Classical IDEAL point-mass analytic time (not comparable to realistic times): {ideal_time:.8f}s")
    fig2, ax = plt.subplots(figsize=(8, 4), facecolor="#FDFDFF")
    for rotation, color in zip([False, True], colors):
        mode = "rotation" if rotation else "no_rotation"
        h = np.genfromtxt(out / f"history_{mode}.csv", delimiter=",", names=True)
        ax.plot(np.atleast_1d(h["evaluations"]), np.atleast_1d(h["best_time_s"]),
                color=color, label=mode.replace("_", " "))
    ax.set(xlabel="Physics evaluations", ylabel="Best travel time (s)",
           title="Learning/search progress (no moving average)")
    ax.grid(True, color="#E2E6F0")
    ax.legend(frameon=False)
    fig2.tight_layout()
    fig2.savefig(out / "training_history.png", dpi=160)
    print(f"Saved results to {out.resolve()}")
    if not args.no_show:
        from visualization import ReplayViewer
        viewer = ReplayViewer(out)
        plt.show()
    else:
        plt.close("all")


if __name__ == "__main__":
    main()
