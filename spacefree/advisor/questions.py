"""System One style answer types: typed judgments with probabilities, never free text."""
from __future__ import annotations

import math
from dataclasses import dataclass


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


@dataclass(frozen=True)
class Noul:
    """Probability that a yes/no condition holds (0..1). Near 0.5 means 'unsure'."""
    p: float


@dataclass(frozen=True)
class Choice:
    """One pick from a fixed set, with the full distribution and its concentration."""
    choice: str
    probs: dict[str, float]
    confidence: float


@dataclass(frozen=True)
class Score:
    """Probability-weighted position on ordered levels."""
    score: float
    probs: list[float]
    confidence: float


def softmax(logits: dict[str, float]) -> dict[str, float]:
    m = max(logits.values())
    exps = {k: math.exp(v - m) for k, v in logits.items()}
    total = sum(exps.values())
    return {k: v / total for k, v in exps.items()}


def concentration(probs: list[float]) -> float:
    """1 - normalised entropy: 1 = one option dominates, 0 = all equally likely."""
    n = len(probs)
    if n < 2:
        return 1.0
    h = -sum(p * math.log(p) for p in probs if p > 0)
    return max(0.0, 1 - h / math.log(n))
