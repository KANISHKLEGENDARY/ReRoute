/**
 * App Layout and Navigation component.
 * Features:
 * - Persistent navy top airline header with brand, tagline, and live status.
 * - Responsive navigation: left sidebar on desktop, collapsible drawer with hamburger toggle on mobile.
 * - Centered max-width shell for all 5 dashboard views.
 */
import React, { useState } from 'react';
import { Routes, Route, NavLink, Navigate } from 'react-router-dom';
import Overview from './pages/Overview.jsx';
import Live from './pages/Live.jsx';
import Events from './pages/Events.jsx';
import Simulate from './pages/Simulate.jsx';
import Evaluation from './pages/Evaluation.jsx';

export default function App() {
  const [menuOpen, setMenuOpen] = useState(false);

  const closeMenu = () => setMenuOpen(false);

  return (
    <div className="app-root">
      {/* 1. Global Airline Navy Header */}
      <header className="top-header">
        <div className="header-inner">
          <div className="header-brand-group">
            <NavLink to="/" className="brand-logo" onClick={closeMenu}>
              <span className="brand-plane" aria-hidden="true">✈</span>
              <span className="brand-name">ReRoute</span>
              <span className="brand-badge">CONCIERGE</span>
            </NavLink>
            <span className="header-tagline">Autonomous Travel-Disruption Concierge</span>
          </div>

          <div className="header-actions">
            <div className="live-status-pill">
              <span className="live-pulse-dot" aria-hidden="true" />
              <span>SYSTEM LIVE</span>
            </div>

            <button
              type="button"
              className="mobile-menu-btn"
              aria-label={menuOpen ? 'Close navigation menu' : 'Open navigation menu'}
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen(!menuOpen)}
            >
              <span aria-hidden="true">{menuOpen ? '✕' : '☰'}</span>
            </button>
          </div>
        </div>
      </header>

      {/* 2. Layout Body with Sidebar + Content */}
      <div className="layout-body">
        {/* Backdrop for mobile drawer */}
        {menuOpen && <div className="sidebar-backdrop" onClick={closeMenu} aria-hidden="true" />}

        <aside className={`sidebar ${menuOpen ? 'open' : ''}`} aria-label="Main Navigation">
          <div className="nav-group-title">Operations Menu</div>
          <nav className="nav-menu">
            <NavLink to="/" end className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} onClick={closeMenu}>
              <span className="nav-icon" aria-hidden="true">📊</span>
              <span>Overview</span>
            </NavLink>
            <NavLink to="/live" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} onClick={closeMenu}>
              <span className="nav-icon" aria-hidden="true">⚡</span>
              <span>Live Feed</span>
            </NavLink>
            <NavLink to="/events" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} onClick={closeMenu}>
              <span className="nav-icon" aria-hidden="true">🛫</span>
              <span>Events & Traces</span>
            </NavLink>
            <NavLink to="/simulate" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} onClick={closeMenu}>
              <span className="nav-icon" aria-hidden="true">🎯</span>
              <span>Simulate</span>
            </NavLink>
            <NavLink to="/evaluation" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} onClick={closeMenu}>
              <span className="nav-icon" aria-hidden="true">📋</span>
              <span>Evaluation</span>
            </NavLink>
          </nav>

          <div className="sidebar-footer">
            <div className="sidebar-footer-label">Engine Protocol</div>
            <div className="sidebar-footer-sub">LangGraph · Gemini Lite · MCP</div>
          </div>
        </aside>

        <main className="content-area" id="main-content">
          <div className="page-shell">
            <Routes>
              <Route path="/" element={<Overview />} />
              <Route path="/live" element={<Live />} />
              <Route path="/events" element={<Events />} />
              <Route path="/events/:eventId" element={<Events />} />
              <Route path="/simulate" element={<Simulate />} />
              <Route path="/evaluation" element={<Evaluation />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </div>
        </main>
      </div>
    </div>
  );
}
