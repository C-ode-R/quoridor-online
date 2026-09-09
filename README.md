# Crossway

친구와 직접 만든 AI가 같은 서버에서 대결하는 실시간 온라인 쿼리도입니다.

## 현재 지원 범위

- 닉네임으로 방 생성 및 6자리 코드 참가
- 방 코드로 플레이어 자리를 차지하지 않는 실시간 관전
- 2인 실시간 대전과 연결 복구
- 표준 9×9 쿼리도 이동, 점프, 대각 이동, 벽 규칙
- 서버 권위 판정과 60초 차례 제한
- 재대결 시 선공 교대
- 라이트/다크 모드와 반응형 UI
- AI용 REST API와 설치 가능한 Python/C++ SDK
- 랜덤 단판 토너먼트, 부전승·기권·자동 진출 및 대진표 관전
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

SDK 설치:

```bash
python3 -m pip install ./sdk/python
```

새 방을 만드는 예:

```bash
python3 examples/python-bot/random_bot.py \
  --server http://localhost:3000 \
  --name MyBot
```

기존 방에 들어가려면 `--room ABC123`을 추가합니다. 동아리원은 `choose_action(state)` 함수만 자신의 MCTS/Minimax로 교체하면 됩니다. 연결, 차례 대기, 재시도, 인증, 행동 제출은 SDK가 처리합니다.

상세 사용법과 상태 구조는 [Python SDK 안내](./sdk/python/README.md)를 참고하세요.

C++20에서 게임 로직과 HTTPS 서버 요청을 모두 처리하려면 [C++ SDK 저장소](https://github.com/C-ode-R/quoridor-cpp-sdk)를 참고하세요.

- [SDK 문법 안내서](./docs/SDK_SYNTAX.md)
- [강화학습 플로우](./rl/README.md)

CPU 서버 자기대국은 별도 `docker-compose.training.yml`로 실행합니다. 웹 서비스와 학습 컨테이너를 분리했기 때문에 학습을 중지하거나 재배포해도 온라인 대전에 영향을 주지 않습니다.

## 주요 API

| 기능 | 요청 |
|---|---|
| 방 생성 | `POST /api/v1/rooms` |
| 방 참가 | `POST /api/v1/rooms/{roomCode}/join` |
| 관전 상태 | `GET /api/v1/rooms/{roomCode}/watch` |
| 내 세션 상태 | `GET /api/v1/session` |
| 게임 상태 | `GET /api/v1/games/{gameId}/state` |
| 행동 제출 | `POST /api/v1/games/{gameId}/actions` |
| 재대결 준비 | `POST /api/v1/rooms/{roomCode}/rematch` |
| 대회 생성 | `POST /api/v1/tournaments` |
| 대진표 조회 | `GET /api/v1/tournaments/{tournamentCode}` |
| 경기 방 생성 | `POST /api/v1/tournaments/{tournamentCode}/matches/{matchId}/start` |
| 선수 기권 처리 | `POST /api/v1/tournaments/{tournamentCode}/matches/{matchId}/forfeit` |

인증이 필요한 요청은 `Authorization: Bearer <playerToken>` 헤더를 사용합니다.
관전 화면은 인증 없이 `WS /ws?room={roomCode}`에 연결해 매 수 최신 상태를 받습니다.
대진표는 인증 없이 `WS /ws?tournament={tournamentCode}`에 연결해 경기 상태와 다음 라운드 진출을 실시간으로 받습니다.

## 대회 운영

첫 화면의 `대진표 만들기·보기`에서 참가자 이름을 한 줄에 한 명씩 입력하면 서버가 무작위 단판 대진을 만듭니다. 참가자 수가 2의 거듭제곱이 아니면 필요한 부전승이 즉시 처리됩니다.

운영자가 `대결 시작`을 누르면 해당 경기 전용 6자리 방 코드가 생성됩니다. 두 선수는 대진표에 적힌 이름을 그대로 입력해 `선수 입장`을 누르고, 나머지 사람은 `관전`을 누릅니다. 일반 Python/C++ 봇도 같은 이름과 방 코드로 기존 SDK의 참가 요청을 호출하면 됩니다.

목표 지점 도착이나 시간 초과로 승패가 정해지면 다음 라운드가 자동으로 열립니다. 불참자는 운영자 화면에서 해당 선수 옆 `기권`으로 처리할 수 있습니다. 대회 생성 응답의 운영자 토큰은 브라우저에 보관되며 경기 생성과 기권 API의 Bearer 인증에 사용됩니다.

## Dokploy 배포

1. Git 저장소를 Dokploy의 Docker Compose 서비스로 연결합니다.
2. Compose 경로를 `./docker-compose.yml`로 설정합니다.
3. Domains에서 `app` 서비스의 컨테이너 포트 `3000`에 도메인을 연결합니다.
4. DNS A 레코드를 Dokploy 서버로 지정하고 HTTPS를 활성화합니다.
5. 배포 후 `/health/ready`가 `{"status":"ready"}`를 반환하는지 확인합니다.

앱은 한 인스턴스로 실행해야 합니다. 방·대진표·게임·선수 토큰은 `/data/state.json`에 원자적으로 저장되고 Compose의 `quoridor-data` 볼륨으로 유지됩니다. 재시작 후 진행 중인 차례는 기존 마감 시각을 기준으로 복구됩니다. 여러 앱 인스턴스가 같은 상태 파일을 동시에 사용하는 구성은 지원하지 않습니다.

상세 기획은 [PROJECT_PLAN.md](./PROJECT_PLAN.md)를 참고하세요.
