/**
 * Events and Decision Traces Page.
 * Airline-style departure board for disruption events,
 * and a boarding-pass detail card with a vertical stage-execution timeline.
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
    fetchEvents(50)
      .then(setEvents)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const targetId = urlEventId || selectedEventId;
    if (!targetId) {
      setTraceDetail(null);
      return;
    }
    setDetailLoading(true);
    fetchEventDetail(targetId)
      .then(setTraceDetail)
      .catch(console.error)
      .finally(() => setDetailLoading(false));
  }, [urlEventId, selectedEventId]);

  const selectEvent = (id) => {
    setSelectedEventId(id);
    navigate(`/events/${id}`);
  };

  const clearSelection = () => {
    setSelectedEventId(null);
    setTraceDetail(null);
    navigate('/events');
  };

  const toggleStageJson = (id) => {
    setExpandedStages((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  // Helper to resolve status chip styling
  const getStatusChipClass = (statusStr) => {
    const s = (statusStr || '').toUpperCase();
    if (s.includes('REBOOK') || s.includes('APPROV') || s.includes('CONFIRM')) return 'chip-green';
    if (s.includes('DELAY') || s.includes('ESCALAT')) return 'chip-amber';
    if (s.includes('CANCEL') || s.includes('REJECT') || s.includes('ERROR') || s.includes('FAIL')) return 'chip-red';
    return 'chip-blue';
  };

  if (loading) {
    return (
      <div className="state-card loading-state">
        <span className="spinner" aria-hidden="true">⏱</span>
        <p>Loading flight departure board...</p>
      </div>
    );
  }

  // Airport code to city name lookup
  const AIRPORT_CITIES = {
    DEL: 'NEW DELHI',
    BOM: 'MUMBAI',
    BLR: 'BENGALURU',
    GOI: 'GOA',
    HYD: 'HYDERABAD',
    MAA: 'CHENNAI',
    CCU: 'KOLKATA',
  };

  // Extract flight info for boarding pass if available
  const newFlight = traceDetail?.result?.new_flight;
  // If no new rebooked flight (e.g. NO_ACTION or ESCALATED), extract route from stage snapshots
  const stageRoute = traceDetail?.stages?.find(
    (s) => s.input_snapshot?.origin || s.output_snapshot?.origin
  );
  const stageFlight = traceDetail?.stages?.find(
    (s) => s.input_snapshot?.flight_number || s.output_snapshot?.flight_number
  );
  const origin = newFlight?.origin || stageRoute?.input_snapshot?.origin || stageRoute?.output_snapshot?.origin || 'DEL';
  const destination = newFlight?.destination || stageRoute?.input_snapshot?.destination || stageRoute?.output_snapshot?.destination || 'BOM';
  const flightNum = newFlight?.flight_number
    || (newFlight?.airline_code ? `${newFlight.airline_code}-${newFlight.flight_number}` : null)
    || stageFlight?.input_snapshot?.flight_number
    || stageFlight?.output_snapshot?.flight_number
    || '6E-204';
  const originCity = AIRPORT_CITIES[origin] ? `${AIRPORT_CITIES[origin]} · DEPARTURE` : 'DEPARTURE';
  const destCity = AIRPORT_CITIES[destination] ? `${AIRPORT_CITIES[destination]} · ARRIVAL` : 'ARRIVAL';

  return (
    <div className="page-section">
      <div className="page-header header-with-action">
        <div>
          <div className="header-meta">DISRUPTION REGISTRY · AUDIT TRAIL</div>
          <h1 className="page-title">
            {selectedEventId ? `Flight Disruption Record #${selectedEventId}` : 'Flight Disruption Board'}
          </h1>
          <p className="page-subtitle">
            {selectedEventId
              ? 'Detailed boarding pass, stage-by-stage decision timeline, and raw trace snapshots'
              : 'Departure-style operations registry of all autonomous rebooking events'}
          </p>
        </div>

        {selectedEventId && (
          <button type="button" className="btn-secondary back-btn" onClick={clearSelection}>
            ← Back to Board
          </button>
        )}
      </div>

      {selectedEventId && traceDetail ? (
        <div className="event-detail-container">
          {/* 1. Boarding Pass Header Card */}
          <div className="airline-card boarding-pass-card">
            <div className="boarding-pass-header">
              <div className="pass-brand">
                <span className="pass-plane-icon" aria-hidden="true">✈</span>
                <span className="pass-title">
                  {traceDetail.result?.action === 'NO_ACTION' ? 'FLIGHT DISRUPTION STATUS (NO REBOOKING REQUIRED)' : 'REBOOKING BOARDING PASS'}
                </span>
              </div>
              <div className="pass-status-group">
                <span className={`status-chip ${getStatusChipClass(traceDetail.result?.action)}`}>
                  ● {traceDetail.result?.action || 'COMPLETED'}
                </span>
                <span className={`status-chip ${getStatusChipClass(traceDetail.result?.policy_verdict)}`}>
                  {traceDetail.result?.policy_verdict || 'VERDICT'}
                </span>
              </div>
            </div>

            {/* Large Airport Code Route Banner */}
            <div className="boarding-pass-route">
              <div className="route-airport">
                <span className="airport-code">{origin}</span>
                <span className="airport-label">{originCity}</span>
                {newFlight?.departure_time && (
                  <span className="flight-time tabular">{new Date(newFlight.departure_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                )}
              </div>

              <div className="route-flight-indicator">
                <span className="route-flight-number">{flightNum}</span>
                <div className="flight-line">
                  <span className="line-bar" />
                  <span className="line-plane" aria-hidden="true">✈</span>
                  <span className="line-bar" />
                </div>
                <span className="flight-cabin">{newFlight?.cabin_class || 'ECONOMY'}</span>
              </div>

              <div className="route-airport text-right">
                <span className="airport-code">{destination}</span>
                <span className="airport-label">{destCity}</span>
                {newFlight?.arrival_time && (
                  <span className="flight-time tabular">{new Date(newFlight.arrival_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                )}
              </div>
            </div>

            <div className="pass-perforation" aria-hidden="true" />

            {/* Boarding Pass Meta Stubs */}
            <div className="boarding-pass-grid">
              <div className="pass-stub">
                <div className="stub-label">BOOKING REFERENCE (PNR)</div>
                <div className="stub-value monospace tabular">{newFlight?.new_pnr || traceDetail.event_id}</div>
              </div>

              <div className="pass-stub">
                <div className="stub-label">E-TICKET NUMBER</div>
                <div className="stub-value monospace tabular">{newFlight?.new_eticket_number || 'E-TKT PENDING'}</div>
              </div>

              <div className="pass-stub">
                <div className="stub-label">FARE ADJUSTMENT (INR)</div>
                <div className="stub-value tabular highlight-accent">
                  {traceDetail.result?.fare_delta_inr != null
                    ? `${traceDetail.result.fare_delta_inr >= 0 ? '+' : ''}₹${traceDetail.result.fare_delta_inr}`
                    : '₹0'}
                </div>
              </div>

              <div className="pass-stub">
                <div className="stub-label">EXECUTION TIME / TOKENS</div>
                <div className="stub-value tabular">
                  {traceDetail.result?.latency_ms ? `${Math.round(traceDetail.result.latency_ms)} ms` : '-'} ·{' '}
                  <span className="stub-dim">{(traceDetail.result?.tokens_in || 0) + (traceDetail.result?.tokens_out || 0)} toks</span>
                </div>
              </div>
            </div>

            {traceDetail.result?.explanation && (
              <div className="traveler-advisory-box">
                <div className="advisory-title">
                  <span aria-hidden="true">ℹ</span> TRAVELER REBOOKING ADVISORY
                </div>
                <p className="advisory-text">{traceDetail.result.explanation}</p>
              </div>
            )}
          </div>

          {/* 2. Vertical Stage Execution Timeline */}
          <div className="airline-card timeline-card">
            <div className="card-header-bar">
              <h2 className="section-title">Decision Pipeline Audit Trail</h2>
              <span className="card-tag">{traceDetail.stages?.length || 0} STAGES EXECUTED</span>
            </div>

            {detailLoading ? (
              <p className="loading-text">Loading pipeline stages...</p>
            ) : (
              <div className="vertical-timeline">
                {traceDetail.stages.map((st, idx) => (
                  <div key={st.id || idx} className="timeline-step">
                    <div className="step-track">
                      <div className="step-dot" aria-hidden="true" />
                      {idx < traceDetail.stages.length - 1 && <div className="step-connector" aria-hidden="true" />}
                    </div>

                    <div className="step-content">
                      <div
                        className="step-header"
                        role="button"
                        tabIndex={0}
                        onClick={() => toggleStageJson(st.id || idx)}
                        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') toggleStageJson(st.id || idx); }}
                        aria-expanded={Boolean(expandedStages[st.id || idx])}
                      >
                        <div className="step-title-group">
                          <span className="step-index">#{idx + 1}</span>
                          <span className="step-name">{st.stage}</span>
                        </div>

                        <div className="step-meta-group">
                          <span className="step-time tabular">{new Date(st.timestamp).toLocaleTimeString()}</span>
                          {st.output_snapshot?.latency_ms && (
                            <span className="step-latency-badge tabular">{Math.round(st.output_snapshot.latency_ms)} ms</span>
                          )}
                          <span className="step-toggle-btn">
                            {expandedStages[st.id || idx] ? 'Hide JSON ▲' : 'View JSON ▼'}
                          </span>
                        </div>
                      </div>

                      {expandedStages[st.id || idx] && (
                        <div className="json-container">
                          <div className="json-header">
                            <span>Stage Snapshot JSON</span>
                          </div>
                          <pre className="json-view">{JSON.stringify({ input: st.input_snapshot, output: st.output_snapshot }, null, 2)}</pre>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : (
        /* 3. Flight Departure Board Table */
        <div className="airline-card departure-board-card">
          <div className="card-header-bar">
            <h2 className="section-title">Recent Disruption Departures</h2>
            <span className="card-tag tabular">{events.length} LOGGED TRACES</span>
          </div>

          <div className="table-responsive-wrapper">
            <table className="departure-table">
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  <th scope="col">Event ID</th>
                  <th scope="col">Route / Leg</th>
                  <th scope="col">Action Taken</th>
                  <th scope="col">Policy Verdict</th>
                  <th scope="col">Fare Delta</th>
                  <th scope="col">Latency</th>
                </tr>
              </thead>
              <tbody>
                {events.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="empty-table-cell">
                      No disruption records logged yet. Trigger a simulated event from the Simulate tab.
                    </td>
                  </tr>
                ) : (
                  events.map((e) => {
                    const flightRes = e.result?.new_flight;
                    const routeStr = flightRes?.origin && flightRes?.destination
                      ? `${flightRes.origin} → ${flightRes.destination}`
                      : 'BOM → GOI';
                    const flightCode = flightRes?.flight_number || '6E-204';

                    return (
                      <tr key={e.event_id} className="board-row clickable-row" onClick={() => selectEvent(e.event_id)}>
                        <td data-label="Time" className="tabular time-cell">
                          {new Date(e.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                        </td>
                        <td data-label="Event ID" className="monospace event-id-cell">
                          {e.event_id}
                        </td>
                        <td data-label="Route / Leg">
                          <div className="route-cell-content">
                            <span className="route-bold">{routeStr}</span>
                            <span className="route-flight-sub">{flightCode}</span>
                          </div>
                        </td>
                        <td data-label="Action Taken">
                          <span className={`status-chip ${getStatusChipClass(e.action)}`}>
                            {e.action || 'COMPLETED'}
                          </span>
                        </td>
                        <td data-label="Policy Verdict">
                          <span className={`status-chip ${getStatusChipClass(e.policy_verdict)}`}>
                            {e.policy_verdict || 'N/A'}
                          </span>
                        </td>
                        <td data-label="Fare Delta" className="tabular fare-cell">
                          {e.fare_delta_inr != null ? `₹${e.fare_delta_inr}` : '₹0'}
                        </td>
                        <td data-label="Latency" className="tabular latency-cell">
                          {e.latency_ms ? `${Math.round(e.latency_ms)} ms` : '-'}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
