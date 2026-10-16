# Delivery Gate: Wali Paper chat

Verified on 2026-10-15. Mode: after (session choice). Direction: user-supplied Paper React exports, Wali identity, English, shared shell, and explicit future-feature placeholders. ENERGY 2 / RHYTHM 1 / MOTION 1.

## Hard gate

- R-02 PASS: newly authored UI copy uses ordinary punctuation; no em dash is authored in the new components.
- R-03 PASS: browser checks document and composer bounds at 1440, 1024, 768, 390, and 320 CSS px; screenshots confirm reflow and no overlapping sidebar content.
- R-17 PASS: no product metrics or invented financial statistics are added; actual request counts come from the provider.
- R-18 PASS: no testimonials or fictional people are present.
- R-23 PASS: Wali's new header, favicon and reply mark use the user-supplied loading.lottie asset; the role-derived avatar still identifies the actual role. The original archive is preserved and no invented image or profile is added.
- R-24 PASS: the sidebar links only to Chat, Approvals, Mandate, and the active in-tab conversation; browser navigation passed.
- R-25 PASS: the regression script verifies 19 text/background pairings, including the purple navigation, sidebar labels, avatar and gradient endpoints for the large greeting; normal text meets 4.5:1 and large greeting text meets 3:1. See generated results.json for ratios.
- Finance contrast PASS: twelve browser-computed text/boundary pairings pass. New primary-button text measures 8.14:1; secondary and decline boundaries measure 4.16:1 and 4.35:1. Ratios are saved in finance-results.json.
- R-26 PASS: active controls invoke tested navigation, reset, prompt, submit, Copy, settings, role and decision behavior; unavailable controls are disabled and explicitly labeled, as requested.
- R-27 PASS: connection loading/error/retry, empty chat, sending, blocked reply, failed send with restored draft, reset failure and outcome notices were exercised; original queue states remain intact.
- R-28 PASS: no FAQ is introduced; help describes the implemented workflow.
- R-32 PASS: browser checks Space on a prompt, visible focus, Enter/Shift+Enter, drawer focus wrap, profile dropdown Escape/outside/Tab dismissal and restored focus.
- R-33 PASS: functionality is authored in React and CSS source. The regression script mocks network responses only in its test browser; it does not inject application functionality.
- R-34 PASS: light-only matches the approved design; there is no theme toggle.
- R-35 PASS: production build, standalone typecheck, ESLint, format check and browser regression completed; screenshots cover home/conversation on desktop/phone. Physical phone keyboard and native zoom are explicit verification boundaries below.
- R-36 PASS: visible Simulation labels and settings explain the demo; no fabricated security, performance or customer claims are added.
- R-37 PASS: DESIGN.md records the user-approved visual source, colors, type, composition and three dials.
- R-38 PASS: real replies and counts remain API-derived; screenshots use test-only fixtures, and Recent is derived from the actual active user message.

## Purpose gate

- R-01 PASS: suggestion and greeting gradients reproduce the supplied Paper reference; they distinguish starting choices and greeting hierarchy.
- R-04 PASS: compact line icons identify the same controls as the supplied exports; visible or accessible labels identify their actions.
- R-06 PASS: Chat, Approvals, Mandate and the shared shell use the requested Poppins headings paired with Arial body text; type sizes establish greeting, page heading, reply and instruction hierarchy.
- R-07 PASS: no decorative background grid is added.
- R-08 PASS: the arrow is reserved for the reference's send action.
- R-09 PASS: Simulation labels describe the actual runtime purpose and are not invented trust badges.
- R-10 PASS: there is no glassmorphism or translucent content surface.
- R-12 PASS: the composer uses a flat fill; focus outlines communicate focus rather than decorative elevation.
- R-13 PASS: no decorative glow is introduced.
- R-14 PASS: four equal prompt cards represent equal starting choices; the phone layout changes to readable horizontal rows.
- R-19 PASS: Lottie processing/reply behavior remains verified. Sidebar changes use a 240 ms desktop width transition and a Motion transform for phone enter/exit with a fading backdrop. Browser checks confirm real intermediate positions, rapid toggles, and immediate reduced-motion states; existing approval animations remain unchanged.
- R-22 PASS: no generic stock illustration or image is added.

## Liveliness

