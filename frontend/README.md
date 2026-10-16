# Wali Web V2

The Next.js interface in this folder runs separately from Wali's original static web page. It does not change the Python API or V1 files.

## Run locally

Start the FastAPI simulation from the repository root:

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) '.uv-cache-v2'
uv run --isolated --python 3.11 python -m wali.interfaces.web
```

The isolated command avoids the broken `.venv` currently present in this local checkout. Once that environment is repaired, the repository's usual `uv run python -m wali.interfaces.web` works too.

In a second terminal, from `frontend/`:

```powershell
& 'D:\Program Files\nodejs\npm.cmd' ci
& 'D:\Program Files\nodejs\npm.cmd' run dev
```

Open `http://127.0.0.1:3000` for the public landing page. **Open Wali** enters `/chat`; `/chat`, `/approvals`, and `/mandate` also work directly. The landing page is server-rendered outside the workspace provider and makes no Wali API requests. Its example prompt is presentation only.

The workspace sidebar links to Chat, Approvals, and Mandate. On phones, Menu opens the sidebar drawer; Escape closes it. Open Settings and help, or the role avatar, to change the simulation role. The Next.js route handler proxies `/api/wali/*` to `http://127.0.0.1:8000` by default. To change the backend, copy `.env.example` to `.env.local` and set `WALI_API_ORIGIN` to its local origin. The browser does not call FastAPI directly; the server proxy sends JSON without the browser's `Origin` header and does not cache API responses.

The role selector stands in for login only in this local simulation. Anyone who can reach either server can select the owner role. Do not expose these servers to other machines or deploy this interface until authentication and authorization are designed for that environment.

The transcript and selected role are retained while navigating between pages in the same tab. Switching roles clears the transcript. There is no persistent history because Wali has no history endpoint. Only the owner can draft a mandate; drafting creates an approval request, not an automatic confirmation.

## Checks

`npm run test:landing` checks `/` at 1440, 1024, 768, 390 and 320 CSS px, sticky navigation, working anchors and Chat entry points, mobile menu focus, shader playback/pixel limits, reduced motion, contrast, no-WebGL fallback and no-JavaScript content. It asserts zero Wali API calls on the landing page and intercepts workspace requests after navigation. Screenshots `landing-*.png` and `landing-results.json` are written to ignored `test-results/`. Set `WALI_TEST_ORIGIN` to test a different local port.

```powershell
& 'D:\Program Files\nodejs\npm.cmd' run typecheck
& 'D:\Program Files\nodejs\npm.cmd' run lint
& 'D:\Program Files\nodejs\npm.cmd' run format:check
& 'D:\Program Files\nodejs\npm.cmd' run build
```

The project uses Next.js App Router, TypeScript, Tailwind CSS v4, `components/ui`, and `motion/react`. The `components.json` file makes the structure compatible with shadcn component additions; the main Wali interface is a custom component in that directory. No shadcn CLI generation is needed to run it.

## Paper chat interface

The home and conversation states follow the supplied Paper React exports. Wali keeps English finance prompts and its existing API. The shared sidebar collapses on desktop, starts compact on tablets, and becomes a keyboard-accessible drawer on phones. Recent shows only the active in-tab conversation; saved history is not implemented. Copy works on assistant replies. Model selection, attachments, tools, microphone, feedback, and regeneration are disabled placeholders labeled Coming soon.

Chat, Approvals, Mandate and the shared shell pair bundled Poppins headings (500/600, Latin subset) with Arial body text and controls. Fonts are served by the application without an external font service. The composer follows visual viewport height changes and the transcript only follows incoming messages when the reader is near the bottom.

The Wali logo is derived from the supplied `loading.lottie`, preserved at `public/brand/wali.lottie`. The header and favicon use its first frame. A local Lottie SVG player loops the mark while processing and plays one cycle on a new reply; reduced motion and player-loading failures retain a static image. Run `npm run test:loading` against the frontend on port 3000 to check playback, completion, reduced motion and favicon assets with mocked API requests.

The sidebar uses the logo's purple palette. Its compact state is 64 px wide with equal 44 px icon controls. Desktop open/close uses a 240 ms width transition; the phone drawer slides and its backdrop fades using Motion. Reduced motion switches states immediately. `npm run test:sidebar` verifies those transitions, proportions, colors and accessibility with mocked requests.

Approvals and Mandate share Chat's typography, centered content width, pale panels and purple action controls. Approvals groups payment facts, proposed changes and warnings above each decision. Mandate explains drafting and review, with explicit connection, owner-only and pending-request states. `npm run test:finance` checks these pages with mocked payment/mandate requests, decision and draft failures, retries, role restrictions, keyboard activation, five viewport widths and twelve measured text/boundary contrast checks. Screenshots and results are written to `test-results/`; no model is called.

## Browser regression checks

After `npm ci`, start the frontend on a separate port:

```powershell
npm.cmd run dev -- --port 3005
```

In another terminal run `npm.cmd run test:ui`. Google Chrome must be installed; the test uses Playwright's `chrome` channel. To test another port, set `$env:WALI_TEST_ORIGIN = 'http://127.0.0.1:3006'` before running it.

The test intercepts every `/api/wali/*` request and uses explicit test responses. It does not need FastAPI, call a model, or perform a financial action. It checks responsive layouts, chat failure recovery, blocked replies, clipboard success/failure, sidebar and profile keyboard behavior, role changes, approval flows, scroll behavior, and connection retry. Screenshots and results are written to ignored `test-results/`. These checks validate UI behavior, not live agent response quality or physical phone keyboards.

`npm run test:profile` checks the avatar dropdown animation, role selector, keyboard focus and dismissal, mobile sidebar shortcut, five responsive widths, short-screen scrolling, reduced motion and five text/control contrast pairs. It uses mocked API responses on port 3000 by default and writes `profile-results.json` plus desktop/phone screenshots in `test-results/`.

`npm run test:mobile-composer` checks the empty chat with Pixel 7 emulation at 393 x 700, 390 x 640, 320 x 568 and 320 x 400. It injects an oversized stored viewport measurement, verifies that the composer stays within the visible screen, scrolls to the final prompt, taps it, checks focus/send reachability and tests viewport shrinkage. All APIs are mocked; this does not reproduce physical browser chrome or a real phone keyboard.

Chat uses the user-supplied Paper GrainGradient from `@paper-design/shaders-react@0.0.81`, loaded on the client with a pale CSS fallback. Lavender/mauve/blue colors, a white veil and lower opacity during conversation keep the background secondary. Reduced motion stops playback; mobile uses a lower speed and pixel budget. `npm run test:background` checks shader initialization, reduced motion, WebGL fallback, prompt/send behavior, mobile bounds and Chat-only scope with mocked APIs, and saves screenshots in `test-results/`.

`npm run test:prompt-mesh` checks the Paper MeshGradient prompt cards: initial playback then pause, actual frame progression on hover, pause on pointer leave, keyboard focus/activation, reduced motion and responsive bounds. Screenshots and `prompt-mesh-results.json` are saved in `test-results/`. No model calls or financial actions are used.

`npm run test:chat-intro` checks stagger timings for greeting, question, prompt cards and composer, natural completion, immediate completion on focus, reduced-motion bypass, unchanged footer opacity, no replay on typing/New chat, and mobile composer bounds. API responses are mocked.

`npm run test:message-motion` checks real message animation durations, intermediate native smooth-scroll positions, interruption while reading previous messages, resumed following on a new send, restored history without replay, and reduced-motion updates. Replies are mocked and no model or financial action is invoked.
