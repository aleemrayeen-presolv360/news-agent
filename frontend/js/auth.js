/*
   Authentication: sign in, create account, reset password, set a new password.
   Uses Supabase Auth; without Supabase it runs a local demo mode.
*/

// Read before the Supabase client starts, because it clears the recovery token from the URL
const RECOVERY_IN_URL = /type=recovery/.test(window.location.hash);
// A refused Google sign-in comes back as #error_description=... (for example, a non-team email)
const OAUTH_ERROR = new URLSearchParams(window.location.hash.slice(1)).get('error_description');

const Auth = {
    currentUser: null,
    currentProfile: null,

    async init() {
        this.bindEvents();
        this.renderPeek();

        const supabase = db.getSupabase();
        if (supabase) {
            supabase.auth.onAuthStateChange((event, session) => {
                // A password-reset email link brings the user back here with a recovery session
                if (event === 'PASSWORD_RECOVERY') this.showRecovery();
                // The saved session came back after the sign-in screen was shown (the network
                // was slow to wake): go straight in instead of asking for the password again.
                // Deferred, because a Supabase call inside this callback can deadlock the client.
                if (['SIGNED_IN', 'TOKEN_REFRESHED'].includes(event) && session && !RECOVERY_IN_URL) {
                    setTimeout(async () => {
                        if (this.currentUser) return;
                        await this._setUser(session.user);
                        this.showApp();
                    }, 0);
                }
            });
            this.offerGoogle();
        }

        await this.checkSession();
        if (OAUTH_ERROR) {
            history.replaceState(null, '', window.location.pathname);
            this._error('signin-error', this._friendly({ message: OAUTH_ERROR }));
        }
    },

    /** Show "Continue with Google" once Google sign-in is switched on in Supabase (Auth > Providers). */
    async offerGoogle() {
        try {
            const resp = await fetch(`${CONFIG.SUPABASE_URL}/auth/v1/settings`, { headers: { apikey: CONFIG.SUPABASE_ANON_KEY } });
            const settings = await resp.json();
            if (!settings.external?.google) return;
            document.querySelectorAll('.google-signin').forEach(el => { el.hidden = false; });
        } catch { /* offline: password sign-in still works */ }
    },

    async signInWithGoogle() {
        this._error('signin-error', '');
        const { error } = await db.getSupabase().auth.signInWithOAuth({
            provider: 'google',
            options: {
                // Back to this page; Supabase must list it under Auth > URL configuration
                redirectTo: window.location.origin + window.location.pathname,
                // Suggest the work account; the database still refuses any other domain
                queryParams: { hd: CONFIG.TEAM_EMAIL_DOMAIN, prompt: 'select_account' }
            }
        });
        if (error) this._error('signin-error', this._friendly(error));
    },

    bindEvents() {
        document.querySelectorAll('[data-auth-view]').forEach(link => {
            link.addEventListener('click', e => {
                e.preventDefault();
                this.showView(link.dataset.authView);
            });
        });

        document.querySelectorAll('[data-toggle-password]').forEach(btn => {
            btn.addEventListener('click', () => {
                const input = document.getElementById(btn.dataset.togglePassword);
                const show = input.type === 'password';
                input.type = show ? 'text' : 'password';
                btn.textContent = show ? 'Hide' : 'Show';
                btn.setAttribute('aria-pressed', String(show));
            });
        });

        document.getElementById('signin-form').addEventListener('submit', e => { e.preventDefault(); this.signIn(); });
        document.getElementById('signup-form').addEventListener('submit', e => { e.preventDefault(); this.signUp(); });
        document.getElementById('reset-form').addEventListener('submit', e => { e.preventDefault(); this.sendReset(); });
        document.getElementById('reset-again').addEventListener('click', () => this.sendReset());
        document.getElementById('newpass-form').addEventListener('submit', e => { e.preventDefault(); this.setNewPassword(); });
        document.querySelectorAll('[data-google-signin]').forEach(btn => btn.addEventListener('click', () => this.signInWithGoogle()));
    },

    /** Show one of: signin, signup, reset, newpass. */
    showView(view) {
        for (const name of ['signin', 'signup', 'reset', 'newpass']) {
            document.getElementById(`${name}-form`).hidden = name !== view;
        }
        if (view === 'reset') {
            document.getElementById('reset-ask').hidden = false;
            document.getElementById('reset-sent').hidden = true;
            const typed = document.getElementById('signin-email').value.trim();
            if (typed) document.getElementById('reset-email').value = typed;
        }
        const firstInput = document.querySelector(`#${view}-form input`);
        firstInput?.focus();
    },

    /** Headlines on the sign-in screen: the payoff waiting after sign-in. Titles only. */
    renderPeek() {
        const top = Stories.all().slice(0, 3);
        const list = document.getElementById('auth-peek');
        list.innerHTML = top.map(s => `<li>${Util.esc(s.headline)}</li>`).join('');
        if (!top.length) document.querySelector('.auth-side').hidden = true;
    },

    // ---------- Helpers for form state ----------

    _busy(form, busy, busyText) {
        const btn = form.querySelector('button[type="submit"]');
        if (busy) {
            btn.dataset.label = btn.textContent;
            btn.textContent = busyText;
        } else if (btn.dataset.label) {
            btn.textContent = btn.dataset.label;
        }
        btn.disabled = busy;
    },

    _error(id, message, field) {
        document.getElementById(id).textContent = message || '';
        document.querySelectorAll('[aria-invalid="true"]').forEach(el => el.removeAttribute('aria-invalid'));
        if (field) {
            field.setAttribute('aria-invalid', 'true');
            field.focus();
        }
    },

    _friendly(error) {
        const msg = error?.message || '';
        if (/invalid login credentials/i.test(msg)) return "That email and password don't match. Try again or reset your password.";
        if (/email not confirmed/i.test(msg)) return 'Confirm your email first. Check your inbox for the confirmation link.';
        if (/already registered/i.test(msg)) return 'An account with this email already exists. Sign in instead.';
        // The database refuses sign-ups outside the team's domain (sql/security.sql)
        if (/presolv360\.com|database error saving new user/i.test(msg)) return `News Intel is for the Presolv360 team. Sign up with your @${CONFIG.TEAM_EMAIL_DOMAIN} email.`;
        if (/provider is not enabled/i.test(msg)) return 'Google sign-in is not switched on yet. Use your email and password.';
        if (/access_denied|cancel/i.test(msg)) return 'Google sign-in was cancelled. Try again, or use your email and password.';
        if (/rate limit/i.test(msg)) return 'Too many attempts. Wait a minute and try again.';
        if (/fetch|network/i.test(msg)) return "Can't reach the server. Check your connection and try again.";
        return msg || 'Something went wrong. Try again.';
    },

    // ---------- Session ----------

    async checkSession() {
        const supabase = db.getSupabase();
        if (supabase) {
            const session = await this._savedSession(supabase);
            if (session) {
                await this._setUser(session.user);
                if (RECOVERY_IN_URL) this.showRecovery();
                else this.showApp();
                return;
            }
        } else {
            const user = db.getLocalUser();
            if (user) {
                this.currentUser = user;
                this.currentProfile = db.getLocalUserProfile();
                this.showApp();
                return;
            }
        }
        this.showAuth();
    },

    /**
     * The session saved in this browser. Sign-in lasts until "Sign out", across closed tabs and
     * new versions of the site. Opening the laptop, the network can take a few seconds to come
     * back; refreshing the session fails meanwhile, so retry instead of showing the sign-in form.
     */
    async _savedSession(supabase) {
        for (let attempt = 0; ; attempt++) {
            const { data: { session }, error } = await supabase.auth.getSession();
            if (session || !error || attempt === 3) return session;
            if (!/fetch|network|retryable/i.test(`${error.name} ${error.message}`)) return null;
            await new Promise(r => setTimeout(r, 1500 * (attempt + 1)));
        }
    },

    async _setUser(user) {
        this.currentUser = user;
        this.currentProfile = (await db.getUserProfile(user.id)) || { name: user.user_metadata?.name, role: 'user' };
    },

    async signIn() {
        const form = document.getElementById('signin-form');
        const emailEl = document.getElementById('signin-email');
        const passEl = document.getElementById('signin-password');
        const email = emailEl.value.trim().toLowerCase();
        const password = passEl.value;

        if (!email) return this._error('signin-error', 'Enter your work email.', emailEl);
        if (!password) return this._error('signin-error', 'Enter your password.', passEl);
        this._error('signin-error', '');

        const supabase = db.getSupabase();
        if (!supabase) {
            if (password.length < 6) return this._error('signin-error', 'In demo mode, use any password of 6 or more characters.', passEl);
            const user = { id: `demo-${Util.normalize(email)}`, email };
            const profile = { name: email.split('@')[0], role: email.includes('admin') ? 'admin' : 'user' };
            db.setLocalUser(user, profile);
            this.currentUser = user;
            this.currentProfile = profile;
            db.logAudit('login', 'Signed in');
            return this.showApp();
        }

        this._busy(form, true, 'Signing in…');
        const { data, error } = await supabase.auth.signInWithPassword({ email, password });
        this._busy(form, false);

        if (error) return this._error('signin-error', this._friendly(error), passEl);

        await this._setUser(data.user);
        await db.logAudit('login', 'Signed in');
        this.showApp();
    },

    async signUp() {
        const form = document.getElementById('signup-form');
        const nameEl = document.getElementById('signup-name');
        const emailEl = document.getElementById('signup-email');
        const passEl = document.getElementById('signup-password');
        const name = nameEl.value.trim();
        const email = emailEl.value.trim().toLowerCase();
        const password = passEl.value;

        if (!name) return this._error('signup-error', 'Enter your full name.', nameEl);
        if (!email) return this._error('signup-error', 'Enter your work email.', emailEl);
        if (!email.endsWith(`@${CONFIG.TEAM_EMAIL_DOMAIN}`)) {
            return this._error('signup-error', `News Intel is for the Presolv360 team. Sign up with your @${CONFIG.TEAM_EMAIL_DOMAIN} email.`, emailEl);
        }
        if (password.length < 8) return this._error('signup-error', 'Use a password with at least 8 characters.', passEl);
        this._error('signup-error', '');

        const supabase = db.getSupabase();
        if (!supabase) {
            const user = { id: `demo-${Util.normalize(email)}`, email };
            const profile = { name, role: 'user' };
            db.setLocalUser(user, profile);
            const users = Util.load('users', []);
            users.push({ ...user, ...profile, created_at: new Date().toISOString() });
            Util.save('users', users);
            this.currentUser = user;
            this.currentProfile = profile;
            db.logAudit('signup', 'Created an account');
            return this.showApp();
        }

        this._busy(form, true, 'Creating account…');
        const { data, error } = await supabase.auth.signUp({ email, password, options: { data: { name } } });
        this._busy(form, false);

        if (error) return this._error('signup-error', this._friendly(error), emailEl);

        // With email confirmation on, Supabase returns no session until the link is clicked
        if (!data.session) {
            this.showView('signin');
            document.getElementById('signin-email').value = email;
            document.getElementById('signin-error').textContent = 'Account created. Confirm your email with the link we sent, then sign in.';
            return;
        }

        // The profile row is created by a database trigger; give it a moment
        await new Promise(r => setTimeout(r, 500));
        await this._setUser(data.user);
        await db.logAudit('signup', 'Created an account');
        this.showApp();
    },

    async sendReset() {
        const form = document.getElementById('reset-form');
        const emailEl = document.getElementById('reset-email');
        const email = emailEl.value.trim().toLowerCase();

        if (!email) return this._error('reset-error', 'Enter the email you signed up with.', emailEl);
        this._error('reset-error', '');

        const supabase = db.getSupabase();
        if (!supabase) return this._error('reset-error', 'Password reset needs Supabase. It is not available in demo mode.');

        this._busy(form, true, 'Sending…');
        // Return to this page; Supabase must list this address under Auth > URL configuration
        const { error } = await supabase.auth.resetPasswordForEmail(email, {
            redirectTo: window.location.origin + window.location.pathname
        });
        this._busy(form, false);

        if (error) return this._error('reset-error', this._friendly(error), emailEl);

        document.getElementById('reset-sent-email').textContent = email;
        document.getElementById('reset-ask').hidden = true;
        document.getElementById('reset-sent').hidden = false;
    },

    async setNewPassword() {
        const form = document.getElementById('newpass-form');
        const passEl = document.getElementById('newpass-password');
        if (passEl.value.length < 8) return this._error('newpass-error', 'Use a password with at least 8 characters.', passEl);

        this._busy(form, true, 'Saving…');
        const { data, error } = await db.getSupabase().auth.updateUser({ password: passEl.value });
        this._busy(form, false);

        if (error) return this._error('newpass-error', this._friendly(error), passEl);

        history.replaceState(null, '', window.location.pathname);
        await this._setUser(data.user);
        Util.toast('Password updated.');
        this.showApp();
    },

    async signOut() {
        const supabase = db.getSupabase();
        if (supabase) await supabase.auth.signOut();
        else db.clearLocalUser();
        // Reload so no signed-in state lingers in memory
        window.location.hash = '';
        window.location.reload();
    },

    showAuth() {
        document.getElementById('app').hidden = true;
        document.getElementById('auth').hidden = false;
        const hash = location.hash.replace('#', '');
        this.showView(['signup', 'reset'].includes(hash) ? hash : 'signin');
    },

    showRecovery() {
        document.getElementById('app').hidden = true;
        document.getElementById('auth').hidden = false;
        this.showView('newpass');
    },

    showApp() {
        document.getElementById('auth').hidden = true;
        document.getElementById('app').hidden = false;
        App.start();
    },

    displayName() {
        return this.currentProfile?.name || this.currentUser?.user_metadata?.name || this.currentUser?.email?.split('@')[0] || 'You';
    },

    isAdmin() {
        return this.currentProfile?.role === 'admin' || this.currentProfile?.is_admin === true;
    }
};

window.Auth = Auth;
