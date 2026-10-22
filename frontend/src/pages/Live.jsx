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
              latency: st.output_snapshot?.latency_ms ? `${st.output_snapshot.latency_ms} ms` : '-',
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
            latency: payload.data.latency_ms ? `${payload.data.latency_ms} ms` : '-',
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

  return (
    <div>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 className="page-title">Live Pipeline Activity</h1>
          <p className="page-subtitle">Real-time WebSocket stream of pipeline execution stages</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div className="live-pill">
            <span className="live-dot" style={{ background: isConnected ? 'var(--success)' : 'var(--danger)' }} />
            <span style={{ color: isConnected ? 'var(--success)' : 'var(--danger)' }}>{status}</span>
          </div>
          {stages.length > 0 && (
            <button className="form-btn" style={{ padding: '6px 12px', fontSize: 12 }} onClick={() => setStages([])}>
              Clear
            </button>
          )}
        </div>
      </div>

      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: 120 }}>Time</th>
              <th style={{ width: 180 }}>Event ID</th>
              <th style={{ width: 220 }}>Stage</th>
              <th style={{ width: 100 }}>Latency</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {stages.length === 0 ? (
              <tr>
                <td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 40 }}>
                  <p style={{ marginBottom: 12 }}>Waiting for live events... No recent disruption in feed.</p>
                  <Link to="/simulate" className="form-btn" style={{ display: 'inline-block', textDecoration: 'none' }}>
                    Trigger a Simulation Event →
                  </Link>
                </td>
              </tr>
            ) : (
              stages.map((st) => (
                <tr key={st.id}>
                  <td style={{ color: 'var(--text-muted)', fontFamily: 'monospace' }}>{st.time}</td>
                  <td style={{ fontFamily: 'monospace', fontWeight: 600 }}>{st.eventId}</td>
                  <td><span className="badge badge-neutral" style={{ fontWeight: 700 }}>{st.stage}</span></td>
                  <td>{st.latency}</td>
                  <td style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                    {st.stage === 'RESULT' && st.snapshot.action ? (
                      <span className={`badge ${st.snapshot.action === 'REBOOKED' ? 'badge-success' : 'badge-warning'}`}>
                        {st.snapshot.action}
                      </span>
                    ) : st.snapshot.policy_verdict ? (
                      `Verdict: ${st.snapshot.policy_verdict}`
                    ) : st.snapshot.model_used ? (
                      `Model: ${st.snapshot.model_used}`
                    ) : (
                      'Completed'
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
