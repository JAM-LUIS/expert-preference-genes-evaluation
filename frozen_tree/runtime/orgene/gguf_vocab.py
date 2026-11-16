"""Tokenizer-only GGUF files for llama-tokenize (E23). Standard library only.

Why: llama.cpp's `llama-tokenize` (the local counter of E09) refuses Ollama's gpt-oss weights blob: the blob names its
architecture 'gptoss', llama.cpp knows it as 'gpt-oss', and --override-kv does not reach the architecture key. The
blob also declares tokenizer.ggml.pre = 'default'. Ollama 0.33 itself serves gpt-oss through its bundled llama-server,
which on load logs "handle_gptoss: detected Ollama-format gpt-oss GGUF; applying compatibility fixes" and then runs
with general.architecture = 'gpt-oss' and tokenizer.ggml.pre = 'gpt-4o' over the blob's own vocabulary and merges.

`derive_vocab_only` writes the same fix into a small GGUF that holds only the tokenizer: the blob's `tokenizer.*`
key/value pairs byte for byte (vocabulary, token types, merges, scores, special token ids, BOS/EOS flags), with
tokenizer.ggml.pre replaced and general.architecture added. No tensor is copied. llama-tokenize loads such a file
with a tokenizer-only load, so it tokenizes with the vocabulary the server uses. The output bytes depend only on the
blob's tokenizer pairs and the recipe, so the file's sha256 can be pinned.

Reading uses mmap and touches only the header of the weights file (a few MB of a 13 GB blob).
"""
import hashlib
import mmap
import os
import struct
import tempfile

MAGIC = b"GGUF"
ALIGNMENT = 32  # GGUF default (general.alignment is not set in the files this module writes)
# GGUF value types
T_UINT8, T_INT8, T_UINT16, T_INT16, T_UINT32, T_INT32, T_FLOAT32, T_BOOL, T_STRING, T_ARRAY, T_UINT64, T_INT64, \
    T_FLOAT64 = range(13)
_SCALAR = {T_UINT8: "<B", T_INT8: "<b", T_UINT16: "<H", T_INT16: "<h", T_UINT32: "<I", T_INT32: "<i",
           T_FLOAT32: "<f", T_BOOL: "<?", T_UINT64: "<Q", T_INT64: "<q", T_FLOAT64: "<d"}
MAX_KV = 1 << 16          # sanity limits for a header read from an untrusted file
MAX_STRING = 1 << 24
MAX_ARRAY = 1 << 26


class GGUFError(ValueError):
    """Not a GGUF file, or a header this module cannot read."""


class _View:
    """Bounds-checked little-endian reads from a buffer (bytes or mmap)."""

    def __init__(self, buf):
        self.buf, self.pos, self.n = buf, 0, len(buf)

    def take(self, k):
        if k < 0 or self.pos + k > self.n:
            raise GGUFError("truncated GGUF header")
        b = self.buf[self.pos:self.pos + k]
        self.pos += k
        return b

    def unpack(self, fmt):
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))[0]

    def string(self):
        n = self.unpack("<Q")
        if n > MAX_STRING:
            raise GGUFError("string too long in GGUF header")
        return bytes(self.take(n))


def _skip_value(v, vtype, decode):
    """Read one value of `vtype` at v.pos; return it decoded (or None when decode is False)."""
    if vtype in _SCALAR:
        x = v.unpack(_SCALAR[vtype])
        return x if decode else None
    if vtype == T_STRING:
        s = v.string()
        return s.decode("utf-8") if decode else None
    if vtype == T_ARRAY:
        etype, count = v.unpack("<I"), v.unpack("<Q")
        if count > MAX_ARRAY:
            raise GGUFError("array too long in GGUF header")
        if etype in _SCALAR:
            size = struct.calcsize(_SCALAR[etype])
            raw = v.take(size * count)
            return list(struct.unpack("<%d%s" % (count, _SCALAR[etype][1]), raw)) if decode else None
        out = [] if decode else None
        for _ in range(count):
            x = _skip_value(v, etype, decode)
            if decode:
                out.append(x)
        return out
    raise GGUFError(f"unknown GGUF value type {vtype}")


