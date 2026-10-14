/*
   Reader: the three-pane view behind "All stories" and "Saved".
   All filter state lives in the URL so Back, refresh and Ctrl-click keep working:

   #/stories?folder=breaking&cat=legal&from=2026-10-01&to=2026-10-11&sort=newest&q=gpt6&story=<url>
   #/saved?cat=legal&story=<url>
*/

const Reader = {
    el: null,
    mode: 'stories',      // 'stories' | 'saved'
    params: new URLSearchParams(),
    list: [],             // stories currently shown in the list
    _layoutKey: null,

    FOLDERS: [
        { id: 'all', name: 'All' },
        { id: 'breaking', name: 'Breaking' },
        { id: 'major', name: 'Major' },
        { id: 'notable', name: 'Notable' }
    ],

    SORTS: [
        { id: 'important', name: 'Most important' },
        { id: 'newest', name: 'Newest' },
        { id: 'covered', name: 'Most covered' }
    ],

    init() {
        this.el = document.getElementById('view-stories');
        this.el.addEventListener('click', e => this.onClick(e));
    },

    // ---------- URL helpers ----------

    base() {
        return this.mode === 'saved' ? '#/saved' : '#/stories';
    },

    /** Link to the current view with some params changed (null removes a param). */
    link(changes = {}) {
        const p = new URLSearchParams(this.params);
        for (const [key, value] of Object.entries(changes)) {
            if (value === null || value === '' || value === undefined) p.delete(key);
            else p.set(key, value);
        }
        const query = p.toString();
        return query ? `${this.base()}?${query}` : this.base();
    },

    get(key) {
        return this.params.get(key) || '';
    },

    // ---------- Data ----------

    baseStories() {
        return this.mode === 'saved' ? UserState.savedStories() : Stories.visible();
    },

    filtered({ ignore = [] } = {}) {
        let list = Stories.inRange(this.baseStories(), this.get('from'), this.get('to'));
        if (this.get('q')) list = Stories.search(this.get('q'), list);
        const folder = this.get('folder');
        if (folder && folder !== 'all' && !ignore.includes('folder')) list = list.filter(s => s.label === folder);
        const cat = this.get('cat');
        if (cat && !ignore.includes('cat')) list = list.filter(s => s.category === cat);
        return list;
    },

    sorted(list) {
        const sort = this.get('sort') || (this.mode === 'saved' ? 'saved' : 'important');
        const byDate = s => new Date(s.publishedAt || 0).getTime();
        const copy = [...list];
        if (sort === 'newest') copy.sort((a, b) => byDate(b) - byDate(a));
        else if (sort === 'covered') copy.sort((a, b) => (b.coverage - a.coverage) || (b.score - a.score));
        else if (sort === 'saved') copy.sort((a, b) => new Date(b.savedAt) - new Date(a.savedAt));
        else copy.sort((a, b) => b.score - a.score);
        return copy;
    },

    // ---------- Rendering ----------

    render(mode, params) {
        this.mode = mode;
        this.params = params;

        // Only rebuild the folders and list when the filters change; opening a story just updates the pane
        const key = `${mode}|${[...params].filter(([k]) => k !== 'story').map(([k, v]) => `${k}=${v}`).join('&')}`;
        if (key !== this._layoutKey || !this.el.querySelector('.reader')) {
            this._layoutKey = key;
            this.renderLayout();
        }
        this.renderSelection();
    },

    /** Force a full re-render on the next render() call (data changed). */
    invalidate() {
        this._layoutKey = null;
    },

    renderLayout() {
        this.list = this.sorted(this.filtered());

        this.el.innerHTML = `
            <div class="reader">
                <nav class="folders" aria-label="Folders">${this.foldersHtml()}</nav>
                <section class="story-list" aria-label="Story list">
                    <div class="list-head">${this.listHeadHtml()}</div>
                    ${this.list.length ? `<ol class="rows">${this.list.map(s => this.rowHtml(s)).join('')}</ol>` : this.emptyListHtml()}
                </section>
                <section class="pane" aria-label="Story" aria-live="polite"></section>
            </div>`;
    },

    foldersHtml() {
        const cat = this.get('cat');
        const folder = this.get('folder') || 'all';
        const forFolders = this.filtered({ ignore: ['folder'] });
        const forCats = this.filtered({ ignore: ['cat'] });
        const count = (list, fn) => list.filter(fn).length;

        const folderLinks = this.mode === 'saved'
            ? `<a href="${this.link({ folder: null, story: null })}" aria-current="${folder === 'all'}"><span class="folder-mark" aria-hidden="true"></span>All saved<span class="n">${forFolders.length}</span></a>`
            : this.FOLDERS.map(f => {
                const n = f.id === 'all' ? forFolders.length : count(forFolders, s => s.label === f.id);
                const icon = f.id === 'breaking' ? '<svg class="icon"><use href="#i-bolt"/></svg>' : '';
                return `<a href="${this.link({ folder: f.id === 'all' ? null : f.id, story: null })}" aria-current="${folder === f.id}">${icon}${f.name}<span class="n">${n}</span></a>`;
            }).join('');

        const catLinks = Object.entries(CONFIG.CATEGORIES).map(([id, name]) => `
            <a href="${this.link({ cat: cat === id ? null : id, story: null })}" aria-current="${cat === id}">
                <span class="cat-dot cat-${id}" aria-hidden="true"></span>${Util.esc(name)}<span class="n">${count(forCats, s => s.category === id)}</span>
            </a>`).join('');

        return `${folderLinks}<h2>Categories</h2>${catLinks}`;
    },

    listHeadHtml() {
        const folder = this.get('folder');
        const title = this.mode === 'saved' ? 'Saved' : (this.FOLDERS.find(f => f.id === folder)?.name || 'All stories');
        const unread = this.list.filter(s => !UserState.isRead(s.id)).length;
        const countText = this.mode === 'saved'
            ? `${this.list.length} ${this.list.length === 1 ? 'story' : 'stories'}`
            : `${unread} unread of ${this.list.length}`;

        const from = this.get('from');
        const to = this.get('to');
        const dateText = from || to ? this.rangeText(from, to) : 'Any date';
        const filtersOn = from || to || this.get('cat') || this.get('q');
        const sorts = this.mode === 'saved' ? [{ id: 'saved', name: 'Newest saved' }, ...this.SORTS.slice(0, 2)] : this.SORTS;
        const currentSort = this.get('sort') || sorts[0].id;

        return `
            <div class="list-head-top"><h1>${Util.esc(title)}</h1><small aria-live="polite">${countText}</small></div>
            <div class="filter-bar">
                <button type="button" class="chip ${from || to ? 'is-active' : ''}" id="date-chip" aria-expanded="false" aria-controls="date-pop">
                    <svg class="icon"><use href="#i-cal"/></svg>${Util.esc(dateText)}<svg class="icon"><use href="#i-chev"/></svg>
                </button>
                ${this.get('cat') ? `<a class="chip is-active" href="${this.link({ cat: null, story: null })}" aria-label="Remove ${Util.esc(CONFIG.CATEGORIES[this.get('cat')])} filter">${Util.esc(CONFIG.CATEGORIES[this.get('cat')])} ✕</a>` : ''}
                ${this.get('q') ? `<a class="chip is-active" href="${this.link({ q: null, story: null })}" aria-label="Remove search filter">“${Util.esc(this.get('q'))}” ✕</a>` : ''}
                ${filtersOn ? `<a class="clear" href="${this.link({ from: null, to: null, cat: null, q: null, story: null })}">Clear all</a>` : ''}
            </div>
            <nav class="sort" aria-label="Sort">
                ${sorts.map(s => `<a href="${this.link({ sort: s.id === sorts[0].id ? null : s.id })}" aria-current="${currentSort === s.id}">${s.name}</a>`).join('')}
            </nav>`;
    },

    rowHtml(s) {
        const read = this.mode === 'stories' && UserState.isRead(s.id);
        const date = this.mode === 'saved' && s.savedAt ? `Saved ${Util.shortDate(s.savedAt)}` : Util.shortDate(s.publishedAt);
        return `
            <li class="${read || this.mode === 'saved' ? 'is-read' : ''}" data-id="${Util.esc(s.id)}">
                <a href="${this.link({ story: s.id })}">
                    <span class="dot-unread" aria-hidden="true"></span>
                    <span class="row-title">${Util.esc(s.headline)}</span>
                    <span class="row-date">${Util.esc(date)}</span>
                    <span class="story-meta">${Stories.labelHtml(s)}<span>${Util.esc(s.source)}</span>${s.coverage > 1 ? `<span>${s.coverage} sources</span>` : ''}${read ? '<span class="sr-only">Read</span>' : ''}</span>
                </a>
            </li>`;
    },

    emptyListHtml() {
        if (this.mode === 'saved' && !this.baseStories().length) {
            return `<div class="empty-state"><h2>Nothing saved yet</h2><p>Press S or "Save" on any story to keep it here. Saved stories stay even after they leave the weekly list.</p><a class="btn" href="#/today">Go to Today</a></div>`;
        }
        if (!this.baseStories().length) {
            return `<div class="empty-state"><h2>No stories yet</h2><p>New stories arrive every 4 hours.</p></div>`;
        }
        return `<div class="empty-state"><h2>No stories match these filters</h2><p>Try a wider date range or another category.</p><a class="btn" href="${this.link({ from: null, to: null, cat: null, q: null, folder: null, story: null })}">Clear all filters</a></div>`;
    },

    renderSelection() {
        const id = this.get('story');
        const story = id ? (this.list.find(s => s.id === id) || Stories.byId(id) || UserState.savedStories().find(s => s.id === id)) : null;
        const pane = this.el.querySelector('.pane');
        this.el.querySelector('.reader').classList.toggle('has-story', !!story);

        this.el.querySelectorAll('.rows a[aria-current]').forEach(a => a.removeAttribute('aria-current'));
        if (!story) {
            pane.innerHTML = `<div class="empty-state"><h2>Pick a story to read it here</h2><p>Use <kbd>J</kbd> and <kbd>K</kbd> to move through the list.</p></div>`;
            return;
        }

        if (this.mode === 'stories') {
            UserState.setRead(story.id);
            const row = this.el.querySelector(`.rows li[data-id="${CSS.escape(story.id)}"]`);
            row?.classList.add('is-read');
        }
        const rowLink = this.el.querySelector(`.rows li[data-id="${CSS.escape(story.id)}"] a`);
        if (rowLink) {
            rowLink.setAttribute('aria-current', 'true');
            rowLink.scrollIntoView({ block: 'nearest' });
        }

        const back = `<a class="btn btn-small mobile-back" href="${this.link({ story: null })}">Back to list</a>`;
        const extra = this.mode === 'stories'
            ? `<button type="button" class="btn" data-action="unread">Mark unread<kbd>E</kbd></button>`
            : '';
        pane.innerHTML = Stories.articleHtml(story, { actions: extra }) + `<p class="kbd-hint pane-hint">J and K move between stories. ${back}</p>`;
        this.updateUnreadCount();
    },

    updateUnreadCount() {
        if (this.mode !== 'stories') return;
        const small = this.el.querySelector('.list-head small');
        if (small) small.textContent = `${this.list.filter(s => !UserState.isRead(s.id)).length} unread of ${this.list.length}`;
    },

    currentStory() {
        const id = this.get('story');
        return id ? (Stories.byId(id) || UserState.savedStories().find(s => s.id === id)) : null;
    },

    // ---------- Actions ----------

    onClick(e) {
        if (e.target.closest('#date-chip')) return this.toggleDatePop();
        const btn = e.target.closest('[data-action]');
        if (!btn) return;
        const story = this.currentStory();
        if (!story) return;

        if (btn.dataset.action === 'save') this.toggleSave(story);
        if (btn.dataset.action === 'note') Notes.openAddToNote(story);
        if (btn.dataset.action === 'unread') this.toggleRead(story);
    },

    toggleSave(story) {
        const saved = UserState.toggleSaved(story);
        const btn = this.el.querySelector('.pane [data-action="save"]');
        if (btn) {
            btn.setAttribute('aria-pressed', String(saved));
            btn.querySelector('span').textContent = saved ? 'Saved' : 'Save';
        }
        if (this.mode === 'saved' && !saved) {
            Util.toast('Removed from saved.', {
                action: { label: 'Undo', onClick: () => { UserState.toggleSaved(story); this.invalidate(); App.route(); } },
                timeout: 6000
            });
            this.invalidate();
            location.hash = this.link({ story: null });
            return;
        }
        Util.toast(saved ? 'Saved.' : 'Removed from saved.');
    },

    toggleRead(story) {
        const read = !UserState.isRead(story.id);
        UserState.setRead(story.id, read);
        this.el.querySelector(`.rows li[data-id="${CSS.escape(story.id)}"]`)?.classList.toggle('is-read', read);
        this.updateUnreadCount();
        Util.toast(read ? 'Marked as read.' : 'Marked as unread.');
    },

    /** Move the selection up or down the list. */
    step(delta) {
        if (!this.list.length) return;
        const index = this.list.findIndex(s => s.id === this.get('story'));
        const next = index === -1 ? 0 : Math.min(this.list.length - 1, Math.max(0, index + delta));
        location.hash = this.link({ story: this.list[next].id });
    },

    onKey(e) {
        const key = e.key.toLowerCase();
        const story = this.currentStory();
        if (key === 'j') this.step(1);
        else if (key === 'k') this.step(-1);
        else if (key === 's' && story) this.toggleSave(story);
        else if (key === 'n' && story) Notes.openAddToNote(story);
        else if (key === 'e' && story && this.mode === 'stories') this.toggleRead(story);
        else if (key === 'o' && story) window.open(story.url, '_blank', 'noopener');
        else return false;
        return true;
    },

    // ---------- Date filter popover ----------

    rangeText(from, to) {
        const f = from ? Util.shortDate(`${from}T12:00:00+05:30`) : '';
        const t = to ? Util.shortDate(`${to}T12:00:00+05:30`) : '';
        if (from && to) return from === to ? f : `${f} – ${t}`;
        return from ? `From ${f}` : `Until ${t}`;
    },

    addDays(dayKey, n) {
        const d = new Date(`${dayKey}T12:00:00+05:30`);
        d.setUTCDate(d.getUTCDate() + n);
        return Util.dayKey(d);
    },

    presets() {
        const today = Util.dayKey();
        const weekday = new Date(`${today}T12:00:00+05:30`).getUTCDay(); // 0 = Sunday
        const monday = this.addDays(today, -((weekday + 6) % 7));
        return [
            { id: 'any', name: 'Any date', from: '', to: '' },
            { id: 'today', name: 'Today', from: today, to: today },
            { id: 'week', name: 'This week', from: monday, to: today },
            { id: '7', name: 'Last 7 days', from: this.addDays(today, -6), to: today },
            { id: '30', name: 'Last 30 days', from: this.addDays(today, -29), to: today }
        ];
    },

    toggleDatePop() {
        const existing = this.el.querySelector('#date-pop');
        if (existing) return this.closeDatePop();

        const chip = this.el.querySelector('#date-chip');
        chip.setAttribute('aria-expanded', 'true');
        const from = this.get('from');
        const to = this.get('to');
        const today = Util.dayKey();

        const pop = document.createElement('div');
        pop.className = 'date-pop';
        pop.id = 'date-pop';
        pop.setAttribute('role', 'dialog');
        pop.setAttribute('aria-label', 'Filter by date');
        pop.innerHTML = `
            <div class="presets">${this.presets().map(p => `<button type="button" class="chip" data-preset="${p.id}" aria-pressed="${p.from === from && p.to === to}">${p.name}</button>`).join('')}</div>
            <div class="range">
                <div class="field"><label for="date-from">From</label><input type="date" id="date-from" max="${today}" value="${from}"></div>
                <div class="field"><label for="date-to">To</label><input type="date" id="date-to" max="${today}" value="${to}"></div>
            </div>
            <div class="date-pop-foot">
                <span class="muted" style="font-size:12.5px">Dates in India time</span>
                <div class="actions">
                    <button type="button" class="btn btn-small" data-pop="cancel">Cancel</button>
                    <button type="button" class="btn btn-primary btn-small" data-pop="apply"></button>
                </div>
            </div>`;
        this.el.querySelector('.story-list').appendChild(pop);

        const fromEl = pop.querySelector('#date-from');
        const toEl = pop.querySelector('#date-to');
        const applyBtn = pop.querySelector('[data-pop="apply"]');

        // Live count before applying, so there are no surprises
        const update = () => {
            let a = fromEl.value, b = toEl.value;
            if (a && b && a > b) [a, b] = [b, a];
            let list = Stories.inRange(this.baseStories(), a, b);
            const folder = this.get('folder');
            if (folder && folder !== 'all') list = list.filter(s => s.label === folder);
            if (this.get('cat')) list = list.filter(s => s.category === this.get('cat'));
            if (this.get('q')) list = Stories.search(this.get('q'), list);
            applyBtn.textContent = `Show ${list.length} ${list.length === 1 ? 'story' : 'stories'}`;
            pop.querySelectorAll('[data-preset]').forEach(btn => {
                const p = this.presets().find(x => x.id === btn.dataset.preset);
                btn.setAttribute('aria-pressed', String(p.from === fromEl.value && p.to === toEl.value));
            });
        };

        pop.addEventListener('click', e => {
            const preset = e.target.closest('[data-preset]');
            if (preset) {
                const p = this.presets().find(x => x.id === preset.dataset.preset);
                fromEl.value = p.from;
                toEl.value = p.to;
                update();
            }
            if (e.target.closest('[data-pop="cancel"]')) this.closeDatePop();
            if (e.target.closest('[data-pop="apply"]')) {
                let a = fromEl.value, b = toEl.value;
                if (a && b && a > b) [a, b] = [b, a];
                this.closeDatePop(false);
                location.hash = this.link({ from: a || null, to: b || null, story: null });
            }
        });
        pop.addEventListener('keydown', e => {
            if (e.key === 'Escape') { e.stopPropagation(); this.closeDatePop(); }
        });
        fromEl.addEventListener('input', update);
        toEl.addEventListener('input', update);

        // Close when clicking anywhere else
        this._outside = e => {
            if (!pop.contains(e.target) && !e.target.closest('#date-chip')) this.closeDatePop(false);
        };
        setTimeout(() => document.addEventListener('mousedown', this._outside));

        update();
        (pop.querySelector('[data-preset][aria-pressed="true"]') || pop.querySelector('[data-preset]')).focus();
    },

    closeDatePop(returnFocus = true) {
        this.el.querySelector('#date-pop')?.remove();
        document.removeEventListener('mousedown', this._outside);
        const chip = this.el.querySelector('#date-chip');
        if (chip) {
            chip.setAttribute('aria-expanded', 'false');
            if (returnFocus) chip.focus();
        }
    }
};

window.Reader = Reader;
