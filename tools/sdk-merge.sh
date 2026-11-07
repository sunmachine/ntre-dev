#!/usr/bin/env bash
# Merge the latest Source SDK 2013 from Valve into the current branch.
#
# Usage: tools/sdk-merge.sh [--ref <ref>] [--no-fetch] [--abort]
#
# The script fetches Valve's history, starts a merge without committing,
# resolves modify/delete conflicts as "keep deleted" for the paths listed in
# tools/sdk-merge-deleted-paths.txt, then prints what is left for a human.
# It never commits. Resolve the remaining conflicts, build both platforms,
# then commit the merge yourself so it lands as a true merge commit.

set -euo pipefail

REMOTE=valve
URL=https://github.com/ValveSoftware/source-sdk-2013.git
REF="$REMOTE/master"
FETCH=1

while [ $# -gt 0 ]; do
	case "$1" in
		--ref) REF="$2"; shift 2 ;;
		--no-fetch) FETCH=0; shift ;;
		--abort) git merge --abort; echo "Merge aborted."; exit 0 ;;
		-h|--help) sed -n '2,12p' "$0"; exit 0 ;;
		*) echo "unknown argument: $1" >&2; exit 2 ;;
	esac
done

TOP="$(git rev-parse --show-toplevel)"
LIST="$TOP/tools/sdk-merge-deleted-paths.txt"
cd "$TOP"

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
	echo "The working tree is not clean. Commit or discard your changes first." >&2
	exit 1
fi

if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
	git remote add "$REMOTE" "$URL"
	git remote set-url --push "$REMOTE" no_push
	echo "Added fetch-only remote $REMOTE."
fi

if [ "$FETCH" = 1 ]; then
	git fetch --no-tags "$REMOTE"
fi

if [ "$(git config --get rerere.enabled || true)" != "true" ]; then
	git config rerere.enabled true
	echo "Enabled rerere for this repository, so a conflict resolved once is replayed next time."
fi

BASE="$(git merge-base HEAD "$REF" || true)"
if [ -z "$BASE" ]; then
	echo "No merge base between HEAD and $REF. Record the SDK base first (see CONTRIBUTING, SDK update procedure)." >&2
	exit 1
fi

echo "Merging $REF ($(git rev-parse --short "$REF")) into $(git branch --show-current), base $(git rev-parse --short "$BASE")."
echo "Valve commits to take: $(git rev-list --count "$BASE".."$REF")"

# Retry an index-writing git command a few times: editors and IDE integrations
# take the index lock for a moment, and so does a concurrent git status.
git_retry() {
	local i
	for i in 1 2 3 4 5; do
		if "$@" 2>/tmp/sdk-merge-git.err; then return 0; fi
		if ! grep -q 'index.lock' /tmp/sdk-merge-git.err; then
			cat /tmp/sdk-merge-git.err >&2
			return 1
		fi
		sleep 1
	done
	cat /tmp/sdk-merge-git.err >&2
	return 1
}

# merge exits non-zero when there are conflicts; that is the expected path.
git_retry git merge --no-commit --no-ff "$REF" >/dev/null || true

# Match a path against the deleted-paths list.
matches_deleted_list() {
	local path="$1" entry
	while IFS= read -r entry; do
		case "$entry" in ''|'#'*) continue ;; esac
		case "$entry" in
			*/) [ "${path#"$entry"}" != "$path" ] && return 0 ;;
			\*.*) [ "${path%"${entry#\*}"}" != "$path" ] && return 0 ;;
			*) [ "$path" = "$entry" ] && return 0 ;;
		esac
	done < "$LIST"
	return 1
}

auto=0
kept=()
content=()
other=()
# Collect the list first: "git diff" may hold the index lock while it runs,
# and the loop below writes to the index.
mapfile -t conflicted < <(git -c core.optionalLocks=false diff --name-only --diff-filter=U)
for f in "${conflicted[@]}"; do
	[ -z "$f" ] && continue
	stages="$(git ls-files -u -- "$f" | awk '{print $3}' | sort -u | tr '\n' ' ')"
	if [ "$stages" = "1 3 " ]; then
		# ours deleted, theirs modified
		if matches_deleted_list "$f"; then
			git_retry git rm -q -- "$f"
			auto=$((auto + 1))
		else
			kept+=("$f")
		fi
	elif [ "$stages" = "1 2 3 " ]; then
		content+=("$f")
	else
		other+=("$f")
	fi
done

echo
echo "Modify/delete conflicts resolved as keep deleted (listed paths): $auto"
echo "Modify/delete conflicts outside the list, left for you: ${#kept[@]}"
printf '  %s\n' "${kept[@]:-}" | sed '/^  $/d'
echo "Content conflicts, left for you: ${#content[@]}"
printf '  %s\n' "${content[@]:-}" | sed '/^  $/d'
if [ "${#other[@]}" -gt 0 ]; then
	echo "Other conflicts (added on both sides, or deleted by Valve): ${#other[@]}"
	printf '  %s\n' "${other[@]}"
fi
echo
echo "Next: resolve the files above, build Linux and Windows, then run"
echo "  git commit"
echo "so the result is a merge commit. To give up: tools/sdk-merge.sh --abort"
