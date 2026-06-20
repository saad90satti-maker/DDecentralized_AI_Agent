#!/usr/bin/env python3
"""
Hugging Face Spaces Deployment Script

This script deploys the Ghost Engine to Hugging Face Spaces.

Usage:
    python deploy.py

Environment Variables (set these in GitHub Secrets or .env):
    HF_TOKEN: Your Hugging Face API token
    HF_SPACE_REPO: Your Space repo ID (e.g., saad2howw/Decentralized-AI-Agent)
"""

import os
import subprocess
import sys
from pathlib import Path


def deploy_to_hf_spaces():
    """Deploy Ghost Engine to Hugging Face Spaces."""
    
    hf_token = os.getenv("HF_TOKEN")
    hf_space_repo = os.getenv("HF_SPACE_REPO", "saad2howw/Decentralized-AI-Agent")
    
    if not hf_token:
        print("❌ HF_TOKEN environment variable not set")
        print("Set it with: export HF_TOKEN='your_token_here'")
        return False
    
    print(f"🚀 Deploying Ghost Engine to Hugging Face Space: {hf_space_repo}")
    
    try:
        # Clone or initialize the HF Space repo
        space_dir = Path("hf_space_repo")
        if space_dir.exists():
            print(f"📂 Using existing Space directory: {space_dir}")
            os.chdir(space_dir)
            subprocess.run(["git", "pull"], check=True)
        else:
            print(f"📥 Cloning Space repository: {hf_space_repo}")
            clone_url = f"https://huggingface.co/spaces/{hf_space_repo}"
            subprocess.run(
                ["git", "clone", clone_url, str(space_dir)],
                check=True
            )
            os.chdir(space_dir)
        
        # Copy project files to Space
        print("📋 Copying project files to Space...")
        files_to_copy = [
            "manager.py",
            "app.py",
            "requirements.txt",
            "hermes_bridge.py",
            "cli.py",
            "browser_agent.py",
            "security_utils.py",
            "execution_core.py",
            "stealth_browser.py",
            "email_agent.py",
            "dashboard_instrumentation.py",
            "run_agent.py",
            ".env.example",
        ]
        
        for file in files_to_copy:
            src = Path("..") / file
            if src.exists():
                subprocess.run(["cp", str(src), str(file)], check=True)
                print(f"  ✓ {file}")
        
        # Create or update app.py for Gradio + FastAPI
        print("🎨 Setting up Gradio interface...")
        create_gradio_interface()
        
        # Commit changes
        print("📝 Committing changes...")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run([
            "git", "commit", "-m",
            "Deploy Ghost Engine - Automated update via CI/CD"
        ], check=True)
        
        # Push to Space
        print(f"🔼 Pushing to {hf_space_repo}...")
        subprocess.run(["git", "push"], check=True)
        
        print(f"✅ Deployment complete!")
        print(f"🌐 Access your Space at: https://huggingface.co/spaces/{hf_space_repo}")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Deployment failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def create_gradio_interface():
    """Create a Gradio interface for Hugging Face Spaces."""
    gradio_code = '''import gradio as gr
import asyncio
import os
import uvicorn
from manager import app
from stealth_browser import BrowserStealth
from email_agent import EmailResponder
from execution_core import ExecutionCoordinator, PipelineTask, TaskType

# Note: For HF Spaces, we run both FastAPI and Gradio together by mounting Gradio onto FastAPI
# The FastAPI app from manager.py is imported as 'app'.

async def execute_command(command: str) -> str:
    """Execute a shell command and return the output."""
    from execution_core import ExecutionCoordinator
    from dashboard_instrumentation import MetricsStore
    
    metrics = MetricsStore()
    coordinator = ExecutionCoordinator(metrics=metrics)
    await coordinator.start()
    
    task = PipelineTask(type=TaskType.SYSTEM, payload={"command": command})
    await coordinator.submit_task(task)
    
    # Wait for task completion with status updates (max 30 seconds)
    for _ in range(30):
        await asyncio.sleep(1)
        if task.status in ["succeeded", "failed", "error", "dead"]:
            break
            
    await coordinator.stop()
    
    if task.status == "succeeded":
        return f"SUCCESS:\\n{task.result.get('stdout', '')}"
    else:
        err = task.result.get('stderr', '') or task.result.get('message', 'Unknown error')
        return f"FAILED (status: {task.status}):\\n{err}"

async def check_email(email: str) -> str:
    """Check unread emails."""
    responder = EmailResponder()
    unread = await asyncio.to_thread(responder._fetch_unread_messages)
    return f"Unread emails: {len(unread)}"

async def analyze_text(text: str) -> str:
    """Analyze text using Hermes."""
    from hermes_bridge import HermesBridge
    
    hb = HermesBridge()
    result = hb.analyze(text)
    # Safely extract text output from response
    if isinstance(result, dict):
        if result.get("status") == "success":
            return result.get("stdout") or result.get("response", {}).get("response", str(result))
        return f"Error: {result.get('reason') or result.get('exception') or str(result)}"
    return f"Analysis: {result}"

# Create Gradio interface
with gr.Blocks(title="Ghost Engine Control Panel") as demo:
    gr.Markdown("# 🤖 Ghost Engine - Autonomous AI Agent")
    gr.Markdown("Control your decentralized AI agent from this interface.")
    
    with gr.Tab("Command Execution"):
        with gr.Row():
            cmd_input = gr.Textbox(label="Command", placeholder="Enter shell command")
            cmd_button = gr.Button("Execute")
        cmd_output = gr.Textbox(label="Output", lines=10)
        cmd_button.click(execute_command, inputs=cmd_input, outputs=cmd_output)
    
    with gr.Tab("Email Management"):
        email_input = gr.Textbox(label="Email Address", placeholder="your@email.com")
        email_button = gr.Button("Check Unread")
        email_output = gr.Textbox(label="Result", lines=3)
        email_button.click(check_email, inputs=email_input, outputs=email_output)
    
    with gr.Tab("AI Analysis"):
        text_input = gr.Textbox(label="Text to Analyze", lines=5)
        analyze_button = gr.Button("Analyze")
        analysis_output = gr.Textbox(label="Analysis Result", lines=5)
        analyze_button.click(analyze_text, inputs=text_input, outputs=analysis_output)
    
    gr.Markdown("---")
    gr.Markdown(
        "**Note:** This interface connects to the Ghost Engine backend running on this Space. "
        "Ensure all required environment variables are set for full functionality."
    )

# Mount Gradio UI directly onto the FastAPI application at the root
app = gr.mount_gradio_app(app, demo, path="/")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
'''
    
    with open("app.py", "w", encoding="utf-8") as f:
        f.write(gradio_code)
    print("  ✓ app.py (Gradio interface)")


if __name__ == "__main__":
    success = deploy_to_hf_spaces()
    sys.exit(0 if success else 1)
