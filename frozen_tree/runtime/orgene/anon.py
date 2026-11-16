"""Neutral-writing self-check (E21): find identity traces in the working tree, the artifacts and the git metadata.

The check changes no file. It is a test that runs at every commit (runtime/tests/test_neutral_selfcheck.py) and a
step of `tools/freeze.py make`, so that the hashes taken at the freeze stay valid at submission.

Detectors
  home_path   absolute paths under a home or per-user temp directory (macOS, Linux, Windows forms)
  email       e-mail addresses, except reserved example domains and no-reply addresses
  term        identity terms (names, organisation, machine, sibling-project names, legacy prefixes) read from a
              terms file that is NOT part of the repository (see below)
  local_user  the login name and host name of the machine running the scan (read at run time, never stored)
  git_author / git_committer / git_config / git_message
              commit identities other than the repository identity, and detectors above applied to commit messages

The identity terms stay out of the tree on purpose: a scanner that lists the author's name would itself be the leak.
Lookup order: --terms / $ORGENE_ANON_TERMS, then <root>/PROVENANCE/anon_terms.txt, then the same path in the main
checkout when <root> is a git worktree. PROVENANCE/ is git-ignored. File format: one term per line, matched
case-insensitively as a substring; a line starting with `re:` is a (case-insensitive) regular expression; `#` starts
a comment line. Without a terms file the generic detectors and local_user still run.

Reports carry path, line, column, detector and an index into the terms list; they never echo the matched line
(case files contain problem text) and mask the matched text.
"""
import fnmatch
import getpass
import os
import re
import socket
import subprocess

TERMS_ENV = "ORGENE_ANON_TERMS"
TERMS_REL = os.path.join("PROVENANCE", "anon_terms.txt")

# The repository identity every commit must carry (DECISIONS R1-D1; `git config user.name/user.email`).
DEFAULT_IDENTITIES = (("orgene-r1", "orgene-r1@example.invalid"),)

# Never scanned by default: git-ignored provenance copies with the original (non-neutral) files, raw benchmark
# files, environments (.venv-tools: its scripts carry absolute paths) and caches (.cache/: the tiktoken encoding
# files, whose hashes are registered in configs/venv_tools.json). Explicit paths given by the caller are scanned as
# given (except .git internals).
EXCLUDED_PREFIXES = ("PROVENANCE/", "releases/v1.0/", "data/raw/", ".cache/")
EXCLUDED_DIR_NAMES = (".git", "__pycache__", ".pytest_cache", "node_modules")
EXCLUDED_DIR_GLOBS = (".venv*",)
# git-ignored directories that hold produced artifacts (runs, evidence snapshots); scanned in addition to the git
# working tree, because they are hashed or shared although git does not track them
ARTIFACT_DIRS = ("experiments", "paper/evidence")
# Every .gitignore entry is either an artifact directory (scanned) or one of the exclusions above (never scanned);
# gitignore_mismatches() checks that the two lists and the repository's .gitignore agree.

# --- generic detectors. Directory names are assembled from pieces so that this file does not match itself.
_HOME_DIRS = "|".join(("Us" + "ers", "ho" + "me"))
_TMP_DIRS = "|".join(("private/var/" + "folders", "var/" + "folders"))
# A leading "/" is allowed before the path (file:///<home>/..., as pip freeze writes local installs), and "\/" (a
# JSON-escaped slash); a host name directly before it is not (https://example.org/<home>/page is a web path), except
# in a file:// URL (file://localhost/<home>/...).
_HOME_RE = re.compile(
    r"(?<![\w.\-~])\\?/(?:" + _HOME_DIRS + r")\\?/[A-Za-z0-9._\-]+"  # posix home directories
    r"|(?<![\w.\-~])\\?/(?:" + _TMP_DIRS + r")\\?/[A-Za-z0-9._\-]+"  # per-user temp directories (macOS)
    r"|(?i:file:)(?:\\?/){2}[A-Za-z0-9.\-]+\\?/(?:" + _HOME_DIRS + "|" + _TMP_DIRS + r")\\?/[A-Za-z0-9._\-]+"  # file URL with host
    r"|(?<![\w])[A-Za-z]:\\+(?:" + "Us" + "ers" + r"|Documents and Settings)\\+[^\\\s\"']+"  # windows profiles
)
_EMAIL_RE = re.compile(r"(?<![\w.%+\-])[A-Za-z0-9][A-Za-z0-9._%+\-]*@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24})\b")
_ALLOWED_EMAIL_DOMAINS = ("example.com", "example.org", "example.net")
_ALLOWED_EMAIL_TLDS = (".invalid", ".example", ".test", ".localhost")
_ALLOWED_EMAIL_LOCALS = ("noreply", "no-reply", "git")

