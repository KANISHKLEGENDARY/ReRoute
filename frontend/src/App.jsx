/**
 * App Layout and Routing component.
 * Provides a clean left sidebar navigation and routes to individual functional pages.
 */
import React from 'react';
import { Routes, Route, NavLink, Navigate } from 'react-router-dom';
import Overview from './pages/Overview.jsx';
import Live from './pages/Live.jsx';
import Events from './pages/Events.jsx';
import Simulate from './pages/Simulate.jsx';
import Evaluation from './pages/Evaluation.jsx';

export default function App() {
  return (
    <div className="app-container">
      <aside className="sidebar">
        <div className="brand">
          <span>ReRoute</span>
          <span className="brand-badge">Ops</span>
        </div>
        <nav className="nav-menu">
          <NavLink to="/" end className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <span>📊</span>
            <span>Overview</span>
          </NavLink>
          <NavLink to="/live" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <span>⚡</span>
            <span>Live Feed</span>
          </NavLink>
          <NavLink to="/events" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <span>🔍</span>
            <span>Events & Traces</span>
          </NavLink>
          <NavLink to="/simulate" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <span>✈️</span>
            <span>Simulate</span>
          </NavLink>
          <NavLink to="/evaluation" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <span>📋</span>
            <span>Evaluation</span>
          </NavLink>
        </nav>
      </aside>

      <main className="content-area">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/live" element={<Live />} />
          <Route path="/events" element={<Events />} />
          <Route path="/events/:eventId" element={<Events />} />
          <Route path="/simulate" element={<Simulate />} />
          <Route path="/evaluation" element={<Evaluation />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
