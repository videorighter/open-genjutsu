# Open Genjutsu

[한국어](README.md) · [English](README.en.md) · [简体中文](README.zh-CN.md)

A node-based workflow studio for combining multiple video models. Each node has independently configurable API providers, model IDs, prompts, and generation settings.

## Getting started

Requires Node.js 22.12 or later. Validated with Node.js 24 in the current environment.

```bash
npm ci
npm run dev
```

## Web UI

- Add nodes, drag them into position, connect ports, duplicate, delete, and undo changes.
- Select OpenRouter, fal, Replicate, GPU Worker, Custom API, or Local providers.
- Choose recommended models or enter custom model IDs and API endpoints.
- Edit prompts, temperature, seed, and resolution independently for each node.
- Automatically save in browser storage and import/export workflow JSON.
- Reject cyclic or duplicate connections and invalid JSON; inspect execution order and model compatibility warnings.
- Edit on desktop or mobile and preview media within the current session.

The current implementation is a **workflow editor and execution-plan preview**. Temporal, authentication, API key management, and video generation APIs are not connected yet. The execution-plan button validates and exports a JSON plan without generating videos or incurring API charges. Do not enter API keys in the UI or workflow JSON.

Media previews remain in the browser session and are not uploaded to a server. Reattach files after refreshing. Browser storage is specific to the browser and device; export JSON to move a workflow to another environment.

## Validation

```bash
npm test
npm run build
npm run test:e2e
```

`test:e2e` builds the production application, then uses Playwright to operate desktop and mobile Chromium. It automatically uses `/usr/bin/chromium` when available. Set `PLAYWRIGHT_CHROMIUM_EXECUTABLE` to use a different executable. If system Chromium is unavailable, run `npx playwright install chromium` first. Your operating system also needs the browser's runtime dependencies.

Open the HTML results with `npm run test:e2e:report`. Screenshots and traces for failed tests are saved in `test-results/`. Validation does not call video generation APIs.

- [Direct browser validation results (Korean)](docs/browser-validation.ko.md)

## Design

The detailed design documents are currently available in Korean.

- [Model research and implementation plan](docs/genjutsu-research-and-plan.ko.md)
- [Temporal execution architecture](docs/temporal-architecture.ko.md)
- [Web editor data and execution integration](docs/web-studio.ko.md)
