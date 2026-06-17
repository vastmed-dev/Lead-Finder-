let OPTIONS = null;
let leadPageState = { page: 1, pages: 1, per_page: 25, filters: {} };
let leadModal = null;
let currentLead = null;

function showToast(message) {
  const toastEl = document.getElementById('mainToast');
  const body = document.getElementById('toastBody');
  if (body) body.textContent = message;
  if (toastEl && window.bootstrap) new bootstrap.Toast(toastEl).show();
}

async function getJSON(url, options = {}) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || 'Request failed');
  return data;
}

function qs(params) {
  const urlParams = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') urlParams.set(k, v);
  });
  return urlParams.toString();
}

function escapeHtml(str) {
  return String(str ?? '').replace(/[&<>'"]/g, tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag]));
}

function toDatetimeLocal(value) {
  if (!value) return '';
  const normalized = String(value).replace(' ', 'T').slice(0, 16);
  return normalized.length >= 16 ? normalized : '';
}

function fromDatetimeLocal(value) {
  if (!value) return '';
  return value.replace('T', ' ') + ':00';
}

function badgeClass(value, type = '') {
  if (type === 'quality') {
    if (value === 'High') return 'text-bg-danger';
    if (value === 'Medium') return 'text-bg-warning';
    return 'text-bg-secondary';
  }
  if (type === 'phone' || type === 'email') {
    if (['Valid', 'Found'].includes(value)) return 'text-bg-success';
    if (['Invalid', 'Unavailable'].includes(value)) return 'text-bg-danger';
    return 'text-bg-secondary';
  }
  if (type === 'website') {
    if (value === 'Good Website') return 'text-bg-success';
    if (value === 'Needs Redesign') return 'text-bg-warning';
    if (value === 'Unavailable') return 'text-bg-danger';
    if (value === 'No Website') return 'text-bg-dark';
    return 'text-bg-secondary';
  }
  if (type === 'status') {
    if (['Converted', 'Interested', 'Replied'].includes(value)) return 'text-bg-success';
    if (['Follow Up Needed', 'Call Attempted', 'Message Sent'].includes(value)) return 'text-bg-primary';
    if (['Lost', 'Not Interested'].includes(value)) return 'text-bg-secondary';
    return 'text-bg-light text-dark border';
  }
  return 'text-bg-secondary';
}

function scoreClass(q) {
  if (q === 'High') return 'score-high';
  if (q === 'Medium') return 'score-medium';
  return 'score-low';
}

function selectOptions(items, selected = '', includeAll = true, allLabel = 'All') {
  const first = includeAll ? `<option value="">${allLabel}</option>` : '';
  const cleaned = includeAll ? (items || []).filter(v => v !== '') : (items || []);
  return first + cleaned.map(v => `<option value="${escapeHtml(v)}" ${String(selected) === String(v) ? 'selected' : ''}>${escapeHtml(v || 'None')}</option>`).join('');
}

function campaignOptions(campaigns, selected = '', includeAll = true) {
  const first = includeAll ? '<option value="">All Campaigns</option>' : '<option value="">No Campaign</option>';
  return first + (campaigns || []).map(c => `<option value="${c.id}" ${String(selected || '') === String(c.id) ? 'selected' : ''}>${escapeHtml(c.name)}</option>`).join('');
}

async function loadOptions(force = false) {
  if (!OPTIONS || force) OPTIONS = await getJSON('/api/options');
  return OPTIONS;
}

async function loadStats() {
  const s = await getJSON('/api/stats');
  const map = {
    statTotal: s.total,
    statNoWebsite: s.no_website,
    statWithPhone: s.with_phone,
    statWithEmail: s.with_email,
    statHotLeads: s.hot_leads,
    statInterested: s.interested,
    statNew: s.new,
    statContacted: s.contacted,
    statFollowUp: s.follow_up,
    statBadWebsites: s.bad_websites,
    statNoSocial: s.no_social,
    statConversionRate: s.conversion_rate,
  };
  Object.entries(map).forEach(([id, value]) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value ?? 0;
  });
  renderBars('statusChart', s.by_status || []);
  renderBars('cityChart', s.by_city || []);
  renderBars('categoryChart', s.by_category || []);
  renderBars('websiteStatusChart', s.by_website_status || []);
  renderBars('offerChart', s.by_offer || []);
}

function renderBars(id, rows) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!rows.length) {
    el.innerHTML = '<div class="text-muted small">No data yet.</div>';
    return;
  }
  const max = Math.max(...rows.map(r => Number(r.value) || 0), 1);
  el.innerHTML = rows.map(r => {
    const width = Math.max(5, Math.round(((Number(r.value) || 0) / max) * 100));
    return `<div class="bar-row"><div class="bar-label">${escapeHtml(r.label || 'Unknown')}</div><div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div><div class="bar-value">${escapeHtml(r.value)}</div></div>`;
  }).join('');
}

