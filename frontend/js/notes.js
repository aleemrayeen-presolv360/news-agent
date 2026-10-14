/*
   Notes: a list on the left and the open note on the right.
   Notes save themselves as you type (no Save button) and fall back to this laptop when offline.

   Routes:  #/notes          list, nothing open
            #/notes/<id>     a note
            #/notes/new      a new, unsaved note
*/

const Notes = {
    el: null,
    notes: [],
    loaded: false,
    current: null,
    query: '',
    _saveTimer: null,
    _pendingDelete: null,

    init() {
        this.el = document.getElementById('view-notes');
        this.bindAddToNote();
    },

    async load() {
        this.notes = await db.getNotes(Auth.currentUser?.id);
        this.loaded = true;
        await this.syncLocalOnly();
        App.updateCounts();
    },

    /** Notes written offline have a temporary id; push them to Supabase once we're back. */
    async syncLocalOnly() {
        const pending = this.notes.filter(n => n.localOnly);
        if (!pending.length || !db.getSupabase() || !navigator.onLine) return;
        for (const note of pending) {
            const saved = await db.saveNote({ ...note, id: null, localOnly: false }, Auth.currentUser?.id);
            if (!saved.localOnly) Object.assign(note, saved, { localOnly: false });
        }
        db.cacheNotes(this.notes);
    },

    sorted() {
        const byDate = (a, b) => new Date(b.updated_at) - new Date(a.updated_at);
        return [...this.notes].sort((a, b) => (b.pinned - a.pinned) || byDate(a, b));
    },

    /** Text of a note for previews and search. DOMParser never runs scripts or loads images. */
    plainText(html) {
        const spaced = String(html || '').replace(/<(br|\/p|\/div|\/li|\/blockquote)[^>]*>/gi, ' $&');
        const doc = new DOMParser().parseFromString(spaced, 'text/html');
        return (doc.body.textContent || '').replace(/\s+/g, ' ').trim();
    },

    // ---------- Rendering ----------

    async render(parts) {
        if (!this.loaded) await this.load();
        const id = parts[0];

        if (id === 'new') {
            if (!this.current || this.current.id) this.current = { id: null, title: '', content: '', pinned: false };
        } else if (id) {
            this.current = this.notes.find(n => String(n.id) === String(id)) || null;
        } else {
            this.current = null;
        }

        this.el.innerHTML = `
            <div class="notes ${this.current ? 'has-note' : ''}">
                <section class="note-list" aria-label="Your notes">
                    <div class="note-list-head">
                        <div class="top">
                            <h1>Notes</h1>
                            <a class="btn btn-primary btn-small" href="#/notes/new"><svg class="icon"><use href="#i-plus"/></svg>New note<kbd>C</kbd></a>
                        </div>
                        <label class="sr-only" for="notes-search">Search notes</label>
                        <input type="text" id="notes-search" autocomplete="off" placeholder="Search notes…" value="${Util.esc(this.query)}">
                    </div>
                    <div class="note-items" id="note-items"></div>
                </section>
                <section class="editor" aria-label="Note editor">${this.current ? this.editorHtml() : this.noNoteHtml()}</section>
            </div>`;

        this.renderList();
        this.el.querySelector('#notes-search').addEventListener('input', e => {
            this.query = e.target.value;
            this.renderList();
        });
        if (this.current) this.bindEditor();
    },

    renderList() {
        const container = this.el.querySelector('#note-items');
        if (!container) return;
        const q = Util.normalize(this.query);
        const notes = this.sorted().filter(n => !q || Util.normalize(`${n.title} ${this.plainText(n.content)}`).includes(q));

        if (!notes.length) {
            container.innerHTML = this.notes.length
                ? `<p class="empty-state">No notes match “${Util.esc(this.query)}”.</p>`
                : `<div class="empty-state"><h2>No notes yet</h2><p>Write your own, or press N while reading a story to start a note from it.</p></div>`;
            return;
        }

        const item = n => `
            <li><a href="#/notes/${encodeURIComponent(n.id)}" aria-current="${this.current && String(this.current.id) === String(n.id)}">
                <span class="t">${Util.esc(n.title || 'Untitled note')}</span>
                <span class="s">${Util.esc(this.plainText(n.content).slice(0, 120) || 'No text yet')}</span>
                <span class="d">${n.localOnly ? 'Saved on this laptop' : `Edited ${Util.esc(Util.relative(n.updated_at))}`}</span>
            </a></li>`;

        const pinned = notes.filter(n => n.pinned);
        const rest = notes.filter(n => !n.pinned);
        container.innerHTML = `
            ${pinned.length ? `<p class="note-group">Pinned</p><ul>${pinned.map(item).join('')}</ul>` : ''}
            ${rest.length ? `${pinned.length ? '<p class="note-group">Recent</p>' : ''}<ul>${rest.map(item).join('')}</ul>` : ''}`;
    },

    noNoteHtml() {
        return `<div class="empty-state"><h2>Pick a note, or start a new one</h2><p>Notes are private to you and save as you type.</p><a class="btn btn-primary" href="#/notes/new">New note</a></div>`;
    },

    editorHtml() {
        const n = this.current;
        return `
            <div class="editor-bar" role="toolbar" aria-label="Formatting">
                <button type="button" class="icon-btn tool" data-cmd="bold" aria-label="Bold (Ctrl B)">B</button>
                <button type="button" class="icon-btn tool" data-cmd="italic" aria-label="Italic (Ctrl I)"><i>I</i></button>
                <button type="button" class="icon-btn tool" data-cmd="underline" aria-label="Underline (Ctrl U)"><u>U</u></button>
                <span class="divider" aria-hidden="true"></span>
                <button type="button" class="icon-btn" data-cmd="insertUnorderedList" aria-label="Bulleted list"><svg class="icon"><use href="#i-list"/></svg></button>
                <button type="button" class="icon-btn" data-cmd="insertOrderedList" aria-label="Numbered list"><svg class="icon"><use href="#i-olist"/></svg></button>
                <button type="button" class="icon-btn" data-tool="image" aria-label="Add an image"><svg class="icon"><use href="#i-image"/></svg></button>
                <input type="file" id="note-image" accept="image/*" hidden>
                <span class="divider" aria-hidden="true"></span>
                <button type="button" class="icon-btn" data-tool="pin" aria-label="Pin note" aria-pressed="${!!n.pinned}"><svg class="icon"><use href="#i-pin"/></svg></button>
                <button type="button" class="icon-btn" data-tool="delete" aria-label="Delete note"><svg class="icon"><use href="#i-trash"/></svg></button>
                <span class="editor-status" id="note-status" aria-live="polite">${n.id ? (n.localOnly ? 'Saved on this laptop' : 'Saved') : 'Not saved yet'}</span>
            </div>
            <div class="editor-doc">
                <label class="sr-only" for="note-title">Note title</label>
                <input type="text" id="note-title" class="note-title" autocomplete="off" placeholder="Untitled note" value="${Util.esc(n.title || '')}">
                <div id="note-body" class="note-body" contenteditable="true" role="textbox" aria-multiline="true" aria-label="Note text" data-placeholder="Start writing…">${n.content || ''}</div>
                <p class="note-private">Only you can see this note.</p>
            </div>`;
    },

    bindEditor() {
        const titleEl = this.el.querySelector('#note-title');
        const bodyEl = this.el.querySelector('#note-body');

        titleEl.addEventListener('input', () => this.queueSave());
        bodyEl.addEventListener('input', () => this.queueSave());

        // Paste as plain text so web styles and scripts never come along
        bodyEl.addEventListener('paste', e => {
            const text = e.clipboardData?.getData('text/plain');
            if (text === undefined) return;
            e.preventDefault();
            document.execCommand('insertText', false, text);
        });

        this.el.querySelector('.editor-bar').addEventListener('click', e => {
            const btn = e.target.closest('button');
            if (!btn) return;
            if (btn.dataset.cmd) {
                document.execCommand(btn.dataset.cmd, false, null);
                bodyEl.focus();
                this.queueSave();
            }
            if (btn.dataset.tool === 'image') this.el.querySelector('#note-image').click();
            if (btn.dataset.tool === 'pin') this.togglePin(btn);
            if (btn.dataset.tool === 'delete') this.remove();
        });

        this.el.querySelector('#note-image').addEventListener('change', e => this.insertImage(e));

        if (!this.current.id) titleEl.focus();
    },

    // ---------- Saving ----------

    queueSave() {
        this.setStatus('Saving…');
        clearTimeout(this._saveTimer);
        this._saveTimer = setTimeout(() => this.saveNow(), 700);
    },

    setStatus(text) {
        const el = this.el.querySelector('#note-status');
        if (el) el.textContent = text;
    },

    async saveNow() {
        const note = this.current;
        if (!note) return;
        const titleEl = this.el.querySelector('#note-title');
        const bodyEl = this.el.querySelector('#note-body');
        if (titleEl) note.title = titleEl.value.trim();
        if (bodyEl) note.content = bodyEl.innerHTML.trim();

        // Don't create empty notes
        if (!note.id && !note.title && !this.plainText(note.content) && !note.content.includes('<img')) {
            this.setStatus('Not saved yet');
            return;
        }

        const wasNew = !note.id;
        const saved = await this.persist(note);
        if (wasNew) history.replaceState(null, '', `#/notes/${encodeURIComponent(saved.id)}`);
        this.setStatus(saved.localOnly ? 'Saved on this laptop' : 'Saved');
        this.renderList();
    },

    /** Save a note object and keep this.notes and the local cache in step. */
    async persist(note) {
        const saved = await db.saveNote(note, Auth.currentUser?.id);
        const index = this.notes.findIndex(n => n === note || (n.id && String(n.id) === String(note.id)));
        Object.assign(note, saved);
        if (index === -1) this.notes.unshift(note);
        db.cacheNotes(this.notes);
        App.updateCounts();
        return note;
    },

    togglePin(btn) {
        this.current.pinned = !this.current.pinned;
        btn.setAttribute('aria-pressed', String(this.current.pinned));
        btn.setAttribute('aria-label', this.current.pinned ? 'Unpin note' : 'Pin note');
        this.queueSave();
    },

    insertImage(e) {
        const file = e.target.files[0];
        e.target.value = '';
        if (!file) return;
        if (file.size > 2 * 1024 * 1024) {
            Util.toast('That image is over 2 MB. Choose a smaller image or compress it first.');
            return;
        }
        const reader = new FileReader();
        reader.onload = event => {
            this.el.querySelector('#note-body').focus();
            document.execCommand('insertImage', false, event.target.result);
            this.queueSave();
        };
        reader.readAsDataURL(file);
    },

    /** Delete with an undo window instead of a confirm box. */
    remove() {
        const note = this.current;
        clearTimeout(this._saveTimer);
        if (!note.id) {
            location.hash = '#/notes';
            return;
        }

        this.notes = this.notes.filter(n => n !== note);
        this.current = null;
        App.updateCounts();
        location.hash = '#/notes';

        const timer = setTimeout(async () => {
            try {
                await db.deleteNote(note);
            } catch (err) {
                console.error('Failed to delete note:', err);
                Util.toast("Couldn't delete the note on the server. It will come back on refresh.");
            }
            db.cacheNotes(this.notes);
        }, 6000);

        Util.toast(`“${note.title || 'Untitled note'}” deleted.`, {
            timeout: 6000,
            action: {
                label: 'Undo',
                onClick: () => {
                    clearTimeout(timer);
                    this.notes.push(note);
                    App.updateCounts();
                    location.hash = `#/notes/${encodeURIComponent(note.id)}`;
                }
            }
        });
    },

    onKey(e) {
        if (e.key.toLowerCase() === 'c') {
            location.hash = '#/notes/new';
            return true;
        }
        return false;
    },

    // ---------- Add a story to a note (dialog) ----------

    _atn: null, // { story, onAdded }

    bindAddToNote() {
        const dialog = document.getElementById('add-to-note');
        const search = document.getElementById('atn-search');

        search.addEventListener('input', () => this.renderChoices());
        dialog.querySelector('[data-close]').addEventListener('click', () => dialog.close());
        dialog.querySelector('#atn-choices').addEventListener('change', () => this.updateAtnButton());
        document.getElementById('atn-form').addEventListener('submit', e => {
            e.preventDefault();
            this.submitAddToNote();
        });
    },

    async openAddToNote(story, onAdded) {
        if (!this.loaded) await this.load();
        this._atn = { story, onAdded };
        document.getElementById('atn-headline').textContent = story.headline;
        document.getElementById('atn-search').value = '';
        document.getElementById('atn-comment').value = '';
        this.renderChoices();
        document.getElementById('add-to-note').showModal();
        document.getElementById('atn-search').focus();
    },

    renderChoices() {
        const typed = document.getElementById('atn-search').value.trim();
        const q = Util.normalize(typed);
        const notes = [...this.notes]
            .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))
            .filter(n => !q || Util.normalize(n.title).includes(q))
            .slice(0, 6);

        const newLabel = typed ? `New note “${Util.esc(typed)}”` : 'New note with this story';
        document.getElementById('atn-choices').innerHTML = `
            ${notes.map((n, i) => `
                <label><input type="radio" name="atn-note" value="${Util.esc(n.id)}" ${i === 0 ? 'checked' : ''}>
                    <svg class="icon"><use href="#i-note"/></svg>${Util.esc(n.title || 'Untitled note')}
                    <small>${i === 0 && !q ? 'Last used' : Util.esc(Util.relative(n.updated_at))}</small></label>`).join('')}
            <label><input type="radio" name="atn-note" value="__new" ${notes.length ? '' : 'checked'}>
                <svg class="icon"><use href="#i-plus"/></svg>${newLabel}</label>`;
        this.updateAtnButton();
    },

    updateAtnButton() {
        const choice = document.querySelector('input[name="atn-note"]:checked')?.value;
        const btn = document.getElementById('atn-submit');
        if (choice === '__new' || !choice) {
            btn.textContent = 'Add to a new note';
        } else {
            const note = this.notes.find(n => String(n.id) === choice);
            btn.textContent = `Add to “${(note?.title || 'Untitled note').slice(0, 40)}”`;
        }
    },

    storyBlock(story, comment) {
        const meta = [story.source, story.publishedAt ? Util.longDate(story.publishedAt) : ''].filter(Boolean).join(', ');
        return `<blockquote class="note-story"><a href="${Util.esc(story.url)}" target="_blank" rel="noopener">${Util.esc(story.headline)}</a><br><span>${Util.esc(meta)}</span>${comment ? `<br>${Util.esc(comment)}` : ''}</blockquote><p><br></p>`;
    },

    async submitAddToNote() {
        const { story, onAdded } = this._atn;
        const dialog = document.getElementById('add-to-note');
        const choice = document.querySelector('input[name="atn-note"]:checked')?.value || '__new';
        const comment = document.getElementById('atn-comment').value.trim();
        const typed = document.getElementById('atn-search').value.trim();

        let note;
        if (choice === '__new') {
            note = { id: null, title: typed || story.headline.slice(0, 80), content: this.storyBlock(story, comment), pinned: false };
        } else {
            note = this.notes.find(n => String(n.id) === choice);
            note.content = `${note.content || ''}${this.storyBlock(story, comment)}`;
        }

        const submit = document.getElementById('atn-submit');
        submit.disabled = true;
        submit.textContent = 'Adding…';
        const saved = await this.persist(note);
        submit.disabled = false;
        dialog.close();

        onAdded?.();
        Util.toast(`Added to “${saved.title || 'Untitled note'}”.`, {
            action: { label: 'Open note', onClick: () => { location.hash = `#/notes/${encodeURIComponent(saved.id)}`; } }
        });
    }
};

window.Notes = Notes;
