import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  FooTrioGame,
  searchPlayerNames as localSearchPlayerNames,
  DRAFT_COUNTDOWN,
  GUESS_COUNTDOWN,
  ATTRIBUTE_LABELS,
  ROOM_SIZE,
  DUO_ROOM_SIZE,
} from "./gameLogic";

const WS_URL =
  import.meta.env.VITE_WS_URL ||
  (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
    ? "ws://localhost:8000/ws"
    : "");

const SESSION_KEY = "ft-session";

export default function App() {
  const wsRef = useRef(null);
  const handleMessageRef = useRef(null);
  const reconnectTimer = useRef(null);
  const localGameRef = useRef(null);
  const localDraftTimerRef = useRef(null);
  const localGuessTimerRef = useRef(null);
  const localNextRoundRef = useRef(null);
  const isSingleRef = useRef(false);

  const [isSingle, setIsSingle] = useState(false);
  const [singleMode, setSingleMode] = useState("single"); // single (1v2) | duo (1v1)
  const [roomSize, setRoomSize] = useState(ROOM_SIZE);
  const [screen, setScreen] = useState("landing"); // landing | lobby | drafting | waiting | guessing | result | game_over
  const [name, setName] = useState("");
  const [theme, setTheme] = useState(() => {
    try {
      const t = localStorage.getItem("theme");
      if (t === "light" || t === "dark") return t;
    } catch {}
    if (typeof window !== "undefined" && window.matchMedia) {
      return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }
    return "light";
  });
  const [joinCode, setJoinCode] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  const [playerId, setPlayerId] = useState(null);
  const [roomCode, setRoomCode] = useState(null);
  const [players, setPlayers] = useState([]);
  const [hostId, setHostId] = useState(null);
  const [round, setRound] = useState(0);

  const [draft, setDraft] = useState(null); // {attribute, attributeLabel, options, selected}
  const [draftStatus, setDraftStatus] = useState({ submittedCount: 0, requiredCount: ROOM_SIZE, secondsLeft: DRAFT_COUNTDOWN });
  const [draftSecondsLeft, setDraftSecondsLeft] = useState(DRAFT_COUNTDOWN);
  const [constraints, setConstraints] = useState(null);
  const [guess, setGuess] = useState("");
  const [guessInfo, setGuessInfo] = useState({ submitted: false, submittedCount: 0, requiredCount: ROOM_SIZE, secondsLeft: GUESS_COUNTDOWN });
  const [suggestions, setSuggestions] = useState([]);
  const [result, setResult] = useState(null);
  const [gameOver, setGameOver] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyPage, setHistoryPage] = useState(0);

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

  useEffect(() => {
    try {
      localStorage.setItem("theme", theme);
    } catch {}
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  const toggleTheme = () => setTheme((t) => (t === "dark" ? "light" : "dark"));

  const resetRoundUi = useCallback((size = roomSize) => {
    const draftReq = size === DUO_ROOM_SIZE ? DUO_ROOM_SIZE : ROOM_SIZE;
    setDraft(null);
    setDraftStatus({ submittedCount: 0, requiredCount: draftReq, secondsLeft: DRAFT_COUNTDOWN });
    setDraftSecondsLeft(DRAFT_COUNTDOWN);
    setConstraints(null);
    setGuess("");
    setGuessInfo({ submitted: false, submittedCount: 0, requiredCount: size, secondsLeft: GUESS_COUNTDOWN });
    setSuggestions([]);
    setResult(null);
  }, [roomSize]);

  const clearLocalTimers = useCallback(() => {
    if (localDraftTimerRef.current) clearInterval(localDraftTimerRef.current);
    if (localGuessTimerRef.current) clearInterval(localGuessTimerRef.current);
    if (localNextRoundRef.current) clearTimeout(localNextRoundRef.current);
    localDraftTimerRef.current = null;
    localGuessTimerRef.current = null;
    localNextRoundRef.current = null;
  }, []);

  useEffect(() => {
    isSingleRef.current = isSingle;
  }, [isSingle]);

  useEffect(() => () => clearLocalTimers(), [clearLocalTimers]);

  const handleMessage = useCallback(
    (msg) => {
      switch (msg.type) {
        case "joined": {
          const size = msg.roomSize || ROOM_SIZE;
          setRoomSize(size);
          setPlayerId(msg.playerId);
          setRoomCode(msg.code);
          setHostId(msg.players?.find((p) => p.isHost)?.id || null);
          setPlayers(msg.players || []);
          setScreen("lobby");
          setStatus("");
          setError("");
          const single = !!(msg.players || []).some((p) => p.isBot);
          setSession({ code: msg.code, playerId: msg.playerId, name: msg.name || name, singlePlayer: single, mode: size === DUO_ROOM_SIZE ? "duo" : "multi" });
          break;
        }
        case "lobby_update": {
          if (msg.roomSize) setRoomSize(msg.roomSize);
          setPlayers(msg.players || []);
          setHostId(msg.hostId || null);
          if (screen === "landing") setScreen("lobby");
          break;
        }
        case "round_started": {
          setRound(msg.round || 1);
          setPlayers(msg.players || []);
          setGameOver(null);
          resetRoundUi(roomSize);
          setScreen("drafting"); // may switch to waiting after draft prompt/select
          break;
        }
        case "draft_prompt": {
          setRound(msg.round || round);
          const secs = msg.secondsLeft ?? DRAFT_COUNTDOWN;
          setDraft({
            attribute: msg.attribute,
            attributeLabel: msg.attributeLabel,
            options: msg.options || [],
            selected: msg.selected || null,
            refreshesLeft: msg.refreshesLeft ?? 0,
          });
          setDraftSecondsLeft(secs);
          setDraftStatus((s) => ({ ...s, secondsLeft: secs }));
          setScreen(msg.selected ? "waiting" : "drafting");
          break;
        }
        case "draft_selected": {
          setDraft((d) => (d ? { ...d, selected: msg.value } : d));
          setScreen("waiting");
          break;
        }
        case "draft_status": {
          const secs = msg.secondsLeft;
          setDraftStatus({
            submittedCount: msg.submittedCount ?? 0,
            requiredCount: msg.requiredCount ?? draftStatus.requiredCount ?? (roomSize === DUO_ROOM_SIZE ? DUO_ROOM_SIZE : ROOM_SIZE),
            secondsLeft: secs ?? 0,
          });
          if (typeof secs === "number") setDraftSecondsLeft(secs);
          break;
        }
        case "guess_phase": {
          setRound(msg.round || round);
          setConstraints(msg.constraints || {});
          setGuessInfo({
            submitted: false,
            submittedCount: msg.submittedCount ?? 0,
            requiredCount: msg.requiredCount ?? roomSize,
            secondsLeft: msg.secondsLeft ?? GUESS_COUNTDOWN,
          });
          setGuess("");
          setSuggestions([]);
          setScreen("guessing");
          break;
        }
        case "player_suggestions": {
          setSuggestions(Array.isArray(msg.suggestions) ? msg.suggestions : []);
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
            const next = [...without, msg].sort((a, b) => a.round - b.round);
            setHistoryPage(Math.max(0, next.length - 1));
            return next;
          });
          setScreen(msg.gameOver ? "game_over" : "result");
          break;
        }
        case "game_over": {
          setGameOver(msg);
          setPlayers(msg.players || players);
          if (msg.history) {
            setHistory(msg.history);
            setHistoryPage(Math.max(0, (msg.history.length || 1) - 1));
          }
          setScreen("game_over");
          break;
        }
        case "state_sync": {
          const pid = msg.playerId;
          const size = msg.roomSize || roomSize || ROOM_SIZE;
          setRoomSize(size);
          setPlayerId(pid);
          setRoomCode(msg.code);
          setHostId(msg.hostId || null);
          setPlayers(msg.players || []);
          setRound(msg.round || 0);
          const hist = msg.history || [];
          setHistory(hist);
          setHistoryPage((p) => (hist.length ? Math.min(p, hist.length - 1) : 0));
          setSession({ code: msg.code, playerId: pid, name: session?.name || name, singlePlayer: !!(msg.players || []).some((p) => p.isBot), mode: size === DUO_ROOM_SIZE ? "duo" : "multi" });
          if (msg.state === "lobby") {
            setScreen("lobby");
            resetRoundUi(size);
            setHistoryPage(0);
          } else if (msg.state === "drafting") {
            const d = msg.draft || {};
            const secs = d.secondsLeft ?? DRAFT_COUNTDOWN;
            setDraft({
              attribute: d.attribute,
              attributeLabel: d.attributeLabel,
              options: d.options || [],
              selected: d.selected || null,
              refreshesLeft: d.refreshesLeft ?? 0,
            });
            setDraftStatus({
              submittedCount: d.submittedCount ?? 0,
              requiredCount: d.requiredCount ?? (size === DUO_ROOM_SIZE ? DUO_ROOM_SIZE : ROOM_SIZE),
              secondsLeft: secs,
            });
            setDraftSecondsLeft(secs);
            setScreen(d.selected ? "waiting" : "drafting");
          } else if (msg.state === "guessing") {
            setConstraints(msg.constraints || {});
            setGuessInfo({
              submitted: !!msg.guess?.submitted,
              submittedCount: msg.guess?.submittedCount ?? 0,
              requiredCount: msg.guess?.requiredCount ?? size,
              secondsLeft: msg.guess?.secondsLeft ?? GUESS_COUNTDOWN,
            });
            setSuggestions([]);
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
    [draftStatus.requiredCount, name, players, resetRoundUi, roomSize, round, screen, session?.name]
  );

  useEffect(() => {
    handleMessageRef.current = handleMessage;
  }, [handleMessage]);

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
          setError("Could not connect to the game server. Check that the backend is running and VITE_WS_URL is correct.");
        };
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data);
            (handleMessageRef.current || handleMessage)(msg);
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

  const startLocalDraftTimer = useCallback(() => {
    if (localDraftTimerRef.current) clearInterval(localDraftTimerRef.current);
    localDraftTimerRef.current = setInterval(() => {
      const game = localGameRef.current;
      if (!game || game.state !== "drafting") return;
      const secs = game.draftSecondsLeft();
      setDraftSecondsLeft(secs);
      setDraftStatus((s) => ({ ...s, secondsLeft: secs, submittedCount: Object.keys(game.selections).length, requiredCount: game.requiredSelections() }));
      if (secs <= 0) {
        clearInterval(localDraftTimerRef.current);
        localDraftTimerRef.current = null;
        game.autoSelectMissing();
        setDraftStatus((s) => ({ ...s, submittedCount: game.requiredSelections(), requiredCount: game.requiredSelections(), secondsLeft: 0 }));
        startLocalGuessing();
      }
    }, 500);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const startLocalGuessTimer = useCallback(() => {
    if (localGuessTimerRef.current) clearInterval(localGuessTimerRef.current);
    localGuessTimerRef.current = setInterval(() => {
      const game = localGameRef.current;
      if (!game || game.state !== "guessing") return;
      const secs = game.guessSecondsLeft();
      setGuessInfo((g) => ({ ...g, secondsLeft: secs, submittedCount: Object.keys(game.guesses).length, requiredCount: game.roomSize }));
      if (secs <= 0) {
        clearInterval(localGuessTimerRef.current);
        localGuessTimerRef.current = null;
        finalizeLocalRound();
      }
    }, 500);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const startLocalGuessing = useCallback(() => {
    const game = localGameRef.current;
    if (!game || game.state !== "drafting") return;
    if (localDraftTimerRef.current) {
      clearInterval(localDraftTimerRef.current);
      localDraftTimerRef.current = null;
    }
    game.startGuessing();
    setPlayers(game.playerList());
    setConstraints(game.currentConstraints());
    setGuessInfo({
      submitted: !!game.guesses.p1,
      submittedCount: Object.keys(game.guesses).length,
      requiredCount: game.roomSize,
      secondsLeft: game.guessSecondsLeft() || GUESS_COUNTDOWN,
    });
    setGuess("");
    setSuggestions([]);
    setScreen("guessing");
    if (game.allGuessed()) {
      finalizeLocalRound();
    } else {
      startLocalGuessTimer();
    }
  }, [startLocalGuessTimer]); // eslint-disable-line react-hooks/exhaustive-deps

  const startLocalRound = useCallback(() => {
    const game = localGameRef.current;
    if (!game) return;
    clearLocalTimers();
    game.startRound();
    setRound(game.roundNumber);
    setPlayers(game.playerList());
    setGameOver(null);
    resetRoundUi(game.roomSize);
    const attr = game.assignments.p1;
    const secs = game.draftSecondsLeft() || DRAFT_COUNTDOWN;
    setDraft({
      attribute: attr,
      attributeLabel: ATTRIBUTE_LABELS[attr] || attr,
      options: game.draftOptions.p1 || [],
      selected: game.selections.p1 || null,
      refreshesLeft: game.draftRefreshesLeft.p1 ?? 0,
    });
    setDraftStatus({ submittedCount: Object.keys(game.selections).length, requiredCount: game.requiredSelections(), secondsLeft: secs });
    setDraftSecondsLeft(secs);
    setScreen(game.selections.p1 ? "waiting" : "drafting");
    if (game.allSelected()) {
      startLocalGuessing();
    } else {
      startLocalDraftTimer();
    }
  }, [clearLocalTimers, resetRoundUi, startLocalDraftTimer, startLocalGuessing]);

  const finalizeLocalRound = useCallback(() => {
    const game = localGameRef.current;
    if (!game || game.state !== "guessing") return;
    if (localGuessTimerRef.current) {
      clearInterval(localGuessTimerRef.current);
      localGuessTimerRef.current = null;
    }
    const resultMsg = game.finalizeRound();
    if (!resultMsg) return;
    setResult(resultMsg);
    setPlayers(game.playerList());
    setHistory([...game.history]);
    setHistoryPage(Math.max(0, game.history.length - 1));
    if (resultMsg.gameOver) {
      const winner = game.playerList().find((p) => p.id === resultMsg.winnerId) || null;
      setGameOver({
        type: "game_over",
        winnerId: resultMsg.winnerId,
        winnerName: winner ? winner.name : null,
        draw: !!resultMsg.draw,
        players: game.playerList(),
        history: game.history,
      });
      setScreen("game_over");
    } else {
      setScreen("result");
      localNextRoundRef.current = setTimeout(() => {
        if (isSingleRef.current && localGameRef.current && localGameRef.current.state === "result") {
          startLocalRound();
        }
      }, 2000);
    }
  }, [startLocalRound]);

  const createRoom = (mode = "multi") => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Enter your name");
      return;
    }
    setError("");
    // local single-player modes: "single" (1v2 bots) and "duo" (1v1 bot)
    if (mode === "single" || mode === "duo") {
      clearLocalTimers();
      const game = new FooTrioGame(trimmed, mode);
      localGameRef.current = game;
      setIsSingle(true);
      setSingleMode(mode);
      setRoomSize(game.roomSize);
      setSession(null);
      setPlayerId("p1");
      setRoomCode("LOCAL");
      setPlayers(game.playerList());
      setHostId("p1");
      setRound(0);
      setHistory([]);
      setHistoryPage(0);
      setStatus("");
      resetRoundUi(game.roomSize);
      setScreen("lobby");
      // auto-start
      setTimeout(() => {
        if (localGameRef.current === game) startLocalRound();
      }, 200);
      return;
    }
    if (!WS_URL) {
      setError("Backend WebSocket URL is not configured. Set VITE_WS_URL for multiplayer on deployed builds.");
      return;
    }
    setIsSingle(false);
    localGameRef.current = null;
    setRoomSize(ROOM_SIZE);
    setStatus("Connecting...");
    connect((ws) => {
      ws.send(
        JSON.stringify({
          type: "create_room",
          name: trimmed,
          mode: "multi",
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
    if (!WS_URL) {
      setError("Backend WebSocket URL is not configured. Set VITE_WS_URL for multiplayer on deployed builds.");
      return;
    }
    setError("");
    setIsSingle(false);
    localGameRef.current = null;
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
    if (!WS_URL) return;
    connect((ws) => {
      ws.send(JSON.stringify({ type: "rejoin_room", code: session.code, playerId: session.playerId }));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // guess countdown tick (client-side, multiplayer/server-timed display)
  useEffect(() => {
    if (isSingle) return;
    if (screen !== "guessing") return;
    if (guessInfo.secondsLeft <= 0) return;
    const t = setTimeout(() => {
      setGuessInfo((g) => ({ ...g, secondsLeft: Math.max(0, g.secondsLeft - 1) }));
    }, 1000);
    return () => clearTimeout(t);
  }, [screen, guessInfo.secondsLeft, isSingle]);

  // draft countdown tick (client-side, multiplayer/server-timed display)
  useEffect(() => {
    if (isSingle) return;
    if (screen !== "drafting" && screen !== "waiting") return;
    if (draftSecondsLeft <= 0) return;
    const t = setTimeout(() => {
      setDraftSecondsLeft((s) => Math.max(0, s - 1));
    }, 1000);
    return () => clearTimeout(t);
  }, [screen, draftSecondsLeft, isSingle]);

  const send = (payload) => {
    if (isSingle) return;
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
    }
  };

  const selectOption = (value) => {
    if (!draft || draft.selected) return;
    if (isSingle) {
      const game = localGameRef.current;
      if (!game) return;
      const res = game.submitSelection("p1", value);
      if (!res.ok) {
        setError(res.error || "Invalid selection");
        return;
      }
      setError("");
      setDraft((d) => (d ? { ...d, selected: value } : d));
      setDraftStatus((s) => ({ ...s, submittedCount: Object.keys(game.selections).length, secondsLeft: game.draftSecondsLeft() }));
      setScreen("waiting");
      if (game.allSelected()) {
        startLocalGuessing();
      }
      return;
    }
    send({ type: "select_option", value });
  };

  const refreshDraft = () => {
    if (!draft || draft.selected) return;
    if ((draft.refreshesLeft ?? 0) <= 0) return;
    if (isSingle) {
      const game = localGameRef.current;
      if (!game) return;
      const res = game.refreshDraftOptions("p1");
      if (!res.ok) {
        setError(res.error || "Could not refresh options");
        return;
      }
      const attr = game.assignments.p1;
      setDraft({
        attribute: attr,
        attributeLabel: ATTRIBUTE_LABELS[attr] || attr,
        options: res.options || [],
        selected: game.selections.p1 || null,
        refreshesLeft: res.refreshesLeft ?? 0,
      });
      setError("");
      return;
    }
    send({ type: "refresh_draft" });
  };

  const submitGuess = (value) => {
    const text = (value ?? guess).trim();
    if (!text) {
      setError("Enter a player name guess");
      return;
    }
    setError("");
    setSuggestions([]);
    if (isSingle) {
      const game = localGameRef.current;
      if (!game) return;
      const res = game.submitGuess("p1", text);
      if (!res.ok) {
        setError(res.error || "Invalid guess");
        return;
      }
      setGuessInfo((g) => ({ ...g, submitted: true, submittedCount: Object.keys(game.guesses).length, secondsLeft: game.guessSecondsLeft() }));
      if (game.allGuessed()) {
        finalizeLocalRound();
      }
      return;
    }
    send({ type: "submit_guess", guess: text });
    setGuessInfo((g) => ({ ...g, submitted: true }));
  };

  const handleGuessChange = (e) => {
    const val = e.target.value;
    setGuess(val);
    const q = val.trim();
    if (q.length < 2) {
      setSuggestions([]);
      return;
    }
    if (isSingle) {
      setSuggestions(localSearchPlayerNames(q, 8));
      return;
    }
    send({ type: "search_players", query: q });
  };

  const pickSuggestion = (item) => {
    const name = typeof item === "string" ? item : item?.name || "";
    setGuess(name);
    setSuggestions([]);
  };

  const leaveToHome = () => {
    if (isSingle) {
      clearLocalTimers();
      localGameRef.current = null;
      setIsSingle(false);
    } else {
      send({ type: "leave" });
      try {
        wsRef.current?.close();
      } catch {}
    }
    setSession(null);
    setScreen("landing");
    setPlayers([]);
    setRoomCode(null);
    setPlayerId(null);
    setRound(0);
    resetRoundUi();
    setGameOver(null);
    setHistory([]);
    setHistoryPage(0);
    setStatus("");
    setError("");
  };

  const me = useMemo(() => players.find((p) => p.id === playerId), [players, playerId]);

  // --- UI screens ---
  if (screen === "landing") {
    return (
      <Shell center>
        <div className="card w-full max-w-lg p-8">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h1 className="text-3xl font-extrabold tracking-tight text-[#143524] dark:text-emerald-300">Football Trivia Draft</h1>
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                Draft Country/Position/Club, then guess a matching footballer. Play 3-player multiplayer, 2-player vs bot, or single player vs 2 bots.
              </p>
            </div>
            <button className="btn btn-ghost text-sm whitespace-nowrap" onClick={toggleTheme} aria-label="Toggle dark mode">
              {theme === "dark" ? "☀️ Light" : "🌙 Dark"}
            </button>
          </div>
          <div className="mt-6 space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1 text-slate-700 dark:text-slate-200">Your name</label>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Enter your name" />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <button className="btn btn-primary w-full" onClick={() => createRoom("multi")}>Multiplayer (3)</button>
              <button className="btn btn-secondary w-full" onClick={() => createRoom("duo")}>2-Player vs Bot</button>
              <button className="btn btn-ghost w-full" onClick={() => createRoom("single")}>1 vs 2 Bots</button>
            </div>
            <div className="space-y-2 pt-1">
              <label className="block text-sm font-medium mb-1 text-slate-700 dark:text-slate-200">Join existing room</label>
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
            {status && <p className="text-sm text-slate-600 dark:text-slate-300">{status}</p>}
            {error && <p className="text-sm text-red-600 dark:text-red-400" role="alert">{error}</p>}
            {!WS_URL && (
              <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-2 dark:text-amber-200 dark:bg-amber-900/30 dark:border-amber-700">
                Multiplayer requires a backend WebSocket URL. Single Player works without it. Set <code>VITE_WS_URL</code> for multiplayer on deployed builds.
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
                <h2 className="text-xl font-bold text-[#143524] dark:text-emerald-300">
                  {screen === "lobby" ? "Lobby" : `Round ${round || 1}`}
                </h2>
                <p className="text-sm text-slate-600 dark:text-slate-300">
                  Room <span className="font-mono font-bold tracking-widest">{roomCode}</span> · You:{" "}
                  <span className="font-semibold">{me?.name || name}</span>
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button className="btn btn-ghost text-sm" onClick={toggleTheme} aria-label="Toggle dark mode">
                  {theme === "dark" ? "☀️ Light" : "🌙 Dark"}
                </button>
                <button className="btn btn-ghost text-sm" onClick={() => navigator.clipboard?.writeText(roomCode || "")}>
                  Copy Code
                </button>
                <button className="btn btn-ghost text-sm" onClick={leaveToHome}>Leave</button>
              </div>
            </div>
            {error && <p className="mt-3 text-sm text-red-600 dark:text-red-400" role="alert">{error}</p>}
            {status && <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{status}</p>}
          </div>

          {screen === "lobby" && (
            <div className="card p-6">
              <h3 className="font-semibold text-lg mb-2 text-slate-900 dark:text-slate-100">Waiting for players</h3>
              <p className="text-sm text-slate-600 dark:text-slate-300 mb-4">
                {players.some((p) => p.isBot)
                  ? (roomSize === DUO_ROOM_SIZE
                    ? "2-player mode: you vs 1 bot. Round 1 starts automatically."
                    : "Single player mode: you vs 2 bots. Round 1 starts automatically.")
                  : `Exactly ${roomSize} players are required. Round 1 starts automatically once everyone joins.`}
              </p>
              <PlayerChips players={players} roomSize={roomSize} />
              <div className="mt-4 text-sm text-slate-700 dark:text-slate-300">
                {players.length}/{roomSize} joined
              </div>
            </div>
          )}

          {(screen === "drafting" || screen === "waiting") && (
            <div className="card p-6">
              <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
                <h3 className="font-semibold text-lg text-slate-900 dark:text-slate-100">Drafting Phase</h3>
                <div className="flex items-center gap-2">
                  <span className={`pill ${draftSecondsLeft <= 10 ? "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300" : "bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200"}`}>
                    {draftSecondsLeft}s left
                  </span>
                  <span className="pill bg-emerald-100 text-emerald-800">
                    {draftStatus.submittedCount}/{draftStatus.requiredCount} selected
                  </span>
                </div>
              </div>
              {draft ? (
                <>
                  <p className="text-sm text-slate-700 dark:text-slate-300 mb-4">
                    You are selecting: <span className="font-bold text-[#143524] dark:text-emerald-300">{draft.attributeLabel || draft.attribute || "..."}</span>
                  </p>
                  {(draft.options || []).length > 0 ? (
                    <>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        {(draft.options || []).map((opt) => {
                          const selected = isSameOption(draft.selected, opt);
                          return (
                            <button
                              key={optionKey(opt)}
                              onClick={() => selectOption(opt)}
                              disabled={!!draft.selected}
                              className={`text-left rounded-xl border px-4 py-3 font-medium transition ${
                                selected
                                  ? "bg-emerald-600 text-white border-emerald-600"
                                  : "bg-white hover:bg-emerald-50 border-emerald-200 text-slate-800 dark:bg-slate-800 dark:hover:bg-slate-700 dark:border-slate-600 dark:text-slate-100"
                              } ${draft.selected && !selected ? "opacity-60" : ""}`}
                            >
                              {displayValue(opt)}
                            </button>
                          );
                        })}
                      </div>
                      {(draft.attribute === "country" || draft.attribute === "position" || draft.attribute === "club") && !draft.selected && (
                        <div className="mt-4 flex items-center gap-3">
                          <button
                            className="btn btn-ghost text-sm"
                            onClick={refreshDraft}
                            disabled={(draft.refreshesLeft ?? 0) <= 0}
                          >
                            Refresh picks ({draft.refreshesLeft ?? 0} left)
                          </button>
                          <span className="text-xs text-slate-500 dark:text-slate-400">
                            {draft.attribute === "position"
                              ? "Get a new set of 5 sub-position options."
                              : "Get a new set of 5 options (keeps 3/5 bias)."}
                          </span>
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="space-y-3">
                      <p className="text-slate-600 dark:text-slate-300">No draft options available yet.</p>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        Check that the backend is running, then hard-refresh and click Retry.
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
                  {draft.selected && (
                    <div className="mt-5 p-4 rounded-xl bg-amber-50 border border-amber-200 text-amber-900 dark:bg-amber-900/30 dark:border-amber-700 dark:text-amber-100">
                      <p className="font-semibold">Waiting for others...</p>
                      <p className="text-sm mt-1">
                        You selected <span className="font-bold">{displayValue(draft.selected)}</span>. The 3 attributes will be revealed once everyone has chosen or when the draft timer ends ({draftSecondsLeft}s left).
                      </p>
                    </div>
                  )}
                </>
              ) : (
                <div className="space-y-3">
                  <p className="text-slate-600 dark:text-slate-300">Preparing your draft options...</p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    If this stays stuck, check that the backend is running, then click Retry.
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
                <h3 className="font-semibold text-lg text-slate-900 dark:text-slate-100">Guessing Phase</h3>
                <div className={`pill ${guessInfo.secondsLeft <= 10 ? "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300" : "bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200"}`}>
                  {guessInfo.secondsLeft}s left
                </div>
              </div>
              <div className="mb-4">
                <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">Constraints (all 3 revealed):</p>
                <div className="flex flex-wrap gap-2">
                  <ConstraintChip label="Country" value={displayValue(constraints?.country)} />
                  <ConstraintChip label="Position" value={displayValue(constraints?.position)} />
                  <ConstraintChip label="Club" value={displayValue(constraints?.club)} />
                </div>
              </div>
              {!guessInfo.submitted ? (
                <div className="space-y-3">
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">Name a real-life football player matching all 3 (as best as you can)</label>
                  <div className="relative">
                    <input
                      className="input"
                      value={guess}
                      onChange={handleGuessChange}
                      placeholder="e.g. Cristiano Ronaldo"
                      autoComplete="off"
                      onKeyDown={(e) => {
                        if (e.key === "Enter") submitGuess();
                      }}
                    />
                    {suggestions.length > 0 && (
                      <div className="absolute z-20 mt-1 w-full rounded-xl border border-slate-200 bg-white shadow-lg max-h-60 overflow-auto dark:border-slate-600 dark:bg-slate-800">
                        {suggestions.map((s) => {
                          const name = typeof s === "string" ? s : s?.name || "";
                          const pos = typeof s === "object" && s ? s.position : "";
                          return (
                            <button
                              key={`${name}-${pos}`}
                              type="button"
                              onMouseDown={(e) => e.preventDefault()}
                              onClick={() => pickSuggestion(s)}
                              className="w-full text-left px-4 py-2 hover:bg-emerald-50 text-slate-800 dark:text-slate-100 dark:hover:bg-slate-700"
                            >
                              <span className="font-medium">{name}</span>
                              {pos ? <span className="ml-2 text-xs text-slate-500 dark:text-slate-400">({pos})</span> : null}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400">Type to see suggestions (click a suggestion to fill it in). This helps avoid typos or unknown players.</p>
                  <button className="btn btn-primary" onClick={() => submitGuess()}>Submit Guess</button>
                </div>
              ) : (
                <div className="p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-900 dark:bg-emerald-900/30 dark:border-emerald-700 dark:text-emerald-100">
                  <p className="font-semibold">Guess submitted. Waiting for others...</p>
                  <p className="text-sm mt-1">Results will appear when the timer ends or all players submit.</p>
                </div>
              )}
              <p className="mt-4 text-sm text-slate-600 dark:text-slate-300">
                Guesses submitted: {guessInfo.submittedCount}/{guessInfo.requiredCount}
              </p>
            </div>
          )}

          {(screen === "result" || screen === "game_over") && result && (
            <div className="card p-6">
              <div className="flex items-center justify-between gap-3 mb-3">
                <h3 className="font-semibold text-lg text-slate-900 dark:text-slate-100">
                  {screen === "game_over" ? "Game Over" : `Round ${result.round} Results`}
                </h3>
                {screen !== "game_over" && <span className="pill bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200">Next round starting...</span>}
              </div>

              <div className="mb-4">
                <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">Constraints</p>
                <div className="flex flex-wrap gap-2">
                  <ConstraintChip label="Country" value={displayValue(result.constraints?.country)} />
                  <ConstraintChip label="Position" value={displayValue(result.constraints?.position)} />
                  <ConstraintChip label="Club" value={displayValue(result.constraints?.club)} />
                </div>
              </div>

              <div className="space-y-3">
                {(result.results || []).map((r) => (
                  <div key={r.playerId} className="rounded-xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-800/60">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="font-semibold text-slate-900 dark:text-slate-100">{r.name}</div>
                      <div className="pill bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200">+{r.points} / 3 (Total {r.totalScore})</div>
                    </div>
                    <div className="mt-1 text-sm text-slate-700 dark:text-slate-300">
                      Guess: <span className="font-medium">{r.guess || "(no guess)"}</span>
                    </div>
                    <div className="mt-1 text-sm text-slate-700 dark:text-slate-300">
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
                <div className="mt-5 p-4 rounded-xl bg-amber-50 border border-amber-200 text-amber-900 dark:bg-amber-900/30 dark:border-amber-700 dark:text-amber-100">
                  {(gameOver?.draw || result.draw) ? (
                    <>
                      <p className="font-bold text-lg">Draw!</p>
                      <p className="text-sm mt-1">Two or more players reached 15 points in the same round.</p>
                    </>
                  ) : (
                    <>
                      <p className="font-bold text-lg">
                        Winner: {players.find((p) => p.id === (gameOver?.winnerId || result.winnerId))?.name || "Unknown"}
                      </p>
                      <p className="text-sm mt-1">First to reach 15 points wins.</p>
                    </>
                  )}
                  <button className="btn btn-secondary mt-3" onClick={leaveToHome}>Back to Home</button>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="space-y-5">
          <div className="card p-5">
            <h3 className="font-bold mb-3 text-slate-900 dark:text-slate-100">Scoreboard</h3>
            <div className="space-y-2">
              {[...players]
                .sort((a, b) => (b.score || 0) - (a.score || 0))
                .map((p) => (
                  <div key={p.id} className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-800">
                    <div className="min-w-0">
                      <div className="font-medium truncate text-slate-900 dark:text-slate-100">
                        {p.name} {p.id === playerId ? <span className="text-slate-400 dark:text-slate-400">(you)</span> : null}
                        {p.isHost ? <span className="ml-1 text-amber-700 dark:text-amber-400 text-xs">(host)</span> : null}
                        {p.isBot ? <span className="ml-1 text-slate-500 dark:text-slate-400 text-xs">(bot)</span> : null}
                      </div>
                    </div>
                    <div className="font-bold text-[#143524] dark:text-emerald-300">{p.score ?? 0}</div>
                  </div>
                ))}
              {players.length === 0 && <p className="text-sm text-slate-500 dark:text-slate-400">No players yet.</p>}
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-3">Win condition: reach 15 points.</p>
          </div>

          <div className="card p-5">
            <h3 className="font-bold mb-3 text-slate-900 dark:text-slate-100">Round Info</h3>
            <ul className="text-sm text-slate-700 dark:text-slate-300 space-y-1">
              <li>State: <span className="font-medium text-slate-900 dark:text-slate-100">{screen}</span></li>
              <li>Round: <span className="font-medium text-slate-900 dark:text-slate-100">{round || "-"}</span></li>
              <li>Players: <span className="font-medium text-slate-900 dark:text-slate-100">{players.length}/{roomSize}</span></li>
            </ul>
            {screen === "waiting" && draft?.selected && (
              <div className="mt-3 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-3 dark:text-amber-100 dark:bg-amber-900/30 dark:border-amber-700">
                Waiting for others... ({draftStatus.submittedCount}/{draftStatus.requiredCount} submitted, {draftSecondsLeft}s left)
              </div>
            )}
          </div>

          <div className="card p-5">
            <div className="flex items-center justify-between mb-3 gap-2">
              <h3 className="font-bold text-slate-900 dark:text-slate-100">Session History</h3>
              {history.length > 0 && (
                <span className="text-xs text-slate-500 dark:text-slate-400">
                  {Math.min(historyPage + 1, history.length)}/{history.length}
                </span>
              )}
            </div>
            {history.length === 0 ? (
              <p className="text-sm text-slate-500 dark:text-slate-400">No completed rounds yet.</p>
            ) : (() => {
              const safePage = Math.min(Math.max(historyPage, 0), history.length - 1);
              const h = history[safePage];
              return (
                <div className="space-y-3">
                  <div className="flex items-center justify-between gap-2">
                    <button
                      type="button"
                      onClick={() => setHistoryPage((p) => Math.max(0, Math.min(p, history.length - 1) - 1))}
                      disabled={safePage === 0}
                      className="px-2.5 py-1 text-xs rounded-lg border border-slate-200 bg-white hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed dark:border-slate-600 dark:bg-slate-800 dark:hover:bg-slate-700 dark:text-slate-200"
                    >
                      ← Prev
                    </button>
                    <span className="text-xs font-medium text-slate-600 dark:text-slate-300">Round {h.round}</span>
                    <button
                      type="button"
                      onClick={() => setHistoryPage((p) => Math.min(history.length - 1, Math.min(p, history.length - 1) + 1))}
                      disabled={safePage === history.length - 1}
                      className="px-2.5 py-1 text-xs rounded-lg border border-slate-200 bg-white hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed dark:border-slate-600 dark:bg-slate-800 dark:hover:bg-slate-700 dark:text-slate-200"
                    >
                      Next →
                    </button>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-700 dark:bg-slate-800/60">
                    <div className="flex items-center justify-between mb-1.5 gap-2">
                      <span className="font-semibold text-slate-900 dark:text-slate-100">Round {h.round}</span>
                      <span className="text-xs text-slate-500 dark:text-slate-400 text-right">
                        {displayValue(h.constraints?.country)} · {displayValue(h.constraints?.position)} · {displayValue(h.constraints?.club)}
                      </span>
                    </div>
                    <ul className="space-y-1.5">
                      {(h.results || []).map((r) => (
                        <li key={r.playerId} className="text-xs">
                          <div className="flex justify-between gap-2">
                            <span className="font-medium text-slate-800 dark:text-slate-200 truncate">{r.name}</span>
                            <span className="font-semibold text-slate-900 dark:text-slate-100">+{r.points}</span>
                          </div>
                          <div className="text-slate-600 dark:text-slate-400 truncate">
                            Guess: <span className="font-medium">{r.guess || "—"}</span>
                          </div>
                          <div className="text-slate-600 dark:text-slate-400 truncate">
                            Matched: <span className="font-medium">{r.matched_player?.name || "No match found"}</span>
                          </div>
                          <div className="mt-1 flex flex-wrap gap-1">
                            <BreakdownPill label="Country" ok={r.breakdown?.country} />
                            <BreakdownPill label="Position" ok={r.breakdown?.position} />
                            <BreakdownPill label="Club" ok={r.breakdown?.club} />
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              );
            })()}
          </div>
        </div>
      </div>
    </Shell>
  );
}

function displayValue(v) {
  if (v && typeof v === "object") return v.name ?? v.label ?? String(v.id ?? "");
  return v ?? "";
}

function optionKey(v) {
  if (v && typeof v === "object") return String(v.id ?? v.name ?? "");
  return String(v ?? "");
}

function isSameOption(a, b) {
  if (a == null || b == null) return false;
  if (typeof a === "object" || typeof b === "object") return optionKey(a) === optionKey(b);
  return a === b;
}

function Shell({ children, center = false }) {
  return (
    <div className={`min-h-screen px-4 py-6 md:py-10 flex justify-center ${center ? "items-center" : "items-start"}`}>
      <div className="w-full max-w-6xl flex justify-center">{children}</div>
    </div>
  );
}

function PlayerChips({ players, roomSize = 3 }) {
  return (
    <div className="flex flex-wrap gap-2">
      {players.map((p) => (
        <span key={p.id} className="pill bg-emerald-100 text-emerald-800 border border-emerald-200 dark:bg-emerald-900/40 dark:text-emerald-200 dark:border-emerald-700">
          {p.name}
          {p.isHost ? " (host)" : ""}
          {p.isBot ? " (bot)" : ""}
        </span>
      ))}
      {Array.from({ length: Math.max(0, roomSize - players.length) }).map((_, i) => (
        <span key={`empty-${i}`} className="pill bg-slate-100 text-slate-500 border border-slate-200 dark:bg-slate-700 dark:text-slate-300 dark:border-slate-600">
          Waiting...
        </span>
      ))}
    </div>
  );
}

function ConstraintChip({ label, value }) {
  return (
    <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 dark:border-emerald-800 dark:bg-emerald-900/30">
      <div className="text-[11px] uppercase tracking-wide text-emerald-700 dark:text-emerald-300 font-semibold">{label}</div>
      <div className="font-semibold text-[#143524] dark:text-slate-100">{value || "?"}</div>
    </div>
  );
}

function BreakdownPill({ label, ok }) {
  return (
    <span className={`pill ${ok ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200" : "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-200"}`}>
      {label} {ok ? "+1" : "+0"}
    </span>
  );
}
