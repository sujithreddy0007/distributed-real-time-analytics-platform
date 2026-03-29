/**
 * App.jsx — Main React Dashboard Component
 * ==========================================
 * Real-Time Sports Analytics Dashboard
 * Connects to the FastAPI WebSocket and renders live match stats, serve speed
 * charts, AI commentary feed, player comparisons, and system health indicators.
 *
 * WebSocket lifecycle:
 *   1. Connect to ws://API_HOST/ws/live on mount
 *   2. Receive JSON payloads every ~1 second
 *   3. Update React state → panels re-render only changed data
 *   4. Auto-reconnect on disconnect (exponential back-off)
 */

import { useEffect, useRef, useState, useCallback } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import "./App.css";

const WS_URL = process.env.REACT_APP_WS_URL || "ws://192.168.1.12:8000/ws/live";
const API_URL = process.env.REACT_APP_API_URL || "http://192.168.1.12:8000";
const MAX_SPEED_POINTS = 30; // Rolling chart window

// ── Custom Hook: WebSocket with reconnect ─────────────────────────────────────
function useLiveWebSocket(url, onMessage) {
  const wsRef = useRef(null);
  const [connected, setConnected] = useState(false);
  const reconnectDelay = useRef(1000);

  const connect = useCallback(() => {
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      reconnectDelay.current = 1000; // Reset delay on successful connection
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch (e) {
        console.error("[WS] Failed to parse message:", e);
      }
    };

    ws.onclose = () => {
      setConnected(false);
      // Exponential back-off reconnect: 1s → 2s → 4s → max 30s
      setTimeout(() => {
        reconnectDelay.current = Math.min(reconnectDelay.current * 2, 30000);
        connect();
      }, reconnectDelay.current);
    };

    ws.onerror = (e) => console.error("[WS] Error:", e);
  }, [url, onMessage]);

  useEffect(() => {
    connect();
    return () => wsRef.current?.close();
  }, [connect]);

  return connected;
}

// ── Sub-Components ─────────────────────────────────────────────────────────────
function StatCard({ label, value, unit = "", highlight = false }) {
  return (
    <div className={`stat-card ${highlight ? "stat-card--highlight" : ""}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">
        {value ?? "—"}
        {unit && <span className="stat-unit"> {unit}</span>}
      </span>
    </div>
  );
}

function CommentaryFeed({ lines }) {
  return (
    <div className="commentary-feed">
      <h3 className="panel-title">🎙 AI Commentary</h3>
      {lines.length === 0 && (
        <p className="commentary-empty">Waiting for significant events…</p>
      )}
      {lines.map((item, i) => (
        <div key={i} className="commentary-item">
          <span className="commentary-time">
            {new Date(item.timestamp).toLocaleTimeString()}
          </span>
          <p className="commentary-text">{item.text}</p>
        </div>
      ))}
    </div>
  );
}

function HealthIndicator({ component, status }) {
  const statusClass =
    status === "healthy" ? "health-green" : status === "degraded" ? "health-amber" : "health-red";
  return (
    <div className="health-item">
      <span className={`health-dot ${statusClass}`} />
      <span className="health-label">{component}</span>
    </div>
  );
}

// ── Main App ───────────────────────────────────────────────────────────────────
export default function App() {
  const [stats, setStats] = useState({});
  const [commentary, setCommentary] = useState([]);
  const [speedHistory, setSpeedHistory] = useState([]);
  const [health, setHealth] = useState({});

  // Handler for incoming WebSocket messages
  const handleMessage = useCallback((data) => {
    if (data.type === "update") {
      setStats(data.stats || {});
      if (data.commentary?.length) {
        setCommentary(data.commentary.slice(0, 5));
      }
      // Append latest serve speed to rolling chart
      if (data.stats?.avg_serve_speed) {
        setSpeedHistory((prev) => {
          const next = [
            ...prev,
            {
              time: new Date().toLocaleTimeString(),
              speed: parseFloat(data.stats.avg_serve_speed.toFixed(1)),
            },
          ];
          return next.slice(-MAX_SPEED_POINTS);
        });
      }
    }
  }, []);

  // Fetch health status separately (less frequent)
  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const res = await fetch(`${API_URL}/health`);
        const data = await res.json();
        setHealth(data.components || {});
      } catch (e) {
        console.error("Health check failed:", e);
      }
    };
    fetchHealth();
    const interval = setInterval(fetchHealth, 15000); // every 15s
    return () => clearInterval(interval);
  }, []);

  const connected = useLiveWebSocket(WS_URL, handleMessage);

  return (
    <div className="app">
      {/* ── Header ── */}
      <header className="app-header">
        <div className="header-left">
          <h1 className="app-title">⚡ Sports Analytics Live</h1>
          <span className="header-subtitle">Powered by Kafka · Spark · RAG</span>
        </div>
        <div className="connection-badge">
          <span className={`ws-dot ${connected ? "ws-dot--live" : "ws-dot--offline"}`} />
          {connected ? "LIVE" : "Reconnecting…"}
        </div>
      </header>

      <main className="dashboard-grid">
        {/* ── Rolling Stats Panel ── */}
        <section className="panel panel--stats">
          <h3 className="panel-title">📊 Live Match Stats</h3>
          <div className="stats-grid">
            <StatCard label="Player" value={stats.player} highlight />
            <StatCard label="Avg Serve Speed" value={stats.avg_serve_speed} unit="km/h" />
            <StatCard label="Ace Count" value={stats.ace_count} highlight />
            <StatCard label="1st Serve %" value={stats.first_serve_pct} unit="%" />
          </div>
        </section>

        {/* ── Serve Speed Chart ── */}
        <section className="panel panel--chart">
          <h3 className="panel-title">📈 Rolling Serve Speed</h3>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={speedHistory}>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis dataKey="time" tick={{ fontSize: 10, fill: "#aaa" }} interval="preserveStartEnd" />
              <YAxis domain={[130, 240]} tick={{ fontSize: 10, fill: "#aaa" }} unit=" km/h" />
              <Tooltip
                contentStyle={{ background: "#1a1a2e", border: "1px solid #444", borderRadius: 8 }}
                labelStyle={{ color: "#eee" }}
              />
              <Line
                type="monotone"
                dataKey="speed"
                stroke="#6c63ff"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 5, fill: "#ff6584" }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </section>

        {/* ── AI Commentary ── */}
        <section className="panel panel--commentary">
          <CommentaryFeed lines={commentary} />
        </section>

        {/* ── System Health ── */}
        <section className="panel panel--health">
          <h3 className="panel-title">🔧 System Health</h3>
          <div className="health-grid">
            {Object.entries(health).map(([comp, status]) => (
              <HealthIndicator key={comp} component={comp} status={status} />
            ))}
            {Object.keys(health).length === 0 && (
              <p style={{ color: "#888", fontSize: 13 }}>Loading health data…</p>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
