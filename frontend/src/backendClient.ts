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
            const r = await this.http.get('/health', { timeout: 3000 });
            return r.data?.status === 'ok';
        } catch {
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
        const r = await this.http.post('/api/execute', req);
        return r.data;
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
        const r = await this.http.post('/api/chat', {
            message,
            provider,
            model: model || undefined,
            sessionId,
            workspacePath,
            agentMode: true,
            context: fileContext ? {
                workspacePath,
                filePath:    fileContext.filePath,
                fileName:    fileContext.fileName,
                language:    fileContext.language,
                totalLines:  fileContext.totalLines,
                captureMode: fileContext.captureMode,
                code:        fileContext.content,
                cursorLine:  fileContext.cursorLine,
                selectionStart: fileContext.selectionStart,
                selectionEnd:   fileContext.selectionEnd,
            } : undefined,
        });
        return r.data;
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
                    filePath:    fileContext.filePath,
                    fileName:    fileContext.fileName,
                    language:    fileContext.language,
                    totalLines:  fileContext.totalLines,
                    captureMode: fileContext.captureMode,
                    code:        fileContext.content,
                    cursorLine:  fileContext.cursorLine,
                    selectionStart: fileContext.selectionStart,
                    selectionEnd:   fileContext.selectionEnd,
                } : undefined,
            }),
        });

        if (!response.body) {
            throw new Error('No response body from stream');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) { break; }
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() ?? '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const event: StreamEvent = JSON.parse(line.slice(6));
                        yield event;
                    } catch {
                        // skip malformed line
                    }
                }
            }
        }
    }

    // ── List providers ────────────────────────────────────────────────────────
    async getProviders(): Promise<Provider[]> {
        const r = await this.http.get('/api/providers');
        return r.data?.providers ?? [];
    }

    // ── List all tools ────────────────────────────────────────────────────────
    async getTools(): Promise<{ builtin: unknown[]; custom: unknown[] }> {
        const r = await this.http.get('/api/tools');
        return r.data;
    }

    // ── Clear session ─────────────────────────────────────────────────────────
    async clearSession(sessionId: string): Promise<void> {
        await this.http.delete(`/api/session/${sessionId}`);
    }
}
