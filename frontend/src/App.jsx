import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const WS_URL =
  import.meta.env.VITE_WS_URL ||
  (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
    ? "ws://localhost:8000/ws"
    : "");

const SESSION_KEY = "ft-session";

export default function App() {
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);

  const [screen, setScreen] = useState("landing"); // landing | lobby | drafting | waiting | guessing | result | game_over
  const [name, setName] = useState("");
  const [joinCode, setJoinCode] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  const [playerId, setPlayerId] = useState(null);
  const [roomCode, setRoomCode] = useState(null);
  const [players, setPlayers] = useState([]);
  const [hostId, setHostId] = useState(null);
  const [round, setRound] = useState(0);

  const [draft, setDraft] = useState(null); // {attribute, attributeLabel, options, selected}
  const [draftStatus, setDraftStatus] = useState({ submittedCount: 0, requiredCount: 3 });
  const [constraints, setConstraints] = useState(null);
  const [guess, setGuess] = useState("");
  const [guessInfo, setGuessInfo] = useState({ submitted: false, submittedCount: 0, requiredCount: 3, secondsLeft: 30 });
  const [result, setResult] = useState(null);
  const [gameOver, setGameOver] = useState(null);
  const [history, setHistory] = useState([]);

  const [session, setSession] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(SESSION_KEY) || "null");
    } catch {
      return null;
    }
  });

  useEffect(() => {
    try {
      if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session));
      else localStorage.removeItem(SESSION_KEY);
    } catch {}
  }, [session]);

  const resetRoundUi = useCallback(() => {
    setDraft(null);
    setDraftStatus({ submittedCount: 0, requiredCount: 3 });
    setConstraints(null);
    setGuess("");
    setGuessInfo({ submitted: false, submittedCount: 0, requiredCount: 3, secondsLeft: 30 });
    setResult(null);
  }, []);

  const handleMessage = useCallback(
    (msg) => {
      switch (msg.type) {
        case "joined": {
          setPlayerId(msg.playerId);
          setRoomCode(msg.code);
          setHostId(msg.players?.find((p) => p.isHost)?.id || null);
          setPlayers(msg.players || []);
          setScreen("lobby");
          setStatus("");
          setError("");
          const single = !!(msg.players || []).some((p) => p.isBot);
          setSession({ code: msg.code, playerId: msg.playerId, name: msg.name || name, singlePlayer: single });
          break;
        }
        case "lobby_update": {
          setPlayers(msg.players || []);
          setHostId(msg.hostId || null);
          if (screen === "landing") setScreen("lobby");
          break;
        }
        case "round_started": {
          setRound(msg.round || 1);
          setPlayers(msg.players || []);
          setGameOver(null);
          resetRoundUi();
          setScreen("drafting"); // may switch to waiting after draft prompt/select
          break;
        }
        case "draft_prompt": {
          setRound(msg.round || round);
          setDraft({
            attribute: msg.attribute,
            attributeLabel: msg.attributeLabel,
            options: msg.options || [],
            selected: msg.selected || null,
          });
          setScreen(msg.selected ? "waiting" : "drafting");
          break;
        }
        case "draft_selected": {
          setDraft((d) => (d ? { ...d, selected: msg.value } : d));
          setScreen("waiting");
          break;
        }
        case "draft_status": {
          setDraftStatus({
            submittedCount: msg.submittedCount ?? 0,
            requiredCount: msg.requiredCount ?? 3,
          });
          break;
        }
        case "guess_phase": {
          setRound(msg.round || round);
          setConstraints(msg.constraints || {});
          setGuessInfo({
            submitted: false,
            submittedCount: msg.submittedCount ?? 0,
            requiredCount: msg.requiredCount ?? 3,
            secondsLeft: msg.secondsLeft ?? 30,
          });
          setGuess("");
          setScreen("guessing");
          break;
        }
        case "guess_update": {
          setGuessInfo((g) => ({
            ...g,
            submittedCount: msg.submittedCount ?? g.submittedCount,
            requiredCount: msg.requiredCount ?? g.requiredCount,
          }));
          break;
        }
        case "round_result": {
          setResult(msg);
          setPlayers(msg.players || msg.standings || players);
          setHistory((h) => {
            const without = h.filter((r) => r.round !== msg.round);
            return [...without, msg].sort((a, b) => a.round - b.round);
          });
          setScreen(msg.gameOver ? "game_over" : "result");
          break;
        }
        case "game_over": {
          setGameOver(msg);
          setPlayers(msg.players || players);
          if (msg.history) setHistory(msg.history);
          setScreen("game_over");
          break;
        }
        case "state_sync": {
          const pid = msg.playerId;
          setPlayerId(pid);
          setRoomCode(msg.code);
          setHostId(msg.hostId || null);
          setPlayers(msg.players || []);
          setRound(msg.round || 0);
          setHistory(msg.history || []);
          setSession({ code: msg.code, playerId: pid, name: session?.name || name });
          if (msg.state === "lobby") {
            setScreen("lobby");
            resetRoundUi();
          } else if (msg.state === "drafting") {
            const d = msg.draft || {};
            setDraft({
              attribute: d.attribute,
              attributeLabel: d.attributeLabel,
              options: d.options || [],
              selected: d.selected || null,
            });
            setDraftStatus({
              submittedCount: d.submittedCount ?? 0,
              requiredCount: d.requiredCount ?? 3,
            });
            setScreen(d.selected ? "waiting" : "drafting");
          } else if (msg.state === "guessing") {
            setConstraints(msg.constraints || {});
            setGuessInfo({
              submitted: !!msg.guess?.submitted,
              submittedCount: msg.guess?.submittedCount ?? 0,
              requiredCount: msg.guess?.requiredCount ?? 3,
              secondsLeft: msg.guess?.secondsLeft ?? 30,
            });
            setScreen("guessing");
          } else if (msg.state === "result" || msg.state === "game_over") {
            if (msg.result) setResult(msg.result);
            setScreen(msg.state === "game_over" ? "game_over" : "result");
          }
          setStatus("");
          break;
        }
        case "player_left": {
          setPlayers(msg.players || players);
          setStatus("A player left the room. Game may pause until 3 players are present.");
          break;
        }
        case "session_invalid": {
          setSession(null);
          setError(msg.message || "Session expired. Please join again.");
          setScreen("landing");
          break;
        }
        case "error": {
          setError(msg.message || "Something went wrong");
          break;
        }
        default:
          break;
      }
    },
    [name, players, resetRoundUi, round, screen, session?.name]
  );

  const connect = useCallback(
    (onOpen) => {
      if (!WS_URL) {
        setError("Backend WebSocket URL is not configured. Set VITE_WS_URL for deployed builds.");
        return null;
      }
      try {
        const ws = new WebSocket(WS_URL);
        wsRef.current = ws;
        ws.onopen = () => {
          setError("");
          if (onOpen) onOpen(ws);
        };
        ws.onclose = () => {
          // do not auto-reconnect aggressively; user can rejoin via session
        };
        ws.onerror = () => {
          setError("Could not connect to the game server. Is the backend running on ws://localhost:8000/ws?");
        };
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data);
            handleMessage(msg);
          } catch {
            // ignore
          }
        };
        return ws;
      } catch (e) {
        setError(String(e));
        return null;
      }
    },
    [handleMessage]
  );

  const createRoom = (singlePlayer = false) => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Enter your name");
      return;
    }
    setError("");
    setStatus("Connecting...");
    connect((ws) => {
      ws.send(
        JSON.stringify({
          type: "create_room",
          name: trimmed,
          mode: singlePlayer ? "single" : "multi",
        })
      );
      setStatus("");
    });
  };

  const joinRoom = () => {
    const trimmed = name.trim();
    const code = joinCode.trim().toUpperCase();
    if (!trimmed) {
      setError("Enter your name");
      return;
    }
    if (!code) {
      setError("Enter a room code");
      return;
    }
    setError("");
    setStatus("Connecting...");
    connect((ws) => {
      ws.send(JSON.stringify({ type: "join_room", name: trimmed, code }));
      setStatus("");
    });
  };

  // auto-rejoin saved session (skip single-player test sessions)
  useEffect(() => {
    if (!session || screen !== "landing") return;
    if (session.singlePlayer) return;
    connect((ws) => {
      ws.send(JSON.stringify({ type: "rejoin_room", code: session.code, playerId: session.playerId }));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // guess countdown tick (client-side)
  useEffect(() => {
    if (screen !== "guessing") return;
    if (guessInfo.secondsLeft <= 0) return;
    const t = setTimeout(() => {
      setGuessInfo((g) => ({ ...g, secondsLeft: Math.max(0, g.secondsLeft - 1) }));
    }, 1000);
    return () => clearTimeout(t);
  }, [screen, guessInfo.secondsLeft]);

  const send = (payload) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
    }
  };

  const selectOption = (value) => {
    if (!draft || draft.selected) return;
    send({ type: "select_option", value });
  };

  const submitGuess = () => {
    const text = guess.trim();
    if (!text) {
      setError("Enter a player name guess");
      return;
    }
    setError("");
    send({ type: "submit_guess", guess: text });
    setGuessInfo((g) => ({ ...g, submitted: true }));
  };

  const leaveToHome = () => {
    send({ type: "leave" });
    try {
      wsRef.current?.close();
    } catch {}
    setSession(null);
    setScreen("landing");
    setPlayers([]);
    setRoomCode(null);
    setPlayerId(null);
    resetRoundUi();
    setGameOver(null);
    setHistory([]);
  };

  const me = useMemo(() => players.find((p) => p.id === playerId), [players, playerId]);

  // --- UI screens ---
  if (screen === "landing") {
    return (
      <Shell>
        <div className="card w-full max-w-lg p-8">
          <h1 className="text-3xl font-extrabold tracking-tight text-[#143524]">Football Trivia Draft</h1>
          <p className="mt-2 text-sm text-slate-600">
            Real-time multiplayer (3 players). Draft Country/Position/Club, then guess a matching footballer.
          </p>
          <div className="mt-6 space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">Your name</label>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Enter your name" />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <button className="btn btn-primary w-full" onClick={() => createRoom(false)}>Create Multiplayer Room</button>
              <button className="btn btn-ghost w-full" onClick={() => createRoom(true)}>Single Player (vs 2 Bots)</button>
            </div>
            <div className="space-y-2 pt-1">
              <label className="block text-sm font-medium mb-1">Join existing room</label>
              <div className="flex gap-2">
                <input
                  className="input uppercase tracking-widest"
                  value={joinCode}
                  onChange={(e) => setJoinCode(e.target.value)}
                  placeholder="ROOM CODE"
                />
                <button className="btn btn-secondary whitespace-nowrap" onClick={joinRoom}>Join</button>
              </div>
            </div>
            {status && <p className="text-sm text-slate-600">{status}</p>}
            {error && <p className="text-sm text-red-600" role="alert">{error}</p>}
            {!WS_URL && (
              <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-2">
                Set <code>VITE_WS_URL</code> for deployed builds (e.g. ws://localhost:8000/ws locally).
              </p>
            )}
          </div>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="w-full max-w-6xl grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-2 space-y-5">
          <div className="card p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-xl font-bold text-[#143524]">
                  {screen === "lobby" ? "Lobby" : `Round ${round || 1}`}
                </h2>
                <p className="text-sm text-slate-600">
                  Room <span className="font-mono font-bold tracking-widest">{roomCode}</span> · You:{" "}
                  <span className="font-semibold">{me?.name || name}</span>
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button className="btn btn-ghost text-sm" onClick={() => navigator.clipboard?.writeText(roomCode || "")}>
                  Copy Code
                </button>
                <button className="btn btn-ghost text-sm" onClick={leaveToHome}>Leave</button>
              </div>
            </div>
            {error && <p className="mt-3 text-sm text-red-600" role="alert">{error}</p>}
            {status && <p className="mt-2 text-sm text-slate-600">{status}</p>}
          </div>

          {screen === "lobby" && (
            <div className="card p-6">
              <h3 className="font-semibold text-lg mb-2">Waiting for players</h3>
              <p className="text-sm text-slate-600 mb-4">
                {players.some((p) => p.isBot)
                  ? "Single player test mode: you vs 2 bots. Round 1 starts automatically."
                  : "Exactly 3 players are required. Round 1 starts automatically once everyone joins."}
              </p>
              <PlayerChips players={players} />
              <div className="mt-4 text-sm text-slate-700">
                {players.length}/3 joined
              </div>
            </div>
          )}

          {(screen === "drafting" || screen === "waiting") && (
            <div className="card p-6">
              <div className="flex items-center justify-between gap-3 mb-3">
                <h3 className="font-semibold text-lg">Drafting Phase</h3>
                <span className="pill bg-emerald-100 text-emerald-800">
                  {draftStatus.submittedCount}/{draftStatus.requiredCount} selected
                </span>
              </div>
              {draft ? (
                <>
                  <p className="text-sm text-slate-700 mb-4">
                    You are selecting: <span className="font-bold text-[#143524]">{draft.attributeLabel}</span>
                  </p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {(draft.options || []).map((opt) => {
                      const selected = draft.selected === opt;
                      return (
                        <button
                          key={opt}
                          onClick={() => selectOption(opt)}
                          disabled={!!draft.selected}
                          className={`text-left rounded-xl border px-4 py-3 font-medium transition ${
                            selected
                              ? "bg-emerald-600 text-white border-emerald-600"
                              : "bg-white hover:bg-emerald-50 border-emerald-200 text-slate-800"
                          } ${draft.selected && !selected ? "opacity-60" : ""}`}
                        >
                          {opt}
                        </button>
                      );
                    })}
                  </div>
                  {draft.selected && (
                    <div className="mt-5 p-4 rounded-xl bg-amber-50 border border-amber-200 text-amber-900">
                      <p className="font-semibold">Waiting for others...</p>
                      <p className="text-sm mt-1">
                        You selected <span className="font-bold">{draft.selected}</span>. The 3 attributes will be revealed once everyone has chosen.
                      </p>
                    </div>
                  )}
                </>
              ) : (
                <div className="space-y-3">
                  <p className="text-slate-600">Preparing your draft options...</p>
                  <p className="text-xs text-slate-500">
                    If this stays stuck, restart <code>python run.py</code> (backend may be on old code) and click Retry.
                  </p>
                  <button
                    className="btn btn-ghost text-sm"
                    onClick={() =>
                      send({
                        type: "rejoin_room",
                        code: session?.code || roomCode,
                        playerId: session?.playerId || playerId,
                      })
                    }
                  >
                    Retry / Sync
                  </button>
                </div>
              )}
            </div>
          )}

          {screen === "guessing" && (
            <div className="card p-6">
              <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                <h3 className="font-semibold text-lg">Guessing Phase</h3>
                <div className={`pill ${guessInfo.secondsLeft <= 10 ? "bg-red-100 text-red-700" : "bg-slate-100 text-slate-700"}`}>
                  {guessInfo.secondsLeft}s left
                </div>
              </div>
              <div className="mb-4">
                <p className="text-sm text-slate-600 mb-2">Constraints (all 3 revealed):</p>
                <div className="flex flex-wrap gap-2">
                  <ConstraintChip label="Country" value={constraints?.country} />
                  <ConstraintChip label="Position" value={constraints?.position} />
                  <ConstraintChip label="Club" value={constraints?.club} />
                </div>
              </div>
              {!guessInfo.submitted ? (
                <div className="space-y-3">
                  <label className="block text-sm font-medium">Name a real-life football player matching all 3 (as best as you can)</label>
                  <input
                    className="input"
                    value={guess}
                    onChange={(e) => setGuess(e.target.value)}
                    placeholder="e.g. Cristiano Ronaldo"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") submitGuess();
                    }}
                  />
                  <button className="btn btn-primary" onClick={submitGuess}>Submit Guess</button>
                </div>
              ) : (
                <div className="p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-900">
                  <p className="font-semibold">Guess submitted. Waiting for others...</p>
                  <p className="text-sm mt-1">Results will appear when the timer ends or all players submit.</p>
                </div>
              )}
              <p className="mt-4 text-sm text-slate-600">
                Guesses submitted: {guessInfo.submittedCount}/{guessInfo.requiredCount}
              </p>
            </div>
          )}

          {(screen === "result" || screen === "game_over") && result && (
            <div className="card p-6">
              <div className="flex items-center justify-between gap-3 mb-3">
                <h3 className="font-semibold text-lg">
                  {screen === "game_over" ? "Game Over" : `Round ${result.round} Results`}
                </h3>
                {screen !== "game_over" && <span className="pill bg-blue-100 text-blue-800">Next round starting...</span>}
              </div>

              <div className="mb-4">
                <p className="text-sm text-slate-600 mb-2">Constraints</p>
                <div className="flex flex-wrap gap-2">
                  <ConstraintChip label="Country" value={result.constraints?.country} />
                  <ConstraintChip label="Position" value={result.constraints?.position} />
                  <ConstraintChip label="Club" value={result.constraints?.club} />
                </div>
              </div>

              <div className="space-y-3">
                {(result.results || []).map((r) => (
                  <div key={r.playerId} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="font-semibold">{r.name}</div>
                      <div className="pill bg-emerald-100 text-emerald-800">+{r.points} / 3 (Total {r.totalScore})</div>
                    </div>
                    <div className="mt-1 text-sm text-slate-700">
                      Guess: <span className="font-medium">{r.guess || "(no guess)"}</span>
                    </div>
                    <div className="mt-1 text-sm text-slate-700">
                      Matched:{" "}
                      <span className="font-medium">
                        {r.matched_player?.name || "No match found"}
                      </span>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2 text-xs">
                      <BreakdownPill label="Country" ok={r.breakdown?.country} />
                      <BreakdownPill label="Position" ok={r.breakdown?.position} />
                      <BreakdownPill label="Club" ok={r.breakdown?.club} />
                    </div>
                  </div>
                ))}
              </div>

              {screen === "game_over" && (
                <div className="mt-5 p-4 rounded-xl bg-amber-50 border border-amber-200 text-amber-900">
                  <p className="font-bold text-lg">
                    Winner: {players.find((p) => p.id === (gameOver?.winnerId || result.winnerId))?.name || "Unknown"}
                  </p>
                  <p className="text-sm mt-1">First to reach 15 points wins.</p>
                  <button className="btn btn-secondary mt-3" onClick={leaveToHome}>Back to Home</button>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="space-y-5">
          <div className="card p-5">
            <h3 className="font-bold mb-3">Scoreboard</h3>
            <div className="space-y-2">
              {[...players]
                .sort((a, b) => (b.score || 0) - (a.score || 0))
                .map((p) => (
                  <div key={p.id} className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-3 py-2">
                    <div className="min-w-0">
                      <div className="font-medium truncate">
                        {p.name} {p.id === playerId ? <span className="text-slate-400">(you)</span> : null}
                        {p.isHost ? <span className="ml-1 text-amber-700 text-xs">(host)</span> : null}
                        {p.isBot ? <span className="ml-1 text-slate-500 text-xs">(bot)</span> : null}
                      </div>
                    </div>
                    <div className="font-bold text-[#143524]">{p.score ?? 0}</div>
                  </div>
                ))}
              {players.length === 0 && <p className="text-sm text-slate-500">No players yet.</p>}
            </div>
            <p className="text-xs text-slate-500 mt-3">Win condition: reach 15 points.</p>
          </div>

          <div className="card p-5">
            <h3 className="font-bold mb-3">Round Info</h3>
            <ul className="text-sm text-slate-700 space-y-1">
              <li>State: <span className="font-medium">{screen}</span></li>
              <li>Round: <span className="font-medium">{round || "-"}</span></li>
              <li>Players: <span className="font-medium">{players.length}/3</span></li>
            </ul>
            {screen === "waiting" && draft?.selected && (
              <div className="mt-3 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-3">
                Waiting for others... ({draftStatus.submittedCount}/{draftStatus.requiredCount} submitted)
              </div>
            )}
          </div>

          {history.length > 0 && (
            <div className="card p-5">
              <h3 className="font-bold mb-3">History</h3>
              <div className="space-y-3 max-h-[360px] overflow-auto pr-1">
                {[...history].reverse().map((h) => (
                  <div key={h.round} className="rounded-lg border border-slate-200 p-3 bg-white">
                    <div className="font-semibold text-sm mb-1">Round {h.round}</div>
                    <div className="text-xs text-slate-600 mb-2">
                      {h.constraints?.country} · {h.constraints?.position} · {h.constraints?.club}
                    </div>
                    <div className="space-y-1">
                      {(h.results || []).map((r) => (
                        <div key={r.playerId} className="text-xs flex justify-between gap-2">
                          <span className="truncate">{r.name}: {r.guess || "—"}</span>
                          <span className="font-semibold">+{r.points}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </Shell>
  );
}

function Shell({ children }) {
  return (
    <div className="min-h-screen px-4 py-6 md:py-10">
      <div className="max-w-6xl mx-auto flex items-start justify-center">{children}</div>
    </div>
  );
}

function PlayerChips({ players }) {
  return (
    <div className="flex flex-wrap gap-2">
      {players.map((p) => (
        <span key={p.id} className="pill bg-emerald-100 text-emerald-800 border border-emerald-200">
          {p.name}
          {p.isHost ? " (host)" : ""}
          {p.isBot ? " (bot)" : ""}
        </span>
      ))}
      {Array.from({ length: Math.max(0, 3 - players.length) }).map((_, i) => (
        <span key={`empty-${i}`} className="pill bg-slate-100 text-slate-500 border border-slate-200">
          Waiting...
        </span>
      ))}
    </div>
  );
}

function ConstraintChip({ label, value }) {
  return (
    <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-emerald-700 font-semibold">{label}</div>
      <div className="font-semibold text-[#143524]">{value || "?"}</div>
    </div>
  );
}

function BreakdownPill({ label, ok }) {
  return (
    <span className={`pill ${ok ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-700"}`}>
      {label} {ok ? "+1" : "+0"}
    </span>
  );
}
