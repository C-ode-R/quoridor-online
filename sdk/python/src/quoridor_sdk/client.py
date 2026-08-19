from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Mapping

from .errors import ApiError, ConnectionError
from .models import Action, Session, Snapshot


class QuoridorClient:
    """Low-level synchronous client for the Quoridor REST API."""

    def __init__(self, server_url: str, *, timeout: float = 10.0):
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
        self.session: Session | None = None

    def create_room(self, nickname: str) -> Session:
        data = self._request("POST", "/api/v1/rooms", body={
            "nickname": nickname,
            "clientType": "BOT",
        })
        return self._set_session(data)

    def join_room(self, room_code: str, nickname: str) -> Session:
        code = room_code.strip().upper()
        data = self._request("POST", f"/api/v1/rooms/{code}/join", body={
            "nickname": nickname,
            "clientType": "BOT",
        })
        return self._set_session(data)

    def resume(self, player_token: str) -> Snapshot:
        self.session = Session(room_code="", player_token=player_token, player_id="P1")
        snapshot = self.get_state()
        self.session = Session(
            room_code=snapshot.room_code,
            player_token=player_token,
            player_id=snapshot.me,
        )
        return snapshot

    def get_state(self) -> Snapshot:
        data = self._request("GET", "/api/v1/session", authenticated=True)
        return Snapshot.from_dict(data)

    def submit(self, action: Action, *, state: Snapshot | None = None) -> Snapshot:
        self._require_session()
        state = state or self.get_state()
        if not state.game_id:
            raise ApiError("GAME_NOT_STARTED")
        if not state.game:
            raise ApiError("GAME_NOT_STARTED")

        idempotency_key = str(uuid.uuid4())
        for attempt in range(3):
            try:
                data = self._request(
                    "POST",
                    f"/api/v1/games/{state.game_id}/actions",
                    authenticated=True,
                    body={"expectedVersion": state.game.version, "action": action.to_dict()},
                    headers={"Idempotency-Key": idempotency_key},
                )
                return Snapshot.from_dict(data["snapshot"])
            except ConnectionError:
                if attempt == 2:
                    raise
                time.sleep(0.2 * (2 ** attempt))
        raise ConnectionError(f"Cannot connect to {self.server_url}")

    def request_rematch(self) -> None:
        session = self._require_session()
        self._request(
            "POST",
            f"/api/v1/rooms/{session.room_code}/rematch",
            authenticated=True,
            body={},
        )

    def _set_session(self, data: Mapping[str, Any]) -> Session:
        self.session = Session(
            room_code=str(data["roomCode"]),
            player_token=str(data["playerToken"]),
            player_id=data["playerId"],
        )
        return self.session

    def _require_session(self) -> Session:
        if self.session is None:
            raise ApiError("NOT_CONNECTED")
        return self.session

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        authenticated: bool = False,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        # Cloudflare rejects Python's default ``Python-urllib/*`` user agent
        # with error 1010. Use an explicit SDK identity for bot clients.
        request_headers = {
            "Accept": "application/json",
            "User-Agent": "quoridor-online-sdk/0.1",
            **(headers or {}),
        }
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        if authenticated:
            session = self._require_session()
            request_headers["Authorization"] = f"Bearer {session.player_token}"

        request = urllib.request.Request(
            self.server_url + path,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read().decode("utf-8"))
                code = payload.get("error", {}).get("code", "REQUEST_FAILED")
            except (json.JSONDecodeError, UnicodeDecodeError):
                code = "REQUEST_FAILED"
            raise ApiError(code, error.code) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout) as error:
            raise ConnectionError(f"Cannot connect to {self.server_url}") from error
