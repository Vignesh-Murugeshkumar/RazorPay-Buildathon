/**
 * SentinelDispute Dashboard Application Logic
 * Integrates real-time stats, LangGraph execution simulation, Dossier viewer, and Cryptographic ledger inspector.
 */

let disputesList = [];
let outcomeChartInstance = null;
let scoreDistChartInstance = null;

// Initialize on DOM Load
document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    fetchStats();
    fetchDisputes();
    fetchLedger();
    setupEventListeners();

    // Auto-refresh stats every 10 seconds
    setInterval(() => {
        fetchStats();
    }, 10000);
});

function setupEventListeners() {
    document.getElementById('search-input').addEventListener('input', filterDisputesTable);
    document.getElementById('network-filter').addEventListener('change', filterDisputesTable);
    document.getElementById('decision-filter').addEventListener('change', filterDisputesTable);
}

// Chart Initializations
function initCharts() {
    const ctxOutcome = document.getElementById('outcomeChart');
    if (ctxOutcome) {
        outcomeChartInstance = new Chart(ctxOutcome, {
            type: 'doughnut',
            data: {
                labels: ['Auto-Dispatched (Win)', 'HITL Review Queue'],
                datasets: [{
                    data: [0, 0],
                    backgroundColor: ['#10b981', '#f59e0b'],
                    borderColor: '#0f172a',
                    borderWidth: 3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { color: '#94a3b8', font: { family: 'Inter', size: 12 } }
                    }
                },
                cutout: '72%'
            }
        });
    }

    const ctxScore = document.getElementById('scoreDistChart');
    if (ctxScore) {
        scoreDistChartInstance = new Chart(ctxScore, {
            type: 'bar',
            data: {
                labels: ['0-40 (Low)', '40-69 (Mid)', '70-84 (Borderline)', '85-100 (Autonomous)'],
                datasets: [{
                    label: 'Dispute Volume',
                    data: [0, 0, 0, 0],
                    backgroundColor: ['#f43f5e', '#fb923c', '#f59e0b', '#10b981'],
                    borderRadius: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    x: {
                        ticks: { color: '#94a3b8', font: { family: 'Inter', size: 11 } },
                        grid: { display: false }
                    },
                    y: {
                        ticks: { color: '#94a3b8', stepSize: 5 },
                        grid: { color: 'rgba(255, 255, 255, 0.05)' }
                    }
                }
            }
        });
    }
}

// API Calls
// Tab Switching
function switchMainTab(tabName) {
    const tabs = ['disputes', 'hitl', 'rules', 'ledger'];
    tabs.forEach(t => {
        const btn = document.getElementById(`tab-btn-${t}`);
        const view = document.getElementById(`view-${t}`);
        if (btn) btn.classList.remove('active');
        if (view) view.style.display = 'none';
    });

    const activeBtn = document.getElementById(`tab-btn-${tabName}`);
    const activeView = document.getElementById(`view-${tabName}`);
    if (activeBtn) activeBtn.classList.add('active');
    if (activeView) activeView.style.display = 'block';

    if (tabName === 'hitl') fetchHitlQueue();
    if (tabName === 'rules') fetchRules();
    if (tabName === 'disputes') fetchDisputes();
}

// API Calls
async function fetchStats() {
    try {
        const [statsRes, dashRes] = await Promise.all([
            fetch('/api/v1/stats'),
            fetch('/api/v1/dashboard/summary')
        ]);
        
        if (statsRes.ok) {
            const stats = await statsRes.json();
            document.getElementById('kpi-total-disputes').innerText = stats.total_disputes.toLocaleString();
            document.getElementById('kpi-yield-rate').innerText = `${stats.autonomous_yield_percentage.toFixed(1)}%`;
            document.getElementById('kpi-recovered-gmv').innerText = `₹${stats.recovered_gmv_inr.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
            document.getElementById('kpi-total-blocks').innerText = stats.total_ledger_blocks.toLocaleString();
            
            const badgeDisputes = document.getElementById('badge-all-disputes');
            if (badgeDisputes) badgeDisputes.innerText = stats.total_disputes;

            const integrityBadge = document.getElementById('ledger-integrity-status');
            if (integrityBadge) {
                if (stats.ledger_integrity_verified) {
                    integrityBadge.innerHTML = `<span class="pulse-dot"></span> SHA-256 Ledger: Verified`;
                    integrityBadge.className = 'status-pill active';
                } else {
                    integrityBadge.innerHTML = `⚠️ Ledger Tamper Detected`;
                    integrityBadge.className = 'status-pill';
                    integrityBadge.style.color = '#f43f5e';
                }
            }

            if (outcomeChartInstance) {
                outcomeChartInstance.data.datasets[0].data = [stats.auto_dispatched_count, stats.hitl_count];
                outcomeChartInstance.update();
            }
        }

        if (dashRes.ok) {
            const dash = await dashRes.json();
            const hitlBadge = document.getElementById('hitl-counter-badge');
            if (hitlBadge) hitlBadge.innerText = dash.hitl_pending_count || 0;
        }
    } catch (err) {
        console.error('Error fetching stats:', err);
    }
}

async function fetchDisputes() {
    try {
        const res = await fetch('/api/v1/disputes');
        if (!res.ok) return;
        disputesList = await res.json();
        renderDisputesTable(disputesList);
        updateScoreDistributionChart(disputesList);
        const badge = document.getElementById('badge-all-disputes');
        if (badge) badge.innerText = disputesList.length;
    } catch (err) {
        console.error('Error fetching disputes:', err);
    }
}

async function fetchLedger() {
    try {
        const res = await fetch('/api/v1/audit/blocks?limit=15');
        if (!res.ok) return;
        const blocks = await res.json();
        renderLedgerBlocks(blocks);
    } catch (err) {
        console.error('Error fetching ledger:', err);
    }
}

async function fetchHitlQueue() {
    try {
        const res = await fetch('/api/v1/review-queue');
        if (!res.ok) return;
        const data = await res.json();
        const queue = data.disputes || [];
        const tbody = document.getElementById('hitl-tbody');
        const badge = document.getElementById('hitl-counter-badge');
        if (badge) badge.innerText = queue.length;
        if (!tbody) return;

        if (queue.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" style="text-align: center; padding: 40px; color: var(--accent-emerald);">
                        🎉 No disputes currently pending manual review. All representments are automated or resolved!
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = queue.map(q => {
            const pWin = (q.win_probability !== null && q.win_probability !== undefined) ? (q.win_probability * 100).toFixed(1) + '%' : 'N/A';
            const ev = q.expected_value_inr !== undefined ? q.expected_value_inr : 0;
            const assignedBadge = q.assigned_to 
                ? `<span class="badge" style="background: rgba(168, 85, 247, 0.2); color: #c084fc;">👤 ${q.assigned_to}</span>` 
                : `<button class="btn btn-secondary" style="padding: 2px 8px; font-size: 11px;" onclick="assignPrompt('${q.dispute_id}')">+ Assign</button>`;

            const gapsList = (q.diagnostic_gaps && q.diagnostic_gaps.length > 0)
                ? q.diagnostic_gaps.map(g => `<span class="factor-pill-neg" style="font-size: 10px; margin: 1px;">⚠️ ${g}</span>`).join(' ')
                : `<span style="color: var(--text-muted); font-size: 11px;">Awaiting analyst assessment</span>`;

            return `
                <tr>
                    <td>
                        <span class="mono-text" style="font-weight: 600; color: var(--accent-cyan);">${q.dispute_id}</span>
                        <br><span class="mono-text" style="font-size: 10px; color: var(--text-subtle);">${q.payment_id}</span>
                    </td>
                    <td style="font-weight: 600;">₹${q.amount_inr.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
                    <td><span class="badge badge-visa">${q.card_network.toUpperCase()} (${q.reason_code})</span></td>
                    <td>
                        <div style="font-size: 12px; font-weight: 600; color: var(--accent-cyan);">P(win): ${pWin}</div>
                        <div style="font-size: 11px; color: ${ev >= 0 ? 'var(--accent-emerald)' : 'var(--accent-rose)'}; font-family: var(--font-mono);">
                            E[V]: ${ev >= 0 ? '+' : ''}₹${ev.toLocaleString()}
                        </div>
                    </td>
                    <td style="max-width: 280px;">${gapsList}</td>
                    <td>${assignedBadge}</td>
                    <td>
                        <div style="display: flex; gap: 6px;">
                            <button class="btn btn-secondary" style="padding: 4px 8px; font-size: 11px;" onclick="viewDossier('${q.dispute_id}')">Inspect</button>
                            <button class="btn btn-primary" style="padding: 4px 8px; font-size: 11px; background: linear-gradient(135deg, #f59e0b, #d97706);" onclick="openRemediationModal('${q.dispute_id}')">🛠️ Remediate</button>
                        </div>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        console.error('Error fetching HITL queue:', err);
    }
}

async function fetchRules() {
    try {
        const res = await fetch('/api/v1/rules/all');
        if (!res.ok) return;
        const data = await res.json();
        const container = document.getElementById('rules-container');
        if (!container) return;

        const rulesObj = data.rules || {};
        container.innerHTML = Object.entries(rulesObj).map(([netKey, netData]) => {
            const regs = netData.regulations || [];
            return `
                <div class="card-panel" style="background: var(--surface-2); border-radius: var(--radius-lg); padding: 18px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid var(--border-color); padding-bottom: 8px;">
                        <h3 style="font-size: 15px; font-weight: 700; color: var(--accent-cyan);">${netData.network}</h3>
                        <span class="badge badge-visa">${regs.length} Active Rules</span>
                    </div>
                    ${regs.map(r => `
                        <div style="margin-bottom: 14px; background: rgba(0,0,0,0.2); padding: 10px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.05);">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                                <strong style="color: var(--text-main); font-size: 12px;">${r.name}</strong>
                                <span class="mono-text" style="font-size: 10px; color: var(--accent-amber);">Reason ${r.reason_codes.join(', ')}</span>
                            </div>
                            <p style="font-size: 11px; color: var(--text-muted); margin-bottom: 6px;">${r.description}</p>
                            ${r.lookback_window_days ? `
                                <div style="font-size: 10px; color: var(--accent-emerald); font-family: var(--font-mono);">
                                    Lookback Window: ${r.lookback_window_days.min} - ${r.lookback_window_days.max} days | Min Orders: ${r.qualifying_threshold}
                                </div>
                            ` : ''}
                        </div>
                    `).join('')}
                </div>
            `;
        }).join('');
    } catch (err) {
        console.error('Error fetching rules:', err);
    }
}

function downloadPdf(disputeId) {
    window.open(`/api/v1/disputes/${disputeId}/representment-pdf`, '_blank');
}

async function assignPrompt(disputeId) {
    const analyst = prompt("Enter Reviewer or Analyst name for dispute " + disputeId + ":", "Senior Analyst");
    if (!analyst || !analyst.trim()) return;

    try {
        const res = await fetch(`/api/v1/disputes/${disputeId}/assign`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ assigned_to: analyst.trim() })
        });
        if (res.ok) {
            alert(`Dispute ${disputeId} successfully assigned to ${analyst.trim()}`);
            fetchDisputes();
            fetchHitlQueue();
            fetchStats();
        } else {
            alert('Failed to assign dispute. Please check server logs.');
        }
    } catch (err) {
        console.error('Error assigning dispute:', err);
    }
}

