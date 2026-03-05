// ==============================================================
// toolsProvider.ts
//
// Phase 2: Explicit tool invocation layer.
//
// When the user right-clicks on code and picks "Generate Tests"
// (or any other tool), this provider:
//   1. Reads selected code + language from the active editor
//   2. Calls the backend /api/execute with the tool name
//   3. Streams the result back into the chat panel
//
// The AGENT (OpenClaw orchestrator) handles everything else:
//   - Intent parsing
//   - Tool selection (if taskType = "auto")
//   - Execution
//   - Result formatting
// ==============================================================

import * as vscode from 'vscode';
import { BackendClient } from './backendClient';
import { OpenClawChatViewProvider } from './chatViewProvider';

// All builtin tools that exist in agent_engine.py BUILTIN_TOOL_PROMPTS
export const BUILTIN_TOOLS = [
    { name: 'generate_tests',       label: 'Generate Tests',        icon: '🧪', description: 'Generate unit tests with edge cases' },
    { name: 'review_code',          label: 'Review Code',           icon: '🔍', description: 'Review for bugs, style, best practices' },
    { name: 'find_bugs',            label: 'Find Bugs',             icon: '🐛', description: 'Identify bugs and logic errors' },
    { name: 'explain_code',         label: 'Explain Code',          icon: '📖', description: 'Explain in plain language' },
    { name: 'refactor_code',        label: 'Refactor Code',         icon: '♻️',  description: 'Improve readability and performance' },
    { name: 'generate_docs',        label: 'Generate Docs',         icon: '📝', description: 'Generate JSDoc/docstrings' },
    { name: 'security_analysis',    label: 'Security Analysis',     icon: '🔒', description: 'Find OWASP vulnerabilities' },
    { name: 'optimize_performance', label: 'Optimize Performance',  icon: '⚡', description: 'Identify bottlenecks' },
    { name: 'analyze_complexity',   label: 'Analyze Complexity',    icon: '📊', description: 'Cyclomatic + Big-O complexity' },
    { name: 'translate_code',       label: 'Translate Code',        icon: '🔄', description: 'Translate to another language' },
] as const;

export type BuiltinToolName = typeof BUILTIN_TOOLS[number]['name'];

export interface ToolExecutionContext {
    code: string;
    language: string;
    filePath: string;
    workspacePath?: string;
    provider?: string;
    model?: string;
    // for translate_code
    targetLanguage?: string;
}

export class ToolsProvider {
    constructor(
        private readonly backendClient: BackendClient,
        private readonly chatProvider: OpenClawChatViewProvider,
    ) {}

    // ── Main entry: run a named builtin tool ──────────────────────────────────
    async runTool(toolName: BuiltinToolName | string, ctx: ToolExecutionContext): Promise<void> {
        const config = vscode.workspace.getConfiguration('openclaw');
        const provider = ctx.provider ?? config.get<string>('defaultProvider', 'openai');
        const model    = ctx.model    ?? config.get<string>('defaultModel', '');

        const toolInfo = BUILTIN_TOOLS.find(t => t.name === toolName);
        const label    = toolInfo?.label ?? toolName;

        // Push user message into chat so user sees what triggered this
        const userMsg = `${toolInfo?.icon ?? '🔧'} **${label}** on \`${ctx.filePath || 'selected code'}\``;
        this.chatProvider.pushUserMessage(userMsg);
        this.chatProvider.startAssistantMessage();

        try {
            const result = await this.backendClient.executeTool({
                taskType: 'tool',
                toolName,
                toolArgs: {
                    code: ctx.code,
                    language: ctx.language,
                    targetLanguage: ctx.targetLanguage,
                },
                context: {
                    filePath: ctx.filePath,
                    language: ctx.language,
                    workspacePath: ctx.workspacePath,
                },
                llmProvider: provider,
                llmModel: model || undefined,
            });

            if (result.error) {
                this.chatProvider.pushError(result.error);
            } else {
                this.chatProvider.pushFullResponse(result.output, {
                    provider: result.provider,
                    model: result.model,
                    durationMs: result.durationMs,
                    toolName: result.toolName,
                });
            }
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            this.chatProvider.pushError(`Tool execution failed: ${msg}`);
        }
    }

    // ── Run from active editor (reads selection automatically) ────────────────
    async runFromEditor(toolName: BuiltinToolName | string): Promise<void> {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            vscode.window.showWarningMessage('OpenClaw: No active editor. Open a file first.');
            return;
        }

        const selection = editor.selection;
        const code = editor.document.getText(
            selection.isEmpty ? undefined : selection
        );

        if (!code.trim()) {
            vscode.window.showWarningMessage('OpenClaw: No code selected or file is empty.');
            return;
        }

        // For translate_code — ask target language
        let targetLanguage: string | undefined;
        if (toolName === 'translate_code') {
            targetLanguage = await vscode.window.showInputBox({
                prompt: 'Translate to which language?',
                placeHolder: 'e.g. Python, TypeScript, Go, Rust...',
            });
            if (!targetLanguage) { return; }
        }

        const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;

        await this.runTool(toolName as BuiltinToolName, {
            code,
            language: editor.document.languageId,
            filePath: vscode.workspace.asRelativePath(editor.document.uri),
            workspacePath,
            targetLanguage,
        });

        // Focus the chat panel so user sees the result
        vscode.commands.executeCommand('openclawChatView.focus');
    }

    // ── Quick-pick tool selector (shows all tools in a menu) ──────────────────
    async showToolPicker(): Promise<void> {
        const editor = vscode.window.activeTextEditor;
        const hasCode = !!editor && !editor.selection.isEmpty;

        const items = BUILTIN_TOOLS.map(t => ({
            label: `${t.icon}  ${t.label}`,
            description: t.description,
            detail: hasCode ? '↳ Will run on selected code' : '↳ Will run on entire file',
            toolName: t.name,
        }));

        const picked = await vscode.window.showQuickPick(items, {
            placeHolder: 'Select a tool to run on your code',
            matchOnDescription: true,
        });

        if (picked) {
            await this.runFromEditor(picked.toolName);
        }
    }
}
