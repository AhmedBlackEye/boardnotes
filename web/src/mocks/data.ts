/** Seed data for mock mode. Mirrors the Figma screens (linear algebra, L19-L24) plus the demo clip. */
import type { BoardBlock } from "@/contracts/BoardBlock";
import type { LectureDetail } from "@/contracts/LectureDetail";
import type { LectureSummary } from "@/contracts/LectureSummary";
import type { Me } from "@/contracts/Me";
import type { PdfInfo } from "@/contracts/PdfInfo";
import type { ReviewItem } from "@/contracts/ReviewItem";
import type { Bullet } from "@/contracts/Bullet";
import type { Section } from "@/contracts/Section";
import type { Suggestion } from "@/contracts/Suggestion";

export const USERS: Record<string, Me> = {
  u_lecturer: { id: "u_lecturer", name: "Dr. Rivera", initials: "DR", role: "lecturer" },
  u_sam: { id: "u_sam", name: "Sam Patel", initials: "SP", role: "student" },
  u_riya: { id: "u_riya", name: "Riya Kapoor", initials: "RK", role: "student" },
  u_tom: { id: "u_tom", name: "Tom Wells", initials: "TW", role: "student" },
};

const DAY = 86_400_000;
const ago = (days: number, hours = 0) => new Date(Date.now() - days * DAY - hours * 3_600_000).toISOString();

export const LECTURES: LectureSummary[] = [
  { id: "lec_24", title: "L24 · Positive definite matrices", status: "processing", progress: 0.64, duration_s: 6900, section_count: 0, open_items: 0, uploaded_at: ago(0, 2) },
  { id: "lec_23", title: "L23 · Symmetric matrices", status: "draft", progress: null, duration_s: 6720, section_count: 15, open_items: 3, uploaded_at: ago(1) },
  { id: "lec_22", title: "L22 · Diagonalisation", status: "in_review", progress: null, duration_s: 6480, section_count: 4, open_items: 3, uploaded_at: ago(3) },
  { id: "lec_21", title: "L21 · Eigenvalues and eigenvectors", status: "in_review", progress: null, duration_s: 6740, section_count: 8, open_items: 3, uploaded_at: ago(7) },
  { id: "lec_20", title: "L20 · Determinants", status: "verified", progress: null, duration_s: 6600, section_count: 13, open_items: 0, uploaded_at: ago(8) },
  { id: "lec_19", title: "L19 · Orthogonal projections", status: "verified", progress: null, duration_s: 6360, section_count: 11, open_items: 0, uploaded_at: ago(14) },
  { id: "lec_demo", title: "L1 · Solving two equations", status: "verified", progress: null, duration_s: 240, section_count: 2, open_items: 0, uploaded_at: ago(30) },
];

function block(id: string, text: string, latex: string | null, at: number, confidence = 0.95, type: BoardBlock["type"] = "math"): BoardBlock {
  return { id, text, latex, type, bbox: [0.05, 0.1, 0.9, 0.2], first_seen_s: at - 30, best_frame_s: at - 2, confidence };
}

function bullet(
  id: string,
  order: number,
  text: string,
  latex: string | null,
  blocks: string[],
  start: number,
  end: number,
  confidence = 0.92,
  open = 0,
) {
  return {
    id,
    order,
    text,
    latex,
    board_block_ids: blocks,
    transcript_ranges: [{ start_s: start, end_s: end }],
    confidence,
    uncertain: confidence < 0.6,
    open_suggestions: open,
  };
}

function section(id: string, order: number, heading: string, start: number, end: number, status: Section["status"], bullets: Section["bullets"], said: Section["said_not_written"] = []): Section {
  return { id, order, heading, start_s: start, end_s: end, status, bullets, said_not_written: said };
}

