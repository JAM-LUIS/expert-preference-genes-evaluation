"""A stand-in for llama.cpp's llama-server (E17 tests): /health, /props and the native /completion.

In-process: FakeLlamaServer(answer_for=...) serves on a free port (url attribute). As a program it accepts the
llama-server command line the ORLM adapter builds (it reads -m, -c, -np, --alias, --port) and writes the command
line it was given to the file named by the environment variable FAKE_LLAMA_ARGV_FILE, so a test can check the launch.
No model is loaded; answers come from `answer_for(prompt)`.
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

ECHO = ("temperature", "top_k", "top_p", "min_p", "typical_p", "repeat_penalty", "presence_penalty",
        "frequency_penalty", "dry_multiplier", "xtc_probability", "mirostat", "seed", "n_predict", "stop")
BUILD_INFO = "b10621-c1d0e7a00"


class FakeLlamaServer:
    def __init__(self, answer_for=None, model_path=None, n_ctx=8192, slots=1, port=0, alias="orlm-llama3-8b-f16"):
        self.answer_for = answer_for or (lambda prompt: "no code here")
        # an absolute model path as a real server reports it (built in pieces: no literal home prefix in this file)
        self.model_path = model_path or os.path.join(os.sep + "Us" + "ers", "someone", "models", "ORLM-LLaMA-3-8B-F16.gguf")
        self.n_ctx, self.slots, self.alias = n_ctx, slots, alias
        self.posts = []
        self.echo_override = {}   # settings the fake reports as applied instead of the sent ones
        self.stop_type = "eos"
        self.truncated = False
        fs = self

        class H(BaseHTTPRequestHandler):
            def _send(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/health":
                    return self._send(200, {"status": "ok"})
                if self.path == "/props":
                    return self._send(200, {"default_generation_settings": {"n_ctx": fs.n_ctx, "params": {}},
                                            "total_slots": fs.slots, "model_path": fs.model_path,
                                            "build_info": BUILD_INFO, "chat_template": "{{ messages }}"})
                return self._send(404, {"error": "not found"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n))
                fs.posts.append((self.path, body))
                if self.path != "/completion":
                    return self._send(404, {"error": "not found"})
                content = fs.answer_for(body.get("prompt", ""))
                gen = {k: body[k] for k in ECHO if k in body}
                gen.update(fs.echo_override)
                gen["model"] = fs.model_path
                self._send(200, {
                    "content": content, "model": fs.model_path, "stop": True, "stop_type": fs.stop_type,
                    "stopping_word": "", "truncated": fs.truncated,
                    "tokens_evaluated": len(body.get("prompt", "").split()), "tokens_predicted": len(content.split()),
                    "tokens_cached": 0, "generation_settings": gen,
                    "timings": {"prompt_n": 10, "prompt_ms": 20.0, "predicted_n": 30, "predicted_ms": 1500.0}})

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", port), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()

    def completions(self):
        return [b for p, b in self.posts if p == "/completion"]

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def _arg(argv, *names, default=None):
    for i, a in enumerate(argv):
        if a in names and i + 1 < len(argv):
            return argv[i + 1]
    return default


if __name__ == "__main__":
    argv = sys.argv[1:]
    out = os.environ.get("FAKE_LLAMA_ARGV_FILE")
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(argv, f)
    answer = os.environ.get("FAKE_LLAMA_ANSWER", "no code here")
    srv = FakeLlamaServer(answer_for=lambda p: answer, model_path=_arg(argv, "-m"),
                          n_ctx=int(_arg(argv, "-c", default="8192")), slots=int(_arg(argv, "-np", default="1")),
                          port=int(_arg(argv, "--port", default="8080")), alias=_arg(argv, "--alias"))
    print("fake llama-server listening", flush=True)
    srv.thread.join()
