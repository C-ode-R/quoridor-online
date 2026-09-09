import type { GameAction, GameState, PlayerId } from "@quoridor/game-engine";

export type PlayerView = {
  id: PlayerId;
  nickname: string;
  clientType: "HUMAN" | "BOT";
  connected: boolean;
  rematchReady: boolean;
};

export type Snapshot = {
  roomCode: string;
  tournamentCode: string | null;
  status: "WAITING" | "PLAYING" | "FINISHED";
  gameId: string | null;
  me: PlayerId | null;
  spectatorCount: number;
  players: PlayerView[];
  game: (GameState & {
    turnDeadline: string | null;
    finishReason: "GOAL" | "TIMEOUT" | "FORFEIT" | null;
    legalActions: GameAction[];
  }) | null;
};

export type TournamentMatch = {
  id: string;
  round: number;
  slot: number;
  player1: string | null;
  player2: string | null;
  winner: string | null;
  status: "PENDING" | "READY" | "WAITING" | "PLAYING" | "FINISHED" | "BYE" | "FORFEIT";
  roomCode: string | null;
  finishReason: "GOAL" | "TIMEOUT" | "FORFEIT" | "BYE" | null;
};

export type TournamentSnapshot = {
  code: string;
  name: string;
  participants: string[];
  rounds: TournamentMatch[][];
  status: "ACTIVE" | "FINISHED";
  winner: string | null;
};
