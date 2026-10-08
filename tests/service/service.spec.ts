import { test, expect, request } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
const config = Object.fromEntries(
  readFileSync(".env", "utf8")
    .split("\n")
    .filter((line) => line && !line.startsWith("#"))
    .map((line) => {
      const i = line.indexOf("=");
      return [line.slice(0, i), line.slice(i + 1)];
    }),
);
const password = "Browser-test-password-123";
test.beforeEach(async ({ page, baseURL }) => {
  const email = `browser-${randomUUID()}@tests.invalid`;
  // Separate context keeps operator credentials out of browser traces.
  const admin = await request.newContext({ baseURL });
  expect(
    (
      await admin.post("/api/auth/login", {
        data: {
          email: config.GENJUTSU_ADMIN_EMAIL,
          password: config.GENJUTSU_ADMIN_PASSWORD,
        },
      })
    ).ok(),
  ).toBe(true);
  const csrf = (await admin.storageState()).cookies.find(
    (c) => c.name === "genjutsu_csrf",
  )!.value;
  expect(
    (
      await admin.post("/api/admin/users", {
        data: { email, password },
        headers: { "X-CSRF-Token": csrf },
      })
    ).status(),
  ).toBe(201);
  await admin.dispose();
  await page.goto("/");
  await page.getByLabel("이메일", { exact: true }).fill(email);
  await page.getByLabel("비밀번호", { exact: true }).fill(password);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page.locator(".service-bar")).toBeVisible();
  await expect(page.locator(".react-flow__node")).toHaveCount(4);
});
async function inspector(page: any) {
  await expect(page.locator(".service-bar")).toBeVisible();
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
  if (
    await page
      .getByRole("button", { name: "노드 설정 열기", exact: true })
      .count()
  )
    await page
      .getByRole("button", { name: "노드 설정 열기", exact: true })
      .click();
}
async function saved(page: any) {
  await expect(page.locator(".save-status")).toContainText("서버 저장됨");
}
test("server saves model and prompt across refresh", async ({ page }) => {
  await inspector(page);
  await page.getByLabel("모델 ID", { exact: true }).fill("my/custom-model");
  await page
    .getByLabel("노드 프롬프트", { exact: true })
    .fill("서버에 저장할 프롬프트");
  await saved(page);
  await page.reload();
  await inspector(page);
  await expect(page.getByLabel("모델 ID", { exact: true })).toHaveValue(
    "my/custom-model",
  );
  await expect(page.getByLabel("노드 프롬프트", { exact: true })).toHaveValue(
    "서버에 저장할 프롬프트",
  );
});
test("model-specific forms preserve options across refresh", async ({
  page,
}) => {
  await inspector(page);
  await page
    .getByLabel("모델 ID", { exact: true })
    .fill("fal-ai/kling-video/v3/pro/motion-control");
  await page
    .getByLabel("캐릭터 방향 기준", { exact: true })
    .selectOption("image");
  await page
    .getByLabel("공급자 결과에 원본 오디오 유지", { exact: true })
    .uncheck();
  await saved(page);
  await page.reload();
  await inspector(page);
  await expect(
    page.getByLabel("캐릭터 방향 기준", { exact: true }),
  ).toHaveValue("image");
  await expect(
    page.getByLabel("공급자 결과에 원본 오디오 유지", { exact: true }),
  ).not.toBeChecked();
  await page.getByLabel("모델 ID", { exact: true }).fill("fal-ai/wan-vace-14b");
  await page
    .getByLabel("VACE 작업", { exact: true })
    .selectOption("inpainting");
  await expect(
    page.getByLabel("마스크 영상 URL", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("추론 단계", { exact: true }).fill("40");
  await expect(
    page.getByLabel("공급자 입력 JSON", { exact: true }),
  ).toHaveValue(/"num_inference_steps": 40/);
  await expect(
    page.getByRole("button", { name: "운영 현황", exact: true }),
  ).toHaveCount(0);
});
test("API keys stay hidden and modal Delete cannot remove nodes", async ({
  page,
}) => {
  await page.getByRole("button", { name: "API 키", exact: true }).click();
  await page.keyboard.press("Delete");
  await expect(page.locator(".react-flow__node")).toHaveCount(4);
  await page
    .getByLabel("API 키", { exact: true })
    .fill("fake-browser-provider-key");
  await page.getByRole("button", { name: "키 저장", exact: true }).click();
  await expect(page.locator(".key-list")).toContainText("openrouter · 연결됨");
  await expect(page.getByLabel("API 키", { exact: true })).toHaveValue("");
  await page.keyboard.press("Escape");
  await expect(page.locator(".service-dialog")).toHaveCount(0);
  await page
    .getByRole("button", { name: "실행 계획", exact: true })
    .first()
    .click();
  await expect(page.locator(".server-preflight")).toContainText(
    "미디어를 서버에 업로드하세요",
  );
  await expect(
    page.getByRole("button", { name: "생성 시작", exact: true }),
  ).toBeDisabled();
});
test("upload, real Temporal generation and download preserve audio", async ({
  page,
}) => {
  const graph = {
    version: 1,
    title: "서비스 영상 테스트",
    nodes: [
      {
        id: "source",
        type: "studio",
        position: { x: 0, y: 0 },
        data: {
          kind: "video",
          label: "원본 영상",
          provider: "local",
          model: "media-input",
          prompt: "",
          temperature: 0.7,
          seed: "42",
          resolution: "720p",
        },
      },
      {
        id: "output",
        type: "studio",
        position: { x: 300, y: 0 },
        data: {
          kind: "output",
          label: "결과 내보내기",
          provider: "local",
          model: "ffmpeg",
          prompt: "",
          temperature: 0.7,
          seed: "42",
          resolution: "720p",
        },
      },
    ],
    edges: [
      { id: "e", source: "source", target: "output", type: "smoothstep" },
    ],
  };
  await page
    .locator("input[type=file]")
    .first()
    .setInputFiles({
      name: "workflow.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(graph)),
    });
  await expect(page.locator(".react-flow__node")).toHaveCount(2);
  await inspector(page);
  const folder = mkdtempSync(join(tmpdir(), "genjutsu-service-"));
  const source = join(folder, "source.mp4");
  execFileSync("ffmpeg", [
    "-v",
    "error",
    "-f",
    "lavfi",
    "-i",
    "color=c=blue:s=64x64:d=1",
    "-f",
    "lavfi",
    "-i",
    "sine=frequency=440:duration=1",
    "-c:v",
    "libx264",
    "-pix_fmt",
    "yuv420p",
    "-threads",
    "1",
    "-c:a",
    "aac",
    source,
  ]);
  try {
    await page.locator("input[type=file]").nth(1).setInputFiles(source);
    await expect(page.locator(".upload-zone")).toContainText("source.mp4");
    await expect
      .poll(() =>
        page
          .locator("video.asset-preview")
          .evaluate((v: HTMLVideoElement) => v.readyState),
      )
      .toBeGreaterThanOrEqual(2);
    await saved(page);
    await page
      .getByRole("button", { name: "실행 계획", exact: true })
      .first()
      .click();
    await expect(
      page.getByRole("button", { name: "생성 시작", exact: true }),
    ).toBeEnabled();
    await page.getByRole("button", { name: "생성 시작", exact: true }).click();
    await expect(page.locator(".job-state")).toHaveText("완료");
    const waiting = page.waitForEvent("download");
    await page
      .locator(".job-card li")
      .filter({ hasText: "output" })
      .getByRole("link", { name: "파일 다운로드" })
      .click();
    const download = await waiting;
    const probe = JSON.parse(
      execFileSync(
        "ffprobe",
        [
          "-v",
          "error",
          "-show_streams",
          "-of",
          "json",
          (await download.path())!,
        ],
        { encoding: "utf8" },
      ),
    );
    expect(probe.streams.some((s: any) => s.codec_type === "audio")).toBe(true);
    expect(probe.streams.some((s: any) => s.codec_type === "video")).toBe(true);
    await page.keyboard.press("Escape");
    await page.reload();
    await inspector(page);
    await expect(page.locator(".upload-zone")).toContainText("source.mp4");
    await expect(page.locator("video.asset-preview")).toHaveAttribute(
      "src",
      /^\/api\/assets\//,
    );
  } finally {
    rmSync(folder, { recursive: true, force: true });
  }
});
test("service editor and key dialog pass accessibility and layout checks", async ({
  page,
}, info) => {
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.screenshot({
    path: `test-results/${info.project.name}.png`,
    fullPage: true,
  });
  await page.getByRole("button", { name: "API 키", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "서비스 창 닫기", exact: true }),
  ).toBeFocused();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(
    (await page.viewportSize())!.width,
  );
});
test("logout clears authenticated access", async ({ page }) => {
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "로그인", exact: true }),
  ).toBeVisible();
  expect((await page.request.get("/api/workflows")).status()).toBe(401);
});

