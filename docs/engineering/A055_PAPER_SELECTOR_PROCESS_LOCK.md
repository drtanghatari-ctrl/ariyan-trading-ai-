# A055 serialize paper orders across participating processes

Persistent paper controllers opened with `PaperExecutionController.reopen`
now acquire ATAI's existing filesystem lock for the resolved selector path.
The lock spans selector and state verification, order submission and
checkpoint publication, or signed escalation and selector replacement.
The instance lock still serializes threads within one controller.

Open each controller independently in its process. Use one canonical selector
pathname per paper ledger and keep the adjacent `.init.lock` file in place.
The sidecar's existence does not indicate that a process currently holds
the OS lock. Use a trusted local directory and filesystem.

An in-progress order can finish before an escalation acquires the lock.
A lock timeout propagates before submission or activation. A controller
with the previous selection refuses later orders once another participant
advances the selector. Reopen it with the independently retained current
pin before using it again.

This coordinates participating persistent controllers on the same selector
pathname. Direct entry calls, in-memory controllers, and separate selector
files are outside that lock. A054's restart, pin, and power-loss boundaries
still apply. The subprocess test uses a simulated checkpoint writer and
does not require process-shared Python semaphores.
