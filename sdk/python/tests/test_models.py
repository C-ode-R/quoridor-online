import unittest
from io import BytesIO
from unittest.mock import patch

from quoridor_sdk import (
    MovePawn,
    PlaceWall,
    Position,
    QuoridorClient,
    Snapshot,
    horizontal_wall,
    move,
)


SAMPLE = {
    "roomCode": "ABC123",
    "status": "PLAYING",
    "gameId": "game-1",
    "me": "P1",
    "players": [
        {"id": "P1", "nickname": "A", "clientType": "BOT", "connected": True, "rematchReady": False},
        {"id": "P2", "nickname": "B", "clientType": "BOT", "connected": True, "rematchReady": False},
    ],
    "game": {
        "version": 0,
        "turn": "P1",
        "pawns": {"P1": {"row": 8, "col": 4}, "P2": {"row": 0, "col": 4}},
        "wallsRemaining": {"P1": 10, "P2": 10},
        "walls": [],
        "winner": None,
        "turnDeadline": "2099-01-01T00:00:00.000Z",
        "finishReason": None,
        "legalActions": [
            {"type": "MOVE_PAWN", "to": {"row": 7, "col": 4}},
            {"type": "PLACE_WALL", "orientation": "HORIZONTAL", "row": 3, "col": 4},
        ],
    },
}


class ModelTests(unittest.TestCase):
    def test_client_sends_explicit_sdk_user_agent(self):
        payload = BytesIO(
            b'{"roomCode":"ABC123","playerToken":"token","playerId":"P1"}'
        )
        with patch("urllib.request.urlopen", return_value=payload) as urlopen:
            QuoridorClient("https://qrd.coder.re.kr").create_room("TestBot")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("User-agent"), "quoridor-online-sdk/0.1")

    def test_parses_snapshot_into_typed_models(self):
        state = Snapshot.from_dict(SAMPLE)
        self.assertTrue(state.is_my_turn)
        self.assertEqual(state.game.pawns["P1"], Position(8, 4))
        self.assertIsInstance(state.game.legal_actions[0], MovePawn)
        self.assertIsInstance(state.game.legal_actions[1], PlaceWall)
        self.assertEqual(state.opponent.nickname, "B")

    def test_action_helpers_match_server_actions(self):
        state = Snapshot.from_dict(SAMPLE)
        self.assertIn(move(7, 4), state.game.legal_actions)
        self.assertIn(horizontal_wall(3, 4), state.game.legal_actions)


if __name__ == "__main__":
    unittest.main()
