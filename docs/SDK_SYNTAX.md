# 쿼리도 Python SDK 문법 안내서

이 문서는 동아리원이 네트워크 코드를 작성하지 않고 `choose_action()` 함수에 자신의 Minimax, MCTS, 강화학습 모델을 연결할 수 있도록 SDK의 기본 문법을 설명한다.

## 1. 설치

저장소를 내려받은 뒤 최상위 폴더에서 실행한다.

```bash
python3 -m pip install ./sdk/python
```

SDK 코드를 수정하면서 사용할 경우 편집 가능 모드로 설치한다.

```bash
python3 -m pip install -e ./sdk/python
```

## 2. 가장 작은 봇

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

`room_code`를 생략하면 새 방을 만든다. 기존 방에 참가하려면 다음처럼 작성한다.

```python
run_bot(
    choose_action,
    nickname="MyBot",
    server_url="https://qrd.coder.re.kr",
    room_code="ABC123",
)
```

## 3. `state`의 구조

`choose_action(state)`는 내 차례에만 호출된다.

```python
state.room_code       # 방 코드
state.status          # WAITING, PLAYING, FINISHED
state.game_id         # 현재 게임 ID
state.me              # P1 또는 P2
state.opponent        # 상대 Player 객체
state.is_my_turn      # 내 차례이면 True
state.game            # 현재 GameState
```

게임 상태는 다음처럼 읽는다.

```python
game = state.game

game.version                    # 상태 버전
game.turn                       # 현재 차례
game.pawns["P1"]                # P1 말 위치
game.pawns["P2"]                # P2 말 위치
game.walls                      # 설치된 벽 tuple
game.walls_remaining["P1"]      # P1의 남은 벽
game.walls_remaining["P2"]      # P2의 남은 벽
game.legal_actions              # 현재 합법 행동
game.seconds_left               # 현재 차례의 남은 초
game.winner                     # 승자 또는 None
game.finish_reason              # GOAL, TIMEOUT 또는 None
```

## 4. 좌표계

API 좌표는 화면 회전과 관계없이 항상 고정되어 있다. `row`, `col`은 0부터 시작한다.

```text
P2 시작 (0, 4), 목표 row = 8

  row 0
    ↓
  row 8

P1 시작 (8, 4), 목표 row = 0
```

말 위치:

```python
position = state.game.pawns[state.me]
print(position.row, position.col)
```

벽 좌표는 8×8 기준이라 `row`, `col` 범위가 0~7이다.

## 5. 행동 만들기

### 말 이동

```python
from quoridor_sdk import move

action = move(7, 4)
```

### 가로 벽

```python
from quoridor_sdk import horizontal_wall

action = horizontal_wall(3, 4)
```

### 세로 벽

```python
from quoridor_sdk import vertical_wall

action = vertical_wall(3, 4)
```

직접 만든 행동은 합법 행동에 포함되는지 확인해야 한다.

```python
if action in state.game.legal_actions:
    return action
```

## 6. 행동 종류 구분하기

```python
from quoridor_sdk import MovePawn, PlaceWall


for action in state.game.legal_actions:
    if isinstance(action, MovePawn):
        print("이동", action.to.row, action.to.col)

    elif isinstance(action, PlaceWall):
        print("벽", action.row, action.col, action.orientation)
```

`orientation`은 `HORIZONTAL` 또는 `VERTICAL`이다.

## 7. 설치된 벽과 남은 벽

```python
for wall in state.game.walls:
    print(wall.row, wall.col, wall.orientation)

my_walls = state.game.walls_remaining[state.me]
opponent_id = "P2" if state.me == "P1" else "P1"
opponent_walls = state.game.walls_remaining[opponent_id]
```

서버가 제공하는 `legal_actions`의 벽은 겹침, 교차, 경로 완전 차단 검사를 이미 통과했다.

## 8. 결과 확인

```python
result = run_bot(
    choose_action,
    nickname="MyBot",
    server_url="https://qrd.coder.re.kr",
)

print(result.won)
print(result.winner)
print(result.finish_reason)
print(result.room_code)
```

## 9. 저수준 클라이언트

대회 운영 프로그램처럼 실행 흐름을 직접 제어할 때만 사용한다.

```python
from quoridor_sdk import QuoridorClient

client = QuoridorClient("https://qrd.coder.re.kr")
session = client.create_room("MyBot")

print(session.room_code)
print(session.player_id)

state = client.get_state()
action = state.game.legal_actions[0]
next_state = client.submit(action, state=state)
```

기존 방 참가:

```python
client.join_room("ABC123", "MyBot")
```

재대결 준비:

```python
client.request_rematch()
```

## 10. Minimax/MCTS/강화학습 연결 규칙

알고리즘 함수는 최종적으로 SDK의 `MovePawn` 또는 `PlaceWall` 객체를 반환해야 한다.

```python
def choose_action(state):
    action = search(state)

    if action not in state.game.legal_actions:
        raise ValueError("탐색 결과가 현재 합법 수가 아닙니다.")

    return action
```

네트워크 요청, 토큰, 상태 버전, 중복 제출, 상대 차례 대기는 `run_bot()`이 처리한다. 학습이나 탐색 코드는 HTTP 요청을 직접 보내지 않는다.

## 11. 자주 발생하는 오류

| 오류 | 의미 |
|---|---|
| `ROOM_NOT_FOUND` | 방 코드가 없거나 서버가 재시작됨 |
| `ROOM_FULL` | 이미 두 명이 참가함 |
| `INVALID_TOKEN` | 플레이어 토큰이 잘못됨 |
| `NOT_YOUR_TURN` | 내 차례가 아닌데 행동을 제출함 |
| `STALE_VERSION` | 오래된 상태를 기준으로 계산한 행동 |
| `ILLEGAL_MOVE` | 이동 규칙에 맞지 않음 |
| `ILLEGAL_WALL` | 겹침, 교차 또는 경로 차단 벽 |
| `GAME_ALREADY_FINISHED` | 계산 중 게임이 종료됨 |

`run_bot()`은 `NOT_YOUR_TURN`, `STALE_VERSION`과 일시적인 연결 실패를 자동으로 처리한다.
