"""Ariadne API examples and model-listing utility.

This script is a quick sanity check for the Ariadne token and a small discovery
tool for seeing which model identifiers are available. It is separate from the
main crew because users may want to inspect the API before running the full
red-teaming workflow.

Requirements: pip install requests python-dotenv

Setup:
    1. Create a .env file with ARIADNE_API_TOKEN=sk-proj-YOUR-TOKEN.
    2. Run this script with Python to print the available models.
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
    """Fetch and print the model catalog returned by the Ariadne API."""
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
    """Validate the token and display the available Ariadne models."""
    if API_TOKEN == "sk-proj-YOUR-TOKEN" or not API_TOKEN:
        print("\n⚠️  Set ARIADNE_API_TOKEN in .env file")
        print("Get your token: https://ariadne.issel.ee.auth.gr")
        sys.exit(1)
    
    print("\n" + "="*70)
    print("🚀 Ariadne API Examples")
    print("="*70)
    
    try:
        # This script only demonstrates the model-listing path; the other examples
        # are documented in the header for reference.
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
