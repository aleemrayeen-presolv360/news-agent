/*
   Per-user state kept on this laptop: read stories, saved stories, hidden sources,
   preferences and today's list. Keys include the user id so people sharing a laptop
   don't see each other's state.
*/

const UserState = {
    userId: 'demo',

    setUser(id) {
        this.userId = id || 'demo';
        this._migrateBookmarks();
    },

    _key(name) {
        return `${name}_${this.userId}`;
    },

    // ---------- Read ----------

    isRead(id) {
        return Util.load(this._key('read'), []).includes(id);
    },

    setRead(id, read = true) {
        const list = Util.load(this._key('read'), []).filter(x => x !== id);
        if (read) list.push(id);
        Util.save(this._key('read'), list.slice(-2000));
    },

    // ---------- Saved ----------
    // A full copy of the story is kept, so saved stories survive after they leave the weekly data file.

    saved() {
        return Util.load(this._key('saved'), []);
    },

    isSaved(id) {
        return this.saved().some(entry => entry.id === id);
    },

    /** Toggle saved. Returns the new state. */
    toggleSaved(story) {
        const list = this.saved();
        const index = list.findIndex(entry => entry.id === story.id);
        if (index > -1) {
            list.splice(index, 1);
        } else {
            const { searchText, ...copy } = story;
            list.unshift({ id: story.id, savedAt: new Date().toISOString(), story: copy });
        }
        Util.save(this._key('saved'), list);
        App.updateCounts();
        return index === -1;
    },

    /** Saved stories as story objects, newest save first. */
    savedStories() {
        return this.saved().map(entry => {
            const live = Stories.byId(entry.id);
            const story = live || { ...entry.story, searchText: Util.normalize(`${entry.story.headline} ${entry.story.source}`) };
            return { ...story, savedAt: entry.savedAt };
        });
    },

    /** The old app stored bookmarks as a plain list of URLs under "bookmarks". Bring them across once. */
    _migrateBookmarks() {
        const old = Util.load('bookmarks', null);
        if (!Array.isArray(old) || !old.length || Util.load(this._key('saved'), null)) return;
        const now = new Date().toISOString();
        const migrated = old
            .map(url => Stories.byId(url))
            .filter(Boolean)
            .map(story => {
                const { searchText, ...copy } = story;
                return { id: story.id, savedAt: now, story: copy };
            });
        Util.save(this._key('saved'), migrated);
    },

    // ---------- Hidden sources (same key the old Settings screen used) ----------

    hiddenSources() {
        return Util.load(`disabled_sources_${this.userId}`, []);
    },

    setSourceHidden(id, hidden) {
        const list = this.hiddenSources().filter(x => x !== String(id));
        if (hidden) list.push(String(id));
        Util.save(`disabled_sources_${this.userId}`, list);
    },

    // ---------- Preferences ----------

    prefs() {
        return {
            dailyCount: CONFIG.DAILY_COUNT_DEFAULT,
            includeLegal: true,
            ...Util.load(this._key('prefs'), {})
        };
    },

    setPref(name, value) {
        Util.save(this._key('prefs'), { ...this.prefs(), [name]: value });
    },

    /** Domain ids the user follows, or null for "all of them" (the default). */
    followedDomains() {
        const list = this.prefs().domains;
        if (!Array.isArray(list)) return null;
        const known = list.filter(id => CONFIG.DOMAINS[id]);
        return known.length && known.length < Object.keys(CONFIG.DOMAINS).length ? known : null;
    },

    /** 'light' | 'dark' | 'system'. Stored as a plain string under "theme", as the old app did. */
    theme() {
        try {
            const value = localStorage.getItem('theme');
            return value === 'light' || value === 'dark' ? value : 'system';
        } catch {
            return 'system';
        }
    },

    setTheme(choice) {
        try {
            if (choice === 'system') localStorage.removeItem('theme');
            else localStorage.setItem('theme', choice);
        } catch { /* storage blocked */ }
        if (choice === 'system') delete document.documentElement.dataset.theme;
        else document.documentElement.dataset.theme = choice;
    },

    // ---------- Today's list ----------

    todaySession() {
        return Util.load(this._key('today'), null);
    },

    saveTodaySession(session) {
        Util.save(this._key('today'), session);
    }
};

window.UserState = UserState;
