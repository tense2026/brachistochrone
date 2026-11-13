"""Contact-only sphere dynamics, quiescent air, planar spin. No track smoothing.
Positive omega = counterclockwise (backspin for rightward motion).
Lift coefficient is a tunable phenomenological assumption, not calibrated data.
"""
import math
import numpy as np


def magnus_normal(env, v, omega):
    if not env.use_magnus or env.R <= 0 or v <= 0:
        return 0.0
    spin = env.R * omega / max(v, 1e-12)
    cl = float(np.clip(env.lift_slope * spin, -env.lift_cap, env.lift_cap))
    return .5 * env.rho_air * math.pi * env.R**2 * v*v * cl


def simulate(env, y):
    env._last_trace = None
    env.last_failure = ''
    y = np.asarray(y, dtype=float)
    if y.shape != (env.N+1,) or not np.all(np.isfinite(y)):
        raise ValueError('Expected N+1 finite heights')
    slopes = np.gradient(y, env.dx)
    second = np.gradient(slopes, env.dx)
    v, omega, elapsed = 0.0, (env.omega0 if env.use_rotation else 0.0), 0.0
    ts, vs, ws, xs, ys = [0.0], [v], [omega], [0.0], [float(y[0])]
    accs, normals, lifts, frictions = [], [], [], []
    max_steps = int(30 / env.physics_dt) + env.N * 4
    steps = 0
    for i in range(env.N):
        drop = float(y[i] - y[i+1])
        length = math.hypot(env.dx, drop)
        sin_t, cos_t = drop / length, env.dx / length
        yp = .5 * (slopes[i]+slopes[i+1])
        ypp = .5 * (second[i]+second[i+1])
        curvature = float(ypp / (1+yp*yp)**1.5)
        # Same finite-radius normal curvature convention as the previous model.
        if curvature > 0 and 1/curvature <= 1.05*env.track_radius:
            env.last_failure = 'radius_constraint'
            return None, False
        kc = curvature / (1-env.track_radius*curvature)
        distance = 0.0
        while distance < length-1e-12:
            steps += 1
            if steps > max_steps:
                env.last_failure = 'time_or_step_limit'
                return None, False
            lift = magnus_normal(env, v, omega)
            normal = env.m*(env.g*cos_t + v*v*kc) - lift
            if normal < -1e-10:
                env.last_failure = 'contact_lost'
                return None, False
            normal = max(0.0, normal)
            drag = .5*env.Cd*env.rho_air*math.pi*env.R**2*v*v if env.use_air_drag else 0.0
            drive = env.g*sin_t-drag/env.m
            alpha = 0.0
            if env.use_rotation:
                # Contact-point slip: v + R*omega. Friction torque = R*f.
                slip = v+env.R*omega
                static_f = -env.m*drive*env.k/(1+env.k)
                capacity = env.mu*normal
                if abs(slip) < 1e-8 and abs(static_f) <= capacity:
                    friction = static_f
                else:
                    direction = slip if abs(slip) >= 1e-8 else drive
                    friction = -math.copysign(capacity, direction) if direction else 0.0
                alpha = friction/(env.k*env.m*env.R)
            else:
                # Constrained non-rotating sliding reference.
                friction = -env.mu*normal
            a = drive + friction/env.m
            remaining = length-distance
            vend2 = v*v+2*a*remaining
            dt = env.physics_dt
            if vend2 >= 0 and v+math.sqrt(vend2) > 1e-14:
                dt = min(dt, 2*remaining/(v+math.sqrt(vend2)))
            if env.use_rotation:
                slip = v+env.R*omega
                slipdot = a+env.R*alpha
                # Split integration at rolling capture rather than crossing slip sign.
                if abs(slip) >= 1e-8 and slip*slipdot < 0:
                    dt = min(dt, -slip/slipdot)
            if v+a*dt < -1e-10 or (v <= 1e-12 and a <= 0):
                env.last_failure = 'stalled_or_reversed'
                return None, False
            ds = v*dt+.5*a*dt*dt
            if dt < 1e-12 or ds <= 0:
                env.last_failure = 'integration_stalled'
                return None, False
            distance = min(length, distance+ds)
            v = max(0.0, v+a*dt)
            omega += alpha*dt
            elapsed += dt
            fraction = distance/length
            accs.append(a); normals.append(normal); lifts.append(lift); frictions.append(friction)
            ts.append(elapsed); vs.append(v); ws.append(omega)
            xs.append(float(env.x[i]+fraction*env.dx)); ys.append(float(y[i]-fraction*drop))
    env._last_trace = dict(t=np.array(ts), v=np.array(vs), omega=np.array(ws),
        a=np.array(accs), x=np.array(xs), y=np.array(ys),
        normal=np.array(normals), magnus=np.array(lifts), friction=np.array(frictions))
    return elapsed, True
