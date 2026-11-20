<?php

declare(strict_types=1);

use Ratchet\MessageComponentInterface;
use Ratchet\ConnectionInterface;
use Ratchet\Server\IoServer;
use Ratchet\Http\HttpServer;
use Ratchet\WebSocket\WsServer;

require __DIR__ . '/vendor/autoload.php';

class FooTrioServer implements MessageComponentInterface
{
    /** @var \SplObjectStorage */
    protected $clients;
    /** @var RoomManager */
    protected $manager;
    /** @var \React\EventLoop\LoopInterface */
    protected $loop;

    public function __construct($loop)
    {
        $this->clients = new \SplObjectStorage();
        $this->loop = $loop;
        global $manager;
        $this->manager = $manager;
    }

    private function genUuid(): string
    {
        $data = random_bytes(16);
        $data[6] = chr((ord($data[6]) & 0x0f) | 0x40);
        $data[8] = chr((ord($data[8]) & 0x3f) | 0x80);
        return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($data), 4));
    }

    private function sendJson(ConnectionInterface $conn, array $msg): void
    {
        try {
            $conn->send(json_encode($msg, JSON_UNESCAPED_UNICODE));
        } catch (\Throwable $e) {
        }
    }

    private function broadcastLobby(Room $room): void
    {
        $room->broadcast([
            'type' => 'lobby_update',
            'players' => $room->player_list(),
            'hostId' => $room->host_id,
            'roomSize' => $room->room_size,
        ]);
    }

    private function sendDraftPrompts(Room $room): void
    {
        foreach ($room->assignments as $pid => $attr) {
            if ($room->is_bot($pid)) {
                continue;
            }
            $options = $room->draft_options[$pid] ?? [];
            if ($attr && count($options) === 0) {
                $options = DataLoader::sampleOptions($attr, DRAFT_OPTIONS);
                $room->draft_options[$pid] = $options;
            }
            $room->send_to($pid, [
                'type' => 'draft_prompt',
                'round' => $room->round_number,
                'attribute' => $attr,
                'attributeLabel' => ATTRIBUTE_LABELS[$attr] ?? $attr,
                'options' => $options,
                'selected' => $room->selections[$pid] ?? null,
                'secondsLeft' => $room->draft_seconds_left() ?? DRAFT_COUNTDOWN,
                'refreshesLeft' => $room->draft_refreshes_left[$pid] ?? 0,
            ]);
        }
        $room->broadcast([
            'type' => 'draft_status',
            'round' => $room->round_number,
            'submittedCount' => count($room->selections),
            'requiredCount' => $room->required_selections(),
            'secondsLeft' => $room->draft_seconds_left() ?? DRAFT_COUNTDOWN,
        ]);
    }

    private function sendStateSync(Room $room): void
    {
        foreach ($room->players as $pid => $_name) {
            if ($room->is_bot($pid)) {
                continue;
            }
            $room->send_to($pid, $room->state_snapshot($pid));
        }
    }

    private function startRound(Room $room): void
    {
        if (!$room->all_players_connected()) {
            return;
        }
        $room->start_round($this->loop);
        $room->broadcast([
            'type' => 'round_started',
            'round' => $room->round_number,
            'players' => $room->player_list(),
        ]);
        $this->sendDraftPrompts($room);
        $this->sendStateSync($room);
        if ($room->all_selected()) {
            $this->beginGuessing($room);
        } else {
            $this->scheduleDraftTimeout($room);
        }
    }

    private function scheduleDraftTimeout(Room $room): void
    {
        $room->cancel_draft_timer($this->loop);
        $timer = $this->loop->addTimer(DRAFT_COUNTDOWN, function () use ($room, &$timer) {
            // Only act if this is still the active timer
            if ($room->draft_task !== $timer) {
                return;
            }
            $room->draft_task = null;
            $room->draft_deadline = null;
            if ($room->state !== 'drafting') {
                return;
            }
            $room->auto_select_missing();
            $room->broadcast([
                'type' => 'draft_status',
                'round' => $room->round_number,
                'submittedCount' => count($room->selections),
                'requiredCount' => $room->required_selections(),
                'secondsLeft' => 0,
            ]);
            if ($room->all_selected()) {
                $this->beginGuessing($room);
            }
        });
        $room->draft_task = $timer;
    }

    private function beginGuessing(Room $room): void
    {
        if ($room->state !== 'drafting') {
            return;
        }
        $room->start_guessing($this->loop);
        $room->_auto_guess_bots();
        $constraints = $room->current_constraints();
        $room->broadcast([
            'type' => 'guess_phase',
            'round' => $room->round_number,
            'constraints' => $constraints,
            'secondsLeft' => GUESS_COUNTDOWN,
            'submittedCount' => count($room->guesses),
            'requiredCount' => $room->room_size,
        ]);
        $this->sendStateSync($room);
        if ($room->all_guessed()) {
            $this->finalizeAndBroadcast($room);
        } else {
            $this->scheduleGuessTimeout($room);
        }
    }

    private function scheduleGuessTimeout(Room $room): void
    {
        $room->cancel_guess_timer($this->loop);
        $timer = $this->loop->addTimer(GUESS_COUNTDOWN, function () use ($room, &$timer) {
            if ($room->guess_task !== $timer) {
                return;
            }
            $room->guess_task = null;
            $room->guess_deadline = null;
            if ($room->state !== 'guessing') {
                return;
            }
            $this->finalizeAndBroadcast($room);
        });
        $room->guess_task = $timer;
    }

    private function finalizeAndBroadcast(Room $room): void
    {
        if ($room->state !== 'guessing') {
            return;
        }
        $result = $room->finalize_round($this->loop);
        if ($result === null) {
            return;
        }
        $payload = array_merge(['type' => 'round_result'], $result, ['players' => $room->player_list()]);
        $room->broadcast($payload);

        if (!empty($result['gameOver'])) {
            $winner = null;
            $winnerId = $result['winnerId'] ?? null;
            foreach ($room->player_list() as $p) {
                if ($p['id'] === $winnerId) {
                    $winner = $p;
                    break;
                }
            }
            $room->broadcast([
                'type' => 'game_over',
                'winnerId' => $winnerId,
                'winnerName' => $winner ? ($winner['name'] ?? null) : null,
                'draw' => !empty($result['draw']),
                'players' => $room->player_list(),
                'history' => $room->history,
            ]);
        } else {
            // auto-start next round after a short reveal
            $delay = REVEAL_DELAY + 4;
            $this->loop->addTimer($delay, function () use ($room) {
                if ($room->state === 'result' && $room->all_players_connected()) {
                    $this->startRound($room);
                }
            });
        }
    }

    public function onOpen(ConnectionInterface $conn)
    {
        $this->clients->attach($conn);
        $conn->appState = [
            'player_id' => $this->genUuid(),
            'room' => null,
            'code' => null,
            'rejoined' => false,
            'explicit_leave' => false,
            'initialized' => false,
        ];
    }

    private function handleInitial(ConnectionInterface $from, array $data): void
    {
        $state = &$from->appState;
        $msgType = $data['type'] ?? null;

        if ($msgType === 'create_room') {
            $name = trim(strval($data['name'] ?? 'Player'));
            if ($name === '') $name = 'Player';
            $mode = strtolower(trim(strval($data['mode'] ?? 'multi')));
            $singlePlayer = in_array($mode, ['single', 'duo'], true);
            $roomSize = ($mode === 'duo') ? DUO_ROOM_SIZE : ROOM_SIZE;
            $playerId = $state['player_id'];
            $code = $this->manager->create_room($playerId, $singlePlayer, $roomSize);
            $room = $this->manager->get_room($code);
            if ($room === null) {
                $this->sendJson($from, ['type' => 'error', 'message' => 'Failed to create room']);
                $from->close();
                return;
            }
            $room->add_player($playerId, $name, $from);
            if ($mode === 'single') {
                $room->add_bot('Bot 1');
                $room->add_bot('Bot 2');
            } elseif ($mode === 'duo') {
                $room->add_bot('Bot 1');
            }
            $state['room'] = $room;
            $state['code'] = $code;
            $state['initialized'] = true;
            $state['rejoined'] = false;

            $this->sendJson($from, [
                'type' => 'joined',
                'playerId' => $playerId,
                'code' => $code,
                'name' => $room->players[$playerId] ?? $name,
                'isHost' => $playerId === $room->host_id,
                'players' => $room->player_list(),
                'roomSize' => $room->room_size,
            ]);
            $room->broadcast([
                'type' => 'lobby_update',
                'players' => $room->player_list(),
                'hostId' => $room->host_id,
                'roomSize' => $room->room_size,
            ], $playerId);
            $this->sendJson($from, [
                'type' => 'lobby_update',
                'players' => $room->player_list(),
                'hostId' => $room->host_id,
                'roomSize' => $room->room_size,
            ]);
            if ($room->state === 'lobby' && $room->all_players_connected()) {
                $this->startRound($room);
            }
            return;
        }

        if ($msgType === 'join_room') {
            $name = trim(strval($data['name'] ?? 'Player'));
            if ($name === '') $name = 'Player';
            $code = strtoupper(trim(strval($data['code'] ?? '')));
            $room = $this->manager->get_room($code);
            if ($room === null) {
                $this->sendJson($from, ['type' => 'error', 'message' => 'Room not found']);
                $from->close();
                return;
            }
            if ($room->single_player) {
                $this->sendJson($from, ['type' => 'error', 'message' => 'Single-player room']);
                $from->close();
                return;
            }
            if ($room->state !== 'lobby') {
                $this->sendJson($from, ['type' => 'error', 'message' => 'Game already in progress']);
                $from->close();
                return;
            }
            if (count($room->players) >= $room->room_size) {
                $this->sendJson($from, ['type' => 'error', 'message' => 'Room is full']);
                $from->close();
                return;
            }
            $playerId = $state['player_id'];
            $room->add_player($playerId, $name, $from);
            $state['room'] = $room;
            $state['code'] = $code;
            $state['initialized'] = true;
            $state['rejoined'] = false;

            $this->sendJson($from, [
                'type' => 'joined',
                'playerId' => $playerId,
                'code' => $code,
                'name' => $room->players[$playerId] ?? $name,
                'isHost' => $playerId === $room->host_id,
                'players' => $room->player_list(),
                'roomSize' => $room->room_size,
            ]);
            $room->broadcast([
                'type' => 'lobby_update',
                'players' => $room->player_list(),
                'hostId' => $room->host_id,
                'roomSize' => $room->room_size,
            ], $playerId);
            $this->sendJson($from, [
                'type' => 'lobby_update',
                'players' => $room->player_list(),
                'hostId' => $room->host_id,
                'roomSize' => $room->room_size,
            ]);
            if ($room->state === 'lobby' && $room->all_players_connected()) {
                $this->startRound($room);
            }
            return;
        }

        if ($msgType === 'rejoin_room') {
            $playerId = trim(strval($data['playerId'] ?? ''));
            $code = strtoupper(trim(strval($data['code'] ?? '')));
            $room = $this->manager->get_room($code);
            if ($room === null || $playerId === '' || !isset($room->players[$playerId])) {
                $this->sendJson($from, ['type' => 'session_invalid', 'message' => 'Session not found']);
                $from->close();
                return;
            }
            $room->attach_player($playerId, $from);
            $state['player_id'] = $playerId;
            $state['room'] = $room;
            $state['code'] = $code;
            $state['initialized'] = true;
            $state['rejoined'] = true;

            $this->sendJson($from, $room->state_snapshot($playerId));
            $this->broadcastLobby($room);
            return;
        }

        $this->sendJson($from, ['type' => 'error', 'message' => 'First message must create, join, or rejoin a room']);
        $from->close();
    }

    public function onMessage(ConnectionInterface $from, $msg)
    {
        $data = json_decode($msg, true);
        if (!is_array($data)) {
            return;
        }
        $state = &$from->appState;

        if (!$state['initialized']) {
            $this->handleInitial($from, $data);
            return;
        }

        /** @var Room|null $room */
        $room = $state['room'];
        $playerId = $state['player_id'];
        $code = $state['code'];
        if ($room === null) {
            return;
        }

        $t = $data['type'] ?? null;

        if ($t === 'select_option') {
            if ($room->state !== 'drafting') {
                return;
            }
            $value = $data['value'] ?? null;
            [$ok, $err] = $room->submit_selection($playerId, $value);
            if (!$ok) {
                $this->sendJson($from, ['type' => 'error', 'message' => $err ?? 'Invalid selection']);
                return;
            }
            $room->send_to($playerId, [
                'type' => 'draft_selected',
                'attribute' => $room->assignments[$playerId] ?? null,
                'value' => $room->selections[$playerId] ?? $value,
            ]);
            $room->broadcast([
                'type' => 'draft_status',
                'round' => $room->round_number,
                'submittedCount' => count($room->selections),
                'requiredCount' => $room->required_selections(),
                'secondsLeft' => $room->draft_seconds_left() ?? 0,
            ]);
            if ($room->all_selected()) {
                $this->beginGuessing($room);
            }
            return;
        }

        if ($t === 'submit_guess') {
            if ($room->state !== 'guessing') {
                return;
            }
            $guess = $data['guess'] ?? null;
            [$ok, $err] = $room->submit_guess($playerId, $guess);
            if (!$ok) {
                $this->sendJson($from, ['type' => 'error', 'message' => $err ?? 'Invalid guess']);
                return;
            }
            $room->broadcast([
                'type' => 'guess_update',
                'submittedCount' => count($room->guesses),
                'requiredCount' => $room->room_size,
            ]);
            if ($room->all_guessed()) {
                $this->finalizeAndBroadcast($room);
            }
            return;
        }

        if ($t === 'search_players') {
            if ($room->state !== 'guessing') {
                $this->sendJson($from, ['type' => 'player_suggestions', 'query' => $data['query'] ?? '', 'suggestions' => []]);
            } else {
                $q = trim(strval($data['query'] ?? ''));
                $suggestions = $q !== '' ? DataLoader::searchPlayerNames($q, 8) : [];
                $this->sendJson($from, ['type' => 'player_suggestions', 'query' => $data['query'] ?? '', 'suggestions' => $suggestions]);
            }
            return;
        }

        if ($t === 'refresh_draft') {
            if ($room->state !== 'drafting') {
                $this->sendJson($from, ['type' => 'error', 'message' => 'Not in drafting phase']);
                return;
            }
            [$ok, $err, $options, $refreshesLeft] = $room->refresh_draft_options($playerId);
            if (!$ok) {
                $this->sendJson($from, ['type' => 'error', 'message' => $err ?? 'Could not refresh options']);
                return;
            }
            $attr = $room->assignments[$playerId] ?? null;
            $secsLeft = $room->draft_seconds_left();
            $room->send_to($playerId, [
                'type' => 'draft_prompt',
                'round' => $room->round_number,
                'attribute' => $attr,
                'attributeLabel' => $attr ? (ATTRIBUTE_LABELS[$attr] ?? $attr) : null,
                'options' => $options,
                'selected' => $room->selections[$playerId] ?? null,
                'secondsLeft' => $secsLeft !== null ? $secsLeft : 0,
                'refreshesLeft' => $refreshesLeft,
            ]);
            return;
        }

        if ($t === 'leave') {
            $state['explicit_leave'] = true;
            $from->close();
            return;
        }
    }

    public function onClose(ConnectionInterface $conn)
    {
        $this->clients->detach($conn);
        $state = $conn->appState ?? null;
        if (!$state) return;
        /** @var Room|null $room */
        $room = $state['room'] ?? null;
        $playerId = $state['player_id'] ?? null;
        $code = $state['code'] ?? null;
        $explicitLeave = $state['explicit_leave'] ?? false;

        if ($room === null || $playerId === null || $code === null) return;
        if (!isset($room->players[$playerId])) return;

        if ($explicitLeave) {
            $room->remove_player($playerId);
            if (count($room->players) === 0) {
                $room->cancel_guess_timer($this->loop);
                $room->cancel_draft_timer($this->loop);
                $this->manager->remove_room($code);
            } else {
                $room->broadcast([
                    'type' => 'player_left',
                    'playerId' => $playerId,
                    'players' => $room->player_list(),
                    'state' => $room->state,
                ]);
                $this->broadcastLobby($room);
            }
        } else {
            $room->detach_player($playerId);
        }
    }

    public function onError(ConnectionInterface $conn, \Exception $e)
    {
        try {
            $conn->close();
        } catch (\Throwable $ex) {
        }
    }
}

$port = (int)(getenv('PORT') ?: 8000);
$loop = \React\EventLoop\Loop::get();
$wsServer = new WsServer(new FooTrioServer($loop));
$httpServer = new HttpServer($wsServer);
$server = IoServer::factory($httpServer, $port, '0.0.0.0', $loop);

echo "PHP WebSocket server running on ws://0.0.0.0:{$port}/ws\n";
$server->run();
