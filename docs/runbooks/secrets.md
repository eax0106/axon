# Secrets

| Secret | Where it lives | Rotate by | Effect |
|---|---|---|---|
| `AXON_JWT_SECRET` | Environment of `api` | Set a new 32+ character value on every `api`, restart | Every signed-in session ends; people sign in again. Do this at once if it leaks: anyone holding it can forge a session for any user, staff included |
| A user's password | Database (argon2 hash) | `POST /auth/password`; it signs out every older session | |
| Vendor keys (Vobiz, Sarvam, Gemini, Smallest, Cartesia, Razorpay, R2, email, WhatsApp) | Environment | New key at the vendor, set it, restart `api`, `engine`, `worker`, then revoke the old key | `GET /admin/providers` shows `configured` again |
| Razorpay webhook secret, Meta app secret and verify token | Environment | New value at the vendor and here at the same time | Webhooks from the vendor are refused (400 or 401) between the two changes |
| An account's API key | Database (only a hash) | The owner makes a new key and revokes the old (`/developer/keys`) | The old key stops at once. We cannot show a key again |
| An account's webhook signing secret | Database | `POST /developer/webhooks/{endpoint_id}/rotate-secret`; takes effect at once, also for sends waiting to be retried | The receiver must take the new secret |
| An employee's lead-intake secret | Database | `POST /employees/{employee_id}/instant/secret/rotate` | Forms and automations posting leads must use the new one |
| Postgres and Redis passwords | `DATABASE_URL`, `REDIS_URL` | New password on the server, set the URL, restart | |
| A staff member's admin rights | `users.is_platform_admin` | `UPDATE users SET is_platform_admin = false WHERE email = ...` | Their open support sessions stop working at once |

**What a leaked database dump exposes:** account data, call transcripts and recordings' storage keys, and, unencrypted, each account's webhook secrets, lead-intake secrets, Google and Meta tokens and tool keys (F5 in `docs/phases/b14-security-review.md`). Password hashes are argon2 and API keys are hashed. After such a leak, rotate everything in the table above and tell the affected customers to rotate theirs.

Nothing here ever goes in git: `.env`, dumps and keys are ignored, and `test_env_example.py` fails if a `.env` file is tracked.
