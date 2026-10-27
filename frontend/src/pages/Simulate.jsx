/**
 * Simulate Page.
 * Allows operators to trigger synthetic disruption events on flight legs:
 * selects a flight leg, disruption type, optional airline notice & traveler preferences,
 * supplies an optional X-Demo-Key, and provides a direct link to the resulting event trace.
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
    <div>
      <div className="page-header">
        <h1 className="page-title">Simulate Flight Disruption</h1>
        <p className="page-subtitle">Dispatch test events through the ingestion pipeline to evaluate autonomous decisions</p>
      </div>

      <div className="form-card">
        {result && (
          <div style={{ background: 'var(--success-bg)', border: '1px solid var(--success)', borderRadius: 6, padding: 14, marginBottom: 20 }}>
            <p style={{ color: 'var(--success)', fontWeight: 600, marginBottom: 6 }}>
              ✓ Disruption event triggered successfully: <strong>{result.event_id}</strong>
            </p>
            <Link to={`/events/${result.event_id}`} style={{ color: 'var(--accent)', fontWeight: 600, textDecoration: 'underline' }}>
              View Event Trace & Final Result →
            </Link>
          </div>
        )}

        {error && (
          <div style={{ background: 'var(--danger-bg)', border: '1px solid var(--danger)', borderRadius: 6, padding: 12, marginBottom: 20, color: 'var(--danger)' }}>
            Error: {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">Flight Leg</label>
            <select className="form-select" value={flightLegId} onChange={(e) => setFlightLegId(e.target.value)} required>
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
            <label className="form-label">Disruption Event Type</label>
            <select className="form-select" value={eventType} onChange={(e) => setEventType(e.target.value)}>
              <option value="CANCELLED">CANCELLED (Flight fully cancelled)</option>
              <option value="DELAYED">DELAYED (Significant departure/arrival delay)</option>
              <option value="MISSED_CONNECTION">MISSED_CONNECTION (Inbound delay caused missed leg)</option>
            </select>
          </div>

          {eventType === 'DELAYED' && (
            <div className="form-group">
              <label className="form-label">Delay (minutes)</label>
              <input type="number" min="1" className="form-input" value={delayMinutes} onChange={(e) => setDelayMinutes(e.target.value)} />
            </div>
          )}

          <div className="form-group">
            <label className="form-label">Airline Notice Text (Optional)</label>
            <textarea className="form-textarea" rows={2} placeholder="e.g. Flight 6E-204 cancelled due to technical snag at DEL" value={noticeText} onChange={(e) => setNoticeText(e.target.value)} />
          </div>

          <div className="form-group">
            <label className="form-label">Traveler Preferences (Optional)</label>
            <input type="text" className="form-input" placeholder="e.g. Prefers morning departures, non-stop flights" value={preferences} onChange={(e) => setPreferences(e.target.value)} />
          </div>

          <div className="form-group">
            <label className="form-label">Demo API Key (Header: X-Demo-Key)</label>
            <input type="text" className="form-input" placeholder="Required if backend DEMO_API_KEY is configured" value={demoKey} onChange={(e) => setDemoKey(e.target.value)} />
          </div>

          <button type="submit" className="form-btn" disabled={loading || !flightLegId}>
            {loading ? 'Dispatching Simulation...' : 'Send Simulated Event'}
          </button>
        </form>
      </div>
    </div>
  );
}
