import asyncio
import queue
import time
from typing import Any

from backend import config


def drain_count_queues(count_queues, app_state: dict[str, Any]) -> None:
    for lane_id, count_queue in enumerate(count_queues):
        latest_counts = None
        while True:
            try:
                _, counts = count_queue.get_nowait()
            except queue.Empty:
                break
            latest_counts = counts

        if latest_counts is not None:
            app_state["counts"][lane_id] = latest_counts


def compute_scores(counts: dict[int, dict[str, int]]) -> dict[int, float]:
    scores: dict[int, float] = {}
    for lane_id, class_counts in counts.items():
        score = 0.0
        for class_name, count in class_counts.items():
            weight = config.VEHICLE_WEIGHTS.get(class_name)
            if weight is not None:
                score += count * weight
        scores[lane_id] = round(score, 2)
    return scores


def compute_green_times(scores: dict[int, float], total_green: int, min_green: int, lane_count: int) -> dict[int, int]:
    total_score = sum(scores.values())
    budget = total_green - lane_count * min_green

    if total_score <= 0:
        even_time = round(total_green / lane_count)
        return {lane_id: even_time for lane_id in range(lane_count)}

    green_times = {}
    for lane_id, score in scores.items():
        green_times[lane_id] = round(min_green + (score / total_score) * budget)
    return green_times


def compute_waiting_times(wait_started_at: dict[int, float], active_lane: int | None = None) -> dict[int, int]:
    now = time.monotonic()
    waiting_times = {}
    for lane_id in range(config.LANE_COUNT):
        if active_lane == lane_id:
            waiting_times[lane_id] = 0
            continue
        started_at = wait_started_at.get(lane_id, now)
        waiting_times[lane_id] = max(0, round(now - started_at))
    return waiting_times


def compute_priority_scores(scores: dict[int, float], waiting_times: dict[int, int]) -> dict[int, float]:
    priority_scores = {}
    for lane_id in range(config.LANE_COUNT):
        priority_scores[lane_id] = round(
            scores.get(lane_id, 0.0) + waiting_times.get(lane_id, 0) * config.WAIT_TIME_WEIGHT,
            2,
        )
    return priority_scores


def select_active_lane(priority_scores: dict[int, float], last_green_lane: int | None) -> int:
    candidate_lanes = list(range(config.LANE_COUNT))
    if config.BLOCK_CONSECUTIVE_GREEN and last_green_lane is not None:
        non_repeating = [lane_id for lane_id in candidate_lanes if lane_id != last_green_lane]
        if non_repeating and any(priority_scores.get(lane_id, 0.0) > 0 for lane_id in non_repeating):
            candidate_lanes = non_repeating
    return max(candidate_lanes, key=lambda lane_id: (priority_scores.get(lane_id, 0.0), -lane_id))


def build_signal_payload(app_state: dict[str, Any]) -> dict[str, Any]:
    ordered_scores = [app_state["scores"].get(i, 0.0) for i in range(config.LANE_COUNT)]
    ordered_green_times = [app_state["green_times"].get(i, config.G_MIN) for i in range(config.LANE_COUNT)]
    ordered_waiting_times = [app_state["waiting_times"].get(i, 0) for i in range(config.LANE_COUNT)]
    ordered_priority_scores = [app_state["priority_scores"].get(i, 0.0) for i in range(config.LANE_COUNT)]
    return {
        "event": "signal_update",
        "signal_states": app_state["signal_states"],
        "active_lane": app_state["active_lane"],
        "remaining_seconds": app_state["remaining_seconds"],
        "scores": ordered_scores,
        "green_times": ordered_green_times,
        "waiting_times": ordered_waiting_times,
        "priority_scores": ordered_priority_scores,
        "emergency_active": app_state["emergency_active"],
        "emergency_lane": app_state["emergency_lane"],
        "timestamp": time.time(),
    }


