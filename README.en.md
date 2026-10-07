# Open Genjutsu

[한국어](README.md) · [English](README.en.md) · [简体中文](README.zh-CN.md)

**A self-hosted video production platform that turns source motion into new characters and scenes.** Combine models and prompts in your browser, track generation jobs, and download finished videos.

## Features

- Connect source video, reference images, scene analysis, prompt design, motion transfer, editing, and output nodes.
- Configure providers, model IDs, prompts, and generation parameters independently for each node.
- Store projects and media per account, detect revision conflicts, and exchange workflow JSON.
- Track jobs and per-node results, request cancellation, download videos, and manage stored media.
- Use Temporal to dispatch persisted jobs after API restarts and continue polling the same provider job after Worker restarts.
- Create team accounts and store encrypted API keys, with endpoint-specific credentials for Custom/GPU APIs.

## Installation

Requires Docker Engine, Docker Compose v2, and Python 3. Run in the checked-out repository:

```bash
python3 scripts/configure.py
docker compose up -d --build
docker compose ps
```

Open `http://localhost:8000` and sign in with the administrator credentials generated in `.env`. Review the email and initial password locally, keep the file private, and register provider keys through the **API 키** menu. The web interface currently uses Korean.

Use HTTPS for public access. Configure your DNS and `.env`:

```dotenv
GENJUTSU_DOMAIN=studio.example.com
GENJUTSU_PUBLIC_URL=https://studio.example.com
GENJUTSU_SECURE_COOKIES=true
```

```bash
docker compose --profile tls up -d --build
```

Caddy provides HTTPS. External video providers must be able to retrieve signed input media URLs from your public origin. The default API port binds to loopback; database and Temporal ports are private.

## Create a video

1. Upload a source video and reference image to a new project.
2. Choose the motion model and parameters. The default graph uses Wan-Animate and FFmpeg output.
3. Add analysis, prompt, or editing nodes when needed. Use the node's provider-input JSON for model-specific options.
4. Open **실행 계획**, review server validation, acknowledge paid API steps, and select **생성 시작**.
5. Track progress in **작업 내역** and download the result. The output step combines source audio and encodes MP4.

Wan-Animate does not accept a free-form prompt. Its default graph omits paid language-model stages that cannot affect the video. Use VACE or a compatible model server for prompt control. Added language-model nodes default to Dolphin and accept other model IDs.

## Provider support

| Provider | Usage |
| --- | --- |
| OpenRouter / OpenAI-compatible Custom | Sample-frame analysis and prompt generation |
| fal | Wan-Animate move/replace, Wan VACE, Kling v3 Motion Control |
| Replicate | Prediction API with model-specific input JSON |
| Custom / GPU API | Model servers implementing the asynchronous job contract |
| Local | Media input, FFmpeg encoding, and source-audio composition |

Operators approve Custom/GPU endpoints and result CDN hosts. Replicate input fields must match the selected model schema. Availability, pricing, and usage policies follow the provider. GPU inference servers and a mask-painting UI are not bundled.

## Operations

Default limits: 128MB per upload, 30-second videos, 2GB storage per user, two active jobs, and four paid steps per generation. See `.env.example` and also configure spending limits in provider accounts.

A lost submission response enters operator review rather than automatically repeating a paid request. Recover with a verified provider job ID or close the job after confirming the external execution and billing. Cancellation requests do not imply refunds.

```bash
curl -fsS http://localhost:8000/api/readyz
docker compose logs --tail=100 api worker
bash scripts/backup.sh
```

Run backups during maintenance with no active jobs. This is a single-host deployment; host recovery requires backups of both databases, media, and encryption keys.

Detailed documents are currently in Korean:

- [Deployment, backup, recovery, and upgrades](docs/operations.ko.md)
- [Model inputs and Custom/GPU API contract](docs/provider-contract.ko.md)
- [Service validation and its scope](docs/service-validation.ko.md)
- [Model research](docs/genjutsu-research-and-plan.ko.md)

## Development and validation

The frontend requires Node.js 22.12+, and the backend uses Python 3.12. `npm run dev` connects to the running local API; `npm run dev:editor` runs the offline editor.

```bash
npm ci
npm test
npm run build
npm run test:e2e
npm run test:service
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
PYTHONPATH=backend .venv/bin/pytest backend/tests -m 'not integration'
```

Set `GENJUTSU_TEST_TEMPORAL_ADDRESS` for real Temporal integration tests. Opt into container restart tests with `GENJUTSU_TEST_COMPOSE_STACK=1` only on a disposable test stack. External paid-provider tests use a fake provider; validate actual generation quality and billing separately with your operational account.
