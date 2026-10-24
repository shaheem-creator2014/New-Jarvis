"""Knowledge inspection and local dashboard launcher."""
import argparse
import os
import threading
import webbrowser
from .server import make_server
from .data import selected_source, load_configuration
from .vault import KnowledgeIndex
from data.generate_demo import generate

def main():
    parser = argparse.ArgumentParser(description="JARVIS local assistant")
    parser.add_argument("--search", help="Search indexed documents with source citations")
    parser.add_argument("--approve-real-knowledge", action="store_true", help="Allow read-only access to Documents/JARVIS_KNOWLEDGE when demo is disabled")
    parser.add_argument("--index-only", action="store_true", help="Print index statistics without starting the dashboard")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the system browser")
    args = parser.parse_args()
    load_configuration()
    source = selected_source(approve_real=args.approve_real_knowledge)
    if source.demo:
        generate(source.root)
    index = KnowledgeIndex(source).build()
    print(f"JARVIS — Shaheem — {'FICTIONAL DEMO' if source.demo else 'APPROVED REAL KNOWLEDGE'}")
    print(f"Knowledge location: {source.root}")
    print(f"Files: {len(index.documents)} | Links: {len(index.edges)} | Skipped: {len(index.skipped)}")
    print("Top 10 graph hubs:")
    for filename, degree in index.hubs():
        print(f"  {degree:3} connections  {filename}")
    for warning in index.warnings:
        print(f"Warning: {warning}")
    for filename, reason in index.skipped:
        print(f"Skipped {filename}: {reason}")
    if args.search:
        results = index.search(args.search)
        for result in results:
            print(f"[{result['citation']}] {result['snippet']}")
        if not results:
            print("No matching documents.")
    if not args.index_only and not args.search:
        with make_server(index) as server:
            status = server.assistant.ai.status()
            print('Ollama: ' + status['message'], flush=True)
            print('ElevenLabs key: ' + ('present (connection untested; each paid request needs approval)' if os.environ.get('ELEVENLABS_API_KEY') else 'not configured (optional; text mode available)'), flush=True)
            print('Voice: ' + server.assistant.voice.status()['message'], flush=True)
            print("Dashboard: http://localhost:8765 — Ctrl+C to stop", flush=True)
            if not args.no_browser:
                timer = threading.Timer(0.3, webbrowser.open, args=("http://localhost:8765",))
                timer.daemon = True
                timer.start()
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("JARVIS stopped")
    return 0
