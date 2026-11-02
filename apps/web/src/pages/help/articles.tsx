import type { ReactNode } from "react";

import { A, Code, LeadUrl, Steps, origin } from "./parts";

export type Article = { slug: string; group: string; title: string; summary: string; keywords: string; body: () => ReactNode };

const P = ({ children }: { children: ReactNode }) => <p className="my-3">{children}</p>;
const H = ({ children }: { children: ReactNode }) => <h2 className="display mt-8 text-xl">{children}</h2>;
const C = ({ children }: { children: ReactNode }) => <code className="num rounded-tag bg-accent-soft px-1 text-ink-strong">{children}</code>;

const leadJson = `{"phone": "+919876543210", "name": "Ravi Kumar", "project": "Kokapet 3 BHK"}`;

/** Every help article, in our own words. Guides read the reader's real URLs where they can. */
export const ARTICLES: Article[] = [
  {
    slug: "getting-started", group: "Start here", title: "Your first employee on the phone",
    summary: "Hire, check the script, test it, get a number, go live.", keywords: "start setup onboarding first",
    body: () => (
      <>
        <P>An Axon employee is an AI that talks on the phone for you, in Telugu, English or Hindi. There are three kinds: <strong>Instant</strong> calls each new lead within seconds, <strong>Bulk</strong> works through a list, and <strong>Inbound</strong> answers your number.</P>
        <Steps>
          <li><A to="/employees/new">Hire</A>: describe your business and what the call is for. Axon writes the first script.</li>
          <li>Read the script on the employee's Script tab and change anything. Edits wait as a draft until you press <em>Apply to live calls</em>; the last three versions can be restored.</li>
          <li>Try it on the <em>Try it</em> tab: chat with it, talk to it in the browser, or have it ring your own phone (verify the phone on <A to="/account">Account</A> first). Test calls to your phone are free.</li>
          <li>Get a number on <A to="/numbers">Numbers</A>. The first purchase asks for KYC (PAN, then Aadhaar through DigiLocker).</li>
          <li>Attach the number to the employee and switch it on. It is live once it has a number, is switched on and has an applied script.</li>
        </Steps>
      </>
    ),
  },
  {
    slug: "credits", group: "Start here", title: "Credits and what a call costs",
    summary: "1 credit = ₹1, billed per second from pickup.", keywords: "billing price cost top up gst invoice credits wallet",
    body: () => (
      <>
        <P>Axon is prepaid. One credit is one rupee, credits never expire, and a new account starts with 50 free.</P>
        <P>A call is billed per second from the moment the other person picks up. Ringing, busy and no-answer cost nothing. The rate depends on the voice tier (Value, Standard, Premium). A phone number costs ₹649 a month, taken from credits on renewal.</P>
        <P>Top up on <A to="/billing">Billing</A> by card or UPI. You can set an hourly spend cap, and you get an email (at most once a day) when the balance runs low. Statements, transactions and GST invoices are on the same page.</P>
      </>
    ),
  },
  {
    slug: "instant", group: "Calling", title: "Instant: call every new lead in seconds",
    summary: "Lead sources, the calling window and retries.", keywords: "instant speed to lead retry window delay",
    body: () => (
      <>
        <P>An Instant employee calls a lead as soon as it arrives from your website, a form tool, Meta Lead Ads or a Google Sheet. Each lead's fields (name, project, budget) become details the employee can use on the call.</P>
        <P>On the employee's Instant tab you set a short dial delay, the hours it may call (never before 6 AM or after 10 PM), what happens to a lead outside those hours, and up to 9 retries. The queue shows who is waiting; the intake log shows every lead that came in and why any was refused.</P>
        <P>Sources: <A to="/help/website-post">your website</A>, <A to="/help/meta-lead-ads">Meta Lead Ads</A>, <A to="/help/google-sheets">Google Sheets</A>, <A to="/help/zapier">Zapier</A>, <A to="/help/make">Make</A>, <A to="/help/n8n">n8n</A>, <A to="/help/pabbly">Pabbly Connect</A>.</P>
      </>
    ),
  },
  {
    slug: "bulk", group: "Calling", title: "Bulk campaigns",
    summary: "Upload a list, set hours and retries, watch it run.", keywords: "campaign list csv bulk outbound concurrency",
    body: () => (
      <>
        <P>Start a campaign on <A to="/campaigns">Campaigns</A>: upload a CSV, paste numbers, or reuse a saved list, then match each column to a detail the script uses. Nothing is guessed: unmatched columns are left out.</P>
        <P>Choose the days and hours (within 9 AM to 9 PM), holidays to skip, how many calls at once (1 to 20), and retries. You confirm that the people on the list agreed to be called. Anyone on your do-not-call list is skipped.</P>
        <P>While it runs you can pause, resume, call one person now, retry the ones not reached, or cancel. Export the results as CSV when it is done.</P>
      </>
    ),
  },
  {
    slug: "inbound", group: "Calling", title: "Answering your number",
    summary: "Hours, greetings, messages, transfers.", keywords: "inbound incoming answer hours greeting transfer missed",
    body: () => (
      <>
        <P>An Inbound employee answers the number attached to it, all day or within your opening hours. Outside hours it can play a closed message or take a message. Set this on the employee's <em>Incoming calls</em> tab.</P>
        <P>It greets new callers and returning ones differently, says the call may be recorded first, and can hand the call to a person on a transfer number when your condition is met. Messages, callbacks and missed callers (with the reason) are in the <A to="/inbox">Inbox</A>.</P>
      </>
    ),
  },
  {
    slug: "do-not-call", group: "Calling", title: "The do-not-call list",
    summary: "Numbers no employee will call.", keywords: "dnc do not call opt out stop consent",
    body: () => (
      <>
        <P>Add numbers one at a time or paste many on <A to="/account">Account</A>. No campaign, Instant lead or callback calls them. When someone on a call asks not to be called again, they are added by themselves and you get a note in the bell. Only the account owner can remove a number.</P>
      </>
    ),
  },
  {
    slug: "website-post", group: "Lead sources", title: "Send leads from your website",
    summary: "One POST per lead, with your secret in a header.", keywords: "website form post webhook curl intake url",
    body: () => (
      <>
        <P>Every Instant employee has its own lead URL. Send one JSON POST per lead. <C>phone</C> is required (an Indian mobile, with or without +91); anything else becomes a detail for the call.</P>
        <LeadUrl />
        <Code>{`curl -X POST '<lead URL>' \\
  -H '<secret header>: <secret>' \\
  -H 'Content-Type: application/json' \\
  -d '${leadJson}'`}</Code>
        <P>The answer says what happened: <C>202</C> accepted and queued, <C>200</C> the same lead arrived recently (nothing done), <C>422</C> refused with the reason. Send it from your server, never from the browser, so the secret stays private.</P>
      </>
    ),
  },
  {
    slug: "meta-lead-ads", group: "Lead sources", title: "Meta Lead Ads (Facebook and Instagram)",
    summary: "Leads from a lead form are called as they arrive.", keywords: "facebook instagram meta lead ads form",
    body: () => (
      <>
        <Steps>
          <li>In Meta Business Suite, open the page that owns the lead form and copy the form's id.</li>
          <li>Create a page access token with permission to read leads for that page.</li>
          <li>On your Instant employee's Instant tab, under Meta Lead Ads, paste the form id and the token and save.</li>
        </Steps>
        <P>New leads from that form are called within seconds and appear in the intake log with the source "meta".</P>
      </>
    ),
  },
  {
    slug: "google-sheets", group: "Lead sources", title: "Google Sheets",
    summary: "New rows in a sheet become leads.", keywords: "google sheets spreadsheet rows",
    body: () => (
      <>
        <Steps>
          <li>Put column names in the first row. One column must hold the phone number.</li>
          <li>On your Instant employee's Instant tab, under Google Sheets, paste the sheet's link and the range (for example <C>A:Z</C>).</li>
          <li>Allow Axon to read the sheet when Google asks. Axon only reads it.</li>
        </Steps>
        <P>Rows already in the sheet when you connect are not called; every row added after that is. Other columns become details for the call.</P>
      </>
    ),
  },
  {
    slug: "zapier", group: "Automation tools", title: "Zapier",
    summary: "Any Zapier trigger can send a lead.", keywords: "zapier zap automation webhooks",
    body: () => (
      <>
        <Steps>
          <li>Create a Zap with the trigger that produces your lead (a form tool, a CRM, an email parser).</li>
          <li>Add the action <em>Webhooks by Zapier → POST</em>.</li>
          <li>URL: your lead URL below. Payload type: <C>json</C>. Data: <C>phone</C> mapped to the lead's phone, plus any other fields (name, project).</li>
          <li>Headers: the secret header below, with your secret as its value.</li>
          <li>Test the step. The lead shows in the employee's intake log; use a test lead first if you don't want a real call.</li>
        </Steps>
        <LeadUrl />
        <P>To go the other way (do something in Zapier after a call), use a <em>Catch Hook</em> trigger and add its address as a <A to="/help/webhooks">webhook</A>.</P>
      </>
    ),
  },
  {
    slug: "make", group: "Automation tools", title: "Make",
    summary: "An HTTP module sends each lead.", keywords: "make integromat scenario http",
    body: () => (
      <>
        <Steps>
          <li>In your scenario, after the module that produces the lead, add <em>HTTP → Make a request</em>.</li>
          <li>Method <C>POST</C>, URL your lead URL below.</li>
          <li>Add a header: name is the secret header below, value is your secret.</li>
          <li>Body type <em>Raw</em>, content type <em>JSON</em>, and a body like <C>{leadJson}</C> with the values mapped from earlier modules.</li>
          <li>Run once and check the intake log.</li>
        </Steps>
        <LeadUrl />
        <P>For call results in Make, start a scenario with <em>Webhooks → Custom webhook</em> and add its address as an Axon <A to="/help/webhooks">webhook</A>.</P>
      </>
    ),
  },
  {
    slug: "n8n", group: "Automation tools", title: "n8n",
    summary: "An HTTP Request node sends each lead.", keywords: "n8n workflow http request node",
    body: () => (
      <>
        <Steps>
          <li>Add an <em>HTTP Request</em> node after the node that produces the lead.</li>
          <li>Method <C>POST</C>, URL your lead URL below.</li>
          <li>Authentication: <em>Generic → Header Auth</em>, with the secret header below as the name and your secret as the value (stored as an n8n credential).</li>
          <li>Send Body: JSON, with <C>phone</C> and any other fields.</li>
        </Steps>
        <LeadUrl />
        <P>To react to calls, start a workflow with a <em>Webhook</em> node (POST) and add its production URL as an Axon <A to="/help/webhooks">webhook</A>. Check the signature in a Code node.</P>
      </>
    ),
  },
  {
    slug: "pabbly", group: "Automation tools", title: "Pabbly Connect",
    summary: "An API request action sends each lead.", keywords: "pabbly connect workflow api",
    body: () => (
      <>
        <Steps>
          <li>In your workflow, add the action <em>API by Pabbly → Execute API Request</em>.</li>
          <li>Action event method <C>POST</C>, endpoint URL your lead URL below, payload type JSON.</li>
          <li>Set a header with the secret header below as the key and your secret as the value.</li>
          <li>Map <C>phone</C> and any other fields into the JSON body, then save and send a test.</li>
        </Steps>
        <LeadUrl />
      </>
    ),
  },
  {
    slug: "api", group: "Developers", title: "The REST API",
    summary: "Read your account, employees, calls, leads and campaigns; post leads.", keywords: "api rest key bearer openapi postman v1",
    body: () => (
      <>
        <P>Make a key on <A to="/developers">Developers</A> (the owner only; the key is shown once). Send it as a bearer token:</P>
        <Code>{`curl '${origin()}/api/v1/calls?limit=20' \\
  -H 'Authorization: Bearer <your API key>'`}</Code>
        <P>The API reads your account, employees, calls (with transcripts), leads and campaigns, and can send a lead to an Instant employee with <C>POST /v1/employees/{"{employee_id}"}/leads</C>. Download the OpenAPI spec or a Postman collection from Developers. Every request made with a key is in the request log there.</P>
      </>
    ),
  },
  {
    slug: "webhooks", group: "Developers", title: "Webhooks and checking the signature",
    summary: "Six events, signed, retried for hours.", keywords: "webhook signature hmac events verify call.completed lead.created",
    body: () => (
      <>
        <P>Add an https address on <A to="/developers">Developers → Webhooks</A> and pick events: <C>call.completed</C>, <C>call.not_connected</C>, <C>call.inbound_answered</C>, <C>call.inbound_missed</C>, <C>lead.created</C>, <C>campaign.status_changed</C>. Each delivery is a JSON POST; answer with any 2xx. Failures are retried for about 9 hours and every attempt is in the delivery log, with a resend.</P>
        <H>Check it came from Axon</H>
        <P>Each request carries <C>X-Axon-Signature: t=&lt;unix time&gt;,v1=&lt;hex&gt;</C>. Compute HMAC-SHA256 of <C>&lt;t&gt;.&lt;raw body&gt;</C> with your signing secret and compare it with <C>v1</C> in constant time. Use the raw body exactly as received, and refuse old timestamps.</P>
        <Code>{`import crypto from "node:crypto";

export function fromAxon(rawBody, header, secret) {
  const { t, v1 } = Object.fromEntries(header.split(",").map((p) => p.split("=")));
  if (Math.abs(Date.now() / 1000 - Number(t)) > 300) return false;
  const want = crypto.createHmac("sha256", secret).update(\`\${t}.\${rawBody}\`).digest("hex");
  return v1.length === want.length && crypto.timingSafeEqual(Buffer.from(v1), Buffer.from(want));
}`}</Code>
        <Code>{`import hmac, hashlib, time

def from_axon(raw_body: bytes, header: str, secret: str) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    if abs(time.time() - int(parts["t"])) > 300:
        return False
    want = hmac.new(secret.encode(), parts["t"].encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, parts["v1"])`}</Code>
        <P>Each employee can also send its own call results to one address (employee → Actions → Send each result to your system), with an optional secret.</P>
      </>
    ),
  },
  {
    slug: "support", group: "Account", title: "Getting help from the Axon team",
    summary: "Chat, feedback and call ratings.", keywords: "support help contact chat team rating",
    body: () => (
      <P>Write to us on <A to="/support">Support</A>; a person answers, usually within a working day, and the reply also appears in your bell. To flag a call that went wrong, rate it on the call's page and say what happened.</P>
    ),
  },
];
