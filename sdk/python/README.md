# Quoridor Online Python SDK

동아리원이 HTTP 요청, 인증 토큰, 재시도, 차례 확인을 직접 구현하지 않고 쿼리도 AI만 작성하도록 돕는 모듈입니다. 외부 패키지 의존성이 없고 Python 3.10 이상에서 동작합니다.

## 설치

저장소를 받은 뒤 프로젝트 루트에서 실행합니다.

```bash
python3 -m pip install ./sdk/python
```

개발 중 SDK 코드를 바로 반영하려면 편집 가능 모드로 설치합니다.

```bash
python3 -m pip install -e ./sdk/python
```

## 가장 간단한 봇

```python
import random
from quoridor_sdk import run_bot


def choose_action(state):
    return random.choice(state.game.legal_actions)


run_bot(
    choose_action,
    nickname="RandomBot",
    server_url="https://qrd.coder.re.kr",
)
```

실행하면 방 코드가 표시됩니다. 두 번째 봇이나 웹 플레이어가 그 코드로 참가하면 게임이 자동으로 시작됩니다.

## 기존 방 참가

```python
run_bot(
    choose_action,
    nickname="MyBot",
    server_url="https://qrd.coder.re.kr",
    room_code="ABC123",
)
```

## `choose_action`에서 받는 값

```python
def choose_action(state):
    print(state.me)                         # "P1" 또는 "P2"
    print(state.game.turn)                  # 현재 차례
    print(state.game.pawns["P1"].row)       # 말 위치
    print(state.game.walls_remaining["P1"]) # 남은 벽
    print(state.game.walls)                 # 설치된 벽
    print(state.game.seconds_left)          # 서버 제한 시간
    print(state.game.legal_actions)         # 지금 제출 가능한 수

    return state.game.legal_actions[0]
```

좌표는 항상 서버 기준이며 `row`, `col`은 모두 0부터 시작합니다.

- P1 시작: `(8, 4)`, 목표: `row == 0`
- P2 시작: `(0, 4)`, 목표: `row == 8`
- 벽 좌표: `row`, `col` 모두 0~7

행동은 합법 행동 목록에서 고르거나 도우미로 만들 수 있습니다.

```python
from quoridor_sdk import move, horizontal_wall, vertical_wall

move(7, 4)
horizontal_wall(3, 4)
vertical_wall(3, 4)
```

## MCTS/Minimax 연결

```python
from quoridor_sdk import run_bot
from my_ai import search_best_action


def choose_action(state):
    # 필요하면 SDK 상태를 자신의 Board 자료구조로 변환합니다.
    return search_best_action(state)


run_bot(
    choose_action,
    nickname="MCTS-10000",
    server_url="https://qrd.coder.re.kr",
    room_code=None,
)
```

`run_bot`이 처리하는 항목:

- 방 생성 또는 참가
- 비밀 플레이어 토큰 관리
- 게임 시작과 상대 차례 대기
- 상태 버전과 중복 요청 키 전송
- 일시적인 네트워크 오류 재시도
- 늦게 계산된 수의 안전한 폐기
- 불법 행동의 사전 검증
- 승패 결과 반환

고급 사용자는 `QuoridorClient`를 직접 사용해 대회 운영 프로그램이나 자체 이벤트 루프를 만들 수 있습니다.

바로 수정해서 사용할 뼈대는 [`examples/minimax_skeleton.py`](./examples/minimax_skeleton.py)에 있습니다.
