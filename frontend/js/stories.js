/*
   Stories: reads window.digestData (written by agent/publish_static.py) and gives every
   screen the same view of a story: id, label, category, date and search text.
*/

const Stories = {
    _all: null,

    /** All stories, highest score first. Each story's id is its article URL. */
    all() {
        if (this._all) return this._all;
        const data = window.digestData || {};
        const raw = [...(data.breaking || []), ...(data.major || []), ...(data.notable || [])];

        const seen = new Set();
        this._all = raw
            .filter(item => item.url && !seen.has(item.url) && seen.add(item.url))
            .map(item => this._shape(item))
            .sort((a, b) => b.score - a.score);
        return this._all;
    },

    _shape(item) {
        const headline = Util.decode(item.headline);
        const story = {
            id: item.url,
            url: item.url,
            headline,
            source: Util.decode(item.source),
            summary: Util.decode(item.one_liner || ''),
            whyItMatters: Util.decode(item.market_impact || ''),
            topics: item.topics || [],
            entities: item.entities || [],
            coverage: Number(item.cluster_count) || 1,
            publishedAt: item.published_at || null,
            score: Number(item.score) || 0
        };
        story.label = this.labelFor(story.score);
        story.category = this.categoryFor(story);
        story.searchText = Util.normalize([headline, story.source, story.summary, ...story.topics, ...story.entities].join(' '));
        return story;
    },

    /** Names of sources hidden for this user (personally or for everyone). Set by Settings.loadSources(). */
    hiddenNames: [],

    /** Stories minus the ones from hidden sources. */
    visible() {
        if (!this.hiddenNames.length) return this.all();
        return this.all().filter(s => !this.hiddenNames.some(name => this.sourceMatches(s.source, name)));
    },

    byId(id) {
        return this.all().find(s => s.id === id) || null;
    },

    /** 'breaking' | 'major' | 'notable'. Readers see these words, never the score. */
    labelFor(score) {
        if (score >= CONFIG.SCORE_BREAKING) return 'breaking';
        if (score >= CONFIG.SCORE_MAJOR) return 'major';
        return 'notable';
    },

    labelText(label) {
        return { breaking: 'Breaking', major: 'Major', notable: 'Notable' }[label] || '';
    },

    /**
     * The pipeline doesn't send a category yet, so it's inferred from the text.
     * Whole words only, so "impact" doesn't count as "act" and "record" doesn't count as "CORD".
     */
    categoryFor(story) {
        const text = `${story.headline} ${story.topics.join(' ')} ${story.entities.join(' ')}`;
        const word = name => new RegExp(`\\b${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i');
        if (CONFIG.COMPETITORS.some(name => word(name).test(text))) return 'competitors';
        if (/\b(law|legal|court|courts|regulation|regulator|compliance|act|policy|gdpr|litigation|arbitration|mediation|judgment|tribunal)\b/i.test(text)) return 'legal';
        if (/\b(market|markets|stock|stocks|funding|valuation|ipo|investment|billion|million|revenue)\b/i.test(text)) return 'market';
        return 'tech';
    },

    /**
     * Does a story's source belong to a source-list entry? Names differ slightly between the
     * pipeline and the source list ("OpenAI" vs "OpenAI Blog"), so a shared prefix counts.
     */
    sourceMatches(storySource, sourceName) {
        const a = Util.normalize(storySource);
        const b = Util.normalize(sourceName);
        if (!a || !b) return false;
        if (a === b) return true;
        return Math.min(a.length, b.length) >= 5 && (a.startsWith(b) || b.startsWith(a));
    },

    fromSource(sourceName) {
        return this.all().filter(s => this.sourceMatches(s.source, sourceName));
    },

    /** Forgiving search: punctuation and spacing are ignored, every word must match. */
    search(query, list = this.all()) {
        const words = String(query).toLowerCase().split(/\s+/).map(Util.normalize).filter(Boolean);
        if (!words.length) return list;
        const joined = Util.normalize(query);
        return list.filter(s => s.searchText.includes(joined) || words.every(w => s.searchText.includes(w)));
    },

    /** Stories published between two YYYY-MM-DD days (inclusive, IST). Stories without a date always pass. */
    inRange(list, from, to) {
        if (!from && !to) return list;
        return list.filter(s => {
            if (!s.publishedAt) return true;
            const day = Util.dayKey(new Date(s.publishedAt));
            return (!from || day >= from) && (!to || day <= to);
        });
    },

    weekLabel() {
        return window.digestData?.week_label || '';
    },

    stats() {
        return window.digestData?.stats || {};
    },

    generatedAt() {
        return window.digestData?.generated_at || null;
    },

    // ---------- Shared markup ----------

    labelHtml(story) {
        return `<span class="label label-${story.label}">${this.labelText(story.label)}</span>`;
    },

    categoryHtml(story) {
        return `<span class="cat-dot cat-${story.category}" aria-hidden="true"></span>${Util.esc(CONFIG.CATEGORIES[story.category])}`;
    },

    coverageText(story) {
        return story.coverage > 1 ? `Covered by ${story.coverage} sources` : '';
    },

    /**
     * The full story view, used by Today and the reader.
     * `primary` goes first in the action row (Next story), `actions` goes last.
     */
    articleHtml(story, { headingTag = 'h2', primary = '', actions = '' } = {}) {
        const saved = UserState.isSaved(story.id);
        const host = Util.hostname(story.url) || 'the source';
        const facts = [];
        if (story.entities.length) {
            facts.push(`<dt>People and companies</dt><dd>${story.entities.slice(0, 8).map(e => `<span class="chip">${Util.esc(e)}</span>`).join('')}</dd>`);
        }
        if (story.topics.length) {
            facts.push(`<dt>Topics</dt><dd>${story.topics.slice(0, 6).map(t => `<span class="chip">${Util.esc(t)}</span>`).join('')}</dd>`);
        }

        return `
            <article class="story" data-story="${Util.esc(story.id)}">
                <div class="story-main">
                    <div class="story-meta">${this.labelHtml(story)}<span>${this.categoryHtml(story)}</span></div>
                    <${headingTag} class="story-title">${Util.esc(story.headline)}</${headingTag}>
                    <p class="story-by"><strong>${Util.esc(story.source)}</strong>${story.publishedAt ? `, ${Util.longDate(story.publishedAt)}` : ''}.${story.coverage > 1 ? ` ${this.coverageText(story)}.` : ''}</p>
                    ${story.summary ? `<p class="story-lead">${Util.esc(story.summary)}</p>` : ''}
                    ${facts.length ? `<dl class="story-facts">${facts.join('')}</dl>` : ''}
                    <div class="story-actions">
                        ${primary}
                        <a class="btn" href="${Util.esc(story.url)}" target="_blank" rel="noopener"><svg class="icon"><use href="#i-ext"/></svg>Read on ${Util.esc(host)}</a>
                        <button type="button" class="btn" data-action="save" aria-pressed="${saved}"><svg class="icon"><use href="#i-save"/></svg><span>${saved ? 'Saved' : 'Save'}</span><kbd>S</kbd></button>
                        <button type="button" class="btn" data-action="note"><svg class="icon"><use href="#i-note"/></svg>Add to note<kbd>N</kbd></button>
                        ${actions}
                    </div>
                </div>
                ${story.whyItMatters ? `
                <aside class="story-margin" aria-label="Why it matters">
                    <div><h3>Why it matters</h3><p>${Util.esc(story.whyItMatters)}</p></div>
                </aside>` : ''}
            </article>`;
    }
};

window.Stories = Stories;