# login/host names too generic to be identifying (CI runners, containers, defaults)
_GENERIC_LOCAL_NAMES = {"root", "user", "admin", "runner", "ubuntu", "ec2-user", "debian", "vagrant", "jenkins",
                        "build", "builder", "circleci", "travis", "gitlab-runner", "localhost", "docker", "codespace",
                        "vscode", "node", "app", "test", "guest", "nobody", "worker", "default"}
_MIN_LOCAL_LEN = 4


class TermsError(ValueError):
    """Unreadable or malformed terms file."""


def mask(s):
    """Masked form of a matched text for reports: first two characters and the length."""
    s = str(s)
    return (s[:2] + "*" * max(0, min(len(s) - 2, 6)) + f"({len(s)})") if s else ""


# ------------------------------------------------------------------ terms


def _git(root, *args):
    try:
        p = subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def main_checkout_root(root):
    """The main checkout of the repository at `root` (differs from `root` inside a git worktree), or None."""
    common = _git(root, "rev-parse", "--git-common-dir")
    if not common:
        return None
    common = common.strip()
    if not os.path.isabs(common):
        common = os.path.join(root, common)
    common = os.path.realpath(common)
    if os.path.basename(common) != ".git":
        return None
    return os.path.dirname(common)


def find_terms_file(root, explicit=None):
    """Path of the terms file, or None. An explicit path (argument or environment) must exist."""
    for cand in (explicit, os.environ.get(TERMS_ENV)):
        if cand:
            if not os.path.isfile(cand):
                raise TermsError("terms file given but not found")
            return cand
    cands = [os.path.join(root, TERMS_REL)]
    main = main_checkout_root(root)
    if main:
        cands.append(os.path.join(main, TERMS_REL))
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def load_terms(path):
    """[(index, compiled regex)] from a terms file (1-based index = position among the term lines)."""
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            t = line.strip()
            if not t or t.startswith("#"):
                continue
            idx = len(out) + 1
            try:
                if t.startswith("re:"):
                    rx = re.compile(t[3:], re.IGNORECASE)
                else:
                    rx = re.compile(re.escape(t), re.IGNORECASE)
            except re.error as e:
                raise TermsError(f"terms file entry {idx}: bad regular expression ({e})") from None
            if rx.search("") is not None:
                raise TermsError(f"terms file entry {idx} matches the empty string")
            out.append((idx, rx))
    return out


def local_identity_terms():
    """[(label, compiled regex)] for the login name and host name of this machine (read now, never stored)."""
    names = []
    try:
        names.append(("login", getpass.getuser()))
    except Exception:  # noqa: BLE001
        pass
    try:
        names.append(("host", socket.gethostname().split(".")[0]))
    except Exception:  # noqa: BLE001
        pass
    out, seen = [], set()
    for label, n in names:
        n = (n or "").strip()
        if len(n) < _MIN_LOCAL_LEN or n.lower() in _GENERIC_LOCAL_NAMES or n.lower() in seen:
            continue
        seen.add(n.lower())
        out.append((label, re.compile(re.escape(n), re.IGNORECASE)))
    return out


class Scanner:
    """Detectors for one scan. terms: list from load_terms(); local: list from local_identity_terms()."""

    def __init__(self, terms=(), local=(), identities=DEFAULT_IDENTITIES):
        self.terms = list(terms)
        self.local = list(local)
        self.identities = {(n.lower(), e.lower()) for n, e in identities}

    @staticmethod
    def _email_allowed(m):
        local, domain = m.group(0).split("@", 1)
        d = m.group(1).lower()
        return (d in _ALLOWED_EMAIL_DOMAINS or d.endswith(_ALLOWED_EMAIL_TLDS)
                or local.lower() in _ALLOWED_EMAIL_LOCALS)

    def scan_text_line(self, line):
        """[(col, detector, detail)] for one line of text."""
        hits = []
        for m in _HOME_RE.finditer(line):
            hits.append((m.start() + 1, "home_path", mask(m.group(0))))
        for m in _EMAIL_RE.finditer(line):
            if not self._email_allowed(m):
                hits.append((m.start() + 1, "email", mask(m.group(0))))
        for idx, rx in self.terms:
            for m in rx.finditer(line):
                hits.append((m.start() + 1, "term", f"term[{idx}]"))
        for label, rx in self.local:
            for m in rx.finditer(line):
                hits.append((m.start() + 1, "local_user", label))
        return hits

    def identity_allowed(self, name, email):
        return (name.lower(), email.lower()) in self.identities


