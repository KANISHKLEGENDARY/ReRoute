/**
 * Events and Traces Page.
 * Displays a table of recent events; clicking an event loads and displays its
 * execution trace: each stage in chronological order with expandable JSON and final result.
 */
import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { fetchEvents, fetchEventDetail } from '../api.js';

export default function Events() {
  const { eventId: urlEventId } = useParams();
  const navigate = useNavigate();
  const [events, setEvents] = useState([]);
  const [selectedEventId, setSelectedEventId] = useState(urlEventId || null);
  const [traceDetail, setTraceDetail] = useState(null);
  const [expandedStages, setExpandedStages] = useState({});
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    fetchEvents(50).then(setEvents).catch(console.error).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const targetId = urlEventId || selectedEventId;
    if (!targetId) { setTraceDetail(null); return; }
    setDetailLoading(true);
    fetchEventDetail(targetId).then(setTraceDetail).catch(console.error).finally(() => setDetailLoading(false));
  }, [urlEventId, selectedEventId]);

  const selectEvent = (id) => { setSelectedEventId(id); navigate(`/events/${id}`); };
  const clearSelection = () => { setSelectedEventId(null); setTraceDetail(null); navigate('/events'); };
  const toggleStageJson = (id) => setExpandedStages((p) => ({ ...p, [id]: !p[id] }));

  if (loading) return <div className="page-header"><p>Loading events...</p></div>;

  return (
    <div>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 className="page-title">Disruption Events & Traces</h1>
          <p className="page-subtitle">Inspect historical disruption decisions and pipeline stage-by-stage executions</p>
        </div>
        {selectedEventId && (
          <button className="form-btn" onClick={clearSelection} style={{ background: 'var(--text-muted)' }}>
            ← Back to All Events
          </button>
        )}
      </div>

      {selectedEventId && traceDetail ? (
        <div>
          <div className="metric-card" style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <div>
                <div className="metric-label">Event Result Overview</div>
                <div className="metric-value" style={{ fontSize: 20 }}>{traceDetail.event_id}</div>
              </div>
              {traceDetail.result && (
                <span className={`badge ${traceDetail.result.action === 'REBOOKED' ? 'badge-success' : 'badge-warning'}`}>
                  {traceDetail.result.action || 'COMPLETED'}
                </span>
              )}
            </div>
            {traceDetail.result && (
              <div style={{ marginTop: 12, fontSize: 13, color: 'var(--text-muted)' }}>
                <span><strong>Verdict:</strong> {traceDetail.result.policy_verdict || 'N/A'} | </span>
                <span><strong>Fare Delta:</strong> ₹{traceDetail.result.fare_delta_inr ?? 0} | </span>
                <span><strong>Latency:</strong> {traceDetail.result.latency_ms ?? 0} ms | </span>
                <span><strong>Tokens:</strong> {(traceDetail.result.tokens_in ?? 0) + (traceDetail.result.tokens_out ?? 0)}</span>
                {traceDetail.result.explanation && (
                  <p style={{ marginTop: 8, color: 'var(--text-main)', background: 'var(--bg-page)', padding: 10, borderRadius: 6 }}>
                    {traceDetail.result.explanation}
                  </p>
                )}
              </div>
            )}
          </div>

          <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Execution Trace Stages</h3>
          {detailLoading ? <p>Loading stages...</p> : (
            <div className="trace-timeline">
              {traceDetail.stages.map((st, idx) => (
                <div key={st.id || idx} className="stage-item">
                  <div className="stage-header" onClick={() => toggleStageJson(st.id || idx)}>
                    <div>
                      <span style={{ color: 'var(--text-muted)', fontSize: 12, marginRight: 8 }}>#{idx + 1}</span>
                      <span className="stage-title">{st.stage}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{new Date(st.timestamp).toLocaleTimeString()}</span>
                      <button style={{ background: 'none', border: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12 }}>
                        {expandedStages[st.id || idx] ? 'Hide JSON ▲' : 'View JSON ▼'}
                      </button>
                    </div>
                  </div>
                  {expandedStages[st.id || idx] && (
                    <pre className="json-view">{JSON.stringify({ input: st.input_snapshot, output: st.output_snapshot }, null, 2)}</pre>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Event ID</th><th>Disruption</th><th>Action</th><th>Verdict</th><th>Fare Delta</th><th>Latency</th><th>Time</th>
              </tr>
            </thead>
            <tbody>
              {events.length === 0 ? (
                <tr><td colSpan={7} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 40 }}>No events recorded yet.</td></tr>
              ) : (
                events.map((e) => (
                  <tr key={e.event_id} className="clickable" onClick={() => selectEvent(e.event_id)}>
                    <td style={{ fontFamily: 'monospace', fontWeight: 600, color: 'var(--accent)' }}>{e.event_id}</td>
                    <td>{e.disruption_type || '-'}</td>
                    <td><span className={`badge ${e.action === 'REBOOKED' ? 'badge-success' : 'badge-warning'}`}>{e.action || 'DONE'}</span></td>
                    <td>{e.policy_verdict || '-'}</td>
                    <td>₹{e.fare_delta_inr ?? 0}</td>
                    <td>{e.latency_ms ? `${e.latency_ms} ms` : '-'}</td>
                    <td style={{ color: 'var(--text-muted)', fontSize: 12 }}>{new Date(e.timestamp).toLocaleTimeString()}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
