/*
   App: starts everything after sign-in, routes between screens, and handles
   global keyboard shortcuts and the offline banner.

   Routes (hash based, so the static site needs no server config):
     #/today[/n|/done]   #/stories?...   #/saved?...   #/notes[/id|/new]   #/settings[/page]
*/

const App = {
    started: false,
    currentView: null,

    VIEWS: {
        today: { el: 'view-today', title: 'Today' },
        stories: { el: 'view-stories', title: 'All stories' },
        saved: { el: 'view-stories', title: 'Saved' },
        notes: { el: 'view-notes', title: 'Notes' },
        settings: { el: 'view-settings', title: 'Settings' }
    },

    boot() {
        db.initSupabase();
        Auth.init();
    },

    /** Called once the user is signed in. */
    start() {
        if (this.started) return;
        this.started = true;

        UserState.setUser(Auth.currentUser?.id);
        this.renderUser();

        Today.init();
        Reader.init();
        Notes.init();
        Settings.init();
        Palette.init();
        Notices.init();
        this.bindGlobal();

        window.addEventListener('hashchange', () => this.route());
        this.updateCounts();
        this.route();

        // Background work: notes for the counts and palette, source list for hidden sources
        Notes.load();
        Notices.loadRequests();
        db.seedSources(window.DEFAULT_SOURCES || []).then(() => Settings.loadSources()).then(() => {
            if (Stories.hiddenNames.length) {
                Reader.invalidate();
                this.route();
            }
            Notices.render();
            this.updateCounts();
        });
    },

    renderUser() {
        const name = Auth.displayName();
        document.getElementById('user-initials').textContent = Util.initials(name);
        document.getElementById('user-name').textContent = name;
        document.getElementById('user-email').textContent = Auth.currentUser?.email || '';
        document.getElementById('user-role').textContent = Auth.isAdmin() ? 'Admin' : 'Member';
    },

    updateCounts() {
        const set = (id, n) => {
            const el = document.getElementById(id);
            if (el) el.textContent = n ? String(n) : '';
        };
        set('nav-count-stories', Stories.visible().length);
        set('nav-count-saved', UserState.saved().length);
        set('nav-count-notes', Notes.loaded ? Notes.notes.length : 0);
    },

    // ---------- Routing ----------

    parseHash() {
        const raw = location.hash.replace(/^#\/?/, '');
        const [path, query = ''] = raw.split('?');
        const [view, ...parts] = path.split('/').filter(Boolean).map(decodeURIComponent);
        return { view, parts, params: new URLSearchParams(query) };
    },

    async route() {
        let { view, parts, params } = this.parseHash();
        if (!this.VIEWS[view]) {
            history.replaceState(null, '', '#/today');
            ({ view, parts, params } = this.parseHash());
        }

        const config = this.VIEWS[view];
        const viewChanged = this.currentView !== view;
        this.currentView = view;

        document.querySelectorAll('.view').forEach(el => { el.hidden = el.id !== config.el; });
        document.querySelectorAll('[data-nav]').forEach(link => {
            if (link.dataset.nav === view) link.setAttribute('aria-current', 'page');
            else link.removeAttribute('aria-current');
        });
        document.title = `${config.title} · News Intel`;

        if (view === 'today') Today.render(parts);
        if (view === 'stories' || view === 'saved') Reader.render(view, params);
        if (view === 'notes') await Notes.render(parts);
        if (view === 'settings') await Settings.render(parts);
        Notices.render();   // after the view, which may have marked a story read

        if (viewChanged) {
            window.scrollTo(0, 0);
            document.getElementById('main').focus({ preventScroll: true });
        }
    },

    // ---------- Global UI ----------

    bindGlobal() {
        // Account menu
        const menuBtn = document.getElementById('user-menu-btn');
        const menu = document.getElementById('user-menu');
        const setMenu = open => {
            menu.hidden = !open;
            menuBtn.setAttribute('aria-expanded', String(open));
            if (open) menu.querySelector('[role="menuitem"]').focus();
        };
        menuBtn.addEventListener('click', () => setMenu(menu.hidden));
        document.addEventListener('click', e => {
            if (!menu.hidden && !e.target.closest('.user-menu')) setMenu(false);
        });
        menu.addEventListener('keydown', e => {
            if (e.key === 'Escape') { setMenu(false); menuBtn.focus(); }
        });
        menu.addEventListener('click', e => { if (e.target.closest('[role="menuitem"]')) setMenu(false); });
        document.getElementById('sign-out').addEventListener('click', () => Auth.signOut());
        document.getElementById('show-shortcuts').addEventListener('click', () => document.getElementById('shortcuts').showModal());
        document.querySelector('#shortcuts [data-close]').addEventListener('click', () => document.getElementById('shortcuts').close());

        document.addEventListener('keydown', e => this.onKey(e));

        // Offline banner
        const banner = document.getElementById('offline-banner');
        const app = document.getElementById('app');
        const setOnline = () => {
            banner.hidden = navigator.onLine;
            app.classList.toggle('is-offline', !navigator.onLine);
            if (navigator.onLine && Notes.loaded) Notes.syncLocalOnly();
        };
        window.addEventListener('online', setOnline);
        window.addEventListener('offline', setOnline);
        setOnline();
    },

    onKey(e) {
        const mod = e.ctrlKey || e.metaKey;

        if (mod && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            Palette.open();
            return;
        }
        if (mod || e.altKey) return;
        if (document.querySelector('dialog[open]')) return;
        if (Util.isTyping(e)) return;

        // Enter on a focused link or button should do its normal job
        const focusIsNeutral = [document.body, document.getElementById('main')].includes(document.activeElement);
        if (e.key === 'Enter' && !focusIsNeutral) return;

        if (e.key === '/') {
            e.preventDefault();
            Palette.open();
            return;
        }
        if (e.key === '?') {
            document.getElementById('shortcuts').showModal();
            return;
        }

        const handlers = { today: Today, stories: Reader, saved: Reader, notes: Notes };
        const handler = handlers[this.currentView];
        if (handler?.onKey?.(e)) e.preventDefault();
    }
};

window.App = App;

document.addEventListener('DOMContentLoaded', () => App.boot());
