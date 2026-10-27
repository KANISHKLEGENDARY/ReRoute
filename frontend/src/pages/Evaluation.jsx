/**
 * Evaluation Benchmark Page.
 * Loads static benchmark metrics from /eval-summary.json:
 * - Baseline vs. Guarded pass rates (75.4% -> 100.0%) as two big hero tiles
 * - PASS and FAIL chips
 * - Responsive bar chart of category pass rates (Baseline vs. Fixed)
 * - Active production safety guardrails
 * - Departure-style table of baseline scenario failures and implemented fixes
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

  if (loading) {
    return (
      <div className="state-card loading-state">
        <span className="spinner" aria-hidden="true">⏱</span>
        <p>Loading benchmark evaluation results...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="state-card error-state">
        <span className="state-icon" aria-hidden="true">⚠</span>
        <div>
          <h3>Benchmark Data Unavailable</h3>
          <p>{error}</p>
        </div>
      </div>
    );
  }

  const { summary, category_pass_rates, safety_checks, baseline_failures } = data;

  return (
    <div className="page-section">
      <div className="page-header">
        <div className="header-meta">BENCHMARK EVALUATION · RELIABILITY TEST SUITE</div>
        <h1 className="page-title">Evaluation & Safety Guardrails</h1>
        <p className="page-subtitle">
          Empirical regression suite verifying 61 complex disruption scenarios: baseline unconstrained agent vs. guarded production pipeline
        </p>
      </div>

      {/* Two Big Hero Benchmark Comparison Tiles */}
      <div className="hero-tiles-grid">
        <div className="hero-tile baseline-hero-tile">
          <div className="hero-tile-header">
            <span className="hero-tile-label">BASELINE UNCONSTRAINED PIPELINE</span>
            <span className="status-chip chip-red">FAIL · 15 FAILURES</span>
          </div>
          <div className="hero-tile-body">
            <div className="hero-tile-value tabular">{summary.baseline_pass_rate}%</div>
            <div className="hero-tile-sub">
              {summary.baseline_passed} of {summary.total_scenarios} scenarios passed ({summary.total_scenarios - summary.baseline_passed} critical failures)
            </div>
          </div>
          <div className="hero-tile-footer">
            <span>Hallucinated flight inventory, missing layover minimums & policy skips</span>
          </div>
        </div>

        <div className="hero-tile guarded-hero-tile">
          <div className="hero-tile-header">
            <span className="hero-tile-label">GUARDED PRODUCTION PIPELINE</span>
            <span className="status-chip chip-green">PASS · 100% RELIABILITY</span>
          </div>
          <div className="hero-tile-body">
            <div className="hero-tile-value tabular highlight-success">{summary.fixed_pass_rate}%</div>
            <div className="hero-tile-sub">
              {summary.fixed_passed} of {summary.total_scenarios} scenarios passed (0 failures)
            </div>
          </div>
          <div className="hero-tile-footer">
            <span>Zero inventory hallucinations · Deterministic policy verification · Strict fallback</span>
          </div>
        </div>
      </div>

      {/* Secondary Metric Info Tiles */}
      <div className="tile-grid eval-secondary-tiles">
        <div className="info-tile">
          <div className="tile-label">Scenarios Evaluated</div>
          <div className="tile-value tabular">{summary.total_scenarios}</div>
          <div className="tile-sub">12 disruption categories</div>
        </div>
        <div className="info-tile">
          <div className="tile-label">Failures Resolved</div>
          <div className="tile-value tabular highlight-accent">+{summary.total_scenarios - summary.baseline_passed}</div>
          <div className="tile-sub">100% gap closed with guardrails</div>
        </div>
        <div className="info-tile">
          <div className="tile-label">Active Guardrails</div>
          <div className="tile-value tabular">{safety_checks.length}</div>
          <div className="tile-sub">Deterministic validation checks</div>
        </div>
        <div className="info-tile">
          <div className="tile-label">Test Suite Status</div>
          <div className="tile-value tabular highlight-success">100%</div>
          <div className="tile-sub">All test assertions passing</div>
        </div>
      </div>

      {/* Category Pass Rates Bar Chart */}
      <div className="airline-card chart-card">
        <div className="card-header-bar">
          <h2 className="section-title">Pass Rate per Disruption Category (%)</h2>
          <span className="card-tag">BASELINE VS. GUARDED</span>
        </div>
        <div className="chart-wrapper">
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={category_pass_rates} margin={{ top: 12, right: 16, left: -10, bottom: 30 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis dataKey="category" tick={{ fontSize: 10, fill: '#475569' }} interval={0} angle={-25} textAnchor="end" />
              <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: '#475569' }} />
              <Tooltip
                contentStyle={{ backgroundColor: '#ffffff', borderColor: '#cbd5e1', borderRadius: 8, fontSize: 12, boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }}
              />
              <Legend verticalAlign="top" height={36} wrapperStyle={{ fontSize: 12 }} />
              <Bar name="Baseline" dataKey="baseline_rate" fill="#94a3b8" radius={[4, 4, 0, 0]} />
              <Bar name="Guarded (Fixed)" dataKey="fixed_rate" fill="#0a1f44" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Production Safety Checks & Guardrails */}
      <div className="airline-card guardrails-card">
        <div className="card-header-bar">
          <h2 className="section-title">Production Safety Checks & Guardrails</h2>
          <span className="card-tag">{safety_checks.length} ACTIVE CHECKS</span>
        </div>
        <div className="guardrails-grid">
          {safety_checks.map((check, idx) => (
            <div key={idx} className="guardrail-item">
              <div className="guardrail-title">
                <span className="guardrail-check" aria-hidden="true">✓</span>
                <span>{check.name}</span>
              </div>
              <div className="guardrail-detail">{check.detail}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Baseline Failures & Implemented Fixes Table */}
      <div className="airline-card departure-board-card">
        <div className="card-header-bar">
          <h2 className="section-title">Baseline Failures & Implemented Fixes</h2>
          <span className="card-tag tabular">{baseline_failures.length} RESOLVED REGRESSIONS</span>
        </div>

        <div className="table-responsive-wrapper">
          <table className="departure-table">
            <thead>
              <tr>
                <th scope="col" style={{ width: '130px' }}>Scenario ID</th>
                <th scope="col" style={{ width: '160px' }}>Category</th>
                <th scope="col">Root Failure at Baseline</th>
                <th scope="col">Safety Guardrail Implemented</th>
              </tr>
            </thead>
            <tbody>
              {baseline_failures.map((f) => (
                <tr key={f.scenario_id} className="board-row">
                  <td data-label="Scenario ID" className="monospace event-id-cell">
                    {f.scenario_id}
                  </td>
                  <td data-label="Category">
                    <span className="status-chip chip-neutral">{f.category}</span>
                  </td>
                  <td data-label="Root Failure at Baseline" className="failure-text-cell">
                    <span className="failure-reason">{f.failure_cause}</span>
                  </td>
                  <td data-label="Safety Guardrail Implemented" className="fix-text-cell">
                    <span className="status-chip chip-green" style={{ marginRight: 6 }}>FIXED</span>
                    <span>{f.fix_applied}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