async function renderPresets() {
  const data = await getJSON('/api/presets');
  const catWrap = document.getElementById('categoryPresets');
  const cityWrap = document.getElementById('cityPresets');
  if (catWrap) catWrap.innerHTML = data.categories.map(c => `<button type="button" class="preset-chip" data-target="businessTypeInput">${escapeHtml(c)}</button>`).join('');
  if (cityWrap) cityWrap.innerHTML = data.cities.map(c => `<button type="button" class="preset-chip" data-target="cityInput">${escapeHtml(c)}</button>`).join('');
  document.querySelectorAll('.preset-chip').forEach(btn => btn.addEventListener('click', () => {
    const target = document.getElementById(btn.dataset.target);
    if (target) target.value = btn.textContent.trim();
  }));
}

async function loadSearchHistory() {
  const wrap = document.getElementById('searchHistory');
  if (!wrap) return;
  const data = await getJSON('/api/search-history?limit=8');
  if (!data.items.length) {
    wrap.innerHTML = '<div class="text-muted small">No searches yet.</div>';
    return;
  }
  wrap.innerHTML = data.items.map(item => `<div class="history-item"><div><strong>${escapeHtml(item.business_type)} in ${escapeHtml(item.city)}</strong><small>${escapeHtml(item.created_at || '')}</small></div><div class="text-end"><span class="badge ${item.status === 'completed' ? 'text-bg-success' : item.status === 'failed' ? 'text-bg-danger' : 'text-bg-primary'}">${escapeHtml(item.status)}</span><small>${Number(item.saved_count || 0)} saved</small></div></div>`).join('');
}

async function fillSearchCampaigns() {
  const opt = await loadOptions();
  const select = document.getElementById('searchCampaign');
  if (select) select.innerHTML = campaignOptions(opt.campaigns, '', false);
}

function initDashboard() {
  loadStats();
  renderPresets();
  loadSearchHistory();
  fillSearchCampaigns();
  const form = document.getElementById('scrapeForm');
  const log = document.getElementById('progressLog');
  const bar = document.getElementById('jobProgressBar');
  const badge = document.getElementById('jobStatusBadge');
  if (!form) return;

  let lastMessage = '';
  function addLog(message) {
    if (!message || message === lastMessage) return;
    lastMessage = message;
    const row = document.createElement('div');
    row.className = 'log-row';
    row.innerHTML = `<span class="log-time">${new Date().toLocaleTimeString()}</span>${escapeHtml(message)}`;
    if (log.querySelector('.text-muted')) log.innerHTML = '';
    log.prepend(row);
  }
  function setProgress(job) {
    const total = job.total || 1;
    const current = job.current || 0;
    const percent = job.status === 'completed' ? 100 : Math.min(100, Math.round((current / total) * 100));
    bar.style.width = `${percent}%`;
    bar.textContent = `${percent}%`;
    badge.textContent = job.status || 'Running';
    badge.className = 'badge ' + (job.status === 'completed' ? 'text-bg-success' : job.status === 'failed' ? 'text-bg-danger' : 'text-bg-primary');
  }
  async function pollJob(jobId) {
    const timer = setInterval(async () => {
      try {
        const job = await getJSON(`/api/scrape/job/${jobId}`);
        setProgress(job);
        addLog(job.message);
        if (['completed', 'failed'].includes(job.status)) {
          clearInterval(timer);
          loadStats();
          loadSearchHistory();
          showToast(job.message || 'Job finished');
        }
      } catch (e) {
        clearInterval(timer);
        showToast(e.message);
      }
    }, 1500);
  }
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const payload = {
      business_type: fd.get('business_type'),
      city: fd.get('city'),
      max_results: fd.get('max_results'),
      campaign_id: fd.get('campaign_id'),
      only_no_website: fd.get('only_no_website') === 'on',
      only_with_phone: fd.get('only_with_phone') === 'on',
      auto_audit: fd.get('auto_audit') === 'on',
    };
    try {
      addLog('Search queued...');
      const data = await getJSON('/api/scrape/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      pollJob(data.job_id);
    } catch (err) {
      showToast(err.message);
    }
  });
}

