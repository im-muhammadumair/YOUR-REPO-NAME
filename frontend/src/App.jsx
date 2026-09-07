import React, { useState, useEffect, useRef } from 'react';
import './App.css';
import { API, AuthAPI, NetworkError, AuthError, RateLimitError, SessionExpiredError } from './api';
import { FaCalendarCheck, FaCalendar, FaMoneyBillWave, FaFolder, FaConciergeBell, FaShieldAlt, FaKey, FaCopy, FaBell, FaFileAlt, FaSearch, FaTimes, FaArrowLeft, FaUser, FaUsers, FaPlus, FaEyeSlash, FaEye, FaPencilAlt, FaTrashAlt, FaStar, FaBuilding, FaGlobe } from 'react-icons/fa';

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

const OPTIONS = [
    { id: 'attendance', title: 'Check Attendance', desc: 'Today, week or a date range', icon: <FaCalendarCheck />, svgPath: 'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z' },
    { id: 'leaves', title: 'Check Leaves', desc: 'View balance & history', icon: <FaCalendar />, svgPath: 'M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z' },
    { id: 'salary', title: 'Check Salary', desc: 'Detailed salary breakdown & payslips', icon: <FaMoneyBillWave />, svgPath: 'M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z' },
    { id: 'documents', title: 'Find Documents', desc: 'Access company documents', icon: <FaFolder />, svgPath: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
    { id: 'services', title: 'People & Services', desc: 'Browse people and support teams', icon: <FaConciergeBell />, svgPath: 'M3 8l9 6 9-6M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' },
];

const ADMIN_OPTION = { id: 'admin', title: 'Admin: Employee Details', desc: 'Select an employee to view their full records', icon: <FaShieldAlt />, svgPath: 'M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z', adminOnly: true };

const MANAGE_ACCOUNTS_OPTION = { id: 'manageAccounts', title: 'Admin: Manage Accounts', desc: 'View, add & edit login accounts', icon: <FaKey />, svgPath: 'M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z', adminOnly: true };

const MANAGE_DOCUMENTS_OPTION = { id: 'manageDocuments', title: 'Admin: Manage Documents', desc: 'Add, upload & remove company documents', icon: <FaCopy />, svgPath: 'M4 7h16M4 7a2 2 0 00-2 2v10a2 2 0 002 2h16a2 2 0 002-2V9a2 2 0 00-2-2M4 7V5a2 2 0 012-2h8l4 4h-2M9 12h6m-6 4h6', adminOnly: true };

// Options that open the live search / browse explorer
const EXPLORER_OPTIONS = new Set(['services', 'documents']);

function buildSubOptions(id, me, accountType) {
    const year = 2026;
    switch (id) {
        case 'attendance':
            return [
                { label: 'Today', value: 'today', action: 'attendanceToday' },
                { label: 'This Week', value: 'week', action: 'attendanceWeek' },
                { label: 'Last Week', value: 'lastWeek', action: 'attendanceWeek' },
                { label: 'Custom Range —', value: 'custom', action: 'attendanceCustom' },
            ];
        case 'leaves':
            return [
                { label: 'My Leave Balance', value: null, action: 'leavesBalance' },
                ...MONTHS.map((m, i) => ({ label: `Leave History — ${m}`, value: { year, month: i + 1 }, action: 'leavesHistory' })),
            ];
        case 'salary':
            return [
                { label: 'My Salary Breakdown', value: null, action: 'salaryDetail' },
                ...MONTHS.map((m, i) => ({ label: `Payslip — ${m}`, value: { year, month: i + 1 }, action: 'salaryPayslip' })),
            ];
        default:
            return [];
    }
}

// Convert a JS Date to YYYY-MM-DD
function toISO(d) {
    const y = d.getFullYear();
    const m = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    return `${y}-${m}-${dd}`;
}

// Monday of the week containing `d`
function weekStart(d) {
    const day = (d.getDay() + 6) % 7; // 0 = Monday
    const s = new Date(d);
    s.setDate(s.getDate() - day);
    return s;
}
function addDays(d, n) {
    const r = new Date(d);
    r.setDate(r.getDate() + n);
    return r;
}

function escapeXml(s) {
    return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Safely render lightweight markdown (headings, bold, italic, inline code,
// fenced code blocks, lists, tables, links) into HTML for AI chat bubbles.
//
// Security: the input is HTML-escaped FIRST (escapeXml), so no raw HTML or
// model/prompt-injected markup can reach the DOM. The parser only ever emits
// tags from a fixed allow-list we construct ourselves. Links are restricted to
// http/https.
function renderInlineMarkdown(s) {
    return s
        // bold **text**
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        // italic *text*  (not inside words)
        .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>')
        // inline code `code`
        .replace(/`([^`\n]+)`/g, '<code>$1</code>')
        // links [text](http...)
        .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

function renderMarkdownTable(lines) {
    // Group consecutive lines that start/contain '|' into tables.
    const out = [];
    let table = [];
    const flushTable = () => {
        if (!table.length) return;
        const rows = [];
        let headerWidth = 0;
        table.forEach((line, i) => {
            let cells = line.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
            // Drop junk placeholder cells (Col1/Col3/...), empty cells and
            // trailing empty leftovers so the table never shows phantom columns.
            cells = cells
                .map(c => c.replace(/\*\*/g, '').trim())
                .filter(c => c && !/^Col\d+$/i.test(c));
            // Skip the markdown alignment separator row (---, :--: etc.)
            if (cells.length && cells.every(c => /^:?-{2,}:?$/.test(c))) return;
            // Snap jagged rows to the header width (pad or drop extras).
            if (i === 0) headerWidth = cells.length;
            if (headerWidth > 0 && cells.length < headerWidth) {
                cells = cells.concat(Array(headerWidth - cells.length).fill(''));
            } else if (headerWidth > 0) {
                cells = cells.slice(0, headerWidth);
            }
            const tag = i === 0 ? 'th' : 'td';
            rows.push(`<tr>${cells.map(c => `<${tag}>${renderInlineMarkdown(escapeInlineForCell(c))}</${tag}>`).join('')}</tr>`);
        });
        if (rows.length) out.push(`<div class="md-table"><table><thead>${rows.shift()}</thead><tbody>${rows.join('')}</tbody></table></div>`);
        table = [];
    };
    lines.forEach(line => {
        if (line.includes('|')) table.push(line);
        else { flushTable(); out.push(line && line.length ? line : ''); }
    });
    flushTable();
    return out;
}

const escapeInlineForCell = (c) => c; // cells already escaped

function renderMarkdown(text) {
    const src = escapeXml(String(text ?? ''));
    // --- fenced code blocks (preserve verbatim) ---
    let codeBlocks = [];
    const noBlocks = src.replace(/```[\s\S]*?```/g, (m) => {
        const inner = m.replace(/^```[^\n]*\n/, '').replace(/\n?```$/, '').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
        const idx = codeBlocks.length;
        codeBlocks.push(`<pre class="md-code"><code>${escapeXml(inner)}</code></pre>`);
        return `\u0000CODE${idx}\u0000`;
    }).replace(
        // Split a numbered point glued onto the tail of the previous line
        // (e.g. "...page 3).4. Support for Management Direction:") onto its own
        // line so it never merges with the preceding point. Only triggers when
        // the marker directly follows punctuation (").", ":", "]"), never
        // inside words, decimals, or after a normal space.
        /(?<=[^\s\w])\d{1,2}\.(?:\s*\*\*|\s+)/g,
        m => `\n${m}`
    );

    // split into blocks by blank lines
    const blocks = noBlocks.split(/\n{2,}/);
    const html = blocks.map((block) => {
        const lines = block.split('\n');

        // table: a pipe table anywhere in the block wins (kept as dark-table HTML)
        const tableOut = renderMarkdownTable(lines);
        if (tableOut.filter(x => x && x.includes('<table')).length) return tableOut.filter(Boolean).join('\n');

        // Line-based block renderer: headings, lists and paragraphs are each
        // detected on their own line, so a list that starts mid-block (or after
        // a bold intro line) is still rendered as a proper <ol>/<ul> and items
        // never get glued together.
        const isCodeLine = (l) => /^\u0000CODE(\d+)\u0000$/.test(l.trim());
        const isBullet = (l) => /^\s*[-*]\s+/.test(l);
        const isItem = (l) => /^\s*\d+[.)]\s+/.test(l) || isBullet(l);
        const isHeading = (l) => /^(#{1,4})\s+(.+)$/.test(l.trim());

        const out = [];
        let i = 0;
        while (i < lines.length) {
            const line = lines[i];
            const t = line.trim();

            if (!t) { i++; continue; }

            // fenced code placeholder
            const codeM = t.match(/^\u0000CODE(\d+)\u0000$/);
            if (codeM) { out.push(codeBlocks[Number(codeM[1])]); i++; continue; }

            // heading
            const h = t.match(/^(#{1,4})\s+(.+)$/);
            if (h) {
                const level = Math.min(h[1].length + 2, 5);
                out.push(`<h${level}>${renderInlineMarkdown(h[2].trim())}</h${level}>`);
                i++;
                continue;
            }

            // bulleted list — consecutive marker lines group; a wrap line joins
            // the previous item so long points never split.
            if (isBullet(t)) {
                const items = [];
                while (i < lines.length) {
                    const tl = lines[i].trim();
                    if (!tl) break;
                    if (isBullet(tl)) { items.push(tl.replace(/^\s*[-*]\s+/, '').trim()); i++; continue; }
                    if (isItem(tl)) break;      // next ordered/bullet item
                    items[items.length - 1] += ' ' + tl; // wrapped continuation
                    i++;
                }
                out.push(`<ul>${items.map(it => `<li>${renderInlineMarkdown(it.trim())}</li>`).join('')}</ul>`);
                continue;
            }

            // ordered list
            if (/^\s*\d+[.)]\s+/.test(t)) {
                const items = [];
                while (i < lines.length) {
                    const tl = lines[i].trim();
                    if (!tl) break;
                    if (/^\s*\d+[.)]\s+/.test(tl)) { items.push(tl.replace(/^\s*\d+[.)]\s+/, '').trim()); i++; continue; }
                    if (isBullet(tl)) break;
                    items[items.length - 1] += ' ' + tl; // wrapped continuation
                    i++;
                }
                out.push(`<ol>${items.map(it => `<li>${renderInlineMarkdown(it.trim())}</li>`).join('')}</ol>`);
                continue;
            }

            // plain paragraph: group consecutive non-special lines; stop at any
            // heading/code/list line so it starts its own block.
            const paraLines = [];
            while (i < lines.length) {
                const pl = lines[i];
                const pt = pl.trim();
                if (!pt || isItem(pt) || isHeading(pt) || isCodeLine(pt)) break;
                paraLines.push(pt);
                i++;
            }
            const para = paraLines.map(l => renderInlineMarkdown(l)).join('<br/>');
            if (para) out.push(`<p>${para}</p>`);
        }
        return out.join('\n');
    }).filter(Boolean);

    return html.join('\n');
}

function truncatePath(s, maxLen) {
    maxLen = maxLen || 35;
    if (!s || s.length <= maxLen) return s;
    const slash = s.lastIndexOf('/');
    const dir = slash >= 0 ? s.slice(0, slash + 1) : '';
    const name = slash >= 0 ? s.slice(slash + 1) : s;
    const dot = name.lastIndexOf('.');
    const ext = dot > 0 ? name.slice(dot) : '';
    const baseLen = maxLen - dir.length - ext.length - 3;
    if (baseLen < 1) return dir + '...' + ext;
    return dir + name.slice(0, baseLen) + '...' + ext;
}

const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
function dayName(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr + 'T00:00:00');
    return DAY_NAMES[d.getDay()] || '';
}
function dayNameShort(dateStr) {
    const n = dayName(dateStr);
    return n ? n.slice(0, 3) : '';
}

function fmtMoney(n) {
    if (n === null || n === undefined) return '-';
    return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function statusPill(status) {
    const cls = String(status).toLowerCase();
    const map = { present: 'success', late: 'warn', absent: 'danger', leave: 'info', off: 'neutral', holiday: 'neutral', approved: 'success', pending: 'warn', rejected: 'danger', generated: 'success', active: 'success', inactive: 'danger', assigned: 'success' };
    return `<span class="pill-tag ${map[cls] || 'neutral'}">${escapeXml(status)}</span>`;
}

async function attendanceHtml(title, d) {
    if (!d.attendance || d.attendance.length === 0) {
        return { html: `<h4>${title}</h4><p>No attendance records found for this period.</p>` };
    }
    const s = d.summary;
    let rows = '';
    for (const a of d.attendance) {
        rows += `<tr><td>${escapeXml(a.date)}</td><td>${escapeXml(dayNameShort(a.date))}</td><td>${escapeXml(a.check_in || '—')}</td><td>${escapeXml(a.check_out || '—')}</td><td>${statusPill(a.status)}</td><td class="num">${a.working_hours != null ? a.working_hours : '—'}</td></tr>`;
    }
    return {
        html: `
        <h4>${title}</h4>
        <div class="stat-row">${s.present}<sub>Present</sub></div><div class="stat-row">${s.late}<sub>Late</sub></div><div class="stat-row">${s.leave}<sub>Leave</sub></div><div class="stat-row">${s.absent}<sub>Absent</sub></div><div class="stat-row">${s.off ?? 0}<sub>Off</sub></div>
        <p class="muted">Total working hours: <strong>${s.total_working_hours}</strong></p>
        <div class="table-wrap"><table><thead><tr><th>Date</th><th>Day</th><th>Check In</th><th>Check Out</th><th>Status</th><th>Hours</th></tr></thead><tbody>${rows}</tbody></table></div>`
    };
}

function attendanceTableHtml(title, d) {
    if (!d.attendance || d.attendance.length === 0) {
        return `<div class="exp-inline-empty">No attendance records found for this period.</div>`;
    }
    const s = d.summary || {};
    let rows = '';
    for (const a of d.attendance) {
        rows += `<tr><td>${escapeXml(a.date)}</td><td>${escapeXml(dayNameShort(a.date))}</td><td>${escapeXml(a.check_in || '—')}</td><td>${escapeXml(a.check_out || '—')}</td><td>${statusPill(a.status)}</td><td class="num">${a.working_hours != null ? a.working_hours : '—'}</td></tr>`;
    }
    return `
        <div class="att-stats">
            <span class="att-stat"><span class="att-num">${s.present ?? 0}</span><span class="att-lbl">Present</span></span>
            <span class="att-stat"><span class="att-num">${s.late ?? 0}</span><span class="att-lbl">Late</span></span>
            <span class="att-stat"><span class="att-num">${s.leave ?? 0}</span><span class="att-lbl">Leave</span></span>
            <span class="att-stat"><span class="att-num">${s.absent ?? 0}</span><span class="att-lbl">Absent</span></span>
            <span class="att-stat"><span class="att-num">${s.off ?? 0}</span><span class="att-lbl">Off</span></span>
        </div>
        <p class="muted att-hours">Total working hours: <strong>${s.total_working_hours ?? 0}</strong></p>
        <div class="table-wrap"><table><thead><tr><th>Date</th><th>Day</th><th>Check In</th><th>Check Out</th><th>Status</th><th>Hours</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

async function runAction(action, value, ctx) {
    switch (action) {
        case 'attendanceToday': {
            const today = toISO(new Date());
            const d = await API.attendanceRange(today, today);
            return await attendanceHtml('My Attendance — Today', d);
        }
        case 'attendanceWeek': {
            const now = new Date();
            const from = value === 'lastWeek' ? weekStart(addDays(now, -7)) : weekStart(now);
            const to = addDays(from, 6);
            const d = await API.attendanceRange(toISO(from), toISO(to));
            const label = value === 'lastWeek' ? 'Last Week' : 'This Week';
            return await attendanceHtml(`My Attendance — ${label} (${toISO(from)} to ${toISO(to)})`, d);
        }
        case 'attendanceRange': {
            const d = await API.attendanceRange(value.from, value.to);
            const heading = value.heading ||
                (value.from === value.to
                    ? `My Attendance — ${value.from}`
                    : `My Attendance — ${value.from} to ${value.to}`);
            return await attendanceHtml(heading, d);
        }
        case 'leavesBalance': {
            const d = await API.leavesOverview();
            const b = d.balance || {};
            const c = d.counts || {};
            const reqs = d.requests || [];
            const norm = status => String(status || '').toLowerCase();
            const pendingReqs = reqs.filter(r => norm(r.status) === 'pending');
            const approvedReqs = reqs.filter(r => norm(r.status) === 'approved');
            const rejectedReqs = reqs.filter(r => norm(r.status) === 'rejected');
            const sec = (title, count, list) => {
                let body;
                if (list.length === 0) {
                    body = `<p class="muted">None.</p>`;
                } else {
                    let rows = '';
                    for (const r of list) {
                        rows += `<tr class="${norm(r.status) === 'pending' ? 'att-pending-row' : ''}"><td>${escapeXml(r.leave_id)}</td><td>${escapeXml(r.type)}</td><td>${escapeXml(r.from)} → ${escapeXml(r.to)}</td><td class="num">${r.days}</td><td>${statusPill(r.status)}</td></tr>`;
                    }
                    body = `<div class="table-wrap"><table><thead><tr><th>ID</th><th>Type</th><th>Dates</th><th>Days</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table></div>`;
                }
                return `<div class="att-sec-title">${title} <span class="explorer-count">${count}</span></div>${body}`;
            };
            return {
                html: `
                <h4>My Leave Balance</h4>
                <div class="stat-row">${b.annual}<sub>Annual</sub></div><div class="stat-row">${b.sick}<sub>Sick</sub></div><div class="stat-row">${b.casual}<sub>Casual</sub></div><div class="stat-row">${b.unpaid}<sub>Unpaid</sub></div>
                <div class="att-summary">
                    <span class="att-chip">${c.total ?? 0} Requested</span>
                    <span class="att-chip pending"><b>${c.pending ?? 0}</b> Pending</span>
                    <span class="att-chip approved"><b>${c.approved ?? 0}</b> Approved</span>
                    <span class="att-chip rejected"><b>${c.rejected ?? 0}</b> Rejected</span>
                </div>
                ${sec('Pending Leaves', pendingReqs.length, pendingReqs)}
                ${sec('Approved Leaves', approvedReqs.length, approvedReqs)}
                ${sec('Rejected Leaves', rejectedReqs.length, rejectedReqs)}
                ${reqs.length === 0 ? '' : ''}
                ${(c.pending || 0) > 0 ? `<p class="muted"><svg class="inline-icon" viewBox="0 0 448 512" width="1em" height="1em"><path fill="currentColor" d="M224 0c-17.7 0-32 14.3-32 32V51.2C119.7 62.4 64 124.3 64 200v33.6c0 45.4-15.1 88.3-38.8 121.6l-7 10.5c-11.7 17.5-2.3 41.6 17.5 44.8l48.4 8c15.3 2.5 31.3-2.3 41.7-13l21.9-22.3c2.6-2.7 6.4-4.3 10.4-4.3s7.8 1.6 10.4 4.3L213.4 407c10.4 10.7 26.4 15.5 41.7 13l48.4-8c19.8-3.2 29.2-27.3 17.5-44.8l-7-10.5C293.1 321.9 278 279 278 233.6V200c0-75.7-55.7-137.6-128-148.8V32c0-17.7-14.3-32-32-32z"/></svg> ${c.pending} leave request${c.pending !== 1 ? 's' : ''} pending approval.</p>` : ''}`
            };
        }
        case 'leavesHistory': {
            const d = await API.leavesHistory(value.year, value.month);
            const monthName = MONTHS[value.month - 1];
            if (!d.requests || d.requests.length === 0) {
                return { html: `<h4>Leave History — ${monthName} ${value.year}</h4><p>No leave requests this month.</p>` };
            }
            let rows = '';
            for (const r of d.requests) {
                rows += `<tr><td>${escapeXml(r.leave_id)}</td><td>${escapeXml(r.type)}</td><td>${escapeXml(r.from)} → ${escapeXml(r.to)}</td><td class="num">${r.days}</td><td>${statusPill(r.status)}</td></tr>`;
            }
            return {
                html: `
                <h4>Leave History — ${monthName} ${value.year}</h4>
                <div class="table-wrap"><table><thead><tr><th>ID</th><th>Type</th><th>Dates</th><th>Days</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table></div>`
            };
        }
        case 'salaryDetail': {
            const d = await API.salaryStructure();
            const st = d.structure || {};
            const def = v => (v === null || v === undefined ? 0 : v);
            const rows = [
                ['Basic Salary', def(st.basic), 'base'],
                ['Housing Allowance', def(st.housing_allowance), 'plus'],
                ['Transport Allowance', def(st.transport_allowance), 'plus'],
                ['Other Allowances', def(st.other_allowances), 'plus'],
                ['Gross Salary', def(st.gross_salary), 'gross'],
                ['Deductions', def(st.deductions), 'minus'],
                ['Net Salary', def(st.net_salary), 'net'],
            ];
            const gu = st.currency || 'PKR';
            let tr = '';
            for (const [k, v, cls] of rows) {
                tr += `<tr><td>${escapeXml(k)}</td><td class="amt num ${cls}"><strong>${gu} ${fmtMoney(v)}</strong></td></tr>`;
            }
            return {
                html: `
                <h4>My Salary Breakdown</h4>
                <div class="table-wrap"><table class="salary-table"><tbody>${tr}</tbody></table></div>
                <div class="salary-note muted">Monthly gross ${gu} ${fmtMoney(def(st.gross_salary))} · take-home ${gu} ${fmtMoney(def(st.net_salary))}</div>`
            };
        }
        case 'salaryPayslip': {
            const d = await API.salaryPayslip(value.year, value.month);
            const monthName = MONTHS[value.month - 1];
            const p = d.payslip;
            if (!p) return { html: `<h4>Payslip — ${monthName} ${value.year}</h4><p>No payslip generated for this month.</p>` };
            let st;
            try { st = (await API.salaryStructure()).structure || {}; } catch { st = {}; }
            const def = v => (v === null || v === undefined ? 0 : v);
            const gu = st.currency || 'PKR';
            const breakdownRows = [
                ['Basic Salary', def(st.basic), 'base'],
                ['Housing Allowance', def(st.housing_allowance), 'plus'],
                ['Transport Allowance', def(st.transport_allowance), 'plus'],
                ['Other Allowances', def(st.other_allowances), 'plus'],
                ['Gross Salary', def(st.gross_salary), 'gross'],
                ['Deductions', def(st.deductions), 'minus'],
                ['Net Salary', def(st.net_salary), 'net'],
            ];
            const btr = breakdownRows
                .map(([k, v, cls]) => `<tr><td>${escapeXml(k)}</td><td class="amt num ${cls}"><strong>${gu} ${fmtMoney(v)}</strong></td></tr>`)
                .join('');
            return {
                html: `
                <h4>Payslip — ${monthName} ${value.year}</h4>
                <div class="stat-row">${fmtMoney(p.gross_salary)}<sub>Gross</sub></div><div class="stat-row">-${fmtMoney(p.deductions)}<sub>Deductions</sub></div><div class="stat-row">${fmtMoney(p.net_salary)}<sub>Net</sub></div>
                <p class="muted">ID: <strong>${escapeXml(p.payslip_id)}</strong> — ${statusPill(p.status)}</p>
                <div class="table-wrap"><table class="salary-table"><tbody>${btr}</tbody></table></div>
                <div class="salary-note muted">Monthly gross ${gu} ${fmtMoney(def(st.gross_salary))} · take-home ${gu} ${fmtMoney(def(st.net_salary))}</div>`
            };
        }
        default:
            return { html: `<p>Not implemented yet.</p>` };
    }
}

// Full preview for a single explorer item (services / employees / documents)
async function runPreview(type, item, ctx) {
    if (type === 'services') {
        const s = item;
        const rows = [
            ['Name', `<strong>${escapeXml(s.name)}</strong>`],
            ['Role', escapeXml(s.role || s.department)],
            ['Department', escapeXml(s.department)],
            ['Extension', escapeXml(s.extension)],
            ['Email', `<a href="mailto:${s.email}">${escapeXml(s.email)}</a>`],
            ['Location', escapeXml(s.location)],
            ['Hours', escapeXml(s.hours)],
        ].map(([k, v]) => `<tr><td>${escapeXml(k)}</td><td>${v}</td></tr>`).join('');
        return { html: `<h4>Employee — ${escapeXml(s.name)}</h4><div class="table-wrap profile-table"><table>${rows}</table></div>` };
    }

    if (type === 'employees') {
        const isAdmin = ctx?.user?.account_type === 'admin';
        if (isAdmin) {
            const rec = await API.adminEmployee(item.employee_id);
            const p = rec?.profiles || {};
            const c = rec?.contacts || {};
            const l = rec?.locations || {};
            const rows = [
                ['Employee ID', escapeXml(p.employee_id || item.employee_id)],
                ['Name', `<strong>${escapeXml(item.name)}</strong>`],
                ['Department', escapeXml(p.department)],
                ['Job Title', escapeXml(p.job_title)],
                ['Employment Type', escapeXml(p.employment_type)],
                ['Employment Status', statusPill(p.employment_status)],
                ['Joining Date', escapeXml(p.joining_date)],
                ['Email', `<a href="mailto:${c.email}">${escapeXml(c.email)}</a>`],
                ['Phone', `<a href="tel:${c.phone}">${escapeXml(c.phone)}</a>`],
                ['Extension', escapeXml(c.extension)],
                ['Floor', escapeXml(l.floor)],
                ['Desk Number', escapeXml(l.desk_number)],
            ].filter(([, v]) => v != null && v !== '').map(([k, v]) => `<tr><td>${escapeXml(k)}</td><td>${v}</td></tr>`).join('');
            return { html: `<h4>Employee — ${escapeXml(item.name)}</h4><div class="table-wrap profile-table"><table>${rows}</table></div>` };
        }
        const rec = await API.employee(item.employee_id);
        const rows = [
            ['Name', `<strong>${escapeXml(rec.name || item.name)}</strong>`],
            ['Department', escapeXml(rec.department)],
            ['Job Title', escapeXml(rec.job_title)],
            ['Email', `<a href="mailto:${rec.email}">${escapeXml(rec.email)}</a>`],
            ['Extension', escapeXml(rec.extension)],
            ['Floor', escapeXml(rec.floor)],
            ['Desk Number', escapeXml(rec.desk_number)],
        ].filter(([, v]) => v != null && v !== '').map(([k, v]) => `<tr><td>${escapeXml(k)}</td><td>${v}</td></tr>`).join('');
        return { html: `<h4>Employee — ${escapeXml(item.name)}</h4><div class="table-wrap profile-table"><table>${rows}</table></div>` };
    }

    if (type === 'documents') {
        const d = item;
        let fileLink = null;
        try {
            const res = await API.documentFileUrl(d.file);
            fileLink = res?.url || null;
        } catch { fileLink = null; }
        const fileCell = fileLink
            ? `<a href="${escapeXml(fileLink)}" target="_blank" rel="noopener" class="doc-link file-path-link" title="${escapeXml(d.file)}">${escapeXml(truncatePath(d.file, 40))} ↗</a>`
            : `<code>${escapeXml(d.file)}</code>`;
        const rows = [
            ['Name', `<strong>${escapeXml(d.name)}</strong>`],
            ['Category', escapeXml(d.category)],
            ['Type', escapeXml(d.type)],
            ['Document ID', escapeXml(d.document_id)],
            ['File', fileCell],
        ].map(([k, v]) => `<tr><td>${escapeXml(k)}</td><td>${v}</td></tr>`).join('');
        return { html: `<h4>Document — ${escapeXml(d.name)}</h4><div class="table-wrap profile-table"><table>${rows}</table></div>` };
    }
    return { html: `<p>No preview available.</p>` };
}

// ---------------------------------- Login ----------------------------------
function LoginView({ onLogin }) {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const submit = async (e) => {
        e.preventDefault();
        setError('');
        if (!username.trim() || !password) { setError('Please enter both username and password.'); return; }
        setLoading(true);
        try {
            const data = await AuthAPI.login(username.trim(), password);
            sessionStorage.setItem('hr_token', data.access_token);
            const me = await API.me();
            const accountType = (data.account_type || me.account_type || '').toLowerCase();
            sessionStorage.setItem('hr_user', JSON.stringify({ ...me, account_type: accountType }));
            onLogin({ ...me, account_type: accountType });
        } catch (err) {
            if (err instanceof NetworkError) {
                setError('Cannot reach the server. Please check your connection and try again.');
            } else if (err instanceof AuthError) {
                setError('Incorrect username or password. Please try again.');
            } else if (err instanceof RateLimitError) {
                setError('Too many failed attempts. Please wait a few minutes and try again.');
            } else if (err instanceof SessionExpiredError) {
                setError('Your session has expired. Please log in again.');
            } else {
                setError(err.message || 'Login failed. Please try again.');
            }
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="login-page">
            <div className="login-card">
                <div className="login-brand">
                    <div className="assistant-avatar">HR</div>
                    <h1>HR CHATBOT</h1>
                    <p>Sign in to access your private HR information</p>
                </div>
                <form onSubmit={submit}>
                    <label className="login-label">Username</label>
                    <input className="login-input" type="text" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Username" autoFocus />
                    <label className="login-label">Password</label>
                    <input className="login-input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password" />
                    {error && <div className="login-error">{error}</div>}
                    <button className="login-btn" type="submit" disabled={loading}>{loading ? 'Signing in…' : 'Sign In'}</button>
                </form>
            </div>
        </div>
    );
}

// ---------------------------------- Explorer ----------------------------------
function ExplorerPanel({ type, onPreview, onPick, onClose }) {
    const [items, setItems] = useState([]);
    const [query, setQuery] = useState('');
    const [mode, setMode] = useState('search');
    const [dept, setDept] = useState(null);
    const [empQuery, setEmpQuery] = useState('');
    const [loading, setLoading] = useState(true);
    const [listVisible, setListVisible] = useState(false);
    const searchRef = useRef(null);

    const typeTitle = type === 'services' ? 'People & Services' : type === 'employees' ? 'Employees' : 'Documents';

    useEffect(() => {
        let alive = true;
        (async () => {
            setLoading(true);
            try {
                let data = [];
                if (type === 'services') data = (await API.services()).services || [];
                else if (type === 'employees') data = (await API.employees()).employees || [];
                else if (type === 'documents') data = (await API.documents(null)).documents || [];
                if (alive) setItems(data);
            } catch {
                if (alive) setItems([]);
            } finally {
                if (alive) { setLoading(false); setListVisible(true); }
            }
        })();
        return () => { alive = false; };
    }, [type]);

    const filtered = items.filter(it => {
        if (!query.trim()) return true;
        const q = query.toLowerCase();
        const hay = [];
        if (type === 'services') hay.push(it.name, it.role, it.department, it.extension, it.email, it.location);
        if (type === 'employees') hay.push(it.name, it.employee_id, it.department, it.job_title, it.email, it.employment_status);
        if (type === 'documents') hay.push(it.name, it.category, it.type, it.document_id);
        return hay.join(' ').toLowerCase().includes(q);
    });

    // Groups: employees by department, documents by category (split-widget layout)
    const isSplit = type === 'employees' || type === 'documents';
    const isEmployees = type === 'employees';
    const groupKey = type === 'documents' ? 'category' : 'department';
    const groupTitle = type === 'documents' ? 'Categories' : 'Departments';
    const searchText = isEmployees ? empQuery : query;
    let groupList = [];
    let nameResults = [];
    if (isSplit) {
        const map = {};
        filtered.forEach(it => { const k = it[groupKey] || 'Other'; (map[k] = map[k] || []).push(it); });
        groupList = Object.entries(map).sort((a, b) => a[0].localeCompare(b[0]));
        const q = searchText.trim().toLowerCase();
        if (q) {
            nameResults = filtered.filter(it =>
                (type === 'documents'
                    ? [it.name, it.category, it.type, it.document_id]
                    : [it.name, it.employee_id, it.job_title, it.department]).join(' ').toLowerCase().includes(q)
            );
        }
    }
    const searching = isSplit && searchText.trim().length > 0;
    const empCard = (it) => (
        <button key={it.employee_id} className="dir-card-item" onClick={() => onPick(it)}>
            <span className="dir-avatar">{it.name.split(' ').map(p => p[0]).join('').slice(0, 2).toUpperCase()}</span>
            <span className="dir-item-main">
                <span className="dir-name">{it.name}</span>
                <span className="dir-id">{it.job_title}</span>
            </span>
        </button>
    );
    const docCard = (it) => (
        <button key={it.document_id} className="dir-card-item" onClick={() => onPreview('documents', it)}>
            <span className="dir-avatar"><FaFileAlt /></span>
            <span className="dir-item-main">
                <span className="dir-name">{it.name}</span>
                <span className="dir-id">{it.type}</span>
            </span>
        </button>
    );
    const renderCard = type === 'documents' ? docCard : empCard;

    return (
        <div className="explorer-panel">
            <div className="explorer-head">
                <span className="explorer-title">{typeTitle} <span className="explorer-count">{items.length}</span></span>
                {isSplit && (
                    <div className="head-search">
                        <span className="head-search-ic"><FaSearch /></span>
                        <input
                            type="text"
                            placeholder={isEmployees ? 'Search by name…' : 'Search documents…'}
                            value={isEmployees ? empQuery : query}
                            onChange={(e) => { if (isEmployees) setEmpQuery(e.target.value); else setQuery(e.target.value); }}
                        />
                        {(isEmployees ? empQuery : query) && (
                            <button className="head-search-clear" onClick={() => isEmployees ? setEmpQuery('') : setQuery('')} title="Clear"><FaTimes /></button>
                        )}
                    </div>
                )}
                <button className="explorer-close" onClick={onClose} title="Close"><FaTimes /></button>
            </div>

            {isSplit ? (
                loading ? (
                    <div className="explorer-loading">Loading…</div>
                ) : (
                    <div className="split-widget">
                        <div className={searching ? 'split-body searching' : 'split-body'}>
                            {searching ? (
                                <div className="split-content">
                                    <div className="split-content-head">
                                        <strong>Search results</strong>
                                        <span className="dir-id">{nameResults.length} match{nameResults.length !== 1 ? 'es' : ''} for “{searchText.trim()}”</span>
                                    </div>
                                    {nameResults.length === 0 ? (
                                        <div className="explorer-empty">No {isEmployees ? 'employee' : 'document'} matches “{searchText.trim()}”.</div>
                                    ) : (
                                        <div className="split-employees">
                                            {nameResults.map(it => renderCard(it))}
                                        </div>
                                    )}
                                </div>
                            ) : (
                                <>
                                    <div className="split-sidebar">
                                        <div className="split-sidebar-title">{groupTitle}</div>
                                        {groupList.length === 0 ? (
                                            <div className="explorer-empty">No {groupTitle.toLowerCase()}.</div>
                                        ) : (
                                            groupList.map(d => (
                                                <button
                                                    key={d[0]}
                                                    className={`split-dept ${dept && dept[0] === d[0] ? 'active' : ''}`}
                                                    onClick={() => setDept(d)}
                                                >
                                                    <span className="split-dept-name">{d[0]}</span>
                                                    <span className="split-dept-count">{d[1].length}</span>
                                                </button>
                                            ))
                                        )}
                                    </div>
                                    <div className="split-content">
                                        {!dept ? (
                                            <div className="split-placeholder"><FaArrowLeft /> Select a {groupTitle.toLowerCase().slice(0, -1)} to see its {isEmployees ? 'employees' : 'documents'} below</div>
                                        ) : (
                                            <div className="split-content-head">
                                                <span className="dir-avatar">{isEmployees ? dept[0].split(' ').map(x => x[0]).join('').slice(0, 2).toUpperCase() : <FaFileAlt />}</span>
                                                <div>
                                                    <strong>{dept[0]}</strong>
                                                    <span className="dir-id">{dept[1].length} {isEmployees ? 'employee' : 'document'}{dept[1].length !== 1 ? 's' : ''} — click one to see it in chat</span>
                                                </div>
                                            </div>
                                        )}
                                        {dept && (
                                            <div className="split-employees">
                                                {dept[1].map(it => renderCard(it))}
                                            </div>
                                        )}
                                    </div>
                                </>
                            )}
                        </div>
                    </div>
                )
            ) : (
                <>
                    {mode === 'search' && (
                        <div className="explorer-search">
                            <input
                                ref={searchRef}
                                type="text"
                                placeholder={`Search ${typeTitle.toLowerCase()}…`}
                                value={query}
                                onChange={(e) => { setQuery(e.target.value); setListVisible(true); }}
                            />
                        </div>
                    )}

                    {loading ? (
                        <div className="explorer-loading">Loading…</div>
                    ) : (
                        <div className={`explorer-list ${mode === 'browse' ? 'browse' : ''}`}>
                            {filtered.length === 0 ? (
                                <div className="explorer-empty">No {typeTitle.toLowerCase()} match your search.</div>
                            ) : (
                                filtered.map((it, idx) => (
                                    <button key={idx} className="explorer-item" onClick={() => onPreview(type, it)}>
                                        {type === 'services' && (<span className="exp-ic"><FaConciergeBell /></span>)}
                                        {type === 'documents' && (<span className="exp-ic"><FaFileAlt /></span>)}
                                        <span className="exp-main">
                                            <span className="exp-name">{it.name}</span>
                                            <span className="exp-sub">
                                                {type === 'services' && `${it.department} — ${it.role || ''}`.replace(/\s—\s*$/, '')}
                                                {type === 'documents' && `${it.category} — ${it.type}`}
                                            </span>
                                        </span>
                                        <span className="exp-arrow">→</span>
                                    </button>
                                ))
                            )}
                        </div>
                    )}
                </>
            )}
        </div>
    );
}

// ------------------------- Attendance Panel -------------------------
function AttendancePanel({ user, onPick, onClose }) {
    const quickFilters = [
        { id: 'today', label: 'Today' },
        { id: 'yesterday', label: 'Yesterday' },
        { id: 'thisWeek', label: 'This Week' },
        { id: 'lastWeek', label: 'Last Week' },
        { id: 'thisMonth', label: 'This Month' },
        { id: 'lastMonth', label: 'Last Month' },
        { id: 'thisYear', label: 'This Year' },
        { id: 'lastYear', label: 'Last Year' },
    ];
    const [years, setYears] = useState([]);
    const [active, setActive] = useState(null);
    const [monthSel, setMonthSel] = useState(null);

    useEffect(() => {
        try {
            const jd = user?.profile?.joining_date || '';
            const joinYear = jd ? parseInt(jd.slice(0, 4), 10) : new Date().getFullYear();
            const currentYear = new Date().getFullYear();
            const ys = [];
            for (let y = currentYear; y >= joinYear; y--) ys.push(y);
            setYears(ys);
        } catch { setYears([]); }
    }, [user]);

    const rangeFor = (id) => {
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        switch (id) {
            case 'today': return { from: today, to: today };
            case 'yesterday': { const y = addDays(today, -1); return { from: y, to: y }; }
            case 'thisWeek': { const f = weekStart(now); return { from: f, to: addDays(f, 6) }; }
            case 'lastWeek': { const f = weekStart(addDays(now, -7)); return { from: f, to: addDays(f, 6) }; }
            case 'thisMonth': return { from: new Date(now.getFullYear(), now.getMonth(), 1), to: new Date(now.getFullYear(), now.getMonth() + 1, 0) };
            case 'lastMonth': return { from: new Date(now.getFullYear(), now.getMonth() - 1, 1), to: new Date(now.getFullYear(), now.getMonth(), 0) };
            case 'thisYear': return { from: new Date(now.getFullYear(), 0, 1), to: today };
            case 'lastYear': return { from: new Date(now.getFullYear() - 1, 0, 1), to: new Date(now.getFullYear() - 1, 11, 31) };
            default: return null;
        }
    };

    const pickFilter = (f) => {
        const { from, to } = rangeFor(f.id);
        let heading;
        if (f.id === 'thisMonth' || f.id === 'lastMonth') {
            heading = `My Attendance — ${f.label} (${MONTHS[from.getMonth()]} ${from.getFullYear()})`;
        } else {
            heading = `My Attendance — ${f.label} (${toISO(from)} to ${toISO(to)})`;
        }
        onPick(`Show me my attendance for ${f.label.toLowerCase()}`, toISO(from), toISO(to), heading);
    };

    const pickMonth = (y, m) => {
        const from = toISO(new Date(y, m - 1, 1));
        const to = toISO(new Date(y, m, 0));
        onPick(`Show me attendance of ${MONTHS[m - 1]} ${y}`, from, to, `Monthly Attendance — ${MONTHS[m - 1]} ${y}`);
    };

    const naturalRangeLabel = () => {
        if (active?.type === 'filter') return active.label;
        if (active?.type === 'year') return `${active.label}${monthSel ? ` — ${MONTHS[monthSel - 1]}` : ''}`;
        return '';
    };

    const showMonths = active && active.type === 'year' && monthSel === null;

    return (
        <div className="explorer-panel">
            <div className="explorer-head">
                <span className="explorer-title">Attendance</span>
                <div className="att-filters">
                    {quickFilters.map(ff => (
                        <button
                            key={ff.id}
                            className={`att-filter ${active && active.type === 'filter' && active.id === ff.id ? 'active' : ''}`}
                            onClick={() => { setActive({ type: 'filter', id: ff.id, label: ff.label }); setMonthSel(null); pickFilter(ff); }}
                        >
                            {ff.label}
                        </button>
                    ))}
                </div>
                <button className="explorer-close" onClick={onClose} title="Close"><FaTimes /></button>
            </div>
            <div className="split-body">
                <div className="split-sidebar">
                    <div className="split-sidebar-title">Years</div>
                    {years.map(y => (
                        <button
                            key={y}
                            className={`split-dept ${active && active.type === 'year' && active.id === y ? 'active' : ''}`}
                            onClick={() => { setActive({ type: 'year', id: y, label: String(y) }); setMonthSel(null); }}
                        >
                            <span className="split-dept-name">{y}</span>
                        </button>
                    ))}
                </div>
                <div className="split-content">
                    {!active ? (
                        <div className="split-placeholder"><FaArrowLeft /> Pick a year to see its months, or use the quick filters above</div>
                    ) : showMonths ? (
                        <>
                            <div className="split-content-head">
                                <div>
                                    <strong>{active.label}</strong>
                                    <span className="dir-id">Pick a month to see it in the chat</span>
                                </div>
                            </div>
                            <div className="split-months">
                                {MONTHS.map((m, i) => (
                                    <button key={m} className="split-month" onClick={() => pickMonth(active.id, i + 1)}>
                                        <span className="split-month-name">{m}</span>
                                    </button>
                                ))}
                            </div>
                        </>
                    ) : (
                        <div className="split-placeholder"><FaArrowLeft /> This was sent to the chat above{active.label ? ` (${naturalRangeLabel()})` : ''}. Pick another filter or a year.</div>
                    )}
                </div>
            </div>
        </div>
    );
}

// ------------------------- Leaves Panel -------------------------
function LeavesPanel({ user, onBalance, onPick, onClose }) {
    const [years, setYears] = useState([]);
    const [selectedYear, setSelectedYear] = useState(null);

    useEffect(() => {
        try {
            const jd = user?.profile?.joining_date || '';
            const joinYear = jd ? parseInt(jd.slice(0, 4), 10) : new Date().getFullYear();
            const currentYear = new Date().getFullYear();
            const ys = [];
            for (let y = currentYear; y >= joinYear; y--) ys.push(y);
            setYears(ys);
            setSelectedYear(currentYear);
        } catch { setYears([]); }
    }, [user]);

    return (
        <div className="explorer-panel">
            <div className="explorer-head">
                <span className="explorer-title">Leaves</span>
                <div className="att-filters">
                    <button className="att-filter" onClick={onBalance}><FaCalendarCheck /> Current Leave Balance</button>
                </div>
                <button className="explorer-close" onClick={onClose} title="Close"><FaTimes /></button>
            </div>
            <div className="split-body">
                <div className="split-sidebar">
                    <div className="split-sidebar-title">Years</div>
                    {years.length === 0 ? (
                        <div className="explorer-empty">No years.</div>
                    ) : years.map(y => (
                        <button
                            key={y}
                            className={`split-dept ${selectedYear === y ? 'active' : ''}`}
                            onClick={() => setSelectedYear(y)}
                        >
                            <span className="split-dept-name">{y}</span>
                        </button>
                    ))}
                </div>
                <div className="split-content">
                    {selectedYear === null ? (
                        <div className="split-placeholder"><FaArrowLeft /> Select a year to see its months</div>
                    ) : (
                        <div className="split-content-head">
                            <div>
                                <strong>{selectedYear}</strong>
                                <span className="dir-id">Pick a month to see your leave history in the chat</span>
                            </div>
                        </div>
                    )}
                    {selectedYear !== null && (
                        <div className="split-months">
                            {MONTHS.map((m, i) => (
                                <button key={m} className="split-month" onClick={() => onPick(selectedYear, i + 1)}>
                                    <span className="split-month-name">{m}</span>
                                </button>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

// ------------------------- Salary Panel -------------------------
function SalaryPanel({ user, onBreakdown, onPick, onClose }) {
    const [mode, setMode] = useState('payslips');
    const [years, setYears] = useState([]);
    const [selectedYear, setSelectedYear] = useState(null);
    const [loading, setLoading] = useState(true);
    const [breakdown, setBreakdown] = useState(null);
    const [bLoading, setBLoading] = useState(false);

    useEffect(() => {
        try {
            const jd = user?.profile?.joining_date || '';
            const joinYear = jd ? parseInt(jd.slice(0, 4), 10) : new Date().getFullYear();
            const currentYear = new Date().getFullYear();
            const ys = [];
            for (let y = currentYear; y >= joinYear; y--) ys.push(y);
            setYears(ys);
            setSelectedYear(currentYear);
        } catch { setYears([]); }
        finally { setLoading(false); }
    }, [user]);

    useEffect(() => {
        if (mode !== 'breakdown') return;
        setBLoading(true);
        API.salaryStructure()
            .then(d => setBreakdown(d.structure || {}))
            .catch(() => setBreakdown(null))
            .finally(() => setBLoading(false));
    }, [mode]);

    return (
        <div className="explorer-panel">
            <div className="explorer-head">
                <span className="explorer-title">Salary <span className="explorer-count">{mode === 'payslips' ? 'Payslips' : 'Breakdown'}</span></span>
                <div className="salary-tabs">
                    <button className={mode === 'payslips' ? 'salary-tab active' : 'salary-tab'} onClick={() => setMode('payslips')}><FaFileAlt /> My Payslips</button>
                    <button className={mode === 'breakdown' ? 'salary-tab active' : 'salary-tab'} onClick={() => setMode('breakdown')}><FaMoneyBillWave /> My Salary Breakdown</button>
                </div>
                <button className="explorer-close" onClick={onClose} title="Close"><FaTimes /></button>
            </div>

            {mode === 'breakdown' ? (
                <div className="split-body" style={{ minHeight: 0 }}>
                    <div className="split-content">
                        {bLoading ? (
                            <div className="explorer-loading">Loading your salary breakdown…</div>
                        ) : !breakdown ? (
                            <div className="split-placeholder">Couldn't load your salary breakdown.</div>
                        ) : (() => {
                            const st = breakdown;
                            const def = v => (v === null || v === undefined ? 0 : v);
                            const gu = st.currency || 'PKR';
                            const items = [
                                ['Basic Salary', def(st.basic), ''],
                                ['Housing Allowance', def(st.housing_allowance), ''],
                                ['Transport Allowance', def(st.transport_allowance), ''],
                                ['Other Allowances', def(st.other_allowances), ''],
                                ['Gross Salary', def(st.gross_salary), 'gross'],
                                ['Deductions', def(st.deductions), 'minus'],
                                ['Net Salary', def(st.net_salary), 'net'],
                            ];
                            return (
                                <div className="split-breakdown">
                                    <div className="att-sec-title">My Salary Breakdown</div>
                                    <div className="table-wrap"><table className="salary-table"><tbody>
                                        {items.map(([k, v, cls]) => (
                                            <tr key={k}><td>{escapeXml(k)}</td><td className={`amt num ${cls}`}><strong>{gu} {fmtMoney(v)}</strong></td></tr>
                                        ))}
                                    </tbody></table></div>
                                    <div className="salary-note muted">Monthly gross {gu} {fmtMoney(def(st.gross_salary))} · take-home {gu} {fmtMoney(def(st.net_salary))}</div>
                                </div>
                            );
                        })()}
                    </div>
                </div>
            ) : (
                <div className="split-body">
                    <div className="split-sidebar">
                        <div className="split-sidebar-title">Years</div>
                        {loading ? (
                            <div className="explorer-loading">Loading…</div>
                        ) : years.length === 0 ? (
                            <div className="explorer-empty">No years.</div>
                        ) : years.map(y => (
                            <button
                                key={y}
                                className={`split-dept ${selectedYear === y ? 'active' : ''}`}
                                onClick={() => setSelectedYear(y)}
                            >
                                <span className="split-dept-name">{y}</span>
                            </button>
                        ))}
                    </div>
                    <div className="split-content">
                        {selectedYear === null ? (
                            <div className="split-placeholder"><FaArrowLeft /> Select a year to see its months</div>
                        ) : (
                            <div className="split-content-head">
                                <div>
                                    <strong>{selectedYear}</strong>
                                    <span className="dir-id">Pick a month to see your payslip in chat</span>
                                </div>
                            </div>
                        )}
                        {selectedYear !== null && (
                            <div className="split-months">
                                {MONTHS.map((m, i) => (
                                    <button key={m} className="split-month" onClick={() => onPick(selectedYear, i + 1)}>
                                        <span className="split-month-name">{m}</span>
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

// ---------------------------------- Admin Employee Panel ----------------------------------
function AdminPanel({ onClose, onPicked }) {
    const [emp, setEmp] = useState([]);
    const [query, setQuery] = useState('');
    const [dept, setDept] = useState(null);
    const [selected, setSelected] = useState(null);
    const [loading, setLoading] = useState(true);
    const [tab, setTab] = useState('profile');
    const [detail, setDetail] = useState(null);
    const [att, setAtt] = useState(null);
    const [lev, setLev] = useState(null);
    const [sal, setSal] = useState(null);
    const [year, setYear] = useState(new Date().getFullYear());

    useEffect(() => {
        (async () => {
            try {
                const d = await API.adminEmployees();
                setEmp(d.employees || []);
            } catch { setEmp([]); }
            finally { setLoading(false); }
        })();
    }, []);

    const norm = st => String(st || '').toLowerCase();

    const yearsFrom = () => {
        try {
            const jd = detail?.profiles?.joining_date || '';
            const joinYear = jd ? parseInt(jd.slice(0, 4), 10) : new Date().getFullYear();
            const currentYear = new Date().getFullYear();
            const ys = [];
            for (let y = currentYear; y >= joinYear; y--) ys.push(y);
            return ys;
        } catch { return [new Date().getFullYear()]; }
    };

    const openEmployee = async (e) => {
        setSelected(e);
        setTab('profile');
        setDetail(null); setAtt(null); setLev(null); setSal(null);
        setYear(new Date().getFullYear());
        try { const rec = await API.adminEmployee(e.employee_id); setDetail(rec); } catch { setDetail(null); }
        API.adminAttendance(e.employee_id, new Date().getFullYear()).then(d => setAtt(d)).catch(() => setAtt(null));
        API.adminLeaves(e.employee_id).then(d => setLev(d)).catch(() => setLev(null));
        API.adminSalary(e.employee_id, new Date().getFullYear()).then(d => setSal(d)).catch(() => setSal(null));
        onPicked(`Opened the full employee record for <strong>${escapeXml(e.name)}</strong> (${escapeXml(e.employee_id)}).`);
    };

    const switchYear = (y) => {
        setYear(y);
        setAtt(null); setSal(null);
        if (selected) {
            API.adminAttendance(selected.employee_id, y).then(d => setAtt(d)).catch(() => setAtt(null));
            API.adminSalary(selected.employee_id, y).then(d => setSal(d)).catch(() => setSal(null));
        }
    };

    const filtered = emp.filter(e => {
        if (!query.trim()) return true;
        const q = query.toLowerCase();
        return [e.name, e.employee_id, e.department, e.job_title, e.email].join(' ').toLowerCase().includes(q);
    });
    const depts = {};
    filtered.forEach(e => { const k = e.department || 'Other'; (depts[k] = depts[k] || []).push(e); });
    const deptList = Object.entries(depts).sort((a, b) => a[0].localeCompare(b[0]));

    const profileView = () => {
        const p = detail?.profiles || {};
        const c = detail?.contacts || {};
        const l = detail?.locations || {};
        return (
            <div className="admin-detail">
                <div className="admin-profile-top">
                    <span className="dir-avatar lg">{selected.name.split(' ').map(x => x[0]).join('').slice(0, 2).toUpperCase()}</span>
                    <div>
                        <div className="dir-name">{selected.name}</div>
                        <div className="dir-id">{p.job_title} — {p.department}</div>
                        <div dangerouslySetInnerHTML={{ __html: statusPill(p.employment_status || selected.employment_status) }} />
                    </div>
                </div>
                <div className="dir-detail-grid">
                    <div className="card-box">
                        <div className="box-title">Profile</div>
                        <div className="row"><span>Employee ID</span> <strong>{p.employee_id || selected.employee_id}</strong></div>
                        <div className="row"><span>Employee Number</span> <strong>{p.employee_number}</strong></div>
                        <div className="row"><span>Department</span> <strong>{p.department}</strong></div>
                        <div className="row"><span>Job Title</span> <strong>{p.job_title}</strong></div>
                        <div className="row"><span>Employment Type</span> <strong>{p.employment_type}</strong></div>
                        <div className="row"><span>Joining Date</span> <strong>{p.joining_date}</strong></div>
                    </div>
                    <div className="card-box">
                        <div className="box-title">Contact</div>
                        <div className="row"><span>Email</span> <a href={`mailto:${c.email}`}>{c.email}</a></div>
                        <div className="row"><span>Phone</span> <a href={`tel:${c.phone}`}>{c.phone}</a></div>
                        <div className="row"><span>Extension</span> <strong>{c.extension}</strong></div>
                    </div>
                    <div className="card-box">
                        <div className="box-title">Work Location</div>
                        <div className="row"><span>Floor</span> <strong>{l.floor}</strong></div>
                        <div className="row"><span>Desk Number</span> <strong>{l.desk_number}</strong></div>
                        <div className="row"><span>Seat Status</span> <strong>{l.seat_status}</strong></div>
                    </div>
                </div>
            </div>
        );
    };

    const attendanceView = () => {
        if (!att) return <div className="explorer-loading">Loading attendance…</div>;
        const s = att.summary || {};
        const rows = (att.attendance || []).map(a => (
            <tr key={a.date}><td>{a.date}</td><td>{dayNameShort(a.date)}</td><td dangerouslySetInnerHTML={{ __html: statusPill(a.status) }} /><td>{a.check_in || '—'}</td><td>{a.check_out || '—'}</td><td className="num">{a.working_hours ?? '—'}</td></tr>
        ));
        return (
            <>
                <div className="admin-summary-sticky">
                    <div className="admin-stats">
                        <div className="admin-stat"><b>{s.total_days}</b><span>Days</span></div>
                        <div className="admin-stat"><b>{s.present}</b><span>Present</span></div>
                        <div className="admin-stat"><b>{s.late}</b><span>Late</span></div>
                        <div className="admin-stat"><b>{s.absent}</b><span>Absent</span></div>
                        <div className="admin-stat"><b>{s.leave}</b><span>Leave</span></div>
                        <div className="admin-stat"><b>{s.off ?? 0}</b><span>Off</span></div>
                        <div className="admin-stat"><b>{s.total_working_hours}</b><span>Hours</span></div>
                    </div>
                </div>
                <div className="admin-detail">
                    <div className="att-sec-title">Attendance — {year}</div>
                    {rows.length === 0 ? <p className="muted">No attendance records.</p> : (
                        <div className="table-wrap"><table><thead><tr><th>Date</th><th>Day</th><th>Status</th><th>In</th><th>Out</th><th>Hours</th></tr></thead><tbody>{rows}</tbody></table></div>
                    )}
                </div>
            </>
        );
    };

    const leavesView = () => {
        if (!lev) return <div className="explorer-loading">Loading leaves…</div>;
        const b = lev.balance || {};
        const c = lev.counts || {};
        const reqs = lev.requests || [];
        const pending = reqs.filter(r => norm(r.status) === 'pending');
        const approved = reqs.filter(r => norm(r.status) === 'approved');
        const rejected = reqs.filter(r => norm(r.status) === 'rejected');
        const tbl = (list) => list.length === 0
            ? <p className="muted">None.</p>
            : <div className="table-wrap"><table><thead><tr><th>ID</th><th>Type</th><th>Dates</th><th>Days</th><th>Status</th></tr></thead><tbody>
                {list.map(r => <tr key={r.leave_id} className={norm(r.status) === 'pending' ? 'att-pending-row' : ''}>
                    <td>{r.leave_id}</td><td>{r.type}</td><td>{r.from} → {r.to}</td><td className="num">{r.days}</td><td dangerouslySetInnerHTML={{ __html: statusPill(r.status) }} /></tr>)}
            </tbody></table></div>;
        return (
            <>
                <div className="admin-summary-sticky">
                    <div className="admin-stats">
                        <div className="admin-stat"><b>{b.annual}</b><span>Annual</span></div>
                        <div className="admin-stat"><b>{b.sick}</b><span>Sick</span></div>
                        <div className="admin-stat"><b>{b.casual}</b><span>Casual</span></div>
                        <div className="admin-stat"><b>{b.unpaid}</b><span>Unpaid</span></div>
                    </div>
                    <div className="att-summary">
                        <span className="att-chip">{c.total ?? 0} Requested</span>
                        <span className="att-chip pending"><b>{c.pending ?? 0}</b> Pending</span>
                        <span className="att-chip approved"><b>{c.approved ?? 0}</b> Approved</span>
                        <span className="att-chip rejected"><b>{c.rejected ?? 0}</b> Rejected</span>
                    </div>
                </div>
                <div className="admin-detail">
                    <div className="att-sec-title">Pending Leaves <span className="explorer-count">{pending.length}</span></div>
                    {tbl(pending)}
                    <div className="att-sec-title">Approved Leaves <span className="explorer-count">{approved.length}</span></div>
                    {tbl(approved)}
                    <div className="att-sec-title">Rejected Leaves <span className="explorer-count">{rejected.length}</span></div>
                    {tbl(rejected)}
                </div>
            </>
        );
    };

    const salaryView = () => {
        if (!sal) return <div className="explorer-loading">Loading salary…</div>;
        const st = sal.structure || {};
        const cur = st.currency || 'PKR';
        const slips = sal.payslips || [];
        const rows = slips.map(sp => (
            <tr key={sp.month}><td>{MONTHS[sp.month - 1]}</td><td className="num">{fmtMoney(sp.gross_salary)}</td><td className="num">{fmtMoney(sp.deductions)}</td><td className="num">{fmtMoney(sp.net_salary)}</td><td dangerouslySetInnerHTML={{ __html: statusPill(sp.status) }} /></tr>
        ));
        return (
            <>
                <div className="admin-summary-sticky">
                    <div className="dir-detail-grid">
                        <div className="card-box">
                            <div className="box-title">Salary Structure</div>
                            <div className="row"><span>Basic</span> <strong>{fmtMoney(st.basic)} {cur}</strong></div>
                            <div className="row"><span>Housing Allowance</span> <strong>{fmtMoney(st.housing_allowance)}</strong></div>
                            <div className="row"><span>Transport Allowance</span> <strong>{fmtMoney(st.transport_allowance)}</strong></div>
                            <div className="row"><span>Other Allowances</span> <strong>{fmtMoney(st.other_allowances)}</strong></div>
                            <div className="row"><span>Gross</span> <strong>{fmtMoney(st.gross_salary)}</strong></div>
                            <div className="row"><span>Deductions</span> <strong>{fmtMoney(st.deductions)}</strong></div>
                            <div className="row"><span>Net</span> <strong>{fmtMoney(st.net_salary)}</strong></div>
                        </div>
                    </div>
                </div>
                <div className="admin-detail">
                    <div className="att-sec-title">Payslips — {year}</div>
                    {rows.length === 0 ? <p className="muted">No payslips for this year.</p> : (
                        <div className="table-wrap"><table><thead><tr><th>Month</th><th>Gross</th><th>Deductions</th><th>Net</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table></div>
                    )}
                </div>
            </>
        );
    };

    if (!selected) {
        return (
            <div className="explorer-panel">
                <div className="explorer-head">
                    <span className="explorer-title">Admin — Employee Details <span className="explorer-count">{emp.length}</span></span>
                    <div className="head-search">
                        <span className="head-search-ic"><FaSearch /></span>
                        <input type="text" placeholder="Search name, ID, department…" value={query} onChange={(e) => setQuery(e.target.value)} />
                        {query && <button className="head-search-clear" onClick={() => setQuery('')} title="Clear"><FaTimes /></button>}
                    </div>
                    <button className="explorer-close" onClick={onClose} title="Close"><FaTimes /></button>
                </div>
                <div className="split-body">
                    {loading ? <div className="explorer-loading">Loading…</div> : (
                        <>
                            <div className="split-sidebar">
                                <div className="split-sidebar-title">Departments</div>
                                {deptList.length === 0 ? <div className="explorer-empty">No departments.</div> : deptList.map(d => (
                                    <button key={d[0]} className={`split-dept ${dept && dept[0] === d[0] ? 'active' : ''}`} onClick={() => setDept(d)}>
                                        <span className="split-dept-name">{d[0]}</span>
                                        <span className="split-dept-count">{d[1].length}</span>
                                    </button>
                                ))}
                            </div>
                            <div className="split-content">
                                {query.trim() ? (
                                    <>
                                        <div className="split-content-head"><strong>Search results</strong><span className="dir-id">{filtered.length} match{filtered.length !== 1 ? 'es' : ''}</span></div>
                                        <div className="split-employees">{filtered.map(e => (
                                            <button key={e.employee_id} className="dir-card-item" onClick={() => openEmployee(e)}>
                                                <span className="dir-avatar">{e.name.split(' ').map(p => p[0]).join('').slice(0, 2).toUpperCase()}</span>
                                                <span className="dir-item-main"><span className="dir-name">{e.name}</span><span className="dir-id">{e.employee_id} — {e.job_title}</span><span className="dir-dept">{e.department}</span></span>
                                            </button>
                                        ))}</div>
                                    </>
                                ) : !dept ? (
                                    <div className="split-placeholder"><FaArrowLeft /> Select a department, then an employee to open their full records</div>
                                ) : (
                                    <>
                                        <div className="split-content-head">
                                            <span className="dir-avatar">{dept[0].split(' ').map(x => x[0]).join('').slice(0, 2).toUpperCase()}</span>
                                            <div><strong>{dept[0]}</strong><span className="dir-id">{dept[1].length} employee{dept[1].length !== 1 ? 's' : ''}</span></div>
                                        </div>
                                        <div className="split-employees">{dept[1].map(e => (
                                            <button key={e.employee_id} className="dir-card-item" onClick={() => openEmployee(e)}>
                                                <span className="dir-avatar">{e.name.split(' ').map(p => p[0]).join('').slice(0, 2).toUpperCase()}</span>
                                                <span className="dir-item-main"><span className="dir-name">{e.name}</span><span className="dir-id">{e.employee_id} — {e.job_title}</span><span className="dir-dept">{e.department}</span></span>
                                            </button>
                                        ))}</div>
                                    </>
                                )}
                            </div>
                        </>
                    )}
                </div>
            </div>
        );
    }

    return (
        <div className="explorer-panel">
            <div className="explorer-head">
                <button className="dir-back admin-back" onClick={() => setSelected(null)}>← Employees</button>
                <span className="explorer-title">{(detail?.profiles?.first_name || '') ? `${detail.profiles.first_name} ${detail.profiles.last_name}` : selected.name} <span className="explorer-count">{selected.employee_id}</span></span>
                <div className="admin-year">
                    {(tab === 'attendance' || tab === 'salary') && (
                        <select className="year-select" value={year} onChange={(e) => switchYear(parseInt(e.target.value, 10))}>
                            {yearsFrom().map(y => <option key={y} value={y}>{y}</option>)}
                        </select>
                    )}
                </div>
                <button className="explorer-close" onClick={onClose} title="Close"><FaTimes /></button>
            </div>
            <div className="admin-tabs">
                {(['profile', 'attendance', 'leaves', 'salary']).map(t => (
                    <button key={t} className={`admin-tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
                        {t === 'profile' ? <><FaUser /> Profile</> : t === 'attendance' ? <><FaCalendarCheck /> Attendance</> : t === 'leaves' ? <><FaCalendar /> Leaves</> : <><FaMoneyBillWave /> Salary</>}
                    </button>
                ))}
            </div>
            <div className="admin-body">
                {tab === 'profile' && (detail ? profileView() : <div className="explorer-loading">Loading profile…</div>)}
                {tab === 'attendance' && attendanceView()}
                {tab === 'leaves' && leavesView()}
                {tab === 'salary' && salaryView()}
            </div>
        </div>
    );
}

// ------------------------- Admin Accounts Panel -------------------------
function AdminAccountsPanel({ onClose, onPicked }) {
    const [tab, setTab] = useState('accounts');
    const [accounts, setAccounts] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showPw, setShowPw] = useState({});
    const [editId, setEditId] = useState(null);
    const [form, setForm] = useState({ employee_id: '', username: '', password: '', account_type: 'Employee', account_status: 'Active' });
    const [busy, setBusy] = useState(false);
    const [msg, setMsg] = useState(null);
    const [query, setQuery] = useState('');

    const load = async () => {
        setLoading(true);
        setMsg(null);
        try {
            const d = await API.adminAccounts();
            setAccounts(d.accounts || []);
        } catch (err) {
            setMsg({ type: 'err', text: err.message });
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (tab === 'accounts') load();
    }, [tab]);

    const startEdit = (acc) => {
        setEditId(acc.user_id);
        setForm({
            employee_id: acc.employee_id,
            username: acc.username,
            password: acc.password || '',
            account_type: acc.account_type === 'Admin' ? 'Admin' : 'Employee',
            account_status: acc.account_status === 'Active' ? 'Active' : 'Inactive',
        });
        setMsg(null);
    };

    const removeAccount = async (acc) => {
        if (!window.confirm(`Delete the login for ${acc.username}? Only the credentials will be removed — the employee record stays untouched.`)) return;
        setBusy(true);
        setMsg(null);
        try {
            await API.adminDeleteAccount(acc.user_id);
            setMsg({ type: 'ok', text: `Deleted ${acc.username}'s login. The employee (${acc.employee_id}) record was kept.` });
            onPicked(`Deleted the login <strong>${escapeXml(acc.username)}</strong> for ${escapeXml(acc.name || acc.employee_id)}. Only its credentials were removed; the employee record is untouched.`);
            if (editId === acc.user_id) setEditId(null);
            await load();
        } catch (err) {
            setMsg({ type: 'err', text: err.message });
        } finally {
            setBusy(false);
        }
    };

    const save = async (e) => {
        e.preventDefault();
        setBusy(true);
        setMsg(null);
        try {
            const payload = {
                username: form.username,
                password: form.password,
                account_type: form.account_type,
                account_status: form.account_status,
            };
            if (editId === null) payload.employee_id = form.employee_id;
            const saved = editId === null
                ? await API.adminCreateAccount(payload)
                : await API.adminUpdateAccount(editId, payload);
            setMsg({ type: 'ok', text: `${editId === null ? 'Account added' : 'Account saved'} for ${saved.username}.` });
            onPicked(editId === null
                ? `Created login <strong>${escapeXml(saved.username)}</strong> for ${escapeXml(saved.name || saved.employee_id)} (${saved.account_type}).`
                : `Updated login <strong>${escapeXml(saved.username)}</strong> — type ${saved.account_type}, status ${saved.account_status}.`);
            setEditId(null);
            setForm({ employee_id: '', username: '', password: '', account_type: 'Employee', account_status: 'Active' });
            if (tab === 'accounts') await load();
        } catch (err) {
            setMsg({ type: 'err', text: err.message });
        } finally {
            setBusy(false);
        }
    };

    const filteredAccounts = accounts.filter(acc => {
        if (!query.trim()) return true;
        return [acc.name, acc.username, acc.employee_id, acc.account_type, acc.account_status]
            .join(' ')
            .toLowerCase()
            .includes(query.toLowerCase());
    });

    const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

    const formFields = (
        <form className="acct-form" onSubmit={save}>
            {editId === null && (
                <label className="acct-field">
                    <span>Employee ID</span>
                    <input type="text" value={form.employee_id} onChange={set('employee_id')} placeholder="e.g. EMP031" required />
                </label>
            )}
            <label className="acct-field">
                <span>Username</span>
                <input type="text" value={form.username} onChange={set('username')} required />
            </label>
            <label className="acct-field">
                <span>Password</span>
                <input type="text" value={form.password} onChange={set('password')} required />
            </label>
            <label className="acct-field">
                <span>Account Type</span>
                <select value={form.account_type} onChange={set('account_type')}>
                    <option value="Employee">User</option>
                    <option value="Admin">Admin</option>
                </select>
            </label>
            <label className="acct-field">
                <span>Account Status</span>
                <select value={form.account_status} onChange={set('account_status')}>
                    <option value="Active">Active</option>
                    <option value="Inactive">Inactive</option>
                </select>
            </label>
            {msg && <div className={`acct-msg ${msg.type === 'ok' ? 'ok' : 'err'}`}>{msg.text}</div>}
            <div className="acct-actions">
                <button className="acct-btn primary" type="submit" disabled={busy}>{busy ? 'Saving…' : editId === null ? 'Create Account' : 'Save Changes'}</button>
                {editId !== null && <button className="acct-btn" type="button" onClick={() => { setEditId(null); setMsg(null); }}>Cancel</button>}
            </div>
        </form>
    );

    return (
        <div className="explorer-panel">
            <div className="explorer-head">
                <span className="explorer-title">Manage Accounts <span className="explorer-count">{accounts.length}</span></span>
                {tab === 'accounts' && editId === null && (
                    <div className="head-search">
                        <span className="head-search-ic"><FaSearch /></span>
                        <input
                            type="text"
                            placeholder="Search accounts…"
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                        />
                        {query && <button className="head-search-clear" onClick={() => setQuery('')} title="Clear"><FaTimes /></button>}
                    </div>
                )}
                <div className="att-filters">
                    <button className={`att-filter ${tab === 'accounts' ? 'active' : ''}`} onClick={() => setTab('accounts')}><FaUsers /> Accounts</button>
                    <button className={`att-filter ${tab === 'add' ? 'active' : ''}`} onClick={() => { setTab('add'); setEditId(null); setMsg(null); }}><FaPlus /> Add Account</button>
                </div>
                <button className="explorer-close" onClick={onClose} title="Close"><FaTimes /></button>
            </div>

            {tab === 'add' ? (
                <div className="acct-body">
                    <div className="acct-title">Create a new login</div>
                    <p className="muted">Enter any Employee ID. If the ID doesn't exist yet, it's created automatically with a default name. Enter an ID that already has an account and you'll get a duplicate error (no two accounts per ID).</p>
                    {formFields}
                </div>
            ) : loading ? (
                <div className="explorer-loading">Loading accounts…</div>
            ) : accounts.length === 0 ? (
                <div className="explorer-empty">No accounts found.</div>
            ) : (
<div className="admin-body acct-body">
                    {msg && <div className={`acct-msg ${msg.type === 'ok' ? 'ok' : 'err'}`}>{msg.text}</div>}
                    {editId === null ? (
                        <div className="table-wrap">
                            <table className="acct-table">
                                    <thead>
                                        <tr>
                                            <th>Employee ID</th>
                                            <th>Name</th>
                                            <th>Username</th>
                                            <th>Password</th>
                                            <th>Account Type</th>
                                            <th>Status</th>
                                            <th></th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {filteredAccounts.map(acc => (
                                            <tr key={acc.user_id} className={editId === acc.user_id ? 'editing' : ''}>
                                                <td>{acc.employee_id}</td>
                                                <td className="acct-name" title={acc.name || ''}>{acc.name || '—'}</td>
                                                <td>{acc.username}</td>
                                                <td className="acct-pw">
                                                    <span className={showPw[acc.user_id] ? '' : 'pw-mask'}>{showPw[acc.user_id] ? (acc.password || '—') : '••••••••'}</span>
                                                    <button className="pw-toggle" title={showPw[acc.user_id] ? 'Hide password' : 'Show password'} onClick={() => setShowPw(prev => ({ ...prev, [acc.user_id]: !prev[acc.user_id] }))}>
                                                        {showPw[acc.user_id] ? <FaEyeSlash /> : <FaEye />}
                                                    </button>
                                                </td>
                                                <td>
                                                    <span className={`pill-tag ${acc.account_type === 'Admin' ? 'success' : 'neutral'}`}>{acc.account_type === 'Admin' ? 'Admin' : 'User'}</span>
                                                </td>
                                                <td dangerouslySetInnerHTML={{ __html: statusPill(acc.account_status) }} />
                                                <td className="acct-actions-cell">
                                                    <div className="row-actions">
                                                        <button className="row-icon-btn edit" title={`Edit ${acc.username}`} onClick={() => startEdit(acc)}><FaPencilAlt /></button>
                                                        <button className="row-icon-btn danger" title={`Delete login for ${acc.username}`} onClick={() => removeAccount(acc)} disabled={busy}><FaTrashAlt /></button>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                                {filteredAccounts.length === 0 && query.trim() && (
                                    <div className="explorer-empty acct-search-empty">No accounts match “{query.trim()}”.</div>
                                )}
                            </div>
                        ) : (
                        <div className="acct-edit-card">
                            <div className="acct-title">Edit account — {form.username}</div>
                            {formFields}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

// ------------------------- Admin Documents Panel -------------------------
function AdminDocumentsPanel({ onClose, onPicked }) {
    const [tab, setTab] = useState('documents');
    const [documents, setDocuments] = useState([]);
    const [categories, setCategories] = useState([]);
    const [dept, setDept] = useState(null);
    const [query, setQuery] = useState('');
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [aiBusy, setAiBusy] = useState({});
    const [msg, setMsg] = useState(null);
    const [form, setForm] = useState({ name: '', category: '', newCategory: '', aiForChat: false });
    const [otherOpen, setOtherOpen] = useState(false);
    const [aiStatusFilter, setAiStatusFilter] = useState(null);

    const load = async () => {
        setLoading(true);
        setMsg(null);
        try {
            const [docRes, catRes, aiRes] = await Promise.all([
                API.documents(null),
                API.adminCategories(),
                API.adminDocumentStatus().catch(() => ({ documents: {} })),
            ]);
            const aiStatus = aiRes.documents || {};
            const docs = (docRes.documents || []).map(doc => ({
                ...doc,
                ai_enabled: aiStatus[doc.document_id]?.ai_enabled ?? doc.ai_enabled,
                ai_status: aiStatus[doc.document_id]?.ai_status ?? doc.ai_status ?? 'not_indexed',
            }));
            setDocuments(docs);
            setCategories(catRes.categories || []);
            if (dept && !docs.some(d => (d.category || '') === dept)) setDept(null);
        } catch (err) {
            setMsg({ type: 'err', text: err.message });
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (tab === 'documents' || tab === 'ai') load();
    }, [tab]);

    const filtered = documents.filter(it => {
        if (!query.trim()) return true;
        return [it.name, it.category, it.type, it.document_id, it.access].join(' ').toLowerCase().includes(query.toLowerCase());
    });

    const groupMap = {};
    filtered.forEach(it => {
        const k = it.category || 'Other';
        (groupMap[k] = groupMap[k] || []).push(it);
    });
    const groupList = Object.entries(groupMap).sort((a, b) => a[0].localeCompare(b[0]));

    const removeDocument = async (doc) => {
        if (!window.confirm(`Delete the document "${doc.name}"? This removes it from the documents section and deletes its file from storage.`)) return;
        setBusy(true);
        setMsg(null);
        try {
            const res = await API.adminDeleteDocument(doc.document_id);
            const catMsg = res.removed_category
                ? ` The <strong>${escapeXml(doc.category)}</strong> category was also removed (no documents left).`
                : '';
            setMsg({ type: 'ok', text: `Deleted "${doc.name}".${res.removed_category ? ' Category removed.' : ''}` });
            onPicked(`Deleted document <strong>${escapeXml(doc.name)}</strong> (${escapeXml(doc.category)}).${catMsg}`);
            await load();
        } catch (err) {
            setMsg({ type: 'err', text: err.message });
        } finally {
            setBusy(false);
        }
    };

    // Enables or disables a document for AI chat, then reflects its status.
    const toggleAI = async (doc) => {
        const targetEnabled = !doc.ai_enabled;
        setAiBusy(prev => ({ ...prev, [doc.document_id]: true }));
        setMsg(null);
        // Optimistically reflect the intent while the request runs.
        setDocuments(prev => prev.map(d =>
            d.document_id === doc.document_id
                ? { ...d, ai_enabled: targetEnabled, ai_status: targetEnabled ? 'indexing' : 'not_indexed' }
                : d
        ));
        try {
            const res = await API.adminSetDocumentAI(doc.document_id, targetEnabled);
            setDocuments(prev => prev.map(d =>
                d.document_id === doc.document_id
                    ? { ...d, ai_enabled: res.ai_enabled, ai_status: res.ai_status }
                    : d
            ));
            if (res.ai_enabled && res.ai_status === 'error') {
                setMsg({ type: 'err', text: `Error indexing "${doc.name}": ${escapeXml(res.error || 'unknown error')}` });
            } else if (res.ai_enabled) {
                setMsg({ type: 'ok', text: `Enabled "${doc.name}" for AI chat.` });
                onPicked(`Indexed <strong>${escapeXml(doc.name)}</strong> for AI chat (${res.chunks_written ?? 0} chunks).`);
            } else {
                setMsg({ type: 'ok', text: `Disabled AI for "${doc.name}".` });
            }
        } catch (err) {
            setMsg({ type: 'err', text: err.message });
            await load();
        } finally {
            setAiBusy(prev => ({ ...prev, [doc.document_id]: false }));
        }
    };

    const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

    const save = async (e) => {
        e.preventDefault();
        const category = otherOpen ? form.newCategory : form.category;
        if (!category.trim()) {
            setMsg({ type: 'err', text: 'Please pick a category or enter a new one.' });
            return;
        }
        if (otherOpen) {
            const existing = categories.find(c => c.toLowerCase() === form.newCategory.trim().toLowerCase());
            if (existing) {
                setMsg({ type: 'err', text: `Category "${existing}" already exists. Please pick it from the dropdown instead of creating a duplicate.` });
                return;
            }
        }
        const fileInput = document.getElementById('admin-doc-file');
        if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
            setMsg({ type: 'err', text: 'Please choose a file to upload.' });
            return;
        }
        setBusy(true);
        setMsg(null);
        try {
            const fd = new FormData();
            fd.append('name', form.name);
            fd.append('category', category);
            fd.append('access', 'public');
            fd.append('file', fileInput.files[0]);
            const saved = await API.adminUploadDocument(fd);
            let statusMsg = `Document "${saved.name}" added under ${saved.category}.`;
            let chatMsg = `Uploaded document <strong>${escapeXml(saved.name)}</strong> (${escapeXml(saved.category)}).`;
            if (form.aiForChat) {
                try {
                    const aiRes = await API.adminSetDocumentAI(saved.document_id, true);
                    if (aiRes.ai_status === 'ready') {
                        statusMsg += ` Enabled for AI chat (${aiRes.chunks_written ?? 0} chunks).`;
                        chatMsg += ` Indexed for AI chat (${aiRes.chunks_written ?? 0} chunks).`;
                    } else if (aiRes.ai_status === 'error') {
                        statusMsg += ` AI indexing failed: ${escapeXml(aiRes.error || 'unknown error')}.`;
                    }
                } catch (aiErr) {
                    statusMsg += ` AI indexing failed: ${aiErr.message}.`;
                }
            }
            setMsg({ type: 'ok', text: statusMsg });
            onPicked(chatMsg);
            setForm({ name: '', category: '', newCategory: '', aiForChat: false });
            setOtherOpen(false);
            fileInput.value = '';
            if (tab === 'documents') await load();
        } catch (err) {
            setMsg({ type: 'err', text: err.message });
        } finally {
            setBusy(false);
        }
    };

    const formFields = (
        <form className="acct-form" onSubmit={save}>
            <label className="acct-field">
                <span>Document Name</span>
                <input type="text" value={form.name} onChange={set('name')} placeholder="e.g. Expense Policy" required />
            </label>
            <label className="acct-field">
                <span>Category</span>
                {otherOpen ? (
                    <>
                        <input type="text" value={form.newCategory} onChange={set('newCategory')} placeholder="Enter a new category name…" autoFocus />
                        <button type="button" className="acct-btn" onClick={() => { setOtherOpen(false); setForm(f => ({ ...f, newCategory: '' })); }}>← Choose an existing category</button>
                    </>
                ) : (
                    <select value={form.category} onChange={(e) => { if (e.target.value === '__other__') { setOtherOpen(true); } else { setForm(f => ({ ...f, category: e.target.value })); } }} required>
                        <option value="" disabled>Select a category…</option>
                        {categories.map(c => <option key={c} value={c}>{c}</option>)}
                        <option value="__other__">Other — create a new category</option>
                    </select>
                )}
            </label>
            <label className="acct-field">
                <span>File</span>
                <input id="admin-doc-file" type="file" accept=".pdf,.doc,.docx,.txt,.xls,.xlsx,.png,.jpg,.jpeg" required />
            </label>
            <label className="acct-field acct-ai-row">
                <span className={`ai-toggle-btn ${form.aiForChat ? 'active' : ''}`} onClick={() => setForm(f => ({ ...f, aiForChat: !f.aiForChat }))} role="button" tabIndex={0}>AI</span>
            </label>
            {msg && <div className={`acct-msg ${msg.type === 'ok' ? 'ok' : 'err'}`}>{msg.text}</div>}
            <div className="acct-actions">
                <button className="acct-btn primary" type="submit" disabled={busy}>{busy ? 'Uploading…' : 'Save Document'}</button>
            </div>
        </form>
    );

    const docCard = (it, showDelete = true) => (
        <div key={it.document_id} className="dir-card-item doc-admin-item">
            <span className="dir-avatar"><FaFileAlt /></span>
            <span className="dir-item-main">
                <span className="dir-name" title={it.name}>{it.name}</span>
                <span className="dir-id">{it.type} · {it.document_id}</span>
                <span className={`ai-status-badge ai-${it.ai_status}`}>
                    {it.ai_status === 'ready' ? 'Ready for AI' : it.ai_status === 'indexing' ? 'Indexing…' : it.ai_status === 'error' ? 'Error' : 'Not indexed'}
                </span>
            </span>
            <div className="doc-ai-toggle" title={it.ai_enabled ? 'Disable this PDF for AI chat' : 'Use this PDF for AI chat'}>
                <label className="ai-switch">
                    <input
                        type="checkbox"
                        checked={!!it.ai_enabled}
                        disabled={aiBusy[it.document_id]}
                        onChange={() => toggleAI(it)}
                    />
                    <span className="ai-slider"></span>
                </label>
                <span className="ai-toggle-label">{it.ai_enabled ? 'AI ON' : 'AI OFF'}</span>
            </div>
            {showDelete && <button className="acct-btn small danger doc-delete-btn" onClick={() => removeDocument(it)} disabled={busy} title={`Delete "${it.name}"`}><FaTrashAlt /></button>}
        </div>
    );

    return (
        <div className="explorer-panel">
            <div className="explorer-head">
                <span className="explorer-title">Manage Documents <span className="explorer-count">{documents.length}</span></span>
                {(tab === 'documents' || tab === 'ai') && (
                    <div className="head-search">
                        <span className="head-search-ic"><FaSearch /></span>
                        <input
                            type="text"
                            placeholder="Search documents…"
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                        />
                        {query && <button className="head-search-clear" onClick={() => setQuery('')} title="Clear"><FaTimes /></button>}
                    </div>
                )}
                <div className="att-filters">
                    <button className={`att-filter ${tab === 'documents' ? 'active' : ''}`} onClick={() => setTab('documents')}><FaCopy /> Documents</button>
                    <button className={`att-filter ${tab === 'ai' ? 'active' : ''}`} onClick={() => { setTab('ai'); setAiStatusFilter(null); }}><FaStar /> AI PDFs</button>
                    <button className={`att-filter ${tab === 'add' ? 'active' : ''}`} onClick={() => { setTab('add'); setMsg(null); }}><FaPlus /> Add Docs</button>
                </div>
                <button className="explorer-close" onClick={onClose} title="Close"><FaTimes /></button>
            </div>

            {tab === 'add' ? (
                <div className="acct-body">
                    <div className="acct-title">Upload a new company document</div>
                    {formFields}
                </div>
            ) : loading ? (
                <div className="explorer-loading">Loading documents…</div>
            ) : tab === 'ai' ? (() => {
                const aiDocs = filtered;  // search applies to both tabs
                const readyEnabled = aiDocs.filter(d => d.ai_status === 'ready' && d.ai_enabled);
                const readyDisabled = aiDocs.filter(d => d.ai_status === 'ready' && !d.ai_enabled);
                const inProgress = aiDocs.filter(d => d.ai_status === 'indexing' || d.ai_status === 'error');
                const aiGroups = [
                    { key: 'ready-enabled', label: 'Ready Enabled PDFs', docs: readyEnabled },
                    { key: 'ready-disabled', label: 'Ready but Disabled', docs: readyDisabled },
                    { key: 'in-progress', label: 'In Progress', docs: inProgress },
                ];
                const selectedGroup = aiGroups.find(g => g.key === aiStatusFilter);
                return (
                    <>
                        {msg && <div className="acct-msg widget-msg" style={{ margin: '10px 14px 0' }}>{msg.text}</div>}
                        <div className="split-widget admin-doc-widget">
                            <div className="split-body">
                                <div className="split-sidebar">
                                    <div className="split-sidebar-title">AI Status</div>
                                    {documents.length === 0 ? (
                                        <div className="explorer-empty">No documents yet.</div>
                                    ) : (
                                        aiGroups.map(g => (
                                            <button
                                                key={g.key}
                                                className={`split-dept ${aiStatusFilter === g.key ? 'active' : ''}`}
                                                onClick={() => setAiStatusFilter(g.key)}
                                            >
                                                <span className="split-dept-name">{g.label}</span>
                                                <span className="split-dept-count">{g.docs.length}</span>
                                            </button>
                                        ))
                                    )}
                                </div>
                                <div className="split-content">
                                    {!aiStatusFilter ? (
                                        <div className="split-placeholder"><FaArrowLeft /> Select a status to see its documents</div>
                                    ) : (
                                        <>
                                            <div className="split-content-head">
                                                <span className="dir-avatar"><FaStar /></span>
                                                <div>
                                                    <strong>{selectedGroup?.label}</strong>
                                                    <span className="dir-id">{selectedGroup?.docs.length} document{selectedGroup?.docs.length !== 1 ? 's' : ''}</span>
                                                </div>
                                            </div>
                                            <div className="split-employees">
                                                {(selectedGroup?.docs || []).map(it => docCard(it, false))}
                                            </div>
                                        </>
                                    )}
                                </div>
                            </div>
                        </div>
                    </>
                );
            })() : (
                <>
                    {msg && <div className="acct-msg widget-msg" style={{ margin: '10px 14px 0' }}>{msg.text}</div>}
                    <div className="split-widget admin-doc-widget">
                        <div className="split-body">
                            <div className="split-sidebar">
                                <div className="split-sidebar-title">Categories</div>
                                {groupList.length === 0 ? (
                                    <div className="explorer-empty">No categories.</div>
                                ) : (
                                    groupList.map(d => (
                                        <button
                                            key={d[0]}
                                            className={`split-dept ${dept === d[0] ? 'active' : ''}`}
                                            onClick={() => setDept(d[0])}
                                        >
                                            <span className="split-dept-name">{d[0]}</span>
                                            <span className="split-dept-count">{d[1].length}</span>
                                        </button>
                                    ))
                                )}
                            </div>
                            <div className="split-content">
                                {!dept ? (
                                    <div className="split-placeholder">👈 Select a category to see its documents</div>
                                ) : (
                                    <>
                                        <div className="split-content-head">
                                            <span className="dir-avatar">📄</span>
                                            <div>
                                                <strong>{dept}</strong>
                                                <span className="dir-id">{(groupMap[dept] || []).length} document{(groupMap[dept] || []).length !== 1 ? 's' : ''} in this category</span>
                                            </div>
                                        </div>
                                        <div className="split-employees">
                                            {(groupMap[dept] || []).map(it => docCard(it))}
                                        </div>
                                    </>
                                )}
                            </div>
                        </div>
                    </div>
                </>
            )}
        </div>
    );
}

// ---------------------------------- App ----------------------------------
export default function App() {
    const [isDarkMode, setIsDarkMode] = useState(false);
    const [messages, setMessages] = useState([]);
    const [inputValue, setInputValue] = useState('');
    const [isPopoverOpen, setIsPopoverOpen] = useState(false);
    const [isProfileOpen, setIsProfileOpen] = useState(false);
    const [subOptions, setSubOptions] = useState([]);
    const [explorer, setExplorer] = useState(null);
    const [salaryPanel, setSalaryPanel] = useState(false);
    const [attendancePanel, setAttendancePanel] = useState(false);
    const [leavesPanel, setLeavesPanel] = useState(false);
    const [adminPanel, setAdminPanel] = useState(false);
    const [accountsPanel, setAccountsPanel] = useState(false);
    const [documentsPanel, setDocumentsPanel] = useState(false);
    const [loading, setLoading] = useState(false);
    const [customRange, setCustomRange] = useState(null);
    const [authChecking, setAuthChecking] = useState(true);
    const [user, setUser] = useState(null);
    const [enableAI, setEnableAI] = useState(false);
    const [aiSelectedDoc, setAiSelectedDoc] = useState(null);
    const [aiDocs, setAiDocs] = useState([]);
    const chatEndRef = useRef(null);
    const popoverRef = useRef(null);

    useEffect(() => {
        if (isDarkMode) document.body.setAttribute('data-theme', 'dark');
        else document.body.removeAttribute('data-theme');
    }, [isDarkMode]);

    useEffect(() => {
        const frame = requestAnimationFrame(() => {
            const el = chatEndRef.current;
            if (!el) return;
            el.scrollIntoView({ behavior: 'smooth', block: 'end' });
        });
        return () => cancelAnimationFrame(frame);
    }, [messages, subOptions, explorer, salaryPanel, attendancePanel, leavesPanel, adminPanel]);

    useEffect(() => {
        const onClickOutside = (e) => { if (popoverRef.current && !popoverRef.current.contains(e.target)) setIsPopoverOpen(false); };
        document.addEventListener('mousedown', onClickOutside);
        return () => document.removeEventListener('mousedown', onClickOutside);
    }, []);

    useEffect(() => {
        let alive = true;
        (async () => {
            const token = sessionStorage.getItem('hr_token');
            if (!token) {
                sessionStorage.removeItem('hr_user');
                if (alive) setAuthChecking(false);
                return;
            }
            try {
                const me = await API.me();
                const stored = JSON.parse(sessionStorage.getItem('hr_user') || 'null') || {};
                if (alive) {
                    setUser({ ...me, account_type: (stored.account_type || me.account_type || '').toLowerCase() });
                }
            } catch {
                sessionStorage.removeItem('hr_token');
                sessionStorage.removeItem('hr_user');
            } finally {
                if (alive) setAuthChecking(false);
            }
        })();
        return () => { alive = false; };
    }, []);

    useEffect(() => {
        const onUnauthorized = () => { setUser(null); setMessages([]); setSubOptions([]); setExplorer(null); };
        window.addEventListener('hr-unauthorized', onUnauthorized);
        return () => window.removeEventListener('hr-unauthorized', onUnauthorized);
    }, []);

    const name = user?.name || '';
    const initials = name.split(' ').map(p => p[0]).join('').slice(0, 2).toUpperCase() || 'HR';
    const isAdmin = user?.account_type === 'admin';
    const allOptions = isAdmin ? [...OPTIONS, ADMIN_OPTION, MANAGE_ACCOUNTS_OPTION, MANAGE_DOCUMENTS_OPTION] : OPTIONS;

    const pushBotText = (html) => {
        setMessages(prev => [...prev, { sender: 'bot', html, id: Date.now() + Math.random(), done: true }]);
    };

    // Pushes a bot message in a "thinking" state and returns a resolver that
    // replaces its placeholder content with the final answer once available.
    const pushBotThinking = (placeholder) => {
        const id = Date.now() + Math.random();
        setMessages(prev => [...prev, { sender: 'bot', html: placeholder, id, async: true, done: false }]);
        return (html) => {
            setMessages(prev => prev.map(m => m.id === id ? { ...m, html, async: true, done: true } : m));
        };
    };

    const pushBotOptions = (html, options) => {
        setMessages(prev => [...prev, { sender: 'bot', html, options, id: Date.now() + Math.random(), done: true }]);
    };

    const clearSubOptions = () => { setSubOptions([]); setExplorer(null); setSalaryPanel(false); setAttendancePanel(false); setLeavesPanel(false); setAdminPanel(false); setAccountsPanel(false); setDocumentsPanel(false); setCustomRange(null); };

    const naturalOptionText = (optId, optTitle) => {
        switch (optId) {
            case 'attendance': return 'Show me my attendance';
            case 'leaves': return 'Show me my leave details';
            case 'salary': return 'Show me my salary';
            case 'services': return 'Show me the employee directory';
            case 'documents': return 'Show me the company documents';
            case 'admin': return 'Show me an employee\'s full records';
            case 'manageAccounts': return 'Show me the account management panel';
            case 'manageDocuments': return 'Show me the document management panel';
            default: return optTitle;
        }
    };

    const handleSelectOption = (optId, optTitle) => {
        setIsPopoverOpen(false);
        setMessages(prev => [...prev, { sender: 'user', text: naturalOptionText(optId, optTitle) }]);
        if (optId === 'admin') {
            setSubOptions([]);
            setExplorer(null);
            setCustomRange(null);
            setAdminPanel(true);
            pushBotText(`Here's the <strong>admin employee panel</strong>. Pick a <strong>department</strong> from the sidebar, then select an <strong>employee</strong> to open their full records.`);
            return;
        }
        if (optId === 'manageAccounts') {
            setSubOptions([]);
            setExplorer(null);
            setCustomRange(null);
            setAccountsPanel(true);
            pushBotText(`Here's the <strong>account management panel</strong>. <strong>Accounts</strong> lists every login with its credentials so you can edit them, and <strong>Add Account</strong> creates a new login for an employee.`);
            return;
        }
        if (optId === 'manageDocuments') {
            setSubOptions([]);
            setExplorer(null);
            setCustomRange(null);
            setDocumentsPanel(true);
            pushBotText(`Here's the <strong>document management panel</strong>. <strong>Documents</strong> lists every company document by category so you can remove them, and <strong>Add Document</strong> uploads a new file (with an optional <strong>Other</strong> category) that every user can then find in the documents section.`);
            return;
        }
        if (optId === 'leaves') {
            setSubOptions([]);
            setExplorer(null);
            setCustomRange(null);
            setLeavesPanel(true);
            pushBotText(`Here's your <strong>leaves panel</strong>. Check your <strong>leave balance</strong> or pick a <strong>year</strong> and <strong>month</strong> to see your leave history.`);
            return;
        }
        if (optId === 'attendance') {
            setSubOptions([]);
            setExplorer(null);
            setCustomRange(null);
            setAttendancePanel(true);
            pushBotText(`Here's your <strong>attendance panel</strong>. Pick a <strong>quick filter</strong> like Today or This Month, or choose a <strong>year</strong> to drill into its months.`);
            return;
        }
        if (optId === 'salary') {
            setSubOptions([]);
            setExplorer(null);
            setCustomRange(null);
            setSalaryPanel(true);
            pushBotText(`Here's your <strong>salary panel</strong>. Open <strong>My Payslips</strong> to pick a year and month, or <strong>My Salary Breakdown</strong> to see your earnings at a glance.`);
            return;
        }
        if (EXPLORER_OPTIONS.has(optId)) {
            setExplorer({ type: optId === 'services' ? 'employees' : optId });
            setSubOptions([]);
            pushBotText(optId === 'services'
                ? `Here's the <strong>employee directory</strong>. Pick a <strong>department</strong> from the sidebar, then select an <strong>employee</strong> to see their full details here in the chat.`
                : `Here's the <strong>company documents</strong>. Pick a <strong>category</strong> from the sidebar to see its documents, or use the search above. Click any document for a full preview.`);
            return;
        }
        setExplorer(null);
        const subs = buildSubOptions(optId, user);
        setSubOptions([]);
        pushBotOptions(`Great! What would you like to see?`, subs);
    };

    const naturalSubText = (sub) => {
        switch (sub.action) {
            case 'attendanceToday': return 'Show me my attendance for today';
            case 'attendanceWeek': return sub.value === 'week' ? 'Show me my attendance for this week' : 'Show me my attendance for last week';
            case 'attendanceCustom': return 'Show me my attendance for a custom range';
            case 'attendanceRange': return `Show me my attendance from ${sub.value?.from} to ${sub.value?.to}`;
            case 'leavesBalance': return 'Show me my leave balance';
            case 'leavesHistory': return `Show me my leave history for ${MONTHS[sub.value?.month - 1]} ${sub.value?.year}`;
            default: return sub.label;
        }
    };

    const handleSelectSubOption = (sub) => {
        setMessages(prev => [...prev, { sender: 'user', text: naturalSubText(sub) }]);
        if (sub.action === 'attendanceCustom') {
            const now = new Date();
            setSubOptions([]);
            setCustomRange({
                from: toISO(addDays(now, -30)),
                to: toISO(now),
                action: sub.action,
            });
            return;
        }
        runSubAction(sub.action, sub.value);
    };

    const handleSalaryBreakdown = () => {
        setMessages(prev => [...prev, { sender: 'user', text: 'Show me my salary breakdown' }]);
        runSubAction('salaryDetail', null);
    };

    const handleSalaryPick = (year, month) => {
        const label = `Show me my payslip for ${MONTHS[month - 1]} ${year}`;
        setMessages(prev => [...prev, { sender: 'user', text: label }]);
        runSubAction('salaryPayslip', { year, month });
    };

    const handleAttendancePick = (label, from, to, heading) => {
        setMessages(prev => [...prev, { sender: 'user', text: label }]);
        runSubAction('attendanceRange', { from, to, heading });
    };

    const handleLeaveBalance = () => {
        setMessages(prev => [...prev, { sender: 'user', text: 'Show me my leave balance' }]);
        runSubAction('leavesBalance', null);
    };

    const handleLeavePick = (year, month) => {
        const label = `Show me my leave history for ${MONTHS[month - 1]} ${year}`;
        setMessages(prev => [...prev, { sender: 'user', text: label }]);
        runSubAction('leavesHistory', { year, month });
    };

    const runSubAction = async (action, value) => {
        setSubOptions([]);
        setLoading(true);
        try {
            const visual = await runAction(action, value, { user });
            pushBotText(visual.html);
        } catch (err) {
            pushBotText(`<div class="error"><strong>Error:</strong> ${escapeXml(err.message)}</div>`);
        } finally {
            setLoading(false);
        }
    };

    const runCustomRange = () => {
        if (!customRange?.from || !customRange?.to) return;
        setMessages(prev => [...prev, { sender: 'user', text: `Custom range: ${customRange.from} → ${customRange.to}` }]);
        setCustomRange(null);
        runSubAction('attendanceRange', { from: customRange.from, to: customRange.to });
    };

    const handlePreview = async (type, item) => {
        const title = type === 'employees'
            ? `Show me the profile of ${item.name} from ${item.department}`
            : `Show me more about the ${item.name} document`;
        setMessages(prev => [...prev, { sender: 'user', text: title }]);
        setLoading(true);
        try {
            const visual = await runPreview(type, item, { user });
            pushBotText(visual.html);
        } catch (err) {
            pushBotText(`<div class="error"><strong>Error:</strong> ${escapeXml(err.message)}</div>`);
        } finally {
            setLoading(false);
        }
    };

    const handlePick = async (emp) => {
        setMessages(prev => [...prev, { sender: 'user', text: `Show me the profile of ${emp.name} from ${emp.department}` }]);
        setLoading(true);
        try {
            const visual = await runPreview('employees', emp, { user });
            pushBotText(visual.html);
        } catch (err) {
            pushBotText(`<div class="error"><strong>Error:</strong> ${escapeXml(err.message)}</div>`);
        } finally {
            setLoading(false);
        }
    };

    const handleNewChat = () => {
        setIsPopoverOpen(false);
        setMessages([]);
        setInputValue('');
        clearSubOptions();
    };

    const loadAiDocs = async () => {
        try {
            const [docRes, aiRes] = await Promise.all([
                API.documents(null),
                API.adminDocumentStatus().catch(() => ({ documents: {} })),
            ]);
            const aiStatus = aiRes.documents || {};
            const ready = (docRes.documents || [])
                .map(doc => ({
                    ...doc,
                    ai_enabled: aiStatus[doc.document_id]?.ai_enabled ?? doc.ai_enabled,
                    ai_status: aiStatus[doc.document_id]?.ai_status ?? doc.ai_status ?? 'not_indexed',
                }))
                .filter(d => d.ai_status === 'ready' && d.ai_enabled);
            setAiDocs(ready);
        } catch { /* ignore */ }
    };

    const handleSendAI = async (text) => {
        clearSubOptions();

        // Push a status bubble (will be updated as SSE status events arrive)
        const statusId = Date.now() + Math.random();
        setMessages(prev => [...prev, {
            sender: 'bot',
            html: '<span class="ai-status-text">Thinking about your question…</span><span class="ai-status-dots"><span></span><span></span><span></span></span>',
            id: statusId,
            async: true,
            done: false,
            isStatus: true,
        }]);

        const resolve = pushBotThinking(''); // placeholder; will be replaced when tokens arrive

        // Replace the placeholder with a streaming bubble that tokens append into
        let answerBuffer = '';
        let firstToken = false;
        const streamingId = Date.now() + Math.random();

        try {
            // Build conversation history for follow-up resolution
            const history = messages
                .filter(m => m.text || m.html)
                .slice(-6)
                .map(m => ({
                    sender: m.sender,
                    text: m.text || '',
                }));

            const stream = API.chatAIStream(text, aiSelectedDoc, history);
            let sources = [];
            let grounded = false;
            let answer = '';

            for await (const frame of stream) {
                if (frame.type === 'status') {
                    // Update the status bubble text
                    setMessages(prev => prev.map(m =>
                        m.id === statusId
                            ? { ...m, html: `<span class="ai-status-text">${escapeXml(frame.message)}</span><span class="ai-status-dots"><span></span><span></span><span></span></span>` }
                            : m
                    ));
                } else if (frame.type === 'token') {
                    if (!firstToken) {
                        // First token arrived — remove status bubble, create streaming answer bubble
                        firstToken = true;
                        setMessages(prev => prev.filter(m => m.id !== statusId));
                        setMessages(prev => [...prev, {
                            sender: 'bot',
                            html: '',
                            id: streamingId,
                            async: true,
                            done: false,
                        }]);
                    }
                    answerBuffer += frame.text;
                    // Render accumulated markdown into the streaming bubble
                    setMessages(prev => prev.map(m =>
                        m.id === streamingId
                            ? { ...m, html: `<div class="ai-answer"><div class="ai-answer-body">${renderMarkdown(answerBuffer)}</div></div>` }
                            : m
                    ));
                } else if (frame.type === 'done') {
                    answer = frame.answer || answerBuffer;
                    sources = frame.sources || [];
                    grounded = frame.grounded ?? false;
                }
            }

            // Finalize: replace streaming bubble with complete answer
            let sourcesHtml = '';
            if (sources.length > 0) {
                const sourceItems = sources
                    .map(s => {
                        const doc = escapeXml(s.document_name || 'Unknown document');
                        const page = s.page ? `, page ${escapeXml(String(s.page))}` : '';
                        const url = s.file_url;
                        if (url) {
                            return `<a class="ai-source ai-source-link" href="${escapeXml(url)}" target="_blank" rel="noopener noreferrer" title="Open PDF${page}">📄 ${doc}${page}</a>`;
                        }
                        return `<span class="ai-source">📄 ${doc}${page}</span>`;
                    })
                    .join('');
                sourcesHtml = `<div class="ai-sources"><strong>Sources:</strong> ${sourceItems}</div>`;
            }

            const notGroundedNote = grounded
                ? ''
                : '<div class="muted">This answer is not grounded — the enabled documents did not contain enough information.</div>';

            // If streaming never produced tokens, fall back to showing the done answer
            if (!firstToken) {
                setMessages(prev => prev.filter(m => m.id !== statusId));
                resolve(`
                    <div class="ai-answer">
                        <div class="ai-answer-body">${renderMarkdown(answer)}</div>
                        ${sourcesHtml}
                        ${notGroundedNote}
                    </div>
                `);
            } else {
                // Update the streaming bubble to include sources
                setMessages(prev => prev.map(m =>
                    m.id === streamingId
                        ? {
                            ...m,
                            async: true,
                            done: true,
                            html: `<div class="ai-answer"><div class="ai-answer-body">${renderMarkdown(answer || answerBuffer)}</div>${sourcesHtml}${notGroundedNote}</div>`,
                        }
                        : m
                ));
            }
        } catch (err) {
            // Remove status bubble on error
            setMessages(prev => prev.filter(m => m.id !== statusId));
            if (firstToken) {
                setMessages(prev => prev.filter(m => m.id !== streamingId));
            }
            resolve(`<div class="error"><strong>AI Error:</strong> ${escapeXml(err.message)}</div>`);
        } finally {
            setLoading(false);
        }
    };

    const handleSendMessage = (text) => {
        if (!text.trim()) return;
        setIsPopoverOpen(false);
        setMessages(prev => [...prev, { sender: 'user', text }]);
        setInputValue('');
        clearSubOptions();

        // When AI is enabled, route the message to the RAG system instead of
        // showing the regular option cards.
        if (enableAI) {
            handleSendAI(text);
            return;
        }

        setTimeout(() => {
            pushBotOptions(
                `You asked: "<strong>${escapeXml(text)}</strong>". Here are the options you can choose from:`,
                allOptions
            );
        }, 500);
    };

    if (authChecking) {
        return (
            <div className="login-page">
                <div className="login-card">
                    <div className="login-brand">
                        <div className="assistant-avatar">HR</div>
                        <h1>HR CHATBOT</h1>
                        <p>Checking your session…</p>
                    </div>
                </div>
            </div>
        );
    }

    if (!user) {
        return <LoginView onLogin={setUser} />;
    }

    const showWelcome = messages.length === 0;

    return (
        <div className="app-shell">
            {/* Window Header */}
            <div className="window-header">
                <div className="header-brand">
                    <div className="window-title">HR CHATBOT</div>
                    <button className="new-chat-btn" onClick={handleNewChat} title="Start a new chat">
                        <svg fill="none" stroke="currentColor" strokeWidth="2.2" viewBox="0 0 24 24" className="new-chat-icon"><path strokeLinecap="round" strokeLinejoin="round" d="M12 5v14m-7-7h14" /></svg>
                        New Chat
                    </button>
                </div>
                <div className="window-actions">
                    <button className="action-btn" onClick={() => setIsDarkMode(!isDarkMode)} title="Toggle Theme">
                        {isDarkMode ? (
                            <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" /></svg>
                        ) : (
                            <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" /></svg>
                        )}
                    </button>
                    <button className="action-btn logout-btn" onClick={async () => { try { await AuthAPI.logout(); } catch { } sessionStorage.removeItem('hr_token'); sessionStorage.removeItem('hr_refresh'); sessionStorage.removeItem('hr_user'); setUser(null); setMessages([]); clearSubOptions(); }} title="Logout">
                        <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" /></svg>
                    </button>
                </div>
            </div>

            {/* Chat area */}
            <div className="chat-container">
                {showWelcome ? (
                    <div className="welcome-view">
                        <div className="assistant-avatar">HR</div>
                        <div className="greeting-title">Hello {name}</div>
                        <div className="greeting-subtitle">How can I help you today? Select an option to get started.</div>
                        <div className="options-grid">
                            {allOptions.map(opt => (
                                <div key={opt.id} className={`option-card${opt.adminOnly ? ' admin-only' : ''}`} onClick={() => handleSelectOption(opt.id, opt.title)}>
                                    <div className="option-icon"><svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d={opt.svgPath} /></svg></div>
                                    <div className="option-content">
                                        <span className="option-title">{opt.title}</span>
                                        <span className="option-desc">{opt.desc}</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                ) : (
                    <div className="chat-messages active">
                        {messages.map((msg, index) => {
                            const isAiAnswer = msg.sender === 'bot' && !msg.isStatus && typeof msg.html === 'string' && msg.html.includes('ai-answer');
                            const isProfileInfo = msg.sender === 'bot' && !msg.isStatus && typeof msg.html === 'string' && msg.html.includes('profile-table');
                            const isAutoText = msg.sender === 'bot' && !msg.isStatus && !isAiAnswer && !isProfileInfo && !(msg.options && msg.options.length > 0) && typeof msg.html === 'string';
                            const isDataTable = msg.sender === 'bot' && !msg.isStatus && !isAiAnswer && !isProfileInfo && typeof msg.html === 'string' && msg.html.includes('table-wrap');
                            return (
                            <div key={msg.id ?? index} className={`message ${msg.sender}${msg.isStatus ? ' status-line' : ''}${isAiAnswer ? ' ai-wide' : ''}${isProfileInfo ? ' profile-info' : ''}${isAutoText ? ' auto-text' : ''}${isDataTable ? ' data-table' : ''}`}>
                                {msg.isStatus ? (
                                    <div className="ai-status-indicator" dangerouslySetInnerHTML={{ __html: msg.html }} />
                                ) : msg.html && msg.sender === 'bot' ? (
                                    <div className="bot-content">
                                        <div dangerouslySetInnerHTML={{ __html: msg.html }} />
                                        {msg.async && !msg.done && <span className="typing">● ● ●</span>}
                                        {msg.options && msg.options.length > 0 && (
                                            <div className="bubble-options">
                                                {msg.options.map(opt => (
                                                    <button key={opt.id ?? opt.label} className="bubble-option" onClick={() => opt.action ? handleSelectSubOption(opt) : handleSelectOption(opt.id, opt.title)}>
                                                        {opt.svgPath && (
                                                            <span className="bubble-option-icon">
                                                                <svg fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d={opt.svgPath} /></svg>
                                                            </span>
                                                        )}
                                                        <span className="bubble-option-title">{opt.title ?? opt.label}</span>
                                                        {opt.desc && <span className="bubble-option-desc">{opt.desc}</span>}
                                                    </button>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                ) : msg.text}
                            </div>
                            );
                        })}
                        <div ref={chatEndRef} />
                    </div>
                )}

                {/* Sub-options shown below the chat */}
                {subOptions.length > 0 && (
                    <div className="suboptions-bar">
                        {subOptions.map((sub, i) => (
                            <button key={i} className="suboption-chip" onClick={() => handleSelectSubOption(sub)}>{sub.label}</button>
                        ))}
                    </div>
                )}

                {/* Explorer: search / browse live widget */}
                {explorer && (
                    <ExplorerPanel type={explorer.type} onPreview={handlePreview} onPick={handlePick} onClose={() => setExplorer(null)} />
                )}

                {/* Salary panel widget */}
                {salaryPanel && (
                    <SalaryPanel user={user} onBreakdown={handleSalaryBreakdown} onPick={handleSalaryPick} onClose={() => setSalaryPanel(false)} />
                )}

                {/* Attendance panel widget */}
                {attendancePanel && (
                    <AttendancePanel user={user} onPick={handleAttendancePick} onClose={() => setAttendancePanel(false)} />
                )}

                {/* Leaves panel widget */}
                {leavesPanel && (
                    <LeavesPanel user={user} onBalance={handleLeaveBalance} onPick={handleLeavePick} onClose={() => setLeavesPanel(false)} />
                )}

                {/* Admin employee details panel */}
                {adminPanel && (
                    <AdminPanel onClose={() => setAdminPanel(false)} onPicked={(label) => pushBotText(label)} />
                )}

                {/* Admin accounts management panel */}
                {accountsPanel && (
                    <AdminAccountsPanel onClose={() => setAccountsPanel(false)} onPicked={(label) => pushBotText(label)} />
                )}

                {/* Admin documents management panel */}
                {documentsPanel && (
                    <AdminDocumentsPanel onClose={() => setDocumentsPanel(false)} onPicked={(label) => pushBotText(label)} />
                )}

                {/* Custom date range picker */}
                {customRange && (
                    <div className="range-picker">
                        <span className="range-label">From</span>
                        <input type="date" value={customRange.from} max={customRange.to} onChange={(e) => setCustomRange({ ...customRange, from: e.target.value })} />
                        <span className="range-label">To</span>
                        <input type="date" value={customRange.to} min={customRange.from} onChange={(e) => setCustomRange({ ...customRange, to: e.target.value })} />
                        <button className="range-go" onClick={runCustomRange}>Get</button>
                    </div>
                )}
            </div>

            {/* Profile badge */}
            <div className="bottom-left-corner">
                <div className="profile-badge" title="Account Details" onClick={() => setIsProfileOpen(true)}>
                    <div className="profile-avatar-sm">{initials}</div>
                    <div className="profile-info-text">
                        <span className="profile-name">{name}</span>
                        <span className="profile-role">{isAdmin ? 'Admin' : 'Employee'}</span>
                    </div>
                </div>
            </div>

            {/* Developer credit badge */}
            <div className="bottom-right-corner">
                <div className="dev-badge" title="Developed By M. Umair Akram">
                    <div className="dev-avatar">UA</div>
                    <div className="dev-info-text">
                        <span className="dev-label">Developed By</span>
                        <span className="dev-name">M. Umair Akram</span>
                    </div>
                </div>
            </div>

            {/* Profile modal */}
            {isProfileOpen && user && (
                <div className="profile-modal-overlay" onClick={() => setIsProfileOpen(false)}>
                    <div className="profile-card" onClick={(e) => e.stopPropagation()}>
                        <div className="close-btn" onClick={() => setIsProfileOpen(false)}>&times;</div>
                        <div className="header-section">
                            <div className="avatar-circle">{initials}</div>
                            <div className="header-info">
                                <h2>{name}</h2>
                                <p className="role">{isAdmin ? 'Administrator' : 'Employee'} — {user.profile?.job_title}</p>
                                <div className="meta-tags">
                                    <span className="tag">🏢 {user.profile?.department}</span>
                                    <span className="tag">⏱ {user.profile?.employment_type}</span>
                                    <span className="badge active"><span className="dot"></span> {user.profile?.employment_status}</span>
                                </div>
                            </div>
                        </div>
                        <div className="grid-container">
                            <div className="card-box">
                                <div className="box-title">Employee Information</div>
                                <div className="row"><span>Employee ID</span> <strong>{user.employee_id}</strong></div>
                                <div className="row"><span>Employee Number</span> <strong>{user.profile?.employee_number}</strong></div>
                                <div className="row"><span>Department</span> <strong>{user.profile?.department}</strong></div>
                                <div className="row"><span>Job Title</span> <strong>{user.profile?.job_title}</strong></div>
                                <div className="row"><span>Employment Type</span> <strong>{user.profile?.employment_type}</strong></div>
                                <div className="row"><span>Employment Status</span> <span className="pill active-pill">{user.profile?.employment_status}</span></div>
                                <div className="row"><span>Joining Date</span> <strong>{user.profile?.joining_date}</strong></div>
                            </div>
                            <div className="card-box">
                                <div className="box-title">Contact Information</div>
                                <div className="row"><span>Email</span> <a href={`mailto:${user.contacts?.email}`}>{user.contacts?.email}</a></div>
                                <div className="row"><span>Phone</span> <a href={`tel:${user.contacts?.phone}`}>{user.contacts?.phone}</a></div>
                                <div className="row"><span>Extension</span> <strong>{user.contacts?.extension}</strong></div>
                            </div>
                            <div className="card-box">
                                <div className="box-title">Work Location</div>
                                <div className="row"><span>Floor</span> <strong>{user.locations?.floor}</strong></div>
                                <div className="row"><span>Desk Number</span> <strong>{user.locations?.desk_number}</strong></div>
                                <div className="row"><span>Seat Status</span> <span className="pill assigned-pill">{user.locations?.seat_status}</span></div>
                            </div>
                            <div className="card-box">
                                <div className="box-title">Account</div>
                                <div className="row"><span>Account Type</span> <span className="pill assigned-pill">{isAdmin ? 'Admin' : 'User'}</span></div>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Input footer */}
            <div className="input-footer">
                <div className="input-container-wrapper" ref={popoverRef}>
                    {isPopoverOpen && (
                        <div className="popover-menu show">
                            {enableAI ? (
                                <>
                                    <div className="ai-pick-title">Choose a PDF to chat with, or use All PDFs</div>
                                    <div
                                        className={`popover-item ai-pick-item ${!aiSelectedDoc ? 'active' : ''}`}
                                        onClick={() => { setAiSelectedDoc(null); setIsPopoverOpen(false); }}
                                    >
                                        <span className="popover-icon">🌐</span>
                                        <div className="popover-text-group">
                                            <span className="popover-title">All PDFs</span>
                                            <span className="popover-desc">Answer from every enabled document</span>
                                        </div>
                                    </div>
                                    {aiDocs.length === 0 && (
                                        <div className="ai-pick-empty">No enabled PDFs are ready yet.</div>
                                    )}
                                    {aiDocs.map(doc => (
                                        <div
                                            key={doc.document_id}
                                            className={`popover-item ai-pick-item ${aiSelectedDoc === doc.document_id ? 'active' : ''}`}
                                            onClick={() => { setAiSelectedDoc(doc.document_id); setIsPopoverOpen(false); }}
                                        >
                                            <span className="popover-icon">📄</span>
                                            <div className="popover-text-group">
                                                <span className="popover-title">{doc.name}</span>
                                                <span className="popover-desc">{doc.category}</span>
                                            </div>
                                        </div>
                                    ))}
                                </>
                            ) : (
                                allOptions.map(opt => (
                                    <div key={opt.id} className={`popover-item${opt.adminOnly ? ' admin-only' : ''}`} onClick={() => handleSelectOption(opt.id, opt.title)}>
                                        <span className="popover-icon">{opt.icon}</span>
                                        <div className="popover-text-group">
                                            <span className="popover-title">{opt.title}</span>
                                            <span className="popover-desc">{opt.desc}</span>
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>
                    )}
                    <div className="input-wrapper">
                        <input
                            type="text"
                            placeholder={enableAI
                                ? (aiSelectedDoc
                                    ? (aiDocs.find(d => d.document_id === aiSelectedDoc)?.name || 'Selected PDF') + ' — ask a question…'
                                    : 'All PDFs — ask a question…')
                                : 'Type a message or tap the menu…'}
                            value={inputValue}
                            onChange={(e) => setInputValue(e.target.value)}
                            onClick={() => setIsPopoverOpen(true)}
                            onKeyDown={(e) => e.key === 'Enter' && handleSendMessage(inputValue)}
                        />
                        <div className="input-actions">
                            <button
                                className={`ai-toggle-btn ${enableAI ? 'active' : ''}`}
                                onClick={() => {
                                    const next = !enableAI;
                                    setEnableAI(next);
                                    setIsPopoverOpen(false);
                                    if (next) { loadAiDocs(); setAiSelectedDoc(null); }
                                }}
                                title={enableAI ? 'Disable AI chat' : 'Enable AI chat'}
                            >
                                <span className="ai-toggle-text">AI</span>
                            </button>
                            <button className="send-btn" onClick={() => handleSendMessage(inputValue)} title="Send">
                                <svg fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M5 10l7-7m0 0l7 7m-7-7v18" /></svg>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
