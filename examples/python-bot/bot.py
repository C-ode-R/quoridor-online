"""Crossway bot example. Replace choose_action() with Minimax, MCTS, etc."""

import json
import os
import random
import time
import urllib.error
import urllib.request
import uuid

SERVER_URL = os.getenv("QUORIDOR_SERVER", "http://localhost:3000").rstrip("/")
ROOM_CODE = os.getenv("QUORIDOR_ROOM", "").strip().upper()
NICKNAME = os.getenv("QUORIDOR_NICKNAME", "RandomBot")


def request(method, path, token=None, body=None, extra_headers=None):
    headers = {"Content-Type": "application/json", **(extra_headers or {})}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(SERVER_URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        payload = json.loads(error.read())
        raise RuntimeError(payload.get("error", {}).get("code", "REQUEST_FAILED")) from error


def choose_action(snapshot):
    """Replace this function with your own MCTS or Minimax search."""
    return random.choice(snapshot["game"]["legalActions"])


def enter_room():
    payload = {"nickname": NICKNAME, "clientType": "BOT"}
    if ROOM_CODE:
        return request("POST", f"/api/v1/rooms/{ROOM_CODE}/join", body=payload)
    return request("POST", "/api/v1/rooms", body=payload)


def main():
    session = enter_room()
    token = session["playerToken"]
    print(f"Room: {session['roomCode']}")

    while True:
        snapshot = request("GET", "/api/v1/session", token=token)
        game = snapshot.get("game")

        if snapshot["status"] == "WAITING":
            time.sleep(0.5)
            continue
        if snapshot["status"] == "FINISHED":
            winner = game.get("winner") if game else None
            print("Won" if winner == snapshot["me"] else "Lost")
            return
        if not game or game["turn"] != snapshot["me"]:
            time.sleep(0.25)
            continue

        action = choose_action(snapshot)
        try:
            request(
                "POST",
                f"/api/v1/games/{snapshot['gameId']}/actions",
                token=token,
                body={"expectedVersion": game["version"], "action": action},
                extra_headers={"Idempotency-Key": str(uuid.uuid4())},
            )
        except RuntimeError as error:
            if str(error) not in {"STALE_VERSION", "NOT_YOUR_TURN"}:
                raise


if __name__ == "__main__":
    main()
