"""Q-5: variant spellings are made consistent by exact replacement, and blocks that become identical merge."""

import pytest

from app.contracts.ai import BoardBlock
from app.contracts.enums import BlockType
from app.llm.client import LLMRequest, T, Usage
from app.llm.fake import FakeLLM
from app.pipeline import terms
from app.pipeline.citations import LatexError, LatexResult
from app.pipeline.terms import TermMap, TermVariant, apply_terms, merge_identical, normalise_terms, usable_pairs


def block(id: str, text: str, latex: str | None = None, *, t: float = 1.0, confidence: float = 0.9) -> BoardBlock:
    return BoardBlock(
        id=id,
        type=BlockType.MATH if latex else BlockType.TEXT,
        text=text,
        latex=latex,
        confidence=confidence,
        first_seen_s=t,
        best_frame_s=t + 1,
        bbox=[0.1, 0.1, 0.2, 0.2],
    )


class MapLLM:
    def __init__(self, pairs: list[tuple[str, str]] | None = None, fail: bool = False) -> None:
        self.usage = Usage()
        self.pairs = pairs or []
        self.fail = fail
        self.requests: list[LLMRequest] = []

    async def structured(self, req: LLMRequest, schema: type[T]) -> T:
        self.requests.append(req)
        if self.fail:
            raise RuntimeError("overloaded")
        return schema.model_validate({"replacements": [{"variant": v, "canonical": c} for v, c in self.pairs]})


@pytest.fixture(autouse=True)
def katex(monkeypatch: pytest.MonkeyPatch) -> None:
    def check(latex_list: list[str]) -> list[LatexResult]:
        return [LatexError("bad") if "\\oops" in x else True for x in latex_list]

    monkeypatch.setattr(terms, "check_latex", check)


def test_replacement_is_whole_token_only() -> None:
    blocks = [
        block("b_1", "the eigen value of A; eigen values"),
        block("b_2", "lamda = 2", r"\lamda = 2 + \lamdax"),
    ]
    out = apply_terms(blocks, {"eigen value": "eigenvalue", "lamda": "lambda", r"\lamda": r"\lambda"})
    assert out[0].text == "the eigenvalue of A; eigen values"  # "eigen values" is a different token
    assert out[1].text == "lambda = 2"
    assert out[1].latex == r"\lambda = 2 + \lamdax"  # never inside a longer command


def test_replacements_do_not_chain_and_latex_stays_out_of_plain_text() -> None:
    blocks = [block("b_1", "ab cd", r"ab + cd")]
    out = apply_terms(blocks, {"ab": "cd", "cd": "ef", "lam": r"\lambda"})
    assert out[0].text == "cd ef"
    assert out[0].latex == "cd + ef"
    out = apply_terms([block("b_2", "lam is 2", "lam = 2")], {"lam": r"\lambda"})
    assert out[0].text == "lam is 2" and out[0].latex == r"\lambda = 2"


def test_unsafe_pairs_are_ignored() -> None:
    term_map = TermMap(
        replacements=[
            TermVariant(variant="x", canonical="y"),  # single character
            TermVariant(variant="same", canonical="same"),
            TermVariant(variant="gone", canonical=" "),
            TermVariant(variant="long " * 20, canonical="short"),
            TermVariant(variant=" colour ", canonical="color"),
        ]
    )
    assert usable_pairs(term_map) == {"colour": "color"}


def test_identical_blocks_merge_keeping_first_id_and_best_reading() -> None:
    a = block("b_1", "eigenvalue", t=5.0, confidence=0.8)
    other = block("b_2", "other", t=6.0)
    b = block("b_3", "eigenvalue", t=2.0, confidence=0.95)
    out = merge_identical([a, other, b])
    assert [x.id for x in out] == ["b_1", "b_2"]
    assert (out[0].first_seen_s, out[0].best_frame_s, out[0].confidence) == (2.0, 3.0, 0.95)


async def test_normalise_terms_one_call_with_blocks_as_untrusted_data() -> None:
    blocks = [block("b_1", "eigen value"), block("b_2", "eigenvalue", t=4.0), block("b_3", "x", r"\lamda x", t=6.0)]
    llm = MapLLM([("eigen value", "eigenvalue"), (r"\lamda", r"\lambda")])
    out = await normalise_terms(blocks, llm)

    assert len(llm.requests) == 1
    req = llm.requests[0]
    assert (req.task, req.tier, req.effort) == ("normalise_terms", "board", "low")
    assert "eigen value" in req.untrusted["blocks"] and "eigen value" not in req.instructions
    assert [(b.id, b.text, b.latex) for b in out] == [("b_1", "eigenvalue", None), ("b_3", "x", r"\lambda x")]


async def test_latex_change_that_breaks_rendering_is_undone() -> None:
    blocks = [block("b_1", "a", r"\alpha + 1"), block("b_2", "b", r"\beta")]
    out = await normalise_terms(blocks, MapLLM([(r"\alpha", r"\oops")]))
    assert out[0].latex == r"\alpha + 1"


async def test_model_failure_or_single_block_changes_nothing(fake_llm: FakeLLM) -> None:
    blocks = [block("b_1", "row pic"), block("b_2", "column picture")]
    assert await normalise_terms(blocks, MapLLM(fail=True)) == blocks
    single = MapLLM([("row pic", "row picture")])
    assert await normalise_terms(blocks[:1], single) == blocks[:1] and single.requests == []
    out = await normalise_terms(blocks, fake_llm)  # recorded fixture
    assert [b.text for b in out] == ["row picture", "column picture"]
