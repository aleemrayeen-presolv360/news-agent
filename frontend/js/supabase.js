/*
   Data access: Supabase when configured, with a localStorage fallback so the app
   keeps working in demo mode or when Supabase is unreachable.

   Tables (Supabase): profile, note, source, audit_log
*/

let supabaseClient = null;

function initSupabase() {
    if (supabaseClient) return supabaseClient;
    if (!CONFIG.SUPABASE_URL || !window.supabase) {
        console.warn('Supabase not available. Running in local demo mode.');
        return null;
    }
    supabaseClient = window.supabase.createClient(CONFIG.SUPABASE_URL, CONFIG.SUPABASE_ANON_KEY);
    return supabaseClient;
}

function getSupabase() {
    return supabaseClient;
}

// ==================== LOCAL DEMO USER ====================

function getLocalUser() {
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

// ==================== SOURCES ====================

async function getSources() {
    if (!supabaseClient) return Util.load('sources', []);

    try {
        const { data, error } = await supabaseClient.from('source').select('*').order('name');
        if (error) throw error;
        return data || [];
    } catch (e) {
        console.error('getSources error:', e);
        return Util.load('sources', []);
    }
}

async function addSource(source) {
    if (!supabaseClient) {
        const sources = Util.load('sources', []);
        const saved = { ...source, id: Date.now(), created_at: new Date().toISOString() };
        sources.push(saved);
        Util.save('sources', sources);
        await logAudit('source_add', `Added source: ${source.name}`);
        return saved;
    }

    const { data, error } = await supabaseClient.from('source').insert(source).select().single();
    if (error) throw error;
    await logAudit('source_add', `Added source: ${source.name}`);
    return data;
}

async function updateSource(id, updates) {
    if (!supabaseClient) {
        const sources = Util.load('sources', []);
        const index = sources.findIndex(s => String(s.id) === String(id));
        if (index === -1) return null;
        sources[index] = { ...sources[index], ...updates };
        Util.save('sources', sources);
        return sources[index];
    }

    const { data, error } = await supabaseClient.from('source').update(updates).eq('id', id).select().single();
    if (error) throw error;
    return data;
}

/** Fill an empty source table with the default feed list (first run only). */
async function seedSources(defaults) {
    if (!supabaseClient) {
        if (Util.load('sources', []).length) return;
        Util.save('sources', defaults.map((s, i) => ({ ...s, id: Date.now() + i, created_at: new Date().toISOString() })));
        return;
    }
    const { data, error } = await supabaseClient.from('source').select('id').limit(1);
    if (error || (data && data.length)) return;
    const { error: insertError } = await supabaseClient.from('source').insert(defaults);
    if (insertError) console.error('Failed to insert default sources:', insertError);
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
    getSources,
    addSource,
    updateSource,
    seedSources,
    logAudit,
    getAuditLog,
    getUsers,
    updateUserRole
};
