/*
   Today: the morning hearing.
   A short list picked from the last few days' stories, read one at a time, ending with "Up to date".

   Routes:  #/today        list (or the finished screen)
            #/today/3      story 3 of the list
            #/today/done   finished screen
*/

const Today = {
    el: null,
    session: null,
    position: null, // 1-based index of the open story, or null on the list

    init() {
        this.el = document.getElementById('view-today');
        this.el.addEventListener('click', e => this.onClick(e));
    },

    // ---------- Building today's list ----------

    /** Published in the last TODAY_DAYS (stories without a date count as recent). */
    isRecent(story) {
        return !story.publishedAt || new Date(story.publishedAt).getTime() >= Date.now() - CONFIG.TODAY_DAYS * 86400000;
    },

    /**
     * Highest-ranked unread stories from the last TODAY_DAYS first (older ones only if there
     * aren't enough), from the domains the user follows (Breaking always counts), at most
     * MAX_PER_DOMAIN per domain so one busy domain can't take every slot. Keep one Legal India
     * story if the user asked for it.
     */
    MAX_PER_DOMAIN: 2,

    buildIds() {
        const prefs = UserState.prefs();
        const count = Number(prefs.dailyCount) || CONFIG.DAILY_COUNT_DEFAULT;
        const followed = UserState.followedDomains();
        // One story per event, so two outlets' takes on the same news never fill two slots
        const candidates = Stories.grouped([...Stories.visible()].sort((a, b) =>
            (UserState.isRead(a.id) - UserState.isRead(b.id)) ||
            (this.isRecent(b) - this.isRecent(a)) || (b.score - a.score)
        ));
        const wanted = s => !followed || followed.includes(s.area) || s.label === 'breaking';
        const ordered = [...candidates.filter(wanted), ...candidates.filter(s => !wanted(s))];

        const picks = [];
        const perDomain = {};
        const repeats = s => picks.some(p => this.sameEvent(p, s));
        for (const s of ordered) {
            if (picks.length >= count) break;
            if ((perDomain[s.area] || 0) >= this.MAX_PER_DOMAIN && s.label !== 'breaking') continue;
            if (repeats(s)) continue;
            picks.push(s);
            perDomain[s.area] = (perDomain[s.area] || 0) + 1;
        }
        // A quiet day with too few domains: fill up regardless of the per-domain limit
        for (const s of ordered) {
            if (picks.length >= count) break;
            if (!picks.includes(s) && !repeats(s)) picks.push(s);
        }

        if (prefs.includeLegal && picks.length && !picks.some(s => s.category === 'legal')) {
            const legal = candidates.find(s => s.category === 'legal' && !picks.includes(s));
            if (legal) picks[picks.length - 1] = legal;
        }
        return picks.sort((a, b) => b.score - a.score).map(s => s.id);
    },

    /**
     * The pipeline leaves many articles about one event ungrouped, so as a fallback two stories
     * count as the same event when they lead with the same company and share a topic word
     * ("IPO filing" and "IPO prospectus").
     */
    sameEvent(a, b) {
        if (a.clusterId && a.clusterId === b.clusterId) return true;
        if (!a.entities[0] || Util.normalize(a.entities[0]) !== Util.normalize(b.entities[0] || '')) return false;
        const generic = new Set(['ai', 'and', 'the', 'of', 'for', 'tech', 'market', 'markets', 'industry', 'news', 'policy', 'strategy', 'corporate', 'business']);
        const words = s => new Set(s.topics.join(' ').toLowerCase().split(/[^a-z0-9]+/).filter(w => w.length > 1 && !generic.has(w)));
        const wa = words(a);
        return [...words(b)].some(w => wa.has(w));
    },

    ensureSession() {
        const today = Util.dayKey();
        let session = UserState.todaySession();
        const stale = !session || session.date !== today || session.ids.some(id => !Stories.byId(id));
        if (stale) {
            session = { date: today, ids: this.buildIds(), heard: [], noted: [], finished: false };
            UserState.saveTodaySession(session);
        }
        this.session = session;
        return session;
    },

    stories() {
        return this.session.ids.map(id => Stories.byId(id)).filter(Boolean);
    },

    // ---------- Rendering ----------

    render(parts) {
        this.ensureSession();
        const stories = this.stories();
        const step = parts[0];

        if (!stories.length) return this.renderEmpty();
        if (step === 'done') return this.renderDone(stories);

        const n = parseInt(step, 10);
        if (n >= 1 && n <= stories.length) return this.renderStory(stories, n);
        // Home opens on the next story not yet read, or the finish line when all are
        if (this.session.finished) return this.renderDone(stories);
        const next = stories.findIndex(s => !this.session.heard.includes(s.id));
        location.replace(`#/today/${next === -1 ? 'done' : next + 1}`);
    },

    renderEmpty() {
        this.position = null;
        this.el.innerHTML = `
            <div class="empty-state">
                <h1>No stories yet</h1>
                <p>The news pipeline hasn't published any stories yet. New stories arrive every morning.</p>
                <a class="btn" href="#/settings/sources">Check your sources</a>
            </div>`;
    },

    renderStory(stories, n) {
        this.position = n;
        const story = stories[n - 1];
        const isLast = n === stories.length;

        if (!this.session.heard.includes(story.id)) {
            this.session.heard.push(story.id);
            this.session.startedAt = this.session.startedAt || Date.now();
            UserState.saveTodaySession(this.session);
        }
        Stories.markRead(story);

        const primary = `<a class="btn btn-primary" href="#/today/${isLast ? 'done' : n + 1}">${isLast ? 'Finish' : 'Next story'}<kbd>→</kbd></a>`;
        const left = isLast ? 'last story' : `about ${(stories.length - n) * this.MINUTES_PER_STORY} min left`;
        const [weekday, date] = Util.weekdayDate().split(/,? (.*)/);

        this.el.innerHTML = `
            <div class="hearing">
                <nav class="rail" id="rail" aria-label="Your briefing">
                    <div><h2>Your briefing</h2><p class="rail-date">${Util.esc(weekday)},<br>${Util.esc(date)}</p></div>
                    <div class="rail-progress">
                        <div class="progress" aria-hidden="true">${stories.map((_, i) => `<span class="${i < n - 1 ? 'is-done' : i === n - 1 ? 'is-now' : ''}"></span>`).join('')}</div>
                        <p class="meta">${n} of ${stories.length} · ${left}</p>
                    </div>
                    <ol class="queue">
                        ${stories.map((s, i) => {
                            const heard = this.session.heard.includes(s.id) && i + 1 !== n;
                            const mark = i + 1 === n ? '→' : heard ? '<svg class="icon"><use href="#i-check"/></svg>' : i + 1;
                            return `<li class="${heard ? 'is-done' : ''}" ${i + 1 === n ? 'aria-current="step"' : ''}>
                                <a href="#/today/${i + 1}"><span class="mark" aria-hidden="true">${mark}</span>${Util.esc(s.headline)}</a>
                            </li>`;
                        }).join('')}
                    </ol>
                </nav>
                ${Panes.handleHtml('a', 'rail', 'Resize the briefing column')}
                ${Stories.articleHtml(story, { headingTag: 'h1', variant: 'brief', primary })}
                ${Panes.handleHtml('c', 'related', 'Resize the related stories column')}
                ${this.relatedHtml(story, stories)}
            </div>`;
        Panes.restore(this.el.querySelector('.hearing'), 'today');
    },

    /**
     * "From your domains": up to three unread stories on the same subject (same company first,
     * then same domain) for the side column. They wait in All stories and never extend Today.
     */
    relatedHtml(story, todays) {
        const lead = Util.normalize(story.entities[0] || '');
        const pool = Stories.grouped(Stories.visible()).filter(s =>
            s.id !== story.id && !(story.clusterId && s.clusterId === story.clusterId) &&
            !todays.includes(s) && !UserState.isRead(s.id) && this.isRecent(s));
        const sameCompany = lead ? pool.filter(s => s.entities.some(e => Util.normalize(e) === lead)) : [];
        const sameDomain = pool.filter(s => s.area === story.area && !sameCompany.includes(s));
        const picks = [...sameCompany, ...sameDomain].slice(0, 3);
        const link = s => `#/stories?${new URLSearchParams({ story: s.id })}`;
        return `
            <aside class="related" id="related" aria-label="From your domains">
                <h2>From your domains</h2>
                ${picks.map(s => `
                    <a class="related-item" href="${link(s)}">
                        ${Stories.labelHtml(s)}
                        <span>${Util.esc(s.headline)}</span>
                        <span class="meta">${Util.esc(s.source)} · ${Util.esc(Stories.categoryName(s))}</span>
                    </a>`).join('') || '<p class="meta">Nothing else on this subject right now.</p>'}
                <p class="meta">Related stories wait in All stories. They never extend Today.</p>
            </aside>`;
    },

    MINUTES_PER_STORY: 2,

    /** When the next stories arrive, from the daily run's schedule (07:01 IST, done by ~7:30). */
    nextUpdateText() {
        const age = Notices.dataAgeHours();
        if (age !== null && age > Notices.STALE_HOURS) return 'The daily update is late, so newer stories may be missing.';
        return 'The next update arrives tomorrow at about 7:30 AM.';
    },

    renderDone(stories) {
        this.position = null;
        if (!this.session.finished) {
            this.session.finished = true;
            this.session.finishedAt = Date.now();
            UserState.saveTodaySession(this.session);
        }
        const unreadMajor = Stories.grouped(Stories.visible())
            .filter(s => s.label !== 'notable' && !UserState.isRead(s.id) && this.isRecent(s)).length;
        const mark = s => UserState.isSaved(s.id) ? 'Saved' : (this.session.noted.includes(s.id) ? 'Added to a note' : '');
        const minutes = this.session.startedAt && this.session.finishedAt
            ? Math.round((this.session.finishedAt - this.session.startedAt) / 60000) : 0;
        const count = `${stories.length} ${stories.length === 1 ? 'story' : 'stories'}`;
        const read = minutes >= 1 && minutes <= 120 ? `${count} in ${minutes} ${minutes === 1 ? 'minute' : 'minutes'}.` : `${count} read.`;

        this.el.innerHTML = `
            <div class="done">
                <span class="seal" aria-hidden="true"><svg class="icon"><use href="#i-check"/></svg></span>
                <h1>You're up to date</h1>
                <p class="done-text">${read} ${Util.esc(this.nextUpdateText())}</p>
                <ol class="recap" aria-label="What you read">
                    ${stories.map((s, i) => `
                        <li><svg class="icon" aria-hidden="true"><use href="#i-check"/></svg><a href="#/today/${i + 1}">${Util.esc(s.headline)}</a><span>${mark(s)}</span></li>`).join('')}
                </ol>
                <p class="meta">${unreadMajor
                    ? `Want more? <a href="#/stories?folder=major">All stories</a> has ${unreadMajor} unread Breaking and Major ${unreadMajor === 1 ? 'story' : 'stories'} from this week.`
                    : 'You have also read every Breaking and Major story from this week.'}</p>
            </div>`;
    },

    // ---------- Actions ----------

    currentStory() {
        return this.position ? this.stories()[this.position - 1] : null;
    },

    onClick(e) {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;
        const story = this.currentStory();
        if (!story) return;

        if (btn.dataset.action === 'save') this.toggleSave(story);
        if (btn.dataset.action === 'note') this.addToNote(story);
    },

    toggleSave(story) {
        const saved = UserState.toggleSaved(story);
        const btn = this.el.querySelector('[data-action="save"]');
        if (btn) {
            btn.setAttribute('aria-pressed', String(saved));
            btn.querySelector('span').textContent = saved ? 'Saved' : 'Save';
        }
        Util.toast(saved ? 'Saved.' : 'Removed from saved.');
    },

    addToNote(story) {
        Notes.openAddToNote(story, () => {
            if (!this.session.noted.includes(story.id)) {
                this.session.noted.push(story.id);
                UserState.saveTodaySession(this.session);
            }
        });
    },

    /** Keyboard shortcuts while Today is open. Returns true when handled. */
    onKey(e) {
        const stories = this.session ? this.stories() : [];
        if (!this.position) return false;

        const story = this.currentStory();
        const key = e.key.toLowerCase();
        if (key === 'arrowright' || key === 'enter') {
            location.hash = this.position === stories.length ? '#/today/done' : `#/today/${this.position + 1}`;
        } else if (key === 'arrowleft' && this.position > 1) {
            location.hash = `#/today/${this.position - 1}`;
        } else if (key === 's') {
            this.toggleSave(story);
        } else if (key === 'n') {
            this.addToNote(story);
        } else if (key === 'o') {
            window.open(story.url, '_blank', 'noopener');
        } else {
            return false;
        }
        return true;
    }
};

window.Today = Today;
