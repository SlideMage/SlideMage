"""What became of each image of a drafting or translating run (workspace v6 handoff, section 5).

alt_draft's batches say what happened to every image they work through (`ItemOutcome`); the Images page and the
assistant's image tasks turn that, with the route the run captured when it started, into a `BatchResult` for the
results panel (ui/pages/image_results.py). An image the run never reached, because it was stopped or the route was
switched, is `CANCELLED`: nothing was sent for it. Pure: no Qt, no network.
"""
from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ai.ai_profile import Route

DRAFT, TRANSLATE = "draft", "translate"                  # what a run does
DONE, KEPT, FAILED, CANCELLED = "done", "kept", "failed", "cancelled"
NO_ANSWER = "the model returned no description"


@dataclass(frozen=True)
class ItemOutcome:
    kind: str           # DONE, KEPT (the user's own text was kept), FAILED or CANCELLED
    reason: str = ""    # why it failed


def display_name(image: str) -> str:
    """An image as the panels name it: its store key without the media/ folder."""
    return image.removeprefix("media/")


@dataclass(frozen=True)
class BatchResult:
    kind: str                                       # DRAFT or TRANSLATE
    route: Route                                    # the one the run captured when it started
    items: tuple[tuple[str, ItemOutcome], ...]      # per image of the queue, in its order

    @classmethod
    def of(cls, kind: str, route: Route, queue: Collection[str], outcomes: Mapping[str, ItemOutcome]) -> "BatchResult":
        """The result of a run over `queue` that settled `outcomes`; the rest was cancelled."""
        return cls(kind, route, tuple((image, outcomes.get(image, ItemOutcome(CANCELLED))) for image in queue))

    def count(self, kind: str) -> int:
        return sum(outcome.kind == kind for _image, outcome in self.items)

    @property
    def failed(self) -> list[str]:
        """The images Retry failed runs again."""
        return [image for image, outcome in self.items if outcome.kind == FAILED]

    @property
    def title(self) -> str:
        what = "Image descriptions" if self.kind == DRAFT else "Image translations"
        return f"{what} · {'partly done' if self.failed or self.count(CANCELLED) else 'done'}"

    @property
    def summary(self) -> str:
        parts = [f"{self.count(DONE)} {'drafted' if self.kind == DRAFT else 'translated'}" if self.count(DONE) else "",
                 f"{self.count(KEPT)} kept as you edited it" if self.count(KEPT) else "",
                 f"{self.count(FAILED)} failed" if self.count(FAILED) else "",
                 f"{self.count(CANCELLED)} cancelled" if self.count(CANCELLED) else ""]
        return (" · ".join(part for part in parts if part) + ". Each finished item was saved as it completed; "
                "nothing is rolled back." + (" Retry runs only the failed ones, as a new run on the current route."
                                             if self.failed else ""))

    def label(self, outcome: ItemOutcome) -> str:
        """What the panel says next to an image."""
        return {DONE: f"{'Drafted' if self.kind == DRAFT else 'Translated'} · needs review",
                KEPT: "You edited it during the run · your text kept",
                FAILED: f"Failed · {outcome.reason or NO_ANSWER}",
                CANCELLED: "Cancelled · not sent"}[outcome.kind]
