// Breathe ESG Production Web Application
import React, { useState, useEffect } from 'react';
import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

function App() {
  const [activeTab, setActiveTab] = useState('review'); // 'review' or 'uploader'
  const [editorName, setEditorName] = useState('Venkatesh S H'); // Analyst Name for Audits
  
  // Data State
  const [metrics, setMetrics] = useState({
    total_rows: 0,
    total_emissions_tco2e: 0,
    pending_reviews: 0,
    suspicious_records: 0,
    scope_splits: { scope1: 0, scope2: 0, scope3: 0 }
  });
  const [dataSources, setDataSources] = useState([]);
  const [ingestionJobs, setIngestionJobs] = useState([]);
  const [activities, setActivities] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  
  // Table Filters
  const [filterCategory, setFilterCategory] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterSuspicious, setFilterSuspicious] = useState('');
  const [filterScope, setFilterScope] = useState('');

  // Selection & Modal States
  const [selectedRow, setSelectedRow] = useState(null);
  const [editingRow, setEditingRow] = useState(null);
  
  // Uploader Form States
  const [uploadSourceId, setUploadSourceId] = useState('');
  const [selectedFile, setSelectedFile] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState(null);

  // Load Initial Data
  useEffect(() => {
    fetchMetrics();
    fetchDataSources();
    fetchIngestionJobs();
    fetchActivities();
  }, []);

  // Fetch lists on filter changes
  useEffect(() => {
    fetchActivities();
  }, [filterCategory, filterStatus, filterSuspicious, filterScope]);

  // Fetch detailed drawer audits when a row is selected
  useEffect(() => {
    if (selectedRow) {
      fetchAuditLogs(selectedRow.id);
    } else {
      setAuditLogs([]);
    }
  }, [selectedRow]);

  const fetchMetrics = async () => {
    try {
      const res = await axios.get(`${API_BASE}/dashboard-metrics/`);
      setMetrics(res.data);
    } catch (err) {
      console.error("Error fetching metrics", err);
    }
  };

  const fetchDataSources = async () => {
    try {
      const res = await axios.get(`${API_BASE}/data-sources/`);
      setDataSources(res.data);
      if (res.data.length > 0) {
        setUploadSourceId(res.data[0].id.toString());
      }
    } catch (err) {
      console.error("Error fetching sources", err);
    }
  };

  const fetchIngestionJobs = async () => {
    try {
      const res = await axios.get(`${API_BASE}/ingestion-jobs/`);
      setIngestionJobs(res.data);
    } catch (err) {
      console.error("Error fetching jobs", err);
    }
  };

  const fetchActivities = async () => {
    try {
      let params = {};
      if (filterCategory) params.category = filterCategory;
      if (filterStatus) params.approval_status = filterStatus;
      if (filterSuspicious) params.is_suspicious = filterSuspicious;
      if (filterScope) params.scope = filterScope;

      const res = await axios.get(`${API_BASE}/activities/`, { params });
      setActivities(res.data);
    } catch (err) {
      console.error("Error fetching activities", err);
    }
  };

  const fetchAuditLogs = async (activityId) => {
    try {
      const res = await axios.get(`${API_BASE}/audit-logs/`, {
        params: { activity_id: activityId }
      });
      setAuditLogs(res.data);
    } catch (err) {
      console.error("Error fetching audits", err);
    }
  };

  // CSV Ingestion Handler
  const handleUpload = async (e) => {
    e.preventDefault();
    if (!uploadSourceId || !selectedFile) {
      alert("Please select a Data Source and choose a CSV file.");
      return;
    }

    setIsUploading(true);
    setUploadMessage(null);

    const formData = new FormData();
    formData.append('data_source_id', uploadSourceId);
    formData.append('file', selectedFile);

    try {
      const res = await axios.post(`${API_BASE}/upload-csv/`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      setUploadMessage({
        type: 'success',
        text: `Successfully ingested CSV! Row Parse Success: ${res.data.parsed_rows}, Failed: ${res.data.failed_rows}`
      });
      setSelectedFile(null);
      
      // Refresh UI state
      fetchMetrics();
      fetchIngestionJobs();
      fetchActivities();
    } catch (err) {
      console.error(err);
      setUploadMessage({
        type: 'danger',
        text: err.response?.data?.error || "Error uploading and parsing CSV file."
      });
    } finally {
      setIsUploading(false);
    }
  };

  // Inline Approve & Lock Handler
  const handleApprove = async (rowId) => {
    try {
      await axios.post(`${API_BASE}/activities/${rowId}/approve/`, {
        editor_name: editorName
      });
      
      // Refresh
      fetchMetrics();
      fetchActivities();
      if (selectedRow && selectedRow.id === rowId) {
        // refresh drawer
        const res = await axios.get(`${API_BASE}/activities/${rowId}/`);
        setSelectedRow(res.data);
      }
    } catch (err) {
      alert(err.response?.data?.error || "Error approving record.");
    }
  };

  // Bulk Approve Handler
  const handleBulkApprove = async () => {
    const pendingIds = activities
      .filter(act => act.approval_status === 'PENDING')
      .map(act => act.id);

    if (pendingIds.length === 0) {
      alert("No pending records to approve.");
      return;
    }

    if (!confirm(`Are you sure you want to bulk-approve all ${pendingIds.length} pending records?`)) {
      return;
    }

    try {
      const res = await axios.post(`${API_BASE}/activities/bulk_approve/`, {
        ids: pendingIds,
        editor_name: editorName
      });
      alert(res.data.message);
      
      // Refresh
      fetchMetrics();
      fetchActivities();
    } catch (err) {
      alert("Error executing bulk approval.");
    }
  };

  // Edit Submit Handler (recomputes emissions)
  const handleEditSubmit = async (e) => {
    e.preventDefault();
    try {
      const res = await axios.put(`${API_BASE}/activities/${editingRow.id}/`, {
        activity_date: editingRow.activity_date,
        normalized_value: editingRow.normalized_value,
        normalized_unit: editingRow.normalized_unit,
        cost: editingRow.cost,
        currency: editingRow.currency,
        description: editingRow.description,
        editor_name: editorName
      });

      // Refresh
      setEditingRow(null);
      fetchMetrics();
      fetchActivities();
      
      // Update drawer if opened
      if (selectedRow && selectedRow.id === res.data.id) {
        setSelectedRow(res.data);
      }
    } catch (err) {
      alert(err.response?.data?.error || "Error updating activity.");
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      
      {/* Header Panel */}
      <header className="app-header">
        <div className="logo-section">
          <div className="logo-icon">B</div>
          <div>
            <div className="logo-text">Breathe ESG</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Data Ingestion Ledger</div>
          </div>
          <span className="logo-tag">Prototype</span>
        </div>

        <div className="nav-tabs">
          <button 
            className={`nav-tab ${activeTab === 'review' ? 'active' : ''}`}
            onClick={() => setActiveTab('review')}
          >
            Analyst Review Grid
          </button>
          <button 
            className={`nav-tab ${activeTab === 'uploader' ? 'active' : ''}`}
            onClick={() => setActiveTab('uploader')}
          >
            Ingestion Hub
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>Analyst Name:</span>
          <input 
            type="text" 
            className="form-input" 
            style={{ width: '130px', padding: '0.35rem 0.5rem', fontSize: '0.85rem' }} 
            value={editorName} 
            onChange={(e) => setEditorName(e.target.value)} 
          />
        </div>
      </header>

      {/* Metrics Banner */}
      <section style={{ backgroundColor: 'white', borderBottom: '1px solid var(--border-color)', padding: '1.5rem 2rem' }}>
        <div className="metrics-bar" style={{ maxWidth: '1400px', margin: '0 auto' }}>
          
          <div className="metric-card">
            <span className="metric-label">Total CO₂e Emissions</span>
            <span className="metric-value" style={{ color: 'var(--primary)' }}>
              {metrics.total_emissions_tco2e.toFixed(3)} <span style={{ fontSize: '1rem', fontWeight: 500 }}>tCO₂e</span>
            </span>
            <div className="scope-split-list">
              <span className="scope-split-item">
                <span className="scope-indicator" style={{ backgroundColor: '#f97316' }}></span>
                S1: {metrics.scope_splits?.scope1?.toFixed(1) || 0} t
              </span>
              <span className="scope-split-item">
                <span className="scope-indicator" style={{ backgroundColor: '#3b82f6' }}></span>
                S2: {metrics.scope_splits?.scope2?.toFixed(1) || 0} t
              </span>
              <span className="scope-split-item">
                <span className="scope-indicator" style={{ backgroundColor: '#10b981' }}></span>
                S3: {metrics.scope_splits?.scope3?.toFixed(1) || 0} t
              </span>
            </div>
          </div>

          <div className="metric-card">
            <span className="metric-label">Ingested Records</span>
            <span className="metric-value">{metrics.total_rows}</span>
            <span className="metric-sub">Total records parsed successfully</span>
          </div>

          <div className="metric-card">
            <span className="metric-label">Pending Reviews</span>
            <span className="metric-value" style={{ color: 'var(--warning)' }}>{metrics.pending_reviews}</span>
            <span className="metric-sub">Awaiting analyst verification</span>
          </div>

          <div className="metric-card">
            <span className="metric-label">Suspicious Records</span>
            <span className="metric-value" style={{ color: 'var(--danger)' }}>{metrics.suspicious_records}</span>
            <span className="metric-sub">Flagged anomalies requiring audit</span>
          </div>

        </div>
      </section>

      {/* Main Content Area */}
      <main className="app-main">
        
        {activeTab === 'uploader' ? (
          /* ========================================================
             TAB: UPLOADER HUB
             ======================================================== */
          <div className="upload-grid">
            
            {/* Upload Selector Card */}
            <div className="card">
              <div className="card-header">
                <h3 className="card-title">New CSV Data Source Upload</h3>
              </div>
              <div className="card-body">
                <form onSubmit={handleUpload}>
                  <div className="form-group">
                    <label>Select Data Source & Platform</label>
                    <select 
                      className="form-select"
                      value={uploadSourceId}
                      onChange={(e) => setUploadSourceId(e.target.value)}
                    >
                      {dataSources.map(ds => (
                        <option key={ds.id} value={ds.id}>
                          [{ds.source_type}] - {ds.name}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="form-group" style={{ marginTop: '1.5rem' }}>
                    <label>Upload File (CSV format only)</label>
                    <div 
                      className="dropzone"
                      onClick={() => document.getElementById('csv-file-picker').click()}
                    >
                      <div className="dropzone-icon">📥</div>
                      <div className="dropzone-text">
                        Drag and drop your export file here, or <span style={{ color: 'var(--primary)', fontWeight: 600 }}>browse</span>
                      </div>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Supports standard SAP flat sheets, Utility portal exports, or Travel manifests</span>
                      
                      <input 
                        id="csv-file-picker"
                        type="file" 
                        accept=".csv"
                        style={{ display: 'none' }}
                        onChange={(e) => setSelectedFile(e.target.files[0])}
                      />
                    </div>
                  </div>

                  {selectedFile && (
                    <div className="selected-file-badge">
                      <span>📄 {selectedFile.name} ({(selectedFile.size / 1024).toFixed(1)} KB)</span>
                      <button 
                        type="button" 
                        style={{ background: 'transparent', border: 'none', color: 'var(--primary)', fontWeight: 'bold', cursor: 'pointer' }}
                        onClick={() => setSelectedFile(null)}
                      >
                        ✕
                      </button>
                    </div>
                  )}

                  <button 
                    type="submit" 
                    className="btn btn-primary"
                    style={{ width: '100%', marginTop: '1.5rem' }}
                    disabled={isUploading || !selectedFile}
                  >
                    {isUploading ? "Uploading & Ingesting..." : "Process CSV File"}
                  </button>
                </form>

                {uploadMessage && (
                  <div 
                    className={`badge badge-${uploadMessage.type}`} 
                    style={{ display: 'block', padding: '1rem', borderRadius: '8px', marginTop: '1.5rem', fontSize: '0.85rem', width: '100%', textWrap: 'wrap' }}
                  >
                    {uploadMessage.text}
                  </div>
                )}
              </div>
            </div>

            {/* Ingestion Audit Log Card */}
            <div className="card">
              <div className="card-header">
                <h3 className="card-title">Data Ingestion Run History</h3>
                <span className="badge badge-info">{ingestionJobs.length} Jobs</span>
              </div>
              <div className="card-body" style={{ padding: '1.5rem' }}>
                <div className="job-list">
                  {ingestionJobs.map(job => (
                    <div className="job-item" key={job.id}>
                      <div className="job-info">
                        <span className="job-file">📄 {job.file_name}</span>
                        <span className="job-meta">
                          Source: <strong>{job.source_name}</strong> | Type: <strong>{job.source_type}</strong>
                        </span>
                        <span className="job-meta" style={{ color: 'var(--text-muted)' }}>
                          Imported: {new Date(job.created_at).toLocaleString()}
                        </span>
                      </div>
                      
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.4rem' }}>
                        <span className={`badge badge-${job.status === 'SUCCESS' ? 'success' : 'danger'}`}>
                          {job.status}
                        </span>
                        {job.error_message && (
                          <span style={{ fontSize: '0.7rem', color: 'var(--danger-text)', maxWidth: '200px', wordBreak: 'break-all' }}>
                            {job.error_message}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                  {ingestionJobs.length === 0 && (
                    <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
                      No CSV ingestion jobs have been run yet.
                    </div>
                  )}
                </div>
              </div>
            </div>

          </div>
        ) : (
          /* ========================================================
             TAB: REVIEW LEDGER GRID
             ======================================================== */
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            
            {/* Filter Toolbar */}
            <div className="toolbar">
              
              <div className="toolbar-group">
                <label>Scope Group</label>
                <select 
                  className="form-select"
                  style={{ width: '130px' }}
                  value={filterScope}
                  onChange={(e) => setFilterScope(e.target.value)}
                >
                  <option value="">All Scopes</option>
                  <option value="1">Scope 1 (Direct)</option>
                  <option value="2">Scope 2 (Electricity)</option>
                  <option value="3">Scope 3 (Travel)</option>
                </select>
              </div>

              <div className="toolbar-group">
                <label>Category Source</label>
                <select 
                  className="form-select"
                  style={{ width: '150px' }}
                  value={filterCategory}
                  onChange={(e) => setFilterCategory(e.target.value)}
                >
                  <option value="">All Categories</option>
                  <option value="FUEL">Fuel & Procure (SAP)</option>
                  <option value="ELECTRICITY">Electricity (Utility)</option>
                  <option value="TRAVEL">Travel (Concur)</option>
                </select>
              </div>

              <div className="toolbar-group">
                <label>Approval Status</label>
                <select 
                  className="form-select"
                  style={{ width: '140px' }}
                  value={filterStatus}
                  onChange={(e) => setFilterStatus(e.target.value)}
                >
                  <option value="">All Statuses</option>
                  <option value="PENDING">Pending Review</option>
                  <option value="APPROVED">Approved & Locked</option>
                </select>
              </div>

              <div className="toolbar-group">
                <label>Anomalies / Flags</label>
                <select 
                  className="form-select"
                  style={{ width: '150px' }}
                  value={filterSuspicious}
                  onChange={(e) => setFilterSuspicious(e.target.value)}
                >
                  <option value="">All Records</option>
                  <option value="true">Suspicious Only</option>
                  <option value="false">Clean Only</option>
                </select>
              </div>

              <div style={{ flex: 1 }}></div>

              <button 
                className="btn btn-secondary"
                onClick={handleBulkApprove}
              >
                ✓ Bulk Approve Pending
              </button>
            </div>

            {/* Ingested Rows Table */}
            <div className="table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Record ID</th>
                    <th>Activity Date</th>
                    <th>Scope</th>
                    <th>Category</th>
                    <th>Ingested Description</th>
                    <th>Original Reading</th>
                    <th>Normalized Reading</th>
                    <th>Carbon (tCO₂e)</th>
                    <th>Status</th>
                    <th style={{ textAlign: 'center' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {activities.map(act => {
                    const isSusp = act.is_suspicious;
                    const isAppr = act.approval_status === 'APPROVED';
                    
                    return (
                      <tr 
                        key={act.id} 
                        className={`${isSusp ? 'suspicious' : ''} ${isAppr ? 'approved' : ''}`}
                      >
                        <td style={{ fontWeight: 600 }}>#{act.id}</td>
                        <td>{act.activity_date}</td>
                        <td>
                          <span className={`badge ${act.scope === 1 ? 'badge-warning' : act.scope === 2 ? 'badge-info' : 'badge-success'}`}>
                            Scope {act.scope}
                          </span>
                        </td>
                        <td>
                          <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                            {act.category}
                          </span>
                        </td>
                        <td>
                          <div style={{ fontWeight: 500, fontSize: '0.85rem', maxWidth: '300px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {act.description || 'No description provided'}
                          </div>
                          <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                            Via: {act.source_name}
                          </span>
                        </td>
                        <td>
                          {parseFloat(act.raw_value).toFixed(1)} {act.raw_unit}
                        </td>
                        <td style={{ fontWeight: 600 }}>
                          {parseFloat(act.normalized_value).toFixed(1)} {act.normalized_unit}
                        </td>
                        <td style={{ fontWeight: 700, color: isAppr ? 'var(--text-secondary)' : 'var(--primary)' }}>
                          {parseFloat(act.co2e_emissions).toFixed(4)}
                        </td>
                        <td>
                          <span className={`badge badge-${isAppr ? 'success' : isSusp ? 'danger' : 'warning'}`}>
                            {isAppr ? '✓ Approved' : isSusp ? '⚠ Suspicious' : 'Pending'}
                          </span>
                        </td>
                        <td style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>
                          <div style={{ display: 'inline-flex', gap: '0.4rem', justifyContent: 'center' }}>
                            
                            <button 
                              className="btn btn-secondary"
                              style={{ padding: '0.35rem 0.6rem', fontSize: '0.8rem' }}
                              onClick={() => setSelectedRow(act)}
                            >
                              Details
                            </button>

                            {!isAppr ? (
                              <>
                                <button 
                                  className="btn btn-secondary"
                                  style={{ padding: '0.35rem 0.6rem', fontSize: '0.8rem' }}
                                  onClick={() => setEditingRow({ ...act })}
                                >
                                  Edit
                                </button>
                                <button 
                                  className="btn btn-primary"
                                  style={{ padding: '0.35rem 0.6rem', fontSize: '0.8rem' }}
                                  onClick={() => handleApprove(act.id)}
                                >
                                  Approve
                                </button>
                              </>
                            ) : (
                              <span style={{ fontSize: '1.1rem', color: 'var(--success)' }}>🔒</span>
                            )}

                          </div>
                        </td>
                      </tr>
                    );
                  })}

                  {activities.length === 0 && (
                    <tr>
                      <td colSpan="10" style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>
                        No records match the current filters. Navigate to 'Ingestion Hub' to upload CSV data.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

          </div>
        )}

      </main>

      {/* ==========================================================
         DRAWER: RAW LINEAGE & AUDIT LOG TIMELINE
         ========================================================== */}
      {selectedRow && (
        <div className="drawer-backdrop" onClick={() => setSelectedRow(null)}>
          <div className="drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-header">
              <h3>Normalized Row Details & Lineage</h3>
              <button className="drawer-close" onClick={() => setSelectedRow(null)}>✕</button>
            </div>
            
            <div className="drawer-body">
              
              {/* Suspicious Reasons */}
              {selectedRow.is_suspicious && (
                <div className="suspicious-reasons-list">
                  <strong>⚠️ Flagged Suspicious for Audit:</strong>
                  <ul>
                    {selectedRow.suspicion_reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Data Properties */}
              <div className="detail-section">
                <h4>Structured Parameters</h4>
                <div className="detail-grid">
                  <div className="detail-item">
                    <span className="detail-label">Activity Date</span>
                    <span className="detail-value">{selectedRow.activity_date}</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Data Ingest Source</span>
                    <span className="detail-value">{selectedRow.source_name}</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Scope Classification</span>
                    <span className="detail-value">Scope {selectedRow.scope}</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Normalized Metric</span>
                    <span className="detail-value">
                      {parseFloat(selectedRow.normalized_value).toFixed(2)} {selectedRow.normalized_unit}
                    </span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Emissions Cost</span>
                    <span className="detail-value">
                      {selectedRow.cost ? `${selectedRow.currency} ${parseFloat(selectedRow.cost).toFixed(2)}` : 'N/A'}
                    </span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Final Calculated Emissions</span>
                    <span className="detail-value" style={{ color: 'var(--primary)' }}>
                      {parseFloat(selectedRow.co2e_emissions).toFixed(4)} tCO₂e
                    </span>
                  </div>
                </div>

                <div className="detail-item" style={{ marginTop: '0.75rem' }}>
                  <span className="detail-label">Emission Factor Applied</span>
                  <span className="detail-value" style={{ fontSize: '0.85rem', fontWeight: 500 }}>
                    {selectedRow.emission_factor_used}
                  </span>
                </div>
              </div>

              {/* Data Lineage: Original JSON Payload */}
              <div className="detail-section">
                <h4>Original Row Raw Payload (Data Lineage)</h4>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
                  Exact record extracted from original source CSV file during import job:
                </p>
                <div className="raw-json-block">
                  {selectedRow.raw_payload ? JSON.stringify(selectedRow.raw_payload, null, 2) : 'No raw record payload. Manually created row.'}
                </div>
              </div>

              {/* Manual Override Audit History */}
              <div className="detail-section">
                <h4>Manual Override Audit History</h4>
                <div className="timeline" style={{ marginTop: '0.5rem' }}>
                  
                  {auditLogs.map((log) => (
                    <div className="timeline-item" key={log.id}>
                      <div className="timeline-marker">
                        <div className={`timeline-dot ${log.action === 'APPROVE' ? 'approve' : ''}`}></div>
                        <div className="timeline-line"></div>
                      </div>
                      
                      <div className="timeline-content">
                        <div className="timeline-title">
                          <span>{log.action} Action executed</span>
                          <span className="timeline-time">{new Date(log.timestamp).toLocaleString()}</span>
                        </div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                          Performed by: <strong>{log.user}</strong>
                        </div>
                        {log.action === 'EDIT' && (
                          <div className="timeline-changes">
                            <div>Changes logged:</div>
                            {Object.keys(log.after_state).map(k => {
                              const before = log.before_state[k];
                              const after = log.after_state[k];
                              if (before !== after) {
                                return (
                                  <div key={k} style={{ textIndent: '10px' }}>
                                    • {k}: <span style={{ color: 'var(--danger-text)', textDecoration: 'line-through' }}>{before || 'null'}</span> → <span style={{ color: 'var(--success-text)', fontWeight: 600 }}>{after}</span>
                                  </div>
                                );
                              }
                              return null;
                            })}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}

                  {auditLogs.length === 0 && (
                    <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', textAlign: 'center', padding: '1rem' }}>
                      No manual audits or edits have been recorded on this row.
                    </div>
                  )}

                </div>
              </div>

            </div>
          </div>
        </div>
      )}

      {/* ==========================================================
         MODAL: EDIT NORMALIZED DATA ROW
         ========================================================== */}
      {editingRow && (
        <div className="modal-backdrop" onClick={() => setEditingRow(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Edit Ingested Record #{editingRow.id}</h3>
              <button className="drawer-close" onClick={() => setEditingRow(null)}>✕</button>
            </div>
            
            <form onSubmit={handleEditSubmit}>
              <div className="modal-body">
                
                <div style={{ background: '#f8fafc', padding: '0.75rem', borderRadius: '8px', border: '1px solid var(--border-color)', fontSize: '0.8rem' }}>
                  <strong>Note:</strong> Modifying the Normalized Value will trigger automatic carbon recalculations using database-backed emission factors, and will log the changes in the <strong>AuditLog</strong>.
                </div>

                <div className="form-group">
                  <label>Activity Description</label>
                  <input 
                    type="text" 
                    className="form-input" 
                    value={editingRow.description || ''} 
                    onChange={(e) => setEditingRow({ ...editingRow, description: e.target.value })} 
                  />
                </div>

                <div className="form-group">
                  <label>Activity Date</label>
                  <input 
                    type="date" 
                    className="form-input" 
                    value={editingRow.activity_date} 
                    onChange={(e) => setEditingRow({ ...editingRow, activity_date: e.target.value })} 
                  />
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                  <div className="form-group">
                    <label>Normalized Value</label>
                    <input 
                      type="number" 
                      step="any"
                      className="form-input" 
                      value={editingRow.normalized_value} 
                      onChange={(e) => setEditingRow({ ...editingRow, normalized_value: e.target.value })} 
                    />
                  </div>
                  <div className="form-group">
                    <label>Normalized Unit</label>
                    <input 
                      type="text" 
                      className="form-input" 
                      value={editingRow.normalized_unit} 
                      disabled
                    />
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                  <div className="form-group">
                    <label>Financial Cost</label>
                    <input 
                      type="number" 
                      step="0.01"
                      className="form-input" 
                      value={editingRow.cost || ''} 
                      onChange={(e) => setEditingRow({ ...editingRow, cost: e.target.value })} 
                    />
                  </div>
                  <div className="form-group">
                    <label>Currency</label>
                    <input 
                      type="text" 
                      className="form-input" 
                      value={editingRow.currency} 
                      onChange={(e) => setEditingRow({ ...editingRow, currency: e.target.value })} 
                    />
                  </div>
                </div>

              </div>

              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setEditingRow(null)}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary">
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Footer */}
      <footer style={{ backgroundColor: 'white', borderTop: '1px solid var(--border-color)', padding: '1rem 2rem', textAlign: 'center', fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 'auto' }}>
        &copy; {new Date().getFullYear()} Breathe ESG. Financial-grade Carbon Accounting Prototype. All rights reserved.
      </footer>

    </div>
  );
}

export default App;
