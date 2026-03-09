// ==============================================================
// chatViewProvider.ts
//
// Implements the persistent sidebar chat panel (like GitHub Copilot).
// Registered as a WebviewViewProvider — survives panel switches.
// ==============================================================

import * as vscode from 'vscode';
import { BackendClient, StreamEvent } from './backendClient';
import { getChatHtml } from './chatHtml';
import { generateSessionId } from './utils';
import { ContextManager, FileContext } from './contextManager';
import { ToolsProvider } from './toolsProvider';

// Messages from webview → extension
interface WebviewMessage {
    type: 'sendMessage' | 'clearChat' | 'newSession' | 'getProviders' | 'cancelStream' | 'getTools' | 'runCustomTool';
    text?: string;
    provider?: string;
    model?: string;
    contextEnabled?: boolean;
    toolName?: string;
}

export class OpenClawChatViewProvider implements vscode.WebviewViewProvider {
    private _view?: vscode.WebviewView;
    private _sessionId: string = generateSessionId();
    private _streamAbortController: AbortController | null = null;
    private _toolsProvider?: ToolsProvider;

    constructor(
        private readonly context: vscode.ExtensionContext,
        private readonly backendClient: BackendClient,
    ) { }

    // Called by extension.ts after both providers are constructed
    public setToolsProvider(tp: ToolsProvider): void {
        this._toolsProvider = tp;
    }

    // ── Called by VS Code when the sidebar panel is first shown ──────────────
    resolveWebviewView(
        webviewView: vscode.WebviewView,
        _ctx: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken,
    ): void {
        this._view = webviewView;

        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [this.context.extensionUri],
        };

        webviewView.webview.html = getChatHtml(webviewView.webview, this.context);

        // ── Handle messages from webview UI ───────────────────────────────────
        webviewView.webview.onDidReceiveMessage(
            async (msg: WebviewMessage) => {
                switch (msg.type) {
                    case 'sendMessage':
                        await this._handleUserMessage(msg.text ?? '', msg.provider, msg.model, msg.contextEnabled);
                        break;
                    case 'clearChat':
                        this.clearChat();
                        break;
                    case 'newSession':
                        this.newSession();
                        break;
                    case 'getProviders':
                        await this._sendProviders();
                        break;
                    case 'cancelStream':
                        this._cancelStream();
                        break;
                    case 'getTools':
                        await this._sendTools();
                        break;
                    case 'runCustomTool':
                        if (msg.toolName && this._toolsProvider) {
                            await this._toolsProvider.runFromEditor(msg.toolName);
                        }
                        break;
                }
            },
            undefined,
            this.context.subscriptions,
        );

        // ── Send initial providers list once panel loads ───────────────────────
        webviewView.onDidChangeVisibility(() => {
            if (webviewView.visible) {
                this._sendProviders();
                this._sendCurrentFileContext(); // FIX #6: refresh pill on panel show
            }
        });
        this._sendProviders();
        this._sendCurrentFileContext(); // FIX #6: populate pill immediately on load

