import { Terminal, useTerminal } from "@wterm/react";
import { GhosttyCore } from "@wterm/ghostty";
import type { TerminalCore, WTerm } from "@wterm/dom";
import "@wterm/react/css";
import { Button } from "@nous-research/ui/ui/components/button";
import { HERMES_BASE_PATH, api, buildWsAuthParam } from "@/lib/api";
import type { TerminalContainerInfo } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Box, Monitor, PlugZap, RefreshCw, RotateCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type TerminalMode = "host" | "docker";
type ConnectionState =
  | "loading"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "error";

function generateTerminalSessionId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `term-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;
}

function buildTerminalWsUrl(
  authParam: [string, string],
  sessionId: string,
  mode: TerminalMode,
  container: string,
): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const qs = new URLSearchParams({
    [authParam[0]]: authParam[1],
    session: sessionId,
    mode,
  });
  if (mode === "docker" && container) {
    qs.set("container", container);
  }
  return `${proto}//${window.location.host}${HERMES_BASE_PATH}/api/terminal/pty?${qs.toString()}`;
}

export default function TerminalPage() {
  const { ref, write, focus } = useTerminal();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const termRef = useRef<WTerm | null>(null);
  const [core, setCore] = useState<TerminalCore | null>(null);
  const [coreSessionId, setCoreSessionId] = useState<string | null>(null);
  const [status, setStatus] = useState<ConnectionState>("loading");
  const [message, setMessage] = useState("Loading terminal core...");
  const [mode, setMode] = useState<TerminalMode>("host");
  const [sessionId, setSessionId] = useState(() => generateTerminalSessionId());
  const [connectSeq, setConnectSeq] = useState(0);
  const [containers, setContainers] = useState<TerminalContainerInfo[]>([]);
  const [selectedContainer, setSelectedContainer] = useState("");
  const [dockerError, setDockerError] = useState<string | null>(null);
  const [containersLoading, setContainersLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    GhosttyCore.load({ scrollbackLimit: 10000 })
      .then((nextCore) => {
        if (cancelled) return;
        setCore(nextCore);
        setCoreSessionId(sessionId);
        setStatus("disconnected");
        setMessage("Ready");
      })
      .catch((err) => {
        if (cancelled) return;
        const text = err instanceof Error ? err.message : String(err);
        setStatus("error");
        setMessage(`Terminal core failed to load: ${text}`);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const refreshContainers = useCallback(() => {
    setContainersLoading(true);
    api
      .getTerminalContainers()
      .then((res) => {
        setContainers(res.containers);
        setDockerError(res.error);
        setSelectedContainer((current) => {
          if (current && res.containers.some((c) => c.id === current || c.name === current)) {
            return current;
          }
          return res.containers[0]?.id ?? "";
        });
      })
      .catch((err) => {
        const text = err instanceof Error ? err.message : String(err);
        setContainers([]);
        setDockerError(text);
        setSelectedContainer("");
      })
      .finally(() => setContainersLoading(false));
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .getTerminalContainers()
      .then((res) => {
        if (cancelled) return;
        setContainers(res.containers);
        setDockerError(res.error);
        setSelectedContainer(res.containers[0]?.id ?? "");
      })
      .catch((err) => {
        if (cancelled) return;
        const text = err instanceof Error ? err.message : String(err);
        setContainers([]);
        setDockerError(text);
        setSelectedContainer("");
      })
      .finally(() => {
        if (!cancelled) setContainersLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const activeContainer = useMemo(
    () => containers.find((c) => c.id === selectedContainer || c.name === selectedContainer),
    [containers, selectedContainer],
  );

  const switchMode = useCallback(
    (nextMode: TerminalMode) => {
      if (nextMode === mode) return;
      setMode(nextMode);
      setSessionId(generateTerminalSessionId());
      setConnectSeq((n) => n + 1);
    },
    [mode],
  );

  const switchContainer = useCallback((container: string) => {
    setSelectedContainer(container);
    setSessionId(generateTerminalSessionId());
    setConnectSeq((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!core) return;
    if (coreSessionId !== sessionId) return;
    if (mode === "docker" && !selectedContainer) {
      return;
    }

    let closedByEffect = false;

    const clearReconnectTimer = () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };

    const connect = async () => {
      clearReconnectTimer();
      setStatus((prev) => (prev === "connected" ? "connected" : "connecting"));
      setMessage("Connecting...");
      try {
        const authParam = await buildWsAuthParam();
        if (closedByEffect) return;
        const url = buildTerminalWsUrl(authParam, sessionId, mode, selectedContainer);
        const ws = new WebSocket(url);
        ws.binaryType = "arraybuffer";
        wsRef.current = ws;

        ws.onopen = () => {
          if (closedByEffect) return;
          setStatus("connected");
          setMessage(mode === "host" ? "Host shell connected" : `Container connected: ${activeContainer?.name ?? selectedContainer}`);
          const wt = termRef.current;
          if (wt) {
            ws.send(`\x1b[RESIZE:${wt.cols};${wt.rows}]`);
          }
          focus();
        };

        ws.onmessage = (ev) => {
          if (typeof ev.data === "string") {
            write(ev.data);
          } else {
            write(new Uint8Array(ev.data as ArrayBuffer));
          }
        };

        ws.onclose = (ev) => {
          if (wsRef.current === ws) {
            wsRef.current = null;
          }
          if (closedByEffect) return;
          if (ev.code === 4401) {
            setStatus("error");
            setMessage("WebSocket auth failed. Reload the dashboard.");
            return;
          }
          if (ev.code === 4403) {
            setStatus("error");
            setMessage("Terminal is disabled or not reachable from this dashboard session.");
            return;
          }
          if (ev.code === 4409) {
            setStatus("error");
            setMessage("This terminal session is already attached in another tab.");
            return;
          }
          setStatus("reconnecting");
          setMessage("Connection lost. Reconnecting...");
          reconnectTimerRef.current = setTimeout(() => {
            reconnectTimerRef.current = null;
            setConnectSeq((n) => n + 1);
          }, 1000);
        };

        ws.onerror = () => {
          if (closedByEffect) return;
          setStatus("reconnecting");
          setMessage("WebSocket error. Reconnecting...");
        };
      } catch (err) {
        if (closedByEffect) return;
        const text = err instanceof Error ? err.message : String(err);
        setStatus("error");
        setMessage(text);
      }
    };

    void connect();

    return () => {
      closedByEffect = true;
      clearReconnectTimer();
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws && ws.readyState !== WebSocket.CLOSED) {
        ws.close();
      }
    };
  }, [activeContainer?.name, connectSeq, core, coreSessionId, focus, mode, selectedContainer, sessionId, write]);

  const handleReady = useCallback(
    (wt: WTerm) => {
      termRef.current = wt;
      focus();
    },
    [focus],
  );

  const handleData = useCallback((data: string) => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(data);
    }
  }, []);

  const handleResize = useCallback((cols: number, rows: number) => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(`\x1b[RESIZE:${cols};${rows}]`);
    }
  }, []);

  const reconnect = useCallback(() => {
    setConnectSeq((n) => n + 1);
  }, []);

  const displayStatus: ConnectionState =
    coreSessionId !== sessionId ? "loading" : mode === "docker" && !selectedContainer ? "disconnected" : status;
  const displayMessage =
    coreSessionId !== sessionId
      ? "Loading terminal core..."
      : mode === "docker" && !selectedContainer
      ? "No running Docker container selected"
      : message;
  const terminalReady = core !== null && coreSessionId === sessionId;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div
        className={cn(
          "flex shrink-0 flex-col gap-2 border border-current/20 bg-black/20 px-3 py-2",
          "sm:flex-row sm:items-center sm:justify-between",
        )}
      >
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <div className="inline-flex overflow-hidden border border-current/20">
            <Button
              ghost
              onClick={() => switchMode("host")}
              className={cn(
                "rounded-none px-3 py-1.5 text-xs",
                mode === "host" ? "bg-midground/15 text-midground" : "text-text-secondary",
              )}
            >
              <Monitor className="h-3.5 w-3.5" />
              Host
            </Button>
            <Button
              ghost
              onClick={() => switchMode("docker")}
              className={cn(
                "rounded-none border-l border-current/20 px-3 py-1.5 text-xs",
                mode === "docker" ? "bg-midground/15 text-midground" : "text-text-secondary",
              )}
            >
              <Box className="h-3.5 w-3.5" />
              Docker
            </Button>
          </div>

          {mode === "docker" && (
            <>
              <select
                aria-label="Docker container"
                value={selectedContainer}
                onChange={(e) => switchContainer(e.target.value)}
                className={cn(
                  "h-8 max-w-[min(20rem,70vw)] border border-current/20 bg-background-base px-2 text-xs text-midground",
                  "focus:outline-none focus:ring-1 focus:ring-midground",
                )}
              >
                {containers.length === 0 ? (
                  <option value="">No running containers</option>
                ) : (
                  containers.map((container) => (
                    <option key={container.id} value={container.id}>
                      {container.name || container.id} - {container.image}
                    </option>
                  ))
                )}
              </select>
              <Button
                ghost
                size="icon"
                onClick={refreshContainers}
                aria-label="Refresh Docker containers"
                className="h-8 w-8 text-text-secondary hover:text-midground"
              >
                <RefreshCw className={cn("h-3.5 w-3.5", containersLoading && "animate-spin")} />
              </Button>
            </>
          )}
        </div>

        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-xs text-text-secondary">
            <span className="inline-flex items-center gap-1.5">
              <PlugZap className="h-3.5 w-3.5 shrink-0" />
              <span className={cn(displayStatus === "connected" && "text-midground", displayStatus === "error" && "text-warning")}>
                {displayMessage}
              </span>
            </span>
          </span>
          <Button
            ghost
            size="icon"
            onClick={reconnect}
            aria-label="Reconnect terminal"
            className="h-8 w-8 shrink-0 text-text-secondary hover:text-midground"
          >
            <RotateCw className={cn("h-3.5 w-3.5", displayStatus === "reconnecting" && "animate-spin")} />
          </Button>
        </div>
      </div>

      {dockerError && mode === "docker" && (
        <div className="border border-warning/50 bg-warning/10 px-3 py-2 text-xs text-warning">
          {dockerError}
        </div>
      )}

      <div
        className="min-h-0 min-w-0 flex-1 overflow-hidden rounded-lg bg-[#0d2626] p-2 shadow-[0_8px_32px_rgba(0,0,0,0.4)] sm:p-3"
      >
        {terminalReady ? (
          <Terminal
            key={sessionId}
            ref={ref}
            core={core}
            cols={100}
            rows={30}
            autoResize
            cursorBlink
            onReady={handleReady}
            onData={handleData}
            onResize={handleResize}
            onError={(err) => {
              const text = err instanceof Error ? err.message : String(err);
              setStatus("error");
              setMessage(text);
            }}
            className="h-full min-h-0 w-full"
            style={{ borderRadius: 0, boxShadow: "none", padding: 0 }}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-text-secondary">
            {displayMessage}
          </div>
        )}
      </div>
    </div>
  );
}
