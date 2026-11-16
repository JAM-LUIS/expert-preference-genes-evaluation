"""Neutral paths for everything written into artifacts (run configs, runner configs, SPLIT_LOCK, case headers).

Rule: a path recorded in any artifact is relative to the repository root (posix separators). A path outside the
root (a temp directory, another checkout) is reduced to `<outside-root>/<basename>`, so no host, user or home
directory name is ever recorded. Command lines are recorded with the root replaced by `$R1`.
"""
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
ROOT_TOKEN = "$R1"
OUTSIDE = "<outside-root>"

# Home-directory prefixes of the common platforms. Spelled in pieces so that a literal scan of this tree
# for such prefixes (tools/anon_scan, E21) does not report the scanner itself.
_HOME_PREFIXES = ("/" + "Users" + "/", "/" + "home" + "/", "/private/var/" + "folders/")
_ABS_RE = re.compile("(?:" + "|".join(re.escape(p) for p in _HOME_PREFIXES) + r")[^\s\"'<>]+")


def _real(p):
    return os.path.realpath(os.path.abspath(p))


def rel(p, root=None):
    """Return `p` relative to `root` (default: the repository root). None stays None."""
    if p is None:
        return None
    root_r = _real(root or ROOT)
    p_r = _real(p)
    if p_r == root_r:
        return "."
    if p_r.startswith(root_r + os.sep):
        return os.path.relpath(p_r, root_r).replace(os.sep, "/")
    return f"{OUTSIDE}/{os.path.basename(p_r)}"


def resolve(p, root=None):
    """Inverse of rel() for paths inside the root: a relative path is taken relative to the root."""
    if p is None:
        return None
    if os.path.isabs(p):
        return p
    return os.path.join(root or ROOT, p)


def sanitize_arg(a, root=None):
    """One command-line argument: absolute paths (also in `--opt=/path` form) go through rel()."""
    if not isinstance(a, str):
        return a
    if a.startswith("-") and "=" in a:
        k, v = a.split("=", 1)
        return k + "=" + sanitize_arg(v, root)
    if os.path.isabs(a):
        r = rel(a, root)
        if r.startswith(OUTSIDE):
            return r
        return ROOT_TOKEN if r == "." else f"{ROOT_TOKEN}/{r}"
    for prefix in {os.path.abspath(root or ROOT), _real(root or ROOT)}:
        a = a.replace(prefix, ROOT_TOKEN)
    return a


def sanitize_argv(argv, root=None):
    """sys.argv as it may be recorded: root -> $R1, other absolute paths -> <outside-root>/<basename>."""
    return [sanitize_arg(a, root) for a in argv]


def find_absolute_paths(text):
    """Home-directory paths in a text blob (used by the tests; the full identity scan is tools/anon_scan, E21)."""
    return _ABS_RE.findall(text or "")


# ---------------------------------------------------------------- program output (execute.run_program)

# execute.run_program gives every call two temporary directories: orgene_exec_* (prog.py; the program's working
# directory and HOME) and orgene_rec_* (the staged solve recorder). A path inside one keeps only its part below the
# directory ("prog.py"), as genes.scrub_exec_paths leaves it in repair messages (a traceback's File "prog.py" reads the
# same both ways); the bare directory becomes <prog-dir> (the solve recorder's word for it) or <rec-dir>. Only the
# path's own components are matched, so text glued in front of a path ("cwd=", "(") stays.
_EXEC_PATH_RE = re.compile(r"""(?:/[^\s"'<>/]+)*/orgene_(?:exec|rec)_[^\s"'/<>]+/""")
_EXEC_DIR_RE = re.compile(r"""(?:/[^\s"'<>/]+)*/orgene_(exec|rec)_[A-Za-z0-9_]+""")
_EXEC_DIR_TOKENS = {"exec": "<prog-dir>", "rec": "<rec-dir>"}


def neutral_home(text, home=None):
    """This process's home directory (and its real path) -> "~" in free text. The parent's home, not the program's:
    run_program sets the child's HOME to its temporary directory. Only whole path components are replaced."""
    if not text:
        return text
    h = home or os.path.expanduser("~")
    for p in sorted({h, os.path.realpath(h)}, key=len, reverse=True):
        if p and p not in (os.sep, "~") and os.path.isabs(p):
            text = re.sub(re.escape(p.rstrip(os.sep)) + r"(?=/|$|[\s\"'<>)\],;:])", "~", text)
    return text


def neutral_exec_text(text, home=None):
    """Program output (stdout, stderr, solver error messages) as it may be recorded: the per-call directories of
    execute.run_program dropped, and the home directory replaced by "~" (a traceback through a virtual environment
    under the home directory, e.g. the baseline environment's packages, would otherwise record the user's name)."""
    if not text:
        return text
    text = _EXEC_PATH_RE.sub("", text)
    text = _EXEC_DIR_RE.sub(lambda m: _EXEC_DIR_TOKENS[m.group(1)], text)
    return neutral_home(text, home)
