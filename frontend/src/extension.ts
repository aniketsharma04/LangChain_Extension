// ==============================================================
// extension.ts — OpenClaw VS Code Extension Entry Point
//
// Phase 2 additions:
//   - All builtin tool commands registered
//   - Right-click context menu on selected code
//   - Quick-pick tool picker command
// ==============================================================

import * as vscode from 'vscode';
import { OpenClawChatViewProvider } from './chatViewProvider';
import { BackendClient } from './backendClient';
import { ToolsProvider, BUILTIN_TOOLS } from './toolsProvider';

export function activate(context: vscode.ExtensionContext) {
    console.log('[OpenClaw] Extension activating...');

    const config = vscode.workspace.getConfiguration('openclaw');
    const backendUrl = config.get<string>('backendUrl', 'http://localhost:3579');
    console.log('[OpenClaw] Backend URL:', backendUrl);
    console.log('[OpenClaw] Config:', {
        defaultProvider: config.get<string>('defaultProvider', 'openai'),
        defaultModel: config.get<string>('defaultModel', ''),
        streamResponses: config.get<boolean>('streamResponses', true),
    });

    // ── Core clients ──────────────────────────────────────────────────────────
    const backendClient = new BackendClient(backendUrl);

    // ── Sidebar webview + tools ───────────────────────────────────────────────
    const chatProvider = new OpenClawChatViewProvider(context, backendClient);
    const toolsProvider = new ToolsProvider(backendClient, chatProvider);
    chatProvider.setToolsProvider(toolsProvider); // wire up for runCustomTool messages

    const chatViewRegistration = vscode.window.registerWebviewViewProvider(
        'openclawChatView',
        chatProvider,
        { webviewOptions: { retainContextWhenHidden: true } }
    );

    // ── Chat commands ─────────────────────────────────────────────────────────
    const chatCommands = [
        vscode.commands.registerCommand('openclaw.openChat', () => vscode.commands.executeCommand('openclawChatView.focus')),
        vscode.commands.registerCommand('openclaw.clearChat', () => chatProvider.clearChat()),
        vscode.commands.registerCommand('openclaw.newSession', () => chatProvider.newSession()),
    ];

    // ── Tool picker (QuickPick menu of all tools) ─────────────────────────────
    const toolPickerCmd = vscode.commands.registerCommand(
        'openclaw.runTool',
        () => toolsProvider.showToolPicker()
    );

    // ── One command per builtin tool ──────────────────────────────────────────
    // Called from right-click context menu
    // Flow:
    //   User selects code → right-click → picks tool
    //   → ToolsProvider reads selection + language
    //   → POST /api/execute { taskType: 'tool', toolName, code, language }
    //   → OpenClaw agent parses, selects tool, executes
    //   → Result appears in chat panel
    const toolCommands = BUILTIN_TOOLS.map(tool =>
        vscode.commands.registerCommand(
            `openclaw.tool.${tool.name}`,
            () => toolsProvider.runFromEditor(tool.name)
        )
    );

    context.subscriptions.push(
        chatViewRegistration,
        ...chatCommands,
        toolPickerCmd,
        ...toolCommands,
    );

    // ── Status bar ────────────────────────────────────────────────────────────
    const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBar.text = '$(hubot) OpenClaw';
    statusBar.tooltip = 'OpenClaw AI — Click to open chat';
    statusBar.command = 'openclaw.openChat';
    statusBar.show();
    context.subscriptions.push(statusBar);

    // ── Health check ──────────────────────────────────────────────────────────
    console.log('[OpenClaw] Running health check...');
    backendClient.healthCheck().then(ok => {
        if (ok) {
            statusBar.text = '$(check) OpenClaw';
            console.log('[OpenClaw] Backend health check passed ✅');
            vscode.window.setStatusBarMessage('$(check) OpenClaw backend connected', 3000);
        } else {
            statusBar.text = '$(warning) OpenClaw';
            console.error('[OpenClaw] Backend health check FAILED ❌ — cannot reach', backendUrl);
            vscode.window.showWarningMessage(
                `OpenClaw: Cannot reach backend at ${backendUrl}. Start the Python server first.`,
                'Dismiss'
            );
        }
    });

    console.log('[OpenClaw] Extension activated.');
}

export function deactivate() { }
