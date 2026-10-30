/*
   Small shared helpers: HTML escaping, dates in IST, safe storage, toasts, search matching.
*/

const Util = {
    /** Escape text before putting it into innerHTML. Every feed or user string goes through this. */
    esc(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },

    /** Decode entities that some feeds leave in headlines, such as &#8216; */
    decode(value) {
        const el = document.createElement('textarea');
        el.innerHTML = String(value ?? '');
        return el.value;
    },

    /** Lowercase and strip spaces and punctuation, so "open ai", "OpenAI" and "gpt6" / "GPT-6" match. */
    normalize(value) {
        return String(value ?? '').toLowerCase().replace(/[^a-z0-9]+/g, '');
    },

    // ---------- Dates (always shown in IST) ----------

    _formatters: {},
    _fmt(key, options) {
        if (!this._formatters[key]) {
            this._formatters[key] = new Intl.DateTimeFormat('en-IN', { timeZone: CONFIG.TIME_ZONE, ...options });
        }
        return this._formatters[key];
    },

    /** YYYY-MM-DD for a date, in IST. */
    dayKey(date = new Date()) {
        return new Intl.DateTimeFormat('en-CA', { timeZone: CONFIG.TIME_ZONE }).format(date);
    },

    /** "13 Oct" */
    shortDate(value) {
        const d = new Date(value);
        return isNaN(d) ? '' : this._fmt('short', { day: 'numeric', month: 'short' }).format(d);
    },

    /** "13 October 2026" */
    longDate(value) {
        const d = new Date(value);
        return isNaN(d) ? '' : this._fmt('long', { day: 'numeric', month: 'long', year: 'numeric' }).format(d);
    },

    /** "Tuesday 13 October" */
    weekdayDate(value = new Date()) {
        return this._fmt('weekday', { weekday: 'long', day: 'numeric', month: 'long' }).format(new Date(value));
    },

    /** "9:40 AM" */
    clock(value) {
        const d = new Date(value);
        return isNaN(d) ? '' : this._fmt('clock', { hour: 'numeric', minute: '2-digit', hour12: true }).format(d).toUpperCase();
    },

    /** "Today, 09:12", "12 Oct, 17:30" */
    dateTime(value) {
        const d = new Date(value);
        if (isNaN(d)) return '';
        const time = this._fmt('time', { hour: '2-digit', minute: '2-digit', hour12: false }).format(d);
        if (this.dayKey(d) === this.dayKey()) return `Today, ${time}`;
        return `${this.shortDate(d)}, ${time}`;
    },

    /** "2 minutes ago" style text for recent edits. */
    relative(value) {
        const seconds = Math.round((Date.now() - new Date(value)) / 1000);
        const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
        if (seconds < 60) return 'just now';
        if (seconds < 3600) return rtf.format(-Math.round(seconds / 60), 'minute');
        if (seconds < 86400) return rtf.format(-Math.round(seconds / 3600), 'hour');
        if (seconds < 86400 * 7) return rtf.format(-Math.round(seconds / 86400), 'day');
        return this.shortDate(value);
    },

    hostname(url) {
        try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return ''; }
    },

    // ---------- Storage (never throws: private windows can block it) ----------

    load(key, fallback) {
        try {
            const raw = localStorage.getItem(key);
            return raw === null ? fallback : JSON.parse(raw);
        } catch {
            return fallback;
        }
    },

    save(key, value) {
        try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage full or blocked */ }
    },

    // ---------- Toasts ----------

    /** Show a short message. Optional action: { label, onClick }. */
    toast(message, { action, timeout = 5000 } = {}) {
        const region = document.getElementById('toasts');
        const el = document.createElement('div');
        el.className = 'toast';
        el.textContent = message;

        if (action) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.textContent = action.label;
            btn.addEventListener('click', () => {
                action.onClick();
                el.remove();
            });
            el.appendChild(btn);
        }

        region.appendChild(el);
        setTimeout(() => el.remove(), timeout);
    },

    /** True when the user is typing, so single-key shortcuts must not fire. */
    isTyping(event) {
        const el = event.target;
        return el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
    },

    initials(name) {
        return String(name || '?').split(/\s+/).filter(Boolean).map(part => part[0]).join('').slice(0, 2).toUpperCase();
    }
};

window.Util = Util;
