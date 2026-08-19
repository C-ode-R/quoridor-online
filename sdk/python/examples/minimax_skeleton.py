"""Minimax 연결 구조 예시. evaluate/search 부분을 직접 구현하세요."""

from quoridor_sdk import run_bot


def choose_action(state):
    game = state.game

    # TODO: game을 자신의 Board 자료구조로 변환하고 Minimax/MCTS를 실행합니다.
    # 반드시 game.legal_actions 중 하나와 같은 Action 객체를 반환해야 합니다.
    return game.legal_actions[0]


if __name__ == "__main__":
    run_bot(
        choose_action,
        nickname="MyMinimax",
        server_url="https://qdr.coder.re.kr",
        # room_code="ABC123",  # 기존 방에 참가할 때만 작성
    )
