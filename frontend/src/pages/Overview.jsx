/**
 * Overview Page.
 * Displays airline operations KPIs and charts:
 * 1. Metric tiles in an auto-fit responsive grid
 * 2. Actions breakdown bar chart (airline navy & warm accent)
 * 3. Latency trend line chart
 */
import React, { useState, useEffect } from 'react';
import {
  ResponsiveContainer, BarChart, Bar, LineChart, Line,
  XAxis, YAxis, Tooltip, CartesianGrid
} from 'recharts';
import { fetchMetrics, fetchEvents } from '../api.js';

export default function Overview() {
  const [metrics, setMetrics] = useState(null);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function loadData() {
      try {
        const [metricsData, eventsData] = await Promise.all([
          fetchMetrics(),
          fetchEvents(20).catch(() => []),
        ]);
        setMetrics(metricsData);
        setEvents(eventsData || []);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  if (loading) {
    return (
      <div className="state-card loading-state">
        <span className="spinner" aria-hidden="true">⏱</span>
        <p>Loading flight disruption metrics...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="state-card error-state">
        <span className="state-icon" aria-hidden="true">⚠</span>
        <div>
          <h3>System Metrics Unavailable</h3>
          <p>{error}</p>
        </div>
      </div>
    );
  }

  // Aggregate actions distribution
  const actionCounts = {};
  events.forEach((e) => {
    const act = e.action || 'UNKNOWN';
    actionCounts[act] = (actionCounts[act] || 0) + 1;
  });
  const actionBarData = Object.entries(actionCounts).map(([action, count]) => ({ action, count }));

  // Latency sequence for chart
  const latencyLineData = [...events].reverse().map((e) => ({
    id: e.event_id ? e.event_id.replace('SIM-', '#') : 'N/A',
    latency_ms: Number(e.latency_ms || 0),
  }));

  return (
    <div className="page-section">
      <div className="page-header">
        <div className="header-meta">OPERATIONS DISPATCH · REAL-TIME TELEMETRY</div>
        <h1 className="page-title">Operations Overview</h1>
        <p className="page-subtitle">Autonomous resolution statistics, latency benchmarks, and active agent guardrails</p>
      </div>

      {/* KPI Info Tiles Grid */}
      <div className="tile-grid">
        <div className="info-tile">
          <div className="tile-label">Disruptions Handled</div>
          <div className="tile-value tabular">{metrics.disruptions_handled}</div>
          <div className="tile-sub">Logged flight disruptions</div>
        </div>

        <div className="info-tile accent-border">
          <div className="tile-label">Auto-Resolution Rate</div>
          <div className="tile-value tabular highlight-success">{(metrics.auto_resolution_rate * 100).toFixed(1)}%</div>
          <div className="tile-sub">Resolved without human agent</div>
        </div>

        <div className="info-tile">
          <div className="tile-label">Escalation Rate</div>
          <div className="tile-value tabular">{(metrics.escalation_rate * 100).toFixed(1)}%</div>
          <div className="tile-sub">Flagged for human concierge</div>
        </div>

        <div className="info-tile">
          <div className="tile-label">Avg / p95 Latency</div>
          <div className="tile-value tabular">
            {metrics.avg_latency_ms} <span className="tile-unit">/ {metrics.p95_latency_ms} ms</span>
          </div>
          <div className="tile-sub">End-to-end pipeline time</div>
        </div>

        <div className="info-tile">
          <div className="tile-label">Avg Tokens / Run</div>
          <div className="tile-value tabular">{metrics.avg_tokens_per_run}</div>
          <div className="tile-sub">Gemini prompt + completion</div>
        </div>

        <div className="info-tile">
          <div className="tile-label">Avg Cost (INR)</div>
          <div className="tile-value tabular highlight-accent">₹{metrics.avg_cost_inr_per_run.toFixed(4)}</div>
          <div className="tile-sub">${metrics.avg_cost_usd_per_run.toFixed(6)} USD / event</div>
        </div>

        <div className="info-tile">
          <div className="tile-label">LLM Fallback Rate</div>
          <div className="tile-value tabular">{(metrics.llm_fallback_rate * 100).toFixed(1)}%</div>
          <div className="tile-sub">Deterministic circuit breakers</div>
        </div>
      </div>

      {/* Analytics Charts Grid */}
      <div className="charts-grid">
        <div className="airline-card chart-card">
          <div className="card-header-bar">
            <h2 className="section-title">Disruption Resolution Actions</h2>
            <span className="card-tag">RECENT EVENTS</span>
          </div>
          <div className="chart-wrapper">
            {actionBarData.length === 0 ? (
              <div className="empty-chart">No event data recorded yet.</div>
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={actionBarData} margin={{ top: 16, right: 16, left: -10, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                  <XAxis dataKey="action" tick={{ fontSize: 11, fill: '#475569' }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: '#475569' }} />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#ffffff', borderColor: '#cbd5e1', borderRadius: 8, fontSize: 13, boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }}
                  />
                  <Bar dataKey="count" fill="#0a1f44" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="airline-card chart-card">
          <div className="card-header-bar">
            <h2 className="section-title">Processing Latency per Event (ms)</h2>
            <span className="card-tag">SEQUENCE TREND</span>
          </div>
          <div className="chart-wrapper">
            {latencyLineData.length === 0 ? (
              <div className="empty-chart">No event data recorded yet.</div>
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={latencyLineData} margin={{ top: 16, right: 16, left: -10, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                  <XAxis dataKey="id" tick={{ fontSize: 11, fill: '#475569' }} />
                  <YAxis tick={{ fontSize: 11, fill: '#475569' }} />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#ffffff', borderColor: '#cbd5e1', borderRadius: 8, fontSize: 13, boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }}
                  />
                  <Line type="monotone" dataKey="latency_ms" stroke="#d9531e" strokeWidth={2.5} dot={{ r: 4, fill: '#d9531e' }} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
