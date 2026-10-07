import { test, expect } from "./fixtures";
import AxeBuilder from "@axe-core/playwright";
test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".react-flow__node")).toHaveCount(6);
});
test("touch library addition and model/prompt editing persist", async ({
  page,
}) => {
  await page
    .getByRole("button", { name: "노드 라이브러리 열기", exact: true })
    .tap();
  await page.locator(".library-item").filter({ hasText: "영역 편집" }).tap();
  await expect(page.locator(".library")).toHaveCount(0);
  await expect(page.locator(".react-flow__node")).toHaveCount(7);
  await page.getByLabel("모델 ID", { exact: true }).fill("mobile/my-model");
  await page
    .getByLabel("노드 프롬프트", { exact: true })
    .fill("모바일 프롬프트");
  await page.waitForTimeout(650);
  await page.reload();
  await page.getByRole("button", { name: "노드 설정 열기", exact: true }).tap();
  const w = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("open-genjutsu.workflow.v1")!),
  );
  expect(
    w.nodes.some(
      (n: any) =>
        n.data.prompt === "모바일 프롬프트" &&
        n.data.model === "mobile/my-model",
    ),
  ).toBe(true);
});
test("drawers close and reopen and search is usable by touch", async ({
  page,
}) => {
  await page.getByRole("button", { name: "노드 설정 열기", exact: true }).tap();
  await page.getByRole("button", { name: "노드 설정 접기", exact: true }).tap();
  await page
    .getByRole("button", { name: "노드 라이브러리 열기", exact: true })
    .tap();
  await page.getByLabel("노드 검색", { exact: true }).fill("motion");
  await expect(page.locator(".library-item")).toHaveCount(1);
  await page
    .getByRole("button", { name: "노드 라이브러리 접기", exact: true })
    .tap();
  await expect(page.locator(".library")).toHaveCount(0);
});
test("mobile execution plan and help dialogs remain usable", async ({
  page,
}) => {
  await page
    .getByRole("button", { name: "실행 계획", exact: true })
    .first()
    .tap();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "실행 계획 내보내기", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "대화상자 닫기", exact: true }).tap();
  await page.getByRole("button", { name: "도움말 열기", exact: true }).tap();
  await page.getByRole("button", { name: "만들기 시작", exact: true }).tap();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
test("mobile editor and opened inspector meet automated WCAG AA checks", async ({
  page,
}) => {
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.getByRole("button", { name: "노드 설정 열기", exact: true }).tap();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
});
test("narrow mobile and landscape widths do not overflow", async ({ page }) => {
  for (const width of [320, 360, 390, 430, 740]) {
    await page.setViewportSize({ width, height: 844 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBe(width);
    await expect(
      page.getByRole("button", { name: "실행 계획", exact: true }).first(),
    ).toBeVisible();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "test-results/mobile-studio.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "노드 설정 열기", exact: true }).tap();
  await page.screenshot({
    path: "test-results/mobile-inspector.png",
    fullPage: true,
  });
});

test("mobile storage failure is visible and JSON can still be exported", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Storage.prototype.setItem = function () {
      throw new DOMException("blocked", "SecurityError");
    };
  });
  await page.reload();
  await expect(page.getByRole("status")).toContainText(
    "브라우저 저장에 실패했습니다",
  );
  const waiting = page.waitForEvent("download");
  await page.getByRole("button", { name: "내보내기", exact: true }).tap();
  expect((await waiting).suggestedFilename()).toMatch(/\.json$/);
});

test("mobile JSON import is available through the navigation rail", async ({
  page,
}) => {
  const chooser = page.waitForEvent("filechooser");
  await page
    .getByRole("button", { name: "JSON 워크플로 가져오기", exact: true })
    .tap();
  await (
    await chooser
  ).setFiles({
    name: "mobile.json",
    mimeType: "application/json",
    buffer: Buffer.from(
      JSON.stringify({
        version: 1,
        title: "Mobile imported",
        nodes: [],
        edges: [],
      }),
    ),
  });
  await expect(page.getByLabel("워크플로 이름", { exact: true })).toHaveValue(
    "Mobile imported",
  );
  await expect(page.locator(".react-flow__node")).toHaveCount(0);
});
