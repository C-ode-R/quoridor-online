# Quoridor Online 기획서

## 1. 목표

동아리원이 웹에서 방을 만들고 실시간으로 쿼리도를 플레이할 수 있으며, 이후 직접 만든 AI 프로그램도 동일한 게임 서버에 참가해 사람 또는 다른 AI와 대결할 수 있는 서비스를 만든다.

첫 버전은 다음 경험에 집중한다.

- 로그인 없이 닉네임 입력
- 6자리 방 코드로 방 만들기와 참가
- 2인 실시간 대전
- 연결이 잠시 끊겨도 같은 플레이어로 복귀
- 대국 종료 후 같은 방에서 재대결
- REST API를 이용한 AI 참가와 행동 제출
- Dokploy를 이용한 실제 인터넷 배포

관전자, 채팅, 랭킹, 대국 기록, 회원 계정, AI 코드 업로드는 첫 버전에서 제외한다.

## 2. 제품 원칙

### 서버가 유일한 판정자

클라이언트와 AI는 원하는 행동만 제출한다. 이동 가능 여부, 벽 설치 가능 여부, 차례, 시간 제한, 승패는 모두 서버가 판정한다. 웹 플레이어와 AI 플레이어는 같은 규칙 엔진을 사용한다.

### 한 게임, 두 가지 접속 방식

- 웹 플레이어: WebSocket으로 상태를 실시간 수신하고 행동 제출
- AI 플레이어: REST API로 상태를 조회하고 행동 제출

두 방식은 서버 내부에서 동일한 `GameCommand`로 변환된다.

### 규칙 엔진은 입출력 없는 순수 모듈

네트워크나 화면 코드와 분리해 테스트가 쉽고, 나중에 AI가 로컬에서 다음 상태를 시뮬레이션할 때도 그대로 재사용할 수 있게 한다.

## 3. 권장 기술 구조

하나의 저장소에서 TypeScript를 공용으로 사용한다.

```text
apps/
  web/          React + Vite 웹 화면
  server/       Node.js + Fastify + WebSocket 서버
packages/
  game-engine/  쿼리도 규칙, 상태 전이, 승리 판정
  protocol/     API 요청/응답과 실시간 이벤트 타입
  ai-sdk/       AI 제작용 TypeScript 예제 클라이언트(추후)
examples/
  python-bot/   Python AI 예제(추후)
```

- 프런트엔드: React, TypeScript, Vite
- 백엔드: Node.js, TypeScript, Fastify
- 실시간 통신: WebSocket
- 입력 검증: Zod
- 테스트: Vitest
- 배포: Docker Compose + Dokploy

첫 버전은 단일 서버 인스턴스의 메모리에 방과 게임 상태를 보관한다. 재접속에는 대응하지만 서버 재시작 중인 대국은 종료된다. 계정과 전적 저장이 필요해질 때 PostgreSQL을, 서버를 여러 대로 늘릴 때 Redis를 추가한다.

## 4. 사용자 흐름

### 방 만들기

1. 사용자가 닉네임을 입력한다.
2. `방 만들기`를 누른다.
3. 서버가 추측하기 어려운 6자리 방 코드와 비밀 재접속 토큰을 발급한다.
4. 대기 화면에서 방 코드를 복사한다.
5. 상대가 입장하면 두 플레이어가 준비 상태가 된다.
6. 방장이 시작하거나 양쪽 준비 완료 시 대국을 시작한다.

### 방 참가

1. 닉네임과 방 코드를 입력한다.
2. 빈 두 번째 자리에 참가한다.
3. 방이 없거나 이미 찼다면 명확한 오류를 표시한다.

### 재접속

브라우저는 플레이어 재접속 토큰을 로컬에 보관한다. 새 WebSocket 연결에서 토큰을 제시하면 서버가 기존 자리를 복원하고 현재 전체 상태를 다시 보낸다.

### 재대결

대국이 끝난 뒤 양쪽이 `재대결`을 누르면 같은 방에서 새 게임을 시작한다. 선공은 이전 대국과 반대로 배정한다.

## 5. 화면 구성

### 시작 화면

- 서비스 제목
- 닉네임 입력
- `방 만들기`
- 방 코드 입력과 `참가`

### 대기실

- 방 코드와 복사 버튼
- 두 플레이어 닉네임과 연결 상태
- 준비/시작 버튼
- 나가기 버튼

### 게임 화면

- 중앙: 9×9 보드와 벽 설치 지점
- 상단: 상대 닉네임, 남은 벽, 차례 시간
- 하단: 내 닉네임, 남은 벽
- 현재 차례를 색과 문장으로 함께 표시
- 선택 가능한 말 이동 칸과 벽 위치를 미리 표시
- 모바일에서는 보드를 화면 너비에 맞추되 게임 정보는 최소화

### 종료 창

- 승자와 종료 이유
- 재대결 준비 버튼
- 방 나가기 버튼

## 6. 쿼리도 규칙 명세

