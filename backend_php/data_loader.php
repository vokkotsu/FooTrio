<?php

declare(strict_types=1);

class DataLoader
{
    private static ?array $gameData = null;
    private static ?array $clubsById = null;
    private static ?array $playerNamePairs = null;
    private static string $dataPath = '';

    public static function init(?string $path = null): void
    {
        self::$dataPath = $path ?? (dirname(__DIR__) . '/game_data.json');
        self::$gameData = null;
        self::$clubsById = null;
        self::$playerNamePairs = null;
    }

    private static function dataPath(): string
    {
        if (self::$dataPath === '') {
            self::$dataPath = dirname(__DIR__) . '/game_data.json';
        }
        return self::$dataPath;
    }

    public static function loadGameData(): array
    {
        if (self::$gameData !== null) {
            return self::$gameData;
        }
        $path = self::dataPath();
        if (!is_file($path)) {
            throw new \RuntimeException("Game data file not found: {$path}");
        }
        $json = file_get_contents($path);
        if ($json === false) {
            throw new \RuntimeException("Failed to read game data file: {$path}");
        }
        $data = json_decode($json, true);
        if (!is_array($data)) {
            throw new \RuntimeException("Invalid game data JSON: {$path}");
        }
        self::$gameData = $data;
        return self::$gameData;
    }

    public static function getPlayers(): array
    {
        return self::loadGameData()['players'] ?? [];
    }

    public static function getOptions(): array
    {
        return self::loadGameData()['options'] ?? [];
    }

    public static function getClubsById(): array
    {
        if (self::$clubsById !== null) {
            return self::$clubsById;
        }
        $clubs = self::getOptions()['clubs'] ?? [];
        $out = [];
        foreach ($clubs as $c) {
            if (is_array($c)) {
                $cid = strval($c['id'] ?? '');
                if ($cid !== '') {
                    $out[$cid] = $c;
                }
            } elseif (is_string($c)) {
                $out[$c] = ['id' => $c, 'name' => $c];
            }
        }
        self::$clubsById = $out;
        return $out;
    }

    private static function clubValueKey($value): string
    {
        if (is_array($value)) {
            return strval($value['id'] ?? '');
        }
        return strval($value);
    }

    private static function sampleArray(array $arr, int $k): array
    {
        if ($k <= 0 || count($arr) === 0) {
            return [];
        }
        if (count($arr) <= $k) {
            $copy = array_values($arr);
            shuffle($copy);
            return $copy;
        }
        $keys = array_rand($arr, $k);
        if (!is_array($keys)) {
            $keys = [$keys];
        }
        $out = [];
        foreach ($keys as $key) {
            $out[] = $arr[$key];
        }
        shuffle($out);
        return $out;
    }

    private static function sampleWeighted(array $pool, array $priorityPool, int $k, int $priorityCount): array
    {
        $pool = array_values($pool);
        $poolByKey = [];
        foreach ($pool as $x) {
            $poolByKey[self::clubValueKey($x)] = $x;
        }

        $priorityKeys = [];
        foreach ($priorityPool as $x) {
            $key = self::clubValueKey($x);
            if (array_key_exists($key, $poolByKey)) {
                $priorityKeys[] = $key;
            }
        }
        // dedupe preserving order
        $priorityKeys = array_values(array_unique($priorityKeys));
        $priority = [];
        foreach ($priorityKeys as $kid) {
            $priority[] = $poolByKey[$kid];
        }
        $priorityKeySet = [];
        foreach ($priority as $x) {
            $priorityKeySet[self::clubValueKey($x)] = true;
        }
        $others = [];
        foreach ($pool as $x) {
            if (!isset($priorityKeySet[self::clubValueKey($x)])) {
                $others[] = $x;
            }
        }

        if (count($pool) <= $k) {
            return $pool;
        }

        $pCount = min($priorityCount, $k, count($priority));
        $oCount = $k - $pCount;
        if ($oCount > count($others)) {
            $oCount = count($others);
            $pCount = min($k - $oCount, count($priority));
        }

        $chosen = [];
        if ($pCount > 0 && count($priority) > 0) {
            $chosen = array_merge($chosen, self::sampleArray($priority, $pCount));
        }
        if ($oCount > 0 && count($others) > 0) {
            $chosen = array_merge($chosen, self::sampleArray($others, $oCount));
        }

        $remainingNeeded = $k - count($chosen);
        if ($remainingNeeded > 0) {
            $chosenKeys = [];
            foreach ($chosen as $x) {
                $chosenKeys[self::clubValueKey($x)] = true;
            }
            $remaining = [];
            foreach ($pool as $x) {
                if (!isset($chosenKeys[self::clubValueKey($x)])) {
                    $remaining[] = $x;
                }
            }
            if (count($remaining) > 0) {
                $chosen = array_merge($chosen, self::sampleArray($remaining, min($remainingNeeded, count($remaining))));
            }
        }

        shuffle($chosen);
        return $chosen;
    }

