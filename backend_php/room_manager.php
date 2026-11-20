<?php

declare(strict_types=1);

class Room
{
    public string $code;
    public string $host_id;
    public bool $single_player;
    public int $room_size;

    /** @var array<string,string> pid -> name */
    public array $players = [];
    /** @var array<string,mixed> pid -> Ratchet connection (humans only) */
    public array $player_ws = [];
    /** @var array<string,bool> */
    public array $bot_ids = [];
    /** @var array<string,int> */
    public array $scores = [];

    public string $state = 'lobby'; // lobby | drafting | guessing | result | game_over
    public int $round_number = 0;
    /** @var array<int,array> */
    public array $history = [];

    public int $assignment_offset = 0;
    /** @var array<string,string> pid -> attribute */
    public array $assignments = [];
    /** @var array<string,array> pid -> options */
    public array $draft_options = [];
    /** @var array<string,int> pid -> refreshes left */
    public array $draft_refreshes_left = [];
    /** @var array<string,mixed> pid -> chosen value */
    public array $selections = [];
    /** @var array<string,mixed> attribute -> chosen value (auto-filled, e.g. duo mode) */
    public array $system_selections = [];
    /** @var array<string,array{ text:string, submitted_at:float }> */
    public array $guesses = [];
    public $round_result = null;
    public $winner_id = null;

    public $guess_deadline = null;
    public $guess_task = null;
    public $draft_deadline = null;
    public $draft_task = null;

    /** @var array<string,int> join order */
    private array $join_order = [];
    private int $join_seq = 0;

    public function __construct(string $code, string $host_id, bool $single_player = false, ?int $room_size = null)
    {
        $this->code = $code;
        $this->host_id = $host_id;
        $this->single_player = $single_player;
        $this->room_size = $room_size ?? ROOM_SIZE;
    }

    // --- player management ---
    public function add_player(string $pid, string $name, $ws): bool
    {
        if (count($this->players) >= $this->room_size) {
            return false;
        }
        $this->players[$pid] = $name;
        $this->player_ws[$pid] = $ws;
        if (!isset($this->scores[$pid])) {
            $this->scores[$pid] = 0;
        }
        if (!isset($this->join_order[$pid])) {
            $this->join_order[$pid] = $this->join_seq++;
        }
        return true;
    }

    public function add_bot(string $name): ?string
    {
        if (count($this->players) >= $this->room_size) {
            return null;
        }
        $pid = 'bot-' . (count($this->bot_ids) + 1);
        $this->players[$pid] = $name;
        $this->bot_ids[$pid] = true;
        if (!isset($this->scores[$pid])) {
            $this->scores[$pid] = 0;
        }
        if (!isset($this->join_order[$pid])) {
            $this->join_order[$pid] = $this->join_seq++;
        }
        return $pid;
    }

    public function is_bot(string $pid): bool
    {
        return isset($this->bot_ids[$pid]);
    }

    public function remove_player(string $pid): void
    {
        unset($this->players[$pid]);
        unset($this->player_ws[$pid]);
        unset($this->bot_ids[$pid]);
        unset($this->scores[$pid]);
        unset($this->selections[$pid]);
        unset($this->guesses[$pid]);
        unset($this->join_order[$pid]);
        if ($pid === $this->host_id && count($this->players) > 0) {
            $this->host_id = array_key_first($this->players);
        }
    }

    public function detach_player(string $pid): void
    {
        unset($this->player_ws[$pid]);
    }

    public function attach_player(string $pid, $ws): bool
    {
        if (isset($this->players[$pid]) && !$this->is_bot($pid)) {
            $this->player_ws[$pid] = $ws;
            return true;
        }
        return false;
    }

    public function player_list(): array
    {
        $ordered = $this->_ordered_pids();
        $out = [];
        foreach ($ordered as $pid) {
            $out[] = [
                'id' => $pid,
                'name' => $this->players[$pid] ?? '?',
                'score' => $this->scores[$pid] ?? 0,
                'isHost' => $pid === $this->host_id,
                'isBot' => $this->is_bot($pid),
            ];
        }
        return $out;
    }

