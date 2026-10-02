import copy
from pathlib import Path
import tempfile
import unittest

from build_evidence_acquisition_plan import build, PINS
from audit_evidence_acquisition_plan import checks_for


class AcquisitionPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = build(Path(__file__).resolve().parents[2]/'1')

    def test_complete_original_gaps(self):
        self.assertTrue(all(checks_for(self.plan, self.plan).values()))

    def test_duplicate_cannot_replace_gap(self):
        fake = copy.deepcopy(self.plan)
        fake['entries'][1] = copy.deepcopy(fake['entries'][0])
        self.assertFalse(checks_for(fake, self.plan)['every_gap_and_issue_once'])

    def test_future_cannot_become_historical(self):
        fake = copy.deepcopy(self.plan)
        next(e for e in fake['entries'] if e['gap'].startswith('FUTURE_'))['task_ref'] = 'A01'
        self.assertFalse(checks_for(fake, self.plan)['future_waits'])

    def test_cycle_rejected(self):
        fake = copy.deepcopy(self.plan)
        fake['tasks'][0]['dependencies'] = ['A11']
        self.assertFalse(checks_for(fake, self.plan)['dependency_order'])

    def test_false_certification_rejected(self):
        fake = copy.deepcopy(self.plan)
        fake['entries'][0]['certified_coverage_seconds'] = 1
        self.assertFalse(checks_for(fake, self.plan)['no_evidence_upgrade'])

    def test_missing_route_rejected(self):
        fake = copy.deepcopy(self.plan)
        fake['tasks'][0]['acquisition_routes'] = []
        self.assertFalse(checks_for(fake, self.plan)['executable_requirements'])

    def test_input_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/next(iter(PINS))
            p.parent.mkdir(parents=True)
            p.write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                build(tmp)


if __name__ == '__main__':
    unittest.main()
