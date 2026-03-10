"""LLM extraction interface.

LLMExtractor is an ABC that converts a ScrapedBlock into a raw dict matching
the DealCandidate schema. Two implementations ship:

  NullExtractor   — always returns None (rule-based fallback is used instead).
                    Safe default; makes the pipeline work without any API key.

  ClaudeExtractor — calls the Anthropic Messages API with the prompt template
                    at data/prompts/scraping_extraction.txt. Requires an
                    ANTHROPIC_API_KEY in the environment.

The pipeline (pipeline.py) tries the LLM first; if it returns None it falls
back to RuleExtractor.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from pathlib import Path

import structlog

from happybites.scraping.base import ScrapedBlock

logger = structlog.get_logger(__name__)

_PROMPT_PATH = Path(__file__).parents[2] / "data" / "prompts" / "scraping_extraction.txt"


def _load_prompt_template() -> str:
    try:
        return _PROMPT_PATH.read_text()
    except FileNotFoundError:
        logger.warning("prompt_template_missing", path=str(_PROMPT_PATH))
        return ""


class LLMExtractor(ABC):
    """Extracts structured deal fields from a ScrapedBlock.

    Returns a raw dict on success, or None to signal the pipeline should fall
    back to rule-based extraction.  The dict keys must match DealCandidate's
    field names (deal_type, price, price_range, items_included, schedule_days,
    start_time, end_time, restrictions).
    """

    @abstractmethod
    def extract(self, block: ScrapedBlock) -> dict | None:
        """Extract fields from block. Return None to trigger rule-based fallback."""
        ...

    @property
    def is_available(self) -> bool:
        """True if this extractor can actually make calls (e.g. has an API key)."""
        return False


class NullExtractor(LLMExtractor):
    """No-op extractor that always defers to rule-based parsing.

    Use as the default when no API key is configured, or in tests where you
    don't want to make real LLM calls.
    """

    def extract(self, block: ScrapedBlock) -> dict | None:
        return None

    @property
    def is_available(self) -> bool:
        return False


class ClaudeExtractor(LLMExtractor):
    """Calls Claude to extract structured deal fields from a text block.

    The prompt template (data/prompts/scraping_extraction.txt) is loaded once
    at construction time. It uses simple {placeholder} substitution.

    Args:
        api_key: Anthropic API key. Defaults to ANTHROPIC_API_KEY env var.
        model:   Claude model ID. Defaults to claude-sonnet-4-6.
        max_tokens: Maximum tokens in the response. 512 is sufficient for JSON output.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 512,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._prompt_template = _load_prompt_template()
        self._client = None

        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            logger.warning("anthropic_not_installed", extractor="ClaudeExtractor")
        except Exception as exc:
            logger.warning("claude_init_failed", error=str(exc))

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def extract(self, block: ScrapedBlock) -> dict | None:
        if not self.is_available or not self._prompt_template:
            return None

        prompt = self._prompt_template.format(
            source_url=block.source_url,
            scraper_name=block.scraper_name,
            block_type=block.block_type,
            block_text=block.text[:1500],   # guard against very long blocks
        )

        log = logger.bind(source_url=block.source_url, scraper=block.scraper_name)
        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = message.content[0].text
            result = _parse_json_response(raw_text)
            if result is None:
                log.warning("claude_scraping_parse_failed", preview=raw_text[:200])
                return None

            result["_model"] = self._model
            result["_prompt_tokens"] = message.usage.input_tokens
            result["_completion_tokens"] = message.usage.output_tokens
            return result

        except Exception as exc:
            log.error("claude_scraping_error", error=str(exc))
            return None


def _parse_json_response(text: str) -> dict | None:
    """Strip markdown fences and parse JSON."""
    clean = re.sub(r"```(?:json)?|```", "", text).strip()
    try:
        return json.loads(clean)
    except (json.JSONDecodeError, ValueError):
        return None
