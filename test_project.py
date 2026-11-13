"""Run: python -m unittest -v test_project.py"""
import tempfile
import unittest
import numpy as np
from brachistochrone import BrachistochroneEnv, cycloid_curve, train_and_get_curve


class ProjectTests(unittest.TestCase):
    def test_endpoints_and_raw_mapping(self):
        env = BrachistochroneEnv()
        a = np.linspace(-1, 1, env.N)
        w = np.exp(a - a.max())
        expected = np.r_[env.H, env.H - np.cumsum(env.H * (1.5*w/w.sum() - .5/env.N))]
        expected[-1] = 0
        y = env._action_to_curve(a)
        np.testing.assert_allclose(y, expected, atol=1e-14)
        self.assertEqual(y[0], env.H)
        self.assertEqual(y[-1], 0)

    def test_zero_action_is_straight(self):
        env = BrachistochroneEnv()
        np.testing.assert_allclose(env._action_to_curve(np.zeros(env.N)), np.linspace(.5, 0, env.N+1), atol=1e-14)

    def test_reward_has_no_roughness_penalty(self):
        env = BrachistochroneEnv()
        _, reward, terminated, truncated, info = env.step(np.zeros(env.N))
        self.assertTrue(info['success'])
        self.assertEqual(reward, -info['total_time'])
        self.assertTrue(terminated)
        self.assertFalse(truncated)

    def test_input_validation(self):
        env = BrachistochroneEnv()
        with self.assertRaises(ValueError):
            env._action_to_curve(np.zeros(2))
        with self.assertRaises(ValueError):
            env._action_to_curve(np.full(env.N, np.nan))

    def test_ideal_cycloid_and_resolution(self):
        errors = []
        for n in (30, 120):
            env = BrachistochroneEnv(R=0, mu=0, k=0, use_rotation=False, use_air_drag=False, n_segments=n)
            y, exact = cycloid_curve(env.x)
            t, ok = env.simulate_physics(y)
            self.assertTrue(ok)
            self.assertAlmostEqual(y[0], .5)
            self.assertAlmostEqual(y[-1], 0)
            errors.append(abs(t-exact))
        self.assertLess(errors[1], errors[0])
        self.assertLess(errors[1], .001)

    def test_classical_cycloid_can_rise_at_end(self):
        env = BrachistochroneEnv(n_segments=120)
        y, _ = cycloid_curve(env.x)
        self.assertLess(y.min(), 0)
        self.assertGreater(y[-1], y[-2])

    def test_seed_archive_and_saved_actions(self):
        outputs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as directory:
                x, y, t = train_and_get_curve(.015, .2, .4, False, episodes=12, pop_size=8, seed=12, output_dir=directory)
                env = BrachistochroneEnv(use_rotation=False)
                action = np.load(directory + '/best_action_no_rotation.npy')
                np.testing.assert_allclose(y, env._action_to_curve(action))
                actual, ok = env.simulate_physics(y)
                self.assertTrue(ok)
                self.assertAlmostEqual(actual, t)
                history = np.genfromtxt(directory + '/history_no_rotation.csv', delimiter=',', names=True)
                self.assertTrue(np.all(np.diff(history['best_time_s']) <= 0))
                initial_t, _ = env.simulate_physics(np.linspace(.5, 0, env.N+1))
                self.assertLess(t, initial_t)
                outputs.append(y)
        np.testing.assert_array_equal(*outputs)


class VisualizationTests(unittest.TestCase):
    def test_render_rgb_array(self):
        env = BrachistochroneEnv(render_mode='rgb_array')
        env.reset(seed=1)
        env.step(np.zeros(env.N))
        frame = env.render()
        self.assertEqual(frame.shape, (500, 900, 3))
        self.assertEqual(frame.dtype, np.uint8)
        self.assertGreater(float(frame.std()), 1)
        env.close()

    def test_particle_motion_uses_same_simulator(self):
        from visualization import position_at
        env = BrachistochroneEnv(use_rotation=False)
        y = np.linspace(.5, 0, env.N + 1)
        t, ok = env.simulate_physics(y)
        self.assertTrue(ok)
        trace = env._last_trace
        np.testing.assert_allclose(position_at(trace, 0), [0, .5])
        np.testing.assert_allclose(position_at(trace, t), [1, 0], atol=1e-12)
        for i in (1, 5, 20):
            np.testing.assert_allclose(position_at(trace, trace['t'][i]),
                                       [env.x[i], y[i]], atol=1e-12)
        self.assertIsNone(position_at(None, 0))

    def test_replay_widgets_and_saved_generations(self):
        from visualization import ReplayViewer
        import matplotlib.pyplot as plt
        with tempfile.TemporaryDirectory() as directory:
            train_and_get_curve(.015, .2, .4, False, episodes=8, pop_size=4, output_dir=directory)
            viewer = ReplayViewer(directory)
            viewer.fig.canvas.draw()
            viewer.animation.event_source.stop()
            viewer.generation.set_val(8)
            self.assertEqual(int(viewer.cursor), 8)
            np.testing.assert_array_equal(viewer.lines[2].get_ydata(), viewer.data['y'][8])
            viewer.speed.set_val(5)
            viewer.toggle_mode()
            viewer.restart_playback()
            viewer.tick(0)
            self.assertEqual(viewer.speed.val, 5)
            plt.close(viewer.fig)

    def test_human_render_path_without_gui(self):
        # Under Agg this checks draw/close logic, not a physical display window.
        env = BrachistochroneEnv(render_mode='human')
        env.reset(seed=1)
        env.step(np.zeros(env.N))
        self.assertIsNone(env.render())
        env.close()


