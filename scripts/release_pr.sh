#!/usr/bin/env bash
set -euo pipefail
artifacts="$(cd "$1" && pwd)"
cd "$(dirname "$0")/.."
test -f infrastructure.lock.json || { echo 'Publish and review infrastructure images first' >&2; exit 1; }
sha="$(git rev-parse HEAD)"
python3 scripts/create_release.py "$artifacts" --deploy-sha "$sha" --routing-zone "$ROUTING_ZONE" --infra infrastructure.lock.json --output "releases/${GITHUB_SHA}.json"
branch="automation/release-${GITHUB_SHA}"
if gh pr list --repo cvn-mosprom/deploy --head "$branch" --json number --jq 'length' | grep -q '^1$'; then exit 0; fi
git switch -c "$branch"
git config user.name "$(python3 -c 'import json;print(json.load(open(".github/commit-author.json"))["name"])')"
git config user.email "$(python3 -c 'import json;print(json.load(open(".github/commit-author.json"))["email"])')"
git add "releases/${GITHUB_SHA}.json"
git commit -m "release: ${GITHUB_SHA}"
auth="$(printf 'x-access-token:%s' "$GH_TOKEN" | base64 -w0)"
echo "::add-mask::$auth"
git -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $auth" push origin "$branch"
printf 'Complete immutable image set. Review migration compatibility before enabling automatic image rollback.\n' > "$RUNNER_TEMP/body.md"
gh pr create --repo cvn-mosprom/deploy --base main --head "$branch" --title "release: ${GITHUB_SHA}" --body-file "$RUNNER_TEMP/body.md"
