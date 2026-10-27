/**
 * Live Feed Page.
 * Connects to the backend WebSocket stream (/api/v1/ws/activity)
 * and displays pipeline stages in real time (time, event id, stage).
 * Preloads the most recent event's stages so the view is never empty on load.
 */
import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { getWebSocketUrl, fetchEvents, fetchEventDetail } from '../api.js';

export default function Live() {
  const [stages, setStages] = useState([]);
  const [status, setStatus] = useState('Connecting...');
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef(null);

  // Pre-load recent event stages so the table is immediately populated
  useEffect(() => {
    async function loadRecent() {
      try {
        const events = await fetchEvents(1);
        if (events && events.length > 0) {
          const detail = await fetchEventDetail(events[0].event_id);
          if (detail && detail.stages) {
            const recent = detail.stages.map((st, idx) => ({
              id: `init-${st.id || idx}`,
              time: st.timestamp ? new Date(st.timestamp).toLocaleTimeString() : new Date().toLocaleTimeString(),
              eventId: detail.event_id,
              stage: st.stage,
              latency: st.output_snapshot?.latency_ms ? `${Math.round(st.output_snapshot.latency_ms)} ms` : '-',
              snapshot: st.output_snapshot || {},
            }));
            setStages(recent);
          }
        }
      } catch (err) {
        // Fall back to empty stream if no events exist yet
      }
    }
    loadRecent();
  }, []);

  // Connect to live WebSocket stream
  useEffect(() => {
    const ws = new WebSocket(getWebSocketUrl());
    wsRef.current = ws;

    ws.onopen = () => { setStatus('Connected'); setIsConnected(true); };
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === 'STAGE_TRACE' && payload.data) {
          const item = {
            id: `${Date.now()}-${Math.random()}`,
            time: payload.data.timestamp ? new Date(payload.data.timestamp).toLocaleTimeString() : new Date().toLocaleTimeString(),
            eventId: payload.data.event_id || 'N/A',
            stage: payload.data.stage || 'STAGE',
            latency: payload.data.latency_ms ? `${Math.round(payload.data.latency_ms)} ms` : '-',
            snapshot: payload.data.output_snapshot || {},
          };
          setStages((prev) => [item, ...prev].slice(0, 100));
        }
      } catch (e) {}
    };
    ws.onerror = () => { setStatus('Connection Error'); setIsConnected(false); };
    ws.onclose = () => { setStatus('Disconnected'); setIsConnected(false); };

    return () => ws.close();
  }, []);

  const getStageChipClass = (stageStr) => {
    const s = (stageStr || '').toUpperCase();
    if (s.includes('RESULT') || s.includes('CONFIRM')) return 'chip-green';
    if (s.includes('DISRUPTION') || s.includes('VERIFY')) return 'chip-amber';
    if (s.includes('ERROR') || s.includes('FAIL')) return 'chip-red';
    return 'chip-blue';
  };

  const getActionChipClass = (actionStr) => {
    const a = (actionStr || '').toUpperCase();
    if (a.includes('REBOOK')) return 'chip-green';
    if (a.includes('ESCALAT')) return 'chip-amber';
    if (a.includes('CANCEL') || a.includes('ERROR')) return 'chip-red';
    return 'chip-blue';
  };

  return (
    <div className="page-section">
      <div className="page-header header-with-action">
        <div>
          <div className="header-meta">LIVE DISPATCH · WEBSOCKET FEED</div>
          <h1 className="page-title">Live Pipeline Activity</h1>
          <p className="page-subtitle">Real-time telemetry stream of autonomous decision pipeline execution stages</p>
        </div>

        <div className="header-actions">
          <div className="live-status-pill">
            <span
              className="live-pulse-dot"
              style={{ background: isConnected ? 'var(--status-green)' : 'var(--status-red)' }}
              aria-hidden="true"
            />
            <span style={{ color: isConnected ? 'var(--status-green)' : 'var(--status-red)' }}>
              {status.toUpperCase()}
            </span>
          </div>
          {stages.length > 0 && (
            <button
              type="button"
              className="btn-secondary"
              aria-label="Clear live pipeline stages ticker"
              onClick={() => setStages([])}
            >
              Clear Ticker
            </button>
          )}
        </div>
      </div>

      <div className="airline-card departure-board-card">
        <div className="card-header-bar">
          <h2 className="section-title">Real-Time Status Ticker</h2>
          <span className="card-tag tabular">{stages.length} ACTIVE STAGES</span>
        </div>

        <div className="table-responsive-wrapper">
          <table className="departure-table">
            <thead>
              <tr>
                <th scope="col" style={{ width: '120px' }}>Time</th>
                <th scope="col" style={{ width: '160px' }}>Event ID</th>
                <th scope="col" style={{ width: '200px' }}>Stage</th>
                <th scope="col" style={{ width: '110px' }}>Latency</th>
                <th scope="col">Execution Output / Status</th>
              </tr>
            </thead>
            <tbody>
              {stages.length === 0 ? (
                <tr>
                  <td colSpan={5} className="empty-table-cell">
                    <p style={{ marginBottom: 12 }}>Waiting for live activity... No recent disruption events in stream.</p>
                    <Link to="/simulate" className="btn-primary" style={{ display: 'inline-block', textDecoration: 'none' }}>
                      Trigger a Simulation Event →
                    </Link>
                  </td>
                </tr>
              ) : (
                stages.map((st) => (
                  <tr key={st.id} className="board-row">
                    <td data-label="Time" className="tabular time-cell">
                      {st.time}
                    </td>
                    <td data-label="Event ID" className="monospace event-id-cell">
                      {st.eventId && st.eventId !== 'N/A' ? (
                        <Link to={`/events/${st.eventId}`} className="event-link">
                          {st.eventId}
                        </Link>
                      ) : (
                        st.eventId
                      )}
                    </td>
                    <td data-label="Stage">
                      <span className={`status-chip ${getStageChipClass(st.stage)}`}>
                        {st.stage}
                      </span>
                    </td>
                    <td data-label="Latency" className="tabular latency-cell">
                      {st.latency}
                    </td>
                    <td data-label="Execution Output / Status" className="details-cell">
                      {st.stage === 'RESULT' && st.snapshot.action ? (
                        <span className={`status-chip ${getActionChipClass(st.snapshot.action)}`}>
                          ● {st.snapshot.action}
                        </span>
                      ) : st.snapshot.policy_verdict ? (
                        <span className="verdict-tag">Verdict: {st.snapshot.policy_verdict}</span>
                      ) : st.snapshot.model_used ? (
                        <span className="model-tag">Model: {st.snapshot.model_used}</span>
                      ) : (
                        <span className="neutral-tag">Completed</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

