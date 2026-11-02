/*
   Data access: Supabase when configured, with a localStorage fallback so the app
   keeps working in demo mode or when Supabase is unreachable.

   Tables (Supabase): profile, note, source_off, source_request, audit_log, user_setting
*/

let supabaseClient = null;

// Demo mode (sign in with any email, data kept in this browser) is for testing on this laptop.
// On the live site a failed Supabase load shows an error instead of a pretend sign-in.
const DEMO_MODE_ALLOWED = ['localhost', '127.0.0.1', ''].includes(window.location.hostname);

function initSupabase() {
    if (supabaseClient) return supabaseClient;
    if (!CONFIG.SUPABASE_URL || !window.supabase) {
        console.warn('Supabase not available. Running in local demo mode.');
        return null;
    }
    // Stay signed in until "Sign out": the session is kept in this browser and refreshed as needed
    supabaseClient = window.supabase.createClient(CONFIG.SUPABASE_URL, CONFIG.SUPABASE_ANON_KEY, {
        auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true }
    });
    return supabaseClient;
}

function getSupabase() {
    return supabaseClient;
}

// ==================== LOCAL DEMO USER ====================

function getLocalUser() {
    if (!DEMO_MODE_ALLOWED) return null;
    return Util.load('demo_user', null);
}

function getLocalUserProfile() {
    return Util.load('demo_profile', { role: 'user', name: 'Demo user' });
}

function setLocalUser(user, profile) {
    Util.save('demo_user', user);
    Util.save('demo_profile', profile);
}

function clearLocalUser() {
    try {
        localStorage.removeItem('demo_user');
        localStorage.removeItem('demo_profile');
    } catch { /* storage blocked */ }
}

// ==================== PROFILE ====================

async function getUserProfile(userId) {
    if (!supabaseClient) return getLocalUserProfile();

    const { data, error } = await supabaseClient.from('profile').select('*').eq('id', userId).single();
    if (error) {
        console.error('getUserProfile error:', error);
        return null;
    }
    return data;
}

async function getUser() {
    if (!supabaseClient) return getLocalUser();
    const { data: { user } } = await supabaseClient.auth.getUser();
    return user;
}

// ==================== NOTES ====================

const LOCAL_NOTES_KEY = 'user_notes';

/**
 * Notes that only ever lived in this browser: written offline ("local-" ids), or created by the
 * old app, which saved notes locally with Date.now() ids. These get uploaded instead of dropped.
 */
function isUnsyncedNote(note) {
    return note.localOnly || String(note.id).startsWith('local-') || (typeof note.id === 'number' && note.id > 1e12);
}

async function getNotes(userId) {
    const local = Util.load(LOCAL_NOTES_KEY, []);

    if (supabaseClient && userId) {
        try {
            const { data, error } = await supabaseClient
                .from('note')
                .select('*')
                .eq('user_id', userId)
                .order('pinned', { ascending: false })
                .order('updated_at', { ascending: false });
            if (error) throw error;

            const unsynced = local.filter(isUnsyncedNote).map(n => ({ ...n, localOnly: true }));
            const notes = [...(data || []), ...unsynced];
            Util.save(LOCAL_NOTES_KEY, notes);
            return notes;
        } catch (e) {
            console.error('Failed to load notes from Supabase:', e);
        }
    }
    return local;
}

/** Insert or update a note. Returns the saved note (with its id). Falls back to local storage on failure. */
async function saveNote(note, userId) {
    const fields = {
        title: note.title,
        content: note.content,
        color: note.color || '#ffffff',
        pinned: !!note.pinned,
        updated_at: new Date().toISOString()
    };

    if (supabaseClient && userId && navigator.onLine) {
        try {
            if (note.id && !note.localOnly) {
                const { error } = await supabaseClient.from('note').update(fields).eq('id', note.id);
                if (error) throw error;
                return { ...note, ...fields };
            }
            const { data, error } = await supabaseClient
                .from('note')
                .insert({ ...fields, user_id: userId, created_at: fields.updated_at })
                .select()
                .single();
            if (error) throw error;
            return data;
        } catch (e) {
            console.error('Failed to save note to Supabase:', e);
        }
    }

    // Local fallback: keep a temporary id and mark it for a later sync
    return { ...note, ...fields, id: note.id || `local-${Date.now()}`, localOnly: true };
}