def read_kv(path, decode=(), with_raw=True):
    """The metadata of a GGUF file (v2 or v3), in file order.

    Returns {"version", "n_tensors", "pairs": [{"key", "type", "raw"?, "value"?}]}: `raw` is the exact encoding of the
    pair (key, type and value bytes) when with_raw; `value` is the decoded value for keys in `decode` (a key, or "*"
    for all). Only the header is read."""
    with open(path, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        if size < 24:
            raise GGUFError("file too small for a GGUF header")
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            return _parse(mm, decode, with_raw)


def parse_kv_bytes(data, decode=(), with_raw=True):
    """read_kv for bytes already in memory (tests, small files)."""
    return _parse(data, decode, with_raw)


def _parse(buf, decode, with_raw):
    v = _View(buf)
    if bytes(v.take(4)) != MAGIC:
        raise GGUFError("not a GGUF file (magic)")
    version = v.unpack("<I")
    if version not in (2, 3):
        raise GGUFError(f"GGUF version {version} is not supported")
    n_tensors, n_kv = v.unpack("<Q"), v.unpack("<Q")
    if n_kv > MAX_KV:
        raise GGUFError("too many metadata pairs")
    pairs = []
    for _ in range(n_kv):
        start = v.pos
        key = v.string().decode("utf-8")
        vtype = v.unpack("<I")
        want = "*" in decode or key in decode
        val = _skip_value(v, vtype, want)
        p = {"key": key, "type": vtype}
        if with_raw:
            p["raw"] = bytes(buf[start:v.pos])
        if want:
            p["value"] = val
        pairs.append(p)
    keys = [p["key"] for p in pairs]
    if len(keys) != len(set(keys)):
        raise GGUFError("duplicate metadata keys")
    return {"version": version, "n_tensors": n_tensors, "pairs": pairs}


def kv_string(key, value):
    """Encoding of one string-valued pair."""
    kb, vb = key.encode("utf-8"), value.encode("utf-8")
    return struct.pack("<Q", len(kb)) + kb + struct.pack("<I", T_STRING) + struct.pack("<Q", len(vb)) + vb


def gguf_bytes(pairs_raw, version=3):
    """A GGUF file with the given encoded pairs and no tensors, padded to the default alignment."""
    body = MAGIC + struct.pack("<I", version) + struct.pack("<Q", 0) + struct.pack("<Q", len(pairs_raw)) + b"".join(pairs_raw)
    return body + b"\x00" * ((-len(body)) % ALIGNMENT)


def vocab_only_bytes(header, architecture, overrides):
    """Bytes of a tokenizer-only GGUF: general.architecture = `architecture` first, then every `tokenizer.*` pair of
    `header` (read_kv output) in file order, byte for byte, except keys in `overrides` (string values), which are
    re-encoded in place. An override key the source does not have is refused (the recipe would silently differ)."""
    tok = [p for p in header["pairs"] if p["key"].startswith("tokenizer.")]
    if not tok:
        raise GGUFError("the file has no tokenizer.* metadata")
    have = {p["key"]: p for p in tok}
    missing = sorted(k for k in overrides if k not in have)
    if missing:
        raise GGUFError(f"override key(s) not in the source: {missing}")
    for k in overrides:
        if have[k]["type"] != T_STRING:
            raise GGUFError(f"override key {k} is not a string in the source")
    raw = [kv_string("general.architecture", architecture)]
    raw += [kv_string(p["key"], overrides[p["key"]]) if p["key"] in overrides else p["raw"] for p in tok]
    return gguf_bytes(raw, version=header["version"])


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def write_atomic(path, data):
    """Write `data` to `path` through a temporary file in the same directory (no partial file is ever visible)."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