function readUrlFilters() {
  const p = new URLSearchParams(window.location.search);
  const f = {};
  for (const [k, v] of p.entries()) f[k] = v;
  return f;
}

async function setupLeadFilters() {
  const opt = await loadOptions();
  document.getElementById('filterCity').innerHTML = selectOptions(opt.cities, leadPageState.filters.city);
  document.getElementById('filterCategory').innerHTML = selectOptions(opt.categories, leadPageState.filters.category);
  document.getElementById('filterStatus').innerHTML = selectOptions(opt.statuses, leadPageState.filters.status);
  document.getElementById('filterWebsiteStatus').innerHTML = selectOptions(opt.website_statuses, leadPageState.filters.website_status);
  document.getElementById('filterQuality').innerHTML = selectOptions(opt.lead_qualities, leadPageState.filters.lead_quality);
  document.getElementById('filterPhone').innerHTML = selectOptions(opt.phone_statuses, leadPageState.filters.phone_status);
  document.getElementById('filterEmail').innerHTML = selectOptions(opt.email_statuses, leadPageState.filters.email_status);
  document.getElementById('filterOffer').innerHTML = selectOptions(opt.suggested_offers, leadPageState.filters.suggested_offer);
  document.getElementById('filterCampaign').innerHTML = campaignOptions(opt.campaigns, leadPageState.filters.campaign_id);
  document.getElementById('filterQ').value = leadPageState.filters.q || '';
}

function collectLeadFilters() {
  return {
    q: document.getElementById('filterQ')?.value || '',
    city: document.getElementById('filterCity')?.value || '',
    category: document.getElementById('filterCategory')?.value || '',
    status: document.getElementById('filterStatus')?.value || '',
    website_status: document.getElementById('filterWebsiteStatus')?.value || '',
    lead_quality: document.getElementById('filterQuality')?.value || '',
    phone_status: document.getElementById('filterPhone')?.value || '',
    email_status: document.getElementById('filterEmail')?.value || '',
    suggested_offer: document.getElementById('filterOffer')?.value || '',
    campaign_id: document.getElementById('filterCampaign')?.value || '',
    hot: leadPageState.filters.hot || '',
  };
}

function updateExportLinks() {
  const query = qs(leadPageState.filters);
  const x = document.getElementById('exportExcel');
  const c = document.getElementById('exportCsv');
  if (x) x.href = '/export/excel' + (query ? '?' + query : '');
  if (c) c.href = '/export/csv' + (query ? '?' + query : '');
}

