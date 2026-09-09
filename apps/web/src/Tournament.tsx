import { useEffect, useMemo, useState } from "react";
import type { Snapshot, TournamentMatch, TournamentSnapshot } from "./types";

type RequestError = Error & { code?: string };

async function request<T>(path: string, options: RequestInit = {}, token?: string): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  const body = await response.json();
  if (!response.ok) {
    const requestError = new Error(body.error?.code ?? "REQUEST_FAILED") as RequestError;
    requestError.code = body.error?.code;
    throw requestError;
  }
  return body as T;
}

const ADMIN_PREFIX = "crossway-tournament-admin:";
const NICKNAME_KEY = "crossway-tournament-nickname";

const roundName = (index: number, total: number) => {
  const remaining = total - index;
  if (remaining === 1) return "결승";
  if (remaining === 2) return "준결승";
  return `${index + 1}라운드`;
};

const statusLabel: Record<TournamentMatch["status"], string> = {
  PENDING: "이전 경기 대기",
  READY: "경기 준비",
  WAITING: "선수 입장 대기",
  PLAYING: "진행 중",
  FINISHED: "종료",
  BYE: "부전승",
  FORFEIT: "기권승",
};

function MatchCard({
  match,
  admin,
  nickname,
  busy,
  onStart,
  onJoin,
  onWatch,
  onForfeit,
}: {
  match: TournamentMatch;
  admin: boolean;
  nickname: string;
  busy: string;
  onStart: () => void;
  onJoin: () => void;
  onWatch: () => void;
  onForfeit: (loser: string) => void;
}) {
  const isParticipant = [match.player1, match.player2].some(
    (player) => player?.toLocaleLowerCase() === nickname.trim().toLocaleLowerCase(),
  );
  const activeRoom = Boolean(match.roomCode) && (match.status === "WAITING" || match.status === "PLAYING");

  return (
    <article className={`bracket-match status-${match.status.toLowerCase()}`}>
      <div className="match-meta">
        <span>{match.id}</span>
        <b>{statusLabel[match.status]}</b>
      </div>
      {[match.player1, match.player2].map((player, index) => (
        <div className={`bracket-player ${match.winner === player ? "winner" : ""}`} key={`${match.id}-${index}`}>
          <span>{player ?? "미정"}</span>
          {player && match.winner === player && <b>승</b>}
          {admin && player && !match.winner && match.player1 && match.player2 && (
            <button className="forfeit-button" disabled={Boolean(busy)} onClick={() => onForfeit(player)}>기권</button>
          )}
        </div>
      ))}
      {match.roomCode && <button className="match-code" onClick={() => navigator.clipboard.writeText(match.roomCode!)}>방 {match.roomCode} · 복사</button>}
      <div className="match-actions">
        {admin && match.status === "READY" && <button disabled={Boolean(busy)} onClick={onStart}>대결 시작</button>}
        {activeRoom && isParticipant && <button className="accent-action" disabled={Boolean(busy)} onClick={onJoin}>선수 입장</button>}
        {activeRoom && <button disabled={Boolean(busy)} onClick={onWatch}>관전</button>}
      </div>
    </article>
  );
}