if __name__ == '__main__':
    unittest.main()


class RegressionTests(unittest.TestCase):
    """Guards for defects found during the README-vs-code audit."""

    def test_legacy_failure_reason_is_not_stale(self):
        # The fixed-step model sets last_failure; the closed-form model used to
        # leave whatever string a previous call had written.
        env = BrachistochroneEnv(dynamic_spin=False, use_rotation=False,
                                 use_magnus=False, mu=5.0, R=0.0, track_radius=0.0)
        env.last_failure = 'radius_constraint'
        _, _, _, _, info = env.step(np.zeros(env.N))
        self.assertFalse(info['success'])
        self.assertEqual(info['failure_reason'], 'stalled_or_reversed')

    def test_legacy_failure_reason_cleared_on_success(self):
        env = BrachistochroneEnv(dynamic_spin=False, use_rotation=False,
                                 use_magnus=False, mu=0.0, R=0.0, track_radius=0.0)
        env.last_failure = 'contact_lost'
        _, _, _, _, info = env.step(np.zeros(env.N))
        self.assertTrue(info['success'])
        self.assertEqual(info['failure_reason'], '')

    def test_cycloid_analytic_time_follows_gravity(self):
        # cycloid_curve used to hardcode g=10, silently disagreeing with the
        # simulator whenever gravity differed.
        # Discretization error on a 600-segment grid is ~1e-4 s, so compare
        # relatively: the pre-fix bug produced a ~1% error at g=9.81 and ~150%
        # at g=1.62, both far outside this tolerance.
        for gravity in (9.81, 10.0, 1.62):
            env = BrachistochroneEnv(R=0, mu=0, k=0, use_rotation=False,
                                     use_air_drag=False, dynamic_spin=False,
                                     n_segments=600)
            env.g = gravity
            y, analytic = cycloid_curve(env.x, env.H, env.L, gravity)
            simulated, ok = env.simulate_physics(y)
            self.assertTrue(ok)
            self.assertLess(abs(simulated - analytic) / analytic, 1e-3)

    def test_radius_only_case_is_dynamically_inert(self):
        # Documents WHY 01_radius reproduces 00_ideal exactly: with mu=0 and no
        # drag the normal force never enters the tangential equation.
        shared = dict(k=2 / 3, dynamic_spin=True, mass=.0027, height=5.,
                      length=10., physics_dt=.01, n_segments=30)
        ideal = BrachistochroneEnv(R=0., track_radius=0., mu=0., use_rotation=False,
                                   use_air_drag=False, use_magnus=False, **shared)
        radius = BrachistochroneEnv(R=.02, track_radius=.02, mu=0., use_rotation=False,
                                    use_air_drag=False, use_magnus=False, **shared)
        y, _ = cycloid_curve(ideal.x, 5., 10., ideal.g)
        t_ideal, ok_a = ideal.simulate_physics(y)
        t_radius, ok_b = radius.simulate_physics(y)
        self.assertTrue(ok_a and ok_b)
        self.assertEqual(t_ideal, t_radius)

    def test_pure_rolling_scales_time_by_sqrt_one_plus_k(self):
        shared = dict(dynamic_spin=True, mass=.0027, height=5., length=10.,
                      physics_dt=.01, n_segments=30, track_radius=0.,
                      use_air_drag=False, use_magnus=False)
        ideal = BrachistochroneEnv(R=0., mu=0., k=0., use_rotation=False, **shared)
        rolling = BrachistochroneEnv(R=.02, mu=100., k=2 / 3, use_rotation=True, **shared)
        y, _ = cycloid_curve(ideal.x, 5., 10., ideal.g)
        t_ideal, ok_a = ideal.simulate_physics(y)
        t_roll, ok_b = rolling.simulate_physics(y)
        self.assertTrue(ok_a and ok_b)
        self.assertAlmostEqual(t_roll / t_ideal, np.sqrt(1 + 2 / 3), places=6)
