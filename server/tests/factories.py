"""Hand-built API objects for tests (no database needed)."""

from datetime import UTC, datetime

from app.contracts.ai import BoardBlock, SaidNotWritten, TimeRange
from app.contracts.api import Bullet, LectureDetail, LectureSummary, Section
from app.contracts.enums import BlockType, LectureStatus, SectionStatus


def bullet(
    id: str,
    order: int,
    text: str,
    latex: str | None = None,
    ranges: list[tuple[float, float]] | None = None,
    blocks: list[str] | None = None,
    uncertain: bool = False,
) -> Bullet:
    return Bullet(
        id=id,
        order=order,
        text=text,
        latex=latex,
        confidence=0.6 if uncertain else 0.95,
        uncertain=uncertain,
        board_block_ids=blocks or [],
        transcript_ranges=[TimeRange(start_s=a, end_s=b) for a, b in (ranges or [])],
        open_suggestions=0,
    )


def sample_lecture(status: LectureStatus = LectureStatus.IN_REVIEW, title: str = "Linear Algebra · Lecture 21") -> LectureDetail:
    return LectureDetail(
        summary=LectureSummary(
            id="lec_21",
            title=title,
            duration_s=3000.0,
            section_count=2,
            status=status,
            open_items=1,
            progress=None,
            uploaded_at=datetime(2026, 11, 12, 9, 0, tzinfo=UTC),
        ),
        sections=[
            Section(
                id="s_4",
                order=2,
                heading="Trace & determinant",
                start_s=2500.0,
                end_s=2800.0,
                status=SectionStatus.DRAFT,
                bullets=[
                    bullet(
                        "b_4_1",
                        1,
                        "The sum of the eigenvalues equals the trace:",
                        r"\lambda_1 + \cdots + \lambda_n = \operatorname{tr}(A)",
                        [(2512.0, 2530.0)],
                    ),
                    bullet("b_4_2", 2, "Watch out: <script>alert('x')</script> & 50% of #cases_{1}", None, None, ["blk_7"], uncertain=True),
                ],
                said_not_written=[SaidNotWritten(text="For a triangular matrix the eigenvalues are on the diagonal.", at_s=2700.0)],
            ),
            Section(
                id="s_3",
                order=1,
                heading="The characteristic equation",
                start_s=2000.0,
                end_s=2500.0,
                status=SectionStatus.VERIFIED,
                bullets=[
                    bullet(
                        "b_3_1",
                        1,
                        "λ is an eigenvalue of A exactly when A − λI has no inverse:",
                        r"\det(A - \lambda I) = 0",
                        [(2050.0, 2064.0), (2010.5, 2020.0)],
                    ),
                    bullet("b_3_2", 2, "Its roots are the eigenvalues.", None, None, ["blk_2"]),
                ],
                said_not_written=[],
            ),
        ],
        board_blocks=[
            BoardBlock(
                id="blk_2",
                type=BlockType.TEXT,
                text="roots = eigenvalues",
                latex=None,
                confidence=0.9,
                first_seen_s=2142.0,
                best_frame_s=2150.0,
                bbox=[0.1, 0.1, 0.5, 0.2],
            ),
            BoardBlock(
                id="blk_7",
                type=BlockType.TEXT,
                text="watch out",
                latex=None,
                confidence=0.6,
                first_seen_s=2590.0,
                best_frame_s=2600.0,
                bbox=[0.1, 0.3, 0.5, 0.4],
            ),
        ],
        video_url="https://example.org/media/lec_21.mp4",
        pdf_url=None,
    )
