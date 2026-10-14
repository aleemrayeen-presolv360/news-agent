/*
   Configuration
   The Supabase anon key is public by design; access is controlled in Supabase.
*/

const CONFIG = {
    SUPABASE_URL: 'https://knpcppdwpxvdbfhomylz.supabase.co',
    SUPABASE_ANON_KEY: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImtucGNwcGR3cHh2ZGJmaG9teWx6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTE4MDY2MDAsImV4cCI6MjEwNzM4MjYwMH0.spv7ls3XxU6eziAVksuiVRcluC1K5oL1iFapM9tBbvY',

    // Display names for the four news categories
    CATEGORIES: {
        tech: 'AI and tech',
        legal: 'Legal India',
        market: 'Market',
        competitors: 'Competitors'
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

    // Today's list
    DAILY_COUNT_DEFAULT: 5,
    TIME_ZONE: 'Asia/Kolkata'
};

window.CONFIG = CONFIG;