async function deleteNote(note) {
    if (supabaseClient && note.id && !note.localOnly) {
        const { error } = await supabaseClient.from('note').delete().eq('id', note.id);
        if (error) throw error;
    }
}

function cacheNotes(notes) {
    Util.save(LOCAL_NOTES_KEY, notes);
}

// ==================== SOURCE SWITCHES ====================
// The source list itself comes from the pipeline (data.js). "Off for everyone" is a row per
// source id in source_off (sql/source_switches.sql): the pipeline stops fetching those sources.

const LOCAL_OFF_KEY = 'sources_off';

/** Ids of sources an admin switched off for everyone. */
async function getSourcesOff() {
    if (!supabaseClient) return Util.load(LOCAL_OFF_KEY, []);
    const { data, error } = await supabaseClient.from('source_off').select('source_id');
    if (error) {
        console.error('getSourcesOff error:', error);
        return [];
    }
    return data.map(r => r.source_id);
}

async function setSourceOff(sourceId, off) {
    if (!supabaseClient) {
        const list = Util.load(LOCAL_OFF_KEY, []).filter(id => id !== sourceId);
        Util.save(LOCAL_OFF_KEY, off ? [...list, sourceId] : list);
        return;
    }
    const table = supabaseClient.from('source_off');
    const { error } = off ? await table.upsert({ source_id: sourceId }) : await table.delete().eq('source_id', sourceId);
    if (error) throw error;
}

/** The old Supabase source list (until Nov 2026), read once to carry hidden sources over. Null on error. */
async function getOldSourceList() {
    if (!supabaseClient) return [];
    const { data, error } = await supabaseClient.from('source').select('id, name, url');
    if (error) {
        console.error('getOldSourceList error:', error);
        return null;
    }
    return data;
}

// ==================== SOURCE REQUESTS ====================
// Members ask for a feed; an admin approves or rejects it. The pipeline fetches approved rows.

const LOCAL_REQUESTS_KEY = 'source_requests';

/** All requests (admins), or only the signed-in person's own (members). Newest first. */
async function getSourceRequests({ mine = false } = {}) {
    const user = await getUser();
    if (!supabaseClient) {
        const all = Util.load(LOCAL_REQUESTS_KEY, []);
        return mine ? all.filter(r => r.requested_by === user?.id) : all;
    }
    try {
        let query = supabaseClient.from('source_request').select('*').order('created_at', { ascending: false });
        if (mine) query = query.eq('requested_by', user?.id);
        const { data, error } = await query;
        if (error) throw error;
        return data || [];
    } catch (e) {
        console.error('getSourceRequests error:', e);
        return [];
    }
}

/** Ask for a source. An admin's own request is approved straight away. */
async function requestSource({ name, url, category, reason }, { approve = false } = {}) {
    const user = await getUser();
    const now = new Date().toISOString();
    const row = {
        name, url, category, reason: reason || null,
        status: approve ? 'approved' : 'pending',
        requested_by: user?.id || null,
        requester_email: user?.email || null,
        ...(approve ? { reviewed_by_email: user?.email || null, reviewed_at: now } : {})
    };

    let saved;
    if (!supabaseClient) {
        saved = { ...row, id: Date.now(), created_at: now };
        Util.save(LOCAL_REQUESTS_KEY, [saved, ...Util.load(LOCAL_REQUESTS_KEY, [])]);
    } else {
        const { data, error } = await supabaseClient.from('source_request').insert(row).select().single();
        if (error) throw error;
        saved = data;
    }
    if (approve) await logAudit('source_add', `Added source: ${name} (${url})`);
    else await logAudit('source_request', `Requested source: ${name} (${url})`);
    return saved;
}