    public function broadcast(array $msg, ?string $exclude_pid = null): void
    {
        $payload = json_encode($msg, JSON_UNESCAPED_UNICODE);
        $dead = [];
        foreach ($this->player_ws as $pid => $ws) {
            if ($exclude_pid !== null && $pid === $exclude_pid) {
                continue;
            }
            try {
                $ws->send($payload);
            } catch (\Throwable $e) {
                $dead[] = $pid;
            }
        }
        foreach ($dead as $pid) {
            $this->detach_player($pid);
        }
    }

    public function send_to(string $pid, array $msg): void
    {
        if (!isset($this->player_ws[$pid])) {
            return;
        }
        $ws = $this->player_ws[$pid];
        try {
            $ws->send(json_encode($msg, JSON_UNESCAPED_UNICODE));
        } catch (\Throwable $e) {
            $this->detach_player($pid);
        }
    }

    // --- helpers ---
    public function all_players_connected(): bool
    {
        return count($this->players) === $this->room_size;
    }

    public function attribute_for(string $pid): ?string
    {
        return $this->assignments[$pid] ?? null;
    }

    public function _ordered_pids(): array
    {
        $pids = array_keys($this->players);
        usort($pids, function ($a, $b) {
            $oa = $this->join_order[$a] ?? PHP_INT_MAX;
            $ob = $this->join_order[$b] ?? PHP_INT_MAX;
            if ($oa === $ob) return strcmp($a, $b);
            return $oa <=> $ob;
        });
        return $pids;
    }

    public function required_selections(): int
    {
        return count($this->assignments);
    }

    // --- game flow ---
    public function start_round($loop = null): bool
    {
        if (count($this->players) !== $this->room_size) {
            return false;
        }
        $this->cancel_guess_timer($loop);
        $this->cancel_draft_timer($loop);
        $this->state = 'drafting';
        $this->round_number += 1;
        $this->selections = [];
        $this->system_selections = [];
        $this->guesses = [];
        $this->round_result = null;
        $this->guess_deadline = null;
        $this->draft_deadline = microtime(true) + DRAFT_COUNTDOWN;

        $pids = $this->_ordered_pids();
        $attrs = array_values(ATTRIBUTE_ORDER);
        $this->assignments = [];
        $this->draft_options = [];
        $this->draft_refreshes_left = [];

        if ($this->room_size === 2) {
            foreach ($pids as $i => $pid) {
                $attr = $attrs[($i + $this->assignment_offset) % count($attrs)];
                $this->assignments[$pid] = $attr;
                $this->draft_options[$pid] = DataLoader::sampleOptions($attr, DRAFT_OPTIONS);
                $this->draft_refreshes_left[$pid] = in_array($attr, ['country', 'position', 'club'], true) ? 3 : 0;
            }
            $assigned = array_values(array_unique(array_values($this->assignments)));
            $missing = [];
            foreach ($attrs as $a) {
                if (!in_array($a, $assigned, true)) {
                    $missing[] = $a;
                }
            }
            if (count($missing) === 0) {
                $missing = [$attrs[($this->assignment_offset + 2) % count($attrs)]];
            }
            foreach ($missing as $attr) {
                $opts = DataLoader::sampleOptions($attr, DRAFT_OPTIONS);
                $choice = $this->_pick_bot_option($attr, $opts);
                $this->system_selections[$attr] = $choice;
            }
        } else {
            foreach ($pids as $i => $pid) {
                $attr = $attrs[($i + $this->assignment_offset) % count($attrs)];
                $this->assignments[$pid] = $attr;
                $this->draft_options[$pid] = DataLoader::sampleOptions($attr, DRAFT_OPTIONS);
                $this->draft_refreshes_left[$pid] = in_array($attr, ['country', 'position', 'club'], true) ? 3 : 0;
            }
        }

        $this->_auto_select_bots();
        return true;
    }