async function loadLeads() {
  const params = { ...leadPageState.filters, page: leadPageState.page, per_page: leadPageState.per_page };
  const data = await getJSON('/api/leads?' + qs(params));
  leadPageState.pages = data.pages;
  const body = document.getElementById('leadsTableBody');
  const count = document.getElementById('leadCountText');
  const pageInfo = document.getElementById('pageInfo');
  if (count) count.textContent = `${data.total} leads`;
  if (pageInfo) pageInfo.textContent = `Page ${data.page} of ${data.pages}`;
  if (!data.items.length) {
    body.innerHTML = '<tr><td colspan="6" class="text-center text-muted p-5">No leads found.</td></tr>';
    return;
  }
  body.innerHTML = data.items.map(lead => {
    const websiteText = lead.website ? `<a href="${escapeHtml(lead.website)}" target="_blank">Open site</a>` : 'No website';
    const socials = ['facebook_url','instagram_url','linkedin_url','tiktok_url','youtube_url'].filter(k => lead[k]).length;
    return `<tr>
      <td><div class="business-title">${escapeHtml(lead.business_name)}</div><div class="business-address">${escapeHtml(lead.address || '')}</div><div class="small text-muted">${escapeHtml(lead.category || '')} · ${escapeHtml(lead.city || '')}</div><div class="small">${lead.campaign_name ? '<span class="badge text-bg-light border">' + escapeHtml(lead.campaign_name) + '</span>' : ''}</div></td>
      <td><div>${escapeHtml(lead.phone || '')} <span class="badge ${badgeClass(lead.phone_status, 'phone')}">${escapeHtml(lead.phone_status || '')}</span></div><div>${escapeHtml(lead.email || '')} ${lead.email_status ? '<span class="badge ' + badgeClass(lead.email_status, 'email') + '">' + escapeHtml(lead.email_status) + '</span>' : ''}</div><div class="small text-muted">Social links: ${socials}</div></td>
      <td><div>${websiteText}</div><span class="badge ${badgeClass(lead.website_status, 'website')}">${escapeHtml(lead.website_status || 'Unchecked')}</span><div class="small text-muted mt-1">Quality: ${Number(lead.website_quality_score || 0)}/100</div><div class="small text-muted truncate-220">${escapeHtml(lead.website_issues || '')}</div></td>
      <td><div class="score-badge ${scoreClass(lead.lead_quality)}">${Number(lead.lead_score || 0)}</div><span class="badge ${badgeClass(lead.lead_quality, 'quality')}">${escapeHtml(lead.lead_quality || '')}</span><div class="small text-muted">${escapeHtml(lead.suggested_offer || '')}</div></td>
      <td><span class="badge ${badgeClass(lead.status, 'status')}">${escapeHtml(lead.status || '')}</span><div class="small text-muted mt-1">Priority: ${escapeHtml(lead.priority || '')}</div><div class="small text-muted">Next: ${escapeHtml(lead.next_follow_up_at || '-')}</div></td>
      <td class="action-cell"><button class="btn btn-sm btn-primary" onclick="openLead(${lead.id})">Open</button> <button class="btn btn-sm btn-outline-primary" onclick="quickAudit(${lead.id})">Audit</button> <button class="btn btn-sm btn-outline-danger" onclick="deleteLead(${lead.id})">Delete</button></td>
    </tr>`;
  }).join('');
  updateExportLinks();
}

async function quickAudit(id) {
  try {
    showToast('Website audit started...');
    const data = await getJSON(`/api/leads/${id}/audit`, { method: 'POST' });
    showToast(`Audit complete: ${data.audit.website_status}`);
    loadLeads();
    if (currentLead && currentLead.id === id) openLead(id);
  } catch (e) { showToast(e.message); }
}

async function deleteLead(id) {
  if (!confirm('Delete this lead?')) return;
  await getJSON(`/api/leads/${id}`, { method: 'DELETE' });
  showToast('Lead deleted');
  loadLeads();
}

function renderTimeline(items) {
  const box = document.getElementById('activityTimeline');
  if (!box) return;
  if (!items || !items.length) {
    box.innerHTML = '<div class="text-muted small">No activity yet.</div>';
    return;
  }
  box.innerHTML = items.map(a => `<div class="timeline-item"><strong>${escapeHtml(a.activity_type || 'Note')}</strong><small>${escapeHtml(a.created_at || '')}</small><p>${escapeHtml(a.note || '')}</p></div>`).join('');
}

