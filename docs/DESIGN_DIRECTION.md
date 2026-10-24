# Design Direction — Dashboard UI (Track 2)

Source of the design language: **alterx.co.in**, studied on 2026-10-24. All 21 reachable pages were opened:
- **Home**
- **Products:** Alter Engine, AxInventory
- **Solutions:** index, The gap, Where it fits, How it works, Reliability
- **Build:** Developers, Docs
- **Company:** About, Careers, Contact, Request access, FAQ, Resources, Work, Security
- **Legal:** Privacy, Terms, Cookies, Acceptable Use, DPA

Values below were measured from computed styles in the live site unless marked *proposed*.

---

## 1. What the site's language is

ALTERX reads as **calm, precise, engineered**: near-black green space, one luminous mint accent, large quiet type, hairline structure, and motion that reveals rather than decorates. It sells reliability ("Built so work cannot quietly fail"), so the UI shows systems working: pipelines, live state, sync badges, code panels.

Recurring patterns across pages:
- **Eyebrow, headline, subline.** A small uppercase mint label (`ALTER ENGINE`, `DEVELOPERS`, `COMPANY · FAQ`), then a large Manrope headline, then a muted one-line sub.
- **Hero.** A headline word is highlighted in mint (`run.`) and cycles letter by letter between words ("automate" ↔ "run"). A soft radial green glow sits top-left, and a WebGL (three.js) organic mint blob morphs below the fold.
- **Hairline lists.** Rows separated by 1px lines with label left and value right ("Counter Inventory / Live State", "Tax · GST-native behaviour"). They read like a calm table.
- **Numbered capability cards.** `01`–`07` in a 2-column grid, each with a title and muted description. The last card's title is in mint for emphasis.
- **Live-state panels.** Inventory rows with units and a mint status tag ("OFFLINE SYNC ACTIVE", "● SYNCED").
- **Pipeline dot stepper.** `UNDERSTAND · PLAN · CONNECT · DO · CHECK · RECOVER`, with the active dot in mint.
- **Stacked 3D card deck.** Code panels (`planning.ts`) fanned in perspective, with a mint "TYPESCRIPT | PYTHON" segmented toggle.
- **Tech logo marquee.** A slow horizontal scroll of muted logos.
- **Pills.** Mint-outlined capsules ("ILLUSTRATIVE WORKFLOW — NOT A CUSTOMER CASE STUDY", docs topic chips).
- **Accordions.** The FAQ has 15 rows with chevrons and hairline separators.
- **Forms.** Dark translucent inputs, 48px tall, 6px radius, mint hairline border, label above.
- **Full-screen menu.** Large Manrope items with chevron accordions, plus a "Talk to us →" button.
- **Next / previous footer links** between solution pages ("← All solutions", "Next: Reliability →").
- **Page-load reveal.** Content fades up out of darkness; screenshots caught mid-reveal show it dimmed.

## 2. Colour tokens

| Token | Value | Use (measured on site) |
|---|---|---|
| `--bg` | `#030806` (rgb 3,8,6) | page background |
| `--bg-deep` | `#020504` | footer and deep sections |
| `--surface` | `#06110B` | cards and panels |
| `--ink` | `#E8F7EE` | body text (most common colour) |
| `--ink-strong` | `#F4FFF8` | headlines, link text |
| `--ink-muted` | `#91A89B` | secondary text |
| `--accent` | `#9FFFC0` | mint: highlighted words, eyebrows, active dots, blob |
| `--accent-soft` | `rgba(159,255,192,0.14)` | tag and pill fills |
| `--accent-ink` | `#D8FFE7` | text on the filled green button |
| `--btn` | `#123D27` | filled "Talk to us" button |
| `--line-accent` | `rgba(91,234,153,0.20)` | button and input hairline borders |
| `--line` | mint at 10–15% alpha | card borders, dividers |

**Proposed** additions for the dashboard. The site has no status colours, so these are tuned to sit inside the green family:
- `--danger #FF8A80`
- `--warn #FFD27A`
- `--info #8FD3FF`
- `--live #9FFFC0`, the accent itself, pulsing for "on a call"

Chart series: mint, then teal `#5BEA99`, sage `#91A89B`, info, warn. All must be checked for contrast on `--surface`.

**Light theme (proposed).** Dark is the brand default; light is opt-in:
- `--bg #F4FFF8`
- `--surface #FFFFFF`
- `--ink #06110B`
- `--accent #138A4B` (a deeper green, so it passes contrast on white)

## 3. Typography

- **Display:** Manrope 500. 60px hero (tracking −1.8px, about −0.03em), 44 / 40 / 34px H2 (tracking about −0.025em). Weight stays at 500, never bold, which gives the calm, expensive feel.
- **Body and UI:** Inter, 14–16px.
- **Eyebrow:** Inter 11px, weight 600, uppercase, tracking 1.1px (0.1em), mint.
- **Mono:** ui-monospace stack, for code, IDs, phone numbers, timers and credit amounts. Use `tabular-nums` for every number that ticks.
- **Indic scripts (dashboard need):** Noto Sans Telugu and Noto Sans Devanagari as fallbacks in the Inter stack, so transcripts in Telugu and Hindi render cleanly at matching x-height.

## 4. Shape, spacing, depth

- **Radius:** 6px for buttons, inputs and chips (most common); 10px for cards and menu items; 4px for small tags; full radius for pills.
- **Depth:** no drop shadows on the site. Depth comes from surface steps, mint hairlines, radial glows and real 3D (the WebGL blob, the perspective card stack).
- **Spacing:** generous, left-aligned and single-column on content pages. Two-column card grids on desktop. Headline line length capped at about 14 words.

