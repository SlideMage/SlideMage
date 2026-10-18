"""Layout profiles of the presenter window (plan 4.10): a split tree whose leaves hold the elements.

A node is a split ("h": a left of b, "v": a above b) with a ratio for `a`, or a leaf: one big element
(current, next, notes) or an info strip of the small ones (counter, clock, timer, toolbar). It maps onto
nested splitters, always fills the window and is easy to validate and store as JSON.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

BIG = ("current", "next", "notes")
SMALL = ("counter", "clock", "timer", "toolbar")
MIN_RATIO, MAX_RATIO = 0.1, 0.9


@dataclass(frozen=True)
class Leaf:
    elements: tuple[str, ...]

    @property
    def is_strip(self) -> bool:
        return all(e in SMALL for e in self.elements)


@dataclass(frozen=True)
class Split:
    orient: str          # "h" or "v"
    ratio: float         # the share of `a`
    a: "Node"
    b: "Node"


Node = Union[Leaf, Split]


@dataclass(frozen=True)
class Profile:
    name: str
    tree: Node
    builtin: bool = False


def parse_node(data: dict) -> Node:
    """A node from its JSON form; ValueError for anything that is not one."""
    if not isinstance(data, dict):
        raise ValueError("a layout node must be an object")
    if "leaf" in data:
        names = data["leaf"] if isinstance(data["leaf"], list) else [data["leaf"]]
        if not names or not all(isinstance(n, str) and n in BIG + SMALL for n in names):
            raise ValueError(f"unknown element in {names!r}")
        return Leaf(tuple(names))
    if data.get("split") not in ("h", "v"):
        raise ValueError("a split must be 'h' or 'v'")
    ratio = min(MAX_RATIO, max(MIN_RATIO, float(data.get("ratio", 0.5))))
    return Split(data["split"], ratio, parse_node(data["a"]), parse_node(data["b"]))


def node_to_dict(node: Node) -> dict:
    if isinstance(node, Leaf):
        return {"leaf": node.elements[0] if len(node.elements) == 1 else list(node.elements)}
    return {"split": node.orient, "ratio": node.ratio, "a": node_to_dict(node.a), "b": node_to_dict(node.b)}


def elements_of(node: Node) -> list[str]:
    return list(node.elements) if isinstance(node, Leaf) else elements_of(node.a) + elements_of(node.b)


def problems(profile: Profile) -> list[str]:
    """Why a profile cannot be used (empty when it can)."""
    found = []
    names = elements_of(profile.tree)
    if "current" not in names:
        found.append("the current slide is missing")
    found += [f"{n} appears twice" for n in sorted(set(names)) if names.count(n) > 1]

    def check(node: Node) -> None:
        if isinstance(node, Leaf):
            if any(e in BIG for e in node.elements) and len(node.elements) > 1:
                found.append("a big element must be alone in its area")
        else:
            check(node.a)
            check(node.b)
    check(profile.tree)
    return found


def profile_from_dict(data: dict) -> Profile:
    profile = Profile(str(data.get("name", "")).strip(), parse_node(data["tree"]))
    if not profile.name:
        raise ValueError("a profile needs a name")
    if (bad := problems(profile)):
        raise ValueError("; ".join(bad))
    return profile


def profile_to_dict(profile: Profile) -> dict:
    return {"name": profile.name, "version": 1, "tree": node_to_dict(profile.tree)}


STRIP = Leaf(("counter", "clock", "timer", "toolbar"))

CURRENT_LARGE = Profile("Current large", Split("v", 0.9, Split(
    "h", 0.62, Leaf(("current",)), Split("v", 0.35, Leaf(("next",)), Leaf(("notes",)))), STRIP), builtin=True)
NEXT_LARGE = Profile("Next large", Split("v", 0.9, Split(
    "h", 0.65, Leaf(("next",)), Split("v", 0.35, Leaf(("current",)), Leaf(("notes",)))), STRIP), builtin=True)

BUILTINS = (CURRENT_LARGE, NEXT_LARGE)


def profile_named(name: str, custom: Optional[list[Profile]] = None) -> Profile:
    """The profile called `name`; the first built-in when there is none (a deleted or invalid choice)."""
    for profile in list(custom or []) + list(BUILTINS):
        if profile.name == name:
            return profile
    return BUILTINS[0]
