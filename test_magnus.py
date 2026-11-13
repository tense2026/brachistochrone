import unittest
import numpy as np
from brachistochrone import BrachistochroneEnv
from magnus_physics import magnus_normal

class MagnusTests(unittest.TestCase):
    def test_sign_and_zero(self):
        e = BrachistochroneEnv(use_magnus=True)
        self.assertGreater(magnus_normal(e, 2, 100), 0)
        self.assertLess(magnus_normal(e, 2, -100), 0)
        self.assertEqual(magnus_normal(e, 0, 100), 0)
        self.assertEqual(magnus_normal(e, 2, 0), 0)
        e.use_magnus = False
        self.assertEqual(magnus_normal(e, 2, 100), 0)

    def test_rolling_energy_and_dt(self):
        times=[]
        for dt in (.01,.005,.0025):
            e=BrachistochroneEnv(use_magnus=True, use_air_drag=False, mu=1, physics_dt=dt)
            t,ok=e.simulate_physics(np.linspace(.5,0,e.N+1))
            self.assertTrue(ok)
            tr=e._last_trace
            np.testing.assert_allclose(tr['v']+e.R*tr['omega'],0,atol=1e-8)
            energy=.5*e.m*tr['v']**2+.5*e.k*e.m*e.R**2*tr['omega']**2+e.m*e.g*tr['y']
            np.testing.assert_allclose(energy, e.m*e.g*e.H,atol=1e-9)
            times.append(t)
        np.testing.assert_allclose(times,times[0],atol=1e-9)

    def test_friction_torque_opposes_slip(self):
        for omega in (-100,100):
            e=BrachistochroneEnv(use_magnus=True, omega0=omega)
            _,ok=e.simulate_physics(np.linspace(.5,0,e.N+1))
            self.assertTrue(ok)
            tr=e._last_trace
            slip=tr['v'][:-1]+e.R*tr['omega'][:-1]
            self.assertTrue(np.all(slip*tr['friction'] <= 1e-9))

    def test_pure_rolling_lift_does_not_directly_accelerate(self):
        times=[]
        for lift in (False,True):
            e=BrachistochroneEnv(dynamic_spin=True,use_magnus=lift,mu=1,use_air_drag=False)
            t,ok=e.simulate_physics(np.linspace(.5,0,e.N+1))
            self.assertTrue(ok)
            times.append(t)
        self.assertAlmostEqual(*times,places=10)

    def test_contact_loss_is_failure_not_flight(self):
        e=BrachistochroneEnv(use_magnus=True,omega0=1000,mu=0,lift_cap=100,lift_slope=100)
        e.rho_air=10000 # artificial stress test, not an experimental air density
        _,ok=e.simulate_physics(np.linspace(.5,0,e.N+1))
        self.assertFalse(ok)
        self.assertEqual(e.last_failure,'contact_lost')
        self.assertIsNone(e._last_trace)

if __name__=='__main__':
    unittest.main()
