"""Q-4 end to end: the job runner redraws diagram blocks, stores the figure, keeps the crop; the API and PDF show it."""

import io
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image as PILImage
from pypdf import PdfReader

from app import repo
from app.config import Settings
from app.contracts.ai import BoardBlock, DiagramFigure
from app.contracts.enums import BlockType
from app.db import Pool
from app.jobs.runner import Stages, run_job
from app.llm.fake import FakeLLM
from app.pipeline import pdf
from app.pipeline.interfaces import FrameReading, Keyframe
from tests.conftest import Db
from tests.factories import sample_lecture
from tests.test_pdf import chromium_ok, pdf_text  # noqa: F401 - fixture
from tests.test_uploads_and_jobs import Calls, pool, queue_lecture  # noqa: F401 - fixture

DIAGRAM = BoardBlock(
    id="b_1", type=BlockType.DIAGRAM, text="two lines meeting at (1, 1)", latex=None, confidence=0.9,
    first_seen_s=5, best_frame_s=6, bbox=[0.1, 0.1, 0.5, 0.5],
)  # fmt: skip


def diagram_stages(calls: Calls, redraw: Any = None) -> Stages:
    PILImage.new("RGB", (640, 360), (40, 50, 55)).save(calls.frame, "JPEG")

    def merge_blocks(readings: list[FrameReading]) -> list[BoardBlock]:
        calls.hit("merge_blocks")
        return [DIAGRAM]

    stages = Stages(**{**calls.stages().__dict__, "merge_blocks": merge_blocks})
    return Stages(**{**stages.__dict__, "redraw_diagrams": redraw}) if redraw else stages


async def test_job_stores_figure_and_crop(pool: Pool, db: Db, settings: Settings, tmp_path: Path) -> None:  # noqa: F811
    calls = Calls(tmp_path)
    await queue_lecture(pool, db, settings)
    assert await run_job(pool, "lec_j", stages=diagram_stages(calls), llm=FakeLLM(), settings=settings)
    async with pool.connection() as conn:
        [stored] = await repo.board_blocks(conn, "lec_j")
    assert stored.figure is not None and stored.figure.kind == "chart" and stored.figure.redrawn_by_ai
    crop = settings.data_dir / "lectures" / "lec_j" / "snapshots" / "b_1.jpg"
    assert crop.is_file()


async def test_diagram_stage_failure_does_not_fail_the_job(pool: Pool, db: Db, settings: Settings, tmp_path: Path) -> None:  # noqa: F811
    async def broken(blocks: list[BoardBlock], keyframes: list[Keyframe], llm: Any) -> list[BoardBlock]:
        raise RuntimeError("boom")

    calls = Calls(tmp_path)
    await queue_lecture(pool, db, settings)
    assert await run_job(pool, "lec_j", stages=diagram_stages(calls, broken), llm=FakeLLM(), settings=settings)
    async with pool.connection() as conn:
        [stored] = await repo.board_blocks(conn, "lec_j")
    assert stored.figure is None


async def test_lecture_detail_carries_figure(lecturer: httpx.AsyncClient, db: Db) -> None:
    fig = DiagramFigure(kind="crop", chart=None, mermaid=None, caption="A sketch", redrawn_by_ai=False)
    await db.execute("insert into lectures (id, title, status) values ('lec_f', 'Diagrams', 'draft')")
    await db.execute(
        """insert into board_blocks (id, lecture_id, type, text, confidence, first_seen_s, best_frame_s, bbox, figure)
           values ('b_9', 'lec_f', 'diagram', 'sketch', 0.9, 1, 2, '{0,0,1,1}', %s)""",
        (fig.model_dump_json(),),
    )
    res = await lecturer.get("/lectures/lec_f")
    assert res.status_code == 200, res.text
    [block] = res.json()["board_blocks"]
    assert DiagramFigure.model_validate(block["figure"]) == fig


# ---------- real rendering (headless Chromium) ----------
async def test_pdf_renders_chart_and_mermaid(chromium_ok: None, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    if not pdf.MERMAID_JS.exists():
        pytest.skip("mermaid not installed in web/node_modules")
    lecture = sample_lecture()
    chart = DiagramFigure.model_validate(
        {
            "kind": "chart",
            "chart": {
                "title": None, "x_label": "x", "y_label": "y", "x_range": [-2, 3], "y_range": [-1, 3], "show_axes": True,
                "elements": [{"type": "point", "points": [[1, 1]], "label": "meet here"}],
            },
            "mermaid": None, "caption": "Row picture", "redrawn_by_ai": True,
        }
    )  # fmt: skip
    flow = DiagramFigure(
        kind="mermaid",
        chart=None,
        mermaid='flowchart LR\n  A["Elimination"] --> B["Back substitution"]',
        caption="Steps",
        redrawn_by_ai=True,
    )
    blocks = [
        DIAGRAM.model_copy(update={"id": "blk_7", "figure": chart}),
        DIAGRAM.model_copy(update={"id": "blk_8", "figure": flow}),
    ]
    sections = [
        s.model_copy(update={"bullets": [b.model_copy(update={"board_block_ids": ["blk_7", "blk_8"]}) for b in s.bullets[:1]]})
        for s in lecture.sections
    ]
    data = await pdf.render_pdf(lecture.model_copy(update={"board_blocks": blocks, "sections": sections}))
    text = pdf_text(data)
    assert "meet here" in text and "Row picture" in text
    assert "Elimination" in text and "Back substitution" in text  # Mermaid rendered the flowchart
    assert text.count("REDRAWN BY AI") == 2 or text.count("Redrawn by AI") == 2
    assert len(PdfReader(io.BytesIO(data)).pages) >= 1