async function openLead(id) {
  const opt = await loadOptions();
  currentLead = await getJSON(`/api/leads/${id}`);
  document.getElementById('modalLeadId').value = currentLead.id;
  document.getElementById('modalLeadTitle').textContent = currentLead.business_name || 'Lead Detail';
  document.getElementById('modalLeadSubtitle').textContent = `${currentLead.category || ''} · ${currentLead.city || ''}`;
  document.getElementById('modalPhone').textContent = `${currentLead.phone || '-'} (${currentLead.phone_status || ''})`;
  document.getElementById('modalEmail').textContent = `${currentLead.email || '-'} (${currentLead.email_status || ''})`;
  document.getElementById('modalScore').textContent = `${currentLead.lead_score || 0}/100 · ${currentLead.lead_quality || ''}`;
  document.getElementById('modalOfferView').textContent = currentLead.suggested_offer || '';
  document.getElementById('modalWebsite').innerHTML = currentLead.website ? `<a href="${escapeHtml(currentLead.website)}" target="_blank">${escapeHtml(currentLead.website)}</a>` : 'No website';
  document.getElementById('modalMap').innerHTML = currentLead.google_map_link ? `<a href="${escapeHtml(currentLead.google_map_link)}" target="_blank">Open Google Maps</a>` : '-';
  document.getElementById('modalAddress').textContent = currentLead.address || '-';
  document.getElementById('modalIssues').textContent = currentLead.website_issues || '-';
  document.getElementById('modalDomains').textContent = currentLead.domain_suggestions || '-';
  document.getElementById('modalStatus').innerHTML = selectOptions(opt.statuses, currentLead.status, false);
  document.getElementById('modalContactMethod').innerHTML = selectOptions(opt.contact_methods, currentLead.contact_method, false);
  document.getElementById('modalPriority').innerHTML = selectOptions(opt.priorities, currentLead.priority, false);
  document.getElementById('modalCampaign').innerHTML = campaignOptions(opt.campaigns, currentLead.campaign_id, false);
  document.getElementById('modalOffer').innerHTML = selectOptions(opt.suggested_offers, currentLead.suggested_offer, false);
  document.getElementById('modalAssignedTo').value = currentLead.assigned_to || '';
  document.getElementById('modalLastContacted').value = toDatetimeLocal(currentLead.last_contacted_at);
  document.getElementById('modalNextFollowUp').value = toDatetimeLocal(currentLead.next_follow_up_at);
  document.getElementById('modalNotes').value = currentLead.notes || '';
  document.getElementById('modalEmailInput').value = currentLead.email || '';
  document.getElementById('modalWebsiteInput').value = currentLead.website || '';
  document.getElementById('proposalBtn').href = `/export/proposal/${currentLead.id}`;
  renderTimeline(currentLead.activities || []);
  try {
    const wa = await getJSON(`/api/whatsapp/${id}`);
    document.getElementById('whatsappPreview').textContent = wa.message || '';
    document.getElementById('whatsappLink').href = wa.url || '#';
  } catch (_) {}
  leadModal = leadModal || new bootstrap.Modal(document.getElementById('leadModal'));
  leadModal.show();
}

