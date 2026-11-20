<?php
// Convenience script to start the PHP WebSocket backend and the built frontend (static) server.
// Usage: php run_php.php
// - WebSocket backend: ws://localhost:8000/ws (Ratchet)
// - Frontend (built SPA): http://localhost:5173 (served via PHP built-in server + index.php)
// Make sure you've run: composer install (in backend_php/) and built frontend into frontend/dist.

$root = __DIR__;
$backend = $root . '/backend_php';

function is_windows(): bool {
    return strtoupper(substr(PHP_OS, 0, 3)) === 'WIN';
}

function cleanup($procs) {
    foreach ($procs as $p) {
        if (is_resource($p)) {
            @proc_terminate($p);
        }
    }
}

$php = PHP_BINARY ?: 'php';

$descriptors = [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']];

// Backend WS server
$backendCmd = escapeshellarg($php) . ' ' . escapeshellarg($backend . '/server.php');
$backendProc = proc_open($backendCmd, $descriptors, $pipes, $backend, null);
if (!is_resource($backendProc)) {
    fwrite(STDERR, "Failed to start backend server. Make sure dependencies are installed: cd backend_php && composer install\n");
    exit(1);
}
$procs = [$backendProc];
foreach ($pipes as $p) { @stream_set_blocking($p, false); }

// Frontend static server (serves built SPA via root index.php router)
$frontendCmd = escapeshellarg($php) . ' -S 0.0.0.0:5173 ' . escapeshellarg($root . '/index.php');
$frontendProc = proc_open($frontendCmd, $descriptors, $pipes2, $root, null);
if (!is_resource($frontendProc)) {
    fwrite(STDERR, "Failed to start frontend server.\n");
    cleanup($procs);
    exit(1);
}
$procs[] = $frontendProc;
foreach ($pipes2 as $p) { @stream_set_blocking($p, false); }

echo "Backend WS: ws://localhost:8000/ws\n";
echo "Frontend:   http://localhost:5173 (serves frontend/dist via index.php)\n";
echo "Press Ctrl+C to stop.\n";

if (function_exists('pcntl_async_signals')) {
    pcntl_async_signals(true);
    $handler = function () use ($procs) { cleanup($procs); exit(0); };
    if (defined('SIGINT')) pcntl_signal(SIGINT, $handler);
    if (defined('SIGTERM')) pcntl_signal(SIGTERM, $handler);
}

while (true) {
    foreach ($procs as $p) {
        $status = proc_get_status($p);
        if (!$status['running']) {
            echo "\nA process exited. Stopping...\n";
            cleanup($procs);
            exit(0);
        }
    }
    usleep(200000);
}