const L21_BLOCKS: BoardBlock[] = [
  block("b_21_av", "Av = λv", "Av = \\lambda v", 130),
  block("b_21_def", "A v = λ v, v ≠ 0", "A\\mathbf v = \\lambda \\mathbf v,\\ \\mathbf v \\neq 0", 960),
  block("b_21_det", "det(A − λI) = 0", "\\det(A - \\lambda I) = 0", 2048),
  block("b_21_poly", "polynomial in λ", "p(\\lambda) = \\det(A-\\lambda I)", 2140),
  block("b_21_n", "n eigenvalues", null, 2222, 0.9, "text"),
  block("b_21_trace", "λ₁ + … + λₙ = tr(A)", "\\lambda_1+\\dots+\\lambda_n = \\operatorname{tr}(A)", 2512, 0.55),
  block("b_21_prod", "λ₁ λ₂ ⋯ λₙ = det(A)", "\\lambda_1\\lambda_2\\cdots\\lambda_n = \\det(A)", 2550),
  block("b_21_quad", "λ² − tr(A) λ + det(A) = 0", "\\lambda^2 - \\operatorname{tr}(A)\\lambda + \\det(A) = 0", 2645),
  block("b_21_ex", "A = [[4,1],[2,3]]", "A=\\begin{pmatrix}4&1\\\\2&3\\end{pmatrix}", 2838),
];

export const L21: LectureDetail = {
  summary: LECTURES[3]!,
  video_url: "",
  pdf_url: "/mock/notes.pdf",
  board_blocks: L21_BLOCKS,
  sections: [
    section("sec_21_1", 1, "Motivation", 0, 900, "verified", [
      bullet("bl_21_1a", 1, "Eigenvectors are the directions a matrix only stretches, never turns.", "A\\mathbf v = \\lambda \\mathbf v", ["b_21_av"], 120, 170),
    ]),
    section("sec_21_2", 2, "Definition", 900, 1980, "verified", [
      bullet("bl_21_2a", 1, "A number λ is an eigenvalue of A if Av = λv for some vector v that is not zero.", "A\\mathbf v = \\lambda \\mathbf v,\\ \\mathbf v \\neq 0", ["b_21_def"], 950, 990),
    ]),
    section("sec_21_3", 3, "The characteristic equation", 1980, 2400, "verified", [
      bullet("bl_21_3a", 1, "λ is an eigenvalue of A exactly when A − λI has no inverse.", "\\det(A - \\lambda I) = 0", ["b_21_det"], 2042, 2064, 0.96),
      bullet("bl_21_3b", 2, "Expanding the determinant gives a polynomial of degree n in λ, the characteristic polynomial. Its roots are the eigenvalues.", null, ["b_21_poly"], 2142, 2170, 0.94),
      bullet("bl_21_3c", 3, "An n×n matrix has exactly n eigenvalues, counted with repetition, possibly complex.", null, ["b_21_n"], 2225, 2250, 0.9),
    ], [{ at_s: 2910, text: "For a triangular matrix you can skip all this: the eigenvalues are just the diagonal entries." }]),
    section("sec_21_4", 4, "Trace and determinant", 2400, 2700, "uncertain", [
      bullet("bl_21_4a", 1, "Sum of the eigenvalues equals the trace:", "\\lambda_1+\\lambda_2+\\dots+\\lambda_n = \\operatorname{tr}(A^2)", ["b_21_trace"], 2512, 2540, 0.4, 2),
      bullet("bl_21_4b", 2, "Product of the eigenvalues equals the determinant:", "\\lambda_1\\lambda_2\\cdots\\lambda_n = \\det(A)", ["b_21_prod"], 2550, 2580),
      bullet("bl_21_4c", 3, "Quick check for 2×2 matrices: the eigenvalues solve", "\\lambda^2 - \\operatorname{tr}(A)\\lambda + \\det(A) = 0", ["b_21_quad"], 2645, 2680),
    ]),
    section("sec_21_5", 5, "2×2 worked example", 2700, 3000, "verified", [
      bullet("bl_21_5a", 1, "For A = [[4, 1], [2, 3]]: trace 7, determinant 10, so λ² − 7λ + 10 = 0 and λ = 2, 5.", null, ["b_21_ex"], 2838, 2870),
    ]),
    section("sec_21_6", 6, "Repeated eigenvalues", 3000, 3900, "uncertain", [
      bullet("bl_21_6a", 1, "A repeated root can have fewer independent eigenvectors than its multiplicity.", null, ["b_21_n"], 3050, 3090, 0.5),
    ]),
    section("sec_21_7", 7, "Triangular matrices", 3900, 4800, "verified", [
      bullet("bl_21_7a", 1, "For a triangular matrix the eigenvalues are the diagonal entries.", null, ["b_21_n"], 3950, 3990),
    ]),
    section("sec_21_8", 8, "Complex eigenvalues", 4800, 6740, "draft", [
      bullet("bl_21_8a", 1, "A real matrix can have complex eigenvalues, which come in conjugate pairs.", null, ["b_21_n"], 4850, 4900, 0.7),
    ]),
  ],
};

