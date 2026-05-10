# creative_sampler.py
from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class CreativeCategory(StrEnum):
    """Supported creative idea categories parsed from creative_ideas.md."""

    MALE_NAMES = "Male Character Names"
    FEMALE_NAMES = "Female Character Names"
    SETTLEMENT_NAMES = "Settlement Names"
    REGION_NAMES = "Country/Region Names"
    ALCHEMY_INGREDIENTS = "Alchemy Ingredients"
    MAGIC_TYPES = "Magic Types"
    RELIGION_NAMES = "Religion Names"
    FOOD_NAMES = "Food Names"
    TAVERN_DRINK_NAMES = "Tavern Drink Names"
    SPECIES_NAMES = "Fantasy Race/Species Names"


@dataclass(frozen=True)
class CreativeSampleRequest:
    """Describes which creative categories should be sampled for a prompt."""

    categories: tuple[CreativeCategory, ...]
    samples_per_category: int = 8
    banned_terms: tuple[str, ...] = ()


class MarkdownCreativeIdeaBank:
    """Parses creative_ideas.md and returns small prompt-safe samples."""

    _HEADING_PATTERN: Final[re.Pattern[str]] = re.compile(
        r"^#{3,4}\s+(?P<title>.+?)\s*$",
        re.MULTILINE,
    )

    _BRACKET_LIST_PATTERN: Final[re.Pattern[str]] = re.compile(
        r"\[(?P<items>.*?)\]",
        re.DOTALL,
    )

    def __init__(self, markdown_text: str | None) -> None:
        self._markdown_text = markdown_text or ""
        self._cache: dict[CreativeCategory, list[str]] = {}

    def build_prompt_fragment(self, request: CreativeSampleRequest | None) -> str:
        """
        Builds a compact creativity prompt fragment.

        Returns an empty string if no request is provided or no matching ideas are found.
        """
        if request is None:
            logging.warning("Creative sampler received no request.")
            return ""

        banned_lower = {term.lower().strip() for term in request.banned_terms if term.strip()}
        lines: list[str] = [
            "Creative inspiration samples. Use these as inspiration, not as a mandatory list.",
            "You may alter, combine, or avoid these examples as needed.",
        ]

        found_any = False

        for category in request.categories:
            ideas = self.get_ideas(category)
            clean_ideas = [
                idea for idea in ideas
                if idea.lower() not in banned_lower
            ]

            if not clean_ideas:
                continue

            sample_size = max(1, min(request.samples_per_category, len(clean_ideas)))
            sampled_ideas = random.sample(clean_ideas, sample_size)

            lines.append(f"- {category.value}: {', '.join(sampled_ideas)}")
            found_any = True

        return "\n".join(lines) if found_any else ""

    def get_ideas(self, category: CreativeCategory) -> list[str]:
        """Returns all parsed ideas for one category."""
        if category in self._cache:
            return self._cache[category]

        section_text = self._extract_section(category.value)
        if not section_text:
            self._cache[category] = []
            return []

        match = self._BRACKET_LIST_PATTERN.search(section_text)
        if match is None:
            logging.warning("No bracketed list found for creative category: %s", category.value)
            self._cache[category] = []
            return []

        ideas = [
            item.strip()
            for item in match.group("items").replace("\n", " ").split(",")
            if item.strip()
        ]

        self._cache[category] = ideas
        return ideas

    def _extract_section(self, heading_title: str) -> str:
        """Extracts the Markdown section under a matching heading."""
        if not self._markdown_text.strip():
            logging.warning("Creative ideas markdown text is empty.")
            return ""

        heading_match = None

        for match in self._HEADING_PATTERN.finditer(self._markdown_text):
            if match.group("title").strip().lower() == heading_title.lower():
                heading_match = match
                break

        if heading_match is None:
            logging.warning("Creative category heading not found: %s", heading_title)
            return ""

        section_start = heading_match.end()
        next_heading = self._HEADING_PATTERN.search(self._markdown_text, section_start)
        section_end = next_heading.start() if next_heading else len(self._markdown_text)

        return self._markdown_text[section_start:section_end]