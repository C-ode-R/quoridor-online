# 쿼리도 강화학습 플로우

## 목표 구조

배포 서버를 학습 환경으로 직접 사용하지 않는다. HTTP 게임은 실제 대전과 최종 검증에만 사용하고, 학습은 동일한 규칙을 구현한 로컬 환경에서 빠르게 진행한다.

```text
로컬 쿼리도 환경
    ↓ 상태 10채널 / 합법 행동 마스크
정책-가치 신경망
    ↓ prior + value
MCTS 자기대국
    ↓ (state, policy, result)
Replay Buffer
    ↓ mini-batch
신경망 학습
    ↓ checkpoint
리그 챔피언 승격 + 휴리스틱 기준 평가
    ↓ 통과
온라인 API 봇 실행
```

## 왜 이 구조인가

- 쿼리도는 이동 81개와 벽 128개를 합쳐 고정 행동 공간이 209개다.
- 상태마다 불가능한 행동이 많아 합법 행동 마스크가 필수다.
- 보상이 승패 시점에만 나타나므로 단순 DQN보다 MCTS가 초기 탐색을 보완한다.
- P1/P2 상태를 현재 플레이어가 항상 아래에서 위로 가는 정규화 관점으로 바꿔 학습량을 줄인다.
- 실제 서버와 학습 환경을 분리하면 초당 훨씬 많은 자기대국을 실행할 수 있다.

## 입력과 출력

### 입력 10×9×9

| 채널 | 내용 |
|---:|---|
| 0 | 현재 플레이어 말 |
| 1 | 상대 말 |
| 2 | 가로 벽 시작 위치 |
| 3 | 세로 벽 시작 위치 |
| 4 | 내 남은 벽 수를 0~1로 정규화한 평면 |
| 5 | 상대 남은 벽 수를 0~1로 정규화한 평면 |
| 6 | 현재 수 진행률 |
| 7 | 내 현재 최단경로 |
| 8 | 상대 현재 최단경로 |
| 9 | 현재 위치 반복 횟수 |

좌우 반사 대칭을 적용해 자기대국 한 수에서 원본과 반사본 두 개의 학습 샘플을 만든다.

### 고급 MCTS

- 선택한 하위 트리를 다음 수에서 재사용
- 외부 API 상대의 응답도 한 수 아래 분기에서 동기화
- 반복 상태 감지와 반복 유발 플레이어 패배 처리
- 신경망 추론 결과 LRU 캐시
- 동적 PUCT와 First Play Urgency
- 모든 최단경로 DAG에서 벽 후보 수집
- 실제 경로 증가량으로 벽 후보 정렬
- 상태별 탐색용 무작위 벽 후보 유지
- 초기에는 BFS 휴리스틱 prior를 섞고 학습에 따라 감소

### 출력

- Policy: 209개 행동 로짓
- Value: 현재 플레이어 관점의 승리 예상값 `-1~1`

행동 인덱스:

```text
0~80    말의 도착 칸 9×9
81~144  가로 벽 8×8
145~208 세로 벽 8×8
```

## 설치

프로젝트 루트에서 실행한다.

```bash
python3 -m pip install -e ./sdk/python
python3 -m pip install -e ./rl
```

현재 학습 실행기는 서버 운용을 단순하게 유지하기 위해 CPU 전용으로 구성되어 있다.

## 1단계: 작은 실행 확인

처음부터 큰 학습을 돌리지 말고 1회 반복으로 전체 흐름을 확인한다.

```bash
python3 rl/train.py \
  --iterations 1 \
  --games 2 \
  --simulations 10 \
  --train-steps 5 \
  --batch-size 16 \
  --channels 32 \
  --blocks 2
```

결과는 기본적으로 `checkpoints/quoridor_latest.pt`에 저장된다.

## 2단계: CPU 서버 학습

```bash
cp .env.training.example .env.training
docker compose --env-file .env.training \
  -f docker-compose.training.yml up -d --build
```

로그 확인:

```bash
docker compose -f docker-compose.training.yml logs -f --tail=100 trainer
```

안전하게 중지하고 다시 시작:

```bash
docker compose -f docker-compose.training.yml stop trainer
docker compose --env-file .env.training \
  -f docker-compose.training.yml up -d trainer
```

체크포인트, Replay Buffer, 지표는 각각 Docker named volume에 저장된다. 컨테이너가 교체되어도 남으며, 재시작하면 `quoridor_latest.pt`와 `quoridor_replay.npz`에서 자동 재개한다. 매 iteration마다 원자적으로 저장하므로 프로세스가 갑자기 종료돼도 이전 완료 지점은 손상되지 않는다.

최고 모델 가져오기:

```bash
docker compose -f docker-compose.training.yml cp \
  trainer:/workspace/checkpoints/quoridor_best.pt ./quoridor_best.pt
```

Dokploy에서는 웹 앱과 별도의 Compose 서비스 하나를 만들고 Compose 경로를 `./docker-compose.training.yml`로 지정한다. 도메인과 포트 연결은 필요 없다. 환경 변수는 `.env.training.example` 값을 등록하면 된다.

### CPU 권장값

| 서버 | `RL_CPUS` | `RL_THREADS` | `RL_WORKERS` | 모델 |
|---|---:|---:|---:|---|
| 2코어 / 4GB | 2 | 2 | 2 | 32채널, 3블록 |
| 4코어 / 8GB | 4 | 4 | 4 | 32채널, 3블록 |
| 8코어 / 16GB | 8 | 8 | 6~8 | 48채널, 4블록 |

