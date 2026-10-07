import { test, expect } from "./fixtures";
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
const store = "open-genjutsu.workflow.v1";
const node = (page: Page, id: string) =>
  page.locator(`.react-flow__node[data-id="${id}"]`);
async function saved(page: Page) {
  await expect(page.locator(".save-status")).toContainText("자동 저장됨");
}
async function exportGraph(page: Page) {
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "내보내기", exact: true }).click();
  const file = await download;
  const { readFile } = await import("node:fs/promises");
  return JSON.parse(await readFile((await file.path())!, "utf8"));
}
async function importGraph(page: Page, w: unknown) {
  await page
    .locator("input[type=file]")
    .first()
    .setInputFiles({
      name: "workflow.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(w)),
    });
}
async function ports(page: Page, source: string, target: string) {
  const a = await node(page, source)
    .locator(".react-flow__handle-right")
    .boundingBox();
  const b = await node(page, target)
    .locator(".react-flow__handle-left")
    .boundingBox();
  expect(a).toBeTruthy();
  expect(b).toBeTruthy();
  await page.mouse.move(a!.x + a!.width / 2, a!.y + a!.height / 2);
  await page.mouse.down();
  await page.mouse.move(b!.x + b!.width / 2, b!.y + b!.height / 2, {
    steps: 16,
  });
  await page.mouse.up();
}
test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".react-flow__node")).toHaveCount(6);
});
test("production page renders with no console errors or failed asset requests", async ({
  page,
}) => {
  const errors: string[] = [],
    failed: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("requestfailed", (r) => failed.push(r.url()));
  page.on("response", (r) => {
    if (r.status() >= 400) failed.push(`${r.status()} ${r.url()}`);
  });
  await page.reload();
  await page.evaluate(() => document.fonts.ready);
  await expect(page.locator(".react-flow__node")).toHaveCount(6);
  expect(errors).toEqual([]);
  expect(failed).toEqual([]);
});
test("all seven library types can be added, selected and configured", async ({
  page,
}) => {
  for (const name of [
    "원본 영상",
    "참조 이미지",
    "장면 분석",
    "프롬프트 설계",
    "모션 전이",
    "영역 편집",
    "결과 내보내기",
  ]) {
    await page.locator(".library-item").filter({ hasText: name }).click();
    await expect(page.getByLabel("노드 이름", { exact: true })).toHaveValue(
      name,
    );
    await page
      .getByLabel("노드 프롬프트", { exact: true })
      .fill(`지시: ${name}`);
  }
  await expect(page.locator(".react-flow__node")).toHaveCount(13);
});
test("library search filters Korean/English and recovers from no results", async ({
  page,
}) => {
  await page.getByLabel("노드 검색", { exact: true }).fill("motion");
  await expect(page.locator(".library-item")).toHaveCount(1);
  await page.getByLabel("노드 검색", { exact: true }).fill("zz-no-match");
  await expect(page.getByText("검색 결과가 없습니다.")).toBeVisible();
  await page.getByLabel("노드 검색", { exact: true }).fill("");
  await expect(page.locator(".library-item")).toHaveCount(7);
});
test("model provider, arbitrary model, endpoint, prompt and advanced settings persist", async ({
  page,
}) => {
  await page.getByLabel("API 공급자", { exact: true }).selectOption("custom");
  await page
    .getByLabel("API base URL", { exact: true })
    .fill("https://example.com/v1");
  await page.getByLabel("모델 ID", { exact: true }).fill("studio/free-model");
  await page
    .getByLabel("노드 프롬프트", { exact: true })
    .fill("한국어 프롬프트\nSecond line <script>alert(1)</script>");
  await page.getByLabel("노드 이름", { exact: true }).fill("나만의 설계");
  await page.getByLabel("Temperature", { exact: true }).fill("1.25");
  await page.getByLabel("Seed", { exact: true }).fill("1984");
  await page.getByLabel("해상도", { exact: true }).selectOption("1080p");
  await saved(page);
  await page.reload();
  await expect(page.getByLabel("모델 ID", { exact: true })).toHaveValue(
    "studio/free-model",
  );
  await expect(page.getByLabel("API base URL", { exact: true })).toHaveValue(
    "https://example.com/v1",
  );
  await expect(page.getByLabel("노드 이름", { exact: true })).toHaveValue(
    "나만의 설계",
  );
  await expect(page.getByLabel("Temperature", { exact: true })).toHaveValue(
    "1.25",
  );
  await expect(page.getByLabel("Seed", { exact: true })).toHaveValue("1984");
  await expect(page.getByLabel("해상도", { exact: true })).toHaveValue("1080p");
  await expect(page.getByLabel("노드 프롬프트", { exact: true })).toHaveValue(
    "한국어 프롬프트\nSecond line <script>alert(1)</script>",
  );
});
test("every provider remains independently editable across nodes", async ({
  page,
}) => {
  for (const provider of [
    "openrouter",
    "fal",
    "replicate",
    "gpu",
    "custom",
    "local",
  ]) {
    await page.getByLabel("API 공급자", { exact: true }).selectOption(provider);
    await expect(page.getByLabel("API 공급자", { exact: true })).toHaveValue(
      provider,
    );
    await page
      .getByLabel("모델 ID", { exact: true })
      .fill(`custom/${provider}`);
  }
  await node(page, "analysis").click();
  await expect(page.getByLabel("모델 ID", { exact: true })).toHaveValue(
    "qwen/qwen3-vl-32b-instruct",
  );
  await node(page, "director").click();
  await expect(page.getByLabel("모델 ID", { exact: true })).toHaveValue(
    "custom/local",
  );
});
test("prompt tab, clipboard and model preset are functional", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.getByRole("button", { name: "프롬프트 1", exact: true }).click();
  await page
    .getByLabel("노드 프롬프트", { exact: true })
    .fill("copy this prompt");
  await page
    .getByRole("button", { name: "프롬프트 복사", exact: true })
    .click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    "copy this prompt",
  );
  await page
    .locator(".inspector-tabs")
    .getByRole("button", { name: "설정", exact: true })
    .click();
  await page
    .getByLabel("추천 모델", { exact: true })
    .selectOption("nousresearch/hermes-3-llama-3.1-70b");
  await expect(page.getByLabel("모델 ID", { exact: true })).toHaveValue(
    "nousresearch/hermes-3-llama-3.1-70b",
  );
});
test("node drag position survives reload", async ({ page }) => {
  const old = await exportGraph(page);
  const box = await node(page, "director").boundingBox();
  await page.mouse.move(box!.x + 30, box!.y + 25);
  await page.mouse.down();
  await page.mouse.move(box!.x + 90, box!.y + 45, { steps: 10 });
  await page.mouse.up();
  await saved(page);
  await page.reload();
  const next = await exportGraph(page);
  expect(next.nodes.find((n: any) => n.id === "director").position).not.toEqual(
    old.nodes.find((n: any) => n.id === "director").position,
  );
});
test("node library supports drag-and-drop creation", async ({ page }) => {
  const library = page
    .locator(".library-item")
    .filter({ hasText: "영역 편집" });
  await library.dragTo(page.locator(".canvas-surface"), {
    targetPosition: { x: 250, y: 280 },
  });
  await expect(page.locator(".react-flow__node")).toHaveCount(7);
});
test("connection creation, cycle rejection, disconnection and undo work", async ({
  page,
}) => {
  await page.locator(".library-item").filter({ hasText: "영역 편집" }).click();
  const id = await page
    .locator(".react-flow__node")
    .last()
    .getAttribute("data-id");
  await page
    .getByRole("button", { name: "전체 노드 보기", exact: true })
    .click();
  await page.waitForTimeout(450);
  await ports(page, "motion", id!);
  await expect(page.locator(".react-flow__edge")).toHaveCount(7);
  await ports(page, "motion", "analysis");
  await expect(page.locator(".react-flow__edge")).toHaveCount(7);
  await node(page, id!).click();
  await page
    .getByRole("button", { name: "모션 전이 연결 삭제", exact: true })
    .click();
  await expect(page.locator(".react-flow__edge")).toHaveCount(6);
  await page.getByRole("button", { name: "되돌리기", exact: true }).click();
  await expect(page.locator(".react-flow__edge")).toHaveCount(7);
});
test("duplication, deletion, undo and redo retain config", async ({ page }) => {
  await page.getByLabel("노드 프롬프트", { exact: true }).fill("duplicate me");
  await page.getByRole("button", { name: "복제", exact: true }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(7);
  await expect(page.getByLabel("노드 프롬프트", { exact: true })).toHaveValue(
    "duplicate me",
  );
  await page
    .getByRole("button", { name: "선택한 노드 삭제", exact: true })
    .click();
  await expect(page.locator(".react-flow__node")).toHaveCount(6);
  await page.getByRole("button", { name: "되돌리기", exact: true }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(7);
  await page.getByRole("button", { name: "다시 실행", exact: true }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(6);
});
test("Delete works for selected node, but not while editing text", async ({
  page,
}) => {
  await page.getByLabel("노드 프롬프트", { exact: true }).focus();
  await page.keyboard.press("Delete");
  await expect(page.locator(".react-flow__node")).toHaveCount(6);
  await node(page, "director").click();
  await page.keyboard.press("Delete");
  await expect(page.locator(".react-flow__node")).toHaveCount(5);
  await expect(page.locator(".react-flow__edge")).toHaveCount(4);
});
test("a modal isolates background graph keyboard shortcuts", async ({
  page,
}) => {
  await page.getByRole("button", { name: "도움말 열기", exact: true }).click();
  await page.keyboard.press("Delete");
  await expect(page.locator(".react-flow__node")).toHaveCount(6);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
test("modal traps focus and restores the trigger", async ({ page }) => {
  const trigger = page.getByRole("button", {
    name: "도움말 열기",
    exact: true,
  });
  await trigger.click();
  const close = page.getByRole("button", {
    name: "대화상자 닫기",
    exact: true,
  });
  await expect(close).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(
    page.getByRole("button", { name: "만들기 시작", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(close).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
});
test("changes survive immediate reload without waiting for debounce", async ({
  page,
}) => {
  await page
    .getByLabel("노드 프롬프트", { exact: true })
    .fill("last edit before reload");
  await page.reload();
  await expect(page.getByLabel("노드 프롬프트", { exact: true })).toHaveValue(
    "last edit before reload",
  );
});
test("workflow JSON export and import preserve custom configuration", async ({
  page,
}) => {
  await page.getByLabel("모델 ID", { exact: true }).fill("arbitrary/model");
  await page.getByLabel("노드 프롬프트", { exact: true }).fill("round trip");
  const w = await exportGraph(page);
  w.title = "Imported graph";
  await importGraph(page, w);
  await expect(page.getByLabel("워크플로 이름", { exact: true })).toHaveValue(
    "Imported graph",
  );
  await node(page, "director").click();
  await expect(page.getByLabel("모델 ID", { exact: true })).toHaveValue(
    "arbitrary/model",
  );
  await expect(page.getByLabel("노드 프롬프트", { exact: true })).toHaveValue(
    "round trip",
  );
});
test("invalid imports are rejected without losing the current graph", async ({
  page,
}) => {
  const valid = await exportGraph(page);
  const bads = [
    { version: 2 },
    { ...valid, nodes: [...valid.nodes, valid.nodes[0]] },
    {
      ...valid,
      edges: [
        ...valid.edges,
        { id: "cycle", source: "motion", target: "analysis" },
      ],
    },
    {
      ...valid,
      edges: [{ id: "missing", source: "nobody", target: "motion" }],
    },
    {
      ...valid,
      nodes: [
        { ...valid.nodes[0], data: { ...valid.nodes[0].data, temperature: 5 } },
      ],
    },
  ];
  for (const bad of bads) {
    await importGraph(page, bad);
    await expect(page.getByRole("status")).toBeVisible();
    await expect(page.locator(".react-flow__node")).toHaveCount(6);
  }
  await page
    .locator("input[type=file]")
    .first()
    .setInputFiles({
      name: "large.json",
      mimeType: "application/json",
      buffer: Buffer.alloc(2_000_001),
    });
  await expect(page.getByRole("status")).toContainText("2MB");
});
test("empty workflow can be imported and rebuilt", async ({ page }) => {
  await importGraph(page, { version: 1, title: "Empty", nodes: [], edges: [] });
  await expect(page.locator(".react-flow__node")).toHaveCount(0);
  await expect(page.getByText("첫 노드부터 시작해 보세요.")).toBeVisible();
  await page
    .getByRole("button", { name: "실행 계획", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("button", { name: "실행 계획 내보내기", exact: true }),
  ).toBeDisabled();
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "원본 영상 추가", exact: true })
    .click();
  await expect(page.locator(".react-flow__node")).toHaveCount(1);
});
test("100-node limit is enforced on import and interactive addition", async ({
  page,
}) => {
  const w = await exportGraph(page);
  w.nodes = Array.from({ length: 100 }, (_, i) => ({
    ...w.nodes[0],
    id: `node-${i}`,
    position: { x: i * 30, y: i * 10 },
  }));
  w.edges = [];
  await importGraph(page, w);
  await expect(page.locator(".react-flow__node")).toHaveCount(100);
  await page.locator(".library-item").filter({ hasText: "영역 편집" }).click();
  await expect(page.getByRole("status")).toContainText("100");
  await expect(page.locator(".react-flow__node")).toHaveCount(100);
});
test("execution plan preserves prompts, dependency order and backend limitations", async ({
  page,
}) => {
  await page
    .getByLabel("노드 프롬프트", { exact: true })
    .fill("my execution prompt");
  await page
    .getByRole("button", { name: "실행 계획", exact: true })
    .first()
    .click();
  await expect(page.getByRole("dialog")).toContainText(
    "실제 생성이나 과금 없이",
  );
  await expect(page.locator(".plan-step")).toHaveCount(6);
  await page.locator(".plan-warnings summary").click();
  await expect(page.locator(".plan-warnings")).toContainText(
    "프롬프트 입력을 지원하지",
  );
  const waiting = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "실행 계획 내보내기", exact: true })
    .click();
  const download = await waiting;
  const { readFile } = await import("node:fs/promises");
  const plan = JSON.parse(await readFile((await download.path())!, "utf8"));
  const director = plan.steps.find((n: any) => n.node_id === "director");
  expect(director.prompt).toBe("my execution prompt");
  for (const step of plan.steps)
    for (const dependency of step.input_nodes)
      expect(
        plan.steps.findIndex((s: any) => s.node_id === dependency),
      ).toBeLessThan(plan.steps.indexOf(step));
});
test("missing model and missing output block plan export", async ({ page }) => {
  await page.getByLabel("모델 ID", { exact: true }).fill("");
  await page
    .getByRole("button", { name: "실행 계획", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("button", { name: "실행 계획 내보내기", exact: true }),
  ).toBeDisabled();
  await expect(page.locator(".plan-errors")).toContainText("모델 ID");
  await page.keyboard.press("Escape");
  await node(page, "output").click();
  await page
    .getByRole("button", { name: "선택한 노드 삭제", exact: true })
    .click();
  await page
    .getByRole("button", { name: "실행 계획", exact: true })
    .first()
    .click();
  await expect(page.locator(".plan-errors")).toContainText("결과 내보내기");
});
test("media file validation, preview and session-only restoration", async ({
  page,
}) => {
  await node(page, "reference").click();
  const input = page.locator("input[type=file]").nth(1);
  await input.setInputFiles({
    name: "not-image.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("wrong"),
  });
  await expect(page.getByRole("status")).toContainText("이미지 파일");
  await expect(page.locator(".asset-preview")).toHaveCount(0);
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII=",
    "base64",
  );
  await input.setInputFiles({
    name: "reference.png",
    mimeType: "image/png",
    buffer: png,
  });
  await expect(page.locator(".asset-preview")).toHaveAttribute("src", /^blob:/);
  await expect
    .poll(() =>
      page
        .locator("img.asset-preview")
        .evaluate((i: HTMLImageElement) => i.naturalWidth),
    )
    .toBeGreaterThan(0);
  await saved(page);
  await page.reload();
  await node(page, "reference").click();
  await expect(page.locator(".upload-zone")).toContainText("reference.png");
  await expect(page.locator(".asset-preview")).toHaveCount(0);
  await expect(
    page.getByText("파일은 서버로 업로드되지 않습니다.", { exact: false }),
  ).toBeVisible();
});
test("new workflow supports cancel, reset and undo", async ({ page }) => {
  await page.getByLabel("노드 프롬프트", { exact: true }).fill("keep this");
  await page.getByRole("button", { name: "새 워크플로", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "취소", exact: true })
    .click();
  await expect(page.getByLabel("노드 프롬프트", { exact: true })).toHaveValue(
    "keep this",
  );
  await page.getByRole("button", { name: "새 워크플로", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "새 워크플로", exact: true })
    .click();
  await page.getByRole("button", { name: "되돌리기", exact: true }).click();
  await node(page, "director").click();
  await expect(page.getByLabel("노드 프롬프트", { exact: true })).toHaveValue(
    "keep this",
  );
});
test("unavailable browser storage is visible and export remains possible", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Storage.prototype.setItem = function () {
      throw new DOMException("blocked", "SecurityError");
    };
  });
  await page.reload();
  await expect(page.locator(".save-status")).toContainText("저장 실패");
  const w = await exportGraph(page);
  expect(w.nodes).toHaveLength(6);
});
test("corrupted stored JSON recovers a usable default canvas", async ({
  page,
}) => {
  await page.addInitScript(
    (key) => localStorage.setItem(key, "{not-json"),
    store,
  );
  await page.reload();
  await expect(page.locator(".react-flow__node")).toHaveCount(6);
  await page.getByLabel("모델 ID", { exact: true }).fill("recovered/model");
  await saved(page);
  const w = await page.evaluate(
    (key) => JSON.parse(localStorage.getItem(key)!),
    store,
  );
  expect(w.nodes.find((n: any) => n.id === "director").data.model).toBe(
    "recovered/model",
  );
});
test("blank names and longest allowed names round-trip without resetting", async ({
  page,
}) => {
  await page.getByLabel("워크플로 이름", { exact: true }).fill("");
  await page.getByLabel("노드 이름", { exact: true }).fill("");
  await saved(page);
  await page.reload();
  await expect(page.getByLabel("워크플로 이름", { exact: true })).toHaveValue(
    "Untitled workflow",
  );
  await expect(page.getByLabel("노드 이름", { exact: true })).toHaveValue(
    "프롬프트 설계",
  );
  await page.getByLabel("노드 이름", { exact: true }).fill("N".repeat(120));
  await page.getByRole("button", { name: "복제", exact: true }).click();
  await saved(page);
  await page.reload();
  await expect(page.locator(".react-flow__node")).toHaveCount(7);
});
test("desktop editor and help modal meet automated WCAG AA checks", async ({
  page,
}) => {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(result.violations).toEqual([]);
  await page.getByRole("button", { name: "도움말 열기", exact: true }).click();
  const modal = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(modal.violations).toEqual([]);
});
test("desktop view fits common viewport widths", async ({ page }) => {
  for (const width of [1024, 1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBe(width);
    await expect(
      page.getByRole("button", { name: "실행 계획", exact: true }).first(),
    ).toBeVisible();
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page
    .getByRole("button", { name: "전체 노드 보기", exact: true })
    .click();
  await page.waitForTimeout(450);
  await page.screenshot({
    path: "test-results/desktop-studio.png",
    fullPage: true,
  });
});

test("all inspector variants and execution/reset dialogs pass automated accessibility checks", async ({
  page,
}) => {
  for (const id of ["source", "reference", "analysis", "motion", "output"]) {
    await node(page, id).click();
    const result = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(result.violations, `inspector ${id}`).toEqual([]);
  }
  await node(page, "director").click();
  await page.getByLabel("API 공급자", { exact: true }).selectOption("custom");
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page
    .getByRole("button", { name: "실행 계획", exact: true })
    .first()
    .click();
  await page.locator(".plan-warnings summary").click();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "새 워크플로", exact: true }).click();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
});

test("a real video file loads and can play in the media preview", async ({
  page,
}) => {
  const bytes = await page.evaluate(async () => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 64;
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = "green";
    ctx.fillRect(0, 0, 64, 64);
    const stream = canvas.captureStream(10);
    const recorder = new MediaRecorder(stream, { mimeType: "video/webm" });
    const chunks: Blob[] = [];
    recorder.ondataavailable = (e) => chunks.push(e.data);
    const result = new Promise<number[]>((resolve) => {
      recorder.onstop = async () =>
        resolve(
          Array.from(new Uint8Array(await new Blob(chunks).arrayBuffer())),
        );
    });
    recorder.start();
    await new Promise((resolve) => setTimeout(resolve, 600));
    recorder.stop();
    stream.getTracks().forEach((track) => track.stop());
    return result;
  });
  await node(page, "source").click();
  await page
    .locator("input[type=file]")
    .nth(1)
    .setInputFiles({
      name: "motion.webm",
      mimeType: "video/webm",
      buffer: Buffer.from(bytes),
    });
  const preview = page.locator("video.asset-preview");
  await expect
    .poll(() => preview.evaluate((v: HTMLVideoElement) => v.readyState))
    .toBeGreaterThanOrEqual(2);
  await preview.evaluate((v: HTMLVideoElement) => v.play());
  await expect
    .poll(() => preview.evaluate((v: HTMLVideoElement) => v.currentTime))
    .toBeGreaterThan(0);
});
