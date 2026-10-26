"""Regression tests for the maintained dstat fork (Python 3).

The tests load the ``dstat`` script as a module, without running ``main()``.
No root privileges and no real network interfaces are required.
"""

import importlib.machinery
import importlib.util
import re
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DSTAT = ROOT / 'dstat'


def load_dstat():
    loader = importlib.machinery.SourceFileLoader('dstat_under_test', str(DSTAT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


MOD = load_dstat()


class NumFormatTest(unittest.TestCase):
    """dchg()/fchg() must never raise on non-finite values."""

    def test_dchg_inf(self):
        self.assertEqual(MOD.dchg(float('inf'), 5, 1000), ('-', 0))
        self.assertEqual(MOD.dchg(float('-inf'), 5, 1000), ('-', 0))

    def test_dchg_nan(self):
        self.assertEqual(MOD.dchg(float('nan'), 5, 1000), ('-', 0))

    def test_dchg_finite(self):
        self.assertEqual(MOD.dchg(1234, 5, 1000), ('1234', 0))

    def test_fchg_inf(self):
        self.assertEqual(MOD.fchg(float('inf'), 5, 1000), ('-', 0))
        self.assertEqual(MOD.fchg(float('-inf'), 5, 1000), ('-', 0))

    def test_fchg_nan(self):
        self.assertEqual(MOD.fchg(float('nan'), 5, 1000), ('-', 0))

    def test_fchg_zero(self):
        self.assertEqual(MOD.fchg(0, 5, 1000), ('0', 0))


class NetCounterRegressionTest(unittest.TestCase):
    """A vanished interface must yield a negative delta, never +inf.

    This is the crash from https://github.com/helixzz/dstat:
    a veth disappears -> net/total regresses -> the old wraparound
    "correction" added maxint (float("inf") on Python 3) -> dchg() died
    with "OverflowError: cannot convert float infinity to integer".
    """

    def setUp(self):
        self._saved = {}
        for name in ('update', 'elapsed', 'step', 'op'):
            self._saved[name] = getattr(MOD, name, None)
        MOD.update = 0
        MOD.elapsed = 1.0
        MOD.step = 1
        MOD.op = types.SimpleNamespace(delay=1, full=False, netlist=None)

    def tearDown(self):
        for name, value in self._saved.items():
            if value is None:
                if hasattr(MOD, name):
                    delattr(MOD, name)
            else:
                setattr(MOD, name, value)

    @staticmethod
    def _row(name, rx, tx):
        # /proc/net/dev layout: name, rx_bytes, rx_packets, ..., tx_bytes, ...
        return [
            name,
            str(rx), '10', '0', '0', '0', '0', '0', '0',
            str(tx), '10', '0', '0', '0', '0', '0', '0',
        ]

    def _net(self, rows):
        class FakeNet(MOD.dstat_net):
            def __init__(self):
                self.vars = ['total']
                self.discover = ['veth0']
                self.totalfilter = re.compile(r'^(lo|bond\d+|face|.+\.\d+)$')
                self.set1 = {}
                self.set2 = {}
                self.val = {}
                self.rows = rows

            def splitlines(self, replace=':'):
                return self.rows

        return FakeNet()

    def test_vanishing_interface_is_negative_not_inf(self):
        net = self._net([self._row('veth0', 1000, 1000)])
        net.extract()                  # first sample: update == 0
        net.set1.update(net.set2)

        net.rows = []                  # veth0 disappeared
        MOD.update = 1
        net.extract()

        self.assertEqual(net.val['total'], [-1000.0, -1000.0])
        # cprint() renders negative values as '-'; dchg() must not see inf.
        self.assertEqual(MOD.dchg(net.val['total'][0], 5, 1000), ('-1000', 0))
        self.assertEqual(MOD.dchg(net.val['total'][1], 5, 1000), ('-1000', 0))

    def test_growing_interface_stays_positive(self):
        net = self._net([self._row('veth0', 1000, 1000)])
        net.extract()
        net.set1.update(net.set2)

        net.rows = [self._row('veth0', 3000, 5000)]
        MOD.update = 1
        net.extract()

        self.assertEqual(net.val['total'], [2000.0, 4000.0])


class SourceGuardTest(unittest.TestCase):
    """Cheap static guards against reintroducing the known-bad patterns."""

    def test_no_infinite_maxint(self):
        source = DSTAT.read_text(encoding='utf-8')
        self.assertNotIn('maxint = float("inf")', source)

    def test_no_six_dependency(self):
        source = DSTAT.read_text(encoding='utf-8')
        self.assertNotIn('import six', source)


if __name__ == '__main__':
    unittest.main()
