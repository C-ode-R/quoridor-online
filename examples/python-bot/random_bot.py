import argparse
import random

from quoridor_sdk import run_bot


def choose_action(state):
    """이 함수만 자신의 MCTS/Minimax 함수로 바꾸면 됩니다."""
    return random.choice(state.game.legal_actions)


def main():
    parser = argparse.ArgumentParser(description="Quoridor Online example bot")
    parser.add_argument("--name", default="RandomBot", help="봇 닉네임")
    parser.add_argument("--room", help="참가할 6자리 방 코드. 생략하면 새 방 생성")
    parser.add_argument("--server", default="https://qdr.coder.re.kr", help="게임 서버 주소")
    args = parser.parse_args()

    run_bot(
        choose_action,
        nickname=args.name,
        server_url=args.server,
        room_code=args.room,
    )


if __name__ == "__main__":
    main()