`RL_WORKERS`는 동시에 만드는 자기대국 수다. CPU 코어 수 이하로 두는 것이 좋다. 처음에는 `RL_SIMULATIONS=20`으로 한 iteration 시간을 측정한 뒤 50, 100 순으로 올린다. 모델 크기보다 자기대국 수와 MCTS 횟수를 먼저 늘리는 편이 효율적이다.

### 자동 평가와 산출물

- `quoridor_latest.pt`: 매 iteration의 최신 학습 상태와 optimizer
- `quoridor_best.pt`: 리그 승격전을 통과한 현재 챔피언
- `checkpoints/league/*.pt`: 10 iteration 간격 및 역대 챔피언 스냅샷
- `quoridor_replay.npz`: 중단 후 이어서 학습할 자기대국 데이터
- `training.jsonl`: loss, 평균 수, 평가 승률, iteration 시간

자기대국은 기본적으로 최신 모델끼리 50%, 최신 모델과 챔피언 30%, 최신 모델과 과거 스냅샷 20%로 구성한다. 챔피언전과 과거전은 최신 모델이 선공과 후공을 번갈아 맡는다.

과거 모델과 대국할 때는 최신 모델의 수만 policy 학습에 사용한다. 과거 모델이 둔 상태는 승패 value 학습에는 유지하되, 오래된 정책을 모방하지 않도록 policy loss 가중치를 0으로 둔다. 챔피언의 수는 더 강한 정책을 전달하는 teacher 데이터로 계속 사용한다.

Replay Buffer는 배치의 60%를 최근 30,000개에서 먼저 선택하고 나머지 40%를 전체 기록에서 선택한다. 학습률은 iteration 100부터 `0.0003`, iteration 250부터 `0.0001`로 낮춘다.

10 iteration마다 Greedy 기준선은 고정 오프닝 20판과 새 무작위 오프닝 20판으로 평가한다. 챔피언 승격전은 고정 40판과 무작위 40판, 총 80판을 사용하며 총점 60% 이상이고 선공·후공 승률이 각각 45% 이상일 때만 승격한다. Greedy BFS 결과는 독립적인 성능 지표일 뿐 승격 기준에는 사용하지 않는다. 평가 대국도 `RL_WORKERS`만큼 병렬 실행된다.

MCTS는 실제 수를 고르는 루트에서 모든 합법 행동을 검토한다. 내부 노드는 CPU 비용을 제한하기 위해 최단 경로 영향이 큰 벽과 전역 탐색 벽을 섞은 제한 후보를 사용하며, 재사용된 내부 노드가 루트가 되면 전체 행동으로 다시 확장한다.

History 풀은 같은 iteration을 중복하지 않으며 최근 정기 스냅샷 6개와 최근 챔피언 3개만 사용한다. 재시작용 `resume_*` 파일은 보존하되 학습 상대에서는 제외한다.

## 3단계: 기준선 평가

학습 체크포인트를 BFS 휴리스틱 AI와 선후공을 교대하며 대결시킨다.

```bash
python3 rl/evaluate.py checkpoints/quoridor_latest.pt \
  --games 20 \
  --simulations 100 \
  --opponent greedy \
  --threads 2
```

확인할 값:

- 승률
- 선공/후공별 승률
- 평균 게임 길이
- 벽 사용 빈도
- 제한 수까지 끝나지 않은 무승부 비율

`--opponent random`도 지원한다. 랜덤 AI를 안정적으로 이긴 뒤 기본값인 BFS 휴리스틱과 비교한다.

## 4단계: 온라인 API 대전

```bash
python3 rl/api_bot.py checkpoints/quoridor_latest.pt \
  --name AlphaZeroLite \
  --server https://qdr.coder.re.kr \
  --simulations 200 \
  --wall-candidates 20 \
  --threads 2
```

기존 방에 참가하려면 `--room ABC123`을 추가한다.

API 봇은 서버 상태를 로컬 환경으로 변환하고 MCTS로 한 수를 계산한 뒤 SDK를 통해 제출한다. 학습 중에는 API를 호출하지 않는다.

## 파일 구성

```text
rl/
  train.py                 자기대국과 학습 반복
  evaluate.py              랜덤 기준선 평가
  api_bot.py               체크포인트의 온라인 대전 실행
  src/quoridor_rl/
    env.py                 로컬 쿼리도 규칙 환경
    encoding.py            상태/행동 인코딩과 합법 수 마스크
    model.py               작은 ResNet 정책-가치 모델
    mcts.py                PUCT MCTS
    self_play.py           자기대국 데이터 생성
    training.py            Replay Buffer와 손실 계산
    adapters.py            온라인 SDK 상태 변환
```

## 권장 실험 순서

1. 로컬 규칙 테스트가 서버 규칙과 일치하는지 검증
2. 작은 모델과 MCTS 10회로 파이프라인 실행 확인
3. 랜덤 초기 모델의 자기대국 데이터 확인
4. 정책 손실과 가치 손실이 감소하는지 확인
5. 랜덤 AI 20판 평가
6. BFS 휴리스틱 20판 평가
7. Minimax 기준선과 선후공 교대 평가
8. 온라인 API에서 시간 제한 내 계산되는지 확인

## 주의점

- 높은 학습 승률만으로 실제 성능을 판단하지 않는다. 이전 체크포인트와 기준 AI를 함께 평가한다.
- MCTS 횟수와 모델 추론 시간이 실제 서버의 차례 제한보다 짧아야 한다.
- 로컬 환경과 서버의 합법 수 목록이 다르면 온라인 실행을 중단하고 규칙 차이를 먼저 수정한다.
- 체크포인트와 Replay Buffer는 용량이 커질 수 있으므로 Git에 올리지 않는다.
