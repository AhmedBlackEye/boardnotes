"""Real Claude calls. Only this file imports the Anthropic SDK."""

import base64

from anthropic import AsyncAnthropic
from anthropic.types import ImageBlockParam, MessageParam, TextBlockParam

from app.config import settings

from .client import DATA_RULE, LLMRequest, T, Usage, render_untrusted

MODELS = {"glance": settings.model_glance, "board": settings.model_board, "notes": settings.model_notes}


class RefusedError(RuntimeError):
    pass


class AnthropicLLM:
    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise RuntimeError("LLM_MODE=live needs ANTHROPIC_API_KEY in .env")
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.usage = Usage()

    async def structured(self, req: LLMRequest, schema: type[T]) -> T:
        content: list[ImageBlockParam | TextBlockParam] = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": img.media_type, "data": base64.standard_b64encode(img.data).decode()},
            }
            for img in req.images
        ]
        if req.cached:
            # Stable lecture context first, marked for prompt caching, so follow-up calls re-read it cheaply.
            content.append({"type": "text", "text": render_untrusted(req.cached), "cache_control": {"type": "ephemeral"}})
        text = req.instructions
        if req.untrusted:
            text += "\n\n" + render_untrusted(req.untrusted)
        content.append({"type": "text", "text": text})

        message: MessageParam = {"role": "user", "content": content}
        response = await self.client.messages.parse(
            model=MODELS[req.tier],
            max_tokens=req.max_tokens,
            system=DATA_RULE,
            output_config={"effort": req.effort},
            messages=[message],
            output_format=schema,
        )
        self.usage.calls += 1
        self.usage.input_tokens += response.usage.input_tokens
        self.usage.output_tokens += response.usage.output_tokens
        self.usage.cache_read_tokens += getattr(response.usage, "cache_read_input_tokens", 0) or 0
        if response.stop_reason == "refusal":
            raise RefusedError(f"{req.task}: model declined the request")
        if response.parsed_output is None:
            raise RuntimeError(f"{req.task}: no structured output (stop_reason={response.stop_reason})")
        return response.parsed_output