    public function _pick_bot_option(?string $attr, ?array $options)
    {
        $options = array_values(array_filter($options ?? [], function ($o) { return $o !== null && $o !== ''; }));
        if (count($options) === 0) {
            return null;
        }
        $opts = DataLoader::getOptions();
        $priority = [];
        if ($attr === 'country') {
            $priority = $opts['top_fifa_countries'] ?? [];
        } elseif ($attr === 'club') {
            $priority = $opts['top5_league_clubs'] ?? [];
        }

        $priorityInOptions = [];
        $others = [];
        if ($attr === 'club') {
            $priorityKeys = [];
            foreach ((is_array($priority) ? $priority : []) as $o) {
                $priorityKeys[DataLoader::clubId($o)] = true;
            }
            foreach ($options as $o) {
                if (isset($priorityKeys[DataLoader::clubId($o)])) {
                    $priorityInOptions[] = $o;
                } else {
                    $others[] = $o;
                }
            }
        } else {
            $prioritySet = [];
            foreach ((is_array($priority) ? $priority : []) as $o) {
                $prioritySet[strval($o)] = true;
            }
            foreach ($options as $o) {
                $key = is_array($o) ? json_encode($o) : strval($o);
                if (isset($prioritySet[strval($o)])) {
                    $priorityInOptions[] = $o;
                } else {
                    $others[] = $o;
                }
            }
        }

        if (count($priorityInOptions) > 0 && (count($others) === 0 || (mt_rand() / mt_getrandmax()) < 0.8)) {
            return $priorityInOptions[array_rand($priorityInOptions)];
        }
        return $options[array_rand($options)];
    }

    public function _auto_select_bots(): void
    {
        foreach (array_keys($this->bot_ids) as $pid) {
            if (array_key_exists($pid, $this->selections)) {
                continue;
            }
            $options = $this->draft_options[$pid] ?? [];
            $choice = $this->_pick_bot_option($this->assignments[$pid] ?? null, $options);
            if ($choice !== null) {
                $this->selections[$pid] = $choice;
            }
        }
    }

    public function _auto_guess_bots(): void
    {
        if ($this->state !== 'guessing') {
            return;
        }
        $constraints = $this->current_constraints();
        foreach (array_keys($this->bot_ids) as $pid) {
            if (array_key_exists($pid, $this->guesses)) {
                continue;
            }
            $guessText = DataLoader::bestGuessForConstraints($constraints);
            $this->guesses[$pid] = ['text' => $guessText, 'submitted_at' => microtime(true)];
        }
    }

    public function submit_selection(string $pid, $value): array
    {
        if ($this->state !== 'drafting') {
            return [false, 'Not in drafting phase'];
        }
        if (!isset($this->assignments[$pid])) {
            return [false, 'Not in this round'];
        }
        if (array_key_exists($pid, $this->selections)) {
            return [false, 'Already selected'];
        }
        $attr = $this->assignments[$pid];
        $options = $this->draft_options[$pid] ?? [];
        if ($attr === 'club') {
            $target = DataLoader::clubId($value);
            $match = null;
            foreach ($options as $o) {
                if (DataLoader::clubId($o) === $target) {
                    $match = $o;
                    break;
                }
            }
            if ($match === null) {
                return [false, 'Invalid selection'];
            }
            $this->selections[$pid] = $match;
            return [true, null];
        }
        // scalar comparison
        $found = false;
        foreach ($options as $o) {
            if ($o === $value) { $found = true; break; }
        }
        if (!$found) {
            return [false, 'Invalid selection'];
        }
        $this->selections[$pid] = $value;
        return [true, null];
    }

    private function opt_key_for_attr(string $attr, $o)
    {
        return $attr === 'club' ? DataLoader::clubId($o) : $o;
    }

