/**
 * Recre Groups: attendance import.
 *
 * Paste this into the attendance sheet once (Extensions → Apps Script). It adds an
 * "Attendance" menu and an "App import" tab. Each week:
 *   1. In the app: Attendance page → Run → Copy for sheet.
 *   2. Here: paste into cell A2 of the "App import" tab.
 *   3. Open the attendance tab and choose Attendance → Import from the app.
 *
 * It puts a 1 under the session date for everyone who was in that session's group,
 * adds people it hasn't seen before in the first empty rows, and never clears anything.
 * It runs as you, inside your own Google account, so the sheet is never shared.
 *
 * No pop-ups on purpose: when the browser is signed in to more than one Google account,
 * Apps Script dialogs and prompts fail ("PERMISSION_DENIED", "Error resuming script execution").
 */

const IMPORT_TAB = 'App import';
const IMPORT_CELL = 'A2';

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Attendance')
    .addItem('Import from the app', 'runImport')
    .addItem('Go to the App import tab', 'showImportTab')
    .addToUi();
}

function importTab() {
  const book = SpreadsheetApp.getActiveSpreadsheet();
  let tab = book.getSheetByName(IMPORT_TAB);
  if (!tab) {
    tab = book.insertSheet(IMPORT_TAB);
    tab.getRange('A1').setValue('Paste what the app copied (Attendance page → Run → Copy for sheet) into A2. ' +
                                'Then open the attendance tab and choose Attendance → Import from the app.')
      .setFontWeight('bold');
    tab.setColumnWidth(1, 900);
  }
  return tab;
}

function showImportTab() {
  const tab = importTab();
  tab.activate();
  tab.getRange(IMPORT_CELL).activate();
}

function runImport() {
  const book = SpreadsheetApp.getActiveSpreadsheet();
  const target = book.getActiveSheet();
  const tab = importTab();
  let message;
  try {
    if (target.getName() === IMPORT_TAB) {
      throw new Error('open the attendance tab first, then choose Attendance → Import from the app again.');
    }
    message = importAttendance(String(tab.getRange(IMPORT_CELL).getValue()), target);
    tab.getRange(IMPORT_CELL).clearContent();  // so last week's data can't be imported by mistake
  } catch (e) {
    message = 'Not imported: ' + e.message;
  }
  tab.getRange('A4').setValue(new Date().toLocaleString() + ' (' + target.getName() + ')\n' + message);
  book.toast(message + '\n(Also written in the App import tab, cell A4.)', 'Attendance', 20);
}

function importAttendance(text, sheet) {
  let data;
  try {
    data = JSON.parse(text);
  } catch (e) {
    data = null;
  }
  if (!data || data.app !== 'recre-attendance') {
    throw new Error(text.trim()
      ? "cell A2 of the App import tab isn't what the app copied. In the app, click Run, then the blue " +
        'Copy for sheet button (not Copy table), and paste again.'
      : 'cell A2 of the App import tab is empty. In the app, click Run, then Copy for sheet, and paste it there.');
  }
  const all = sheet.getRange(1, 1, sheet.getMaxRows(), sheet.getMaxColumns());
  const plan = planAttendance(all.getDisplayValues(), all.getFormulas(), data);
  if (plan.rowsNeeded > sheet.getMaxRows()) {
    sheet.insertRowsAfter(sheet.getMaxRows(), plan.rowsNeeded - sheet.getMaxRows());
  }
  plan.updates.forEach(function (u) {
    sheet.getRange(u.row + 1, u.col + 1).setValue(u.value);
  });
  let summary = plan.summary;
  const L = plan.layout;
  if (L && L.row >= 0) {  // redraw the month headings above the dates
    try {
      const months = sheet.getRange(L.row + 1, L.from + 1, 1, L.to - L.from + 1);
      months.breakApart();
      months.clearContent();
      L.months.forEach(function (m) {
        const range = sheet.getRange(L.row + 1, m.col + 1, 1, m.span);
        if (m.span > 1) range.merge();
        range.getCell(1, 1).setValue("'" + m.label);
      });
    } catch (e) {
      summary += "\nCouldn't redo the month headings (" + e.message + '); please fix them by hand.';
    }
  }
  return summary;
}

// ------------------------------------------------------------ the logic (no Google calls)

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTH_DAYS = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const HANDLE_HEADINGS = ['tele handle', 'telegram handle', 'handle', 'telehandle'];

