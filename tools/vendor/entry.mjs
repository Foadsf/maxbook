// Everything the Maxbook front end uses from ProseMirror and markdown-it,
// bundled into one ES module so the app needs no build step at run time.
export * as model from "prosemirror-model";
export * as state from "prosemirror-state";
export * as view from "prosemirror-view";
export * as transform from "prosemirror-transform";
export * as commands from "prosemirror-commands";
export * as keymap from "prosemirror-keymap";
export * as history from "prosemirror-history";
export * as inputrules from "prosemirror-inputrules";
export * as schemaList from "prosemirror-schema-list";
export * as dropcursor from "prosemirror-dropcursor";
export * as gapcursor from "prosemirror-gapcursor";
export * as collab from "prosemirror-collab";
export * as markdown from "prosemirror-markdown";
export { default as MarkdownIt } from "markdown-it";
