import { expect, test } from "@playwright/test";
import { login, open } from "./helpers";
import { API_URL } from "./ports";

/** Students never reach lecturer pages; the server refuses lecturer routes too (the page hiding them is not the check). */
test.describe("role checks", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, "Sam Patel");
  });

  test("a student has no review or upload links", async ({ page }) => {
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "Lectures" })).toBeVisible();
    await expect(nav.getByRole("link", { name: /Review queue/ })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Upload lecture" })).toHaveCount(0);
    await expect(page.getByLabel("Choose a lecture video")).toHaveCount(0);
  });

  for (const path of ["/review", "/upload"]) {
    test(`a student opening ${path} is sent back to the lectures`, async ({ page }) => {
      await open(page, path);
      await expect(page).toHaveURL(/\/lectures$/);
      await expect(page.getByRole("heading", { name: "Lectures" })).toBeVisible();
    });
  }

  test("the API refuses lecturer routes for a student", async ({ page }) => {
    // page.request shares the browser's session cookie.
    const review = await page.request.get(`${API_URL}/review`);
    expect(review.status()).toBe(403);
    const upload = await page.request.post(`${API_URL}/uploads`, { data: { filename: "x.mp4", size_bytes: 10, title: "x" } });
    expect(upload.status()).toBe(403);
    const decision = await page.request.post(`${API_URL}/review/bullet:bul_x/decision`, { data: { decision: "approve" } });
    expect(decision.status()).toBe(403);
  });
});
