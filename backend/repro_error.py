import asyncio
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
import os
from dotenv import load_dotenv

load_dotenv()

async def test_astream_events_v2():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("No API key")
        return

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=api_key,
        streaming=True
    )

    final_output = ""
    print("Starting astream_events(v2)...")
    try:
        async for event in llm.astream_events(
            [HumanMessage(content="Say hello")],
            version="v2"
        ):
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                content = chunk.content
                print(f"Event: {kind} | Content Type: {type(content)} | Content: {repr(content)}")
                
                try:
                    # Simulation of current agent_engine.py logic (with string initialization)
                    # Note: I initialized final_output = "" above
                    final_output += content
                    print("  Concatenation SUCCESS")
                except TypeError as e:
                    print(f"  Concatenation FAILED: {e}")
                    
    except Exception as e:
        print(f"Stream Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_astream_events_v2())
