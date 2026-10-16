# Open Genjutsu

Versioned releases, approval gates, digest-pinned deployment and rollback procedures: [release guide (Korean)](docs/release-process.ko.md).

[한국어](README.md) · [English](README.en.md) · [简体中文](README.zh-CN.md)

**A self-hosted video production platform that turns source motion into new characters and scenes.** Combine models and prompts in your browser, track generation jobs, and download finished videos.

## Features

- Connect source video, reference image, scene analysis, prompt writer, motion transfer, video edit, and Final output nodes.
- Choose OpenRouter text, image, and video models, and configure model IDs, prompts, and model options independently for each node.
- Store projects and media per account, detect revision conflicts, and exchange project JSON.
- Track jobs and per-node results, request cancellation, download videos, and manage stored media.
- Use Temporal to dispatch persisted jobs after API restarts and continue polling the same generation request after Worker restarts.
- Create team accounts and store an encrypted OpenRouter API key for each account.
- Start from the Genjutsu template (MiniMax H3 motion transfer) with per-node recommended models and model options, while keeping other OpenRouter model IDs and advanced options (JSON).
- Inspect queue age, recent completion P95, media and disk usage, and recover ambiguous generation requests from an administrator dashboard.

## Installation

For HTTPS without inbound port forwarding, follow the [Cloudflare Tunnel guide (Korean)](docs/cloudflare-staging.ko.md). A Docker host and domain are still required.

Requires Docker Engine, Docker Compose v2, and Python 3. Run in the checked-out repository:

```bash
python3 scripts/configure.py
docker compose up -d --build
docker compose ps
```

Open `http://localhost:8000` and sign in with the administrator credentials generated in `.env`. Review the email and initial password locally, keep the file private, and register your OpenRouter key through the **API 키** menu. The web interface currently uses Korean.

Start with **새 프로젝트 템플릿 → 로컬 영상 테스트** to check upload, Temporal execution and MP4 download without API charges. On localhost, an OpenRouter key also runs analysis, prompt, image generation, and image-to-video steps. **Motion transfer or video editing with a source video requires a public HTTPS address**, because OpenRouter accepts videos sent to the model only as public HTTPS URLs. See the [local testing guide (Korean)](docs/local-testing.ko.md) for setup and a $10 total evaluation budget; enforce spending limits in your OpenRouter account.

Use HTTPS for public access. Configure your DNS and `.env`:

```dotenv
GENJUTSU_DOMAIN=studio.example.com
GENJUTSU_PUBLIC_URL=https://studio.example.com
GENJUTSU_SECURE_COOKIES=true
```

```bash
docker compose --profile tls up -d --build
```

Caddy provides HTTPS. With a public HTTPS address, OpenRouter retrieves input media through expiring signed URLs, so it must be able to reach your origin. The default API port binds to loopback; database and Temporal ports are private.

## Create a video

1. Upload a source video and reference image to a new project. On the source video node you can set the **range** (**구간**, e.g. 3–8 s of a 10 s video) at 0.1 s precision while watching the preview; without one the whole video is used. Motion transfer and video edit steps that take the source video generate the shortest model duration covering the range and cut the result to its length; source audio follows the range too.
2. Start from the **Genjutsu** template (source video + reference image → motion transfer → Final output) and adjust the motion-transfer model and model options. The default project uses MiniMax H3 motion transfer and an FFmpeg Final output. Seedance 2.5 is no longer the motion-transfer default because it rejects source videos that appear to show a real person.
3. Add scene analysis, prompt writer, or video edit nodes when needed. Pick model-specific settings under the node's model options (**모델 옵션**), or edit them as JSON in **고급 옵션(JSON)**.
4. Open the pre-run check (**실행 전 확인**), review the steps, estimated costs, errors and warnings, acknowledge paid API steps, and select **생성 시작**.
5. Track progress in Job history (**작업 내역**) and download the result. The Final output node saves the one connected image or video as the result. Videos are encoded to MP4 with the audio chosen on the node (source audio, generated audio or silent); when unset, it uses the source audio if a source video feeds the flow and the generated audio otherwise.

The motion transfer node sends the reference image as an identity and style reference (**인물·스타일 참조**) together with the source video, with a default prompt asking the reference character to perform the source video's motion, camera movement, and timing. The default project omits paid language-model steps. Added scene analysis and prompt writer nodes default to Qwen3 VL and Dolphin and accept other model IDs.

The **추천 모델** list shows only models for the selected node kind. The OpenRouter model ID field suggests models for the selected node from OpenRouter's public catalog (about 650 text, image and video models), refreshed by the server every 6 hours. Use the **Image generation** node to create reference images, and pick OpenRouter video models in motion transfer or video edit nodes. OpenRouter video generation requests cannot be cancelled once started, and sending a source video to the model requires a public HTTPS address. The pre-run check shows estimated costs for per-second-priced models (such as MiniMax H3, Wan, Kling, Veo, and FLUX.3) and marks token-priced models such as Seedance as unestimated; Job history shows the cost reported by the provider.

## Provider support

| Provider | Usage |
| --- | --- |
| OpenRouter text | Sample-frame or full-video analysis and prompt generation |
| OpenRouter images and video | Reference image generation, motion transfer and video editing from a source video and reference image, image-to-video generation |
| Local | Media input and Final output (FFmpeg; image or video result, audio choice) |

Generation uses OpenRouter only; the provider is fixed per node kind. Among the recommended video models, MiniMax H3, Seedance 2.5, Seedance 2.0, Seedance 2.0 Fast, FLUX.3 Video, and Runway Aleph 2.0 (video editing) accept a source video; Veo 3.1, Kling v3.0 Pro, Wan 3.0, and Grok Imagine Video 1.5 generate from images only. In real tests, Seedance 2.5 rejected a source video that appeared to show a real person, and FLUX.3 Video does not accept a source video and a reference image in the same request, so it cannot be used for motion transfer. Other OpenRouter models can still be entered by ID. Availability, pricing, and usage policies follow OpenRouter and the model provider. Projects saved with earlier fal, Replicate, GPU, or Custom nodes open with the OpenRouter default model for each step.

## Operations

Default limits: 512MB per upload, 120-second videos, 2GB storage per user, two active jobs, and four paid steps per job. See `.env.example` and also configure spending limits in provider accounts.

A lost submission response enters operator review rather than automatically repeating a paid request. Recover with a verified generation request ID or close the job after confirming the external execution and billing. Cancellation requests do not imply refunds.

```bash
curl -fsS http://localhost:8000/api/readyz
docker compose logs --tail=100 api worker
bash scripts/backup.sh
```

Run backups during maintenance with no active jobs. This is a single-host deployment; host recovery requires backups of both databases, media, and encryption keys.

Detailed documents are currently in Korean:

- [Deployment, backup, recovery, and upgrades](docs/operations.ko.md)
- [Model options and OpenRouter contract](docs/provider-contract.ko.md)
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
