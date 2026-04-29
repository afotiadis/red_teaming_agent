"""
Ariadne API Examples - https://ariadne.issel.ee.auth.gr

Requirements: pip install requests python-dotenv

Setup:
    1. Create .env file: ARIADNE_API_TOKEN=sk-proj-YOUR-TOKEN
    2. Run: python ariadne_api_examples.py

Examples included:
    1. Simple Chat (non-streaming)
    2. Multi-turn Conversation
    3. Function/Tool Calling
    4. List Available Models
    5. Error Handling
    6. Streaming Chat (SSE)
    7. Streaming with Tools
"""

import requests
import json
import sys
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
    API_TOKEN = os.getenv('ARIADNE_API_TOKEN', 'sk-proj-YOUR-TOKEN')
    print("✅ API token loaded" if API_TOKEN != 'sk-proj-YOUR-TOKEN' else "⚠️  Set ARIADNE_API_TOKEN in .env")
except ImportError:
    API_TOKEN = "sk-proj-YOUR-TOKEN"

BASE_URL = "https://ariadne.issel.ee.auth.gr/api"

def example4_list_models():
    """List available models"""
    print("\n" + "="*70)
    print("EXAMPLE 4: Available Models")
    print("="*70)
    
    response = requests.get(
        f"{BASE_URL}/v1/models",
        headers={"Authorization": f"Bearer {API_TOKEN}"}
    )
    
    models = response.json()['data']
    print(f"\n✅ {len(models)} models available:")
    
    for model in models:
        print(f"  📦 {model['name']} - provider='{model['provider']}', model='{model['id']}'")

def main():
    if API_TOKEN == "sk-proj-YOUR-TOKEN" or not API_TOKEN:
        print("\n⚠️  Set ARIADNE_API_TOKEN in .env file")
        print("Get your token: https://ariadne.issel.ee.auth.gr")
        sys.exit(1)
    
    print("\n" + "="*70)
    print("🚀 Ariadne API Examples")
    print("="*70)
    
    try:
        # Non-streaming examples
        example4_list_models()
        
        print("\n" + "="*70)
        print("✅ All examples completed!")
        print("📚 See AriadneAPI_QUICKSTART.md for full documentation")
        print("="*70 + "\n")
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted")
        sys.exit(0)

if __name__ == "__main__":
    main()
