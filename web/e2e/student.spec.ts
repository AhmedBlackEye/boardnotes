import { expect, test } from "@playwright/test";
import type { LectureDetail } from "@/contracts/LectureDetail";
import { apiAs, expectPdf, login, suggestViaApi, uploadLectureViaApi } from "./helpers";

const TITLE = "Student flow lecture";
let lecture: LectureDetail;
let bulletId: string;
const RIYA_FIX = "x = 2y - 1 (Riya's reading)";

test.beforeAll(async () => {
  // A processed lecture, and one fix from another student (Riya) on its first point for Sam to upvote.
  const lecturer = await apiAs("u_lecturer");
  lecture = await uploadLectureViaApi(lecturer, TITLE);
  await lecturer.dispose();
  bulletId = lecture.sections[0].bullets[0].id;
  const riya = await apiAs("u_riya");
  await suggestViaApi(riya, bulletId, RIYA_FIX);
  await riya.dispose();
});

/** Student flow from the Figma prototype: notes -> source -> suggest a fix -> upvote -> ask -> course notes. */
test("student reads the notes, suggests and upvotes fixes, asks the lecture and gets the course PDF", async ({ page }) => {
  await login(page, "Sam Patel");

  // Open the lecture's notes from the list.
  await page.getByRole("link", { name: new RegExp(TITLE) }).first().click();
  await expect(page).toHaveURL(new RegExp(`/lectures/${lecture.summary.id}$`));
  const notes = page.getByTestId("notes");
  const first = notes.getByTestId("note-bullet").first();
  await expect(first).toContainText(lecture.sections[0].bullets[0].text);

  // Open a source: the video, the board and what was said.
  await first.click();
  const panel = page.getByRole("complementary", { name: "Source" });
  await expect(panel).toBeVisible();
  await expect(panel.getByText(/The lecturer said/)).toBeVisible();

  // Suggest a fix and see the AI check.
  await panel.getByRole("button", { name: "Suggest a fix" }).click();
  const fix = page.getByRole("complementary", { name: "Suggest a fix" });
  await fix.getByLabel("Your fix").fill("We solve the system 2x + y = 3 and x - 2y = -1 (corrected)");
  await fix.getByRole("button", { name: "Send to lecturer" }).click();
  await expect(fix.getByRole("status")).toContainText(/AI (agrees|disagrees|is not sure)/);

  // Upvote Riya's fix on the same point.
  const riyas = fix.getByTestId("suggestion-card").filter({ hasText: RIYA_FIX });
  await expect(riyas).toContainText("Riya K.");
  const upvote = riyas.getByRole("button", { name: /Upvote/ });
  await expect(upvote).toHaveAttribute("aria-pressed", "false");
  await upvote.click();
  await expect(upvote).toHaveAttribute("aria-pressed", "true");
  await expect(upvote).toHaveAccessibleName("Upvote, 1 so far");

  // Ask the lecture: an answer with sources, or a clear "not covered" message.
  await page.getByRole("button", { name: "Ask the lecture" }).click();
  const ask = page.getByRole("complementary", { name: "Ask the lecture" });
  await ask.getByLabel("Your question").fill("What does the row picture show?");
  await ask.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(ask.getByText("What does the row picture show?")).toBeVisible();
  const answer = ask.getByText(/row picture draws each equation|isn.t covered|not covered/i);
  await expect(answer).toBeVisible();
  if (/row picture draws/i.test((await answer.textContent()) ?? "")) {
    // A covered answer cites at least one source (a timestamp or a board / section reference).
    await expect(ask.getByRole("button", { name: /^\d+:\d{2}$/ }).or(ask.getByText(/^(Section \d+|Board)/)).first()).toBeVisible();
  }

  // Course notes: the lecture's PDF is listed and downloads.
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Course notes" }).click();
  await expect(page).toHaveURL(/\/course-notes$/);
  await expect(page.getByRole("heading", { name: "Course notes" })).toBeVisible();
  const row = page.getByText(TITLE, { exact: true }).locator("xpath=ancestor::div[contains(@class,'border-t')][1]");
  await expect(row).toBeVisible();
  await expectPdf(page, await row.getByRole("link", { name: "Download" }).getAttribute("href"));
});