async function saveModalLead() {
  const id = document.getElementById('modalLeadId').value;
  const payload = {
    status: document.getElementById('modalStatus').value,
    contact_method: document.getElementById('modalContactMethod').value,
    priority: document.getElementById('modalPriority').value,
    campaign_id: document.getElementById('modalCampaign').value,
    suggested_offer: document.getElementById('modalOffer').value,
    assigned_to: document.getElementById('modalAssignedTo').value,
    last_contacted_at: fromDatetimeLocal(document.getElementById('modalLastContacted').value),
    next_follow_up_at: fromDatetimeLocal(document.getElementById('modalNextFollowUp').value),
    notes: document.getElementById('modalNotes').value,
    email: document.getElementById('modalEmailInput').value,
    website: document.getElementById('modalWebsiteInput').value,
  };
  await getJSON(`/api/leads/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  showToast('Lead saved');
  await openLead(Number(id));
  loadLeads();
}

async function addModalActivity() {
  const id = document.getElementById('modalLeadId').value;
  const note = document.getElementById('activityNote').value.trim();
  if (!note) return showToast('Please add note first');
  const data = await getJSON(`/api/leads/${id}/activities`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ activity_type: 'Note', note }) });
  document.getElementById('activityNote').value = '';
  renderTimeline(data.items);
  showToast('Activity note added');
}

function initLeadsPage() {
  leadPageState.filters = readUrlFilters();
  setupLeadFilters().then(loadLeads);
  document.getElementById('applyFilters')?.addEventListener('click', () => { leadPageState.page = 1; leadPageState.filters = collectLeadFilters(); loadLeads(); });
  document.getElementById('resetFilters')?.addEventListener('click', () => { leadPageState.filters = {}; leadPageState.page = 1; setupLeadFilters().then(loadLeads); });
  document.getElementById('hotOnly')?.addEventListener('click', () => { leadPageState.filters = collectLeadFilters(); leadPageState.filters.hot = '1'; leadPageState.page = 1; loadLeads(); });
  document.getElementById('prevPage')?.addEventListener('click', () => { if (leadPageState.page > 1) { leadPageState.page--; loadLeads(); } });
  document.getElementById('nextPage')?.addEventListener('click', () => { if (leadPageState.page < leadPageState.pages) { leadPageState.page++; loadLeads(); } });
  document.getElementById('saveLeadBtn')?.addEventListener('click', saveModalLead);
  document.getElementById('auditLeadBtn')?.addEventListener('click', () => quickAudit(Number(document.getElementById('modalLeadId').value)));
  document.getElementById('addActivityBtn')?.addEventListener('click', addModalActivity);
}

async function initFollowupsPage() {
  const body = document.getElementById('followupsBody');
  const data = await getJSON('/api/leads?due_follow_up=1&per_page=100');
  if (!data.items.length) {
    body.innerHTML = '<tr><td colspan="5" class="text-center text-muted p-5">No follow-ups due today.</td></tr>';
    return;
  }
  body.innerHTML = data.items.map(l => `<tr><td><div class="business-title">${escapeHtml(l.business_name)}</div><div class="business-address">${escapeHtml(l.address || '')}</div></td><td>${escapeHtml(l.phone || '')}<br><span class="small text-muted">${escapeHtml(l.email || '')}</span></td><td>${escapeHtml(l.next_follow_up_at || '')}</td><td><span class="badge ${badgeClass(l.status, 'status')}">${escapeHtml(l.status || '')}</span></td><td><a class="btn btn-sm btn-primary" href="/leads?q=${encodeURIComponent(l.business_name || '')}">Open</a></td></tr>`).join('');
}

async function loadCampaigns() {
  const data = await getJSON('/api/campaigns');
  const body = document.getElementById('campaignsBody');
  if (!body) return;
  if (!data.items.length) {
    body.innerHTML = '<tr><td colspan="6" class="text-center text-muted p-5">No campaigns yet.</td></tr>';
    return;
  }
  body.innerHTML = data.items.map(c => `<tr><td><strong>${escapeHtml(c.name)}</strong><div class="small text-muted">${escapeHtml(c.category || '')} · ${escapeHtml(c.city || '')}</div></td><td>${c.total_leads || 0}</td><td>${c.contacted || 0}</td><td>${c.interested || 0}</td><td>${c.converted || 0}</td><td><a class="btn btn-sm btn-outline-primary" href="/leads?campaign_id=${c.id}">View Leads</a> <button class="btn btn-sm btn-outline-danger" onclick="deleteCampaign(${c.id})">Delete</button></td></tr>`).join('');
}

async function deleteCampaign(id) {
  if (!confirm('Delete campaign? Leads will not be deleted.')) return;
  await getJSON(`/api/campaigns/${id}`, { method: 'DELETE' });
  showToast('Campaign deleted');
  loadCampaigns();
}

function initCampaignsPage() {
  loadCampaigns();
  const form = document.getElementById('campaignForm');
  form?.addEventListener('submit', async e => {
    e.preventDefault();
    const fd = new FormData(form);
    const payload = Object.fromEntries(fd.entries());
    await getJSON('/api/campaigns', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    form.reset();
    showToast('Campaign created');
    loadCampaigns();
  });
}

function initReportsPage() {
  loadStats();
}
