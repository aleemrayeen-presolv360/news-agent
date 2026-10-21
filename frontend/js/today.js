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
     * aren't enough); keep one Legal India story if the user asked for it.
     */
    buildIds() {
        const prefs = UserState.prefs();
        const count = Number(prefs.dailyCount) || CONFIG.DAILY_COUNT_DEFAULT;
        const candidates = [...Stories.visible()].sort((a, b) =>
            (UserState.isRead(a.id) - UserState.isRead(b.id)) ||
            (this.isRecent(b) - this.isRecent(a)) || (b.score - a.score)
        );

        const picks = candidates.slice(0, count);
        if (prefs.includeLegal && picks.length && !picks.some(s => s.category === 'legal')) {
            const legal = candidates.find(s => s.category === 'legal' && !picks.includes(s));
            if (legal) picks[picks.length - 1] = legal;
        }
        return picks.sort((a, b) => b.score - a.score).map(s => s.id);
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
        if (step === 'done' || (!step && this.session.finished)) return this.renderDone(stories);

        const n = parseInt(step, 10);
        if (n >= 1 && n <= stories.length) return this.renderStory(stories, n);
        return this.renderList(stories);
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

    renderList(stories) {
        this.position = null;
        const nextIndex = stories.findIndex(s => !this.session.heard.includes(s.id));
        const started = this.session.heard.length > 0;
        const startAt = nextIndex === -1 ? 1 : nextIndex + 1;
        const stats = Stories.stats();
        const recent = Stories.visible().filter(s => this.isRecent(s));
        const breaking = recent.filter(s => s.label === 'breaking').length;
        const readCount = recent.filter(s => UserState.isRead(s.id)).length;
        const prefs = UserState.prefs();

        this.el.innerHTML = `
            <div class="today">
                <div>
                    <h1>${stories.length === 1 ? '1 story needs you today' : `${stories.length} stories need you today`}</h1>
                    <p class="today-sub">${Util.esc(Util.weekdayDate())}. Picked from the last ${CONFIG.TODAY_DAYS} days.</p>
                    <div class="today-start">
                        <a class="btn btn-primary btn-big" href="#/today/${startAt}" id="today-start">
                            ${started ? `Continue with story ${startAt}` : 'Start with story 1'}<kbd>Enter</kbd>
                        </a>
                        <span class="muted">or pick any story below</span>
                    </div>
                    <ol class="today-list">
                        ${stories.map((s, i) => `
                            <li class="${this.session.heard.includes(s.id) ? 'is-read' : ''}">
                                <a href="#/today/${i + 1}">
                                    <span class="today-headline">${Util.esc(s.headline)}</span>
                                    <span class="story-meta">${Stories.labelHtml(s)}<span>${Util.esc(s.source)}</span><span>${Stories.categoryHtml(s)}</span>${s.coverage > 1 ? `<span>${Stories.coverageText(s)}</span>` : ''}</span>
                                </a>
                            </li>`).join('')}
                    </ol>
                </div>
                <div class="side-stack">
                    <section class="side-box">
                        <h2>Last ${CONFIG.TODAY_DAYS} days</h2>
                        <p>${recent.length} stories worth reading, ${breaking} of them breaking. You've read ${readCount}.</p>
                    </section>
                    <section class="side-box">
                        <h2>How this list is chosen</h2>
                        <p>The highest-ranked stories you haven't read yet, picked from ${stats.items_ingested ? `${stats.items_ingested} stories scanned` : 'everything scanned'} this week.${prefs.includeLegal ? ' At least one Legal India story is included when there is one.' : ''}</p>
                        <a href="#/settings/preferences">Change in preferences</a>
                    </section>
                </div>
            </div>`;
    },

    renderStory(stories, n) {
        this.position = n;
        const story = stories[n - 1];
        const isLast = n === stories.length;

        if (!this.session.heard.includes(story.id)) {
            this.session.heard.push(story.id);
            UserState.saveTodaySession(this.session);
        }
        UserState.setRead(story.id);

        const nextLabel = isLast ? 'Finish' : 'Next story';
        const primary = `<a class="btn btn-primary btn-big" href="#/today/${isLast ? 'done' : n + 1}">${nextLabel}<kbd>→</kbd></a>`;
        const actions = n > 1 ? `<a class="btn" href="#/today/${n - 1}"><svg class="icon"><use href="#i-prev"/></svg>Previous<kbd>←</kbd></a>` : '';

        this.el.innerHTML = `
            <div class="hearing">
                <nav class="queue" aria-label="Today's list">
                    <h2>Today, story ${n} of ${stories.length}</h2>
                    <div class="progress" aria-hidden="true">${stories.map((_, i) => `<span class="${i < n ? 'is-done' : ''}"></span>`).join('')}</div>
                    <ol>
                        ${stories.map((s, i) => {
                            const heard = this.session.heard.includes(s.id) && i + 1 !== n;
                            return `<li class="${heard ? 'is-done' : ''}" ${i + 1 === n ? 'aria-current="step"' : ''}>
                                <a href="#/today/${i + 1}"><span class="mark">${heard ? '<svg class="icon"><use href="#i-check"/></svg>' : ''}</span>${Util.esc(s.headline)}</a>
                            </li>`;
                        }).join('')}
                    </ol>
                </nav>
                ${Stories.articleHtml(story, { headingTag: 'h1', primary, actions })}
            </div>`;
    },

    renderDone(stories) {
        this.position = null;
        if (!this.session.finished) {
            this.session.finished = true;
            UserState.saveTodaySession(this.session);
        }
        const savedToday = stories.filter(s => UserState.isSaved(s.id));

        this.el.innerHTML = `
            <div class="done">
                <div class="done-col">
                    <div class="stamp"><strong>Up to date</strong><span>${Util.esc(Util.longDate(new Date()))}</span></div>
                    <h1 class="sr-only">You're up to date</h1>
                    <p class="done-text">That's everything that needs you today. Tomorrow's list is ready from midnight, India time.</p>
                    <div class="tally">
                        <div><strong>${this.session.heard.length}</strong><span>read</span></div>
                        <div><strong>${savedToday.length}</strong><span>saved</span></div>
                        <div><strong>${this.session.noted.length}</strong><span>added to notes</span></div>
                    </div>
                    <div class="done-actions">
                        <a class="btn btn-primary" href="#/notes">Open my notes</a>
                        <a class="btn" href="#/stories">Browse all ${Stories.visible().length} stories</a>
                        <a class="btn" href="#/today/1">Go through today's list again</a>
                    </div>
                </div>
                ${savedToday.length ? `
                <section class="side-box">
                    <h2>You saved today</h2>
                    <ul class="plain-list">${savedToday.map(s => `<li><a href="#/saved?story=${encodeURIComponent(s.id)}">${Util.esc(s.headline)}</a></li>`).join('')}</ul>
                </section>` : ''}
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
        if (!this.position) {
            // App only passes Enter through when focus isn't on a link or button
            if (e.key === 'Enter') {
                document.getElementById('today-start')?.click();
                return true;
            }
            return false;
        }

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
