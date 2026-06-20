import os
import sys
import subprocess
import json
import urllib.request
from dotenv import load_dotenv

load_dotenv()

# Force UTF-8 encoding for standard output on Windows to support emojis
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# API Configuration - keys loaded from .env file only
import google.generativeai as genai

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    print("WARNING: GEMINI_API_KEY not set in .env. Gemini fallback will be unavailable.")
    model = None
else:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel(os.getenv("GEMINI_API_MODEL", "models/gemini-2.0-flash"))

print("🧠 Decentralized Self-Evolving AI Agent (Local Llama/Gemini) Active ho gaya hai!")

def get_ai_response(prompt):
    if not model:
        raise RuntimeError("No AI model available. Set GEMINI_API_KEY in .env or start Ollama.")
    # Try local Ollama first
    try:
        url = "http://localhost:11434/api/generate"
        headers = {"Content-Type": "application/json"}
        
        data = {
            "model": "llama3.2:1b",
            "prompt": prompt,
            "stream": False
        }
        
        req = urllib.request.Request(
            url, 
            data=json.dumps(data).encode('utf-8'), 
            headers=headers, 
            method='POST'
        )
        
        # Adding a 15-second timeout to avoid hanging indefinitely
        with urllib.request.urlopen(req, timeout=15) as response:
            response_data = json.loads(response.read().decode('utf-8'))
            
        raw_text = response_data.get('response', '').strip()
        print("🤖 Response generated via local Ollama (Llama 3.2:1b).")
    except Exception as e:
        print(f"⚠️ Local Ollama is unavailable ({e}). Falling back to Gemini 3.5 Flash API...")
        if model:
            try:
                response = model.generate_content(prompt)
                raw_text = response.text.strip()
                print("✨ Response generated via Gemini API fallback.")
            except Exception as gemini_err:
                print(f"❌ Gemini fallback also failed: {gemini_err}")
                raise gemini_err
        else:
            raise RuntimeError("No AI model available. Set GEMINI_API_KEY in .env or start Ollama.")
    
    # Markdown formatting saaf karna
    if raw_text.startswith("```python"):
        raw_text = raw_text[9:]
    elif raw_text.startswith("```"):
        raw_text = raw_text[3:]
    if raw_text.endswith("```"):
        raw_text = raw_text[:-3]
        
    return raw_text.strip()

# Initialize error state
execution_errors = ""

def main():
    global execution_errors
    # Agent ka Andruni Dimaag Loop
    while True:
        user_goal = input("\n🎯 Aapka Azaad Goal / Target ('exit' likhein band karne ke liye): ")
        
        if user_goal.lower() == 'exit':
            print("Agent ko band kiya ja raha hai. Allah Hafiz!")
            break
            
        if not user_goal.strip():
            print("Goal khali nahi ho sakta!")
            continue
            
        current_code = ""
        task_file = "evolved_task.py"
        
        for iteration in range(3): 
            try:
                if iteration == 0:
                    print(f"\n⏳ [Koshish {iteration+1}] Agent local Llama se connect ho kar script bana raha...")
                    prompt = (
                        "You are a decentralized, self-evolving AI software engineer agent. "
                        "Write clean, functional, and complete Python code to achieve the following goal. "
                        "Return ONLY the raw Python code. Do not include markdown blocks or conversational text.\n\n"
                        f"Goal: {user_goal}"
                    )
                else:
                    print(f"\n⚙️ [Koshish {iteration+1}] Agent pichli kharabi ko parh kar code ko customize/evolve kar raha...")
                    prompt = (
                        "You are a decentralized, self-evolving AI software engineer agent. "
                        "The previous execution failed or needs improvement. Fix the code or improve it to achieve the goal. "
                        "Return ONLY the raw Python code. Do not include markdown blocks or conversational text.\n\n"
                        f"Original Goal: {user_goal}\n"
                        f"Previous Code:\n{current_code}\n"
                        f"Execution Error / Output:\n{execution_errors}"
                    )
                
                generated_code = get_ai_response(prompt)
                
                print(f"\n💡 Generated Code (Iteration {iteration+1}):")
                print("=" * 50)
                print(generated_code)
                print("=" * 50)
                
                with open(task_file, "w", encoding="utf-8") as f:
                    f.write(generated_code)
                    
                current_code = generated_code
                
                print(f"\n🚀 Code execute ho raha hai...")
                exec_process = subprocess.run(
                    ["python", task_file], 
                    capture_output=True, 
                    text=True, 
                    encoding="utf-8"
                )
                
                print("\n📊 Execution Output:")
                if exec_process.stdout:
                    print("Output:")
                    print(exec_process.stdout)
                    
                if exec_process.stderr:
                    print("⚠️ Errors Detected:")
                    print(exec_process.stderr)
                    execution_errors = exec_process.stderr
                    
                    if not execution_errors.strip():
                        execution_errors = exec_process.stdout
                else:
                    print("✨ Task kamyabi ke sath mukammal ho gaya!")
                    execution_errors = ""
                    break 
                    
            except Exception as e:
                print(f"\n⚠️ Loop Exception: {e}")
                execution_errors = str(e)
                
        print("\n🏁 Yeh goal process khatam hua. Aap naya goal de sakte hain.")
        print("-" * 60)

if __name__ == "__main__":
    main()