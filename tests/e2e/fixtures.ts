import { test as base, expect } from "@playwright/test";
export { expect };
export const test = base.extend<{ browserErrors: void }>({
  browserErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(message.text());
      });
      await use();
      expect(errors, "Browser console and uncaught runtime errors").toEqual([]);
    },
    { auto: true },
  ],
});