/** Approve or reject (admins), or withdraw (the requester). A reject needs a note. */
async function reviewSourceRequest(request, status, note = '') {
    const user = await getUser();
    const updates = status === 'withdrawn'
        ? { status }
        : { status, review_note: note || null, reviewed_by_email: user?.email || null, reviewed_at: new Date().toISOString() };

    if (!supabaseClient) {
        const all = Util.load(LOCAL_REQUESTS_KEY, []);
        const match = all.find(r => String(r.id) === String(request.id));
        if (match) Object.assign(match, updates);
        Util.save(LOCAL_REQUESTS_KEY, all);
    } else {
        // Only change a request that is still pending, so two admins can't decide it twice
        const { data, error } = await supabaseClient.from('source_request')
            .update(updates).eq('id', request.id).eq('status', 'pending').select();
        if (error) throw error;
        if (!data?.length) throw new Error('This request was already decided.');
    }

    if (status === 'approved') {
        await logAudit('source_approve', `Approved ${request.name} (${request.url}), requested by ${request.requester_email || 'unknown'}`);
    }
    if (status === 'rejected') {
        await logAudit('source_reject', `Rejected ${request.name} (${request.url}), requested by ${request.requester_email || 'unknown'}: ${note}`);
    }
}

// ==================== USER SETTINGS ====================
// Kept with the account (user_setting, private to its owner), so they follow the person to every device.

/** Saved settings: {} when there are none yet, null when they can't be read (offline or demo mode). */
async function getUserSettings(userId) {
    if (!supabaseClient || !userId) return null;
    const { data, error } = await supabaseClient.from('user_setting').select('preferences').eq('user_id', userId).maybeSingle();
    if (error) {
        console.error('getUserSettings error:', error);
        return null;
    }
    return data?.preferences || {};
}

/** Merge changes into the saved settings. False when they couldn't be saved. */
async function saveUserSettings(userId, changes) {
    const current = await getUserSettings(userId);
    if (current === null) return false;
    const { error } = await supabaseClient.from('user_setting').upsert({ user_id: userId, preferences: { ...current, ...changes } });
    if (error) console.error('saveUserSettings error:', error);
    return !error;
}

// ==================== AUDIT LOG ====================

async function logAudit(action, details) {
    const user = await getUser();
    const entry = {
        user_id: user?.id,
        user_email: user?.email || 'demo@example.com',
        action,
        details
    };

    if (supabaseClient) {
        try {
            const { error } = await supabaseClient.from('audit_log').insert(entry);
            if (!error) return;
            console.error('logAudit error:', error);
        } catch (e) {
            console.error('logAudit error:', e);
        }
    }

    const log = Util.load('audit_log', []);
    log.unshift({ ...entry, id: Date.now(), created_at: new Date().toISOString() });
    Util.save('audit_log', log.slice(0, 100));
}

async function getAuditLog() {
    if (!supabaseClient) return Util.load('audit_log', []);

    try {
        const { data, error } = await supabaseClient
            .from('audit_log')
            .select('*')
            .order('created_at', { ascending: false })
            .limit(500);
        if (error) throw error;
        return data || [];
    } catch (e) {
        console.error('getAuditLog error:', e);
        return Util.load('audit_log', []);
    }
}

// ==================== USERS (admin) ====================

async function getUsers() {
    if (!supabaseClient) return Util.load('users', []);

    try {
        const { data, error } = await supabaseClient.from('profile').select('*').order('created_at', { ascending: false });
        if (error) throw error;
        return data || [];
    } catch (e) {
        console.error('getUsers error:', e);
        return [];
    }
}

async function updateUserRole(user, role) {
    const who = user.name || user.email || user.id;

    if (!supabaseClient) {
        const users = Util.load('users', []);
        const match = users.find(u => String(u.id) === String(user.id));
        if (match) match.role = role;
        Util.save('users', users);
    } else {
        const { error } = await supabaseClient.from('profile').update({ role }).eq('id', user.id);
        if (error) throw error;
    }
    await logAudit('user_role', `Changed ${who} to ${role === 'admin' ? 'Admin' : 'Member'}`);
}

// ==================== EXPORT ====================

window.db = {
    DEMO_MODE_ALLOWED,
    initSupabase,
    getSupabase,
    getUser,
    getUserProfile,
    getLocalUser,
    getLocalUserProfile,
    setLocalUser,
    clearLocalUser,
    getNotes,
    saveNote,
    deleteNote,
    cacheNotes,
    getSourcesOff,
    setSourceOff,
    getOldSourceList,
    getSourceRequests,
    requestSource,
    reviewSourceRequest,
    logAudit,
    getAuditLog,
    getUsers,
    updateUserRole,
    getUserSettings,
    saveUserSettings
};
