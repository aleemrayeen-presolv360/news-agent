/*
   Search palette (Ctrl K or /): stories, notes and places in one box.
   Matching ignores spaces and punctuation, so "gpt6", "GPT-6" and "open ai" all work.
*/

const Palette = {
    dialog: null,
    input: null,
    results: [],
    active: 0,

    PLACES: [
        { name: 'Today', hash: '#/today' },
        { name: 'All stories', hash: '#/stories' },
        { name: 'Breaking stories', hash: '#/stories?folder=breaking' },
        { name: 'Saved', hash: '#/saved' },
        { name: 'Notes', hash: '#/notes' },
        { name: 'New note', hash: '#/notes/new' },
        { name: 'Preferences', hash: '#/settings/preferences' },
        { name: 'My sources', hash: '#/settings/sources' }
    ],

    init() {
        this.dialog = document.getElementById('palette');
        this.input = document.getElementById('palette-input');
        this.list = document.getElementById('palette-results');

        document.getElementById('open-palette').addEventListener('click', () => this.open());
        this.input.addEventListener('input', () => this.update());
        this.input.addEventListener('keydown', e => this.onKey(e));
        this.list.addEventListener('click', e => {
            const item = e.target.closest('[data-index]');
            if (item) this.choose(Number(item.dataset.index));
        });
        // Clicking the backdrop closes the palette
        this.dialog.addEventListener('click', e => { if (e.target === this.dialog) this.dialog.close(); });
    },

    open() {
        if (this.dialog.open) return;
        this.input.value = '';
        this.update();
        this.dialog.showModal();
        this.input.focus();
    },

    update() {
        const q = this.input.value.trim();
        const nq = Util.normalize(q);
        const groups = [];

        if (q) {
            const stories = Stories.search(q).slice(0, 6).map(s => ({
                group: 'Stories', text: s.headline, meta: `${s.source}${s.publishedAt ? `, ${Util.shortDate(s.publishedAt)}` : ''}`,
                hash: `#/stories?story=${encodeURIComponent(s.id)}`
            }));
            if (stories.length) {
                stories.push({ group: 'Stories', text: `Show all stories matching “${q}”`, meta: '', hash: `#/stories?q=${encodeURIComponent(q)}` });
            }
            groups.push(...stories);

            const notes = (Notes.notes || [])
                .filter(n => Util.normalize(`${n.title} ${Notes.plainText(n.content)}`).includes(nq))
                .slice(0, 3)
                .map(n => ({ group: 'Notes', text: n.title || 'Untitled note', meta: Util.relative(n.updated_at), hash: `#/notes/${encodeURIComponent(n.id)}` }));
            groups.push(...notes);
        }

        const places = this.PLACES
            .filter(p => !nq || Util.normalize(p.name).includes(nq))
            .map(p => ({ group: 'Go to', text: p.name, meta: '', hash: p.hash }));
        groups.push(...(q ? places.slice(0, 3) : places));

        this.results = groups;
        this.active = 0;
        this.render();
    },

    render() {
        if (!this.results.length) {
            this.list.innerHTML = `<p class="palette-empty">No matches. Try fewer words, or a company or person's name.</p>`;
            this.input.setAttribute('aria-activedescendant', '');
            return;
        }
        let lastGroup = '';
        this.list.innerHTML = this.results.map((r, i) => {
            const head = r.group !== lastGroup ? `<p class="palette-group" role="presentation">${r.group}</p>` : '';
            lastGroup = r.group;
            return `${head}<div class="palette-item" role="option" id="palette-opt-${i}" data-index="${i}" aria-selected="${i === this.active}">
                <span>${Util.esc(r.text)}</span>${r.meta ? `<small>${Util.esc(r.meta)}</small>` : ''}</div>`;
        }).join('');
        this.input.setAttribute('aria-activedescendant', `palette-opt-${this.active}`);
    },

    move(delta) {
        if (!this.results.length) return;
        this.active = (this.active + delta + this.results.length) % this.results.length;
        this.list.querySelectorAll('.palette-item').forEach((el, i) => el.setAttribute('aria-selected', String(i === this.active)));
        this.input.setAttribute('aria-activedescendant', `palette-opt-${this.active}`);
        document.getElementById(`palette-opt-${this.active}`)?.scrollIntoView({ block: 'nearest' });
    },

    choose(index) {
        const result = this.results[index];
        if (!result) return;
        this.dialog.close();
        location.hash = result.hash;
    },

    onKey(e) {
        if (e.key === 'ArrowDown') { e.preventDefault(); this.move(1); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); this.move(-1); }
        else if (e.key === 'Enter') { e.preventDefault(); this.choose(this.active); }
    }
};

window.Palette = Palette;
