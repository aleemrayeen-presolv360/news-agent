/*
   Panes: drag the line between columns to resize them (laptop only; phones show one column).
   All stories: folders (a) and story list (b). Today: briefing rail (a) and related stories (c).
   Widths are remembered per browser. Double-click a line (or focus it and press Enter) to reset
   it; arrow keys move it, Home and End go to its narrowest and widest.
*/

const Panes = {
    SIZES: {
        reader: { a: { min: 150, max: 360 }, b: { min: 280, max: 680 } },
        today: { a: { min: 170, max: 400 }, c: { min: 200, max: 440 } }
    },
    MIDDLE_MIN: 360,   // the reading column never gets narrower than this
    STEP: 16,          // pixels per arrow key

    init() {
        document.addEventListener('pointerdown', e => this.onPointerDown(e));
        document.addEventListener('keydown', e => this.onKey(e));
        document.addEventListener('dblclick', e => {
            const handle = e.target.closest('.pane-handle');
            if (handle) this.reset(handle);
        });
    },

    /** The draggable line. `key` is the column it sizes; `controls` is that column's id. */
    handleHtml(key, controls, label) {
        return `<div class="pane-handle" role="separator" tabindex="0" aria-orientation="vertical" aria-controls="${controls}" aria-label="${label}" data-pane="${key}" title="Drag to resize. Double-click to reset."></div>`;
    },

    /** Apply the widths this browser remembers. Called after each render of a layout. */
    restore(container, layout) {
        if (!container) return;
        container.dataset.panes = layout;
        const saved = this.load(layout);
        for (const [key, px] of Object.entries(saved)) container.style.setProperty(`--pane-${key}`, `${px}px`);
        container.querySelectorAll('.pane-handle').forEach(h => this.syncAria(h));
    },

    // ---------- Sizing ----------

    parts(handle) {
        const container = handle.parentElement;
        const layout = container.dataset.panes;
        const key = handle.dataset.pane;
        return {
            container, layout, key,
            column: document.getElementById(handle.getAttribute('aria-controls')),
            middle: container.querySelector(':scope > .pane, :scope > .story'),
            limits: this.SIZES[layout]?.[key],
            // The right-hand column grows when the line moves left
            sign: key === 'c' ? -1 : 1
        };
    },

    setWidth(handle, width) {
        const { container, column, middle, limits, key } = this.parts(handle);
        if (!column || !limits) return;
        const current = column.getBoundingClientRect().width;
        const room = middle ? middle.getBoundingClientRect().width - this.MIDDLE_MIN : Infinity;
        const max = Math.min(limits.max, current + Math.max(room, 0));
        const px = Math.round(Math.max(limits.min, Math.min(max, width)));
        container.style.setProperty(`--pane-${key}`, `${px}px`);
        this.syncAria(handle);
        return px;
    },

    reset(handle) {
        const { container, layout, key } = this.parts(handle);
        container.style.removeProperty(`--pane-${key}`);
        const saved = this.load(layout);
        delete saved[key];
        this.save(layout, saved);
        this.syncAria(handle);
    },

    remember(handle) {
        const { layout, key, column } = this.parts(handle);
        if (!column) return;
        const saved = this.load(layout);
        saved[key] = Math.round(column.getBoundingClientRect().width);
        this.save(layout, saved);
    },

    syncAria(handle) {
        const { column, limits } = this.parts(handle);
        if (!column || !limits) return;
        handle.setAttribute('aria-valuemin', limits.min);
        handle.setAttribute('aria-valuemax', limits.max);
        handle.setAttribute('aria-valuenow', Math.round(column.getBoundingClientRect().width));
    },

    // ---------- Input ----------

    onPointerDown(e) {
        const handle = e.target.closest('.pane-handle');
        if (!handle || e.button !== 0) return;
        e.preventDefault();
        const { column, sign } = this.parts(handle);
        if (!column) return;
        const startX = e.clientX;
        const startWidth = column.getBoundingClientRect().width;
        handle.setPointerCapture(e.pointerId);
        document.body.classList.add('is-resizing');

        const move = ev => this.setWidth(handle, startWidth + sign * (ev.clientX - startX));
        const end = () => {
            handle.removeEventListener('pointermove', move);
            handle.removeEventListener('pointerup', end);
            handle.removeEventListener('pointercancel', end);
            document.body.classList.remove('is-resizing');
            this.remember(handle);
        };
        handle.addEventListener('pointermove', move);
        handle.addEventListener('pointerup', end);
        handle.addEventListener('pointercancel', end);
    },

    onKey(e) {
        const handle = e.target.closest?.('.pane-handle');
        if (!handle || !['ArrowLeft', 'ArrowRight', 'Home', 'End', 'Enter'].includes(e.key)) return;
        e.preventDefault();
        e.stopPropagation();
        if (e.key === 'Enter') return this.reset(handle);
        const { column, limits, sign } = this.parts(handle);
        if (!column || !limits) return;
        const width = column.getBoundingClientRect().width;
        const target = e.key === 'Home' ? limits.min
            : e.key === 'End' ? limits.max
            : width + sign * (e.key === 'ArrowRight' ? this.STEP : -this.STEP);
        this.setWidth(handle, target);
        this.remember(handle);
    },

    // ---------- Storage (per browser; private windows may refuse it) ----------

    load(layout) {
        try { return JSON.parse(localStorage.getItem(`panes.${layout}`)) || {}; } catch { return {}; }
    },

    save(layout, widths) {
        try { localStorage.setItem(`panes.${layout}`, JSON.stringify(widths)); } catch { /* not remembered */ }
    }
};

window.Panes = Panes;