    public function refresh_draft_options(string $pid): array
    {
        if ($this->state !== 'drafting') {
            return [false, 'Not in drafting phase', null, 0];
        }
        if (!isset($this->assignments[$pid])) {
            return [false, 'Not in this round', null, 0];
        }
        if (array_key_exists($pid, $this->selections)) {
            return [false, 'Already selected', null, 0];
        }
        $attr = $this->assignments[$pid];
        if (!in_array($attr, ['country', 'position', 'club'], true)) {
            return [false, 'Refresh not available for this attribute', null, 0];
        }
        $left = $this->draft_refreshes_left[$pid] ?? 0;
        if ($left <= 0) {
            return [false, 'No refreshes left', null, 0];
        }

        $currentOptions = $this->draft_options[$pid] ?? [];
        $options = DataLoader::sampleOptions($attr, DRAFT_OPTIONS);

        $currentKeys = [];
        foreach ($currentOptions as $o) {
            $currentKeys[$this->opt_key_for_attr($attr, $o)] = true;
        }
        $bestOptions = $options;
        $bestOverlap = 0;
        foreach ($options as $o) {
            $k = $this->opt_key_for_attr($attr, $o);
            if (isset($currentKeys[$k])) $bestOverlap++;
        }

        if ($bestOverlap > 0 && count($currentKeys) > 0) {
            for ($i = 0; $i < 25; $i++) {
                $candidate = DataLoader::sampleOptions($attr, DRAFT_OPTIONS);
                $overlap = 0;
                foreach ($candidate as $o) {
                    $k = $this->opt_key_for_attr($attr, $o);
                    if (isset($currentKeys[$k])) $overlap++;
                }
                if ($overlap < $bestOverlap) {
                    $bestOptions = $candidate;
                    $bestOverlap = $overlap;
                }
                if ($bestOverlap === 0) {
                    break;
                }
            }
        }
        $options = $bestOptions;

        $this->draft_options[$pid] = $options;
        $this->draft_refreshes_left[$pid] = $left - 1;
        return [true, null, $options, $this->draft_refreshes_left[$pid]];
    }

    public function auto_select_missing(): bool
    {
        $changed = false;
        foreach ($this->_ordered_pids() as $pid) {
            if (array_key_exists($pid, $this->selections)) {
                continue;
            }
            $options = $this->draft_options[$pid] ?? [];
            if (count($options) === 0) {
                $attr = $this->assignments[$pid] ?? null;
                if ($attr) {
                    $options = DataLoader::sampleOptions($attr, DRAFT_OPTIONS);
                    $this->draft_options[$pid] = $options;
                }
            }
            $choice = $this->_pick_bot_option($this->assignments[$pid] ?? null, $options);
            if ($choice !== null) {
                $this->selections[$pid] = $choice;
                $changed = true;
            }
        }
        return $changed;
    }

    public function all_selected(): bool
    {
        return count($this->selections) === $this->required_selections() && $this->all_players_connected();
    }

    public function current_constraints(): array
    {
        $out = $this->system_selections;
        foreach ($this->assignments as $pid => $attr) {
            if (array_key_exists($pid, $this->selections)) {
                $out[$attr] = $this->selections[$pid];
            }
        }
        return $out;
    }

    public function start_guessing($loop = null): bool
    {
        if ($this->state !== 'drafting') {
            return false;
        }
        $this->cancel_draft_timer($loop);
        $this->state = 'guessing';
        $this->guesses = [];
        $this->guess_deadline = microtime(true) + GUESS_COUNTDOWN;
        return true;
    }

    public function submit_guess(string $pid, $text): array
    {
        if ($this->state !== 'guessing') {
            return [false, 'Not in guessing phase'];
        }
        if (!isset($this->players[$pid])) {
            return [false, 'Not in room'];
        }
        if (array_key_exists($pid, $this->guesses)) {
            return [false, 'Already guessed'];
        }
        $guessText = trim(strval($text ?? ''));
        if ($guessText === '') {
            return [false, 'Guess cannot be empty'];
        }
        $this->guesses[$pid] = ['text' => $guessText, 'submitted_at' => microtime(true)];
        return [true, null];
    }

    public function all_guessed(): bool
    {
        return count($this->guesses) === $this->room_size && $this->all_players_connected();
    }

