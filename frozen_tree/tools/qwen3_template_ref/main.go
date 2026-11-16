// Reference renderer for the Ollama chat template of qwen3 (E09).
//
// Executes an Ollama chat template with Go's text/template the way Ollama's template.Execute does for a
// /api/chat request without tools or images: system messages are collected into .System (joined by "\n\n"),
// consecutive messages of one role are merged with "\n\n" (tool messages excepted), and .Think / .IsThinkSet
// follow the request's "think" field. The Python port (runtime/orgene/tokcount.py, render_qwen3) is tested
// against the output of this program (runtime/tests/fixtures/qwen3_template_go_reference.json).
//
//	go run tools/qwen3_template_ref/main.go <template file> < cases.json > reference.json
//
// cases.json: [{"name": ..., "think": true|false|null, "messages": [{"role", "content", "thinking"}]}]
// The template file is the Ollama template blob (sha256 ae370d88...; a copy is runtime/tests/fixtures/
// qwen3_ollama_template.gotmpl). Standard library only; no model is loaded.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"runtime"
	"strings"
	"text/template"
)

type Message struct {
	Role      string `json:"role"`
	Content   string `json:"content"`
	Thinking  string `json:"thinking,omitempty"`
	ToolCalls []any  `json:"-"`
}

type Case struct {
	Name     string    `json:"name"`
	Think    *bool     `json:"think"`
	Messages []Message `json:"messages"`
	Prompt   string    `json:"prompt"`
}

type Reference struct {
	TemplateSHA256 string `json:"template_sha256"`
	GoVersion      string `json:"go_version"`
	Generator      string `json:"generator"`
	Cases          []Case `json:"cases"`
}

// collate mirrors Ollama's template.collate for messages without images.
func collate(msgs []Message) (string, []*Message) {
	var system []string
	var collated []*Message
	for i := range msgs {
		if msgs[i].Role == "system" {
			system = append(system, msgs[i].Content)
		}
		if len(collated) > 0 && collated[len(collated)-1].Role == msgs[i].Role && msgs[i].Role != "tool" {
			collated[len(collated)-1].Content += "\n\n" + msgs[i].Content
		} else {
			collated = append(collated, &msgs[i])
		}
	}
	return strings.Join(system, "\n\n"), collated
}

func main() {
	src, err := os.ReadFile(os.Args[1])
	if err != nil {
		panic(err)
	}
	sum := sha256.Sum256(src)
	tmpl := template.Must(template.New("t").Parse(string(src)))
	var cases []Case
	if err := json.NewDecoder(os.Stdin).Decode(&cases); err != nil {
		panic(err)
	}
	ref := Reference{TemplateSHA256: hex.EncodeToString(sum[:]), GoVersion: runtime.Version(),
		Generator: "tools/qwen3_template_ref/main.go"}
	for _, c := range cases {
		work := append([]Message(nil), c.Messages...) // collate merges in place; keep the input for the output
		system, messages := collate(work)
		think, isSet := false, false
		if c.Think != nil {
			think, isSet = *c.Think, true
		}
		var tools []any
		var b strings.Builder
		if err := tmpl.Execute(&b, map[string]any{
			"System": system, "Messages": messages, "Tools": tools, "Response": "",
			"Think": think, "ThinkLevel": "", "IsThinkSet": isSet,
		}); err != nil {
			panic(err)
		}
		c.Prompt = b.String()
		ref.Cases = append(ref.Cases, c)
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", " ")
	if err := enc.Encode(ref); err != nil {
		panic(err)
	}
}