- Dials PASS: ENERGY 2 / RHYTHM 1 / MOTION 1 is documented and reflected in the approved gradient greeting/cards, repeated task choices, and static chat surfaces.
- Focal point PASS: the greeting leads the home state; the transcript leads the conversation state, as confirmed in screenshots.
- Whitespace PASS: the centered 760 px content lane separates prompts from the dock at 1440 x 900 without imposing fixed desktop spacing on phones.
- Accent PASS: purple marks selected navigation and finance actions; prompt gradients follow the approved Chat reference, and warnings retain semantic colors.
- Identity PASS: finance prompts, actual role context, approval counts and the real mandate workflow identify Wali throughout the shared shell.
- Design Read PASS: audience, language, source frames, layout and typography are recorded in DESIGN.md.

## Craftsmanship and quality locks

- C-1 PASS: DESIGN.md gives a concrete purpose for the source palette, layout, type, radii and response structure.
- C-2 PASS: tested active controls have real behavior; future capabilities are intentionally disabled rather than simulated.
- C-3 PASS: prompts and navigation correspond to Wali's finance workflow; no unrelated template sections are added.
- C-4 PASS: empty/loading/error/blocked states, narrow/short viewports, keyboard flows and scroll preservation were checked in the browser.
- C-5 PASS: product data remains API-backed; test fixture content stays in the test script.
- R-05 PASS: both states follow the requested chat composition rather than a landing-page layout.
- R-11 PASS: prompt, composer, user bubble and controls use the distinct corner sizes from the reference.
- R-15 PASS: Send message, New chat, Copy reply, Settings and help, Confirm and Decline name concrete actions.
- R-16 PASS: the new copy uses plain finance tasks and instructions, without marketing filler.
- R-20 PASS: actual role and approval flows, domain prompts and simulation context retain Wali's identity.
- R-21 PASS: white/pale surfaces follow the explicitly approved light theme.
- R-29 PASS: surface, text, active, gradient and warning roles are documented with exact values.
- R-30 PASS: close reference reproduction is intentional and explicitly requested; generic sample content is replaced with Wali behavior.
- R-31 PASS: major visual choices and their practical purposes are recorded in DESIGN.md.

## Reproduction and limits

Message motion revision PASS (scoped): `test:message-motion` checks 240 ms native message animations, intermediate smooth-scroll positions, interrupted scrolling and preserved reading position, following resumed by a new send, immediate reduced-motion behavior and existing history without entrance replay. Full Chat and entrance regression suites pass. Typecheck, lint, formatting and production build pass. Motion uses opacity/transform, retains semantic list/status elements and existing API-backed content, and adds no placeholder timing or model call. Existing desktop/mobile layout checks remain in the full Chat suite.

Chat entrance revision PASS (scoped): `test:chat-intro` records actual native animation timings for greeting/question, four cards and composer, and checks natural completion, immediate completion on focus, preserved footer opacity, no replay on typing/reset, reduced-motion bypass and visible mobile controls with mocked APIs. Full Chat and MeshGradient card suites pass. Typecheck, lint, format check and production build pass. Motion uses opacity plus a 10 px transform without bounce; no geometry or data/API change is introduced. The sequence is explicitly requested, scoped to Chat and completes within 880 ms. Error/loading content stays visible and no live finance/model action is used.

Prompt brightness adjustment PASS (scoped): the dark veil is reduced from 50% to 38%, revealing more of the supplied pink/purple mesh. A conservative completely white shader composited through this veil and the 0.64 surface opacity over #4A1749 gives 4.52:1 white-text contrast, excluding shadow. This supersedes the previous 5.93:1 bound. The prompt-mesh playback/keyboard/responsive suite passes and the new desktop screenshot was reviewed. No fresh production build is claimed for this CSS-only adjustment.

Prompt MeshGradient revision PASS (scoped): `test:prompt-mesh` checks initial speed 1 followed by automatic pause, actual frame progression during hover, pause on pointer leave/blur, visible keyboard focus, Space filling/focusing the composer, reduced motion and five responsive widths. Desktop/mobile screenshots were reviewed. A full-white shader under the 50% dark veil at 0.64 surface opacity over #4A1749 yields a conservative 5.93:1 white-text contrast, excluding text shadow. Existing blue-card contrast evidence is superseded by this calculation. Full Chat, mobile-composer and background/fallback suites pass; typecheck, lint, formatting and production build pass. Motion matches the explicit intro/hover request, the layer is decorative and cannot intercept input, and CSS fallback preserves usable cards without WebGL. Physical-device GPU performance is not measured.

