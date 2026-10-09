"""Analytic regression captures; these are NOT AM3352 simulation results."""

import importlib.util
from pathlib import Path
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location(
    "waveforms",
    Path(__file__).resolve().parents[2] / "scripts/analyze-ddr-waveforms.py",
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
UI = 1.25e-9


def capture(jitter_ps=0, delay_ps=300, extra_ps=0):
    t = np.arange(0, 160 * UI, 2e-12)
    nominal = np.arange(1, 160) * UI
    jitter = jitter_ps * 1e-12 * np.sin(2 * np.pi * np.arange(159) / 16)
    added = extra_ps * 1e-12 * np.cos(2 * np.pi * np.arange(159) / 8)

    def voltage(edges):
        out = np.ones_like(t) * 0.75
        for i, edge in enumerate(edges):
            change = -1.5 if i % 2 == 0 else 1.5
            out += change * np.clip((t - edge) / 40e-12 + 0.5, 0, 1)
        return out

    tx = voltage(nominal + jitter)
    rx = voltage(nominal + jitter + delay_ps * 1e-12 + added)
    table = np.zeros(
        len(t),
        dtype=[
            (n, float) for n in ["time_s", "dqs_p_v", "dqs_n_v", "tx_p_v", "tx_n_v"]
        ],
    )
    table["time_s"] = t
    table["dqs_p_v"], table["dqs_n_v"] = 0.75 + rx / 2, 0.75 - rx / 2
    table["tx_p_v"], table["tx_n_v"] = 0.75 + tx / 2, 0.75 - tx / 2
    return table, jitter, added


class Waveforms(unittest.TestCase):
    def test_jitter_not_aligned_away(self):
        table, jitter, _ = capture(jitter_ps=30)
        result, _ = m.analyze(table, 800, 3)
        expected = np.std(jitter) * 1e12
        self.assertAlmostEqual(result["receiverTie"]["rmsPs"], expected, places=5)
        self.assertAlmostEqual(
            result["channelAddedEdgeVariation"]["rmsPs"], 0, places=5
        )
        self.assertAlmostEqual(result["meanPropagationDelayPs"], 300, places=5)
        self.assertFalse(result["signoff"])

    def test_channel_variation_separate_from_source_jitter(self):
        table, _, added = capture(jitter_ps=30, extra_ps=12)
        result, _ = m.analyze(table, 800, 3)
        self.assertAlmostEqual(
            result["channelAddedEdgeVariation"]["rmsPs"], np.std(added) * 1e12, places=5
        )

    def test_ideal_has_no_invented_jitter(self):
        result, _ = m.analyze(capture()[0], 800, 3)
        self.assertLess(result["receiverTie"]["rmsPs"], 1e-6)

    def test_gap_and_wrong_rate_rejected(self):
        table = capture()[0]
        with self.assertRaises(ValueError):
            m.analyze(table[::10], 800, 3)
        with self.assertRaises(ValueError):
            m.analyze(table, 400, 3)

    def test_extra_crossing_not_hidden(self):
        table = capture()[0]
        i = np.flatnonzero(
            (table["time_s"] > 10.5 * UI) & (table["time_s"] < 10.6 * UI)
        )
        table["dqs_p_v"][i], table["dqs_n_v"][i] = (
            table["dqs_n_v"][i],
            table["dqs_p_v"][i].copy(),
        )
        with self.assertRaises(ValueError):
            m.analyze(table, 800, 3)

    def test_dq_requires_thresholds_and_direction_timing(self):
        table = capture()[0]
        extended = np.zeros(len(table), dtype=table.dtype.descr + [("dq0_v", float)])
        for n in table.dtype.names:
            extended[n] = table[n]
        extended["dq0_v"] = 0.75
        with self.assertRaises(ValueError):
            m.analyze(extended, 800, 3)
        result, _ = m.analyze(extended, 800, 3, vil=0.6, vih=0.9, sample_delay_ps=0)
        self.assertEqual(
            result["dq"][0]["indeterminateSamples"], result["dq"][0]["samplingEdges"]
        )
        self.assertLess(result["dq"][0]["minimumThresholdHeadroomV"], 0)

    def test_dq_margins_use_actual_strobe_edges(self):
        table = capture()[0]
        extended = np.zeros(len(table), dtype=table.dtype.descr + [("dq0_v", float)])
        for n in table.dtype.names:
            extended[n] = table[n]
        t = extended["time_s"]
        data = np.zeros(len(t))
        # Alternating data changes halfway between the delayed DQS samples.
        for i, edge in enumerate(np.arange(160) * UI + 300e-12 + UI / 2):
            data += (1.5 if i % 2 == 0 else -1.5) * np.clip(
                (t - edge) / 40e-12 + 0.5, 0, 1
            )
        extended["dq0_v"] = data
        result, _ = m.analyze(extended, 800, 3, vil=0.6, vih=0.9, sample_delay_ps=0)
        dq = result["dq"][0]
        self.assertEqual(dq["indeterminateSamples"], 0)
        self.assertAlmostEqual(dq["minimumTimeValidBeforeSamplePs"], 621, places=4)
        self.assertAlmostEqual(dq["minimumTimeValidAfterSamplePs"], 621, places=4)


if __name__ == "__main__":
    unittest.main()
