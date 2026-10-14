/*
   Settings: preferences, my sources and account for everyone;
   sources, users and audit log for admins.

   Routes: #/settings/preferences | sources | account | admin-sources | users | audit
*/

const Settings = {
    el: null,
    page: 'preferences',
    sources: [],
    sourceFilter: { query: '', category: 'all' },

    PAGES: {
        preferences: { title: 'Preferences' },
        sources: { title: 'My sources' },
        account: { title: 'Account and password' },
        'admin-sources': { title: 'Sources', admin: true },
        users: { title: 'Users', admin: true },
        audit: { title: 'Audit log', admin: true }
    },

    init() {
        this.el = document.getElementById('view-settings');
        this.el.addEventListener('click', e => this.onClick(e));
        this.el.addEventListener('change', e => this.onChange(e));
        this.el.addEventListener('input', e => this.onInput(e));
        this.bindSourceDialog();
    },

    /** Load the source list and work out which stories to hide (personal and global switches). */
    async loadSources() {
        this.sources = await db.getSources();
        const hidden = new Set(UserState.hiddenSources());
        Stories.hiddenNames = this.sources
            .filter(s => hidden.has(String(s.id)) || s.enabled === false)
            .map(s => s.name);
    },

    /** Stories this week from a source. Matched by name, since the pipeline doesn't send source ids. */
    storyCount(source) {
        return Stories.fromSource(source.name).length;
    },

    // ---------- Rendering ----------

    async render(parts) {
        let page = parts[0] || 'preferences';
        if (!this.PAGES[page]) page = 'preferences';
        if (this.PAGES[page].admin && !Auth.isAdmin()) page = 'preferences';
        this.page = page;

        this.el.innerHTML = `
            <div class="settings">
                <nav class="settings-nav" aria-label="Settings">
                    <h2>You</h2>
                    ${this.navLink('preferences')}${this.navLink('sources')}${this.navLink('account')}
                    ${Auth.isAdmin() ? `<div class="admin-group"><h2>Admin</h2>${this.navLink('admin-sources')}${this.navLink('users')}${this.navLink('audit')}</div>` : ''}
                </nav>
                <div class="settings-body" id="settings-body"><p class="muted">Loading…</p></div>
            </div>`;

        const body = this.el.querySelector('#settings-body');
        if (page === 'preferences') body.innerHTML = this.preferencesHtml();
        if (page === 'account') body.innerHTML = this.accountHtml();
        if (page === 'sources' || page === 'admin-sources') {
            await this.loadSources();
            body.innerHTML = page === 'sources' ? this.mySourcesHtml() : this.adminSourcesHtml();
        }
        if (page === 'users') body.innerHTML = await this.usersHtml();
        if (page === 'audit') {
            this.auditEntries = await db.getAuditLog();
            body.innerHTML = this.auditHtml();
        }
    },

    navLink(page) {
        return `<a href="#/settings/${page}" ${this.page === page ? 'aria-current="page"' : ''}>${this.PAGES[page].title}</a>`;
    },

    // ---------- Preferences ----------

    preferencesHtml() {
        const prefs = UserState.prefs();
        const theme = UserState.theme();
        const radio = (name, value, current, text) =>
            `<label><input type="radio" name="${name}" value="${value}" ${String(current) === String(value) ? 'checked' : ''}><span>${text}</span></label>`;

        return `
            <div class="settings-head"><h1>Preferences</h1></div>
            <p class="settings-lede">These only change News Intel for you.</p>

            <div class="setting-row">
                <div><h2 id="pref-theme-label">Theme</h2><p>System follows your laptop's light or dark setting.</p></div>
                <div class="segmented" role="radiogroup" aria-labelledby="pref-theme-label">
                    ${radio('theme', 'light', theme, 'Light')}${radio('theme', 'dark', theme, 'Dark')}${radio('theme', 'system', theme, 'System')}
                </div>
            </div>

            <div class="setting-row">
                <div><h2 id="pref-count-label">Stories in Today's list</h2><p>Five takes about ten minutes. A change applies from the next list.</p></div>
                <div class="segmented" role="radiogroup" aria-labelledby="pref-count-label">
                    ${radio('dailyCount', 3, prefs.dailyCount, '3')}${radio('dailyCount', 5, prefs.dailyCount, '5')}${radio('dailyCount', 7, prefs.dailyCount, '7')}
                </div>
            </div>

            <div class="setting-row">
                <div><h2 id="pref-legal-label">Always include Legal India</h2><p>Keep at least one Legal India story in Today's list, even in a busy AI week.</p></div>
                <button type="button" class="switch" role="switch" aria-checked="${prefs.includeLegal}" aria-labelledby="pref-legal-label" data-pref="includeLegal"></button>
            </div>

            <div class="setting-row">
                <div><h2>Keyboard shortcuts</h2><p>J and K to move, S to save, N to add to a note, Ctrl K to search.</p></div>
                <button type="button" class="btn btn-small" data-open="shortcuts">Show all shortcuts<kbd>?</kbd></button>
            </div>`;
    },

    /** Apply a Today preference now if the list hasn't been started, otherwise from the next list. */
    resetTodayIfUnstarted() {
        const session = UserState.todaySession();
        if (session && !session.heard.length) UserState.saveTodaySession(null);
    },

    // ---------- My sources ----------

    sourceToolbarHtml() {
        const counts = { all: this.sources.length };
        for (const id of Object.keys(CONFIG.CATEGORIES)) counts[id] = this.sources.filter(s => s.category === id).length;
        const hiddenCount = UserState.hiddenSources().length;
        const f = this.sourceFilter;
        const chip = (id, text, n) => `<button type="button" class="chip" data-source-cat="${id}" aria-pressed="${f.category === id}">${text} ${n}</button>`;

        return `
            <div class="toolbar">
                <label class="sr-only" for="source-search">Find a source</label>
                <input type="text" id="source-search" autocomplete="off" placeholder="Find a source…" value="${Util.esc(f.query)}">
                ${chip('all', 'All', counts.all)}
                ${Object.entries(CONFIG.CATEGORIES).map(([id, name]) => chip(id, Util.esc(name), counts[id])).join('')}
                ${this.page === 'sources' ? chip('hidden', 'Hidden', hiddenCount) : ''}
            </div>`;
    },

    filteredSources() {
        const q = Util.normalize(this.sourceFilter.query);
        const hidden = new Set(UserState.hiddenSources());
        return this.sources.filter(s => {
            if (q && !Util.normalize(`${s.name} ${s.url}`).includes(q)) return false;
            if (this.sourceFilter.category === 'hidden') return hidden.has(String(s.id));
            return this.sourceFilter.category === 'all' || s.category === this.sourceFilter.category;
        });
    },

    mySourcesHtml() {
        const hidden = new Set(UserState.hiddenSources());
        const shown = this.sources.filter(s => !hidden.has(String(s.id)) && s.enabled !== false).length;
        return `
            <div class="settings-head"><h1>My sources</h1></div>
            <p class="settings-lede">Hide sources you don't need. Their stories are left out of Today and All stories, for you only. You're showing ${shown} of ${this.sources.length}.</p>
            ${this.sourceToolbarHtml()}
            <div class="table-wrap" id="source-table">${this.mySourcesTable()}</div>`;
    },

    mySourcesTable() {
        const hidden = new Set(UserState.hiddenSources());
        const rows = this.filteredSources();
        if (!rows.length) return `<p class="empty-state">No sources match.</p>`;
        return `
            <table>
                <thead><tr><th scope="col">Source</th><th scope="col">Category</th><th scope="col">This week</th><th scope="col">Show me</th></tr></thead>
                <tbody>${rows.map(s => {
                    const isHidden = hidden.has(String(s.id));
                    const globallyOff = s.enabled === false;
                    const n = this.storyCount(s);
                    return `
                    <tr class="${isHidden || globallyOff ? 'is-off' : ''}">
                        <td>${Util.esc(s.name)}<small>${globallyOff ? 'Turned off for everyone by an admin' : Util.esc(Util.hostname(s.url))}</small></td>
                        <td>${Util.esc(CONFIG.CATEGORIES[s.category] || s.category)}</td>
                        <td class="num">${n ? `${n} ${n === 1 ? 'story' : 'stories'}` : '<span class="muted">None</span>'}</td>
                        <td>${globallyOff
                            ? '<span class="status status-off">Off for everyone</span>'
                            : `<button type="button" class="switch" role="switch" aria-checked="${!isHidden}" aria-label="Show ${Util.esc(s.name)}" data-hide-source="${Util.esc(s.id)}"></button>`}</td>
                    </tr>`;
                }).join('')}</tbody>
            </table>`;
    },

    // ---------- Account ----------

    accountHtml() {
        const user = Auth.currentUser || {};
        const canChangePassword = !!db.getSupabase();
        return `
            <div class="settings-head"><h1>Account and password</h1></div>
            <div class="setting-row"><div><h2>Name</h2><p>${Util.esc(Auth.displayName())}</p></div></div>
            <div class="setting-row"><div><h2>Email</h2><p>${Util.esc(user.email || '')}</p></div></div>
            <div class="setting-row"><div><h2>Role</h2><p>${Auth.isAdmin() ? 'Admin' : 'Member'}</p></div></div>
            ${canChangePassword ? `
            <form class="account-form" id="password-form" novalidate>
                <h2>Change password</h2>
                <div class="field">
                    <label for="account-password">New password</label>
                    <input type="password" id="account-password" name="new-password" autocomplete="new-password" minlength="8" required>
                    <span class="hint">At least 8 characters.</span>
                </div>
                <p class="form-error" id="account-error" aria-live="polite"></p>
                <button type="submit" class="btn btn-primary">Save new password</button>
            </form>` : '<p class="muted">Password changes need Supabase. They are not available in demo mode.</p>'}
            <div><button type="button" class="btn" data-action="sign-out"><svg class="icon"><use href="#i-out"/></svg>Sign out</button></div>`;
    },

    async changePassword(form) {
        const input = form.querySelector('#account-password');
        const error = form.querySelector('#account-error');
        const btn = form.querySelector('button[type="submit"]');
        if (input.value.length < 8) {
            error.textContent = 'Use a password with at least 8 characters.';
            input.setAttribute('aria-invalid', 'true');
            input.focus();
            return;
        }
        input.removeAttribute('aria-invalid');
        btn.disabled = true;
        btn.textContent = 'Saving…';
        const { error: err } = await db.getSupabase().auth.updateUser({ password: input.value });
        btn.disabled = false;
        btn.textContent = 'Save new password';
        if (err) {
            error.textContent = Auth._friendly(err);
            return;
        }
        error.textContent = '';
        input.value = '';
        Util.toast('Password updated.');
    },

    // ---------- Admin: sources ----------

    adminSourcesHtml() {
        const stats = Stories.stats();
        const off = this.sources.filter(s => s.enabled === false).length;
        return `
            <div class="settings-head">
                <h1>Sources</h1>
                <span class="muted">The pipeline checks feeds every 4 hours.</span>
                <button type="button" class="btn btn-primary btn-small right" data-open="source-dialog"><svg class="icon"><use href="#i-plus"/></svg>Add source</button>
            </div>
            <div class="summary">
                ${stats.sources_total ? `<div><span class="status status-ok"></span><strong>${stats.sources_healthy}</strong>of ${stats.sources_total} feeds healthy at the last run</div>` : ''}
                <div><strong>${this.sources.length - off}</strong>on for everyone</div>
                <div><span class="status status-off"></span><strong>${off}</strong>turned off</div>
            </div>
            ${this.sourceToolbarHtml()}
            <div class="table-wrap" id="source-table">${this.adminSourcesTable()}</div>
            <p class="callout">Turning a source off hides its stories for everyone. Every change is recorded in the audit log.</p>`;
    },

    adminSourcesTable() {
        const rows = this.filteredSources();
        if (!rows.length) return `<p class="empty-state">No sources match.</p>`;
        return `
            <table>
                <thead><tr><th scope="col">Source</th><th scope="col">Category</th><th scope="col">This week</th><th scope="col">Status</th><th scope="col">On for everyone</th></tr></thead>
                <tbody>${rows.map(s => {
                    const on = s.enabled !== false;
                    const n = this.storyCount(s);
                    return `
                    <tr class="${on ? '' : 'is-off'}">
                        <td>${Util.esc(s.name)}<small>${Util.esc(s.url)}</small></td>
                        <td>${Util.esc(CONFIG.CATEGORIES[s.category] || s.category)}</td>
                        <td class="num">${n || '<span class="muted">None</span>'}</td>
                        <td><span class="status ${on ? 'status-ok' : 'status-off'}">${on ? 'On' : 'Off for everyone'}</span></td>
                        <td><button type="button" class="switch" role="switch" aria-checked="${on}" aria-label="${Util.esc(s.name)} on for everyone" data-global-source="${Util.esc(s.id)}"></button></td>
                    </tr>`;
                }).join('')}</tbody>
            </table>`;
    },

    async setSourceGlobal(id, enabled, { undo = true } = {}) {
        const source = this.sources.find(s => String(s.id) === String(id));
        if (!source) return;
        try {
            await db.updateSource(id, { enabled });
        } catch (e) {
            console.error(e);
            Util.toast("Couldn't change the source. Check your connection and try again.");
            return;
        }
        await db.logAudit('source_toggle', `${enabled ? 'Turned on' : 'Turned off'} ${source.name} for everyone`);
        await this.loadSources();
        this.refreshSourceTable();
        Reader.invalidate();

        const n = this.storyCount(source);
        const impact = n ? ` ${n} ${n === 1 ? 'story' : 'stories'} ${enabled ? 'shown again' : 'hidden'}.` : '';
        Util.toast(`${source.name} is ${enabled ? 'on' : 'off'} for everyone.${impact}`, {
            timeout: 6000,
            action: undo ? { label: 'Undo', onClick: () => this.setSourceGlobal(id, !enabled, { undo: false }) } : null
        });
    },

    refreshSourceTable() {
        const table = this.el.querySelector('#source-table');
        if (!table) return;
        table.innerHTML = this.page === 'sources' ? this.mySourcesTable() : this.adminSourcesTable();
        const toolbar = this.el.querySelector('.toolbar');
        if (toolbar) {
            const focusedSearch = document.activeElement?.id === 'source-search';
            toolbar.outerHTML = this.sourceToolbarHtml();
            if (focusedSearch) {
                const input = this.el.querySelector('#source-search');
                input.focus();
                input.setSelectionRange(input.value.length, input.value.length);
            }
        }
    },

    bindSourceDialog() {
        const dialog = document.getElementById('source-dialog');
        dialog.querySelector('[data-close]').addEventListener('click', () => dialog.close());
        document.getElementById('source-form').addEventListener('submit', async e => {
            e.preventDefault();
            const nameEl = document.getElementById('source-name');
            const urlEl = document.getElementById('source-url');
            const error = document.getElementById('source-error');
            const name = nameEl.value.trim();
            let url = urlEl.value.trim();
            [nameEl, urlEl].forEach(el => el.removeAttribute('aria-invalid'));

            if (!name) {
                error.textContent = 'Give the source a name.';
                nameEl.setAttribute('aria-invalid', 'true');
                return nameEl.focus();
            }
            if (url && !/^https?:\/\//i.test(url)) url = `https://${url}`;
            try { new URL(url); } catch {
                error.textContent = 'Enter a feed address, such as techcrunch.com/feed.';
                urlEl.setAttribute('aria-invalid', 'true');
                return urlEl.focus();
            }
            if (this.sources.some(s => s.url === url)) {
                error.textContent = `This feed is already listed as ${this.sources.find(s => s.url === url).name}.`;
                urlEl.setAttribute('aria-invalid', 'true');
                return urlEl.focus();
            }

            error.textContent = '';
            try {
                await db.addSource({ name, url, category: document.getElementById('source-category').value, enabled: true });
            } catch (err) {
                console.error(err);
                error.textContent = "Couldn't add the source. Check your connection and try again.";
                return;
            }
            dialog.close();
            e.target.reset();
            await this.loadSources();
            this.refreshSourceTable();
            Util.toast(`${name} added. The pipeline will pick it up on its next run.`);
        });
    },

    // ---------- Admin: users ----------

    async usersHtml() {
        this.users = await db.getUsers();
        const admins = this.users.filter(u => u.role === 'admin' || u.is_admin === true).length;
        return `
            <div class="settings-head"><h1>Users</h1><span class="muted">${this.users.length} ${this.users.length === 1 ? 'person' : 'people'}, ${admins} ${admins === 1 ? 'admin' : 'admins'}</span></div>
            <p class="settings-lede">People join by creating an account on the sign-in page. Admins can manage sources, users and the audit log.</p>
            ${this.users.length ? `
            <div class="table-wrap">
                <table>
                    <thead><tr><th scope="col">Person</th><th scope="col">Role</th><th scope="col">Joined</th></tr></thead>
                    <tbody>${this.users.map(u => {
                        const isMe = String(u.id) === String(Auth.currentUser?.id);
                        const role = u.role === 'admin' || u.is_admin === true ? 'admin' : 'user';
                        const name = u.name || u.email || 'Unknown';
                        return `
                        <tr>
                            <td><span class="person"><span class="avatar" aria-hidden="true">${Util.esc(Util.initials(name))}</span><span>${Util.esc(name)}${isMe ? ' (you)' : ''}<small>${Util.esc(u.email || '')}</small></span></span></td>
                            <td>
                                <label class="sr-only" for="role-${Util.esc(u.id)}">Role for ${Util.esc(name)}</label>
                                <select id="role-${Util.esc(u.id)}" data-role-user="${Util.esc(u.id)}" ${isMe ? 'disabled title="You can\'t change your own role"' : ''}>
                                    <option value="user" ${role === 'user' ? 'selected' : ''}>Member</option>
                                    <option value="admin" ${role === 'admin' ? 'selected' : ''}>Admin</option>
                                </select>
                            </td>
                            <td>${u.created_at ? Util.esc(Util.longDate(u.created_at)) : ''}</td>
                        </tr>`;
                    }).join('')}</tbody>
                </table>
            </div>` : '<p class="empty-state">No users found. If you expected people here, check that admins can read the profile table in Supabase.</p>'}
            <p class="callout">Every role change is recorded in the audit log.</p>`;
    },

    async setRole(select) {
        const user = this.users.find(u => String(u.id) === select.dataset.roleUser);
        const previous = user.role === 'admin' || user.is_admin === true ? 'admin' : 'user';
        const role = select.value;
        select.disabled = true;
        try {
            await db.updateUserRole(user, role);
            user.role = role;
        } catch (e) {
            console.error(e);
            select.value = previous;
            Util.toast("Couldn't change the role. Check your connection and try again.");
            select.disabled = false;
            return;
        }
        select.disabled = false;
        Util.toast(`${user.name || user.email} is now ${role === 'admin' ? 'an Admin' : 'a Member'}.`, {
            timeout: 6000,
            action: {
                label: 'Undo',
                onClick: async () => {
                    select.value = previous;
                    await db.updateUserRole(user, previous);
                    user.role = previous;
                }
            }
        });
    },

    // ---------- Admin: audit log ----------

    AUDIT_ACTIONS: {
        login: 'Signed in',
        signup: 'Created an account',
        source_add: 'Added a source',
        source_toggle: 'Turned a source on or off',
        source_approve: 'Approved a source',
        source_reject: 'Rejected a source',
        user_role: 'Changed a role'
    },

    auditFilter: { range: '7', person: 'all', action: 'all' },

    filteredAudit() {
        const f = this.auditFilter;
        const since = f.range === 'all' ? 0 : Date.now() - Number(f.range) * 86400000;
        return (this.auditEntries || []).filter(entry =>
            new Date(entry.created_at || entry.timestamp).getTime() >= since &&
            (f.person === 'all' || entry.user_email === f.person) &&
            (f.action === 'all' || entry.action === f.action)
        );
    },

    auditHtml() {
        const f = this.auditFilter;
        const people = [...new Set((this.auditEntries || []).map(e => e.user_email).filter(Boolean))].sort();
        const option = (value, text, current) => `<option value="${Util.esc(value)}" ${current === value ? 'selected' : ''}>${Util.esc(text)}</option>`;

        return `
            <div class="settings-head">
                <h1>Audit log</h1>
                <button type="button" class="btn btn-small right" data-action="export-audit">Export as CSV</button>
            </div>
            <div class="toolbar">
                <label class="sr-only" for="audit-range">Date range</label>
                <select id="audit-range" data-audit="range">${option('7', 'Last 7 days', f.range)}${option('30', 'Last 30 days', f.range)}${option('all', 'All time', f.range)}</select>
                <label class="sr-only" for="audit-person">Person</label>
                <select id="audit-person" data-audit="person">${option('all', 'Anyone', f.person)}${people.map(p => option(p, p, f.person)).join('')}</select>
                <label class="sr-only" for="audit-action">Action</label>
                <select id="audit-action" data-audit="action">${option('all', 'Any action', f.action)}${Object.entries(this.AUDIT_ACTIONS).map(([k, v]) => option(k, v, f.action)).join('')}</select>
                <span class="muted" id="audit-count"></span>
            </div>
            <div class="table-wrap" id="audit-table">${this.auditTable()}</div>`;
    },

    auditTable() {
        const rows = this.filteredAudit();
        setTimeout(() => {
            const count = this.el.querySelector('#audit-count');
            if (count) count.textContent = `${rows.length} ${rows.length === 1 ? 'entry' : 'entries'}`;
        });
        if (!rows.length) return '<p class="empty-state">No entries for these filters. Try a longer date range.</p>';
        return `
            <table>
                <thead><tr><th scope="col">When (India time)</th><th scope="col">Who</th><th scope="col">Action</th><th scope="col">Details</th></tr></thead>
                <tbody>${rows.map(e => `
                    <tr>
                        <td class="num">${Util.esc(Util.dateTime(e.created_at || e.timestamp))}</td>
                        <td>${Util.esc(e.user_email || 'System')}</td>
                        <td>${Util.esc(this.AUDIT_ACTIONS[e.action] || e.action)}</td>
                        <td>${Util.esc(e.details || '')}</td>
                    </tr>`).join('')}</tbody>
            </table>`;
    },

    exportAudit() {
        const quote = value => `"${String(value ?? '').replace(/"/g, '""')}"`;
        const lines = [['When', 'Who', 'Action', 'Details'].map(quote).join(',')];
        for (const e of this.filteredAudit()) {
            lines.push([e.created_at || e.timestamp, e.user_email, this.AUDIT_ACTIONS[e.action] || e.action, e.details].map(quote).join(','));
        }
        const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = `audit-log-${Util.dayKey()}.csv`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    },

    // ---------- Events ----------

    onClick(e) {
        const target = e.target.closest('button');
        if (!target) return;

        if (target.dataset.pref) {
            const value = target.getAttribute('aria-checked') !== 'true';
            target.setAttribute('aria-checked', String(value));
            UserState.setPref(target.dataset.pref, value);
            this.resetTodayIfUnstarted();
        }
        if (target.dataset.open) document.getElementById(target.dataset.open).showModal();
        if (target.dataset.action === 'sign-out') Auth.signOut();
        if (target.dataset.action === 'export-audit') this.exportAudit();

        if (target.dataset.sourceCat) {
            this.sourceFilter.category = target.dataset.sourceCat;
            this.refreshSourceTable();
        }
        if (target.dataset.hideSource) {
            const show = target.getAttribute('aria-checked') !== 'true';
            UserState.setSourceHidden(target.dataset.hideSource, !show);
            this.loadSources().then(() => {
                this.refreshSourceTable();
                Reader.invalidate();
            });
            this.resetTodayIfUnstarted();
        }
        if (target.dataset.globalSource) {
            const on = target.getAttribute('aria-checked') !== 'true';
            this.setSourceGlobal(target.dataset.globalSource, on);
        }
    },

    onChange(e) {
        const el = e.target;
        if (el.name === 'theme') UserState.setTheme(el.value);
        if (el.name === 'dailyCount') {
            UserState.setPref('dailyCount', Number(el.value));
            this.resetTodayIfUnstarted();
        }
        if (el.dataset.roleUser) this.setRole(el);
        if (el.dataset.audit) {
            this.auditFilter[el.dataset.audit] = el.value;
            this.el.querySelector('#audit-table').innerHTML = this.auditTable();
        }
    },

    onInput(e) {
        if (e.target.id === 'source-search') {
            this.sourceFilter.query = e.target.value;
            this.refreshSourceTable();
        }
    }
};

// Password form uses submit, so bind it through delegation on the document
document.addEventListener('submit', e => {
    if (e.target.id === 'password-form') {
        e.preventDefault();
        Settings.changePassword(e.target);
    }
});

window.Settings = Settings;