Paper background revision PASS (scoped): `test:background` verifies actual shader mounting, normal speed, reduced-motion zero speed, WebGL-disabled CSS fallback, prompt/send/reply behavior, mobile bounds, conversation opacity and absence on Mandate. Desktop, mobile and conversation screenshots were reviewed. Chat and mobile-composer regression suites pass; typecheck, lint, format check and production build pass. The mobile test now waits for the viewport layout to settle before measuring its keyboard-size simulation. Home opacity 0.30 and conversation opacity 0.16 are multiplied by a white veil of at least 45%, increasing to 85% in the reading lane. Even a completely black shader would leave the #505762 body text at 4.96:1 and #666B70 large headings at 3.66:1 under the weakest veil. Existing user-authored footer opacity is outside that contrast claim. Ambient motion is explicitly requested; reduced motion stops it. Physical phone GPU performance is not measured. All browser test API responses are mocked.

Mobile browser follow-up PASS (emulated scope): mobile shell is fixed and capped by 100svh plus the measured available height, with safe-area/keyboard viewport metadata. `test:mobile-composer` passes all four sizes, stale measurements, prompt scrolling/focus and a reduced VisualViewport while focused, followed by restoration. Full Chat and profile suites pass. Physical Safari and Android browser UI remain unverified; the screenshots supplied by the user supersede earlier assumptions that the first viewport correction resolved those environments. This follow-up was run in dev; no new production-build result is claimed.

Empty mobile composer correction PASS: `npm run test:mobile-composer` uses Pixel 7 emulation at 393 x 700, 390 x 640, 320 x 568 and 320 x 400. The test injects a stale oversized height, checks composer bounds, scrolls to the final prompt, taps it and verifies focus and visible Send controls. It also verifies updates after viewport shrinkage and no runtime errors. The screenshot was reviewed; Chat and profile regression suites and production build pass. Browser toolbar and keyboard behavior on the user's physical device remain unverified. No real model or finance action is used.

Composer hint visibility correction PASS (scoped check): the row is hidden at 320, 390, 768 and 1023 px, and visible at 1024 and 1440 px, verified in Chrome with mocked APIs. The existing aria-describedby relationship is retained. This check supersedes earlier mobile hint typography evidence; no new full-suite or production-build result is claimed for this visibility-only correction.

Poppins revision PASS: Poppins 500/600 Latin is bundled locally for headings and the Wali wordmark, paired with Arial body text. Browser font checks confirm Poppins is loaded and the expected computed font families are applied. The 390 px screenshot was reviewed; full Chat, finance and profile mock suites pass at their documented responsive sizes. Production build, including TypeScript checks, passes. Colors, API behavior and financial data are unchanged.

Mobile header revision PASS: browser scroll checks on Chat, Approvals and Mandate at 320, 390 and 768 px keep the header at y=0. At widths up to 760 px it explicitly uses sticky positioning with a white background; the main flex panel permits content scrolling within its viewport. Composer helper text uses 10 px / 14 px mobile typography without reducing contrast. The 390 px screenshot was reviewed. Chat and profile regression suites, format check and production build pass. These checks use mocked APIs and do not claim physical-device testing.

Profile dropdown revision PASS: `npm run test:profile` checks actual intermediate animation opacity, open focus, Tab order/departure, role switching, Escape, outside click, close button, mobile sidebar shortcut, five viewport widths, 320 x 400 scrolling constraints, reduced motion and no browser errors. Five browser-computed text/control contrast pairs pass. Desktop and phone screenshots were visually reviewed. The full Chat and finance regression suites, typecheck, lint, format check and production build passed after this revision. The dropdown replaces the previous modal; historical nested-modal behavior is superseded by closing the mobile drawer before opening the profile dropdown. The shadow distinguishes the overlay; the short transform/opacity transition connects it to its avatar trigger.

Run `npm ci`, `npm run build`, then `npm run start -- --port 3005` in one terminal and `npm run test:ui` in another. The test uses installed Google Chrome and the locked Playwright dev dependency. Screenshots and detailed JSON results are generated in ignored `test-results/`.

API calls are intercepted; no live model or financial action is performed. Earlier Paper screenshots used Arial as the Google Sans fallback; the current user-requested typography uses bundled Poppins headings with Arial body text. The 320 CSS px and 400 px-tall checks verify reflow and a reduced visible area; they do not claim physical-device keyboard or native 200% browser zoom testing. No new Python test results are claimed because the Python code and API contract are unchanged.

