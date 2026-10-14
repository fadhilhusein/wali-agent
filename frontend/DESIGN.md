# Wali Web V2: design direction

## Design read

Wali V2 is a local financial conversation workspace for small-business operators. It is not a marketing page. The interface uses English, a light theme, and the approved white/blue reference as a point of departure. ENERGY 2 / RHYTHM 2 / MOTION 2.

The UI has a fixed left navigation and a centered work area, borrowing only the spatial composition of the supplied Gemini screenshot. Wali has three real destinations: Chat, Approvals, and Mandate. The empty conversation is the visual anchor; requests and drafting have separate pages so decisions do not compete with writing a message. There is no invented chat history or unsupported navigation.

## Palette and type

| Role | Value | Purpose |
| --- | --- | --- |
| White | `#FFFFFF` | Primary conversation surface |
| Cloud | `#F6F8FC` | Distinguish the navigation sidebar |
| Ink | `#12213D` | Primary text |
| Slate | `#586681` | Secondary text |
| Blue | `#1748BF` | Real actions and identity |
| Line | `#D9E2EF` | Ledger-like hierarchy |
| Amber ink | `#744018` | Risk information, always paired with a warning label |

Outfit is self-hosted through `@fontsource/outfit`; system sans-serif remains the fallback. The wide, short empty-state headline borrows editorial breathing room from the reference without turning the work area into a landing-page hero. Numeric amounts use tabular figures. Type and controls retain readable sizes at narrow widths and 200% zoom.

Outfit's broad lowercase forms make the assistant conversational without weakening the dense approval details. Small uppercase labels distinguish request types and navigation context from values the user can act on. Simple symbols support navigation scanning; text labels remain primary.

## Spacing, shape, and motion

Desktop uses a 258 px sidebar and a fluid main panel. At tablet width the sidebar narrows and approval cards stack. At phone width the sidebar becomes an Escape-dismissable drawer opened by a labeled Menu button; content remains a single column, including at a 320 CSS px layout budget for 200% zoom. The baseline spacing is 4/8/12/16/24/32 px, with larger negative space reserved for the empty chat state. Corners are modest; borders do most of the grouping work, with a single restrained composer shadow for input priority.

The quick prompts share one size because they are equal starting choices, not feature cards in a marketing grid. Ledger dividers and tabular amounts carry Wali's financial identity into the separate Approvals and Mandate pages. The simulation label and role selector sit together at the bottom of the sidebar to make the local-only status explicit.

MotionJS enters pages, messages, and queue cards in less than 300 ms. Controls use short state transitions. There is no continuous gradient logo, looping decoration, pinning, or scroll theatre. `prefers-reduced-motion` removes these movements. Motion communicates new state; it is never a prerequisite to understanding it.

## Product decisions

- The Wali text wordmark replaces the generic rotating gradient logo. No new logo asset or invented business metrics are used.
- Prompt categories are real finance tasks that fill and focus the composer. They never send on behalf of the user.
- Search, Deep Research, Reason, microphone, and file upload are informational “Coming soon” text, not misleading buttons.
- The role selector is visibly part of a simulation. It is not authentication and must remain local-only until an actual auth model exists.
- The shared App Router layout retains the current role and in-tab transcript between destinations. Role changes clear the transcript; New chat resets it for that role. There is no persistent history API, so none is implied.
- Mandate can be opened by any role to explain the permission boundary. Only the owner sees Draft mandate; a successful draft links to Approvals for a decision.
- Amounts, supplier names, invoice details, risk warnings, and approval outcomes are shown only from API responses.
- Risk and error states use words and structure as well as color. Decisions are next to the details they affect.
- AIDA chapters, GSAP, bento grids, stock photography, and oversized landing-page spacing are omitted because this screen is an operational workspace and the requested motion library is MotionJS.
