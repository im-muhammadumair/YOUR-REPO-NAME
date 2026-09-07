# MTM HR Agent — Frontend Reference

This document describes the entire frontend so a developer can quickly understand
every file, what it does, and where to change things.

- **Stack:** React 18 + Vite 5 (ESM), plain CSS in one file, `fetch` API client
- **Runs as:** web app (browser) or desktop app (Electron wrapper)
- **Entry point:** `frontend/src/main.jsx` → `src/App.jsx`
- **Dev server / port:** Vite on `http://127.0.0.1:5173`, proxies `/api` → `http://127.0.0.1:8000` (backend)

---

## Table of Contents

1. [Architecture & data flow](#1-architecture--data-flow)
2. [Directory structure](#2-directory-structure)
3. [File references (quick review + details)](#3-file-references-quick-review--details)
   - [src/main.jsx](#srcmainjsx)
   - [index.html](#indexhtml)
   - [vite.config.js](#viteconfigjs)
   - [package.json](#packagejson)
   - [src/api.js](#srcapijs)
   - [scripts/dev.cjs](#scriptsdevcjs)
   - [scripts/desktop.cjs](#scriptsdesktopcjs)
   - [electron/main.cjs](#electronmaincjs)
   - [src/App.css](#srcappcss)
   - [src/App.jsx](#srcappjsx)
4. [App.jsx structure (components + helpers)](#4-appjsx-structure-components--helpers)
5. [Auth & session flow](#5-auth--session-flow)
6. [API ↔ frontend contract](#6-api--frontend-contract)
7. [How to run / build](#7-how-to-run--build)
8. [Common change scenarios](#8-common-change-scenarios)

---

## 1. Architecture & data flow

```
 React app (src/App.jsx, components)
        │  imports
        ▼
   src/api.js  (fetch client — attaches Bearer token, calls backend)
        │  HTTP + JSON via Vite proxy  (Authorization: Bearer <access token>)
        ▼
   Vite dev server  (vite.config.js — proxies /api → :8000)
        ▼
   FastAPI backend  (see backend.md — the API this doc's contract targets)
```

- **The frontend only ever talks to the backend over JSON/HTTP.** It never touches
  the database. `api.js` is the single place that knows the endpoint paths.
- **State lives in one big `App` component** plus five smaller panel components.
  There is no router library — the app switches views based on React state.
- **Chat-like UI:** the main screen is a chatbot that renders HTML messages/pills
  and opens live panels (attendance, leaves, salary, explorer, admin) built from
  API data.
- **Two run modes share the same `src/` code:**
  - **Web:** `npm run dev` → `scripts/dev.cjs` starts the backend + Vite.
  - **Desktop:** `npm run desktop` → `scripts/desktop.cjs` also launches Electron.

---

## 2. Directory structure

```
frontend/
├── index.html            Vite HTML entry (mounts #root, loads src/main.jsx)
├── package.json          scripts + dependencies (react, vite, electron)
├── package-lock.json     locked dependency versions
├── vite.config.js        Vite dev config + /api proxy to backend
├── electron/
│   └── main.cjs          Electron main process (desktop window, security)
├── scripts/
│   ├── dev.cjs           starts backend + Vite (web mode)
│   └── desktop.cjs       starts backend + Vite + Electron (desktop mode)
└── src/
    ├── main.jsx          React root render (<App /> + stylesheet)
    ├── api.js            fetch client: auth + all endpoint calls
    ├── App.jsx           the whole UI (helpers, components, main App)
    └── App.css           all styling (4700+ lines, single file)
```

Nothing else lives here — it is intentionally a small, single-page React app.

---

## 3. File references (quick review + details)

### src/main.jsx

**Quick review:** The React entry point. Mounts `<App />` into `#root` inside
`<React.StrictMode>` and imports `App.css`.

**Details:**
- `import './App.css'` — pulls in all styles globally.
- `React.createRoot(document.getElementById('root')).render(...)`.
- `<React.StrictMode>` — enables extra dev checks (double-invokes effects in dev).

> **Where to change:** practically never. Only if you add providers/context or
> a router at the root.

---

### index.html

**Quick review:** Plain Vite HTML shell.

**Details:**
- `<div id="root">` — mount point for React.
- `<script type="module" src="/src/main.jsx">` — loads the app.
- `<title>HR CHATBOT</title>` — appears in the browser/Electron title bar.

> **Where to change:** page `<title>`, favicon, meta tags, adding a root element.

---

### vite.config.js

**Quick review:** Vite dev-server configuration, especially the `/api` proxy.

**Details:**
- `plugins: [react()]` — the React plugin (JSX fast refresh).
- Dev server: `host: true`, `port: 5173`.
- **Proxy:** `/api` → `http://127.0.0.1:8000` with `changeOrigin: true`. This is
  why the frontend calls relative `/api/...` paths and the backend appears at the
  same origin in the browser (no CORS issues in dev).

> **Where to change:** dev port, proxy target (pointing at a different backend
> host/port), extra Vite plugins.

---

### package.json

**Quick review:** Scripts and dependencies.

**Details — scripts:**
- `dev` → `node scripts/dev.cjs` (backend + Vite, web mode).
- `dev:vite` → `vite` (just the Vite dev server).
- `build` → `vite build` (production bundle to `dist/`).
- `preview` → `vite preview` (serve the built bundle locally).
- `desktop` → `node scripts/desktop.cjs` (backend + Vite + Electron).

**Dependencies:** `react`, `react-dom`. **DevDependencies:** `@vitejs/plugin-react`,
`vite`, `electron`.

> **Where to change:** adding npm packages, changing scripts/commands.

---

### src/api.js

**Quick review:** The single fetch-based API client. Owns the base path, the
`Authorization` header, the session-storage keys, and every endpoint call.

**Details:**
- `BASE = '/api'`; `STORE = sessionStorage` (re-exported as `STORE`).
- `request(path, options)` — adds `Bearer <token>` from `hr_token`; on a `401`
  it clears `hr_token`/`hr_user`, dispatches an `hr-unauthorized` window event
  (the app listens and logs out), and throws a "Session expired" error.
- `AuthAPI.login(username, password)` — posts to `/auth/login`; on success
  **stores `hr_refresh` = `refresh_token`** (the access token is stored by the
  caller). Returns the raw login payload.
- `AuthAPI.logout()` — reads `hr_refresh`, sends `{ refresh_token }` to
  `/auth/logout`, then clears `hr_refresh`.
- `API.*` — one method per backend endpoint: `me`, `attendance`, `attendanceRange`,
  `leavesBalance`, `leavesOverview`, `leavesHistory`, `salaryStructure`,
  `salaryPayslip`, `services`, `documents`, `documentFileUrl`, `adminEmployees`,
  `adminEmployee`, `adminPayslips`, `adminAttendance`, `adminLeaves`,
  `adminSalary`, `adminAccounts`, `adminAccount`, `adminCreateAccount`,
  `adminUpdateAccount`, `adminDeleteAccount`, `employees`, `employee`.

> **Where to change:** endpoint paths, headers, the 401 handling, or session
> storage keys. **If the backend routes change, this is the only file to update.**

---

### scripts/dev.cjs

**Quick review:** Dev orchestrator for **web mode**. Ensures the backend is up on
`:8000`, starts Vite on `:5173`, prints the local + LAN URLs, and cleans up on exit.

**Details:**
- Locates the backend venv (`backend/.venv/Scripts/python.exe`) and spawns
  `python main.py` in the `backend` folder if `:8000` isn't already listening.
- Starts `npm run dev:vite` (Vite) if `:5173` isn't already running.
- `waitFor(port, ...)` — polls a port until it responds.
- Tracks child processes and kills them (Windows `taskkill /T /F`) on Ctrl+C/SIGINT.
- Prints `Local:` and `Network:` (LAN IP) URLs so other devices can connect.

> **Where to change:** ports, host binding, how the backend venv is located,
> startup timeouts.

---

### scripts/desktop.cjs

**Quick review:** Same orchestrator as `dev.cjs` but for **desktop mode** — it also
launches Electron after the backend + Vite are ready.

**Details:**
- Reuses the same backend/Vite wait-and-start logic (binds Vite to `127.0.0.1`).
- `electronBinaryPath()` — resolves the installed Electron binary.
- Spawns `electron main.cjs` with `HR_DEV_URL` set to the Vite URL.
- When the Electron window closes, it shuts everything down.

> **Where to change:** ports, Electron launch behavior, env vars passed to Electron.

---

### electron/main.cjs

**Quick review:** The Electron **main process** — creates the desktop window and
hardens it (no menu, no devtools, no node integration in the renderer).

**Details:**
- `Menu.setApplicationMenu(null)` — removes the default File/Edit/View menu.
- `createWindow()` — 1280×860 (min 900×640), title "HR CHATBOT",
  `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`,
  `devTools: false`.
- Loads `DEV_URL` (from `HR_DEV_URL`, default `http://127.0.0.1:5173`).
- Blocks devtools and adds custom shortcuts:
  - `Ctrl+R` refresh, `Ctrl+`/`Ctrl-` zoom (0.5×–3×) with a temporary zoom badge,
    `Ctrl+0` reset zoom.
  - Blocks F12 / `Ctrl+Shift+I/J/C` devtools.
- Standard window lifecycle: recreate on `activate`, quit when all windows close
  (except macOS).

> **Where to change:** window size/title, security flags, keyboard shortcuts,
> the served URL.

---

### src/App.css

**Quick review:** Every style in the app lives here (one large file). Class names
cover the login screen, chat layout, cards, tables, pills, panels, explorer,
admin view, dark mode, and responsive layout.

**Details:**
- Layouts: `.login-*`, `.chat-*`, `.window-*`, `.sidebar-*`.
- Components: `.options-grid`, `.option-card`, `.dir-card-*`, `.panel-*`,
  `.explorer-*`, `.admin-*`, `.att-*`, `.leaves-*`, `.salary-*`.
- Shared bits: `.pill-tag` (status colors via `.success/.warn/.danger/.info/.neutral`),
  `.stat-row`, `.table-wrap`, `.muted`, `.num`.
- Includes CSS variables / dark-mode overrides (`isDarkMode` toggles a class).

> **Where to change:** any color, spacing, size, font, or layout tweak — it is all
> here. Search by class name before adding new CSS.

---

### src/App.jsx

**Quick review:** The whole application UI + logic in one file — helper/data
functions, five panel components, and the main `App` component that holds state,
handles auth, and renders the chat interface.

**Details:** see the dedicated section below (it is the heart of the frontend).

> **Where to change:** almost every frontend behavioural change touches this file.

---

## 4. App.jsx structure (components + helpers)

### Module-level constants & helpers (~lines 1–330)

- `MONTHS` — the 12 month names (used to build "Payslip — January", etc.).
- `OPTIONS` — the main chat home tiles
  (attendance, leaves, salary, documents, services): `{id, title, desc, icon, svgPath}`.
- `ADMIN_OPTION` — the extra admin tile (`adminOnly: true`) shown to admins.
- `MANAGE_ACCOUNTS_OPTION` — the admin "Manage Accounts" tile (`adminOnly: true`);
  admins also see this one (with `ADMIN_OPTION`).
- `EXPLORER_OPTIONS` — the options that open the live-search explorer
  (`services`, `documents`).
- `buildSubOptions(id, me, accountType)` — returns the clickable sub-options
  shown after a user picks a main tile (e.g. attendance: Today / This Week /
  Last Week / Custom Range).
- Date/utils: `toISO`, `weekStart`, `addDays`, `DAY_NAMES`, `dayName`,
  `dayNameShort` — date formatting for attendance rows.
- `escapeXml(s)` — escapes user/DB text before inserting into HTML messages
  (XSS guard — **do not render raw data into HTML without this**).
- `fmtMoney(n)` — thousands-separator formatting.
- `statusPill(status)` — maps a status string to a colored pill HTML snippet.
- HTML builders: `attendanceHtml`, `attendanceTableHtml`, plus similar builders
  that turn API data into chat-message HTML (leaves, salary, documents,
  services summaries).
- `runAction(action, value, ctx)` — dispatches to the right API call /
  behaviour for each chat action (attendance today/week/range, leave balance /
  history, salary breakdown / payslip, etc.), builds the HTML, and pushes bot
  messages.

### Components

- **`LoginView`** (~line 330) — username/password form. Calls `AuthAPI.login`,
  stores `hr_token` = `data.access_token`, loads `/api/me`, lowercases
  `account_type` and stores it in `hr_user`, then calls `onLogin(user)`.
  (It normalizes `account_type` to lowercase so admin checks are case-safe.)
- **`ExplorerPanel`** (~line 377) — live search/browse for **services &
  documents**. Loads the directory/docs list, filters by query/dept/category,
  and lets the user pick an item (opens PDFs in a new tab via signed file URLs).
- **`AttendancePanel`** (~line 588) — month-by-month attendance with a summary
  and a date-range picker.
- **`LeavesPanel`** (~line 714) — leave balance + history by year/month.
- **`SalaryPanel`** (~line 781) — salary breakdown + per-month payslips.
- **`AdminPanel`** (~line 902) — admin-only: pick an employee, then view
  profile / attendance / leaves / salary tabs.
- **`AdminAccountsPanel`** (~line 1207) — admin-only: **Manage Accounts** (header
  always shows an account-count badge, e.g. `Manage Accounts 30`). Two tabs:
  - **Accounts** — table of every login account (name, employee ID, username,
    password with a 👁 show/hide toggle, **Account Type**, status pill, Edit
    button, Delete button). **Account Type displays `Admin` or `User`** (any
    non-admin role is shown as `User`; the backend still stores the real role
    name). Editing opens an inline form (the table hides while editing) to
    change username / password / account type / account status. **Delete** asks
    for confirmation and only removes the credentials — the employee record
    stays untouched.
  - **Add Account** — form with employee ID, username, password, account type
    (dropdown labels **User** / **Admin**, values `Employee` / `Admin`) and
    account status (Active/Inactive) to create a new login. **Any Employee ID
    works: an ID that doesn't exist is auto-created with the ID as its default
    name** (no data, so nothing shows in the app for it); reusing an ID that
    already has an account returns a "duplicate employee ID" error.

### Main `App` component (~line 1206)

- State: `isDarkMode, messages, inputValue, isPopoverOpen, isProfileOpen,
  subOptions, explorer, salaryPanel, attendancePanel, leavesPanel, adminPanel,
  accountsPanel, loading, customRange, authChecking, user`.
- **Auth restore effect** (~line 1243): on load, if `hr_token` exists, calls
  `/api/me` to restore the session; on any error it clears storage.
- **Unauthorized listener** (~line 1268): listens for the `hr-unauthorized`
  event (fired by `api.js` on 401) and resets the UI to logged-out.
- `isAdmin = user?.account_type === 'admin'` — determines whether the admin tile
  is available.
- Chat handlers: `pushBotText`, `pushBotOptions`, option/sub-option click
  handlers, and the message send/render logic.
- Layout: sidebar + chat area + welcome screen + panels + admin view; a
  dark-mode toggle and logout button in the top actions.

> **Where to change:** chat behaviour, option tiles, panels, admin view, theme
> toggle, and session handling live here.

---

## 5. Auth & session flow

The app uses the backend's **JWT + refresh-token** auth (see `backend.md`).

1. **Login:** `LoginView` → `AuthAPI.login` → `POST /api/auth/login`.
   - Backend returns `{ access_token, refresh_token, token_type, expires_in,
     employee_id, account_type, account_status }`.
   - Frontend stores `hr_token = access_token`, `hr_refresh = refresh_token`,
     and `hr_user` (with a **lowercased** `account_type`).
2. **Every request:** `api.js` attaches `Authorization: Bearer <hr_token>`.
3. **Access-token expiry (~20 min):** on `401`, `api.js` clears storage and
   dispatches `hr-unauthorized`; the app resets to the login screen. The
   frontend does **not** automatically refresh yet (refresh is stored but unused
   in normal flow).
4. **Logout:** `AuthAPI.logout` sends `{ refresh_token }` to `POST
   /api/auth/logout` (revokes the session server-side), then clears local
   storage.

> **Session keys:** `hr_token` (access token), `hr_refresh` (refresh token),
> `hr_user` (profile + account_type). All in `sessionStorage`.

---

## 6. API ↔ frontend contract

All calls go through `src/api.js` (`API` and `AuthAPI`) and are shaped by the
backend (see `backend.md` for the endpoint map). Key points:

- **Login response** now uses `access_token` / `refresh_token` (the old `token`
  field is gone). The frontend reads `data.access_token` and stores the refresh
  token itself — **do not reintroduce `data.token`.**
- **`account_type`** returned by the backend is title-case (`Admin`, `Employee`);
  the frontend lowercases it **only for display/checks** (`account_type === 'admin'`).
- `documentFileUrl(path)` returns a signed URL that the app opens in a new tab —
  PDFs render **inline** (not downloaded).
- Any backend response-shape change must be matched here or in the HTML builders
  in `App.jsx`.
- **Employee directory previews are role-aware** (`runPreview('employees', …)`):
  admins fetch the full record via `API.adminEmployee`; regular users fetch only
  the public fields via `API.employee` (name, department, job_title, email,
  extension, floor, desk_number) — the backend enforces this by returning only
  public fields on `/api/employees/{id}`.

---

## 7. How to run / build

```bash
cd frontend
npm install            # first time only

npm run dev            # web mode: backend + Vite on :5173
npm run desktop        # desktop mode: same + Electron window
npm run build          # production bundle → dist/ (then `npm run preview`)
```

- Backend auto-starts on `:8000` via the venv at `backend/.venv`.
- Open `http://127.0.0.1:5173` (or the printed Network link for LAN).

---

## 7A. AI chat + PDFs UX

- **AI toggle (footer):** the chat footer has a text-only "AI" button. Grey when
  off, brand-blue when on. Turning it on loads the list of ready-enabled PDFs
  (`loadAiDocs()`) so the user can focus the assistant on a specific document.
- **PDF selector:** a popover lets the user pick "🌐 All PDFs" (global) or one
  ready-enabled PDF per its category; the input placeholder reflects the choice,
  and the question is routed to that document via `chatAI(question, documentId)`.
- **Admin "✨ AI PDFs" tab** (`AdminDocumentsPanel`): always shows three groups —
  "Ready Enabled PDFs", "Ready but Disabled" (vectors still in ChromaDB, so
  re-enabling is instant), and "In Progress" (indexing/error). Each card has the
  AI toggle but no delete button. The Add-Docs form has an "AI" text-only toggle
  that enables the PDF for chat after upload.
- **Answer contract:** `POST /api/chat` returns `{answer, sources, grounded}`.
  Answers come only from the enabled PDFs; personal-record questions are
  deflected, never guessed.

---

## 8. Common change scenarios

| I want to…                                   | Change here                                       |
|----------------------------------------------|---------------------------------------------------|
| Point the app at a different backend         | `vite.config.js` proxy target (dev)              |
| Rename/move an API endpoint call             | `src/api.js` (`API.*`)                           |
| Change how login/logout/session works        | `src/api.js` (`AuthAPI`) + `App.jsx` auth flow    |
| Add a new home tile / chat option            | `App.jsx` → `OPTIONS` (+ handler in `runAction`)  |
| Change a chat message's look/text            | `App.jsx` HTML builders + `App.css`               |
| Tweak any styling (colors, spacing, fonts)   | `src/App.css`                                     |
| Add a whole new panel (e.g. a report)        | new component in `App.jsx` + state in `App` + `api.js` method |
| Change the number of admin tabs/labels       | `App.jsx` → `AdminPanel`                          |
| Change AI chat PDF selector / AI toggle      | `App.jsx` → AI popover + `api.js` `chatAI`        |
| Add/remove admin tabs (incl. "AI PDFs")      | `App.jsx` → `AdminDocumentsPanel` tabs + `api.js` |
| Change account management panel              | `App.jsx` → `AdminAccountsPanel` + `App.css` (`.acct-*`) |
| Change login screen look / copy              | `App.jsx` → `LoginView` + `App.css`               |
| Change desktop window (size, security, zoom) | `electron/main.cjs`                               |
| Change dev ports / LAN access                | `scripts/dev.cjs` + `vite.config.js`              |
| Change the browser title                      | `index.html` `<title>`                            |
| Add a new dependency / script                | `package.json`                                    |