export default function Tournament({
  initialCode,
  onCodeChange,
  onClose,
  onSession,
  onWatch,
}: {
  initialCode: string;
  onCodeChange: (code: string) => void;
  onClose: () => void;
  onSession: (token: string, snapshot: Snapshot) => void;
  onWatch: (snapshot: Snapshot) => void;
}) {
  const [tournament, setTournament] = useState<TournamentSnapshot | null>(null);
  const [lookupCode, setLookupCode] = useState(initialCode);
  const [name, setName] = useState("동아리 토너먼트");
  const [participantText, setParticipantText] = useState("");
  const [nickname, setNickname] = useState(() => localStorage.getItem(NICKNAME_KEY) ?? "");
  const [adminToken, setAdminToken] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const participants = useMemo(
    () => participantText.split("\n").map((entry) => entry.trim()).filter(Boolean),
    [participantText],
  );

  useEffect(() => {
    if (!initialCode) return;
    let disposed = false;
    request<TournamentSnapshot>(`/api/v1/tournaments/${initialCode}`)
      .then((snapshot) => {
        if (disposed) return;
        setTournament(snapshot);
        setAdminToken(localStorage.getItem(`${ADMIN_PREFIX}${snapshot.code}`) ?? "");
      })
      .catch(() => { if (!disposed) setError("대회를 찾을 수 없습니다."); });
    return () => { disposed = true; };
  }, [initialCode]);

  useEffect(() => {
    if (!tournament) return;
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    let disposed = false;
    let socket: WebSocket | undefined;
    let reconnectTimer: number | undefined;
    const connect = () => {
      if (disposed) return;
      socket = new WebSocket(`${protocol}//${window.location.host}/ws?tournament=${tournament.code}`);
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "tournament.snapshot") setTournament(message.payload);
      };
      socket.onclose = () => { if (!disposed) reconnectTimer = window.setTimeout(connect, 1_000); };
    };
    connect();
    return () => {
      disposed = true;
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [tournament?.code]);

  const create = async () => {
    if (participants.length < 2) return setError("참가자를 한 줄에 한 명씩 2명 이상 입력해주세요.");
    setBusy("create");
    setError("");
    try {
      const result = await request<{ adminToken: string; tournament: TournamentSnapshot }>("/api/v1/tournaments", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), participants }),
      });
      localStorage.setItem(`${ADMIN_PREFIX}${result.tournament.code}`, result.adminToken);
      setAdminToken(result.adminToken);
      setTournament(result.tournament);
      setLookupCode(result.tournament.code);
      onCodeChange(result.tournament.code);
    } catch (requestError) {
      const code = requestError instanceof Error ? requestError.message : "";
      setError(code === "DUPLICATE_PARTICIPANT" ? "참가자 이름은 중복될 수 없습니다." : "대진표를 만들지 못했습니다.");
    } finally {
      setBusy("");
    }
  };

  const open = async () => {
    if (lookupCode.trim().length !== 6) return setError("6자리 대회 코드를 입력해주세요.");
    setBusy("open");
    setError("");
    try {
      const snapshot = await request<TournamentSnapshot>(`/api/v1/tournaments/${lookupCode.trim().toUpperCase()}`);
      setTournament(snapshot);
      setAdminToken(localStorage.getItem(`${ADMIN_PREFIX}${snapshot.code}`) ?? "");
      onCodeChange(snapshot.code);
    } catch {
      setError("대회를 찾을 수 없습니다.");
    } finally {
      setBusy("");
    }
  };

  const startMatch = async (match: TournamentMatch) => {
    setBusy(match.id);
    setError("");
    try {
      const result = await request<{ tournament: TournamentSnapshot }>(
        `/api/v1/tournaments/${tournament!.code}/matches/${match.id}/start`,
        { method: "POST", body: "{}" },
        adminToken,
      );
      setTournament(result.tournament);
    } catch {
      setError("경기를 시작하지 못했습니다.");
    } finally {
      setBusy("");
    }
  };

  const forfeit = async (match: TournamentMatch, loser: string) => {
    if (!window.confirm(`${loser} 선수를 기권 처리할까요?`)) return;
    setBusy(match.id);
    setError("");
    try {
      const result = await request<{ tournament: TournamentSnapshot }>(
        `/api/v1/tournaments/${tournament!.code}/matches/${match.id}/forfeit`,
        { method: "POST", body: JSON.stringify({ loser }) },
        adminToken,
      );
      setTournament(result.tournament);
    } catch {
      setError("기권 처리하지 못했습니다.");
    } finally {
      setBusy("");
    }
  };

  const joinMatch = async (match: TournamentMatch) => {
    if (!match.roomCode || !nickname.trim()) return setError("대진표 위에 참가자 이름을 입력해주세요.");
    setBusy(match.id);
    setError("");
    localStorage.setItem(NICKNAME_KEY, nickname.trim());
    try {
      const result = await request<{ playerToken: string; snapshot: Snapshot }>(`/api/v1/rooms/${match.roomCode}/join`, {
        method: "POST",
        body: JSON.stringify({ nickname: nickname.trim(), clientType: "HUMAN" }),
      });
      onSession(result.playerToken, result.snapshot);
    } catch (requestError) {
      const code = requestError instanceof Error ? requestError.message : "";
      setError(code === "TOURNAMENT_SEAT_REQUIRED" ? "이 경기의 선수 이름과 일치하지 않습니다." : code === "ROOM_FULL" ? "두 선수가 이미 입장했습니다." : "경기에 입장하지 못했습니다.");
    } finally {
      setBusy("");
    }
  };

  const watchMatch = async (match: TournamentMatch) => {
    if (!match.roomCode) return;
    setBusy(match.id);
    setError("");
    try {
      onWatch(await request<Snapshot>(`/api/v1/rooms/${match.roomCode}/watch`));
    } catch {
      setError("관전 화면을 열지 못했습니다.");
    } finally {
      setBusy("");
    }
  };

  if (!tournament) {
    return (
      <main className="tournament-entry">
        <section className="tournament-form">
          <div className="section-heading"><h1>대진표</h1><button className="text-button" onClick={onClose}>게임으로</button></div>
          <label><span>대회 이름</span><input maxLength={40} value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label><span>참가자 · 한 줄에 한 명</span><textarea value={participantText} onChange={(event) => setParticipantText(event.target.value)} placeholder={"민준\n서연\n지후\n하윤"} /></label>
          <div className="participant-count">{participants.length}명 · 최대 32명</div>
          <button className="primary-button" disabled={Boolean(busy)} onClick={create}>랜덤 대진 만들기</button>
          <div className="divider"><span>기존 대회 열기</span></div>
          <div className="code-row">
            <input aria-label="대회 코드" maxLength={6} value={lookupCode} onChange={(event) => setLookupCode(event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))} placeholder="ABC123" />
            <button disabled={Boolean(busy)} onClick={open}>열기</button>
          </div>
          {error && <p className="form-error" role="alert">{error}</p>}
        </section>
      </main>
    );
  }

  return (
    <main className="tournament-shell">
      <header className="tournament-header">
        <div>
          <span className="room-label">대회 코드</span>
          <button className="room-code" onClick={() => navigator.clipboard.writeText(tournament.code)}>{tournament.code} <small>복사</small></button>
        </div>
        <div className="tournament-title"><h1>{tournament.name}</h1><p>{tournament.participants.length}명 · {adminToken ? "운영자" : "관전자"}</p></div>
        <button className="text-button" onClick={onClose}>나가기</button>
      </header>
      <section className="tournament-controls">
        <label><span>내 참가자 이름</span><input maxLength={20} value={nickname} onChange={(event) => setNickname(event.target.value)} placeholder="대진표의 이름과 같게 입력" /></label>
        {tournament.winner && <div className="champion"><span>우승</span><strong>{tournament.winner}</strong></div>}
      </section>
      {error && <p className="form-error tournament-error" role="alert">{error}</p>}
      <div className="bracket-scroll">
        <div className="bracket" style={{ gridTemplateColumns: `repeat(${tournament.rounds.length}, minmax(230px, 1fr))` }}>
          {tournament.rounds.map((round, roundIndex) => (
            <section className="bracket-round" key={roundIndex}>
              <h2>{roundName(roundIndex, tournament.rounds.length)}</h2>
              <div className="round-matches">
                {round.map((match) => (
                  <MatchCard
                    key={match.id}
                    match={match}
                    admin={Boolean(adminToken)}
                    nickname={nickname}
                    busy={busy}
                    onStart={() => startMatch(match)}
                    onJoin={() => joinMatch(match)}
                    onWatch={() => watchMatch(match)}
                    onForfeit={(loser) => forfeit(match, loser)}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
    </main>
  );
}
