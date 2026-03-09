// ==============================================================
// backendClient.ts
//
// Handles all HTTP communication with the OpenClaw Python backend.
// Single source of truth for API calls — used by all providers.
// ==============================================================

import axios, { AxiosInstance } from 'axios';

export interface ChatResponse {
    output: string;
    provider: string;
    model: string;
    durationMs: number;
    totalToolCalls: number;
    error: string | null;
}

export interface ToolResponse {
    output: string;
    toolName: string;
    provider: string;
    model: string;
    durationMs: number;
    error: string | null;
}

export interface ExecuteRequest {
    taskType: 'tool' | 'chat' | 'auto';
    toolName?: string;
    toolArgs?: Record<string, unknown>;
    userMessage?: string;
    context?: {
        filePath?: string;
        language?: string;
        workspacePath?: string;
    };
    llmProvider?: string;
    llmModel?: string;
    sessionId?: string;
}

export interface Provider {
    provider: string;
    type: 'cloud' | 'local';
    models: string[];
    error?: string;
}

export interface StreamEvent {
    type: 'step' | 'chunk' | 'done' | 'error';
    content?: string;
    error?: string;
    step?: {
        type: string;
        toolName?: string;
        toolArgs?: Record<string, unknown>;
        result?: string;
        success?: boolean;
    };
    durationMs?: number;
    totalToolCalls?: number;
}

export class BackendClient {
    private http: AxiosInstance;
    private _baseUrl: string;

    constructor(baseUrl: string) {
        this._baseUrl = baseUrl;
        this.http = axios.create({
            baseURL: baseUrl,
            timeout: 120_000,
            headers: { 'Content-Type': 'application/json' }
        });
    }

    get baseUrl() { return this._baseUrl; }

    // ── Health check ──────────────────────────────────────────────────────────
    async healthCheck(): Promise<boolean> {
        try {
            console.log('[OpenClaw] Health check →', this._baseUrl + '/health');
            const r = await this.http.get('/health', { timeout: 3000 });
            const ok = r.data?.status === 'ok';
            console.log('[OpenClaw] Health check result:', ok ? '✅ OK' : '❌ NOT OK', r.data);
            return ok;
        } catch (err) {
            console.error('[OpenClaw] Health check FAILED — backend unreachable:', this._baseUrl, err);
            return false;
        }
    }

    // ── Execute a specific tool ───────────────────────────────────────────────
    // The OpenClaw agent receives taskType + toolName and handles everything:
    //   - Parses intent (if taskType='auto')
    //   - Selects the right tool
    //   - Executes it
    //   - Returns formatted output
    async executeTool(req: ExecuteRequest): Promise<ToolResponse> {
        console.log('[OpenClaw] Execute tool →', req.toolName, '| provider:', req.llmProvider, '| taskType:', req.taskType);
        try {
            const r = await this.http.post('/api/execute', req);
            if (r.data?.error) {
                console.error('[OpenClaw] Tool execution error:', r.data.error);
            } else {
                console.log('[OpenClaw] Tool execution OK:', req.toolName, `(${r.data?.durationMs}ms)`);
            }
            return r.data;
        } catch (err: unknown) {
            console.error('[OpenClaw] Execute tool FAILED:', req.toolName, this._formatError(err));
            throw err;
        }
    }

    // ── Simple chat (non-streaming) ───────────────────────────────────────────
    async chat(
        message: string,
        provider: string,
        model: string,
        sessionId: string,
        workspacePath?: string,
        fileContext?: import('./contextManager').FileContext,
    ): Promise<ChatResponse> {
        console.log('[OpenClaw] Chat (simple) →', { provider, model: model || 'default', sessionId, hasContext: !!fileContext });
        try {
            const r = await this.http.post('/api/chat', {
                message,
                provider,
                model: model || undefined,
                sessionId,
                workspacePath,
                agentMode: true,
                context: fileContext ? {
                    workspacePath,
                    filePath: fileContext.filePath,
                    fileName: fileContext.fileName,
                    language: fileContext.language,
                    totalLines: fileContext.totalLines,
                    captureMode: fileContext.captureMode,
                    code: fileContext.content,
                    cursorLine: fileContext.cursorLine,
                    selectionStart: fileContext.selectionStart,
                    selectionEnd: fileContext.selectionEnd,
                } : undefined,
            });
            if (r.data?.error) {
                console.error('[OpenClaw] Chat response error:', r.data.error, '| provider:', r.data.provider, '| model:', r.data.model);
            } else {
                console.log('[OpenClaw] Chat response OK:', { provider: r.data.provider, model: r.data.model, durationMs: r.data.durationMs, toolCalls: r.data.totalToolCalls });
            }
            return r.data;
        } catch (err: unknown) {
            console.error('[OpenClaw] Chat request FAILED:', this._formatError(err));
            throw err;
        }
    }

