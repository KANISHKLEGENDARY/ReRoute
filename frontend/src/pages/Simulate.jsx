/**
 * Simulate Page.
 * Allows operators to trigger synthetic disruption events on flight legs:
 * selects a flight leg, disruption type, optional airline notice & traveler preferences,
 * supplies an optional X-Demo-Key, and provides a direct link to the resulting event trace.
 * Styled as an airline flight disruption search card.
 */
import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { fetchFlightLegs, simulateEvent } from '../api.js';

export default function Simulate() {
  const [legs, setLegs] = useState([]);
  const [flightLegId, setFlightLegId] = useState('');
  const [eventType, setEventType] = useState('CANCELLED');
  const [delayMinutes, setDelayMinutes] = useState(120);
  const [noticeText, setNoticeText] = useState('');
  const [preferences, setPreferences] = useState('');
  const [demoKey, setDemoKey] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchFlightLegs()
      .then((data) => {
        setLegs(data);
        if (data.length > 0) setFlightLegId(data[0].id);
      })
      .catch((err) => setError(`Failed to load flight legs: ${err.message}`));
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const payload = {
        flight_leg_id: Number(flightLegId),
        event_type: eventType,
        delay_minutes: eventType === 'DELAYED' ? Number(delayMinutes) : 0,
        notice_text: noticeText.trim() || null,
        traveler_preferences: preferences.trim() || null,
      };
      const res = await simulateEvent(payload, demoKey);
      setResult(res);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-section">
      <div className="page-header">
        <div className="header-meta">SIMULATION ENGINE · DISRUPTION INJECTION</div>
        <h1 className="page-title">Simulate Flight Disruption</h1>
        <p className="page-subtitle">
          Dispatch test disruption events through the autonomous rebooking pipeline to evaluate real-time agent decisions
        </p>
      </div>

      <div className="airline-card flight-search-card">
        <div className="search-card-header">
          <div className="search-badge-icon" aria-hidden="true">🛫</div>
          <div>
            <h2 className="section-title">Flight Disruption Parameters</h2>
            <p className="search-card-desc">Select scheduled flight leg, specify disruption severity, and dispatch for autonomous concierging</p>
          </div>
        </div>

        {result && (
          <div className="alert-banner alert-success">
            <div className="alert-icon" aria-hidden="true">✓</div>
            <div className="alert-body">
              <div className="alert-title">Disruption Event Triggered Successfully</div>
              <p className="alert-text">
                Pipeline execution logged as <strong>{result.event_id}</strong>.
              </p>
              <Link to={`/events/${result.event_id}`} className="alert-link">
                View Event Boarding Pass & Full Stage Trace →
              </Link>
            </div>
          </div>
        )}

        {error && (
          <div className="alert-banner alert-error">
            <div className="alert-icon" aria-hidden="true">⚠</div>
            <div className="alert-body">
              <div className="alert-title">Simulation Request Failed</div>
              <p className="alert-text">{error}</p>
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit} className="flight-form">
          <div className="form-grid">
            <div className="form-group full-width">
              <label htmlFor="flight-leg-select" className="form-label">
                Scheduled Flight Leg <span className="required-star">*</span>
              </label>
              <select
                id="flight-leg-select"
                className="form-control form-select"
                value={flightLegId}
                onChange={(e) => setFlightLegId(e.target.value)}
                required
              >
                {legs.map((leg) => {
                  const flightLabel = leg.flight_number?.startsWith(leg.airline_code)
                    ? leg.flight_number
                    : `${leg.airline_code}-${leg.flight_number}`;
                  const origin = leg.origin || leg.departure_airport || 'ORIG';
                  const dest = leg.destination || leg.arrival_airport || 'DEST';
                  return (
                    <option key={leg.id} value={leg.id}>
                      {flightLabel}: {origin} → {dest} ({leg.status})
                    </option>
                  );
                })}
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="event-type-select" className="form-label">
                Disruption Event Type <span className="required-star">*</span>
              </label>
              <select
                id="event-type-select"
                className="form-control form-select"
                value={eventType}
                onChange={(e) => setEventType(e.target.value)}
              >
                <option value="CANCELLED">CANCELLED (Flight fully cancelled)</option>
                <option value="DELAYED">DELAYED (Significant departure/arrival delay)</option>
                <option value="MISSED_CONNECTION">MISSED_CONNECTION (Inbound delay caused missed leg)</option>
              </select>
            </div>

            {eventType === 'DELAYED' ? (
              <div className="form-group">
                <label htmlFor="delay-minutes-input" className="form-label">
                  Delay Duration (Minutes) <span className="required-star">*</span>
                </label>
                <input
                  id="delay-minutes-input"
                  type="number"
                  min="1"
                  className="form-control form-input"
                  value={delayMinutes}
                  onChange={(e) => setDelayMinutes(e.target.value)}
                  required
                />
              </div>
            ) : (
              <div className="form-group">
                <label htmlFor="demo-key-input" className="form-label">
                  Demo API Key (Header: X-Demo-Key)
                </label>
                <input
                  id="demo-key-input"
                  type="text"
                  className="form-control form-input"
                  placeholder="Optional demo key"
                  value={demoKey}
                  onChange={(e) => setDemoKey(e.target.value)}
                />
              </div>
            )}

            {eventType === 'DELAYED' && (
              <div className="form-group full-width">
                <label htmlFor="demo-key-input-alt" className="form-label">
                  Demo API Key (Header: X-Demo-Key)
                </label>
                <input
                  id="demo-key-input-alt"
                  type="text"
                  className="form-control form-input"
                  placeholder="Optional demo key"
                  value={demoKey}
                  onChange={(e) => setDemoKey(e.target.value)}
                />
              </div>
            )}

            <div className="form-group full-width">
              <label htmlFor="notice-text-input" className="form-label">
                Airline Operations Notice Text (Optional)
              </label>
              <textarea
                id="notice-text-input"
                className="form-control form-textarea"
                rows={2}
                placeholder="e.g. Flight 6E-204 cancelled due to technical snag at DEL"
                value={noticeText}
                onChange={(e) => setNoticeText(e.target.value)}
              />
            </div>

            <div className="form-group full-width">
              <label htmlFor="traveler-pref-input" className="form-label">
                Traveler Preferences (Optional)
              </label>
              <input
                id="traveler-pref-input"
                type="text"
                className="form-control form-input"
                placeholder="e.g. Prefers morning departures, non-stop flights"
                value={preferences}
                onChange={(e) => setPreferences(e.target.value)}
              />
            </div>
          </div>

          <div className="form-actions">
            <button
              type="submit"
              className="btn-accent form-submit-btn"
              disabled={loading || !flightLegId}
            >
              {loading ? (
                <>
                  <span className="spinner-inline" aria-hidden="true">⏱</span>
                  <span>Dispatching Disruption Pipeline...</span>
                </>
              ) : (
                <>
                  <span aria-hidden="true">✈</span>
                  <span>Dispatch Simulated Disruption</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