    private function _score_guess(string $guessText, array $constraints): array
    {
        $matches = DataLoader::findPlayerMatches($guessText);
        if (count($matches) === 0) {
            return [
                'guess' => $guessText,
                'matched_player' => null,
                'breakdown' => ['country' => false, 'position' => false, 'club' => false],
                'points' => 0,
            ];
        }
        $best = null;
        $countryC = $constraints['country'] ?? null;
        $positionC = $constraints['position'] ?? null;
        $clubC = $constraints['club'] ?? null;
        foreach ($matches as $player) {
            $clubsRaw = $player['clubs'] ?? [];
            $clubs = [];
            if (is_array($clubsRaw)) {
                foreach ($clubsRaw as $c) {
                    $cid = DataLoader::clubId($c);
                    if ($cid !== '') $clubs[] = $cid;
                }
            }
            $breakdown = [
                'country' => ($player['country'] ?? null) === $countryC,
                'position' => ($player['position'] ?? null) === $positionC,
                'club' => DataLoader::clubMatches($clubC, $clubs),
            ];
            $points = 0;
            foreach ($breakdown as $v) { if ($v) $points++; }
            $clubHistoryLen = count(array_unique($clubs));
            $name = trim(strval($player['name'] ?? ''));
            $playerIdStr = strval($player['player_id'] ?? '');
            $cand = [$points, $clubHistoryLen, $playerIdStr, $name, $player, $breakdown];
            if ($best === null) {
                $best = $cand;
            } else {
                // compare first 4 elements lexicographically (higher is better)
                if ($cand[0] > $best[0]
                    || ($cand[0] === $best[0] && $cand[1] > $best[1])
                    || ($cand[0] === $best[0] && $cand[1] === $best[1] && $cand[2] > $best[2])
                    || ($cand[0] === $best[0] && $cand[1] === $best[1] && $cand[2] === $best[2] && $cand[3] > $best[3])
                ) {
                    $best = $cand;
                }
            }
        }
        [, , , , $player, $breakdown] = $best;
        $points = 0;
        foreach ($breakdown as $v) { if ($v) $points++; }
        return [
            'guess' => $guessText,
            'matched_player' => [
                'player_id' => $player['player_id'] ?? null,
                'name' => $player['name'] ?? null,
                'country' => $player['country'] ?? null,
                'position' => $player['position'] ?? null,
            ],
            'breakdown' => $breakdown,
            'points' => $points,
        ];
    }

    public function finalize_round($loop = null): ?array
    {
        if ($this->state !== 'guessing') {
            return null;
        }
        $this->cancel_guess_timer($loop);
        $constraints = $this->current_constraints();
        $perPlayer = [];
        foreach ($this->_ordered_pids() as $pid) {
            $guessInfo = $this->guesses[$pid] ?? ['text' => ''];
            $scored = $this->_score_guess(strval($guessInfo['text'] ?? ''), $constraints);
            $points = intval($scored['points'] ?? 0);
            $this->scores[$pid] = ($this->scores[$pid] ?? 0) + $points;
            $perPlayer[$pid] = array_merge(
                [
                    'playerId' => $pid,
                    'name' => $this->players[$pid] ?? '?',
                ],
                $scored,
                ['totalScore' => $this->scores[$pid]]
            );
        }

        $winner_id = null;
        $draw = false;
        $maxScore = count($this->scores) > 0 ? max($this->scores) : 0;
        if ($maxScore >= WIN_SCORE) {
            $reached = [];
            foreach ($this->scores as $pid => $sc) {
                if ($sc >= WIN_SCORE) $reached[] = $pid;
            }
            if (count($reached) >= 2) {
                $draw = true;
                $winner_id = null;
            } else {
                $candidates = [];
                foreach ($this->scores as $pid => $sc) {
                    if ($sc === $maxScore && $sc >= WIN_SCORE) $candidates[] = $pid;
                }
                usort($candidates, function ($a, $b) {
                    $na = $this->players[$a] ?? '';
                    $nb = $this->players[$b] ?? '';
                    if ($na === $nb) return strcmp($a, $b);
                    return strcmp($na, $nb);
                });
                $winner_id = count($candidates) > 0 ? $candidates[0] : null;
            }
        }

        $assignmentsOut = [];
        foreach ($this->assignments as $pid => $attr) {
            $assignmentsOut[$pid] = ['attribute' => $attr, 'value' => $this->selections[$pid] ?? null];
        }
        foreach ($this->system_selections as $attr => $value) {
            $assignmentsOut['system:' . $attr] = ['attribute' => $attr, 'value' => $value, 'system' => true];
        }

        $bestAnswer = DataLoader::bestAnswerForConstraints($constraints);
        $resultsList = [];
        foreach ($this->_ordered_pids() as $pid) {
            if (isset($perPlayer[$pid])) $resultsList[] = $perPlayer[$pid];
        }
        $this->round_result = [
            'round' => $this->round_number,
            'constraints' => $constraints,
            'assignments' => $assignmentsOut,
            'results' => $resultsList,
            'standings' => $this->player_list(),
            'bestAnswer' => $bestAnswer,
            'winnerId' => $winner_id,
            'draw' => $draw,
            'gameOver' => ($winner_id !== null || $draw),
        ];
        $this->history[] = $this->round_result;

        if ($winner_id !== null || $draw) {
            $this->state = 'game_over';
            $this->winner_id = $winner_id;
        } else {
            $this->state = 'result';
            $attrCount = count(ATTRIBUTE_ORDER);
            if ($attrCount > 0) {
                $this->assignment_offset = ($this->assignment_offset + 1) % $attrCount;
            }
        }
        return $this->round_result;
    }

