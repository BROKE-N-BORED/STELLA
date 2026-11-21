"""STELLA live Hugging Face lookup (v0.33.0).

The bridge (ollama_bridge) knows a small curated map of Ollama
tags to Hugging Face repos. For a tag the map does not know, the
download used to dead-end with "Stella doesn't know where this
model's training files live" — the user had to go and find the
repo themselves. Joshua's order (2026-11-18): "I told you it
needs to pull this from huggingface dude I shouldn't have to do
anything". So now Stella looks it up itself.

The lookup uses the public Hub API — no key, no account:

    GET {HUB_API_BASE}/api/models?search=<terms>&limit=20
    GET {HUB_API_BASE}/api/models/<owner>/<name>   (for siblings)

The query ladder (deterministic, derived from the tag by
``search_terms``):

1. the model's base name as-is ("granite4.1-abliterated"),
2. the base name with dashes at letter-to-digit boundaries
   ("granite-4.1-abliterated") — Hub repos are usually dashed,
3. the leading family token plus the size ("granite 3b"),
4. the family token alone ("granite") — only when no size is
   known anywhere in the tag.

The first rung that yields an offerable repo wins; later rungs
are not searched.

A repo is offerable ONLY if it is really this model (its name
and size agree with the tag - see _repo_matches_model) AND it
can actually be trained from:

- its name does not contain "gguf" or "mlx" (case-insensitive),
- its file list has config.json AND at least one .safetensors
  file — GGUF-only repos fail this, which matters: a live search
  for Granite returns mostly GGUF/MLX repos, while the real
  training repo (ibm-granite/granite-4.1-3b-base) passes.

Ranking among the offerable repos of one rung is deterministic:
(1) exact repo-name match to the model's name, (2) repos owned
by the tag's own author org, (3) most downloads, (4) repo id.
At most 3 are offered.

Results are candidates the user confirms — exactly like the
bridge, a found repo is never set silently. Failure is honest:
the Hub unreachable, a timeout, or the 30-second budget running
out gives the "offline" state (a plain try-again message),
never a traceback; a completed search with nothing offerable
gives "none" (the old honest unknown message — now the rare
case, e.g. bonsai-2, which has no transformers repo on the Hub).
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .ollama_bridge import _base_name

HUB_API_BASE = "https://huggingface.co"

# The two plain-words endings, shared by the window and the chat
# so the words never drift apart. UNKNOWN is the pre-v0.33.0
# message, kept word for word: it is now what a completed search
# with no offerable repo says.
UNKNOWN_MESSAGE = (
    "Stella doesn't know where this model's training files live "
    "on Hugging Face yet. Find the model on huggingface.co and "
    "set the Hugging Face repo in the profile window, or pick a "
    "different model."
)
OFFLINE_MESSAGE = (
    "Stella couldn't reach Hugging Face. Check your connection "
    "and try again, or pick a different model."
)

_MAX_OFFERS = 3
_MAX_DETAILS_PER_RUNG = 10
_REQUEST_CAP_SECONDS = 10.0
_FOUND_SOURCE = "found on Hugging Face"


class _HubDown(Exception):
    """One Hub request failed (network, HTTP, bad JSON, or the
    lookup budget ran out). The search treats it per call site:
    a failed search means the Hub is unreachable; a failed
    detail fetch just skips that repo."""


def _size_hint(text: str) -> str | None:
    """The size in a tag part, as written: "3b" from ":3b" or
    "2b-q4_K_M". Looks in the version part first (after the last
    ":" of the model's own name), then in the whole text."""
    lowered = (text or "").lower()
    last = lowered.rsplit("/", 1)[-1]
    version = last.rsplit(":", 1)[-1] if ":" in last else ""
    for part in (version, lowered):
        match = re.search(r"(\d+(?:\.\d+)?)b", part)
        if match:
            return match.group(1) + "b"
    return None


def _dashed(name: str) -> str:
    """The name with dashes at letter-to-digit boundaries:
    "granite4.1-abliterated" becomes "granite-4.1-abliterated",
    "qwen3.5" becomes "qwen-3.5". Hub repos are usually named
    this way; Ollama tags usually are not."""
    return re.sub(r"([a-zA-Z])(\d)", r"\1-\2", name)


def search_terms(tag: str) -> list[str]:
    """The query ladder for a tag, in order (see the module
    docstring). Deterministic: the same tag always gives the
    same ladder."""
    base = _base_name(tag)
    name = base.rsplit("/", 1)[-1]
    terms: list[str] = []

    def add(term: str) -> None:
        term = (term or "").strip()
        if term and term not in terms:
            terms.append(term)

    add(name)
    add(_dashed(name))
    family_match = re.match(r"[a-zA-Z]+", name)
    family = family_match.group(0) if family_match else ""
    size = _size_hint(tag)
    if family and size:
        add(f"{family} {size}")
    elif family:
        add(family)
    return terms


def _fetch_json(path: str, deadline: float):
    """GET one Hub API path as JSON. Raises _HubDown on any
    failure, including the lookup budget running out."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _HubDown("the lookup budget ran out")
    url = HUB_API_BASE.rstrip("/") + path
    request = urllib.request.Request(
        url, headers={"User-Agent": "STELLA"}
    )
    try:
        with urllib.request.urlopen(
            request, timeout=min(_REQUEST_CAP_SECONDS, remaining)
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError,
            ValueError) as exc:
        raise _HubDown(str(exc)) from exc


def _name_tokens(text: str) -> list[str]:
    """Name tokens for matching: 'qwen3.5-uncensored' becomes
    ['qwen', '3.5', 'uncensored'], 'granite-4.1-3b-base' becomes
    ['granite', '4.1', '3b', 'base']. A trailing size ('3b',
    '1.7b') stays one token."""
    return re.findall(
        r"[a-z]+|\d+(?:\.\d+)?b|\d+(?:\.\d+)?",
        (text or "").lower(),
    )


def _repo_matches_model(repo: str, tag: str) -> bool:
    """True when a Hub repo really is the model the tag names
    (v0.35.0, N2). The Hub's fuzzy search returns near misses -
    other families' builds and other sizes that merely share a
    search word - and offering one of those as 'this model'
    would download a stranger's weights. So a repo is only
    offerable when its name agrees with the tag:

    - the family token (qwen, granite, bonsai) is in the name;
    - every version number in the tag's name (3.5, 4.1) is in
      the repo name;
    - the sizes agree: a size in both must be the same size,
      and a repo that names a size the tag never mentions
      cannot be checked, so it is not offered;
    - a variant word in the tag's name (uncensored,
      abliterated) is in the repo name too, unless the repo is
      plainly the base model (its name says 'base'), which is
      what a tuned tag is trained from.
    """
    base = _base_name(tag)
    name = base.rsplit("/", 1)[-1]
    repo_name = repo.rsplit("/", 1)[-1].lower()
    tag_tokens = _name_tokens(name)
    repo_tokens = _name_tokens(repo_name)
    if not tag_tokens or not repo_tokens:
        return False
    tag_size = _size_hint(tag)
    repo_size = _size_hint(repo_name)
    if tag_size is not None and repo_size is not None:
        if tag_size != repo_size:
            return False
    elif repo_size is not None:
        return False
    family = next(
        (tok for tok in tag_tokens if tok.isalpha()), ""
    )
    if not family or family not in repo_tokens:
        return False
    size_token = tag_size or ""
    for tok in tag_tokens:
        if tok[0].isdigit() and tok != size_token:
            if tok not in repo_tokens:
                return False
    variants = [
        tok for tok in tag_tokens
        if tok.isalpha() and tok != family
    ]
    if variants and "base" not in repo_tokens:
        if not any(tok in repo_tokens for tok in variants):
            return False
    return True


def _offerable(detail) -> bool:
    """True when a repo detail shows real training weights:
    config.json plus at least one .safetensors file."""
    if not isinstance(detail, dict):
        return False
    siblings = [
        entry.get("rfilename", "")
        for entry in (detail.get("siblings") or [])
        if isinstance(entry, dict)
    ]
    return "config.json" in siblings and any(
        name.endswith(".safetensors") for name in siblings
    )


def lookup_hf_repos(tag: str, timeout: float = 30.0) -> dict:
    """Look a tag's Hugging Face repo up on the Hub, live.

    Returns {"state": "found", "candidates": [...]} with at most
    3 candidates ({"repo", "source"} dicts, the bridge's shape),
    {"state": "none", "candidates": []} when the search completed
    but nothing offerable turned up, or {"state": "offline",
    "candidates": []} when the Hub could not be reached within
    the budget. Never raises for a network problem."""
    deadline = time.monotonic() + timeout
    base = _base_name(tag)
    name = base.rsplit("/", 1)[-1]
    org = base.rsplit("/", 1)[0] if "/" in base else ""
    dashed = _dashed(name)
    for term in search_terms(tag):
        if time.monotonic() >= deadline:
            return {"state": "offline", "candidates": []}
        path = (
            "/api/models?search="
            + urllib.parse.quote(term)
            + "&limit=20"
        )
        try:
            results = _fetch_json(path, deadline)
        except _HubDown:
            return {"state": "offline", "candidates": []}
        if not isinstance(results, list):
            results = []
        offerable: list[dict] = []
        checked = 0
        for item in results:
            if not isinstance(item, dict):
                continue
            repo = (item.get("id") or "").strip()
            if not repo or "/" not in repo:
                continue
            lowered = repo.lower()
            if "gguf" in lowered or "mlx" in lowered:
                continue
            if checked >= _MAX_DETAILS_PER_RUNG:
                break
            if time.monotonic() >= deadline:
                return {"state": "offline", "candidates": []}
            checked += 1
            try:
                detail = _fetch_json(f"/api/models/{repo}", deadline)
            except _HubDown:
                continue
            if _offerable(detail) and _repo_matches_model(repo, tag):
                offerable.append(
                    {
                        "repo": repo,
                        "downloads": item.get("downloads") or 0,
                    }
                )
        if offerable:
            def rank_key(candidate: dict):
                owner, _, repo_name = candidate["repo"].partition("/")
                exact = repo_name.lower() in (name, dashed)
                own_org = bool(org) and owner.lower() == org
                return (
                    not exact,
                    not own_org,
                    -candidate["downloads"],
                    candidate["repo"].lower(),
                )

            offerable.sort(key=rank_key)
            return {
                "state": "found",
                "candidates": [
                    {"repo": c["repo"], "source": _FOUND_SOURCE}
                    for c in offerable[:_MAX_OFFERS]
                ],
            }
    return {"state": "none", "candidates": []}