/** '27 Aug', '19th Aug', '4th Sept', '3 september' -> '27 Aug' / '19 Aug' / '4 Sep' / '3 Sep'; '' if no date. */
function sessionDate(text) {
  const re = /(\d{1,2})(?:st|nd|rd|th)?\s*([A-Za-z]{3,9})\b/gi;
  let m;
  while ((m = re.exec(String(text || ''))) !== null) {
    const month = MONTHS.indexOf(m[2].slice(0, 3).charAt(0).toUpperCase() + m[2].slice(1, 3).toLowerCase());
    const day = parseInt(m[1], 10);
    if (month >= 0 && day >= 1 && day <= MONTH_DAYS[month]) return day + ' ' + MONTHS[month];
  }
  return '';
}

function columnLetter(c) {
  let s = '';
  for (c += 1; c > 0; c = Math.floor((c - 1) / 26)) s = String.fromCharCode(65 + (c - 1) % 26) + s;
  return s;
}

/**
 * Which cells to change. shown/formulas are the tab's display values and formulas
 * (row by row); returns {updates: [{row, col, value}] (0-based), rowsNeeded, summary}.
 */
function planAttendance(shown, formulas, data) {
  const cell = function (grid, r, c) { return r < grid.length && c < grid[r].length ? String(grid[r][c]) : ''; };
  const head = shown.findIndex(function (row) {
    return HANDLE_HEADINGS.indexOf(String(row[0] || '').trim().toLowerCase()) >= 0;
  });
  if (head < 0) throw new Error("Couldn't find the 'Tele Handle' heading in column A of this tab. Open the attendance tab first.");

  // The row above the headings with the most dates in it, e.g. "27 Aug | 29 Aug | 3 Sep".
  let dateRow = 0, most = -1;
  for (let r = 0; r <= head; r++) {
    const n = shown[r].filter(function (v) { return sessionDate(v); }).length;
    if (n > most) { most = n; dateRow = r; }
  }
  const columns = {};
  shown[dateRow].forEach(function (v, c) {
    const d = sessionDate(v);
    if (d && !(d in columns)) columns[d] = c;
  });
  const dateCols = Object.keys(columns).map(function (d) { return columns[d]; });
  if (!dateCols.length) throw new Error("Couldn't find any session dates (like '27 Aug') above the headings.");
  const headings = shown[head].map(function (v) { return String(v).trim().toLowerCase(); });
  const nameCol = headings.indexOf('name');
  const totalCol = headings.findIndex(function (v) { return v.indexOf('total') >= 0; });
  const first = Math.min.apply(null, dateCols), last = Math.max.apply(null, dateCols);
  const isEmpty = function (r, c) { return !cell(shown, r, c).trim() && !cell(formulas, r, c).trim(); };

  const rows = {}, empty = [];
  for (let r = head + 1; r < shown.length; r++) {
    const h = cell(shown, r, 0).trim().replace(/^@/, '').toLowerCase();
    if (h) {
      if (!(h in rows)) rows[h] = r;
    } else if (dateCols.every(function (c) { return !cell(shown, r, c).trim(); })) {
      empty.push(r);
    }
  }
  let end = shown.length;

  const updates = [];
  // Dates as the app sent them, tidied the same way as the sheet's ('19th Aug' -> '19 Aug').
  const tidy = function (d) { return sessionDate(d) || String(d || '').trim(); };
  const sessions = (data.sessions || []).map(function (s) {
    return {title: s.title, date: tidy(s.date), day: s.day || ''};
  });

  // A fresh tab (e.g. copied from last semester): no ticks yet and none of its dates are ours.
  // Then its date row and month headings are rewritten to this semester's sessions.
  let layout = null;
  const ticked = dateCols.some(function (c) {
    for (let r = head + 1; r < shown.length; r++) if (cell(shown, r, c).trim()) return true;
    return false;
  });
  if (sessions.length && !ticked && sessions.every(function (s) { return !(s.date in columns); })) {
    layout = setDates(sessions, dateCols.slice().sort(function (a, b) { return a - b; }), dateRow, shown, updates);
    Object.keys(columns).forEach(function (d) { delete columns[d]; });
    layout.placed.forEach(function (s) { columns[s.date] = s.col; });
  }

  const skipped = sessions.filter(function (s) { return !(s.date in columns); });
  if (sessions.length && skipped.length === sessions.length) {
    throw new Error('none of the sessions (' + sessions.map(function (s) { return s.date || s.title; }).join(', ') +
                    ') has a date column in this tab, which runs ' + shown[dateRow][first] + ' to ' +
                    shown[dateRow][last] + '. Open the tab for that semester, or fix the session dates in the app. ' +
                    'Nothing was changed.');
  }

  const added = [], noHandle = [];
  let ticks = 0, notHere = 0;
  // Columns to tick for a person; people with none are left out instead of getting an empty row.
  const colsOf = function (p) {
    const cols = {};
    (p.dates || []).forEach(function (d) { d = tidy(d); if (d in columns) cols[columns[d]] = true; });
    return Object.keys(cols).map(Number).sort(function (a, b) { return a - b; });
  };
  // New people go in the order they first came, like the sheet is filled by hand.
  const people = (data.people || []).map(function (p, i) { return {p: p, i: i, cols: colsOf(p)}; })
    .sort(function (a, b) { return (a.cols[0] === undefined ? Infinity : a.cols[0]) -
                                   (b.cols[0] === undefined ? Infinity : b.cols[0]) || a.i - b.i; });

  people.forEach(function (x) {
    const p = x.p;
    const shownHandle = String(p.handle || '').trim().replace(/^@/, '');
    const handle = shownHandle.toLowerCase();
    if (!x.cols.length) { notHere++; return; }
    if (!handle) { noHandle.push(p.name); return; }
    let r = rows[handle];
    if (r === undefined) {
      r = empty.length ? empty.shift() : end++;
      rows[handle] = r;
      added.push(handle);
      updates.push({row: r, col: 0, value: '@' + shownHandle});
    }
    if (nameCol >= 0 && isEmpty(r, nameCol)) updates.push({row: r, col: nameCol, value: p.name});
    if (totalCol >= 0 && isEmpty(r, totalCol)) {
      updates.push({row: r, col: totalCol,
                    value: '=SUM(' + columnLetter(first) + (r + 1) + ':' + columnLetter(last) + (r + 1) + ')'});
    }
    x.cols.forEach(function (c) {
      if (cell(shown, r, c).trim() !== '1') {
        updates.push({row: r, col: c, value: 1});
        ticks++;
      }
    });
  });

  const lines = [];
  if (layout) {
    lines.push("Set this tab's dates to your sessions (" + layout.placed[0].date + ' to ' +
               layout.placed[layout.placed.length - 1].date + ') and redid the month headings. ' +
               'Check the labels under the dates (like CNY or Midterm): those were for the old dates.');
  }
  lines.push('✓ ' + ticks + ' new tick' + (ticks === 1 ? '' : 's') + ', ' + added.length + ' new ' +
             (added.length === 1 ? 'person' : 'people') + '.');
  if (skipped.length) {
    lines.push('No date column in this tab for: ' + skipped.map(function (s) { return s.title; }).join(', ') +
               '. Fix their session dates in the app, or add the date to the sheet.');
  }
  if (notHere) lines.push(notHere + ' ' + (notHere === 1 ? 'person was' : 'people were') + ' only at those sessions, so not added.');
  if (noHandle.length) lines.push('No Telegram handle, so not added: ' + noHandle.join(', ') + '.');
  return {updates: updates, rowsNeeded: end, summary: lines.join('\n'), layout: layout};
}