        // FIX #6 — Live context pill: update whenever user switches files
        // Previously the pill only updated when a message was sent
        // Now it updates in real-time as the developer navigates files
        const editorChangeListener = vscode.window.onDidChangeActiveTextEditor(() => {
            if (webviewView.visible) {
                this._sendCurrentFileContext();
            }
        });
        const selectionChangeListener = vscode.window.onDidChangeTextEditorSelection(() => {
            if (webviewView.visible) {
                this._sendCurrentFileContext();
            }
        });
        this.context.subscriptions.push(editorChangeListener, selectionChangeListener);
    }

    // ── Handle a user chat message ────────────────────────────────────────────
    private async _handleUserMessage(
        text: string,
        provider?: string,
        model?: string,
        contextEnabled?: boolean,
    ): Promise<void> {
        if (!text.trim()) { return; }

        const config = vscode.workspace.getConfiguration('openclaw');
        const resolvedProvider = provider ?? config.get<string>('defaultProvider', 'openai');
        const resolvedModel = model ?? config.get<string>('defaultModel', '');
        const useStream = config.get<boolean>('streamResponses', true);
        const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;

        console.log(`[OpenClaw] User message: provider=${resolvedProvider}, model=${resolvedModel || 'default'}, stream=${useStream}, contextEnabled=${contextEnabled !== false}`);

        // ── Capture file context ───────────────────────────────────────────────
        // contextEnabled comes from the UI toggle (defaults to true)
        let fileContext: FileContext | undefined;
        const shouldInjectContext = contextEnabled !== false;

        if (shouldInjectContext) {
            const captured = ContextManager.capture();
            if (captured) {
                fileContext = captured.context;
                console.log('[OpenClaw] File context captured:', captured.summary?.label || 'unknown');
                // Tell the webview to show which file was sent
                this._postToWebview({ type: 'contextAttached', summary: captured.summary });
            }
        }

        this._postToWebview({ type: 'startAssistant' });

        try {
            if (useStream) {
                await this._streamResponse(text, resolvedProvider, resolvedModel, workspacePath, fileContext);
            } else {
                await this._simpleResponse(text, resolvedProvider, resolvedModel, workspacePath, fileContext);
            }
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            console.error('[OpenClaw] Chat handling error:', err);
            this._postToWebview({ type: 'error', message: `Backend error: ${msg}` });
        }
    }

    // ── Stream response (SSE) ─────────────────────────────────────────────────
    private async _streamResponse(
        message: string,
        provider: string,
        model: string,
        workspacePath?: string,
        fileContext?: FileContext,
    ): Promise<void> {
        this._streamAbortController = new AbortController();
        let toolCallCount = 0;

        try {
            for await (const event of this.backendClient.chatStream(
                message, provider, model, this._sessionId, workspacePath, fileContext,
                this._streamAbortController.signal
            )) {
                if (this._streamAbortController.signal.aborted) { break; }

                switch (event.type) {
                    case 'step':
                        if (event.step?.type === 'tool_call') {
                            toolCallCount++;
                            this._postToWebview({
                                type: 'toolCall',
                                toolName: event.step.toolName,
                                count: toolCallCount,
                            });
                        }
                        break;

                    case 'chunk':
                        this._postToWebview({ type: 'chunk', content: event.content ?? '' });
                        break;

                    case 'done':
                        this._postToWebview({
                            type: 'done',
                            durationMs: event.durationMs,
                            totalToolCalls: event.totalToolCalls,
                            provider,
                            model,
                        });
                        break;

                    case 'error':
                        this._postToWebview({ type: 'error', message: event.error ?? 'Unknown error' });
                        break;
                }
            }
        } catch (err) {
            if (!this._streamAbortController.signal.aborted) {
                throw err;
            }
            // User cancelled — send done
            this._postToWebview({ type: 'cancelled' });
        } finally {
            this._streamAbortController = null;
        }
    }

    // ── Simple (non-streaming) response ───────────────────────────────────────
    private async _simpleResponse(
        message: string,
        provider: string,
        model: string,
        workspacePath?: string,
        fileContext?: FileContext,
    ): Promise<void> {
        const result = await this.backendClient.chat(
            message, provider, model, this._sessionId, workspacePath, fileContext
        );

        if (result.error) {
            this._postToWebview({ type: 'error', message: result.error });
        } else {
            this._postToWebview({
                type: 'fullResponse',
                content: result.output,
                durationMs: result.durationMs,
                totalToolCalls: result.totalToolCalls,
                provider: result.provider,
                model: result.model,
            });
        }
    }

    // ── Send providers list to webview ────────────────────────────────────────
    private async _sendProviders(): Promise<void> {
        try {
            const providers = await this.backendClient.getProviders();
            this._postToWebview({ type: 'providers', providers });
        } catch (err) {
            console.error('[OpenClaw] Failed to fetch providers from backend:', err);
            this._postToWebview({ type: 'providers', providers: [] });
        }
    }

    // ── Send tools list (builtin + custom) to webview ─────────────────────────
    private async _sendTools(): Promise<void> {
        try {
            const tools = await this.backendClient.getTools();
            this._postToWebview({ type: 'tools', builtin: tools.builtin, custom: tools.custom });
        } catch (err) {
            console.error('[OpenClaw] Failed to fetch tools from backend:', err);
            this._postToWebview({ type: 'tools', builtin: [], custom: [] });
        }
    }

    // ── FIX #6: Send current file context to update the context pill live ─────
    // Called on editor switch, selection change, and panel visibility change
    private _sendCurrentFileContext(): void {
        const captured = ContextManager.capture();
        if (captured) {
            this._postToWebview({ type: 'contextAttached', summary: captured.summary });
        } else {
            this._postToWebview({ type: 'contextAttached', summary: null });
        }
    }

    // ── Cancel active stream ──────────────────────────────────────────────────
    private _cancelStream(): void {
        this._streamAbortController?.abort();
    }

    // ── Public API (called by commands + toolsProvider) ───────────────────────
    public clearChat(): void {
        this._postToWebview({ type: 'clearChat' });
    }

    public newSession(): void {
        const oldSessionId = this._sessionId;
        this._sessionId = generateSessionId();
        this.backendClient.clearSession(oldSessionId).catch(() => { });
        this._postToWebview({ type: 'newSession', sessionId: this._sessionId });
        vscode.window.setStatusBarMessage('$(add) OpenClaw: New session started', 2000);
    }

    // Called by ToolsProvider to inject a user-triggered tool message into chat
    public pushUserMessage(text: string): void {
        this._postToWebview({ type: 'pushUserMessage', text });
    }

    public startAssistantMessage(): void {
        this._postToWebview({ type: 'startAssistant' });
    }

    public pushFullResponse(
        content: string,
        meta: { provider?: string; model?: string; durationMs?: number; toolName?: string }
    ): void {
        this._postToWebview({ type: 'fullResponse', content, ...meta });
    }

    public pushError(message: string): void {
        this._postToWebview({ type: 'error', message });
    }

    // ── Helper: post message to webview ──────────────────────────────────────
    private _postToWebview(data: Record<string, unknown>): void {
        this._view?.webview.postMessage(data);
    }
}