async def run_emergency_phase(app_state, socketio_server, emergency_event, emergency_lane_id, emergency_seen_at) -> None:
    lane = emergency_lane_id.value
    if lane < 0:
        emergency_event.clear()
        return

    while app_state["running"] and emergency_event.is_set():
        states = ["red"] * config.LANE_COUNT
        states[lane] = "green"
        app_state["signal_states"] = states
        app_state["active_lane"] = lane
        app_state["emergency_active"] = True
        app_state["emergency_lane"] = lane
        app_state["remaining_seconds"] = config.G_EMERGENCY
        app_state["waiting_times"] = compute_waiting_times(app_state["wait_started_at"], lane)
        app_state["priority_scores"] = compute_priority_scores(app_state["scores"], app_state["waiting_times"])
        await socketio_server.emit("signal_update", build_signal_payload(app_state))

        for remaining in range(config.G_EMERGENCY, 0, -1):
            if not app_state["running"]:
                return
            app_state["remaining_seconds"] = remaining
            app_state["waiting_times"] = compute_waiting_times(app_state["wait_started_at"], lane)
            app_state["priority_scores"] = compute_priority_scores(app_state["scores"], app_state["waiting_times"])
            await socketio_server.emit(
                "timer_tick",
                {
                    "event": "timer_tick",
                    "active_lane": lane,
                    "remaining_seconds": remaining,
                    "waiting_times": [app_state["waiting_times"].get(i, 0) for i in range(config.LANE_COUNT)],
                    "emergency_active": True,
                },
            )
            await asyncio.sleep(1)

        # Extend only when the emergency keeps being observed by workers.
        if time.time() - emergency_seen_at.value > config.EMERGENCY_STALE_SECONDS:
            break
        if emergency_lane_id.value != lane:
            lane = emergency_lane_id.value

    emergency_event.clear()
    with emergency_lane_id.get_lock():
        emergency_lane_id.value = -1
    app_state["emergency_active"] = False
    app_state["emergency_lane"] = None
    app_state["remaining_seconds"] = 0
    app_state["waiting_times"] = {lane_id: 0 for lane_id in range(config.LANE_COUNT)}
    app_state["priority_scores"] = {lane_id: 0.0 for lane_id in range(config.LANE_COUNT)}


async def signal_controller_loop(
    app_state,
    count_queues,
    emergency_event,
    emergency_lane_id,
    emergency_seen_at,
    socketio_server,
) -> None:
    while app_state["running"]:
        drain_count_queues(count_queues, app_state)

        if emergency_event.is_set():
            await run_emergency_phase(
                app_state,
                socketio_server,
                emergency_event,
                emergency_lane_id,
                emergency_seen_at,
            )
            continue

        scores = compute_scores(app_state["counts"])
        waiting_times = compute_waiting_times(app_state["wait_started_at"])
        priority_scores = compute_priority_scores(scores, waiting_times)
        green_times = compute_green_times(priority_scores, config.G_TOTAL, config.G_MIN, config.LANE_COUNT)
        active_lane = select_active_lane(priority_scores, app_state["last_green_lane"])

        states = ["red"] * config.LANE_COUNT
        states[active_lane] = "green"

        app_state["scores"] = scores
        app_state["green_times"] = green_times
        app_state["priority_scores"] = priority_scores
        app_state["active_lane"] = active_lane
        app_state["signal_states"] = states
        app_state["remaining_seconds"] = green_times[active_lane]
        app_state["emergency_active"] = False
        app_state["emergency_lane"] = None
        app_state["waiting_times"] = compute_waiting_times(app_state["wait_started_at"], active_lane)

        await socketio_server.emit("signal_update", build_signal_payload(app_state))

        duration = green_times[active_lane]
        for remaining in range(duration, 0, -1):
            if not app_state["running"] or emergency_event.is_set():
                break
            drain_count_queues(count_queues, app_state)
            app_state["remaining_seconds"] = remaining
            app_state["scores"] = compute_scores(app_state["counts"])
            app_state["waiting_times"] = compute_waiting_times(app_state["wait_started_at"], active_lane)
            app_state["priority_scores"] = compute_priority_scores(app_state["scores"], app_state["waiting_times"])
            await socketio_server.emit(
                "timer_tick",
                {
                    "event": "timer_tick",
                    "active_lane": active_lane,
                    "remaining_seconds": remaining,
                    "waiting_times": [app_state["waiting_times"].get(i, 0) for i in range(config.LANE_COUNT)],
                    "emergency_active": False,
                },
            )
            await asyncio.sleep(1)

        if not app_state["running"] or emergency_event.is_set():
            continue

        states = ["red"] * config.LANE_COUNT
        states[active_lane] = "yellow"
        app_state["signal_states"] = states
        app_state["remaining_seconds"] = config.YELLOW_DURATION
        app_state["waiting_times"] = compute_waiting_times(app_state["wait_started_at"], active_lane)
        app_state["priority_scores"] = compute_priority_scores(app_state["scores"], app_state["waiting_times"])
        await socketio_server.emit("signal_update", build_signal_payload(app_state))

        for remaining in range(config.YELLOW_DURATION, 0, -1):
            if not app_state["running"] or emergency_event.is_set():
                break
            app_state["remaining_seconds"] = remaining
            app_state["waiting_times"] = compute_waiting_times(app_state["wait_started_at"], active_lane)
            app_state["priority_scores"] = compute_priority_scores(app_state["scores"], app_state["waiting_times"])
            await socketio_server.emit(
                "timer_tick",
                {
                    "event": "timer_tick",
                    "active_lane": active_lane,
                    "remaining_seconds": remaining,
                    "waiting_times": [app_state["waiting_times"].get(i, 0) for i in range(config.LANE_COUNT)],
                    "emergency_active": False,
                },
            )
            await asyncio.sleep(1)

        if app_state["running"] and not emergency_event.is_set():
            app_state["wait_started_at"][active_lane] = time.monotonic()
            app_state["last_green_lane"] = active_lane