test("unused media and projects can be removed through the service UI", async ({
  page,
  context,
}) => {
  const csrf = (await context.cookies()).find(
    (c) => c.name === "genjutsu_csrf",
  )!.value;
  const png = Buffer.from(
    await page.evaluate(() => {
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 16;
      const drawing = canvas.getContext("2d")!;
      drawing.fillStyle = "green";
      drawing.fillRect(0, 0, 16, 16);
      return canvas.toDataURL("image/png").split(",")[1];
    }),
    "base64",
  );
  const asset = await page.request.post("/api/assets", {
    headers: { "X-CSRF-Token": csrf },
    multipart: {
      file: { name: "unused.png", mimeType: "image/png", buffer: png },
    },
  });
  expect(asset.status()).toBe(201);
  const id = (await asset.json()).id;
  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "미디어", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "미디어 보관함", exact: true }),
  ).toBeVisible();
  await page
    .locator(".key-list li")
    .filter({ hasText: "unused.png" })
    .getByRole("button", { name: "삭제", exact: true })
    .click();
  await expect(page.locator(".key-list li")).toHaveCount(0);
  expect((await page.request.get(`/api/assets/${id}/content`)).status()).toBe(
    404,
  );
  await page.keyboard.press("Escape");
  const previous = await page
    .getByLabel("저장된 워크플로", { exact: true })
    .inputValue();
  await page
    .getByRole("button", { name: "프로젝트 삭제", exact: true })
    .click();
  await expect(
    page.getByLabel("저장된 워크플로", { exact: true }),
  ).not.toHaveValue(previous);
  await expect(page.locator(".react-flow__node")).toHaveCount(4);
});
