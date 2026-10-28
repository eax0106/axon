# Runbooks

Written in B14 for whoever runs Axon in production. Each one is short and says what to run. Settings named here are listed in `.env.example`; scripts named here are in `scripts/`; both are checked by a test (`test_runbooks.py`), so a rename that breaks a runbook fails CI.

| Runbook | Use it when |
|---|---|
| [deploy.md](deploy.md) | First deploy, an upgrade, a rollback, making a staff admin |
| [backup-restore.md](backup-restore.md) | Setting up backups, restoring after a loss, the restore drill |
| [incidents.md](incidents.md) | Something is wrong: calls not starting, a vendor down, a locked-out user, a stuck number purchase |
| [capacity.md](capacity.md) | Setting how many calls run at once; sizing the database pool; running the load test |
| [secrets.md](secrets.md) | Rotating a secret; what a leaked one exposes |

Staff routes live under `/admin` (the console UI is Track 2; until then call them with a staff session token). Open items that need a person rather than a command are in `docs/WIRING_CHECKLIST.md`.
