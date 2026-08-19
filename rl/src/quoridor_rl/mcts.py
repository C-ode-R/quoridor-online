from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np
import torch

from quoridor_sdk import Action, MovePawn

from .encoding import ACTION_SIZE, encode_action, encode_state, legal_action_mask
from .env import QuoridorEnv
from .model import PolicyValueNet


@dataclass(slots=True)
class Node:
    prior: float
    visit_count: int = 0
    value_sum: float = 0.0
    children: dict[Action, "Node"] = field(default_factory=dict)
    root_noise_applied: bool = False
    fully_expanded: bool = False

    @property
    def value(self) -> float:
        return self.value_sum / self.visit_count if self.visit_count else 0.0


class MCTS:
    """PUCT search with subtree reuse, repetition-aware state keys and NN cache."""

    def __init__(
        self,
        model: PolicyValueNet,
        *,
        simulations: int = 100,
        c_puct: float = 1.25,
        c_base: float = 19_652.0,
        fpu_reduction: float = 0.20,
        device: str = "cpu",
        wall_candidates: int = 24,
        heuristic_weight: float = 0.25,
        cache_size: int = 50_000,
    ):
        self.model = model
        self.simulations = simulations
        self.c_puct = c_puct
        self.c_base = c_base
        self.fpu_reduction = fpu_reduction
        self.device = device
        self.wall_candidates = wall_candidates
        self.heuristic_weight = min(1.0, max(0.0, heuristic_weight))
        self.cache_size = cache_size
        self._root: Node | None = None
        self._root_key: tuple | None = None
        self._root_env: QuoridorEnv | None = None
        self._inference_cache: OrderedDict[
            tuple, tuple[tuple[Action, ...], np.ndarray, float]
        ] = OrderedDict()
        self.cache_hits = 0
        self.cache_misses = 0
        self.reused_roots = 0

    def reset_tree(self, *, clear_cache: bool = False) -> None:
        self._root = None
        self._root_key = None
        self._root_env = None
        if clear_cache:
            self._inference_cache.clear()

    def search(
        self,
        env: QuoridorEnv,
        *,
        temperature: float = 1.0,
        add_noise: bool = False,
    ) -> tuple[Action, np.ndarray]:
        state_key = env.search_key()
        if self._root is not None and self._root_key != state_key:
            self._synchronize_one_ply(env)
        if self._root is None or self._root_key != state_key:
            self._root = Node(prior=1.0)
            self._root_key = state_key
            self._root_env = env.clone()
        else:
            self.reused_roots += 1
        root = self._root
        # A node may have first been expanded as an internal node with a bounded
        # wall set. Once it becomes the real root, widen it to every legal move
        # so candidate pruning can never hide the move that is actually played.
        if not root.fully_expanded:
            self._expand(root, env, full_expansion=True)
        if not root.children:
            raise RuntimeError("MCTS received a state with no searchable actions")

        if add_noise and not root.root_noise_applied:
            # Keep total Dirichlet concentration roughly stable as the root
            # grows from a few pawn moves to more than one hundred legal walls.
            alpha = min(0.30, max(0.03, 10.0 / len(root.children)))
            noise = np.random.dirichlet([alpha] * len(root.children))
            for child, sample in zip(root.children.values(), noise):
                child.prior = 0.75 * child.prior + 0.25 * float(sample)
            root.root_noise_applied = True

        visits_before = {
            action: child.visit_count for action, child in root.children.items()
        }
        for _ in range(self.simulations):
            simulation = env.clone()
            node = root
            path = [node]

            while node.children and not simulation.state.done:
                action, node = self._select(node)
                simulation.step(action, validate=False)
                path.append(node)

            if simulation.state.done:
                winner = simulation.state.winner
                value = (
                    0.0
                    if winner is None
                    else (1.0 if winner == simulation.state.turn else -1.0)
                )
            else:
                value = self._expand(node, simulation)

            for visited in reversed(path):
                visited.visit_count += 1
                visited.value_sum += value
                value = -value

        actions = list(root.children)
        visits = np.array(
            [
                max(0, root.children[action].visit_count - visits_before[action])
                for action in actions
            ],
            dtype=np.float64,
        )
        if visits.sum() <= 0:
            visits.fill(1.0)
        if temperature <= 1e-6:
            probabilities = np.zeros_like(visits)
            probabilities[int(np.argmax(visits))] = 1.0
        else:
            scaled = np.power(visits, 1.0 / temperature)
            probabilities = scaled / scaled.sum()

        chosen_index = int(np.random.choice(len(actions), p=probabilities))
        chosen_action = actions[chosen_index]
        policy = np.zeros(ACTION_SIZE, dtype=np.float32)
        player = env.state.turn
        for action, probability in zip(actions, probabilities):
            policy[encode_action(action, player)] = probability

        # Keep the explored subtree for the next real move.
        next_env = env.clone()
        next_env.step(chosen_action, validate=False)
        self._root = root.children[chosen_action]
        self._root_key = next_env.search_key()
        self._root_env = next_env
        return chosen_action, policy

    def _synchronize_one_ply(self, env: QuoridorEnv) -> None:
        """Reuse the opponent branch when an external/API move was played."""
        if self._root is None or self._root_env is None or not self._root.children:
            return
        target_key = env.inference_key()
        for action, child in self._root.children.items():
            candidate = self._root_env.clone()
            candidate.step(action, validate=False)
            if candidate.inference_key() == target_key:
                self._root = child
                self._root_key = env.search_key()
                self._root_env = env.clone()
                self.reused_roots += 1
                return

    def _select(self, node: Node) -> tuple[Action, Node]:
        parent_visits = max(1, node.visit_count)
        explored_prior = sum(
            child.prior for child in node.children.values() if child.visit_count > 0
        )
        fpu_value = node.value - self.fpu_reduction * math.sqrt(explored_prior)
        pb_c = self.c_puct + math.log(
            (parent_visits + self.c_base + 1.0) / self.c_base
        )
        scale = math.sqrt(parent_visits)

        def score(item: tuple[Action, Node]) -> float:
            _action, child = item
            q_value = -child.value if child.visit_count else fpu_value
            exploration = pb_c * child.prior * scale / (1 + child.visit_count)
            return q_value + exploration

        return max(node.children.items(), key=score)

    def _expand(
        self,
        node: Node,
        env: QuoridorEnv,
        *,
        full_expansion: bool = False,
    ) -> float:
        cache_key = (full_expansion, env.inference_key())
        cached = self._inference_cache.get(cache_key)
        if cached is not None:
            self.cache_hits += 1
            self._inference_cache.move_to_end(cache_key)
            actions, probabilities, value = cached
        else:
            self.cache_misses += 1
            actions = (
                env.legal_actions()
                if full_expansion
                else env.search_actions(max_wall_candidates=self.wall_candidates)
            )
            if not actions:
                return 0.0
            observation = (
                torch.from_numpy(encode_state(env.state)).unsqueeze(0).to(self.device)
            )
            with torch.no_grad():
                logits, predicted_value = self.model(observation)
            logits_array = logits[0].detach().cpu().numpy()
            mask = legal_action_mask(actions, env.state.turn)
            masked = np.where(mask, logits_array, -1e9)
            masked -= masked.max()
            network_probabilities = np.exp(masked) * mask
            network_probabilities /= network_probabilities.sum()
            heuristic_probabilities = self._heuristic_policy(actions, env)
            probabilities = (
                (1.0 - self.heuristic_weight) * network_probabilities
                + self.heuristic_weight * heuristic_probabilities
            ).astype(np.float32)
            value = float(predicted_value.item())
            self._inference_cache[cache_key] = (actions, probabilities, value)
            if len(self._inference_cache) > self.cache_size:
                self._inference_cache.popitem(last=False)

        player = env.state.turn
        for action in actions:
            prior = float(probabilities[encode_action(action, player)])
            child = node.children.get(action)
            if child is None:
                node.children[action] = Node(prior=prior)
            else:
                # Preserve visits/value accumulated while this was an internal
                # node, but refresh the prior from the full root action set.
                child.prior = prior
        if full_expansion:
            node.fully_expanded = True
        return value

    @staticmethod
    def _heuristic_policy(actions: tuple[Action, ...], env: QuoridorEnv) -> np.ndarray:
        weights = np.zeros(ACTION_SIZE, dtype=np.float64)
        player = env.state.turn
        opponent = "P2" if player == "P1" else "P1"
        move_entries: list[tuple[int, float]] = []
        wall_entries: list[tuple[int, float]] = []
        base_distance = len(env.shortest_path(player)) - 1
        opponent_distance = len(env.shortest_path(opponent)) - 1
        wall_actions = tuple(
            action for action in actions if not isinstance(action, MovePawn)
        )
        # The bounded action generator is ordered by measured path impact. For
        # a fully expanded root, use that strategic subset as the heuristic
        # preference and leave the neural policy free to surface other walls.
        ordered_preferred_walls = wall_actions
        if len(wall_actions) > 24:
            ordered_preferred_walls = tuple(
                action
                for action in env.search_actions(max_wall_candidates=24)
                if not isinstance(action, MovePawn)
            )
        preferred_walls = {
            action: rank for rank, action in enumerate(ordered_preferred_walls)
        }
        for action in actions:
            index = encode_action(action, player)
            if isinstance(action, MovePawn):
                goal_row = 0 if player == "P1" else 8
                if action.to.row == goal_row:
                    move_entries.append((index, 30.0))
                else:
                    original = env.state.pawns[player]
                    env.state.pawns[player] = action.to
                    new_distance = len(env.shortest_path(player)) - 1
                    env.state.pawns[player] = original
                    move_entries.append(
                        (index, math.exp(1.4 * (base_distance - new_distance)))
                    )
            else:
                rank = preferred_walls.get(action)
                if rank is None:
                    wall_entries.append((index, 0.15))
                else:
                    relative_rank = rank / max(1, len(preferred_walls) - 1)
                    wall_entries.append((index, 1.4 - 0.8 * relative_rank))

        wall_budget = 0.0
        if wall_entries:
            wall_budget = 0.45 if opponent_distance <= base_distance else 0.30
        move_budget = 1.0 - wall_budget
        move_total = sum(weight for _index, weight in move_entries)
        wall_total = sum(weight for _index, weight in wall_entries)
        for index, weight in move_entries:
            weights[index] = move_budget * weight / max(move_total, 1e-12)
        for index, weight in wall_entries:
            weights[index] = wall_budget * weight / max(wall_total, 1e-12)
        total = weights.sum()
        if total <= 0:
            mask = legal_action_mask(actions, player)
            return mask.astype(np.float64) / mask.sum()
        return weights / total
