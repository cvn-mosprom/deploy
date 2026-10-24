#!/usr/bin/env python3
"""Reviewable repository setup. Requires an actual collaborator, never a placeholder team."""
import argparse
import base64
import json
import subprocess


def gh(path, body=None):
    command = ["gh", "api", path]
    if body is not None:
        command += ["-X", "PUT", "--input", "-"]
    return json.loads(subprocess.check_output(command, input=json.dumps(body) if body else None, text=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True, help="GitHub collaborator login")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    requirements = {"frontend": ["quality", "security"], "backend": ["quality", "integration", "security"], "deploy": ["validate", "security"]}
    for repository, contexts in requirements.items():
        repo = f"cvn-mosprom/{repository}"
        permissions = gh(f"repos/{repo}/collaborators/{args.owner}/permission")
        if permissions.get("permission") not in {"admin", "maintain", "write"}:
            raise SystemExit(f"{args.owner} is not an eligible owner of {repo}")
        payload = {"required_status_checks": {"strict": True, "contexts": contexts}, "enforce_admins": True,
                   "required_pull_request_reviews": {"required_approving_review_count": 1, "dismiss_stale_reviews": True,
                                                       "require_code_owner_reviews": True}, "restrictions": None,
                   "allow_force_pushes": False, "allow_deletions": False}
        print(json.dumps({"repository": repo, "owner": args.owner, "protection": payload}, indent=2))
        if args.apply:
            owners = gh(f"repos/{repo}/contents/.github/CODEOWNERS?ref=main")
            rules = base64.b64decode(owners["content"]).decode().splitlines()
            if not any(line.split() == ["*", "@" + args.owner] for line in rules if not line.lstrip().startswith("#")):
                raise SystemExit(f"{repo}: commit '* @{args.owner}' to CODEOWNERS before applying protection")
            gh(f"repos/{repo}/branches/main/protection", payload)
    print("CODEOWNERS must contain this verified login before protection is activated")


if __name__ == "__main__":
    main()