# ------------------------------------------------------------------ file selection


def _excluded(relpath):
    rp = relpath.replace(os.sep, "/")
    if any(rp == p.rstrip("/") or rp.startswith(p) for p in EXCLUDED_PREFIXES):
        return True
    parts = rp.split("/")[:-1]
    for part in parts:
        if part in EXCLUDED_DIR_NAMES or any(fnmatch.fnmatch(part, g) for g in EXCLUDED_DIR_GLOBS):
            return True
    return False


def _walk(root, sub):
    out = []
    base = os.path.join(root, sub)
    if os.path.isfile(base):
        return [sub.replace(os.sep, "/")]
    for dirpath, dirnames, files in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIR_NAMES
                             and not any(fnmatch.fnmatch(d, g) for g in EXCLUDED_DIR_GLOBS))
        for fn in sorted(files):
            out.append(os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/"))
    return out


def default_files(root, artifacts=True):
    """(files, how): the git working tree (tracked + untracked, not ignored) plus artifact directories.

    Without git, every file under root except the excluded directories.
    """
    listed = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if listed is None:
        files, how = _walk(root, "."), "walk"
        files = [f[2:] if f.startswith("./") else f for f in files]
    else:
        files, how = [f for f in listed.split("\0") if f], "git"
    if artifacts:
        for d in ARTIFACT_DIRS:
            if os.path.isdir(os.path.join(root, d)):
                files += _walk(root, d)
    seen, out = set(), []
    for f in files:
        if f in seen or _excluded(f) or not os.path.isfile(os.path.join(root, f)):
            continue
        seen.add(f)
        out.append(f)
    return sorted(out), how


def _gitignore_entries(root):
    path = os.path.join(root, ".gitignore")
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            e = line.strip()
            if e and not e.startswith("#"):
                out.append(e)
    return out


def _entry_is_excluded(entry):
    e = entry.lstrip("/")
    name = e.rstrip("/")
    return (any(e == p or e.rstrip("/") == p.rstrip("/") for p in EXCLUDED_PREFIXES)
            or name in EXCLUDED_DIR_NAMES or any(fnmatch.fnmatch(name, g) for g in EXCLUDED_DIR_GLOBS))


def gitignore_mismatches(root):
    """Where the default scan selection and <root>/.gitignore disagree. Returns (unaccounted, not_ignored):

    unaccounted  .gitignore entries that are neither an artifact directory (scanned although ignored) nor a default
                 exclusion: files there would silently escape the scan;
    not_ignored  excluded prefixes and artifact directories that .gitignore does not list: files there could be
                 committed without ever being scanned (exclusions) or would be scanned twice over (artifacts).
    """
    entries = _gitignore_entries(root)
    names = {e.lstrip("/").rstrip("/") for e in entries}
    unaccounted = [e for e in entries if e.lstrip("/").rstrip("/") not in ARTIFACT_DIRS and not _entry_is_excluded(e)]
    not_ignored = [p for p in EXCLUDED_PREFIXES + tuple(d + "/" for d in ARTIFACT_DIRS) if p.rstrip("/") not in names]
    return unaccounted, not_ignored


def _is_binary(path):
    with open(path, "rb") as f:
        return b"\0" in f.read(8192)


def scan_file(scanner, root, relpath):
    """Hits in one file: [{"path", "line", "col", "detector", "detail"}]; None for a binary file."""
    full = os.path.join(root, relpath)
    if _is_binary(full):
        return None
    hits = []
    # the path itself can carry identity (a directory named after a person)
    for col, det, detail in scanner.scan_text_line(relpath):
        hits.append({"path": relpath, "line": 0, "col": col, "detector": det + "_in_path", "detail": detail})
    with open(full, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            for col, det, detail in scanner.scan_text_line(line):
                hits.append({"path": relpath, "line": i, "col": col, "detector": det, "detail": detail})
    return hits


def scan_text(scanner, label, text):
    """Hits in an in-memory text (e.g. a manifest before it is written)."""
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        for col, det, detail in scanner.scan_text_line(line):
            hits.append({"path": label, "line": i, "col": col, "detector": det, "detail": detail})
    return hits


# ------------------------------------------------------------------ git metadata


def scan_git(scanner, root):
    """Identity checks on the commits reachable from HEAD and on the repository-level git config.

    Returns (hits, info). No git or no commits: ([], {"git": False}).
    """
    hits = []
    head = _git(root, "rev-parse", "--verify", "-q", "HEAD")
    if head is None:
        return hits, {"git": False}
    log = _git(root, "log", "--format=%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B%x1e", "HEAD") or ""
    n = 0
    for rec in log.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        parts = rec.split("\x1f")
        if len(parts) < 6:
            continue
        n += 1
        sha, an, ae, cn, ce, body = parts[0], parts[1], parts[2], parts[3], parts[4], "\x1f".join(parts[5:])
        where = f"git:{sha[:12]}"
        if not scanner.identity_allowed(an, ae):
            hits.append({"path": where, "line": 0, "col": 0, "detector": "git_author", "detail": mask(an) + " " + mask(ae)})
        if not scanner.identity_allowed(cn, ce):
            hits.append({"path": where, "line": 0, "col": 0, "detector": "git_committer", "detail": mask(cn) + " " + mask(ce)})
        for i, line in enumerate(body.splitlines(), 1):
            for col, det, detail in scanner.scan_text_line(line):
                hits.append({"path": where, "line": i, "col": col, "detector": "git_message:" + det, "detail": detail})
    name = (_git(root, "config", "--local", "--get", "user.name") or "").strip()
    email = (_git(root, "config", "--local", "--get", "user.email") or "").strip()
    local_identity = bool(name or email)
    if local_identity and not scanner.identity_allowed(name, email):
        hits.append({"path": "git:config", "line": 0, "col": 0, "detector": "git_config", "detail": mask(name) + " " + mask(email)})
    return hits, {"git": True, "commits": n, "local_identity_set": local_identity}


# ------------------------------------------------------------------ entry point


def build_scanner(root, terms_file=None, require_terms=False, local=True, identities=DEFAULT_IDENTITIES):
    """(Scanner, terms file found?) with the identity terms found for `root`."""
    tf = find_terms_file(os.path.abspath(root), terms_file)
    if tf is None and require_terms:
        raise TermsError("no identity terms file found (see runtime/orgene/anon.py for the lookup order)")
    terms = load_terms(tf) if tf else []
    return Scanner(terms=terms, local=local_identity_terms() if local else (), identities=identities), tf is not None


def scan(root, paths=None, terms_file=None, require_terms=False, artifacts=True, git_meta=True, local=True,
         identities=DEFAULT_IDENTITIES, scanner=None):
    """Run the self-check. Returns a report dict; report["hits"] is empty when the scan is clean.

    paths: files or directories relative to root (default: the git working tree plus artifact directories).
    """
    root = os.path.abspath(root)
    if scanner is None:
        scanner, found = build_scanner(root, terms_file, require_terms, local, identities)
    else:
        found = bool(scanner.terms)
    terms = scanner.terms
    tf = found
    if paths:
        files = []
        for p in paths:
            p = os.path.relpath(os.path.abspath(os.path.join(root, p)), root)
            files += [f for f in _walk(root, p) if ".git/" not in f and not f.startswith(".git/")]
        files, how = sorted(set(files)), "paths"
    else:
        files, how = default_files(root, artifacts=artifacts)
    hits, n_binary = [], 0
    for f in files:
        h = scan_file(scanner, root, f)
        if h is None:
            n_binary += 1
            continue
        hits += h
    git_info = {"git": False}
    if git_meta:
        gh, git_info = scan_git(scanner, root)
        hits += gh
    return {"files_scanned": len(files) - n_binary, "binary_skipped": n_binary, "selection": how,
            "identity_terms": len(terms), "terms_file_found": tf, "local_identity_terms": len(scanner.local),
            "git": git_info, "hits": hits}


def format_hits(report, limit=200):
    lines = []
    for h in report["hits"][:limit]:
        lines.append(f"{h['path']}:{h['line']}:{h['col']}: {h['detector']} {h['detail']}")
    if len(report["hits"]) > limit:
        lines.append(f"... {len(report['hits']) - limit} more")
    return "\n".join(lines)