    public static function sampleOptions(string $attribute, int $k = 5): array
    {
        $options = self::getOptions();
        $keyMap = [
            'country' => 'countries',
            'position' => 'positions',
            'club' => 'clubs',
        ];
        $key = $keyMap[$attribute] ?? $attribute;
        $pool = $options[$key] ?? [];
        if (!is_array($pool)) {
            $pool = [];
        }

        if ($attribute === 'country') {
            $priority = $options['top_fifa_countries'] ?? [];
            if (is_array($priority) && count($priority) > 0) {
                return self::sampleWeighted($pool, $priority, $k, min(3, $k));
            }
        } elseif ($attribute === 'club') {
            $priority = $options['top5_league_clubs'] ?? [];
            if (is_array($priority) && count($priority) > 0) {
                return self::sampleWeighted($pool, $priority, $k, min(3, $k));
            }
        }

        if (count($pool) <= $k) {
            $copy = array_values($pool);
            shuffle($copy);
            return $copy;
        }
        return self::sampleArray($pool, $k);
    }

    public static function normalizeName(?string $name): string
    {
        $s = $name ?? '';
        if ($s === '') {
            return '';
        }
        // Try Unicode normalization + combining mark removal (intl Normalizer)
        if (class_exists('\\Normalizer')) {
            $normalized = \Normalizer::normalize($s, \Normalizer::FORM_KD);
            if ($normalized !== false && $normalized !== null) {
                $s = $normalized;
            }
            // remove combining marks
            $s = preg_replace('/\p{Mn}+/u', '', $s) ?? $s;
        } else {
            // Fallback: transliterate accents where possible
            $trans = @iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $s);
            if ($trans !== false) {
                $s = $trans;
            }
        }
        $s = mb_strtolower($s, 'UTF-8');
        $s = preg_replace('/[^a-z0-9\s]+/u', ' ', $s) ?? $s;
        $s = preg_replace('/\s+/u', ' ', $s) ?? $s;
        return trim($s);
    }

    public static function clubId($value): string
    {
        if (is_array($value)) {
            $cid = $value['id'] ?? null;
            return $cid !== null ? strval($cid) : '';
        }
        if ($value === null) {
            return '';
        }
        return strval($value);
    }

    public static function clubDisplay($value): string
    {
        if (is_array($value)) {
            $name = $value['name'] ?? null;
            if ($name !== null && $name !== '') {
                return strval($name);
            }
            $cid = $value['id'] ?? null;
            return $cid !== null ? strval($cid) : '';
        }
        if ($value === null) {
            return '';
        }
        $s = strval($value);
        $info = self::getClubsById()[$s] ?? null;
        if ($info && isset($info['name'])) {
            return strval($info['name']);
        }
        return $s;
    }

    public static function clubMatches($constraintClub, $playerClubs): bool
    {
        $target = self::clubId($constraintClub);
        if ($target === '') {
            return false;
        }
        if (!is_array($playerClubs)) {
            return false;
        }
        foreach ($playerClubs as $club) {
            if (self::clubId($club) === $target) {
                return true;
            }
        }
        return false;
    }

    public static function findPlayerMatches(string $guess): array
    {
        $data = self::loadGameData();
        $norm = self::normalizeName($guess);
        if ($norm === '') {
            return [];
        }
        $ids = $data['name_index'][$norm] ?? [];
        if (!is_array($ids) || count($ids) === 0) {
            return [];
        }
        $playersById = [];
        foreach (($data['players'] ?? []) as $p) {
            if (isset($p['player_id'])) {
                $playersById[strval($p['player_id'])] = $p;
            }
        }
        $out = [];
        foreach ($ids as $id) {
            $key = strval($id);
            if (isset($playersById[$key])) {
                $out[] = $playersById[$key];
            }
        }
        return $out;
    }

    public static function bestAnswerForConstraints(array $constraints): ?array
    {
        $players = self::getPlayers();
        if (!is_array($players) || count($players) === 0) {
            return null;
        }
        $country = $constraints['country'] ?? null;
        $position = $constraints['position'] ?? null;
        $club = $constraints['club'] ?? null;

        $best = null;
        $bestScore = -1;
        foreach ($players as $p) {
            $pCountry = $p['country'] ?? null;
            $pPosition = $p['position'] ?? null;
            $pClubs = $p['clubs'] ?? [];
            $breakdown = [
                'country' => ($country !== null && $pCountry === $country),
                'position' => ($position !== null && $pPosition === $position),
                'club' => ($club !== null && self::clubMatches($club, $pClubs)),
            ];
            $score = 0;
            foreach ($breakdown as $v) {
                if ($v) $score++;
            }
            if ($score > $bestScore) {
                $best = [
                    'name' => $p['name'] ?? null,
                    'player_id' => $p['player_id'] ?? null,
                    'country' => $p['country'] ?? null,
                    'position' => $p['position'] ?? null,
                    'breakdown' => $breakdown,
                    'points' => $score,
                ];
                $bestScore = $score;
                if ($bestScore === 3) {
                    break;
                }
            }
        }
        return $best;
    }

    public static function bestGuessForConstraints(array $constraints): string
    {
        $best = self::bestAnswerForConstraints($constraints);
        if ($best && !empty($best['name'])) {
            return strval($best['name']);
        }
        $players = self::getPlayers();
        if (is_array($players) && count($players) > 0) {
            $pick = $players[array_rand($players)];
            return strval($pick['name'] ?? 'Unknown Player');
        }
        return 'Unknown Player';
    }

    private static function playerNamePairs(): array
    {
        if (self::$playerNamePairs !== null) {
            return self::$playerNamePairs;
        }
        $pairs = [];
        foreach (self::getPlayers() as $p) {
            $name = $p['name'] ?? '';
            if ($name === null || $name === '') {
                continue;
            }
            $pairs[] = [
                strval($name),
                self::normalizeName(strval($name)),
                strval($p['position'] ?? ''),
            ];
        }
        self::$playerNamePairs = $pairs;
        return $pairs;
    }

    public static function searchPlayerNames(string $query, int $limit = 8): array
    {
        $q = self::normalizeName($query);
        if ($q === '') {
            return [];
        }
        $pairs = self::playerNamePairs();
        $tokenStarts = [];
        $contains = [];
        $seen = [];
        foreach ($pairs as $pair) {
            [$name, $norm, $position] = $pair;
            if ($norm === '' || isset($seen[$norm])) {
                continue;
            }
            $item = ['name' => $name, 'position' => $position];
            $tokens = preg_split('/\s+/u', $norm, -1, PREG_SPLIT_NO_EMPTY) ?: [];
            $prefixMatch = false;
            foreach ($tokens as $t) {
                if ($t !== '' && str_starts_with($t, $q)) {
                    $prefixMatch = true;
                    break;
                }
            }
            if ($prefixMatch) {
                $seen[$norm] = true;
                $tokenStarts[] = $item;
                if (count($tokenStarts) >= $limit) {
                    return array_slice($tokenStarts, 0, $limit);
                }
            } elseif (str_contains($norm, $q)) {
                $contains[] = [$norm, $item];
            }
        }
        foreach ($contains as $entry) {
            [$norm, $item] = $entry;
            if (isset($seen[$norm])) {
                continue;
            }
            $seen[$norm] = true;
            $tokenStarts[] = $item;
            if (count($tokenStarts) >= $limit) {
                break;
            }
        }
        return array_slice($tokenStarts, 0, $limit);
    }
}

// Initialize with default path
DataLoader::init();
