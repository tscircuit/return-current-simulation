import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib/palace/python"))
from crosstalk_extract import EPS0, C0, electrostatic


class ElectrostaticsTests(unittest.TestCase):
    def test_nonuniform_parallel_plate_matches_independent_analytic_result(self):
        x = np.array([0, .1, .3, .8, 1]) * 1e-3
        y = np.array([0, .03, .1, .2]) * 1e-3
        labels = np.full((len(y), len(x)), -1)
        labels[0], labels[-1] = 0, 1
        cap, _, phi = electrostatic(x, y, labels, 1, 4)
        expected = 4 * EPS0 * (x[-1]-x[0]) / (y[-1]-y[0])
        self.assertAlmostEqual(cap[0, 0] / expected, 1, places=13)
        np.testing.assert_allclose(phi.reshape(len(y), len(x))[:, 2], y/y[-1], atol=1e-14)

    def test_external_inductance_vacuum_duality_and_power_preservation(self):
        cap = np.array([[20, -3], [-3, 20]]) * 1e-12
        inductance = np.linalg.inv(cap) / C0**2
        np.testing.assert_allclose(inductance @ cap, np.eye(2) / C0**2, atol=1e-32)
        transform = np.array([[1, 1], [1, -1]]) / np.sqrt(2)
        v, i = np.array([.4, 1.2]), np.array([.01, -.02])
        self.assertAlmostEqual(v @ i, (transform.T @ v) @ (transform.T @ i), places=15)
        self.assertTrue(np.all(np.linalg.eigvalsh(inductance) > 0))


if __name__ == "__main__":
    unittest.main()