- 보드: 9×9 칸
- 플레이어: 2명
- 시작 위치: 각자 자기 쪽 중앙
- 목표: 반대쪽 끝 행의 아무 칸에 먼저 도착
- 시작 벽: 각 플레이어 10개
- 한 차례에는 말 이동 또는 벽 하나 설치
- 인접 칸 이동, 상대를 넘는 직선 점프, 점프가 막힌 경우 대각 이동을 지원
- 벽 좌표는 8×8 교차 위치와 `HORIZONTAL` 또는 `VERTICAL` 방향으로 표현
- 기존 벽과 겹치거나 교차하는 벽은 금지
- 벽 설치 후 양쪽 모두 목표 행까지 경로가 남아 있어야 함
- 경로 존재 여부는 BFS로 검사

첫 버전의 기본 차례 제한은 60초다. 제한 시간이 지나면 해당 플레이어의 패배로 처리하며, 연결이 끊겨도 시간은 계속 흐른다. 방 생성 시 제한 시간 없음 또는 30/60/120초 선택은 후속 옵션으로 둘 수 있다.

## 7. 핵심 상태 모델

```ts
type PlayerId = "P1" | "P2";

type GameState = {
  gameId: string;
  version: number;
  status: "WAITING" | "PLAYING" | "FINISHED";
  turn: PlayerId;
  turnDeadline: string | null;
  pawns: Record<PlayerId, { row: number; col: number }>;
  wallsRemaining: Record<PlayerId, number>;
  horizontalWalls: Array<{ row: number; col: number }>;
  verticalWalls: Array<{ row: number; col: number }>;
  winner: PlayerId | null;
  finishReason: "GOAL" | "TIMEOUT" | "RESIGN" | null;
};
```

`version`은 행동이 적용될 때마다 1씩 증가한다. 웹과 AI 모두 자신이 확인한 버전을 함께 제출해야 하며, 오래된 상태에서 만든 행동은 서버가 거부한다.

## 8. AI용 REST API 초안

모든 경로는 `/api/v1` 아래에 둔다. AI 토큰은 충분히 긴 임의 문자열이며 `Authorization: Bearer <token>`으로 전달한다. 토큰 원문은 서버 로그에 남기지 않는다.

### AI가 방 만들기

```http
POST /api/v1/rooms
Content-Type: application/json

{
  "nickname": "ShortestPathBot",
  "clientType": "BOT"
}
```

```json
{
  "roomCode": "K7M2Q9",
  "playerToken": "secret-token",
  "playerId": "P1"
}
```

### AI가 기존 방 참가

```http
POST /api/v1/rooms/K7M2Q9/join
Content-Type: application/json

{
  "nickname": "WallBot",
  "clientType": "BOT"
}
```

### 현재 상태 조회

```http
GET /api/v1/games/{gameId}/state
Authorization: Bearer <playerToken>
```

응답에는 전체 공개 게임 상태, 내 플레이어 ID, 현재 합법 행동 목록을 포함한다. AI가 규칙 엔진을 직접 구현하지 않아도 참가할 수 있게 하는 선택이다.

### 말 이동 제출

```http
POST /api/v1/games/{gameId}/actions
Authorization: Bearer <playerToken>
Idempotency-Key: <random-uuid>
Content-Type: application/json

{
  "expectedVersion": 12,
  "action": {
    "type": "MOVE_PAWN",
    "to": { "row": 4, "col": 5 }
  }
}
```

### 벽 설치 제출

```json
{
  "expectedVersion": 13,
  "action": {
    "type": "PLACE_WALL",
    "orientation": "HORIZONTAL",
    "row": 3,
    "col": 4
  }
}
```

### API 오류 원칙

- `400 INVALID_ACTION`: 형식 또는 좌표 오류
- `401 INVALID_TOKEN`: 토큰 없음 또는 잘못된 토큰
- `403 NOT_YOUR_SEAT`: 이 게임의 플레이어가 아님
- `404 ROOM_NOT_FOUND` 또는 `GAME_NOT_FOUND`
- `409 NOT_YOUR_TURN`, `STALE_VERSION`, `ROOM_FULL`, `GAME_ALREADY_FINISHED`
- `429 RATE_LIMITED`: 과도한 상태 조회 또는 행동 요청

AI는 `409 STALE_VERSION`을 받으면 상태를 다시 조회해야 한다. 같은 `Idempotency-Key`로 재시도한 요청은 행동을 중복 적용하지 않는다.

초기 버전은 250~500ms 간격 폴링으로 충분하다. 이후에는 `GET /state?afterVersion=12&wait=25` 형태의 롱 폴링을 추가해 불필요한 요청을 줄일 수 있다.

## 9. 웹 실시간 프로토콜

### 클라이언트에서 서버로

- `session.resume`
- `room.ready`
- `game.action`
- `game.resign`
- `rematch.ready`

### 서버에서 클라이언트로

- `room.snapshot`
- `player.connection_changed`
- `game.started`
- `game.snapshot`
- `game.action_applied`
- `game.finished`
- `rematch.status`
- `error`

