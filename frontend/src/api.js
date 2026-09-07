const BASE = '/api';
const STORE = window.sessionStorage;

// ── Error types ─────────────────────────────────────────────────────────────
// Every request failure is thrown as one of these classes so the UI (and the
// console) can tell exactly what went wrong, while still carrying a friendly
// human-readable message. Branch on `err.kind`, `err.status` or `instanceof`.
class ApiError extends Error {
    constructor(message, { kind = 'unknown', status = 0, path = '', detail = null } = {}) {
        super(message);
        this.name = this.constructor.name;
        this.kind = kind;
        this.status = status;
        this.path = path;
        this.detail = detail;
    }
}

class NetworkError extends ApiError {
    constructor(path) {
        super('Cannot reach the server. Please check your connection and try again.',
            { kind: 'network', status: 0, path });
    }
}

class AuthError extends ApiError {
    constructor(message, path, detail) {
        super(message, { kind: 'auth', status: 401, path, detail });
    }
}

class SessionExpiredError extends ApiError {
    constructor(path) {
        super('Session expired. Please log in again.',
            { kind: 'session_expired', status: 401, path });
    }
}

class ForbiddenError extends ApiError {
    constructor(message, path, detail) {
        super(message, { kind: 'forbidden', status: 403, path, detail });
    }
}

class ValidationError extends ApiError {
    constructor(message, status, path, detail) {
        super(message, { kind: 'validation', status, path, detail });
    }
}

class RateLimitError extends ApiError {
    constructor(message, path, detail) {
        super(message, { kind: 'rate_limit', status: 429, path, detail });
    }
}

class ServerError extends ApiError {
    constructor(message, status, path, detail) {
        super(message, { kind: 'server', status, path, detail });
    }
}

class NotFoundError extends ApiError {
    constructor(message, path, detail) {
        super(message, { kind: 'not_found', status: 404, path, detail });
    }
}

class UnknownError extends ApiError {
    constructor(message, status, path, detail) {
        super(message, { kind: 'unknown', status, path, detail });
    }
}

function friendlyHttpMessage(status, detail) {
    if (detail && typeof detail === 'string' && detail.trim()) return detail;
    switch (status) {
        case 400: return 'The request was invalid. Please check your input and try again.';
        case 401: return 'Your session has expired. Please log in again.';
        case 403: return 'You are not allowed to perform this action.';
        case 404: return 'The requested item was not found.';
        case 422: return 'The provided information is not valid. Please review and try again.';
        case 429: return 'Too many attempts. Please wait a few minutes and try again.';
        default:
            if (status >= 500) return 'Something went wrong on the server. Please try again in a moment.';
            return 'Something went wrong. Please try again.';
    }
}

function errorForStatus(status, message, path, detail) {
    switch (status) {
        case 400:
        case 422: return new ValidationError(message, status, path, detail);
        case 403: return new ForbiddenError(message, path, detail);
        case 404: return new NotFoundError(message, path, detail);
        case 429: return new RateLimitError(message, path, detail);
        default:
            if (status >= 500) return new ServerError(message, status, path, detail);
            return new UnknownError(message, status, path, detail);
    }
}

function isNetworkishError(body) {
    if (typeof body !== 'string') return false;
    return /connect econnrefused|proxy error|econnreset|failed to fetch|networkerror|socket hang up/i.test(body.trim());
}

async function readBody(res) {
    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
        try { return await res.json(); } catch { return null; }
    }
    try { return await res.text(); } catch { return null; }
}

async function request(path, options = {}) {
    const token = STORE.getItem('hr_token');
    const headers = { ...(options.headers || {}) };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    let res;
    try {
        res = await fetch(BASE + path, { ...options, headers });
    } catch {
        throw new NetworkError(path);
    }

    const body = await readBody(res);

    if (res.status === 401) {
        if (options.raw401) {
            const msg = (body && body.detail) ? body.detail : 'Invalid username or password';
            throw new AuthError(msg, path, body?.detail ?? null);
        }
        STORE.removeItem('hr_token');
        STORE.removeItem('hr_user');
        window.dispatchEvent(new Event('hr-unauthorized'));
        throw new SessionExpiredError(path);
    }

    if (!res.ok) {
        if (isNetworkishError(body)) throw new NetworkError(path);
        const detail = (body && typeof body === 'object' && body.detail) ? body.detail : null;
        throw errorForStatus(res.status, friendlyHttpMessage(res.status, detail), path, detail);
    }
    return body;
}

export { STORE };

export {
    ApiError,
    NetworkError,
    AuthError,
    SessionExpiredError,
    ForbiddenError,
    ValidationError,
    RateLimitError,
    ServerError,
    NotFoundError,
    UnknownError,
};

