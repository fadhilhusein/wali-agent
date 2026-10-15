# Wali: Paper chat direction

## Source and design read

The user supplied the React exports and screenshots for Paper's Chat Beranda and Chat Percakapan frames on 2026-10-15. Those exports define the layout and styling; the generic Nova examples are reference content, not application data. Wali is a finance workspace for small-business operators, with English copy and a light theme. ENERGY 2 / RHYTHM 1 / MOTION 1: welcoming color, repeated functional choices, and no decorative movement.

This direction supersedes the earlier Next.js blue/white design. Root DESIGN.md continues to describe the original Python static demo.

## Visual system

| Role | Value | Purpose |
| --- | --- | --- |
| Main surface | `#FFFFFF` | Keep the transcript open and readable |
| Composer, user bubble | `#F0F4F9` | Group user input |
| Sidebar surface | `#F8F3F9` | Give navigation a light tint from the purple logo |
| Primary text | `#1F1F1F` | Readable finance questions and responses |
| Secondary text | `#444746`, `#505762` | Instructions and unavailable feature labels |
| Large secondary heading | `#666B70` | Defer to the greeting while retaining contrast |
| Brand and active navigation | `#7C2F81`, `#632268` on `#ECDCEF` | Match the supplied logo and identify the current destination |
| Prompt mesh | `#E0EAFF`, `#6B005F`, `#F75092`, `#9F50D3` | Match the user-supplied Paper MeshGradient card reference |
| Warning | `#744018` on `#FFF7EC` | Distinguish blocked output with explicit words |

Use locally bundled Poppins at weights 500 and 600 for headings and the Wali wordmark, paired with Arial for conversation text, finance details and controls. The user requested this font combination after the Paper implementation: Poppins gives the headings a rounded geometric identity while Arial keeps dense financial information compact. Only Latin subsets are loaded with font-display swap; no external font request is needed. Desktop headings are 48 px with a 56 px line height; chat and composer text are 16 px. Smaller labels supplement controls rather than replacing their accessible names.

## Composition and reflow

Prompt cards use the user's Paper MeshGradient reference (scale 1, distortion 0.8, swirl 0.1, frame 24216.3, opacity 0.64). The four real finance prompts, 16 px text and white 40 px icon discs are retained. Following the user's brightness adjustment, the dark veil is reduced from 50% to 38% over a plum base. The conservative full-white shader bound still gives 4.52:1 white-text contrast without relying on shadow. Cards play at speed 1 for 1.8 seconds on mounting, then pause at the current frame. Mouse hover or visible keyboard focus resumes playback without resetting the frame; leaving or blurring pauses it. Touch does not activate persistent hover. Reduced motion keeps them still, and a CSS gradient retains their appearance without WebGL. WebGL capability is checked once per document and shared with the page background; each card uses a 60,000 pixel rendering budget. Mobile retains horizontal prompt rows and independent welcome scrolling.

The user-supplied Paper GrainGradient (shaders-react 0.0.81) now supplies a quiet Chat-only background. Lavender, mauve and pale blue replace the saturated source colors and black backdrop. Home opacity is 0.30; conversations use 0.16, with a white center veil to protect the reading lane. Softness 0.85, intensity 0.25 and noise 0.08 keep the texture subordinate to text. Speed is 0.12 on desktop and 0.07 on mobile; reduced motion sets it to zero. This user-requested ambient background is the explicit exception to the original MOTION 1 direction. The shader is loaded only in the client and capped at 480,000 pixels (240,000 on mobile); an equivalent pale CSS background remains when WebGL2 is unavailable. The layer is decorative and cannot intercept pointer events. Approvals, Mandate and the shared header/sidebar retain their existing surfaces.

- Desktop: 280 px sidebar, 72 px header, 760 px content/composer; white space separates the greeting and suggestions from input. Composer radius is 32 px, suggestions 16 px, and user messages 24 px, following the exported shapes.
- Tablet, 761 to 1100 px: sidebar starts at 64 px and suggestions use two columns. The sidebar toggle can expand or collapse it.
- Phone, up to 760 px: sidebar is an initially hidden drawer, header is 64 px, and the main panel keeps the composer visible. At 480 px and below, suggestions become single-column horizontal rows.
- Chat fills the visible viewport. Only its transcript/welcome area scrolls; the composer is a separate flex row. On mobile the shell is fixed to the viewport and capped by 100svh, its containing viewport and the measured visible height, reserving space for expanded browser toolbars. The viewport metadata enables safe-area coverage and requests content resizing for virtual keyboards where supported. The measurement takes the smallest positive innerHeight, root clientHeight and VisualViewport height. VisualViewport resize/scroll and window resize/pageshow update it near normal zoom, with a fallback when VisualViewport is unavailable. The welcome section does not shrink, so overflowing prompt content remains scrollable above the composer.
- The collapsed desktop/tablet rail is 64 px with 10 px side padding. New chat, Chat, Approvals, Mandate, Settings and the menu share 44 px icon targets on the same center line. Zero approval counts are omitted; positive counts remain visible as compact badges.
- Desktop width changes take 240 ms without overshoot. Phone drawers use Motion transform enter/exit over 240 ms and a short fading backdrop. A closed mobile drawer is inert and hidden from assistive technology during its exit. Reduced motion makes both layouts switch immediately. Purple also marks keyboard focus, the avatar and the focused composer for consistency with the logo.
- A manual scroll upward prevents incoming replies from moving the reader. Sending a new message resumes following the bottom. Reduced-motion preferences remain honored by the existing global styles and unchanged approval animations.

