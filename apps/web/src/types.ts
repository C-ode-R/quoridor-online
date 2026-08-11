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
  status: "WAITING" | "PLAYING" | "FINISHED";
  gameId: string | null;
  me: PlayerId | null;
  players: PlayerView[];
  game: (GameState & {
    turnDeadline: string | null;
    finishReason: "GOAL" | "TIMEOUT" | null;
    legalActions: GameAction[];
  }) | null;
};
