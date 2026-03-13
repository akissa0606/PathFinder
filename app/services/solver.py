"""
Solver service — bridges sync TSP algorithms with async SSE streaming.

Uses a thread-safe queue so the algorithm (running in a thread) can push
progress events that the async generator yields to the SSE response.
"""

import asyncio
import queue
from collections.abc import AsyncGenerator
from typing import Any

from app.algorithms import nearest_neighbor as nn


_SENTINEL = object()


async def run_nn_with_progress(
    matrix: list[list[float]],
    start_index: int = 0,
    time_windows: list[tuple[float, float]] | None = None,
    service_time: float = 0,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Run Nearest Neighbor in a thread, yielding SSE-ready dicts as it progresses.

    Yields:
        {"type": "progress", "route": [...], "cost": float}  — after each city
        {"type": "done", "route": [...], "cost": float}       — final result
    """
    q: queue.Queue[tuple[str, list[int], float] | object] = queue.Queue()

    def callback(route: list[int], cost: float) -> None:
        q.put(("progress", route, cost))

    def run() -> tuple[list[int], float]:
        try:
            result = nn.solve(
                matrix,
                start_index=start_index,
                time_windows=time_windows,
                service_time=service_time,
                progress_callback=callback,
            )
            return result
        finally:
            q.put(_SENTINEL)

    task = asyncio.get_event_loop().run_in_executor(None, run)

    while True:
        item = await asyncio.to_thread(q.get)
        if item is _SENTINEL:
            break
        _, route, cost = item
        yield {"type": "progress", "route": route, "cost": cost}

    route, cost = await task
    yield {"type": "done", "route": route, "cost": cost}
