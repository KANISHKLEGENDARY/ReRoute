/**
 * Centralized API client module for ReRoute Dashboard.
 * All HTTP requests and WebSocket URL resolution flow through here.
 * Base URL is driven by VITE_API_URL (defaults to http://localhost:8000).
 */

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export async function fetchMetrics() {
  const res = await fetch(`${API_BASE}/api/v1/metrics`);
  if (!res.ok) throw new Error(`Failed to load metrics: ${res.statusText}`);
  return res.json();
}

export async function fetchEvents(limit = 50) {
  const res = await fetch(`${API_BASE}/api/v1/events?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed to load events: ${res.statusText}`);
  return res.json();
}

export async function fetchEventDetail(eventId) {
  const res = await fetch(`${API_BASE}/api/v1/events/${eventId}`);
  if (!res.ok) throw new Error(`Failed to load event ${eventId}: ${res.statusText}`);
  return res.json();
}

export async function fetchFlightLegs() {
  const res = await fetch(`${API_BASE}/api/v1/legs`);
  if (!res.ok) throw new Error(`Failed to load flight legs: ${res.statusText}`);
  return res.json();
}

export async function simulateEvent(payload, demoKey = '') {
  const headers = { 'Content-Type': 'application/json' };
  if (demoKey && demoKey.trim()) {
    headers['X-Demo-Key'] = demoKey.trim();
  }
  const res = await fetch(`${API_BASE}/api/v1/events/simulate`, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || `Simulation request failed (${res.status})`);
  }
  return res.json();
}

export async function fetchEvalSummary() {
  const res = await fetch('/eval-summary.json');
  if (!res.ok) throw new Error(`Failed to load evaluation summary: ${res.statusText}`);
  return res.json();
}

export function getWebSocketUrl() {
  const wsProtocol = API_BASE.startsWith('https') ? 'wss' : 'ws';
  const cleanHost = API_BASE.replace(/^https?:\/\//, '');
  return `${wsProtocol}://${cleanHost}/api/v1/ws/activity`;
}
