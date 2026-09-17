(function () {
  'use strict';
  var tableBody   = document.getElementById('attendance-table-body');
  var errorBanner = document.getElementById('live-feed-error');
  var updatedText = document.getElementById('updated-text');
  var POLL_MS     = 3000;
  var TIMEOUT_MS  = 5000;

  function initial(name) {
    return (name && name.length > 0) ? name[0].toUpperCase() : '?';
  }

  function esc(str) {
    if (str == null) return '';
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function statusBadge(status) {
    var map = {
      present: ['status-present', '&#9679; Present'],
      late:    ['status-late',    '&#9680; Late'],
      absent:  ['status-absent',  '&#9675; Absent'],
      manual:  ['status-manual',  '&#9998; Manual'],
    };
    var pair = map[status] || ['', esc(status) || '&mdash;'];
    return '<span class="status-badge ' + pair[0] + '">' + pair[1] + '</span>';
  }

  function confBar(conf) {
    if (conf == null) return '&mdash;';
    var pct = Math.min(100, Math.max(0, parseFloat(conf)));
    return '<div class="conf-bar-wrap">'
      + '<div class="conf-bar"><div class="conf-bar-fill" style="width:' + pct + '%"></div></div>'
      + '<span class="conf-text">' + pct.toFixed(1) + '%</span>'
      + '</div>';
  }

  function renderRows(faces) {
    if (!faces || faces.length === 0) {
      return '<tr><td colspan="6"><div class="empty-state">'
        + '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="margin:0 auto 1rem;opacity:0.35"><path d="M22 13V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v12c0 1.1.9 2 2 2h8"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/><path d="M16 19h6"/><path d="M19 16v6"/></svg>'
        + '<h3>No attendance records yet today</h3>'
        + '<p style="font-size:0.85rem;color:var(--color-muted)">Records appear as faces are recognized at the kiosk.</p>'
        + '</div></td></tr>';
    }
    return faces.map(function(r) {
      var name = esc(r.full_name || 'Unknown');
      var init = initial(r.full_name);
      return '<tr>'
        + '<td><div class="name-cell">'
        +   '<div class="name-avatar">' + init + '</div>'
        +   '<div><div class="name-text">' + name + '</div>'
        +   '<div class="name-sub">' + esc(r.id_number) + '</div></div>'
        + '</div></td>'
        + '<td style="display:none">' + esc(r.id_number) + '</td>'
        + '<td>' + (esc(r.time_in)  || '&mdash;') + '</td>'
        + '<td>' + (esc(r.time_out) || '&mdash;') + '</td>'
        + '<td>' + statusBadge(r.status) + '</td>'
        + '<td>' + confBar(r.confidence) + '</td>'
        + '</tr>';
    }).join('');
  }

  function fetchLiveFeed() {
    var ctrl = new AbortController();
    var tid  = setTimeout(function() { ctrl.abort(); }, TIMEOUT_MS);
    fetch('/api/live-feed', { signal: ctrl.signal })
      .then(function(res) { return res.json(); })
      .then(function(data) {
        clearTimeout(tid);
        var rows = data.faces || data.records || [];
        tableBody.innerHTML = renderRows(rows);
        if (typeof lucide !== 'undefined') lucide.createIcons();
        if (errorBanner) errorBanner.style.display = 'none';
        if (updatedText) updatedText.textContent = 'Updated ' + new Date().toLocaleTimeString();
      })
      .catch(function() {
        clearTimeout(tid);
        if (errorBanner) errorBanner.style.display = '';
      });
  }

  fetchLiveFeed();
  setInterval(fetchLiveFeed, POLL_MS);
})();