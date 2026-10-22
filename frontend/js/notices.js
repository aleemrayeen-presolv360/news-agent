/*
   Notices: the website is News Intel's only notifier (no Telegram, no email).
   A bar under the top bar shows, most urgent first:
     - Breaking stories from the last few days that you haven't read (everyone)
     - the news being out of date because the daily update didn't run (everyone)
     - pipeline problems from data.js "health" (admins), with details in Settings → Sources
   The tab title also counts unread Breaking stories, so it shows while the tab is in the background.
*/

const Notices = {
    BREAKING_DAYS: 3,     // Breaking stories older than this no longer get a notice
    STALE_HOURS: 30,      // data.js is rewritten every morning; older than this means the update failed

    el: null,

    init() {
        this.el = document.getElementById('notice-bar');
        this.el.addEventListener('click', e => {
            const btn = e.target.closest('[data-dismiss]');
            if (!btn) return;
            UserState.dismissNotice(btn.dataset.dismiss);
            this.render();
        });
    },

    /** Unread, undismissed Breaking stories from the last BREAKING_DAYS, newest first. */
    unreadBreaking() {
        const since = Date.now() - this.BREAKING_DAYS * 86400000;
        return Stories.visible()
            .filter(s => s.label === 'breaking' && s.publishedAt && new Date(s.publishedAt).getTime() >= since)
            .filter(s => !UserState.isRead(s.id) && !UserState.isNoticeDismissed(s.id))
            .sort((a, b) => new Date(b.publishedAt) - new Date(a.publishedAt));
    },

    /** Hours since data.js was generated, or null when unknown. */
    dataAgeHours() {
        const at = Stories.generatedAt();
        if (!at) return null;
        return (Date.now() - new Date(at).getTime()) / 3600000;
    },

    health() {
        return window.digestData?.health || null;
    },

    storyLink(story) {
        return `#/stories?${new URLSearchParams({ folder: 'breaking', story: story.id })}`;
    },

    render() {
        if (!this.el) return;
        const items = [];

        const breaking = this.unreadBreaking();
        if (breaking.length) {
            const top = breaking[0];
            const more = breaking.length - 1;
            items.push(`
                <div class="notice notice-breaking" role="status">
                    <span class="label label-breaking">Breaking</span>
                    <a class="notice-text" href="${this.storyLink(top)}">${Util.esc(top.headline)}</a>
                    ${more ? `<a class="notice-more" href="#/stories?folder=breaking">${more} more</a>` : ''}
                    <button type="button" class="notice-close" data-dismiss="${Util.esc(top.id)}" aria-label="Dismiss this notice">✕</button>
                </div>`);
        }

        const age = this.dataAgeHours();
        if (age !== null && age > this.STALE_HOURS) {
            items.push(`
                <div class="notice" role="status">
                    <p class="notice-text"><strong>News is out of date.</strong> The last update was ${Util.esc(Util.relative(Stories.generatedAt()))}, so newer stories are missing.${Auth.isAdmin() ? ' The daily workflow in GitHub Actions probably failed or didn\'t run.' : ''}</p>
                </div>`);
        }

        const warnings = this.health()?.warnings || [];
        if (Auth.isAdmin() && warnings.length) {
            items.push(`
                <div class="notice" role="status">
                    <p class="notice-text"><strong>The news pipeline needs a look.</strong> ${warnings.length === 1 ? Util.esc(warnings[0]) : `${warnings.length} issues.`}</p>
                    <a class="notice-more" href="#/settings/sources">See details</a>
                </div>`);
        }

        this.el.innerHTML = items.join('');
        this.el.hidden = !items.length;
        this.updateTitle(breaking.length);
    },

    updateTitle(count) {
        const base = document.title.replace(/^\(\d+\) /, '');
        document.title = count ? `(${count}) ${base}` : base;
    },

    /** Admin panel for Settings → Sources: what the pipeline last did and what's wrong. */
    healthHtml() {
        const h = this.health();
        if (!h) return '';
        const when = value => value ? Util.esc(Util.relative(value)) : 'never';
        const score = h.last_score;
        const list = (title, names) => names?.length
            ? `<p><strong>${title}:</strong> ${names.map(n => Util.esc(n)).join(', ')}</p>` : '';
        return `
            <section class="health" aria-labelledby="health-title">
                <h2 id="health-title">Pipeline health</h2>
                <div class="summary">
                    <div><strong>${when(Stories.generatedAt())}</strong>website updated</div>
                    <div><strong>${when(h.last_ingest_at)}</strong>feeds fetched (${h.ingest_runs_24h} times in 24h)</div>
                    ${score ? `<div><strong>${when(score.at)}</strong>last scoring: ${score.scored} scored, ${score.waiting ?? '?'} waiting</div>` : ''}
                    ${score && score.groq_remaining !== null ? `<div><strong>${score.groq_remaining}</strong>Groq calls were left that day</div>` : ''}
                </div>
                ${h.warnings.length
                    ? `<ul class="health-warnings">${h.warnings.map(w => `<li>${Util.esc(w)}</li>`).join('')}</ul>`
                    : '<p class="muted">No problems found in the last run.</p>'}
                ${list('Feeds failing', h.failing_sources)}
                ${list('Feeds with nothing new for 14 days', h.quiet_sources)}
            </section>`;
    }
};

window.Notices = Notices;
