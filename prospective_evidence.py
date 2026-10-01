"""Bind an observation ledger to frozen future folds without certifying costs."""
from spec_evidence import summarize, verify

VERSION = "m6-prospective-spec-evidence-v1"


def assess(record, ledger_directory=None, expected_sha256=None, *, now):
    """Recompute gaps for registered assets/dates, never reuse a ledger's window."""
    if (ledger_directory is None) != (expected_sha256 is None):
        raise ValueError("Evidence ledger directory and reviewed SHA-256 are required together")
    snapshots = {}
    ledger = None
    if ledger_directory is not None:
        ledger, snapshots = verify(ledger_directory, expected_sha256, include_snapshots=True)
        # Reuse all verified snapshot records, even assets not requested by the
        # original ledger. Avoid a second unpinned filesystem read.
        for snapshot in snapshots.values():
            for observation in snapshot["contracts"]:
                if observation["observed_at"] > now.timestamp():
                    raise ValueError("Evidence observation postdates execution clock")
    folds = [dict(fold=index, **summarize(snapshots, record["protocol"]["assets"],
                                        fold["test_start"], fold["test_end"]))
             for index, fold in enumerate(record["folds"])]
    return dict(version=VERSION,
                status="VERIFIED_OBSERVATIONS_ONLY" if ledger is not None else "NO_LEDGER_PROVIDED",
                ledger_sha256=expected_sha256,
                ledger_required_window=None if ledger is None else ledger["required_window"],
                snapshot_count=0 if ledger is None else len(ledger["snapshots"]),
                folds=folds, historical_specs_verified=False, exact_costs_verified=False,
                acceptance_status="NOT_VALIDATED", used_for_execution_parameters=False)
