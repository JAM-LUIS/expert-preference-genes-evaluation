// Reference renderer for the Ollama chat template of gpt-oss:20b (E23).
//
// Executes the template blob (sha256 fa6710a9...; a copy is runtime/tests/fixtures/gptoss_ollama_template.gotmpl)
// with Go's text/template the way Ollama's template.Execute does for a /api/chat request without tools or images:
// system messages are collected into .System (joined by "\n\n"), consecutive messages of one role are merged with
// "\n\n" (tool messages excepted), and the request's "think" field sets .IsThinkSet, .Think and .ThinkLevel:
//
//	absent -> IsThinkSet false, Think false, ThinkLevel ""
//	true   -> IsThinkSet true,  Think true,  ThinkLevel ""
//	false  -> IsThinkSet true,  Think false, ThinkLevel ""
//	"low"  -> IsThinkSet true,  Think true,  ThinkLevel "low"   (likewise "medium", "high")
//
// The template writes the server's local date ({{ currentDate }}, YYYY-MM-DD); here each case gives the date.
// The Python port (runtime/orgene/tokcount_harmony.py, render_gptoss) is tested against the output of this program
// (runtime/tests/fixtures/gptoss_template_go_reference.json).
//
//	go run tools/gptoss_template_ref/main.go <template file> < cases.json > reference.json
//
// cases.json: [{"name", "think": null|true|false|"low"|..., "date": "YYYY-MM-DD",
//
//	"messages": [{"role", "content", "thinking"}]}]
//
// Standard library only; no model is loaded.
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

type ToolCallFunction struct {
	Name      string
	Arguments string
}

type ToolCall struct {
	Function ToolCallFunction
}

type Message struct {
	Role      string     `json:"role"`
	Content   string     `json:"content"`
	Thinking  string     `json:"thinking,omitempty"`
	ToolName  string     `json:"-"`
	ToolCalls []ToolCall `json:"-"`
}

type Case struct {
	Name     string    `json:"name"`
	Think    any       `json:"think"`
	Date     string    `json:"date"`
	Messages []Message `json:"messages"`
	Prompt   string    `json:"prompt"`
}

type Reference struct {
	TemplateSHA256 string `json:"template_sha256"`
	GoVersion      string `json:"go_version"`
	Generator      string `json:"generator"`
	ThinkMapping   string `json:"think_mapping"`
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
	date := ""
	funcs := template.FuncMap{
		"currentDate":      func(args ...string) string { return date },
		"toTypeScriptType": func(v any) string { return "any" },
		"json": func(v any) string {
			b, _ := json.Marshal(v)
			return string(b)
		},
	}
	tmpl := template.Must(template.New("t").Funcs(funcs).Parse(string(src)))
	var cases []Case
	if err := json.NewDecoder(os.Stdin).Decode(&cases); err != nil {
		panic(err)
	}
	ref := Reference{TemplateSHA256: hex.EncodeToString(sum[:]), GoVersion: runtime.Version(),
		Generator:    "tools/gptoss_template_ref/main.go",
		ThinkMapping: "absent: unset; true/false: set, Think=value, ThinkLevel empty; level string: set, Think true, ThinkLevel=value"}
	for _, c := range cases {
		work := append([]Message(nil), c.Messages...) // collate merges in place; keep the input for the output
		system, messages := collate(work)
		think, isSet, level := false, false, ""
		switch v := c.Think.(type) {
		case nil:
		case bool:
			think, isSet = v, true
		case string:
			think, isSet, level = true, true, v
		default:
			panic("think must be null, a boolean or a string")
		}
		date = c.Date
		var tools []any
		var b strings.Builder
		if err := tmpl.Execute(&b, map[string]any{
			"System": system, "Messages": messages, "Tools": tools, "Response": "",
			"Think": think, "ThinkLevel": level, "IsThinkSet": isSet,
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
