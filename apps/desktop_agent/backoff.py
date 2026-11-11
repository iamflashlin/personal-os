import random
from collections.abc import Callable


class Backoff:
    """Full-jitter exponential backoff: each wait is uniform in [0, min(cap, base * 2^n)].

    Jitter keeps a restarted Hub from being hit by every agent at the same instant.
    """

    def __init__(
        self, base_s: float, cap_s: float, rand: Callable[[], float] = random.random
    ) -> None:
        self.base_s = base_s
        self.cap_s = cap_s
        self._rand = rand
        self._attempt = 0

    def next(self) -> float:
        ceiling = min(self.cap_s, self.base_s * 2**self._attempt)
        self._attempt = min(self._attempt + 1, 32)
        return ceiling * self._rand()

    def reset(self) -> None:
        self._attempt = 0
