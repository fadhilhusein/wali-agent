# Third-party components

Versions are the ones pinned in `pyproject.toml` (Python) and installed from
`frontend/package-lock.json` (web front end). Licences are as the packages declare them.

## Python (the agent, guard, simulation, CLI, Telegram bot, API)

| Package | Version | Licence | Used for |
| --- | --- | --- | --- |
| anthropic | 1.13.0 | MIT | Anthropic model client (when `WALI_LLM_PROVIDER=anthropic`) |
| cryptography | 50.0.2 | Apache-2.0 or BSD-3-Clause | Ed25519 signatures on mandates and payment approvals |
| fastapi | 0.143.0 | MIT | The JSON API behind the web pages |
| httpx | 0.28.1 | BSD-3-Clause | The OpenAI-compatible model client; FastAPI's test client |
| pydantic | 2.14.1 | MIT | Data models and settings validation |
| python-telegram-bot | 22.8 | LGPL-3.0-only | The Telegram bot (used as an unmodified library) |
| PyYAML | 6.0.3 | MIT | Reading the evaluation files |
| uvicorn | 0.54.0 | BSD-3-Clause | Serving the web API |

Development only: pytest 9.1.1 (MIT) for tests, ruff 0.17.0 (MIT) for linting and formatting.
Packages these depend on (for example starlette, pydantic-core) are installed by `uv` and keep
their own licences.

## Web front end (`frontend/`, built by the team)

| Package | Version | Licence |
| --- | --- | --- |
| next | 16.4.0 | MIT |
| react, react-dom | 19.3.0 | MIT |
| motion | 14.2.0 | MIT |
| @paper-design/shaders-react | 0.0.81 | Apache-2.0 |
| lottie-web | 5.13.0 | MIT |
| lucide-react | 1.58.0 | ISC |
| @fontsource/poppins, @fontsource/outfit | 5.3.0 | OFL-1.1 (the fonts) |
| clsx | 2.1.1 | MIT |
| tailwind-merge | 3.7.0 | MIT |

Development only: tailwindcss and @tailwindcss/postcss 4.3.3 (MIT), postcss 8.5.30 (MIT),
typescript 6.0.3 (Apache-2.0), eslint 9.39.5 and eslint-config-next 16.4.0 (MIT),
prettier 3.9.10 (MIT), playwright 1.62.1 (Apache-2.0), and the @types packages (MIT).

The Wali logo animation (`frontend/public/brand/wali.lottie`) was supplied by the team.

## Services

| Service | Used for | Notes |
| --- | --- | --- |
| A language model with tool calling | The assistant, and the sentinel's screening check | Configured in `.env`. The published evaluations used OpenAI-compatible endpoints: `deepseek-v4.1-flash` through the SumoPod gateway (`docs/results/`) and `openai/gpt-oss-20b` through NVIDIA NIM (`docs/baseline/`). The Anthropic path is supported and tested without a live model |
| GitHub Actions | Tests, lint, and frontend checks on every push and pull request | `.github/workflows/ci.yml`; it never calls a model |
| Telegram Bot API | The Telegram interface | Optional; needs a bot token from @BotFather |

No real bank, payment network, or personal data is used anywhere. The bank, the books, the
suppliers, and the people are all synthetic.

## Tools used to build it

The code was written with the help of Claude Code (Anthropic), working from the team's build
specification, with the team reviewing each phase. The development environment used Python 3.11
managed by uv.