## Product behavior

New user messages, assistant replies and the processing row enter with a 240 ms opacity/8 px translate animation, without scaling or changing layout. Messages already present on entering Chat stay still. Reply updates use native smooth scrolling while following the bottom; intermediate programmatic scroll events do not accidentally disable following. Wheel-up, pointer/touch input and upward navigation keys interrupt automatic scrolling. Reading older messages preserves that position; sending a new message resumes following. Reduced motion uses immediate message updates and instant scrolling, and restoring existing history positions the transcript immediately.

On entering Chat, Motion animates the greeting at 0 ms, its question at 80 ms, four prompt cards at 160/220/280/340 ms, the composer at 400 ms and helper text at 480 ms. Each moves upward by 10 px while fading in over 400 ms, without bounce or layout changes. It begins after role information loads, once per mounted Chat page, and does not replay on typing, reset or role changes. Reduced motion skips it; focus or pointer interaction completes it immediately. Existing computed opacity is preserved, including the user's muted footer. The mesh-card intro and hover behavior remain separate. This requested entrance sequence is another explicit exception to the initial motion dial.

Wali, Simulation, and the actual role initial replace Nova, the invented model name, and the sample user. Suggestions cover reconciliation, cash forecasts, invoice review, and cash-flow recommendations. They fill the composer and never send automatically. Recent derives its single title from the active conversation's first user message; it does not imply persisted history.

Settings and help opens as a nonmodal profile dropdown below the top-right avatar, retaining the real simulation role selector. The 360 px white panel uses a pale role section, clear help divisions and one soft shadow to separate it from the page underneath. A brief 180 ms opacity/transform transition connects it to its trigger without bounce; reduced motion removes the transition. The sidebar links to the three existing destinations. A failed New chat preserves the transcript and shows the error; navigation follows a successful reset only. API-derived amounts, approvals, blocked flags, and notices remain unchanged.

Future model selection, attachments, tools, voice, feedback, regeneration, and saved history are explicitly unavailable. They never invoke an API. Copy uses the clipboard with success and failure feedback. Reply content is rendered as text with preserved whitespace, never injected as HTML.

The shared shell and all three pages use `paper-` CSS classes so the current design does not depend on legacy styles. Every active icon control has a 44 px target and an accessible label. Drawers trap focus, support Escape, and restore focus. The profile dropdown focuses its nonmodal dialog when opened, closes on Escape, outside clicks or Tab departure, and restores focus on explicit dismissal. The mobile sidebar settings shortcut closes the drawer before opening the same profile dropdown, returning focus to the avatar. Narrow and short viewports constrain the dropdown to the screen with internal scrolling.

## Approvals and Mandate

Both pages share Chat's centered 760 px content lane with 40 px desktop gutters, 48 px headings, white surfaces, pale `#F0F4F9` panels, purple accents and pill-shaped controls. On phones, gutters reduce to 20 px, headings to 32 px, panel radii to 20 px, and action targets stay at least 44 px. Shared headings state the actual role and request counts without using technical uppercase labels.

Approvals uses a single readable column rather than two dense cards. Each request groups its actual type and expiry, supplier or mandate title, requester and required role, payment amount, invoice facts, changes and risk warnings. Amounts use tabular figures. Long account identifiers wrap, and labels/values stack on phones. Amber remains reserved for warnings; Confirm is purple and Decline has a distinct red label and border. Requests are removed only after the existing API decision and queue refresh; failed decisions retain them. Empty state links back to Chat, while connection and queue errors have working retry actions.

Mandate presents the real two-step flow in one pale panel: draft, then review in Approvals. Only an actual owner role receives the Draft mandate button; non-owners get guidance to Settings and help. Connecting and disconnected states are separate from the role restriction. The draft creates a request, never a confirmation. Success links to Approvals and the pending status comes from the actual queue; a failed queue read has its own retry action. No editable policy fields, limits, supplier data or approval results are invented.

## Loading feedback

The user-supplied `loading.lottie` replaces the earlier sparkle/Motion treatment as Wali's identity. Its original archive is preserved at `public/brand/wali.lottie`; its vector animation data is extracted without changing shapes, colors or timing into `lib/wali-logo-animation.json`. The animation has 80 frames at 60 fps and uses seven purple vector tiles without external image assets. A tighter viewBox removes unused canvas margins without clipping the tile motion.

The header uses a stationary first-frame SVG from this same animation, also used for the favicon and a rendered 180 px touch icon. The pending status mark loops with the real sending state and is removed on success or failure. A completed reply plays one cycle, then returns to the static brand mark, keeping older replies still. The local light SVG renderer is loaded only for animation and cleaned up when its instance is removed. If playback cannot load, the first-frame image remains visible. Reduced motion uses only the stationary image and observes preference changes during a request. The Thinking text remains available to assistive technology. There is no estimated percentage or simulated processing timer.