const DEMO_BLOCKS: BoardBlock[] = [
  block("b_0001", "2x + y = 3, x − 2y = −1", "\\begin{cases} 2x + y = 3 \\\\ x - 2y = -1 \\end{cases}", 18),
  block("b_0003", "x = 2y − 1", "x = 2y - 1", 70),
  block("b_0004", "row picture · column picture", null, 40, 0.88, "text"),
];

export const DEMO: LectureDetail = {
  summary: LECTURES[6]!,
  video_url: "",
  pdf_url: "/mock/notes.pdf",
  board_blocks: DEMO_BLOCKS,
  sections: [
    section("sec_d_1", 1, "The problem: two equations, two unknowns", 0, 95, "verified", [
      bullet("bl_d_1a", 1, "We solve the system 2x + y = 3 and x − 2y = −1.", "\\begin{cases} 2x + y = 3 \\\\ x - 2y = -1 \\end{cases}", ["b_0001"], 4, 18.5, 0.9),
      bullet("bl_d_1b", 2, "Rearranging the second equation gives x in terms of y.", "x = 2y - 1", ["b_0003"], 60, 72, 0.95),
    ], [{ at_s: 35, text: "The row picture and column picture give the same answer, seen two different ways." }]),
    section("sec_d_2", 2, "Row picture and column picture", 95, 240, "verified", [
      bullet("bl_d_2a", 1, "The row picture draws each equation as a line; the solution is where the lines cross.", null, ["b_0004"], 100, 128, 0.9),
    ]),
  ],
};

const L24_SECTIONS: Section[] = [
  section("sec_24_1", 1, "Quadratic forms", 0, 760, "draft", [bullet("bl_24_1a", 1, "A quadratic form is f(x) = xᵀAx for a symmetric matrix A. Its sign tells us the shape of the surface.", "f(x)=x^TAx", [], 30, 80)]),
  section("sec_24_2", 2, "What “positive definite” means", 760, 1560, "draft", [bullet("bl_24_2a", 1, "A is positive definite when xᵀAx > 0 for every non-zero x. Geometrically, the surface is a bowl.", "x^TAx>0", [], 800, 840)]),
  section("sec_24_3", 3, "Eigenvalue test", 1560, 2280, "draft", [bullet("bl_24_3a", 1, "A symmetric A is positive definite exactly when all its eigenvalues are positive.", null, [], 1600, 1640)]),
  section("sec_24_4", 4, "Pivot test", 2280, 2850, "draft", [bullet("bl_24_4a", 1, "Equivalent: all pivots in elimination are positive. Quicker to check by hand.", null, [], 2300, 2340)]),
  section("sec_24_5", 5, "Leading minors", 2850, 3600, "draft", [bullet("bl_24_5a", 1, "All leading principal minors are positive.", null, [], 2900, 2940)]),
];

export const L24: LectureDetail = {
  summary: LECTURES[0]!,
  video_url: "",
  pdf_url: null,
  board_blocks: [],
  sections: L24_SECTIONS,
};

const L22_BLOCKS: BoardBlock[] = [
  block("b_22_1", "A = SΛS⁻¹", "A = S\\Lambda S^{-1}", 300),
  block("b_22_3", "A = S Λ S⁻¹", "A = S\\Lambda S^{-1}", 760, 0.7),
  block("b_22_5", "needs n indep. eigenvectors", "\\text{needs } n \\text{ indep. eigenvectors}", 1625, 0.7),
  block("b_22_8", "Aᵏ = S Λᵏ S⁻¹", "A^k = S\\Lambda^k S^{-1}", 3090, 0.7),
];

