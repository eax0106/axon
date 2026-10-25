# Sending leads to an Instant employee

Every Instant employee has a private intake address and a secret. Find them with `GET /employees/{id}/instant` (the path) and `POST /employees/{id}/instant/secret/reveal` (the secret, owner only). Rotate the secret with `POST .../secret/rotate`; the old one stops working at once.

## Website, Zapier, Pabbly, n8n or any server

Post one lead as JSON with the secret in a header:

```bash
curl -X POST "https://<api-host>/lead-intake/<connection-id>" \
  -H "X-Axon-Lead-Secret: <secret>" \
  -H "Content-Type: application/json" \
  -d '{"phone": "98765 43210", "name": "Ravi", "budget": "5 lakh"}'
```

- `phone` (also `phone_number`, `mobile`) must be an Indian mobile number. `name` (also `full_name`) is optional.
- Any other field is kept only if its name matches a pre-call variable the employee's script declares. Everything else is ignored.
- Answers: `202 accepted` (a call is queued), `200 deduplicated` (the same number came in within the employee's duplicate window), `422 rejected` (bad number, on the do-not-call list, employee not live), `401` (wrong secret).
- Zapier, Pabbly and n8n: use their "Webhooks / HTTP request" step with the same URL, header and a JSON body; map your form fields to the names above.

## Meta (Facebook / Instagram) Lead Ads

1. In the Meta app, subscribe the page to `leadgen` and set the callback URL to `https://<api-host>/lead-intake/meta` with the verify token from `META_VERIFY_TOKEN`.
2. Give the employee the lead form and a page access token that can read leads: `PUT /employees/{id}/instant/meta {"form_id": "...", "page_access_token": "..."}`.
3. Each new lead is fetched from Meta and goes through the same rules as a website lead. A form can feed one employee.

## Google Sheets

1. `GET /employees/{id}/instant/sheets/consent-url?redirect_uri=...` and send the owner there; then `POST .../sheets/connect {"code", "redirect_uri"}`.
2. `PUT .../sheets {"sheet_id", "range"}`. The first row names the columns. Rows already in the sheet are not called; each row added afterwards is, within a minute.

## Checking it works

`POST /employees/{id}/instant/test-lead` runs a lead through every rule and the intake log without making a call. `GET .../intake-log` shows what each source delivered and what became of it.
