<?php
// Simple PHP front controller to serve the built frontend (SPA) for PHP deployments.
// Build the frontend first: cd frontend && npm install --include=dev && npm run build
// Then deploy this project on a PHP-capable web server with document root at project root,
// or run: php -S 0.0.0.0:5173 index.php

$dist = __DIR__ . '/frontend/dist';
$uri = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
$uri = rawurldecode($uri);

// Prevent directory traversal
if (strpos($uri, '..') !== false) {
    http_response_code(400);
    echo 'Bad request';
    exit;
}

$requested = realpath($dist . $uri);
$distReal = realpath($dist);

if ($requested && $distReal && strpos($requested, $distReal) === 0 && is_file($requested)) {
    $ext = strtolower(pathinfo($requested, PATHINFO_EXTENSION));
    $types = [
        'html' => 'text/html; charset=utf-8',
        'js' => 'application/javascript; charset=utf-8',
        'mjs' => 'application/javascript; charset=utf-8',
        'css' => 'text/css; charset=utf-8',
        'json' => 'application/json; charset=utf-8',
        'svg' => 'image/svg+xml',
        'png' => 'image/png',
        'jpg' => 'image/jpeg',
        'jpeg' => 'image/jpeg',
        'gif' => 'image/gif',
        'webp' => 'image/webp',
        'ico' => 'image/x-icon',
        'woff' => 'font/woff',
        'woff2' => 'font/woff2',
        'ttf' => 'font/ttf',
        'map' => 'application/json; charset=utf-8',
        'txt' => 'text/plain; charset=utf-8',
    ];
    if (isset($types[$ext])) {
        header('Content-Type: ' . $types[$ext]);
    }
    readfile($requested);
    exit;
}

// SPA fallback
$index = $dist . '/index.html';
if (is_file($index)) {
    header('Content-Type: text/html; charset=utf-8');
    readfile($index);
    exit;
}

http_response_code(503);
header('Content-Type: text/plain; charset=utf-8');
echo "Frontend build not found.\n\n";
echo "Build it with:\n  cd frontend\n  npm install --include=dev\n  npm run build\n\n";
echo "Then ensure VITE_WS_URL points to your PHP WebSocket server (e.g. ws://host:8000/ws) before building for deployed environments.\n";
