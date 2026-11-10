# A027 offline Predictability Gate

The gate returns `NO_TRADE` for new exposure. ATAI has development evidence
from R001–R004 and A024. The evidence has yet to establish a repeatable edge
after costs under independent prospective validation. A027 makes that state
explicit through a Python API and a Termux command.

```sh
PYTHONPATH=app python -m ariyan_trading.predictability_gate
PYTHONPATH=app python -m ariyan_trading.predictability_gate --review work/btc-review
```

Use `assess_new_exposure(review_directory=None)` in Python. The command emits
one JSON decision. Exit status zero means a decision was emitted. Automation
must block new exposure when the decision is `NO_TRADE` or when a recognized
decision is missing, including on command failure. A command-line syntax error
exits nonzero.

| Reason | Meaning |
| --- | --- |
| `MISSING_VALIDATION_EVIDENCE` | The caller supplied no review. |
| `UNVERIFIABLE_REVIEW_EVIDENCE` | The supplied input could not pass A025 copied-artifact inspection. |
| `DEVELOPMENT_REVIEW_ONLY` | A025 checked the copied development artifacts. The result includes the unsigned batch digest and the number of jobs for reference. |

An A026 catalog is an index. For review evidence, supply the original or copied
A024 bundle, including its copied inputs. Use the A025 inspection command to
diagnose a rejected bundle. The gate delegates integrity and resource checks
to A025 and never follows original-data paths recorded in the saved review.
It does not rerun replay or read the original full-year CSV. The batch digest
identifies a saved record and carries no authentication.

A027 has no positive admission branch. A future evidence contract would need
a frozen strategy and instrument scope, prospectively specified evaluation,
adequate uncertainty and sample-size criteria, cost-stress results, and a
verified link from those results to the exact strategy under assessment.
A027 does not choose the numerical requirements or release reserved
performance. This gate is a standalone offline entry point. Research replay
still runs independently. Production integration, authenticated human
authority, STOP/FREEZE and existing-position handling remain separate.
