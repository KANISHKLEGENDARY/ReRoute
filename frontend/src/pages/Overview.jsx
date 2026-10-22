/**
 * Overview Page.
 * Displays high-level system metrics (KPIs) and operational charts:
 * 1. Metric cards from GET /api/v1/metrics
 * 2. Bar chart showing breakdown of actions taken across recent events
 * 3. Line chart showing end-to-end latency per recent event
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

  if (loading) return <div className="page-header"><p>Loading system metrics...</p></div>;
  if (error) return <div className="page-header"><p style={{ color: 'var(--danger)' }}>Error: {error}</p></div>;

  // Prepare Actions Bar Chart data
  const actionCounts = {};
  events.forEach((e) => {
    const act = e.action || 'UNKNOWN';
    actionCounts[act] = (actionCounts[act] || 0) + 1;
  });
  const actionBarData = Object.entries(actionCounts).map(([action, count]) => ({ action, count }));

  // Prepare Latency Line Chart data (oldest to newest for smooth trend)
  const latencyLineData = [...events].reverse().map((e) => ({
    id: e.event_id ? e.event_id.slice(-6) : 'N/A',
    latency_ms: Number(e.latency_ms || 0),
  }));

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Operations Overview</h1>
        <p className="page-subtitle">Real-time pipeline performance and disruption resolution statistics</p>
      </div>

      <div className="card-grid">
        <div className="metric-card">
          <div className="metric-label">Events Handled</div>
          <div className="metric-value">{metrics.disruptions_handled}</div>
          <div className="metric-sub">Processed disruptions</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Auto-Resolution Rate</div>
          <div className="metric-value">{(metrics.auto_resolution_rate * 100).toFixed(1)}%</div>
          <div className="metric-sub">Resolved without human agent</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Escalation Rate</div>
          <div className="metric-value">{(metrics.escalation_rate * 100).toFixed(1)}%</div>
          <div className="metric-sub">Flagged for human review</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Avg / p95 Latency</div>
          <div className="metric-value">{metrics.avg_latency_ms} <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>/ {metrics.p95_latency_ms} ms</span></div>
          <div className="metric-sub">End-to-end processing time</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Avg Tokens / Event</div>
          <div className="metric-value">{metrics.avg_tokens_per_run}</div>
          <div className="metric-sub">Prompt + Completion</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Avg Cost (INR)</div>
          <div className="metric-value">₹{metrics.avg_cost_inr_per_run.toFixed(4)}</div>
          <div className="metric-sub">${metrics.avg_cost_usd_per_run.toFixed(6)} USD</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">LLM Fallback Rate</div>
          <div className="metric-value">{(metrics.llm_fallback_rate * 100).toFixed(1)}%</div>
          <div className="metric-sub">Rule-based fallback triggers</div>
        </div>
      </div>

      <div className="charts-row">
        <div className="chart-card">
          <div className="chart-title">Actions Taken (Recent Events)</div>
          {actionBarData.length === 0 ? (
            <p style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 40, textAlign: 'center' }}>No event data recorded yet</p>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={actionBarData} margin={{ top: 10, right: 20, left: 0, bottom: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="action" tick={{ fontSize: 11 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="count" fill="var(--accent)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="chart-card">
          <div className="chart-title">Latency per Recent Event (ms)</div>
          {latencyLineData.length === 0 ? (
            <p style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 40, textAlign: 'center' }}>No event data recorded yet</p>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={latencyLineData} margin={{ top: 10, right: 20, left: 0, bottom: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="id" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Line type="monotone" dataKey="latency_ms" stroke="var(--accent)" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </div>
  );
}