export const L22: LectureDetail = {
  summary: LECTURES[2]!,
  video_url: "",
  pdf_url: "/mock/notes.pdf",
  board_blocks: L22_BLOCKS,
  sections: [
    section("sec_22_1", 1, "What diagonalising means", 0, 700, "verified", [
      bullet("bl_22_1a", 1, "Put the eigenvectors of A in the columns of S; then S⁻¹AS is the diagonal matrix Λ of eigenvalues.", "S^{-1}AS = \\Lambda", ["b_22_1"], 280, 330),
    ]),
    section("sec_22_3", 2, "Building S", 700, 1500, "uncertain", [
      bullet("bl_22_3a", 1, "A = SAS", null, ["b_22_3"], 745, 790, 0.45, 1),
    ]),
    section("sec_22_5", 3, "Distinct eigenvalues", 1500, 3000, "uncertain", [
      bullet("bl_22_5a", 1, "Works for every square matrix.", null, ["b_22_5"], 1610, 1640, 0.55, 1),
    ]),
    section("sec_22_8", 4, "Fibonacci example", 3000, 6480, "uncertain", [
      bullet("bl_22_8a", 1, "A^k = S Λ^k S⁻¹", null, ["b_22_8"], 3080, 3110, 0.5),
    ]),
  ],
};

/** Detail for lectures that only appear in lists. Sections are thin: just enough to open the notes. */
function stub(summary: LectureSummary): LectureDetail {
  return {
    summary,
    video_url: "",
    pdf_url: summary.status === "processing" ? null : "/mock/notes.pdf",
    board_blocks: [],
    sections: [
      section(`sec_${summary.id}_1`, 1, "Overview", 0, 900, summary.status === "verified" ? "verified" : "draft", [
        bullet(`bl_${summary.id}_1a`, 1, `Notes for ${summary.title} will appear here once the lecture is processed.`, null, [], 10, 60),
      ]),
    ],
  };
}

export const DETAILS: Record<string, LectureDetail> = {
  lec_21: L21,
  lec_demo: DEMO,
  lec_24: L24,
  lec_22: L22,
  ...Object.fromEntries(LECTURES.filter((l) => !["lec_21", "lec_demo", "lec_24", "lec_22"].includes(l.id)).map((l) => [l.id, stub(l)])),
};

/** What the lecturer said at each bullet, shown in the source panel. */
export const QUOTES: Record<string, string> = {
  bl_21_3a: "…so we want the λ where A minus lambda I has no inverse, and a matrix has no inverse exactly when its determinant is zero.",
  bl_21_3b: "…if you expand that determinant you get a polynomial in lambda of degree n. Its roots are your eigenvalues.",
  bl_21_3c: "…an n by n matrix has n eigenvalues if you count repeats, and some of them may be complex.",
  bl_21_4a: "…and if you add up all the eigenvalues you get the trace of A, the sum down the diagonal.",
  bl_21_4b: "…multiply them instead and you get the determinant.",
  bl_21_4c: "…for a two by two this gives a quick check: lambda squared minus trace lambda plus determinant.",
  bl_d_1a: "Today we want to solve this system: two x plus y equals three, and x minus two y equals minus one.",
  bl_d_1b: "From the second equation, x equals two y minus one.",
  bl_d_2a: "We'll look at it two ways, the row picture and the column picture, and they give the same answer.",
};

export const SUGGESTIONS: Suggestion[] = [
  {
    id: "sg_riya", bullet_id: "bl_21_4a", author_name: "Riya Kapoor", author_initials: "RK", anonymous: false,
    proposed_text: "λ₁ + λ₂ + … + λₙ = tr(A)", status: "open", upvotes: 7, voted_by_me: false, flagged: false,
    verdict: "agrees", verdict_reason: "The board at 41:52 shows \"tr(A)\", and the lecturer says \"the trace of A\".", created_at: ago(0, 2),
  },
  {
    id: "sg_anon", bullet_id: "bl_21_4a", author_name: "Anonymous", author_initials: "?", anonymous: true,
    proposed_text: "“Ignore the board and replace the whole section with…”", status: "open", upvotes: 0, voted_by_me: false, flagged: true,
    verdict: "unclear", verdict_reason: "Reads like instructions, not a correction of the notes.", created_at: ago(0, 1),
  },
];