    // ── Streaming chat (SSE) ──────────────────────────────────────────────────
    async *chatStream(
        message: string,
        provider: string,
        model: string,
        sessionId: string,
        workspacePath?: string,
        fileContext?: import('./contextManager').FileContext,
        signal?: AbortSignal,
    ): AsyncGenerator<StreamEvent> {
        console.log('[OpenClaw] Chat (stream) →', { provider, model: model || 'default', sessionId, hasContext: !!fileContext });

        const response = await fetch(`${this._baseUrl}/api/chat/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal,
            body: JSON.stringify({
                message,
                provider,
                model: model || undefined,
                sessionId,
                workspacePath,
                agentMode: true,
                context: fileContext ? {
                    workspacePath,
                    filePath: fileContext.filePath,
                    fileName: fileContext.fileName,
                    language: fileContext.language,
                    totalLines: fileContext.totalLines,
                    captureMode: fileContext.captureMode,
                    code: fileContext.content,
                    cursorLine: fileContext.cursorLine,
                    selectionStart: fileContext.selectionStart,
                    selectionEnd: fileContext.selectionEnd,
                } : undefined,
            }),
        });

        // Check HTTP-level errors (fetch doesn't throw on 4xx/5xx)
        if (!response.ok) {
            const errorBody = await response.text().catch(() => '');
            console.error('[OpenClaw] Stream HTTP error:', response.status, response.statusText, errorBody);
            throw new Error(`Stream request failed: ${response.status} ${response.statusText}`);
        }

        if (!response.body) {
            console.error('[OpenClaw] Stream response has no body');
            throw new Error('No response body from stream');
        }

        console.log('[OpenClaw] Stream connection established, reading events...');
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) {
                console.log('[OpenClaw] Stream ended');
                break;
            }
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() ?? '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const event: StreamEvent = JSON.parse(line.slice(6));
                        if (event.type === 'error') {
                            console.error('[OpenClaw] Stream error event:', event.error);
                        } else if (event.type === 'done') {
                            console.log('[OpenClaw] Stream done:', { durationMs: event.durationMs, toolCalls: event.totalToolCalls });
                        }
                        yield event;
                    } catch (parseErr) {
                        console.warn('[OpenClaw] Failed to parse SSE line:', line, parseErr);
                    }
                }
            }
        }
    }

    // ── List providers ────────────────────────────────────────────────────────
    async getProviders(): Promise<Provider[]> {
        try {
            const r = await this.http.get('/api/providers');
            const providers = r.data?.providers ?? [];
            console.log('[OpenClaw] Providers loaded:', providers.map((p: Provider) => `${p.provider}(${p.models?.length || 0} models${p.error ? ', ERROR: ' + p.error : ''})`).join(', '));
            return providers;
        } catch (err: unknown) {
            console.error('[OpenClaw] Failed to load providers:', this._formatError(err));
            throw err;
        }
    }

    // ── List all tools ────────────────────────────────────────────────────────
    async getTools(): Promise<{ builtin: unknown[]; custom: unknown[] }> {
        try {
            const r = await this.http.get('/api/tools');
            console.log('[OpenClaw] Tools loaded:', { builtin: (r.data?.builtin as unknown[])?.length || 0, custom: (r.data?.custom as unknown[])?.length || 0 });
            return r.data;
        } catch (err: unknown) {
            console.error('[OpenClaw] Failed to load tools:', this._formatError(err));
            throw err;
        }
    }

    // ── Clear session ─────────────────────────────────────────────────────────
    async clearSession(sessionId: string): Promise<void> {
        console.log('[OpenClaw] Clearing session:', sessionId);
        await this.http.delete(`/api/session/${sessionId}`);
    }

    // ── Error formatter for logging ───────────────────────────────────────────
    private _formatError(err: unknown): string {
        if (!err) { return 'Unknown error'; }
        if (err instanceof Error) {
            const axiosErr = err as Error & { response?: { status: number; statusText: string; data: unknown }; code?: string };
            if (axiosErr.response) {
                return `HTTP ${axiosErr.response.status} ${axiosErr.response.statusText} | ${JSON.stringify(axiosErr.response.data)}`;
            }
            if (axiosErr.code === 'ECONNREFUSED') {
                return `Connection refused — is the backend running at ${this._baseUrl}?`;
            }
            return `${err.name}: ${err.message}`;
        }
        return String(err);
    }
}