Lottie revision: `npm run test:loading` checks both normal and reduced-motion browser contexts, actual SVG frame changes, processing loops, one-cycle completed replies, header logo, favicon assets, live preference changes, removal of the pending animation after success/failure, preserved drafts on errors, and no browser runtime errors. It defaults to the running frontend on port 3000; set `WALI_TEST_ORIGIN` to use another port. The script intercepts all Wali API requests. Its results and screenshots are saved in `test-results/`. The full UI suite also checks all five responsive widths with the new header logo.

Sidebar revision: `npm run test:sidebar` checks animated desktop open/close, rapid toggles, the 64 px compact rail, four equal 44 x 44 px action targets centered at x=32, actual purple active colors, absence of zero badges, mobile enter/exit, inert/focus boundaries, reduced-motion switches and browser errors. Screenshots include `sidebar-collapsed.png`, `sidebar-expanded.png` and `sidebar-mobile-open.png`; measurements are saved in `sidebar-results.json`. All API responses are mocked.

Finance revision: `npm run test:finance` checks populated/empty Approvals, payment and mandate details, long account wrapping, risk visibility, disabled processing controls, successful Confirm/Decline, failed decision preservation, queue and connection retries, owner-only drafting, keyboard draft activation, draft failure/processing/success, pending navigation and browser errors. Both pages are checked at 1440, 1024, 768, 390 and 320 CSS px. Twelve actual browser-computed contrast pairs meet 4.5:1 for text and 3:1 for interactive boundaries. Screenshots cover desktop, phone, empty queue and non-owner states; all requests are intercepted and no live model or financial action occurs. No backend, API contract or workspace-provider behavior is changed.
# Landing page delivery, 2026-10-16

Status: PASS for the automated Chrome and visual-review scope described below. Native browser zoom and physical phone testing are not claimed.

The approved Stitch screen `d18b6926901840faa21a2a86ca0ccc07` was read through MCP and its screenshot/export inspected. The implementation retains the slim header, centered hero, broad rounded visual and plain footer. Wali's purple/pink mesh replaces the floral panel at the user's request. The four capabilities and three workspace responsibilities come from the existing application. No customer logos, ratings, invented results, authentication controls or unsupported destinations were carried over.

`npm run test:landing` passes against the production build on port 3005. It checks 1440, 1024, 768, 390 and 320 CSS px with no horizontal overflow, 44 px action targets, sticky header, all five Chat CTAs, both home logo links, every desktop/footer anchor, mobile keyboard/menu selection, Escape/focus return, outside dismissal and the skip link. It checks actual shader frame progression, automatic pause after the intro, hover/focus playback, reduced-motion pause and desktop/mobile pixel budgets. Six browser-computed contrast pairs pass: heading 16.48:1, secondary copy 6.81:1, primary button 8.14:1, secondary boundary 4.16:1, preview copy 16.48:1 and simulation copy 6.22:1. Text uses solid surfaces, so animated colors cannot lower its contrast. Local Poppins loading and keyboard focus outlines are checked.

The landing makes zero `/api/wali/*` calls before entering the workspace. Direct `/chat`, `/approvals` and `/mandate` navigation works with mocked APIs. WebGL-disabled rendering retains the CSS gradient; without JavaScript the server-rendered copy, native menu and Chat links work. No browser runtime errors were recorded. The separate full `test:ui` and `test:finance` suites pass with API interception, covering successful/failed/blocked Chat replies, restored drafts, reset, roles, approval actions and mandate drafting without live financial or model requests. Typecheck, lint, format check and the final production build pass.

Evidence: `test-results/landing-results.json`, `landing-1440.png`, `landing-1024.png`, `landing-768.png`, `landing-390.png`, `landing-320.png` and `landing-no-webgl.png`, plus existing Chat and finance result files. Production desktop and phone screenshots were visually reviewed; these files are generated locally and intentionally ignored by Git.

Core Delivery Gate: Hard Gate checks pass within this scope: real navigation, no fabricated claims or assets, readable text, responsive bounds, keyboard access, working controls, source edits through patches and an executed production build. Purpose Gate: the mesh carries the existing brand palette, icons identify the four finance functions, the simulation label identifies sample content, one preview shadow separates it from the background, and restrained entrance motion introduces the hero. Liveliness: ENERGY 2 / RHYTHM 2 / MOTION 1 is documented in `DESIGN.md`; centered hero, plain capabilities, asymmetric workflow and simulation panel establish varied hierarchy. Craftsmanship: each section explains existing product behavior; there are no decorative disabled forms or fake proof points. The landing has no remote data state requiring a loader; its shader has a visible fallback. Audit after is recorded in `../anti-slop/audit-017-2026-10-16.md`.

