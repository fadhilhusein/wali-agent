# Antislop Delivery Gate: Wali Web V2

Mode: `during` (session override). Design Read: financial chat workspace for small-business operators, English, light, ENERGY 2 / RHYTHM 2 / MOTION 2. Verification date: 2026-10-14.

## Hard gate

- R-02 PASS: source and authored docs scanned; no em dash copy remains.
- R-03 PASS: browser document width matched viewport at 1440, 1024, 768, 375, and 320 CSS px; the 375 x 400 drawer scrolls to its role selector.
- R-17 PASS: no unverified metrics or statistics in the interface.
- R-18 PASS: no testimonials, avatars, or invented people.
- R-23 PASS: identity is the user-approved Wali text wordmark; no new logo or image asset was created.
- R-24 PASS: sidebar links only to the built `/chat`, `/approvals`, and `/mandate` pages; `/` redirects to Chat.
- R-25 PASS: contrast checker measured 5.02:1 or better for normal text pairings and 7.73:1 for white on the primary action blue.
- R-26 PASS: Chat, Approvals, and Mandate links navigate; quick prompts focus the composer; role, Send, New chat, draft, Confirm, and Decline perform API actions. Future features are plain text.
- R-27 PASS: chat connection, approvals, and mandate actions present loading, empty, error, processing, and result feedback as applicable.
- R-28 PASS: there is no FAQ or generic filler section.
- R-32 PASS: Menu opens with focus inside and Escape restores focus to Menu; browser measurement found a visible 2.4 px keyboard focus outline. Space activated a quick prompt, Enter sent, and Shift+Enter inserted a newline.
- R-33 PASS: all UI behavior lives in React source and the fixed Next.js route handler; no external injection script.
- R-34 PASS: light-only is the explicit project choice; there is no broken theme toggle.
- R-35 PASS: TypeScript, ESLint, formatting, production build, and 18 `tests/test_web.py` cases passed; live browser covered navigation, role switch, quick prompt, send, New chat, draft, Confirm, Decline, and mobile drawer. The 320 CSS px reflow check covers the layout budget of a 640 px viewport at 200% zoom.
- R-36 PASS: the simulation is labeled and no security, compliance, or performance claim is made.
- R-37 PASS: the approved blue/white direction and dials are recorded in `DESIGN.md` before delivery.
- R-38 PASS: displayed financial data and results come from FastAPI; suggested prompt text is clearly user-editable input.

## Purpose gate

- R-01 PASS: there are no decorative gradients or glows.
- R-04 PASS: no generic icon set is loaded; simple nav glyphs identify the three real destinations and text labels carry meaning.
- R-06 PASS: Outfit and the small uppercase status labels have stated character and scanning purposes in `DESIGN.md`.
- R-07 PASS: there is no decorative background grid; ledger dividers structure financial details.
- R-08 PASS: Send and the link from a successful draft to Approvals use arrows to signal forward action; no repeated arrow decoration appears on cards.
- R-09 PASS: the simulation label sits next to the role selector and explicitly says it is not login.
- R-10 PASS: no glassmorphism is used.
- R-12 PASS: only the composer has a restrained shadow, to prioritize entry.
- R-13 PASS: no glow is applied across controls or surfaces.
- R-14 PASS: three equal prompt choices deliberately have equal visual weight.
- R-19 PASS: MotionJS enters page content, messages, and queue changes briefly; reduced-motion preference removes movement.
- R-22 PASS: no generic illustration or stock image is used.

## Liveliness

- Dials PASS: ENERGY 2 / RHYTHM 2 / MOTION 2 are explicit in `DESIGN.md`.
- Consistency PASS: calm blue/white visual system, differentiated approval rail, and short state motion match those dials.
- Focal point PASS: Chat centers the question and composer; Approvals centers the request details; Mandate centers the draft action and review path.
- Whitespace PASS: the open chat state is separate from denser decisions and draft instructions.
- Accent PASS: Wali blue marks identity and real actions; amber is reserved for risk.
- Motif PASS: ledger borders, tabular amounts, and compact labels give the three pages one Wali visual system.
- Design Read PASS: audience, language, and workspace purpose were declared before UI generation.

## Craftsmanship and quality locks

- C-1 PASS: major choices have product purposes recorded in `DESIGN.md`.
- C-2 PASS: no dead interactive controls; unsupported features are labeled “Coming soon” as text.
- C-3 PASS: conversation, composer, prompts, approval decisions, and mandate drafting correspond to real product tasks.
- C-4 PASS: error, empty, loading, blocked, and processing states exist; browser reflow and keyboard checks passed.
- C-5 PASS: no fabricated claim, metric, testimonial, or supplier is in frontend source.
- R-05 PASS: the layout is an operational chat plus approval ledger, not a landing-page template.
- R-11 PASS: radius varies between status capsule, buttons, composer, and cards.
- R-15 PASS: action labels are specific: Send, New chat, Draft mandate, Confirm, Decline.
- R-16 PASS: UI copy contains no AI marketing buzzwords.
- R-20 PASS: ledger hierarchy, distinct decision page, and explicit approval workflow retain Wali's character beyond the wordmark.
- R-21 PASS: light-only follows the explicit approved direction.
- R-29 PASS: white/cloud, ink, blue, and amber risk accent have defined semantic roles.
- R-30 PASS: only Gemini's sidebar and centered-chat composition were adapted; Wali retains its own palette, routes, finance copy, and data model.
- R-31 PASS: layout, typography, borders, restrained motion, and component grouping each have a one-line reason in `DESIGN.md`.

## Verification record

- `npm.cmd run typecheck`, `npm.cmd run lint`, `npm.cmd run format:check`, and `npm.cmd run build`: PASS. Build exposes `/`, `/chat`, `/approvals`, and `/mandate`.
- `uv run --isolated --python 3.11 pytest tests/test_web.py`: 18 passed; no `.py` source or test was changed.
- Live FastAPI plus Next.js: role switch cleared transcript, quick prompt focused composer, chat returned a reply, transcript survived route navigation, New chat reset, draft linked to Approvals, Confirm and Decline removed requests and updated counts, and non-owner Mandate displayed the restriction: PASS.
- Proxy contract: unchanged fixed-action route handler; prior proxy checks covered owner-only 403, foreign Origin 403, malformed JSON 400, and API GET `Cache-Control: no-store`.
- Browser console: no warnings or errors with both local servers running; the expected API-offline error was also shown in the UI and Retry recovered.
- API-offline browser check: both conversation and queue show explicit error states and a connection retry.
- Blocked reply rendering follows `blocked` from the API and labels it in text; the existing backend test covers the blocked response contract.
