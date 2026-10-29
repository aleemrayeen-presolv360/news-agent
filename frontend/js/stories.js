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
            summary: this.cleanSummary(Util.decode(item.one_liner || ''), headline),
            whyItMatters: Util.decode(item.market_impact || ''),
            topics: item.topics || [],
            entities: item.entities || [],
            clusterId: item.cluster_id || null,
            others: (item.coverage || []).map(c => ({ source: Util.decode(c.source), headline: Util.decode(c.headline), url: c.url })),
            publishedAt: item.published_at || null,
            score: Number(item.score) || 0,
            domain: CONFIG.DOMAINS[item.domain] ? item.domain : null
        };
        // Distinct outlets that covered the event; older data.js files only have the count
        const outlets = new Set([story.source, ...story.others.map(o => o.source)]);
        story.coverage = story.others.length ? outlets.size : (Number(item.cluster_count) || 1);
        story.label = this.labelFor(story.score);
        story.category = this.categoryFor(story, item.category);
        story.area = story.domain || this.guessDomain(story);
        // Older data.js files have no "trending"; wide coverage is the same signal
        story.trending = Boolean(item.trending) || story.coverage >= 3;
        story.searchText = Util.normalize([headline, story.source, story.summary, CONFIG.DOMAINS[story.domain] || '', ...story.topics, ...story.entities].join(' '));
        return story;
    },

    /**
     * The feed's summary, or '' when it adds nothing: Hacker News sends link metadata
     * ("Article URL: ... Comments: 94") and Google News repeats the headline.
     * Newsletter lines ("sign up here") are dropped, and since the pipeline cuts summaries
     * at a fixed length, the text ends at the last full sentence, or at a whole word with "…".
     */
    cleanSummary(summary, headline) {
        if (/^(Article URL|Comments URL):/i.test(summary)) return '';
        const a = Util.normalize(summary), b = Util.normalize(headline);
        if (a && b && a.startsWith(b) && a.length < b.length + 40) return '';
        const sentences = summary.match(/.+?(?:[.!?]+["'”’)\]]*(?=\s|$)\s*|$)/g) || [];
        const kept = sentences.filter(s => !/originally appeared|appeared first on|sign up|subscribe to|in your inbox|click here|read more/i.test(s));
        const text = kept.join('').trim();
        if (!text || /[.!?]["'”’)\]]*$/.test(text)) return text;
        const whole = kept.slice(0, -1).join('').trim();
        if (whole.length > 20) return whole;
        return text.replace(/\s+\S*$/, '').replace(/[\s,;:–-]+$/, '') + '…';
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

    /** Other stories on the site about the same event (same cluster). */
    siblings(story) {
        return story.clusterId ? this.all().filter(s => s.clusterId === story.clusterId && s.id !== story.id) : [];
    },

    /** Reading one article about an event counts as reading the event. */
    markRead(story, read = true) {
        UserState.setRead(story.id, read);
        for (const s of this.siblings(story)) UserState.setRead(s.id, read);
    },

    /**
     * One entry per event: the first story of each cluster in `list` stands for the others, so
     * keep `list` in the order you want leads picked (most important, newest...).
     */
    grouped(list) {
        const seen = new Set();
        return list.filter(s => !s.clusterId || (!seen.has(s.clusterId) && seen.add(s.clusterId)));
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
     * Competitors are found by name. Otherwise the pipeline's category is used; stories scored
     * before the pipeline sent one are guessed from the text.
     * Whole words only, so "impact" doesn't count as "act" and "record" doesn't count as "CORD".
     */
    categoryFor(story, fromPipeline) {
        const text = `${story.headline} ${story.topics.join(' ')} ${story.entities.join(' ')}`;
        const word = name => new RegExp(`\\b${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i');
        if (CONFIG.COMPETITORS.some(name => word(name).test(text))) return 'competitors';
        if (CONFIG.CATEGORIES[fromPipeline]) return fromPipeline;
        if (/\b(law|legal|court|courts|regulation|regulator|compliance|act|policy|gdpr|litigation|arbitration|mediation|judgment|tribunal)\b/i.test(text)) return 'legal';
        if (/\b(market|markets|stock|stocks|funding|valuation|ipo|investment|billion|million|revenue)\b/i.test(text)) return 'market';
        return 'tech';
    },

    /**
     * A domain for stories scored before the pipeline sent one (before 21 Oct 2026). Those came
     * from AI-only scoring, so AI is the fallback for tech.
     */
    guessDomain(story) {
        if (story.category === 'legal') return 'legal_india';
        if (story.category === 'market' || story.category === 'competitors') return 'business';
        const text = `${story.headline} ${story.topics.join(' ')}`;
        const rules = [
            ['security', /\b(security|vulnerabilit\w*|breach|hack\w*|malware|ransomware|exploit|cve)\b/i],
            ['chips', /\b(chips?|gpus?|semiconductor\w*|tsmc|nvidia|wafer|foundry)\b/i],
            ['mobility', /\b(ev|evs|electric vehicles?|tesla|robotaxi|self-driving|autonomous driving|cars?)\b/i],
            ['space', /\b(space|nasa|spacex|rocket|satellite|orbit|isro|lunar|mars)\b/i],
            ['health', /\b(health|medical|drug|biotech|clinical|cancer|protein|genom\w*)\b/i],
            ['energy', /\b(energy|climate|battery|batteries|solar|nuclear|grid|carbon)\b/i],
            ['robotics', /\b(robots?|robotics|humanoid)\b/i]
        ];
        return (rules.find(([, re]) => re.test(text)) || ['ai'])[0];
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

    /** Pipeline sources added in the last 2 days: [{ name, added_at }]. */
    newSources() {
        return window.digestData?.new_sources || [];
    },

    generatedAt() {
        return window.digestData?.generated_at || null;
    },

    // ---------- Shared markup ----------

    labelHtml(story) {
        return `<span class="label label-${story.label}">${this.labelText(story.label)}</span>`;
    },

    trendHtml(story) {
        return story.trending ? '<span class="trend-tag">Trending</span>' : '';
    },

    /** The finer domain when there is one ("EVs and mobility"), else the category. */
    categoryName(story) {
        return story.category !== 'competitors' && story.domain
            ? CONFIG.DOMAINS[story.domain]
            : CONFIG.CATEGORIES[story.category];
    },

    categoryHtml(story) {
        return `<span class="tag">${Util.esc(this.categoryName(story))}</span>`;
    },

    coverageText(story) {
        return story.coverage > 1 ? `Covered by ${story.coverage} sources` : '';
    },

    /** "+7 sources" after the outlet's name, or '' when only one outlet has it. */
    moreSourcesText(story) {
        const n = story.coverage - 1;
        return n > 0 ? `+${n} ${n === 1 ? 'source' : 'sources'}` : '';
    },

    /** Every outlet that covered the story, lead outlet first, each name once. */
    outlets(story) {
        const seen = new Set();
        return [{ source: story.source, headline: story.headline, url: story.url }, ...story.others]
            .filter(o => !seen.has(o.source) && seen.add(o.source));
    },

    /** Today's card: "Covered by 8 sources" and the outlets as tags. */
    coverageTagsHtml(story) {
        const outlets = this.outlets(story);
        const shown = outlets.slice(0, 4);
        const rest = Math.max(story.coverage, outlets.length) - shown.length;
        const title = story.coverage > 1 ? this.coverageText(story) : 'Reported by';
        return `
            <section class="coverage" aria-label="Coverage">
                <strong>${title}</strong>
                ${shown.map(o => `<a class="tag" href="${Util.esc(o.url)}" target="_blank" rel="noopener">${Util.esc(o.source)}</a>`).join('')}
                ${rest > 0 ? `<span class="tag">+${rest}</span>` : ''}
            </section>`;
    },

    /** The reading pane: every outlet with its own headline, the long tail folded into "+N more". */
    coverageTableHtml(story) {
        const outlets = this.outlets(story);
        const rows = outlets.length > 5 ? outlets.slice(0, 4) : outlets;
        const folded = outlets.slice(rows.length);
        const rest = Math.max(story.coverage, outlets.length) - rows.length;
        const row = o => `<li><b>${Util.esc(o.source)}</b><a href="${Util.esc(o.url)}" target="_blank" rel="noopener">${Util.esc(o.headline)}</a></li>`;
        return `
            <section class="story-block" aria-label="Coverage">
                <h3>Coverage · ${story.coverage > 1 ? `${story.coverage} sources` : '1 source'}</h3>
                <ul class="cov-list">
                    ${rows.map(row).join('')}
                    ${rest > 0 ? `<li class="cov-more"><b>+${rest} more</b><span>${Util.esc(folded.map(o => o.source).join(', ') || 'Other outlets')}</span></li>` : ''}
                </ul>
            </section>`;
    },

    /**
     * The story card, in Today's briefing ('brief') or the All stories reading pane ('pane').
     * Same order in both: what happened, why it matters, who covered it.
     * `primary` (Next story) sits at the end of the action row, `actions` before it.
     */
    articleHtml(story, { headingTag = 'h2', variant = 'pane', primary = '', actions = '' } = {}) {
        const saved = UserState.isSaved(story.id);
        const brief = variant === 'brief';
        const when = story.publishedAt
            ? (brief ? `${Util.shortDate(story.publishedAt)} · ${Util.clock(story.publishedAt)}` : Util.longDate(story.publishedAt))
            : '';
        const meta = brief
            ? `${this.labelHtml(story)}${this.categoryHtml(story)}${this.trendHtml(story)}${when ? `<span class="meta">${when}</span>` : ''}`
            : `${this.labelHtml(story)}${this.trendHtml(story)}<span class="meta">${Util.esc(this.categoryName(story))}${when ? ` · ${when}` : ''}</span>`;
        const why = story.whyItMatters && !/^none\.?$/i.test(story.whyItMatters) ? story.whyItMatters : '';

        return `
            <article class="story story-${variant}" data-story="${Util.esc(story.id)}">
                <div class="story-meta">${meta}</div>
                <${headingTag} class="story-title">${Util.esc(story.headline)}</${headingTag}>
                ${story.summary ? `<section class="story-block"><h3>${brief ? 'What happened' : 'The news'}</h3><p class="story-lead">${Util.esc(story.summary)}</p></section>` : ''}
                ${why ? `<section class="story-block"><h3>Why it matters</h3><p class="story-lead">${Util.esc(why)}</p></section>` : ''}
                ${brief ? this.coverageTagsHtml(story) : this.coverageTableHtml(story)}
                <div class="story-actions">
                    <button type="button" class="btn" data-action="save" aria-pressed="${saved}"><kbd>S</kbd><span>${saved ? 'Saved' : 'Save'}</span></button>
                    <button type="button" class="btn" data-action="note"><kbd>N</kbd><span class="wide-only">Add to note</span><span class="phone-only">Note</span></button>
                    <a class="btn btn-read" href="${Util.esc(story.url)}" target="_blank" rel="noopener"><kbd>O</kbd>Read at ${Util.esc(story.source || Util.hostname(story.url) || 'the source')}</a>
                    ${actions}
                    ${primary}
                </div>
            </article>`;
    }
};

window.Stories = Stories;
