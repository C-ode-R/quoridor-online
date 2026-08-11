import { useCallback, useEffect, useMemo, useState } from "react";
import type { GameAction, Orientation, PlayerId, Position, Wall } from "@quoridor/game-engine";
import type { PlayerView, Snapshot } from "./types";

const TOKEN_KEY = "crossway-player-token";
type Theme = "light" | "dark";

function getInitialTheme(): Theme {
  const saved = localStorage.getItem("crossway-theme");
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

async function api<T>(path: string, options: RequestInit = {}, token?: string): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.code ?? "REQUEST_FAILED");
  return body as T;
}

function ThemeToggle({ theme, onToggle }: { theme: Theme; onToggle: () => void }) {
  return (
    <button className="icon-button" onClick={onToggle} aria-label={theme === "light" ? "다크 모드로 전환" : "라이트 모드로 전환"}>
      <span aria-hidden="true">{theme === "light" ? "☾" : "☀"}</span>
    </button>
  );
}

function Landing({ onSession }: { onSession: (token: string, snapshot: Snapshot) => void }) {
  const [nickname, setNickname] = useState("");
  const [roomCode, setRoomCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (mode: "create" | "join") => {
    if (!nickname.trim()) return setError("닉네임을 입력해주세요.");
    if (mode === "join" && roomCode.trim().length !== 6) return setError("6자리 방 코드를 입력해주세요.");
    setBusy(true);
    setError("");
    try {
      const path = mode === "create" ? "/api/v1/rooms" : `/api/v1/rooms/${roomCode.trim().toUpperCase()}/join`;
      const result = await api<{ playerToken: string; snapshot: Snapshot }>(path, {
        method: "POST",
        body: JSON.stringify({ nickname: nickname.trim(), clientType: "HUMAN" }),
      });
      onSession(result.playerToken, result.snapshot);
    } catch (requestError) {
      const code = requestError instanceof Error ? requestError.message : "REQUEST_FAILED";
      setError(({ ROOM_NOT_FOUND: "방을 찾을 수 없습니다.", ROOM_FULL: "이미 가득 찬 방입니다." } as Record<string, string>)[code] ?? "연결하지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="landing">
      <section className="join-card" aria-label="게임 시작">
        <div className="simple-heading">
          <h1>쿼리도</h1>
          <p>방을 만들거나 코드로 참가하세요.</p>
        </div>
        <label>
          <span>닉네임</span>
          <input maxLength={20} value={nickname} onChange={(event) => setNickname(event.target.value)} placeholder="어떻게 불러드릴까요?" autoComplete="nickname" />
        </label>
        <button className="primary-button" disabled={busy} onClick={() => submit("create")}>새 방 만들기 <span>→</span></button>
        <div className="divider"><span>또는 방 코드로 참가</span></div>
        <div className="code-row">
          <input aria-label="방 코드" maxLength={6} value={roomCode} onChange={(event) => setRoomCode(event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))} placeholder="ABC123" />
          <button disabled={busy} onClick={() => submit("join")}>참가</button>
        </div>
        {error && <p className="form-error" role="alert">{error}</p>}
      </section>
    </main>
  );
}

function TurnTimer({ deadline, player }: { deadline: string | null; player?: PlayerView }) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    setNow(Date.now());
    if (!deadline) return;
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [deadline]);

  const seconds = deadline
    ? Math.max(0, Math.ceil((new Date(deadline).getTime() - now) / 1000))
    : null;
  const formatted = seconds === null
    ? "--:--"
    : `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;

  return (
    <section className={`time-card ${seconds !== null && seconds <= 10 ? "urgent" : ""}`} aria-label="현재 차례 제한 시간">
      <div>
        <span>남은 시간</span>
        <small>{player?.nickname ?? "-"} 차례</small>
      </div>
      <strong>{formatted}</strong>
    </section>
  );
}

function PlayerCard({ player, active, me, walls = 10 }: { player?: PlayerView; active: boolean; me: boolean; walls?: number }) {
  return (
    <div className={`player-card ${active ? "active" : ""}`}>
      <span className={`pawn-mini ${player?.id === "P2" ? "clay" : "green"}`} />
      <div>
        <strong>{player?.nickname ?? "기다리는 중"}{me ? " (나)" : ""}</strong>
        <small>{player ? (player.clientType === "BOT" ? "AI" : "플레이어") : "친구가 참가하면 시작됩니다"}</small>
      </div>
      {player && <span className={`connection ${player.connected ? "online" : ""}`} title={player.connected ? "연결됨" : "연결 끊김"} />}
      {player && (
        <div className="wall-inventory" aria-label={`남은 벽 ${walls}개`}>
          <span className="wall-inventory-label">벽</span>
          <span className={`wall-units ${player.id === "P1" ? "accent" : ""}`} aria-hidden="true">
            {Array.from({ length: 10 }, (_, index) => <i key={index} className={index < walls ? "remaining" : "used"} />)}
          </span>
          <b>{walls}</b>
        </div>
      )}
    </div>
  );
}

function Board({ snapshot, onAction }: { snapshot: Snapshot; onAction: (action: GameAction) => void }) {
  const game = snapshot.game!;
  const flipped = snapshot.me === "P2";
  const [orientation, setOrientation] = useState<Orientation>("HORIZONTAL");
  const legalMoves = useMemo(() => game.legalActions.filter((action): action is Extract<GameAction, { type: "MOVE_PAWN" }> => action.type === "MOVE_PAWN"), [game.legalActions]);
  const legalWalls = useMemo(() => new Set(game.legalActions.filter((action) => action.type === "PLACE_WALL").map((action) => `${action.orientation}:${action.row}:${action.col}`)), [game.legalActions]);
  const myTurn = snapshot.me === game.turn && snapshot.status === "PLAYING";

  const isLegalMove = (position: Position) => legalMoves.some((move) => move.to.row === position.row && move.to.col === position.col);

  return (
    <div className="board-column">
      <div className="board-toolbar">
        <div>
          <span className="toolbar-label">벽 방향</span>
          <div className="segmented" aria-label="벽 방향 선택">
            <button className={orientation === "HORIZONTAL" ? "selected" : ""} onClick={() => setOrientation("HORIZONTAL")} aria-label="가로 벽">━</button>
            <button className={orientation === "VERTICAL" ? "selected" : ""} onClick={() => setOrientation("VERTICAL")} aria-label="세로 벽">┃</button>
          </div>
        </div>
        <span className={`turn-pill ${myTurn ? "mine" : ""}`}>{myTurn ? "내 차례" : `${game.turn === "P1" ? "1번" : "2번"} 차례`}</span>
      </div>

      <div className="board" aria-label="쿼리도 게임 보드">
        {Array.from({ length: 81 }, (_, index) => {
          const displayPosition = { row: Math.floor(index / 9), col: index % 9 };
          const position = flipped
            ? { row: 8 - displayPosition.row, col: 8 - displayPosition.col }
            : displayPosition;
          const occupant = (Object.entries(game.pawns) as [PlayerId, Position][]).find(([, pawn]) => pawn.row === position.row && pawn.col === position.col)?.[0];
          const legal = myTurn && isLegalMove(position);
          return (
            <button key={index} className={`cell ${legal ? "legal" : ""}`} disabled={!legal} onClick={() => onAction({ type: "MOVE_PAWN", to: position })} aria-label={`${displayPosition.row + 1}행 ${displayPosition.col + 1}열${legal ? "로 이동" : ""}`}>
              {occupant && <span className={`pawn ${occupant === "P1" ? "green" : "clay"}`} />}
            </button>
          );
        })}

        {game.walls.map((wall, index) => <WallPiece key={`${wall.orientation}-${wall.row}-${wall.col}-${index}`} wall={wall} flipped={flipped} />)}

        {myTurn && Array.from({ length: 64 }, (_, index) => {
          const row = Math.floor(index / 8);
          const col = index % 8;
          const key = `${orientation}:${row}:${col}`;
          if (!legalWalls.has(key)) return null;
          return <button key={key} className={`wall-target ${orientation.toLowerCase()}`} style={wallStyle({ row, col, orientation }, flipped)} onClick={() => onAction({ type: "PLACE_WALL", row, col, orientation })} aria-label={`${row + 1}, ${col + 1}에 ${orientation === "HORIZONTAL" ? "가로" : "세로"} 벽 설치`} />;
        })}
      </div>
    </div>
  );
}

function wallStyle(wall: Wall, flipped = false): React.CSSProperties {
  const displayWall = flipped
    ? { ...wall, row: 7 - wall.row, col: 7 - wall.col }
    : wall;
  if (displayWall.orientation === "HORIZONTAL") {
    return { top: `${((displayWall.row + 1) / 9) * 100}%`, left: `${(displayWall.col / 9) * 100 + 0.5}%` };
  }
  return { top: `${(displayWall.row / 9) * 100 + 0.5}%`, left: `${((displayWall.col + 1) / 9) * 100}%` };
}

function WallPiece({ wall, flipped }: { wall: Wall; flipped: boolean }) {
  return <span className={`wall-piece ${wall.orientation.toLowerCase()}`} style={wallStyle(wall, flipped)} />;
}

function Room({ snapshot, token, onExit }: { snapshot: Snapshot; token: string; onExit: () => void }) {
  const [copied, setCopied] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const game = snapshot.game;
  const p1 = snapshot.players.find((player) => player.id === "P1");
  const p2 = snapshot.players.find((player) => player.id === "P2");

  const copyCode = async () => {
    await navigator.clipboard.writeText(snapshot.roomCode);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const submitAction = async (action: GameAction) => {
    if (!game || !snapshot.gameId || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      await api(`/api/v1/games/${snapshot.gameId}/actions`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ expectedVersion: game.version, action }),
      }, token);
    } catch (requestError) {
      const code = requestError instanceof Error ? requestError.message : "";
      setError(code === "STALE_VERSION" ? "상태가 갱신되었습니다. 다시 선택해주세요." : "그 수는 둘 수 없습니다.");
    } finally {
      setSubmitting(false);
    }
  };

  const rematch = async () => {
    await api(`/api/v1/rooms/${snapshot.roomCode}/rematch`, { method: "POST", body: "{}" }, token);
  };

  const winner = game?.winner ? snapshot.players.find((player) => player.id === game.winner) : undefined;
  const me = snapshot.players.find((player) => player.id === snapshot.me);

  return (
    <main className="game-shell">
      <header className="game-header">
        <div>
          <span className="room-label">방 코드</span>
          <button className="room-code" onClick={copyCode}>{snapshot.roomCode} <small>{copied ? "복사됨" : "복사"}</small></button>
        </div>
        <button className="text-button" onClick={onExit}>나가기</button>
      </header>

      {snapshot.status === "WAITING" ? (
        <section className="waiting-card">
          <h1>상대를 기다리는 중</h1>
          <p>방 코드 {snapshot.roomCode}</p>
          <button className="primary-button compact" onClick={copyCode}>{copied ? "복사했어요" : "방 코드 복사"}</button>
        </section>
      ) : game ? (
        <div className="match-layout">
          <aside className="match-sidebar">
            <TurnTimer deadline={snapshot.status === "PLAYING" ? game.turnDeadline : null} player={snapshot.players.find((player) => player.id === game.turn)} />
            <div className="players-stack">
              <PlayerCard player={p2} active={game.turn === "P2" && snapshot.status === "PLAYING"} me={snapshot.me === "P2"} walls={game.wallsRemaining.P2} />
              <div className="versus">대</div>
              <PlayerCard player={p1} active={game.turn === "P1" && snapshot.status === "PLAYING"} me={snapshot.me === "P1"} walls={game.wallsRemaining.P1} />
            </div>
            {error && <p className="form-error" role="alert">{error}</p>}
          </aside>
          <Board snapshot={snapshot} onAction={submitAction} />
          {snapshot.status === "FINISHED" && (
            <div className="result-backdrop">
              <section className="result-card" role="dialog" aria-modal="true" aria-label="게임 결과">
                <span className={`result-pawn ${game.winner === "P2" ? "clay" : "green"}`} />
                <h2>{winner?.nickname} 승리</h2>
                <p>{game.finishReason === "TIMEOUT" ? "제한 시간이 끝났습니다." : "반대편 끝에 먼저 도착했습니다."}</p>
                <button className="primary-button" onClick={rematch} disabled={me?.rematchReady}>{me?.rematchReady ? "상대의 선택을 기다리는 중" : "재대결"}</button>
                <button className="text-button" onClick={onExit}>방 나가기</button>
              </section>
            </div>
          )}
        </div>
      ) : null}
    </main>
  );
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) ?? "");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [restoring, setRestoring] = useState(Boolean(token));

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("crossway-theme", theme);
  }, [theme]);

  const connect = useCallback((sessionToken: string) => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws?token=${encodeURIComponent(sessionToken)}`);
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "room.snapshot") setSnapshot(message.payload);
    };
    return socket;
  }, []);

  useEffect(() => {
    if (!token) { setRestoring(false); return; }
    let socket: WebSocket | undefined;
    api<Snapshot>("/api/v1/session", {}, token)
      .then((restored) => { setSnapshot(restored); socket = connect(token); })
      .catch(() => { localStorage.removeItem(TOKEN_KEY); setToken(""); })
      .finally(() => setRestoring(false));
    return () => socket?.close();
  }, [token, connect]);

  const beginSession = (sessionToken: string, initial: Snapshot) => {
    localStorage.setItem(TOKEN_KEY, sessionToken);
    setSnapshot(initial);
    setToken(sessionToken);
  };

  const exit = () => {
    localStorage.removeItem(TOKEN_KEY);
    setToken("");
    setSnapshot(null);
  };

  return (
    <div className="app">
      <nav className="topbar"><ThemeToggle theme={theme} onToggle={() => setTheme(theme === "light" ? "dark" : "light")} /></nav>
      {restoring ? <div className="loading"><span /><p>게임을 불러오는 중</p></div> : snapshot && token ? <Room snapshot={snapshot} token={token} onExit={exit} /> : <Landing onSession={beginSession} />}
    </div>
  );
}
