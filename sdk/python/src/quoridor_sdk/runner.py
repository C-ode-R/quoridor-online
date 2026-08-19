from __future__ import annotations

import time
from collections.abc import Callable

from .client import QuoridorClient
from .errors import ApiError, ConnectionError, InvalidActionError
from .models import Action, MatchResult, Session, Snapshot

ChooseAction = Callable[[Snapshot], Action]


def run_bot(
    choose_action: ChooseAction,
    *,
    nickname: str,
    server_url: str,
    room_code: str | None = None,
    poll_interval: float = 0.25,
    request_timeout: float = 10.0,
    print_status: bool = True,
) -> MatchResult:
    """Connect a bot and run it until the current match finishes."""
    client = QuoridorClient(server_url, timeout=request_timeout)
    session = (
        client.join_room(room_code, nickname)
        if room_code
        else client.create_room(nickname)
    )
    if print_status:
        _print_session(session, created=room_code is None)

    connection_failures = 0
    while True:
        try:
            snapshot = client.get_state()
            connection_failures = 0
        except ConnectionError:
            connection_failures += 1
            if connection_failures >= 5:
                raise
            time.sleep(min(2.0, poll_interval * (2 ** connection_failures)))
            continue

        if snapshot.status == "FINISHED":
            game = snapshot.game
            result = MatchResult(
                room_code=snapshot.room_code,
                player_id=snapshot.me,
                winner=game.winner if game else None,
                finish_reason=game.finish_reason if game else None,
            )
            if print_status:
                print("승리" if result.won else "패배")
            return result

        if not snapshot.is_my_turn:
            time.sleep(poll_interval)
            continue

        game = snapshot.game
        if game is None:
            time.sleep(poll_interval)
            continue

        action = choose_action(snapshot)
        if not hasattr(action, "to_dict"):
            raise InvalidActionError(
                "choose_action은 move(), horizontal_wall(), vertical_wall() 또는 "
                "snapshot.game.legal_actions의 행동을 반환해야 합니다."
            )
        if action not in game.legal_actions:
            raise InvalidActionError(f"현재 둘 수 없는 행동입니다: {action!r}")

        try:
            client.submit(action, state=snapshot)
        except ApiError as error:
            if error.code not in {"STALE_VERSION", "NOT_YOUR_TURN"}:
                raise


def _print_session(session: Session, *, created: bool) -> None:
    label = "방 생성" if created else "방 참가"
    print(f"{label}: {session.room_code} ({session.player_id})", flush=True)
