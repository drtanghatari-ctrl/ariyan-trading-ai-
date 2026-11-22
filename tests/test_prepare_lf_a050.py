import sys
import unittest

sys.path.insert(0, 'research')
from prepare_lf import prepare  # noqa: E402

HEAD = '<DATE>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n'


class PrepareLf(unittest.TestCase):
    def test_sunday_stub_merges_into_monday(self):
        lines = [HEAD, '2022.03.11\t1\t2\t0.5\t1.5\t10\t0\t5\n', '2022.03.13\t1.5\t1.6\t1.4\t1.55\t3\t0\t6\n',
                 '2022.03.14\t1.55\t1.9\t1.2\t1.7\t20\t0\t7\n']
        _, out = prepare(lines)
        self.assertEqual([r[0] for r in out], ['2022.03.11', '2022.03.14'])
        self.assertEqual(out[1], ['2022.03.14', '1.5', '1.9', '1.2', '1.7', '23', '0', '7'])

    def test_weekday_rows_untouched(self):
        lines = [HEAD, '2022.03.14\t1\t2\t0.5\t1.5\t10\t0\t5\n', '2022.03.15\t1.5\t2\t1\t1.6\t11\t0\t5\n']
        _, out = prepare(lines)
        self.assertEqual(len(out), 2)


if __name__ == '__main__':
    unittest.main()
