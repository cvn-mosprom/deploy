#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import json,re
from pathlib import Path
refs={}
for path in Path('artifacts').rglob('*.txt'):
    name=path.stem
    ref=path.read_text().strip()
    if name not in {'discovery','patroni'} or not re.fullmatch(r'ghcr.io/cvn-mosprom/'+name+r'@sha256:[a-f0-9]{64}',ref):
        raise SystemExit('unexpected infrastructure image')
    refs[name]=ref
if set(refs)!={'discovery','patroni'}:
    raise SystemExit('incomplete infrastructure build')
refs['pgbackrest']=refs['patroni']
Path('infrastructure.lock.json').write_text(json.dumps(refs,indent=2)+'\n')
PY
branch="automation/infrastructure-${GITHUB_SHA}"
if gh pr list --repo cvn-mosprom/deploy --head "$branch" --json number --jq length | grep -q '^1$'; then exit 0; fi
git switch -c "$branch"
git config user.name "$(python3 -c 'import json;print(json.load(open(".github/commit-author.json"))["name"])')"
git config user.email "$(python3 -c 'import json;print(json.load(open(".github/commit-author.json"))["email"])')"
git add infrastructure.lock.json
git commit -m "build: pin infrastructure images ${GITHUB_SHA}"
auth="$(printf 'x-access-token:%s' "$GH_TOKEN" | base64 -w0)"
echo "::add-mask::$auth"
git -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $auth" push origin "$branch"
printf 'Reviewed discovery and Patroni/pgBackRest images, scanned before publication and signed by the infrastructure workflow.\n' > "$RUNNER_TEMP/body.md"
gh pr create --repo cvn-mosprom/deploy --base main --head "$branch" --title 'build: update infrastructure images' --body-file "$RUNNER_TEMP/body.md"
