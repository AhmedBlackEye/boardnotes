import path from "node:path";
import { expect, test } from "@playwright/test";
import { expectPdf, login, open } from "./helpers";
import { videoPath } from "./video";

/** Lecturer flow from the Figma prototype: upload -> processing -> notes -> review queue -> view as student -> PDF. */
test("lecturer uploads a lecture, reviews it and downloads the PDF", async ({ page }) => {
  await login(page, "Dr. Rivera");

  // Upload through the page (the drop zone's file input).
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Upload lecture" }).click();
  await expect(page).toHaveURL(/\/upload$/);
  await page.getByLabel("Choose a lecture video").setInputFiles(videoPath());
  await expect(page.getByTestId("upload-card")).toContainText(path.basename(videoPath()));

  // Processing page: the steps and the progress pill, until the notes are ready.
  await expect(page).toHaveURL(/\/lectures\/lec_[^/]+\/processing$/, { timeout: 60_000 });
  const lectureUrl = page.url().replace(/\/processing$/, "");
  const steps = page.getByTestId("steps");
  for (const title of ["Checked the video", "Listened to the lecture", "Reading the board", "Writing notes and PDF"]) {
    await expect(steps).toContainText(title);
  }
  // With fake models the job is quick, so it may already be finished when the page first draws.
  await expect(page.getByText(/^(Processing · \d+%|Ready for review)$/)).toBeVisible();
  await expect(page.getByText("Ready for review")).toBeVisible({ timeout: 120_000 });
  await expect(steps.getByText("Done", { exact: true })).toHaveCount(4);
  await expect(page.getByText(/^1 · /).first()).toBeVisible(); // the first section card

  // Notes appear, with the lecturer's review controls.
  await page.getByRole("button", { name: "Open notes to review" }).click();
  await expect(page).toHaveURL(lectureUrl);
  const notes = page.getByTestId("notes");
  await expect(notes.getByTestId("note-bullet").first()).toBeVisible();
  await expect(notes.getByRole("heading", { level: 2 }).first()).toHaveText(/^1 · /);
  await expect(page.getByRole("button", { name: "Approve lecture" })).toBeVisible();

  // Review queue: approve one uncertain reading ("Looks right"); the queue gets shorter.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: /Review queue/ }).click();
  await expect(page).toHaveURL(/\/review$/);
  const items = page.getByTestId("review-item");
  await expect(items.first()).toBeVisible();
  const before = await items.count();
  expect(before).toBeGreaterThan(0);
  await items.first().getByRole("button", { name: /^(Looks right|Approve)$/ }).click();
  await expect(items).toHaveCount(before - 1);

  // Back to the notes, preview them as a student, then download the PDF.
  await open(page, lectureUrl);
  await page.getByRole("button", { name: "View as student" }).click();
  await expect(page.getByRole("button", { name: "View as student" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "Ask the lecture" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve lecture" })).toHaveCount(0);
  const pdf = page.getByRole("link", { name: "Download PDF" });
  await expect(pdf).toBeVisible();
  await expectPdf(page, await pdf.getAttribute("href"));
});