/**
 * Put the sessions, in date order, into the tab's date columns and clear the rest.
 * Returns where each went and the month headings to draw: {placed, row, from, to, months: [{col, span, label}]}.
 */
function setDates(sessions, slots, dateRow, shown, updates) {
  const seen = {};
  const key = function (s) { return s.day || s.date; };
  const ordered = sessions.filter(function (s) {
    if (!s.date || seen[s.date]) return false;
    seen[s.date] = true;
    return true;
  }).sort(function (a, b) { return key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0; });
  const placed = [];
  slots.forEach(function (c, i) {
    const s = ordered[i];
    const text = s ? s.date : '';
    if (s) placed.push({date: s.date, col: c, month: monthLabel(s)});
    const now = c < shown[dateRow].length ? String(shown[dateRow][c]).trim() : '';
    if (now !== text) updates.push({row: dateRow, col: c, value: text ? "'" + text : ''});  // ' keeps it as text
  });
  const months = [];
  placed.forEach(function (p) {
    const last = months[months.length - 1];
    if (last && last.label === p.month && last.col + last.span === p.col) last.span++;
    else months.push({col: p.col, span: 1, label: p.month});
  });
  return {placed: placed, row: dateRow - 1, from: slots[0], to: slots[slots.length - 1], months: months};
}

/** 'Aug-26' for a session on 2026-08-19 (just 'Aug' if the year isn't known). */
function monthLabel(s) {
  const m = /^(\d{4})-(\d{2})/.exec(s.day || '');
  return m ? MONTHS[parseInt(m[2], 10) - 1] + '-' + m[1].slice(2) : s.date.split(' ')[1];
}

if (typeof module !== 'undefined') {  // lets the app's tests run this with Node
  module.exports = {planAttendance: planAttendance, sessionDate: sessionDate, columnLetter: columnLetter};
}