## 5. Motion language

Measured transitions on the site:

| Duration and easing | Count | Role |
|---|---|---|
| 150 / 200 / 300 ms `cubic-bezier(0.4,0,0.2,1)` | about 220 | hover, press, colour, small state changes |
| 700 ms `cubic-bezier(0.16,1,0.3,1)` | 19 | content reveals (expo-out) |
| 300 ms `cubic-bezier(0.22,1,0.36,1)` | 14 | panels and menus |
| 750 ms `ease-in-out` | 14 | looping ambient moves |

The site's runtime libraries are **GSAP** and **three.js (WebGL)**, plus one CSS keyframe (`square-loader-move`).

Motion rules for the dashboard:
1. **Reveal, don't bounce.** Entrances fade up 8–16px with a slight blur-in over 700ms expo-out, staggered 40–60ms. No overshoot springs on content.
2. **Micro feedback in 150–200ms.** Hover lifts the hairline to mint; press scales to 0.98.
3. **One hero moment per screen.** Each page gets one signature animation; everything else stays quiet. This is how Linear, Vercel and Stripe keep heavy motion from feeling noisy (my reading of their products, not sourced here).
4. **Motion means state.** Pulses only on live calls; counters roll only when values change; the pipeline dot moves only when the call state moves.
5. **Reduced motion.** Under `prefers-reduced-motion: reduce`, every reveal becomes an instant fade, WebGL becomes a static gradient image, and marquees stop.
6. **Performance budget.** Animate only `transform` and `opacity`. WebGL runs only on screens that need it, at 30fps when idle, and pauses on hidden tabs.

Libraries (proposed):
- **Motion** (framer-motion's successor) for React layout and enter/exit transitions and shared-element transitions.
- **GSAP**, matching the site, for scripted timelines and letter-split text.
- **react-three-fiber** for the WebGL orb.
- All motion tokens live in one `motion.ts`, so durations and easings stay consistent.

## 6. Dashboard concepts — going all out, in the brand's voice

Each concept maps a real product state to motion:

1. **Live Call Orb (signature).**
   - The site's mint WebGL blob becomes the voice of the agent.
   - It reacts to real audio amplitude: it breathes while listening, ripples while the caller speaks, and swells mint while the agent speaks.
   - It appears on the test-call page, the live call drawer and the inbound "answering now" state.
2. **Call pipeline stepper.**
   - The site's `UNDERSTAND · PLAN · CONNECT · DO · CHECK · RECOVER` dots become `RINGING · LISTENING · THINKING · SPEAKING · CAPTURING · DONE`.
   - The active dot glides between steps using real engine events over WebSocket.
3. **Streaming transcript.**
   - Words appear as transcription returns them, in Telugu, Hindi or English, with a soft mint caret.
   - Captured fields (budget, locality) fly out of the transcript into a "Captured" hairline list as they're extracted.
4. **Instant queue lanes.**
   - New leads drop into a "Waiting" lane with a circular countdown to dial time.
   - They then slide to "Dialing", "On call" and "Done" through Motion layout animations.
5. **Campaign constellation.**
   - Each contact is a dot in a grid. Dots light mint as they connect, sage when no-answer, and dim when skipped for do-not-call.
   - Concurrency 1–20 shows as that many active pulses at once.
   - A rolling tabular counter tracks done out of total.
6. **Agent builder "materialise".**
   - A spoken brief shows a live waveform.
   - The drafted script then builds section by section (welcome line, qualify, objections, close), each card revealing with expo-out and the site's numbered `01`–`0n` style.
7. **Version deck.** The last three published versions sit as the site's perspective card stack. Hover fans them out; restoring one flips it to the front.
8. **Hero headline cycling.** Empty states and onboarding reuse the site's letter-cycling mint word, for example "Your AI employee never _sleeps / forgets / misses a lead_".
9. **Command palette (⌘K).** Jump to any employee, lead or call, or start a test call. Keyboard-first, like Linear.
10. **Live-state hairline lists everywhere.** Numbers, the credit balance and the number lease use the site's label-left, value-right rows, with mint status tags ("● LIVE", "SYNCED", "RENEWS 12 NOV").
11. **Leads kanban.** Columns by outcome with physics-free layout animation on drag. The card a lead lands on glows briefly in mint.
12. **Credits runway meter.** A sparkline of daily spend plus a horizontal runway bar that animates when you top up.
13. **Page transitions.** Content cross-fades with a 6px blur over 300ms `(0.22,1,0.36,1)`. Navigation itself never animates.

## 7. Dashboard structure (proposed)

Built from Outpero's screens in our design language:
- **Left rail:** Dashboard, Employees, Hire, Instant, Bulk, Inbound, Conversations, Leads, Performance, Numbers, Billing, Developers, Settings, Help.
- **Top bar:** credit chip (warns when low), live-calls indicator (pulsing mint), notifications, ⌘K.
- **Employee detail tabs:** Script · Voice · Training · Actions · Post-call · Channel settings · Versions.

## 8. Build notes

- **Stack:** React + Vite + TypeScript, Tailwind with all the tokens above as CSS variables, Radix primitives for accessibility, plus Motion, GSAP and react-three-fiber.
- **Accessibility:** text contrast at least 4.5:1 on `--bg` and `--surface`; visible mint focus rings; full keyboard navigation; reduced-motion parity.
- **Brand:** the logo and name are not decided. ALTERX's mark is not reused unless you confirm this product belongs to ALTERX.
