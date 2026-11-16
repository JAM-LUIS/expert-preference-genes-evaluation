"""A backend that answers without a server, for the self-test and the tests (E06). Never used for study runs:
make_backend() does not know it.

CannedBackend is an Ollama backend (same request body, same options check, same request_sha256, same call record)
whose transport is replaced:
  script mode  answer(messages, body) -> content; every answer is also stored under the request's sha256 in `table`
  replay mode  table {request_sha256: content} only; a request that is not in the table fails (recorded in `misses`),
               so two executions that must send identical requests can be compared
Token counts and durations in the response are deterministic functions of the request and the answer.
"""
import hashlib

from .base import canonical_json, request_sha256
from .ollama import OllamaBackend

CANNED_DIGEST = hashlib.sha256(b"orgene canned backend").hexdigest()


class CannedMiss(KeyError):
    """Replay mode: the request is not in the table."""


class CannedBackend(OllamaBackend):
    def __init__(self, model="canned:1", *, answer=None, table=None, digest=CANNED_DIGEST, fail=None, **kw):
        kw.setdefault("retry_sleep", 0)
        kw.setdefault("max_attempts", 1)
        super().__init__(model, host="http://canned.invalid", **kw)
        if answer is None and table is None:
            raise ValueError("CannedBackend needs answer= (script) or table= (replay)")
        self.answer = answer
        self.table = dict(table) if table is not None else {}
        self.replay = answer is None
        self.canned_digest = digest
        self.fail = fail            # optional fail(body) -> str: an error text makes that attempt fail
        self.sent = []              # request_sha256 of every body that reached the transport, in order
        self.misses = []

    def _lookup_identity(self):
        return {"backend": self.kind, "host": "canned", "ollama_version": "canned", "model": self.model,
                "digest": self.canned_digest, "size_bytes": None, "modified_at": None, "details": None,
                "capabilities": ["completion"], "parameters_from_modelfile": None, "template_sha256": None}

    def loaded_models(self):
        return []

    def _send_once(self, body):
        h = request_sha256(body)
        self.sent.append(h)
        if self.fail is not None:
            err = self.fail(body)
            if err:
                raise RuntimeError(err)
        if self.replay:
            if h not in self.table:
                self.misses.append(h)
                raise CannedMiss(f"request {h[:12]} is not in the replay table")
            content = self.table[h]
        else:
            content = self.answer(body["messages"], body)
            self.table[h] = content
        n_in = len(canonical_json(body["messages"])) // 4
        n_out = max(1, len(content) // 4)
        return {"model": body["model"], "created_at": "2026-01-01T00:00:00Z",
                "message": {"role": "assistant", "content": content}, "done": True, "done_reason": "stop",
                "prompt_eval_count": n_in, "eval_count": n_out, "load_duration": 0,
                "prompt_eval_duration": n_in * 1000, "eval_duration": n_out * 1000,
                "total_duration": 1_000_000_000 + (n_in + n_out) * 1000}, body
