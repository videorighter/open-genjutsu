import { test, expect, request } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
const config = Object.fromEntries(
  readFileSync(".env", "utf8")
    .split("\n")
    .filter((line) => line && !line.startsWith("#"))
    .map((line) => {
      const i = line.indexOf("=");
      return [line.slice(0, i), line.slice(i + 1)];
    }),
);
test.use({ trace: "off" });
test.describe("operator dashboard", () => {
  test("administrator can inspect real operational metrics", async ({
    page,
    baseURL,
  }) => {
    const admin = await request.newContext({ baseURL });
    try {
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
      await page.context().clearCookies();
      await page.context().addCookies((await admin.storageState()).cookies);
      await page.goto("/");
      await page
        .getByRole("button", { name: "운영 현황", exact: true })
        .click();
      await expect(
        page.getByText("Temporal 연결", { exact: true }),
      ).toBeVisible();
      await expect(page.locator(".operations-metrics")).toContainText("연결됨");
      await expect(page.locator(".operations-panel")).toContainText(
        "확인 대기 작업이 없습니다.",
      );
      await expect(page.locator(".operations-panel [role=alert]")).toHaveCount(
        0,
      );
      const accessibility = await new AxeBuilder({ page })
        .include(".service-dialog")
        .withTags(["wcag2a", "wcag2aa"])
        .analyze();
      expect(accessibility.violations).toEqual([]);
    } finally {
      await admin.dispose();
    }
  });
});
