#!/usr/bin/env bash
# Commit the freshly built frontend/data.js and push it. Used by daily.yml and new-source.yml.
#
#   bash scripts/push_site_data.sh "commit message"
#
# The job checked out the commit that started it, and other pushes may have landed since:
# code, or another job's data.js. Rebasing two copies of these generated files conflicts, so
# the new data.js is kept aside, the job moves to the latest main, puts it back and re-stamps
# index.html against the latest code. A push that loses a race is retried.
set -euo pipefail

message="$1"
built="$(mktemp)"
cp frontend/data.js "$built"

git config user.name "GitHub Actions"
git config user.email "actions@github.com"

for attempt in 1 2 3; do
    git checkout -- frontend/data.js frontend/index.html
    git pull --rebase --quiet
    cp "$built" frontend/data.js
    python -m agent.publish_static --stamp-only
    git add frontend/data.js frontend/index.html
    git diff --staged --quiet && exit 0
    git commit --quiet -m "$message"
    git push --quiet && exit 0
    echo "push_site_data: push lost a race (attempt $attempt), trying again"
    git reset --quiet --hard HEAD~1
done
echo "push_site_data: couldn't push after 3 attempts" >&2
exit 1
