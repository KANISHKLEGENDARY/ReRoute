/**
 * Evaluation Benchmark Page.
 * Loads static benchmark metrics from /eval-summary.json:
 * - Baseline vs. Fixed pass rates (75.4% -> 100.0%)
 * - Bar chart of category pass rates (Baseline vs. Fixed)
 * - Active production safety guardrails
 * - Detailed table of baseline scenario failures and implemented fixes
 */
import React, { useState, useEffect } from 'react';
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip,
  Legend, CartesianGrid
} from 'recharts';
import { fetchEvalSummary } from '../api.js';

export default function Evaluation() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchEvalSummary()
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="page-header"><p>Loading evaluation results...</p></div>;
  if (error) return <div className="page-header"><p style={{ color: 'var(--danger)' }}>Error: {error}</p></div>;

  const { summary, category_pass_rates, safety_checks, baseline_failures } = data;

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Evaluation Benchmark</h1>
        <p className="page-subtitle">Regression test suite comparing baseline pipeline against guarded agentic pipeline</p>
      </div>

      <div className="card-grid">
        <div className="metric-card">
          <div className="metric-label">Baseline Pass Rate</div>
          <div className="metric-value" style={{ color: 'var(--danger)' }}>{summary.baseline_pass_rate}%</div>
          <div className="metric-sub">{summary.baseline_passed} of {summary.total_scenarios} passed (15 failed)</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Guarded Pass Rate</div>
          <div className="metric-value" style={{ color: 'var(--success)' }}>{summary.fixed_pass_rate}%</div>
          <div className="metric-sub">{summary.fixed_passed} of {summary.total_scenarios} passed (0 failures)</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Scenarios Evaluated</div>
          <div className="metric-value">{summary.total_scenarios}</div>
          <div className="metric-sub">Across 12 disruption categories</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Resolved Failures</div>
          <div className="metric-value">+15</div>
          <div className="metric-sub">100% baseline gap closure</div>
        </div>
      </div>

      <div className="chart-card" style={{ marginBottom: 24 }}>
        <div className="chart-title">Pass Rate per Disruption Category (%)</div>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={category_pass_rates} margin={{ top: 10, right: 20, left: -10, bottom: 25 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis dataKey="category" tick={{ fontSize: 10 }} interval={0} angle={-20} textAnchor="end" />
            <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
            <Tooltip />
            <Legend verticalAlign="top" height={36} wrapperStyle={{ fontSize: 12 }} />
            <Bar name="Baseline" dataKey="baseline_rate" fill="#94a3b8" radius={[3, 3, 0, 0]} />
            <Bar name="Guarded (Fixed)" dataKey="fixed_rate" fill="var(--accent)" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="chart-card" style={{ marginBottom: 24, minHeight: 'auto' }}>
        <div className="chart-title">Production Safety Checks & Guardrails</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
          {safety_checks.map((check, idx) => (
            <div key={idx} style={{ background: 'var(--bg-page)', border: '1px solid var(--border)', borderRadius: 6, padding: 12 }}>
              <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--accent)', marginBottom: 4 }}>
                ✓ {check.name}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{check.detail}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="table-container">
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', fontWeight: 600, fontSize: 14 }}>
          Baseline Failures & Applied Fixes ({baseline_failures.length} Scenarios)
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: 140 }}>Scenario ID</th>
              <th style={{ width: 160 }}>Category</th>
              <th>Root Failure at Baseline</th>
              <th>Fix Implemented</th>
            </tr>
          </thead>
          <tbody>
            {baseline_failures.map((f) => (
              <tr key={f.scenario_id}>
                <td style={{ fontFamily: 'monospace', fontWeight: 600 }}>{f.scenario_id}</td>
                <td><span className="badge badge-neutral">{f.category}</span></td>
                <td style={{ color: 'var(--danger)', fontSize: 12 }}>{f.failure_cause}</td>
                <td style={{ color: 'var(--success)', fontSize: 12, fontWeight: 500 }}>{f.fix_applied}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