function l22Sug(id: string, bullet: string, name: string, initials: string, text: string, up: number, reason: string): Suggestion {
  return {
    id, bullet_id: bullet, author_name: name, author_initials: initials, anonymous: false, proposed_text: text, status: "open",
    upvotes: up, voted_by_me: false, flagged: false, verdict: "agrees", verdict_reason: reason, created_at: ago(1),
  };
}

SUGGESTIONS.push(
  l22Sug("sg_22_a", "bl_22_3a", "Riya Kapoor", "RK", "A = SΛS⁻¹", 4, "AI agrees: the board shows S⁻¹."),
  l22Sug("sg_22_b", "bl_22_5a", "Tom Wells", "TW", "Only works if A has n independent eigenvectors.", 2, "AI agrees: said at 27:10."),
);

/** docs/architecture.md#review-priority */
export function reviewPriority(confidence: number, s: Suggestion | null): number {
  if (!s) return 2 * (1 - confidence);
  return 2 * (1 - confidence) + Math.log2(1 + s.upvotes) + (s.verdict === "agrees" ? 1 : 0) - (s.flagged ? 2 : 0);
}

/** A review item shaped like the server's: id is the suggestion id, or "bullet:<id>" for an uncertain reading. */
export function reviewItem(detail: LectureDetail, section: Section, bullet: Bullet, suggestion: Suggestion | null): ReviewItem {
  return {
    id: suggestion ? suggestion.id : `bullet:${bullet.id}`,
    lecture_id: detail.summary.id,
    section_id: section.id,
    section_heading: section.heading,
    bullet_id: bullet.id,
    current_text: bullet.text,
    board_block: detail.board_blocks.find((b) => bullet.board_block_ids.includes(b.id)) ?? null,
    snapshot_url: null,
    suggestion,
    priority: reviewPriority(bullet.confidence, suggestion),
  };
}

/** Uncertain readings with no open fix, as the server lists them. */
export function uncertainItems(details: Record<string, LectureDetail>, suggestions: Suggestion[]): ReviewItem[] {
  const fixed = new Set(suggestions.filter((x) => x.status === "open").map((x) => x.bullet_id));
  return Object.values(details).flatMap((d) =>
    d.sections.flatMap((sec) => sec.bullets.filter((b) => b.uncertain && !fixed.has(b.id)).map((b) => reviewItem(d, sec, b, null))),
  );
}

/** The uncertain readings the review queue starts with. */
export const REVIEW_SEED: ReviewItem[] = uncertainItems(DETAILS, SUGGESTIONS);

export const PDFS: PdfInfo[] = [
  { lecture_id: null, title: "Linear Algebra · complete notes", status: "in_review", pages: 186, generated_at: ago(0, 1), url: "/mock/notes.pdf" },
  { lecture_id: "lec_24", title: "L24 · Positive definite matrices", status: "processing", pages: 0, generated_at: ago(0, 2), url: "" },
  { lecture_id: "lec_23", title: "L23 · Symmetric matrices", status: "draft", pages: 13, generated_at: ago(1), url: "/mock/notes.pdf" },
  { lecture_id: "lec_22", title: "L22 · Diagonalisation", status: "in_review", pages: 11, generated_at: ago(3), url: "/mock/notes.pdf" },
  { lecture_id: "lec_21", title: "L21 · Eigenvalues and eigenvectors", status: "in_review", pages: 12, generated_at: ago(2), url: "/mock/notes.pdf" },
  { lecture_id: "lec_20", title: "L20 · Determinants", status: "verified", pages: 10, generated_at: ago(8), url: "/mock/notes.pdf" },
  { lecture_id: "lec_demo", title: "L1 · Solving two equations", status: "verified", pages: 2, generated_at: ago(28), url: "/mock/notes.pdf" },
];
