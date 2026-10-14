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

Open `http://127.0.0.1:3000`, which redirects to `/chat`. The sidebar links to `/chat`, `/approvals`, and `/mandate`. On phones, Menu opens the sidebar drawer; Escape closes it. The Next.js route handler proxies `/api/wali/*` to `http://127.0.0.1:8000` by default. To change the backend, copy `.env.example` to `.env.local` and set `WALI_API_ORIGIN` to its local origin. The browser does not call FastAPI directly; the server proxy sends JSON without the browser's `Origin` header and does not cache API responses.

The role selector stands in for login only in this local simulation. Anyone who can reach either server can select the owner role. Do not expose these servers to other machines or deploy this interface until authentication and authorization are designed for that environment.

The transcript and selected role are retained while navigating between pages in the same tab. Switching roles clears the transcript. There is no persistent history because Wali has no history endpoint. Only the owner can draft a mandate; drafting creates an approval request, not an automatic confirmation.

## Checks

```powershell
& 'D:\Program Files\nodejs\npm.cmd' run typecheck
& 'D:\Program Files\nodejs\npm.cmd' run lint
& 'D:\Program Files\nodejs\npm.cmd' run format:check
& 'D:\Program Files\nodejs\npm.cmd' run build
```

The project uses Next.js App Router, TypeScript, Tailwind CSS v4, `components/ui`, and `motion/react`. The `components.json` file makes the structure compatible with shadcn component additions; the main Wali interface is a custom component in that directory. No shadcn CLI generation is needed to run it.
