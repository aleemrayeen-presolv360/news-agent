/*
   Configuration
   The Supabase anon key is public by design; access is controlled in Supabase.
*/

const CONFIG = {
    SUPABASE_URL: 'https://knpcppdwpxvdbfhomylz.supabase.co',
    SUPABASE_ANON_KEY: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImtucGNwcGR3cHh2ZGJmaG9teWx6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTE4MDY2MDAsImV4cCI6MjEwNzM4MjYwMH0.spv7ls3XxU6eziAVksuiVRcluC1K5oL1iFapM9tBbvY',

    // Display names for the four news categories (also used for sources in Settings)
    CATEGORIES: {
        tech: 'Tech and science',
        legal: 'Legal India',
        market: 'Market',
        competitors: 'Competitors'
    },

    // Categories a source can be filed under: the four above, plus Other for a site that fits none.
    // Stories are still sorted into the four by their content, whatever their source's category.
    SOURCE_CATEGORIES: {
        tech: 'Tech and science',
        legal: 'Legal India',
        market: 'Market',
        competitors: 'Competitors',
        other: 'Other'
    },

    // The finer domain the scoring model gives each story. The pipeline maps each one to a
    // category above (agent/config.py DOMAINS); keep the ids in step.
    DOMAINS: {
        ai: 'AI',
        chips: 'Chips and computing',
        mobility: 'EVs and mobility',
        space: 'Space',
        health: 'Health and biotech',
        energy: 'Energy and climate',
        robotics: 'Robotics',
        fintech: 'Fintech',
        security: 'Cybersecurity',
        consumer: 'Gadgets and internet',
        science: 'Science',
        policy: 'Tech policy',
        legal_india: 'Legal India',
        business: 'Business'
    },

    // Company names that put a story in the Competitors category
    COMPETITORS: [
        'Sama', 'Jupitice', 'Webnyay', 'CADRE', 'adrEdge',
        'SMART ODR', 'CORD', 'CODR', 'JustAct', 'WeVaad', 'Credgenics',
        'SpotDraft', 'Legistify', 'NearLaw', 'CaseMine',
        'Clio', 'Smokeball', 'PracticePanther', 'LegalZoom'
    ],


    // Score thresholds behind the Breaking / Major / Notable labels (scores are never shown)
    SCORE_BREAKING: 85,
    SCORE_MAJOR: 70,
    // Breaking is news only while it's fresh; after this a Breaking-scored story shows as Major
    BREAKING_HOURS: 48,

    // Today's list
    DAILY_COUNT_DEFAULT: 5,
    TODAY_DAYS: 7,          // Today picks from stories this recent (data.js holds 30 days)
    TIME_ZONE: 'Asia/Kolkata'
};

window.CONFIG = CONFIG;
