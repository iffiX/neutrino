package main

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// writeEvent writes one event to standard error: the time, the verb, and
// each key=value pair, a value with a space or a quote quoted.
func writeEvent(verb string, pairs ...string) {
	var line strings.Builder
	line.WriteString(time.Now().UTC().Format(time.RFC3339))
	line.WriteString(" ")
	line.WriteString(verb)
	for index := 0; index+1 < len(pairs); index += 2 {
		value := pairs[index+1]
		if value == "" || strings.ContainsAny(value, " \"=\t\r\n") {
			value = strconv.Quote(value)
		}
		line.WriteString(" ")
		line.WriteString(pairs[index])
		line.WriteString("=")
		line.WriteString(value)
	}
	line.WriteString("\n")
	fmt.Fprint(os.Stderr, line.String())
}
