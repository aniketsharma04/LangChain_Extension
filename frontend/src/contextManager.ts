// ==============================================================
// contextManager.ts
//
// Phase 3: Active file context injection.
//
// Reads the current editor state and builds a structured
// FileContext object that gets sent to the backend with every
// chat message. The backend injects it into the agent prompt
// so the LLM is always aware of what the developer is looking at.
//
// Priority order (what gets sent):
//   1. Selected text only  → if user has a selection
//   2. Visible range       → if file is too large (> MAX_LINES)
//   3. Full file content   → if file is small enough
// ==============================================================

import * as vscode from 'vscode';

// Max lines to send as full file before switching to visible-range mode
const MAX_FULL_FILE_LINES = 500;

// Hard cap on characters sent (avoids blowing up the LLM context window)
const MAX_CHARS = 40_000;

export interface FileContext {
    // What was sent to the backend
    fileName: string;
    filePath: string;           // relative to workspace root
    language: string;
    totalLines: number;
    content: string;            // the actual code sent

    // How it was captured
    captureMode: 'selection' | 'full_file' | 'visible_range';
    selectionStart?: number;    // 1-based line numbers
    selectionEnd?: number;
    visibleStart?: number;
    visibleEnd?: number;
    cursorLine?: number;

    // Workspace info
    workspacePath?: string;
    workspaceName?: string;
}

export interface ContextSummary {
    // What to show in the UI context pill
    label: string;              // e.g. "server.py (full)" or "agent.py:12-45 (selection)"
    fileName: string;
    captureMode: FileContext['captureMode'];
    lineCount: number;
    truncated: boolean;
}

export class ContextManager {

    // ── Build context from the active editor ──────────────────────────────────
    static capture(): { context: FileContext; summary: ContextSummary } | null {
        const editor = vscode.window.activeTextEditor;
        if (!editor) { return null; }

        const doc         = editor.document;
        const totalLines  = doc.lineCount;
        const language    = doc.languageId;
        const workspaceFolders = vscode.workspace.workspaceFolders;
        const workspacePath    = workspaceFolders?.[0]?.uri.fsPath;
        const workspaceName    = workspaceFolders?.[0]?.name;

        // Relative file path
        const filePath = workspacePath
            ? vscode.workspace.asRelativePath(doc.uri)
            : doc.uri.fsPath;
        const fileName = doc.uri.path.split('/').pop() ?? filePath;

        // ── Decide capture mode ───────────────────────────────────────────────

        const selection   = editor.selection;
        const hasSelection = !selection.isEmpty;

        let content: string;
        let captureMode: FileContext['captureMode'];
        let selectionStart: number | undefined;
        let selectionEnd: number | undefined;
        let visibleStart: number | undefined;
        let visibleEnd: number | undefined;

        if (hasSelection) {
            // Mode 1: User has selected text — send exactly that
            content = doc.getText(selection);
            captureMode = 'selection';
            selectionStart = selection.start.line + 1;
            selectionEnd   = selection.end.line + 1;

        } else if (totalLines <= MAX_FULL_FILE_LINES) {
            // Mode 2: Small file — send the whole thing
            content = doc.getText();
            captureMode = 'full_file';

        } else {
            // Mode 3: Large file — send only what's visible in the viewport
            // plus some buffer above/below for context
            const visibleRanges = editor.visibleRanges;
            if (visibleRanges.length === 0) {
                content = doc.getText();
                captureMode = 'full_file';
            } else {
                const first = visibleRanges[0];
                const last  = visibleRanges[visibleRanges.length - 1];

                // Add 30-line buffer above and below visible range
                const bufferLines = 30;
                const startLine = Math.max(0, first.start.line - bufferLines);
                const endLine   = Math.min(totalLines - 1, last.end.line + bufferLines);

                const range = new vscode.Range(startLine, 0, endLine, Number.MAX_SAFE_INTEGER);
                content = doc.getText(range);
                captureMode = 'visible_range';
                visibleStart = startLine + 1;
                visibleEnd   = endLine + 1;
            }
        }

        // ── Hard truncate if content still too large ──────────────────────────
        let truncated = false;
        if (content.length > MAX_CHARS) {
            content = content.slice(0, MAX_CHARS) + '\n... [truncated]';
            truncated = true;
        }

        const cursorLine = editor.selection.active.line + 1;
        const contentLines = content.split('\n').length;

        // ── Build context object ──────────────────────────────────────────────
        const context: FileContext = {
            fileName,
            filePath,
            language,
            totalLines,
            content,
            captureMode,
            selectionStart,
            selectionEnd,
            visibleStart,
            visibleEnd,
            cursorLine,
            workspacePath,
            workspaceName,
        };

        // ── Build summary for UI pill ─────────────────────────────────────────
        let label: string;
        if (captureMode === 'selection') {
            label = `${fileName}:${selectionStart}-${selectionEnd} (selection)`;
        } else if (captureMode === 'visible_range') {
            label = `${fileName}:${visibleStart}-${visibleEnd} (visible)`;
        } else {
            label = `${fileName} (full file)`;
        }
        if (truncated) { label += ' [truncated]'; }

        const summary: ContextSummary = {
            label,
            fileName,
            captureMode,
            lineCount: contentLines,
            truncated,
        };

        return { context, summary };
    }

    // ── Format context into a prompt prefix ──────────────────────────────────
    // This is what actually gets prepended to the user's message
    static buildPromptPrefix(ctx: FileContext): string {
        const lines: string[] = [];

        lines.push(`## Active File Context`);
        lines.push(`**File:** \`${ctx.filePath}\``);
        lines.push(`**Language:** ${ctx.language}`);
        lines.push(`**Total lines:** ${ctx.totalLines}`);

        if (ctx.captureMode === 'selection') {
            lines.push(`**Showing:** Selected lines ${ctx.selectionStart}–${ctx.selectionEnd}`);
        } else if (ctx.captureMode === 'visible_range') {
            lines.push(`**Showing:** Visible range lines ${ctx.visibleStart}–${ctx.visibleEnd} (of ${ctx.totalLines})`);
        } else {
            lines.push(`**Showing:** Full file (${ctx.totalLines} lines)`);
        }

        if (ctx.cursorLine) {
            lines.push(`**Cursor at:** line ${ctx.cursorLine}`);
        }

        lines.push('');
        lines.push(`\`\`\`${ctx.language}`);
        lines.push(ctx.content);
        lines.push('```');

        return lines.join('\n');
    }
}