export const AuthAPI = {
    login: async (username, password) => {
        const data = await request('/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
            raw401: true,
        });
        if (data.refresh_token) STORE.setItem('hr_refresh', data.refresh_token);
        return data;
    },
    logout: () => {
        const refreshToken = STORE.getItem('hr_refresh');
        const body = refreshToken ? JSON.stringify({ refresh_token: refreshToken }) : '{}';
        STORE.removeItem('hr_refresh');
        return request('/auth/logout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body,
        });
    },
};

export const API = {
    me: () => request('/me'),
    attendance: (year, month) => request(`/attendance?year=${year}&month=${month}`),
    attendanceRange: (fromDate, toDate) => request(`/attendance/range?from=${fromDate}&to=${toDate}`),
    leavesBalance: () => request('/leaves/balance'),
    leavesOverview: () => request('/leaves/overview'),
    leavesHistory: (year, month) => request(`/leaves/history?year=${year}&month=${month}`),
    salaryStructure: () => request('/salary/structure'),
    salaryPayslip: (year, month) => request(`/salary/payslip?year=${year}&month=${month}`),
    services: () => request('/services'),
    documents: (category) => request(`/documents${category ? `?category=${encodeURIComponent(category)}` : ''}`),
    documentFileUrl: (path) => request(`/documents/file-url?path=${encodeURIComponent(path)}`),
    adminEmployees: () => request('/admin/employees'),
    adminEmployee: (id) => request(`/admin/employees/${id}`),
    adminPayslips: (id) => request(`/admin/payslips/${id}`),
    adminAttendance: (id, year) => request(`/admin/attendance/${encodeURIComponent(id)}?year=${year}`),
    adminLeaves: (id) => request(`/admin/leaves/${encodeURIComponent(id)}`),
    adminSalary: (id, year) => request(`/admin/salary/${encodeURIComponent(id)}?year=${year}`),
    adminAccounts: () => request('/admin/accounts'),
    adminAccount: (id) => request(`/admin/accounts/${id}`),
    adminCategories: () => request('/admin/categories'),
    adminUploadDocument: (formData) => request('/admin/documents', {
        method: 'POST',
        body: formData,
    }),
    adminDeleteDocument: (documentId) => request(`/admin/documents/${encodeURIComponent(documentId)}`, {
        method: 'DELETE',
    }),
    adminCreateAccount: (payload) => request('/admin/accounts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }),
    adminUpdateAccount: (id, payload) => request(`/admin/accounts/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }),
    adminDeleteAccount: (id) => request(`/admin/accounts/${id}`, {
        method: 'DELETE',
    }),
    employees: () => request('/employees'),
    employee: (id) => request(`/employees/${id}`),
    // RAG / AI chat — SSE streaming (status events + streamed answer)
    chatAIStream: async function* (question, documentId, history) {
        const token = STORE.getItem('hr_token');
        let res;
        try {
            res = await fetch(BASE + '/chat/stream', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(token ? { Authorization: `Bearer ${token}` } : {}),
                },
                body: JSON.stringify({
                    question,
                    document_id: documentId || null,
                    history: history || null,
                }),
            });
        } catch {
            throw new NetworkError('/chat/stream');
        }
        if (res.status === 401) {
            STORE.removeItem('hr_token');
            STORE.removeItem('hr_user');
            window.dispatchEvent(new Event('hr-unauthorized'));
            throw new SessionExpiredError('/chat/stream');
        }
        if (!res.ok) {
            const body = await readBody(res);
            if (isNetworkishError(body)) throw new NetworkError('/chat/stream');
            const detail = (body && typeof body === 'object' && body.detail) ? body.detail : null;
            throw errorForStatus(res.status, friendlyHttpMessage(res.status, detail), '/chat/stream', detail);
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // keep incomplete line in buffer
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    yield JSON.parse(line.slice(6));
                } catch { /* skip malformed frames */ }
            }
        }
        // flush remaining buffer
        if (buffer.startsWith('data: ')) {
            try { yield JSON.parse(buffer.slice(6)); } catch { /* ignore */ }
        }
    },
    // RAG / AI chat — legacy non-streaming (fallback)
    chatAI: (question, documentId) => request('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, document_id: documentId || null }),
    }),
    // Admin AI document management
    adminDocumentStatus: () => request('/admin/documents/ai-status'),
    adminSetDocumentAI: (documentId, enabled) => request(`/admin/documents/${encodeURIComponent(documentId)}/ai?enabled=${enabled}`, {
        method: 'POST',
    }),
};
