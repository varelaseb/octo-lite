# Herdr comms lock reclamation

Be extremely concise. Sacrifice grammar for the sake of concision.
No em-dashes or en-dashes. Ever.

## Law

Message locks live at `$XDG_STATE_HOME/octo-lite/locks/<id>.lock` (default
`~/.local/state/octo-lite/locks/`). They are PERMANENT while the system runs:
no helper (herdr-say, herdr-drain, herdr-ack, operator-sweep) ever unlinks a
lock. flock(2) only. Reclamation happens ONLY through this runbook, wholesale,
by a human operator.

Transport reminder: message transport is a bounded duplicate-prone transport
with no delivery guarantee under a per-epoch retry cap
(`OCTO_TRANSPORT_ATTEMPT_CAP`); a message may arrive zero times, once, or up
to the cap per epoch. Deleting a lock file that a live helper holds breaks
mutual exclusion (a fresh open creates a NEW inode; two holders result), which
is why per-lock deletion is forbidden.

## Verify quiescence, then reclaim wholesale

1. Stop the sweep timer so no P1 repair runs mid-reclamation:

   ```sh
   scripts/operator-timer remove --name <operator-name> --control-dir <control-dir>
   ```

2. Verify no helper process is live:

   ```sh
   pgrep -af 'herdr-say|herdr-drain|herdr-ack|operator-sweep' || echo quiescent
   ```

   Any hit: wait or stop it. Do not proceed while a helper runs.

3. Verify no lock is held (every lock acquirable non-blocking):

   ```sh
   locks="${XDG_STATE_HOME:-$HOME/.local/state}/octo-lite/locks"
   for f in "$locks"/*.lock; do
     [ -e "$f" ] || continue
     flock -n "$f" true || echo "HELD: $f"
   done
   ```

   Any `HELD:` line: not quiescent. Stop.

4. Reclaim wholesale (never per-file):

   ```sh
   rm -rf "${XDG_STATE_HOME:-$HOME/.local/state}/octo-lite/locks/"
   ```

5. Reinstall the sweep timer. Helpers recreate `locks/` race-safely on first
   use.
