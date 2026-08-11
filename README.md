# Crossway

친구와 직접 만든 AI가 같은 서버에서 대결하는 실시간 온라인 쿼리도입니다.

## 현재 지원 범위

- 닉네임으로 방 생성 및 6자리 코드 참가
- 2인 실시간 대전과 연결 복구
- 표준 9×9 쿼리도 이동, 점프, 대각 이동, 벽 규칙
- 서버 권위 판정과 60초 차례 제한
- 재대결 시 선공 교대
- 라이트/다크 모드와 반응형 UI
- AI용 REST API와 Python 예제
- Dokploy용 Docker Compose 배포

## 로컬 실행

Node.js 22 이상이 필요합니다.

```bash
npm install
npm run build -w @quoridor/game-engine
npm run dev
```

- 웹: `http://localhost:5173`
- 서버: `http://localhost:3000`

## AI 실행

AI 프로그램은 MCP나 Tool Calling을 사용하지 않습니다. 독립 실행되는 일반 프로그램이 서버의 REST API에서 현재 상태를 읽고, MCTS/Minimax 등으로 수를 계산한 뒤 행동 API를 호출합니다.

새 방을 만드는 예:

```bash
QUORIDOR_SERVER=http://localhost:3000 \
QUORIDOR_NICKNAME=MyBot \
python3 examples/python-bot/bot.py
```

출력된 방 코드를 웹에서 입력하면 사람 대 AI 게임이 시작됩니다.

기존 방에 들어가는 예:

```bash
QUORIDOR_SERVER=http://localhost:3000 \
QUORIDOR_ROOM=ABC123 \
QUORIDOR_NICKNAME=MyBot \
python3 examples/python-bot/bot.py
```

`examples/python-bot/bot.py`의 `choose_action(snapshot)`을 각자의 알고리즘으로 교체하면 됩니다. `snapshot["game"]["legalActions"]`에는 현재 제출 가능한 모든 행동이 들어 있습니다.

## 주요 API

| 기능 | 요청 |
|---|---|
| 방 생성 | `POST /api/v1/rooms` |
| 방 참가 | `POST /api/v1/rooms/{roomCode}/join` |
| 내 세션 상태 | `GET /api/v1/session` |
| 게임 상태 | `GET /api/v1/games/{gameId}/state` |
| 행동 제출 | `POST /api/v1/games/{gameId}/actions` |
| 재대결 준비 | `POST /api/v1/rooms/{roomCode}/rematch` |

인증이 필요한 요청은 `Authorization: Bearer <playerToken>` 헤더를 사용합니다.

## Dokploy 배포

1. Git 저장소를 Dokploy의 Docker Compose 서비스로 연결합니다.
2. Compose 경로를 `./docker-compose.yml`로 설정합니다.
3. Domains에서 `app` 서비스의 컨테이너 포트 `3000`에 도메인을 연결합니다.
4. DNS A 레코드를 Dokploy 서버로 지정하고 HTTPS를 활성화합니다.
5. 배포 후 `/health/ready`가 `{"status":"ready"}`를 반환하는지 확인합니다.

앱은 한 인스턴스로 실행해야 합니다. 현재 방 상태는 메모리에 있으므로 배포나 서버 재시작 시 진행 중인 게임은 종료됩니다.

상세 기획은 [PROJECT_PLAN.md](./PROJECT_PLAN.md)를 참고하세요.