The 320 CSS px check demonstrates narrow-width reflow; it is not a native 200% browser-zoom measurement. Physical Safari/Android browser chrome, GPU performance and native zoom remain unverified. No deployment or new Python test results are claimed.

## Workflow conversation demo, 2026-10-16

Status: PASS for the scoped automated Chrome and visual-review checks. `test:workflow-demo` verifies that playback starts only when the panel is in view, reveals partial reply text, completes four scripted messages after 14 seconds of active playback, and stops without looping. Keyboard Pause/Resume and Replay work. Leaving the viewport and simulated document visibility changes pause the clock; resuming preserves progress. Panel height remains unchanged during playback and completion. The logo uses the existing Lottie player only during active processing intervals. All content is local; the browser recorded zero Wali API calls and no runtime errors.

The complete transcript is visible with reduced motion and without JavaScript. Accessible text is supplied once, outside the decorative animated list, without a per-word live region. Controls have visible keyboard outlines and 44 px targets. Text and panel bounds pass at 1440, 1024, 768, 390 and 320 CSS px. Five additional computed contrast pairs pass: user bubble 12.60:1, assistant bubble 16.48:1, speaker/disclosure 6.45:1 and controls 10.15:1. Screenshots `workflow-demo-playing.png` and `workflow-demo-{width}.png`, plus `workflow-demo-results.json`, are saved locally in ignored `test-results/`; desktop and 390/320 px views were reviewed.

Landing regression, typecheck, lint, format check and production build pass after the addition. No new full Chat/finance or Python-suite result is claimed for this isolated landing component. Existing workspace behavior and API contracts are unchanged. Physical phones, native browser zoom, assistive-technology speech output and actual background-tab throttling were not measured; document visibility was simulated through the browser API.

Core Delivery Gate passes within this scope: no invented financial results, working labeled controls, reserved responsive layout, keyboard access, contrast and executed build. Motion demonstrates the actual question/processing/reply order and stops after one pass; offscreen and reduced-motion states prevent continuous decorative playback. The four scripted lines are explicitly illustrative, reuse existing finance responsibilities, and do not imply any live action. The existing ENERGY 2 / RHYTHM 2 / MOTION 1 direction is retained. Audit after: `../anti-slop/audit-018-2026-10-16.md`.

## Lucide landing icons, 2026-10-16

Status: PASS for the scoped icon revision. Lucide React 1.58.0 is pinned in the manifest and lockfile. Capability icons are 24 px; workflow, simulation and menu icons are 20 px; demo control icons are 16 px. Browser checks verify 1.75 strokes and `aria-hidden` on decorative SVGs. The workflow retains its semantic ordered list, controls retain readable labels and keyboard behavior, and the logo and entry CTAs retain their existing appearance. All changes are scoped to the landing.

`test:landing` and `test:workflow-demo` pass, including all five responsive widths, no overflow/clipped text, CTA/anchor navigation, mobile menu focus/Escape, Pause/Resume/Replay, reduced motion, no-JavaScript content and zero Wali API calls before entering the workspace. Both existing contrast checks continue to pass. Typecheck, lint, format check, production build and `git diff --check` pass. Updated `landing-{width}.png`, `workflow-demo-{width}.png` and playback screenshots are generated in ignored `test-results/`; desktop and 320 px screenshots were visually reviewed.

Core Delivery Gate: icon use is explicitly authorized, each glyph identifies an actual capability or control, text is retained, no decorative animation is added, and the existing visual dials remain unchanged. Hard, Purpose, Liveliness and Craftsmanship checks pass in this narrow scope. Audit after is recorded in `../anti-slop/audit-019-2026-10-16.md`. No physical-device, native zoom, new workspace regression or Python test result is claimed.

Dependency check: `npm audit` reports five high-severity entries in the existing ESLint tooling chain (`eslint-config-next`, its plugin, fast-glob, micromatch and braces), with no Lucide advisory reported. The lockfile diff only adds Lucide; unrelated toolchain upgrades were not applied. This UI Delivery Gate is not a clean dependency-security audit.