    public function cancel_guess_timer($loop = null): void
    {
        if ($this->guess_task !== null && $loop !== null) {
            try { $loop->cancelTimer($this->guess_task); } catch (\Throwable $e) {}
        }
        $this->guess_task = null;
        $this->guess_deadline = null;
    }

    public function cancel_draft_timer($loop = null): void
    {
        if ($this->draft_task !== null && $loop !== null) {
            try { $loop->cancelTimer($this->draft_task); } catch (\Throwable $e) {}
        }
        $this->draft_task = null;
        $this->draft_deadline = null;
    }

    public function guess_seconds_left(): ?int
    {
        if ($this->guess_deadline === null) return null;
        return max(0, (int)round($this->guess_deadline - microtime(true)));
    }

    public function draft_seconds_left(): ?int
    {
        if ($this->draft_deadline === null) return null;
        return max(0, (int)round($this->draft_deadline - microtime(true)));
    }

    public function state_snapshot(string $pid): array
    {
        $snapshot = [
            'type' => 'state_sync',
            'playerId' => $pid,
            'code' => $this->code,
            'isHost' => $pid === $this->host_id,
            'hostId' => $this->host_id,
            'state' => $this->state,
            'round' => $this->round_number,
            'players' => $this->player_list(),
            'history' => $this->history,
            'winScore' => WIN_SCORE,
            'roomSize' => $this->room_size,
        ];

        if ($this->state === 'drafting') {
            $attr = $this->assignments[$pid] ?? null;
            $options = $this->draft_options[$pid] ?? [];
            if ($attr && count($options) === 0) {
                $options = DataLoader::sampleOptions($attr, DRAFT_OPTIONS);
                $this->draft_options[$pid] = $options;
            }
            $snapshot['draft'] = [
                'attribute' => $attr,
                'attributeLabel' => $attr ? (ATTRIBUTE_LABELS[$attr] ?? $attr) : null,
                'options' => $options,
                'selected' => $this->selections[$pid] ?? null,
                'submittedCount' => count($this->selections),
                'requiredCount' => $this->required_selections(),
                'secondsLeft' => $this->draft_seconds_left() ?? 0,
                'refreshesLeft' => $this->draft_refreshes_left[$pid] ?? 0,
            ];
        } elseif ($this->state === 'guessing') {
            $snapshot['constraints'] = $this->current_constraints();
            $snapshot['guess'] = [
                'submitted' => array_key_exists($pid, $this->guesses),
                'submittedCount' => count($this->guesses),
                'requiredCount' => $this->room_size,
                'secondsLeft' => $this->guess_seconds_left() ?? 0,
            ];
        } elseif ($this->state === 'result' || $this->state === 'game_over') {
            $snapshot['result'] = $this->round_result;
        }

        return $snapshot;
    }
}

class RoomManager
{
    /** @var array<string,Room> */
    public array $rooms = [];

    private function gen_code(): string
    {
        $chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
        $code = '';
        for ($i = 0; $i < 5; $i++) {
            $code .= $chars[random_int(0, strlen($chars) - 1)];
        }
        return $code;
    }

    public function create_room(string $host_id, bool $single_player = false, ?int $room_size = null): string
    {
        $code = $this->gen_code();
        while (isset($this->rooms[$code])) {
            $code = $this->gen_code();
        }
        $this->rooms[$code] = new Room($code, $host_id, $single_player, $room_size);
        return $code;
    }

    public function get_room(?string $code): ?Room
    {
        if ($code === null) return null;
        $key = strtoupper($code);
        return $this->rooms[$key] ?? null;
    }

    public function remove_room(?string $code): void
    {
        if ($code === null) return;
        $key = strtoupper($code);
        unset($this->rooms[$key]);
    }
}

$manager = new RoomManager();
