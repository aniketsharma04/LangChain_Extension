Fix: Rate Limit Error Crashing Agent Response After Tool Calls
Problem
When you send "hi", the agent correctly calls tools to understand the codebase, but then crashes with a rate limit error before it can generate the final response. The Gemini free tier allows ~10 RPM for gemini-2.5-flash. Each tool call in the ReAct loop requires a separate LLM call, so 6 tool calls + 1 final response = 7 API calls in quick succession, often hitting the limit.

Root Causes
No retry/backoff — ChatGoogleGenerativeAI is created with default max_retries=2 and no delay between retries. When a 429 hits, it fails fast.
No rate-limiting between agent steps — LangGraph fires tool calls as fast as possible with no pacing, burning through the free tier RPM instantly.
NOTE

The Unleash console error is from the Antigravity IDE itself — harmless, no action needed.

Proposed Changes
Agent Engine
[MODIFY] 
agent_engine.py
Add a rate-limit-aware callback handler that introduces a small delay (~3s) between consecutive LLM calls in the agent loop. This keeps us under the free tier RPM limit without making the agent feel sluggish.

Add graceful error recovery in 
run_streaming()
 — If a rate limit error occurs mid-stream, wait and retry instead of immediately propagating the error to the UI.

LLM Router
[MODIFY] 
llm_router.py
Set max_retries=5 on ChatGoogleGenerativeAI to enable LangChain's built-in exponential backoff retry for 429 errors. Also set request_timeout=60 to prevent premature timeouts.
Verification Plan
Manual Verification
Start backend: cd backend && python server.py
Launch extension (F5)
Send "hi" → Agent should call tools AND then successfully respond with a greeting (no rate limit crash)
Send a follow-up question → Should work normally without 429 errors