연결 직후와 재접속 직후에는 항상 전체 스냅샷을 보내고, 평소에는 변경 이벤트를 보낸다. 클라이언트 버전이 하나라도 건너뛰면 전체 스냅샷을 다시 요청한다.

## 10. 보안과 운영 기준

- 모든 외부 연결은 HTTPS/WSS 사용
- CORS는 실제 웹 도메인만 허용
- 방 코드와 플레이어 토큰을 분리: 방 코드를 알아도 수를 둘 수 없음
- 방 생성, 참가, 상태 조회, 행동 제출에 IP 및 토큰별 요청 제한
- 닉네임 길이와 허용 문자를 서버에서 검증
- 요청 본문 크기 제한
- AI 행동 응답과 오류에 `requestId`를 넣어 문제 추적
- 로그에 토큰, Authorization 헤더, 불필요한 개인 정보 기록 금지
- 서버 종료 시 새 연결을 막고 짧은 유예 후 종료하는 graceful shutdown 적용

## 11. Dokploy 배포안

첫 버전은 하나의 앱 컨테이너이거나 웹과 서버를 묶은 Docker Compose로 배포한다. 실시간 방 상태가 메모리에 있으므로 서버 인스턴스는 1개만 실행한다.

권장 구성:

```text
Internet
   │ HTTPS / WSS
Dokploy + Traefik
   │
quoridor-app:3000
```

- 앱은 컨테이너 내부에서 `0.0.0.0:3000`에 바인딩
- 호스트 포트를 직접 공개하지 않고 Dokploy Domains에서 컨테이너 포트 3000 연결
- `/health/live`와 `/health/ready` 제공
- Git 저장소 push 시 Dokploy 자동 배포 웹훅 사용 가능
- 도메인의 DNS A 레코드를 서버 IP에 연결한 뒤 HTTPS 인증서 설정
- WebSocket은 같은 도메인의 `/ws` 경로 사용
- 배포 시 진행 중인 방이 종료될 수 있음을 첫 버전 운영 정책에 명시

웹과 API를 `https://quoridor.example.com` 하나에 두면 CORS와 쿠키, WebSocket 설정이 단순해진다.

## 12. 개발 단계

### 1단계: 규칙 엔진

- 보드와 벽 자료구조
- 일반 이동, 점프, 대각 이동
- 벽 겹침/교차 검사
- BFS 경로 보장
- 승리 판정
- 모든 규칙의 단위 테스트

완료 기준: 네트워크 없이 두 명이 명령을 번갈아 적용해 완전한 게임을 진행할 수 있다.

### 2단계: 방과 게임 서버

- 방 생성/참가/나가기
- 플레이어 비밀 토큰과 재접속
- 차례와 60초 타이머
- 서버 권위 행동 처리
- 재대결 상태 머신

완료 기준: 자동화 테스트에서 두 클라이언트가 방 생성부터 재대결까지 수행한다.

### 3단계: 웹 UI

- 시작 화면과 대기실
- 반응형 게임 보드
- 말 이동 및 벽 배치 미리보기
- 연결 상태와 오류 표시
- 승리 및 재대결 UI

완료 기준: 데스크톱과 모바일 브라우저 두 개로 실제 대국이 가능하다.

### 4단계: AI API

- REST 방 생성/참가
- 상태 조회와 합법 행동 목록
- 버전 기반 행동 제출
- 인증, 중복 요청 방지, 요청 제한
- Python 랜덤 AI와 BFS AI 예제

완료 기준: 사람 대 AI와 AI 대 AI가 모두 동일한 서버에서 끝까지 진행된다.

### 5단계: 배포와 장애 점검

- Docker 이미지와 Compose 설정
- Dokploy 도메인 및 HTTPS/WSS
- 상태 확인 엔드포인트
- 끊김/재연결, 새로고침, 중복 요청, 시간 초과 테스트

완료 기준: 서로 다른 외부 네트워크의 두 기기와 로컬 AI 프로그램이 배포 서버에서 대국한다.

## 13. 첫 버전 완료 조건

- 두 사람이 방 코드로 만나 정상 대국 가능
- 새로고침 후 기존 자리와 게임 상태 복원
- 모든 불법 이동과 불법 벽을 서버가 거부
- 양쪽 경로를 완전히 막는 벽을 서버가 거부
- 동시에 행동이 들어와도 하나만 적용
- 제한 시간과 승리 판정이 서버 기준으로 일치
- 재대결 시 선공 교대
- Python 예제 AI가 공개 API만으로 한 판 완주
- Dokploy HTTPS 환경에서 WebSocket 재연결 정상 작동

## 14. 후속 확장

첫 버전이 안정된 뒤 아래 순서로 확장한다.

1. 대국 기록과 재생
2. 관전자
3. AI 전용 빠른 대전과 짧은 차례 제한
4. 자동 리그, Elo, 순위표
5. 사용자 계정과 AI 토큰 관리
6. PostgreSQL 영속화
7. Redis 기반 다중 서버 운영