// Table Rendering
function renderDisputesTable(disputes) {
    const tbody = document.getElementById('disputes-tbody');
    if (!tbody) return;

    if (disputes.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" style="text-align: center; padding: 40px; color: var(--text-muted);">
                    No disputes processed yet. Click a simulation preset above to test real-time state execution!
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = disputes.map(d => {
        const isAuto = d.decision === 'AUTO_DISPATCHED';
        const isVisa = d.card_network.toLowerCase().includes('visa');
        
        let scoreClass = 'low';
        if (d.confidence_score >= 85) scoreClass = 'high';
        else if (d.confidence_score >= 60) scoreClass = 'mid';

        const pWinStr = (d.win_probability !== null && d.win_probability !== undefined) 
            ? (d.win_probability * 100).toFixed(1) + '%' 
            : ((d.p_win || 0) * 100).toFixed(1) + '%';

        const evVal = (d.expected_value !== null && d.expected_value !== undefined)
            ? d.expected_value
            : (d.expected_value_inr || 0);

        const assignedHtml = d.assigned_to 
            ? `<span class="badge" style="background: rgba(168, 85, 247, 0.2); color: #c084fc; font-size: 11px;">👤 ${d.assigned_to}</span>` 
            : `<button class="btn btn-secondary" style="padding: 2px 6px; font-size: 10px;" onclick="assignPrompt('${d.dispute_id}')">+ Assign</button>`;

        return `
            <tr>
                <td>
                    <span class="mono-text" style="font-weight: 600; color: var(--accent-cyan);">${d.dispute_id}</span>
                    <br><span class="mono-text" style="font-size: 10px; color: var(--text-subtle);">${d.payment_id}</span>
                </td>
                <td>
                    <span class="badge ${isVisa ? 'badge-visa' : 'badge-mc'}">
                        ${d.card_network.toUpperCase()} (${d.reason_code})
                    </span>
                </td>
                <td style="font-weight: 600;">
                    ₹${d.amount_inr.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                </td>
                <td>
                    <div class="score-cell">
                        <div class="score-bar-bg">
                            <div class="score-bar-fill ${scoreClass}" style="width: ${d.confidence_score}%"></div>
                        </div>
                        <span style="font-weight: 600; font-size: 12px;">${d.confidence_score}</span>
                    </div>
                </td>
                <td>
                    <div style="font-size: 12px; font-weight: 600; color: var(--accent-cyan);">${pWinStr}</div>
                    <div style="font-size: 10px; color: ${evVal >= 0 ? 'var(--accent-emerald)' : 'var(--accent-rose)'}; font-family: var(--font-mono);">
                        E[V]: ${evVal >= 0 ? '+' : ''}₹${evVal.toLocaleString()}
                    </div>
                </td>
                <td>
                    <span class="badge ${isAuto ? 'badge-auto' : (d.decision === 'AUTO_ACCEPT_OR_REFUND' ? 'badge-hitl' : 'badge-hitl')}">
                        ${isAuto ? '🛡️ Auto-Dispatched' : (d.decision === 'AUTO_ACCEPT_OR_REFUND' ? '🛑 Auto-Refund' : '👤 HITL Review')}
                    </span>
                </td>
                <td>
                    ${assignedHtml}
                </td>
                <td>
                    <div style="display: flex; gap: 4px;">
                        <button class="btn btn-secondary" style="padding: 4px 8px; font-size: 11px;" onclick="viewDossier('${d.dispute_id}')">
                            Inspect
                        </button>
                        <button class="btn btn-pdf" style="padding: 4px 8px; font-size: 11px;" onclick="downloadPdf('${d.dispute_id}')" title="Download Representment PDF">
                            📄 PDF
                        </button>
                        ${!isAuto ? `
                            <button class="btn btn-primary" style="padding: 4px 8px; font-size: 11px; background: linear-gradient(135deg, #f59e0b, #d97706); border-color: #f59e0b;" onclick="openRemediationModal('${d.dispute_id}')">
                                🛠️
                            </button>
                        ` : ''}
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function updateScoreDistributionChart(disputes) {
    if (!scoreDistChartInstance) return;
    const bins = [0, 0, 0, 0];
    disputes.forEach(d => {
        const s = d.confidence_score;
        if (s < 40) bins[0]++;
        else if (s < 70) bins[1]++;
        else if (s < 85) bins[2]++;
        else bins[3]++;
    });
    scoreDistChartInstance.data.datasets[0].data = bins;
    scoreDistChartInstance.update();
}

function filterDisputesTable() {
    const search = document.getElementById('search-input').value.toLowerCase();
    const network = document.getElementById('network-filter').value.toLowerCase();
    const decision = document.getElementById('decision-filter').value;

    const filtered = disputesList.filter(d => {
        const matchSearch = d.dispute_id.toLowerCase().includes(search) || 
                            d.payment_id.toLowerCase().includes(search) || 
                            d.reason_code.toLowerCase().includes(search);
        const matchNetwork = network === 'all' || d.card_network.toLowerCase().includes(network);
        const matchDecision = decision === 'all' || d.decision === decision;
        return matchSearch && matchNetwork && matchDecision;
    });

    renderDisputesTable(filtered);
}

// Render Ledger Blocks
function renderLedgerBlocks(blocks) {
    const container = document.getElementById('ledger-blocks-container');
    if (!container) return;

    container.innerHTML = blocks.map(b => `
        <div class="ledger-block-item">
            <div class="block-header">
                <div>
                    <span class="block-tag">Block #${b.index}</span>
                    <span style="color: var(--text-muted); margin-left: 8px;">[${b.agent_id}] &rarr; <strong>${b.state_transition}</strong></span>
                </div>
                <span class="mono-text" style="color: var(--text-subtle); font-size: 11px;">${b.timestamp.split('T')[1].substring(0, 8)} UTC</span>
            </div>
            <div class="block-hashes">
                <div>
                    <span class="hash-label">PREVIOUS BLOCK HASH</span>
                    <span class="hash-val">${b.previous_hash.substring(0, 24)}...</span>
                </div>
                <div>
                    <span class="hash-label">BLOCK SHA-256 HASH</span>
                    <span class="hash-val" style="color: var(--accent-cyan);">${b.block_hash.substring(0, 24)}...</span>
                </div>
            </div>
        </div>
    `).join('');
}

// Modal Dossier Inspector
async function viewDossier(disputeId) {
    try {
        const [dossierRes, timelineRes] = await Promise.all([
            fetch(`/api/v1/disputes/${disputeId}`),
            fetch(`/api/v1/disputes/${disputeId}/timeline`)
        ]);

        if (!dossierRes.ok) return;
        const dossier = await dossierRes.json();
        const timelineEvents = timelineRes.ok ? await timelineRes.json() : [];

        const modal = document.getElementById('dossier-modal');
        const modalBody = document.getElementById('modal-dossier-body');

        const isAuto = dossier.decision === 'AUTO_DISPATCHED';
        const evalRes = dossier.evaluation || {};
        const pWin = dossier.win_probability !== null && dossier.win_probability !== undefined ? (dossier.win_probability * 100).toFixed(1) + '%' : ((dossier.p_win || 0) * 100).toFixed(1) + '%';
        const evVal = dossier.expected_value !== null && dossier.expected_value !== undefined ? dossier.expected_value : (dossier.expected_value_inr || 0);

        const explanation = dossier.decision_explanation || {};
        const positiveFactors = explanation.top_positive_factors || [];
        const negativeFactors = explanation.top_negative_factors || [];

        modalBody.innerHTML = `
            <!-- Dossier Header Banner -->
            <div class="dossier-cert-banner">
                <div>
                    <h3 style="font-size: 16px; font-weight: 700; color: #ffffff; margin-bottom: 4px;">
                        ${isAuto ? '🛡️ Autonomous Representment Dossier (CE 3.0 / FPT Certified)' : '⚠️ Human-in-the-Loop Review Dossier'}
                    </h3>
                    <p style="font-size: 12px; color: var(--text-muted);">${dossier.summary}</p>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 24px; font-weight: 800; color: ${isAuto ? 'var(--accent-emerald)' : 'var(--accent-amber)'};">
                        ${dossier.confidence_score}<span style="font-size: 14px; font-weight: 500; color: var(--text-muted);">/100</span>
                    </div>
                    <span class="badge ${isAuto ? 'badge-auto' : 'badge-hitl'}">${dossier.decision}</span>
                </div>
            </div>

            <!-- Explainable AI Decision Card -->
            <div style="background: var(--surface-2); border-radius: var(--radius-md); padding: 18px; border: 1px solid var(--border-color);">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                    <h4 style="font-size: 14px; font-weight: 600; color: var(--accent-cyan); margin: 0;">
                        🧠 Explainable AI Decision &amp; Attribution Factors
                    </h4>
                    <span class="badge badge-visa">${explanation.rule_applied || dossier.card_network.toUpperCase()}</span>
                </div>
                <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 12px;">${explanation.summary || dossier.summary}</p>

                ${positiveFactors.length > 0 ? `
                    <div style="margin-bottom: 10px;">
                        <span style="font-size: 11px; font-weight: 600; color: var(--accent-emerald); display: block; margin-bottom: 4px;">TOP POSITIVE FACTORS:</span>
                        <div style="display: flex; flex-wrap: wrap; gap: 6px;">
                            ${positiveFactors.map(f => `<span class="factor-pill-pos">✅ ${f}</span>`).join('')}
                        </div>
                    </div>
                ` : ''}

                ${negativeFactors.length > 0 ? `
                    <div style="margin-bottom: 10px;">
                        <span style="font-size: 11px; font-weight: 600; color: var(--accent-amber); display: block; margin-bottom: 4px;">ATTRIBUTION GAPS / NEGATIVE FACTORS:</span>
                        <div style="display: flex; flex-wrap: wrap; gap: 6px;">
                            ${negativeFactors.map(f => `<span class="factor-pill-neg">⚠️ ${f}</span>`).join('')}
                        </div>
                    </div>
                ` : ''}

                <div style="background: rgba(0,0,0,0.2); padding: 8px 12px; border-radius: 6px; font-size: 11px; color: var(--text-main); margin-top: 8px;">
                    <strong>Recommendation:</strong> ${explanation.recommendation || 'Proceed with representment'}
                </div>
            </div>

            <!-- Evidence Intelligence Matrix -->
            <div>
                <h4 style="font-size: 14px; font-weight: 600; margin-bottom: 12px; color: var(--text-main);">
                    🎯 Evidence Intelligence &amp; Multi-Factor Verification
                </h4>
                <div class="matrix-grid">
                    <div class="matrix-card ${dossier.mfa_verification ? 'matched' : 'missing'}">
                        <div class="matrix-status">${dossier.mfa_verification ? '✅' : '❌'}</div>
                        <div class="matrix-title">Authentication (3DS)</div>
                        <div class="matrix-desc">${dossier.payment_authentication || (dossier.mfa_verification ? '3DS 2.2 Verified' : 'Frictionless')}</div>
                    </div>
                    <div class="matrix-card ${(dossier.delivery_proof && dossier.delivery_proof.delivered_status) || (dossier.carrier_proof && dossier.carrier_proof.delivered_status) ? 'matched' : 'missing'}">
                        <div class="matrix-status">${(dossier.delivery_proof && dossier.delivery_proof.delivered_status) || (dossier.carrier_proof && dossier.carrier_proof.delivered_status) ? '✅' : '❌'}</div>
                        <div class="matrix-title">Physical Carrier Proof</div>
                        <div class="matrix-desc">${dossier.delivery_proof ? dossier.delivery_proof.carrier_name + ' (' + dossier.delivery_proof.tracking_number + ')' : (dossier.carrier_proof ? dossier.carrier_proof.carrier_name : 'No Proof')}</div>
                    </div>
                    <div class="matrix-card ${(dossier.gps_verification && dossier.gps_verification.verified_within_50m) || (dossier.carrier_proof && dossier.carrier_proof.verified_gps) ? 'matched' : 'missing'}">
                        <div class="matrix-status">${(dossier.gps_verification && dossier.gps_verification.verified_within_50m) || (dossier.carrier_proof && dossier.carrier_proof.verified_gps) ? '✅' : '❌'}</div>
                        <div class="matrix-title">GPS Geolocation Scan</div>
                        <div class="matrix-desc">${(dossier.gps_verification && dossier.gps_verification.verified_within_50m) ? '50m Radius Verified' : 'No GPS Match'}</div>
                    </div>
                    <div class="matrix-card ${(dossier.customer_history_summary && dossier.customer_history_summary.qualifying_orders_count >= 1) || dossier.historical_count >= 1 ? 'matched' : 'missing'}">
                        <div class="matrix-status">${(dossier.customer_history_summary && dossier.customer_history_summary.qualifying_orders_count >= 1) || dossier.historical_count >= 1 ? '✅' : '❌'}</div>
                        <div class="matrix-title">Historical Trust (CE 3.0)</div>
                        <div class="matrix-desc">${dossier.customer_history_summary ? dossier.customer_history_summary.total_historical_orders + ' orders (' + dossier.customer_history_summary.undisputed_count + ' undisputed)' : dossier.historical_count + ' historical orders'}</div>
                    </div>
                </div>
            </div>

            <!-- Economic Expected Value (E[V]) Breakdown -->
            <div style="background: rgba(56, 189, 248, 0.08); border: 1px solid rgba(56, 189, 248, 0.3); border-radius: var(--radius-md); padding: 16px;">
                <h4 style="font-size: 13px; font-weight: 600; color: #38bdf8; margin-bottom: 12px;">
                    💰 Economic Net Recovery Expected Value E[V] = P(win)&middot;A &minus; (1&minus;P(win))&middot;F<sub>fee</sub> &minus; C<sub>op</sub>
                </h4>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; font-size: 12px;">
                    <div class="metric-box">
                        <div class="metric-box-title">Disputed Amount (A)</div>
                        <div class="metric-box-val" style="color: var(--text-main);">₹${dossier.amount_inr.toLocaleString()}</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-box-title">Win Prob P(win)</div>
                        <div class="metric-box-val" style="color: var(--accent-cyan);">${pWin}</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-box-title">Net E[V]</div>
                        <div class="metric-box-val" style="color: ${evVal >= 0 ? 'var(--accent-emerald)' : 'var(--accent-rose)'};">
                            ${evVal >= 0 ? '+' : ''}₹${evVal.toLocaleString()}
                        </div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-box-title">Issuer Fee Risk</div>
                        <div class="metric-box-val" style="color: var(--accent-rose);">₹1,500.00</div>
                    </div>
                </div>
            </div>

            <!-- Evidence Timeline Trail -->
            <div style="background: var(--surface-2); border-radius: var(--radius-md); padding: 18px; border: 1px solid var(--border-color);">
                <h4 style="font-size: 13px; font-weight: 600; color: #a855f7; margin-bottom: 14px;">
                    ⏱️ Chronological Evidence &amp; Decision Timeline
                </h4>
                <div class="timeline-container">
                    ${timelineEvents.length > 0 ? timelineEvents.map(ev => `
                        <div class="timeline-node">
                            <div class="timeline-dot"></div>
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <span class="timeline-title">${ev.title}</span>
                                <span class="timeline-time">${ev.timestamp ? ev.timestamp.substring(11, 19) : ''}</span>
                            </div>
                            <div class="timeline-desc">${ev.description}</div>
                        </div>
                    `).join('') : '<div style="color: var(--text-muted); font-size: 12px;">No timeline events recorded.</div>'}
                </div>
            </div>

            <!-- Modal Action Buttons Bar -->
            <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid var(--border-color); padding-top: 16px;">
                <div style="display: flex; gap: 10px;">
                    <button class="btn btn-pdf" onclick="downloadPdf('${dossier.dispute_id}')">
                        📥 Download Official PDF Packet
                    </button>
                    <button class="btn btn-secondary" onclick="window.open('/api/v1/disputes/${dossier.dispute_id}/representment-package', '_blank')">
                        📄 View JSON Package
                    </button>
                    <button class="btn btn-secondary" onclick="assignPrompt('${dossier.dispute_id}')">
                        👤 ${dossier.assigned_to ? 'Reassign (' + dossier.assigned_to + ')' : 'Assign Analyst'}
                    </button>
                </div>
                ${!isAuto ? `
                    <button class="btn btn-primary" style="background: linear-gradient(135deg, #f59e0b, #d97706); border-color: #f59e0b;" onclick="openRemediationModal('${dossier.dispute_id}')">
                        🛠️ Remediate Evidence
                    </button>
                ` : ''}
            </div>

            <!-- Cryptographic Seal Info -->
            <div style="border-top: 1px solid var(--border-color); padding-top: 12px; font-size: 11px; font-family: var(--font-mono); color: var(--text-muted);">
                <div><strong>CRYPTOGRAPHIC SEAL:</strong> <span style="color: var(--accent-cyan);">${dossier.sealed_hash}</span></div>
                <div><strong>TIMESTAMP:</strong> ${dossier.timestamp}</div>
            </div>
        `;

        modal.classList.add('open');
    } catch (err) {
        console.error('Error viewing dossier:', err);
    }
}

function closeDossierModal() {
    const modal = document.getElementById('dossier-modal');
    if (modal) modal.classList.remove('open');
}

// Quick Scenario Simulations
async function runSimulation(type) {
    let payload;
    const now = Date.now();

    if (type === 'visa_ce30') {
        payload = {
            event: "payment.dispute.created",
            dispute_id: `disp_sim_visa_${now % 10000}`,
            payment_id: `pay_visa_${now % 10000}`,
            amount_inr: 4500.0,
            card_network: "visa",
            reason_code: "10.4",
            telemetry: {
                ip_address: "49.207.180.45",
                device_id: "dev_fingerprint_macbook_pro_uuid",
                user_id: "user_rahul_sharma",
                shipping_address: "Flat 402, Embassy Palms, Indiranagar, Bangalore",
                mfa_authenticated: true
            },
            carrier_proof: {
                carrier_name: "BlueDart Express",
                tracking_number: `BD${now % 100000}`,
                delivered_status: true,
                verified_gps: true
            },
            historical_transactions: [
                {
                    transaction_id: "tx_h1",
                    payment_id: "pay_h1",
                    amount_inr: 4200.0,
                    days_ago: 145,
                    card_last4: "4242",
                    card_network: "visa",
                    ip_address: "49.207.180.45",
                    device_id: "dev_fingerprint_macbook_pro_uuid",
                    user_id: "user_rahul_sharma",
                    shipping_address: "Flat 402, Embassy Palms, Indiranagar, Bangalore",
                    undisputed: true
                },
                {
                    transaction_id: "tx_h2",
                    payment_id: "pay_h2",
                    amount_inr: 4800.0,
                    days_ago: 290,
                    card_last4: "4242",
                    card_network: "visa",
                    ip_address: "49.207.180.45",
                    device_id: "dev_fingerprint_macbook_pro_uuid",
                    user_id: "user_rahul_sharma",
                    shipping_address: "Flat 402, Embassy Palms, Indiranagar, Bangalore",
                    undisputed: true
                }
            ]
        };
    } else if (type === 'mc_fpt') {
        payload = {
            event: "payment.dispute.created",
            dispute_id: `disp_sim_mc_${now % 10000}`,
            payment_id: `pay_mc_${now % 10000}`,
            amount_inr: 7800.0,
            card_network: "mastercard",
            reason_code: "4837",
            telemetry: {
                ip_address: "103.211.54.88",
                device_id: "dev_pixel_phone_uuid",
                user_id: "user_priya_nair",
                shipping_address: "Tower 3, Hiranandani, Powai, Mumbai",
                mfa_authenticated: true
            },
            carrier_proof: {
                carrier_name: "Delhivery",
                tracking_number: `DL${now % 100000}`,
                delivered_status: true,
                verified_gps: true
            },
            historical_transactions: [
                {
                    transaction_id: "tx_mc_h1",
                    payment_id: "pay_mc_h1",
                    amount_inr: 6500.0,
                    days_ago: 80,
                    card_last4: "5555",
                    card_network: "mastercard",
                    ip_address: "103.211.54.88",
                    device_id: "dev_pixel_phone_uuid",
                    user_id: "user_priya_nair",
                    shipping_address: "Tower 3, Hiranandani, Powai, Mumbai",
                    undisputed: true
                },
                {
                    transaction_id: "tx_mc_h2",
                    payment_id: "pay_mc_h2",
                    amount_inr: 7200.0,
                    days_ago: 180,
                    card_last4: "5555",
                    card_network: "mastercard",
                    ip_address: "103.211.54.88",
                    device_id: "dev_pixel_phone_uuid",
                    user_id: "user_priya_nair",
                    shipping_address: "Tower 3, Hiranandani, Powai, Mumbai",
                    undisputed: true
                }
            ]
        };
    } else if (type === 'hitl_lookback') {
        payload = {
            event: "payment.dispute.created",
            dispute_id: `disp_sim_hitl_${now % 10000}`,
            payment_id: `pay_hitl_${now % 10000}`,
            amount_inr: 3200.0,
            card_network: "visa",
            reason_code: "10.4",
            telemetry: {
                ip_address: "115.112.89.12",
                device_id: "dev_unknown_tablet",
                user_id: "user_vikram_singh",
                shipping_address: "Anna Nagar, Chennai",
                mfa_authenticated: false
            },
            carrier_proof: {
                carrier_name: "Shadowfax",
                tracking_number: `SF${now % 100000}`,
                delivered_status: false,
                verified_gps: false
            },
            historical_transactions: [
                {
                    transaction_id: "tx_h1",
                    payment_id: "pay_h1",
                    amount_inr: 3000.0,
                    days_ago: 30, // < 120 days
                    card_last4: "4242",
                    card_network: "visa",
                    ip_address: "115.112.89.12",
                    device_id: "dev_unknown_tablet",
                    user_id: "user_vikram_singh",
                    shipping_address: "Anna Nagar, Chennai",
                    undisputed: true
                }
            ]
        };
    } else if (type === 'service_13_1_rag') {
        payload = {
            event: "payment.dispute.created",
            dispute_id: `disp_sim_rag_${now % 10000}`,
            payment_id: `pay_rag_${now % 10000}`,
            amount_inr: 8500.0,
            card_network: "visa",
            reason_code: "13.1",
            telemetry: {
                ip_address: "106.51.78.22",
                device_id: "dev_iphone15_pro_uuid",
                user_id: "user_ananya_sharma",
                shipping_address: "B-204, Prestige Ozone, Whitefield, Bangalore",
                mfa_authenticated: true
            },
            carrier_proof: {
                carrier_name: "BlueDart Express",
                tracking_number: `BD99881122`,
                delivered_status: true,
                recipient_signature_present: true,
                verified_gps: true,
                gps_latitude: 12.9698,
                gps_longitude: 77.7499
            },
            historical_transactions: []
        };
    } else if (type === 'negative_ev_refund') {
        // Low amount (₹400), low probability, unviable E[V] <= 0
        payload = {
            event: "payment.dispute.created",
            dispute_id: `disp_sim_low_ev_${now % 10000}`,
            payment_id: `pay_low_ev_${now % 10000}`,
            amount_inr: 450.0,
            card_network: "visa",
            reason_code: "10.4",
            telemetry: {
                ip_address: "14.139.128.1",
                device_id: "unverified_dev_fp",
                user_id: "guest_buyer",
                shipping_address: "General Delivery",
                mfa_authenticated: false
            },
            carrier_proof: null,
            historical_transactions: []
        };
    } else if (type === 'razorpay_udir') {
        // Domestic NPCI UDIR UPI / RuPay dispute
        payload = {
            event: "payment.dispute.created",
            dispute_id: `disp_sim_udir_${now % 10000}`,
            payment_id: `pay_upi_${now % 10000}`,
            amount_inr: 3500.0,
            card_network: "rupay",
            reason_code: "10.4",
            service_type: "physical",
            telemetry: {
                ip_address: "49.207.180.45",
                device_id: "dev_fingerprint_macbook_pro_uuid",
                user_id: "user_rahul_sharma",
                shipping_address: "Flat 402, Embassy Palms, Indiranagar, Bangalore",
                mfa_authenticated: true
            },
            carrier_proof: {
                carrier_name: "Delhivery",
                tracking_number: `DL${now % 100000}`,
                delivered_status: true,
                verified_gps: true
            },
            historical_transactions: [
                {
                    transaction_id: "tx_u1",
                    payment_id: "pay_u1",
                    amount_inr: 3200.0,
                    days_ago: 150,
                    card_last4: "1234",
                    card_network: "rupay",
                    ip_address: "49.207.180.45",
                    device_id: "dev_fingerprint_macbook_pro_uuid",
                    user_id: "user_rahul_sharma",
                    shipping_address: "Flat 402, Embassy Palms, Indiranagar, Bangalore",
                    undisputed: true
                },
                {
                    transaction_id: "tx_u2",
                    payment_id: "pay_u2",
                    amount_inr: 3800.0,
                    days_ago: 240,
                    card_last4: "1234",
                    card_network: "rupay",
                    ip_address: "49.207.180.45",
                    device_id: "dev_fingerprint_macbook_pro_uuid",
                    user_id: "user_rahul_sharma",
                    shipping_address: "Flat 402, Embassy Palms, Indiranagar, Bangalore",
                    undisputed: true
                }
            ]
        };
    } else if (type === 'pre_dispute_deflect') {
        // First ingest 2 qualifying telemetry orders in hot cache
        const cardFp = "card_fp_test_verifi_deflect_99";
        try {
            await fetch('/api/v1/pre-dispute/telemetry/ingest', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    card_fingerprint: cardFp,
                    customer_id: "user_deflect_hero",
                    ip_address: "49.207.180.45",
                    device_fingerprint: "dev_deflect_fp_uuid",
                    shipping_address: "Indiranagar, Bangalore",
                    days_ago: 160
                })
            });
            await fetch('/api/v1/pre-dispute/telemetry/ingest', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    card_fingerprint: cardFp,
                    customer_id: "user_deflect_hero",
                    ip_address: "49.207.180.45",
                    device_fingerprint: "dev_deflect_fp_uuid",
                    shipping_address: "Indiranagar, Bangalore",
                    days_ago: 280
                })
            });

            // Now dispatch pre-dispute inquiry
            const inqRes = await fetch('/api/v1/pre-dispute/verifi', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    order_insight_id: `oi_${now % 10000}`,
                    card_fingerprint: cardFp,
                    customer_id: "user_deflect_hero",
                    ip_address: "49.207.180.45",
                    device_fingerprint: "dev_deflect_fp_uuid",
                    shipping_address: "Indiranagar, Bangalore"
                })
            });
            const inqData = await inqRes.json();
            await fetchStats();
            await fetchLedger();
            alert(`🛡️ Verifi Order Insight Pre-Dispute Interception Result:\nStatus: ${inqData.status}\nResponse Latency: ${inqData.response_time_ms} ms (SLA <= 2000ms: ${inqData.sla_guaranteed})\nEvidence: ${inqData.evidence_type}\nMessage: ${inqData.message}`);
            return;
        } catch (err) {
            alert('Error running pre-dispute deflection simulation: ' + err.message);
            return;
        }
    } else {
        // Fraud / Unqualified
        payload = {
            event: "payment.dispute.created",
            dispute_id: `disp_sim_fraud_${now % 10000}`,
            payment_id: `pay_fraud_${now % 10000}`,
            amount_inr: 12500.0,
            card_network: "visa",
            reason_code: "10.4",
            telemetry: {
                ip_address: "185.220.101.5",
                device_id: "spoofed_emulator_device",
                user_id: "anonymous_shopper",
                shipping_address: "Unknown Drop Point, Delhi",
                mfa_authenticated: false
            },
            carrier_proof: null,
            historical_transactions: []
        };
    }

    try {
        const res = await fetch('/api/v1/simulate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!res.ok) throw new Error('Simulation failed');
        const dossier = await res.json();
        
        await fetchStats();
        await fetchDisputes();
        await fetchLedger();

        viewDossier(dossier.dispute_id);
    } catch (err) {
        alert('Error running simulation: ' + err.message);
    }
}

// 60-Scenario Benchmark Runner
async function runFullBenchmark() {
    const btn = document.getElementById('btn-benchmark');
    if (btn) {
        btn.disabled = true;
        btn.innerText = '⏳ Running 60 Scenarios...';
    }

    try {
        const res = await fetch('/api/v1/benchmark/run', { method: 'POST' });
        if (!res.ok) throw new Error('Benchmark failed');
        const result = await res.json();

        await fetchStats();
        await fetchDisputes();
        await fetchLedger();

        alert(`🎉 Benchmark Complete!\n\n• Scenarios: ${result.total_scenarios}\n• Autonomous Yield: ${result.autonomous_yield_percentage}%\n• Precision: ${result.precision_percentage}%\n• Avg Latency: ${result.average_latency_ms} ms\n• Ledger Integrity: ${result.ledger_integrity ? 'VALID' : 'FAILED'}`);
    } catch (err) {
        alert('Benchmark execution error: ' + err.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = '⚡ Run 60-Scenario Benchmark';
        }
    }
}

// Verify Ledger Integrity on demand
async function verifyLedgerOnDemand() {
    try {
        const res = await fetch('/api/v1/audit/integrity');
        const report = await res.json();
        if (report.is_valid) {
            alert(`✅ Cryptographic Hash Chain 100% Intact!\n\n• Total Blocks: ${report.total_blocks}\n• Genesis Hash: ${report.genesis_hash}\n• Latest Hash: ${report.latest_hash}\n• Verified At: ${report.verified_at}`);
        } else {
            alert(`❌ Integrity Violation Detected!\n\nDetails: ${report.discrepancy_details}`);
        }
    } catch (err) {
        alert('Error checking integrity: ' + err.message);
    }
}

// ----------------- HITL REMEDIATION MODAL -----------------
async function openRemediationModal(disputeId) {
    const modal = document.getElementById('remediation-modal');
    const container = document.getElementById('modal-remediation-body');
    if (!modal || !container) return;

    modal.classList.add('active');
    container.innerHTML = `
        <div style="text-align: center; padding: 30px; color: var(--text-muted);">
            ⏳ Fetching dispute context for remediation...
        </div>
    `;

    try {
        const res = await fetch(`/api/v1/disputes/${disputeId}`);
        if (!res.ok) throw new Error('Could not fetch dispute dossier');
        const d = await res.json();

        const gapsList = (d.evaluation.diagnostic_gaps || []).map(g => `<li>⚠️ ${g}</li>`).join('');

        container.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; border-bottom: 1px solid var(--border-color); padding-bottom: 12px;">
                <div>
                    <span class="mono-text" style="font-size: 14px; font-weight: 700; color: var(--accent-cyan);">${d.dispute_id}</span>
                    <span style="color: var(--text-muted); font-size: 12px; margin-left: 8px;">(${d.card_network.toUpperCase()} - Reason ${d.reason_code})</span>
                </div>
                <div style="text-align: right;">
                    <span style="font-size: 12px; color: var(--text-muted);">Current Score:</span>
                    <span style="font-size: 16px; font-weight: 800; color: var(--accent-amber); margin-left: 4px;">${d.confidence_score}/100</span>
                </div>
            </div>

            ${gapsList ? `
                <div style="background: rgba(245, 158, 11, 0.08); border: 1px solid rgba(245, 158, 11, 0.25); border-radius: 8px; padding: 12px; margin-bottom: 16px;">
                    <strong style="color: var(--accent-amber); font-size: 12px; display: block; margin-bottom: 6px;">Identified Evidence Gaps:</strong>
                    <ul style="margin: 0; padding-left: 18px; font-size: 11px; color: #fde68a; line-height: 1.6;">
                        ${gapsList}
                    </ul>
                </div>
            ` : ''}

            <form id="remediation-form" onsubmit="event.preventDefault(); submitRemediation('${d.dispute_id}')" style="display: flex; flex-direction: column; gap: 14px;">
                <div style="background: var(--bg-surface-2); padding: 14px; border-radius: 8px; border: 1px solid var(--border-color);">
                    <h4 style="font-size: 13px; color: var(--accent-cyan); margin-bottom: 10px;">📦 Carrier & Logistics Proof</h4>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                        <div>
                            <label style="font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 4px;">Carrier Name</label>
                            <input type="text" id="rem-carrier-name" class="search-input" value="${d.carrier_proof ? d.carrier_proof.carrier_name : 'BlueDart'}" style="width: 100%;">
                        </div>
                        <div>
                            <label style="font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 4px;">Tracking Number</label>
                            <input type="text" id="rem-tracking-no" class="search-input" value="${d.carrier_proof ? d.carrier_proof.tracking_number : 'BD' + Date.now().toString().slice(-8)}" style="width: 100%;">
                        </div>
                    </div>
                    <div style="margin-top: 10px; display: flex; gap: 20px; flex-wrap: wrap;">
                        <label style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-main); cursor: pointer;">
                            <input type="checkbox" id="rem-delivered" checked>
                            <span>Verified Physical Delivery (+35 pts)</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-main); cursor: pointer;">
                            <input type="checkbox" id="rem-gps" checked>
                            <span>Carrier GPS &le;50m Verified (+10 pts)</span>
                        </label>
                    </div>
                </div>

                <div style="background: var(--bg-surface-2); padding: 14px; border-radius: 8px; border: 1px solid var(--border-color);">
                    <h4 style="font-size: 13px; color: var(--accent-purple); margin-bottom: 10px;">🔐 Identity & Authentication Proof</h4>
                    <div style="display: flex; gap: 20px; flex-wrap: wrap;">
                        <label style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-main); cursor: pointer;">
                            <input type="checkbox" id="rem-mfa" checked>
                            <span>3DS / 2FA Verification Log (+5 pts)</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-main); cursor: pointer;">
                            <input type="checkbox" id="rem-digital-logs">
                            <span>SaaS / Server Access Logs Verified</span>
                        </label>
                    </div>
                </div>

                <div>
                    <label style="font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 4px;">Analyst Notes / Defense Rationale</label>
                    <textarea id="rem-notes" class="search-input" rows="2" style="width: 100%; resize: vertical;" placeholder="e.g. Uploaded signed BlueDart POD receipt and validated customer 3DS authentication telemetry."></textarea>
                </div>

                <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 10px;">
                    <button type="button" class="btn btn-secondary" onclick="closeRemediationModal()">Cancel</button>
                    <button type="submit" id="btn-submit-remediation" class="btn btn-primary" style="background: linear-gradient(135deg, #10b981, #059669); border-color: #10b981;">
                        ⚡ Re-evaluate & Auto-Dispatch &rarr;
                    </button>
                </div>
            </form>
        `;
    } catch (err) {
        container.innerHTML = `
            <div style="color: var(--accent-rose); padding: 20px;">
                ❌ Error loading dispute: ${err.message}
            </div>
        `;
    }
}

function closeRemediationModal() {
    const modal = document.getElementById('remediation-modal');
    if (modal) modal.classList.remove('active');
}

async function submitRemediation(disputeId) {
    const btn = document.getElementById('btn-submit-remediation');
    if (btn) {
        btn.disabled = true;
        btn.innerText = '⏳ Re-evaluating LangGraph Compliance Engine...';
    }

    const payload = {
        analyst_id: 'ANALYST_AGENT_01',
        analyst_notes: document.getElementById('rem-notes').value || 'Analyst verified documentary proof',
        carrier_name: document.getElementById('rem-carrier-name').value,
        tracking_number: document.getElementById('rem-tracking-no').value,
        delivered_status: document.getElementById('rem-delivered').checked,
        recipient_signature_present: true,
        verified_gps: document.getElementById('rem-gps').checked,
        gps_latitude: 12.9716,
        gps_longitude: 77.5946,
        mfa_authenticated: document.getElementById('rem-mfa').checked,
        digital_access_logs_verified: document.getElementById('rem-digital-logs').checked ? true : null
    };

    try {
        const res = await fetch(`/api/v1/disputes/${disputeId}/remediate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Remediation failed');
        }

        const updatedDossier = await res.json();
        closeRemediationModal();

        await fetchStats();
        await fetchDisputes();
        await fetchLedger();

        alert(`🎉 Remediation Successful!\n\n• Dispute ID: ${updatedDossier.dispute_id}\n• New Confidence Score: ${updatedDossier.confidence_score}/100.0\n• Decision: ${updatedDossier.decision}\n• SHA-256 Seal: ${updatedDossier.sealed_hash.substring(0, 16)}...\n\nPromoted to Auto-Dispatched & defense dispatched to card network!`);

        viewDossier(updatedDossier.dispute_id);
    } catch (err) {
        alert('Remediation error: ' + err.message);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = '⚡ Re-evaluate & Auto-Dispatch →';
        }
    }
}

