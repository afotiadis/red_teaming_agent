"""Build the documentation knowledge base used by the planner agent.

This script creates the retrieval corpus that helps the strategist choose good
tests. Instead of indexing source code, it focuses on documentation and official
guides so the planner learns concepts, tool usage patterns, and workflow ideas.

The pipeline has three stages:
1. Clone selected repositories and keep only markdown/text artifacts.
2. Find and scrape official docs from the web.
3. Chunk the content, embed it, and persist it in a local Chroma database.
"""

import os
import json
import requests
import subprocess
import shutil
from pathlib import Path
from dotenv import load_dotenv
from langchain_community.document_loaders import DirectoryLoader, TextLoader, WebBaseLoader
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

# WebBaseLoader emits a warning if USER_AGENT is unset; provide a safe default
# so documentation scraping can run without extra shell setup.
os.environ.setdefault("USER_AGENT", "red_teaming_agent/1.0")

REPOS_DIR = os.getenv("REPOS_DIR", "data/repos")
DB_DIR = os.getenv("KNOWLEDGE_BASE_PATH", "chroma_db")
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_SOURCES_PATH = os.getenv("KNOWLEDGE_SOURCES_PATH", os.path.join(PROJECT_ROOT, "config", "knowledge_sources.json"))
SEARCH_QUERIES = [
    query.strip()
    for query in os.getenv("SEARCH_QUERIES", "site:promptfoo.dev/docs,site:azure.github.io/PyRIT").split(",")
    if query.strip()
]


def _load_knowledge_sources() -> dict:
    """Load repository and search sources from JSON, falling back to env defaults."""
    try:
        with open(KNOWLEDGE_SOURCES_PATH, "r", encoding="utf-8") as source_file:
            return json.load(source_file)
    except Exception:
        return {
            "repositories": [
                {"name": "promptfoo", "url": "https://github.com/promptfoo/promptfoo.git", "enabled": True},
                {"name": "pyrit", "url": "https://github.com/Azure/PyRIT.git", "enabled": True},
                {"name": "agentic-radar", "url": "https://github.com/splx-ai/agentic-radar.git", "enabled": True},
            ],
            "web_searches": [{"query": query, "enabled": True} for query in SEARCH_QUERIES],
            "local_documents": [
                {"name": "gandalf-skill", "path": "skills/gandalf/SKILL.md", "enabled": True},
            ],
        }


KNOWLEDGE_SOURCES = _load_knowledge_sources()


def _load_local_documents():
    """Load explicitly configured local markdown documents into the corpus."""
    local_documents = []
    for doc_config in KNOWLEDGE_SOURCES.get("local_documents", []):
        if not doc_config.get("enabled", True):
            continue

        doc_path = Path(doc_config["path"])
        if not doc_path.is_absolute():
            doc_path = Path(PROJECT_ROOT) / doc_path

        if not doc_path.exists():
            print(f"⚠️ Local doc not found: {doc_path}")
            continue

        try:
            local_documents.extend(TextLoader(str(doc_path), encoding="utf-8").load())
            print(f"📘 Loaded local document: {doc_config.get('name', doc_path.name)}")
        except Exception as exc:
            print(f"⚠️ Failed to load local document {doc_path}: {exc}")

    return local_documents

def fetch_and_filter_docs():
    """Clone the reference repositories and keep only documentation files.

    This intentionally discards source code because the RAG store is meant to
    teach the planner about common red-teaming tools and workflows, not to turn
    the crew into a code indexer. Keeping the corpus narrow also reduces noise
    when retrieving relevant background material.
    """
    if not os.path.exists(REPOS_DIR):
        os.makedirs(REPOS_DIR)

    for repo_config in KNOWLEDGE_SOURCES.get("repositories", []):
        if not repo_config.get("enabled", True):
            continue

        name = repo_config["name"]
        url = repo_config["url"]
        repo_path = os.path.join(REPOS_DIR, name)
        
        if not os.path.exists(repo_path):
            print(f"📥 Shallow cloning {name} from {url}...")
            subprocess.run(["git", "clone", "--depth", "1", url, repo_path], check=True)
        else:
            print(f"✅ {name} already exists. Reusing the local checkout instead of pulling updates.")
            print("   If you want a fresh clone, delete the repo folder and rerun ingestion.")

        print(f"🧹 Purging source code from {name}, keeping only documentation...")
        for root, dirs, files in os.walk(repo_path, topdown=False):
            if '.git' in root:
                continue
            for file in files:
                if not file.endswith(('.md', '.mdx', '.txt')):
                    try:
                        os.remove(os.path.join(root, file))
                    except Exception:
                        pass 
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                if not os.listdir(dir_path): 
                    try:
                        os.rmdir(dir_path)
                    except Exception:
                        pass

def search_and_scrape_docs():
    """Use Serper to locate official docs and scrape the resulting pages.

    The local repository clone is helpful, but official docs often explain the
    intended usage of a tool more clearly than examples embedded in a repo. This
    step augments the knowledge base with those canonical sources.
    """
    if not SERPER_API_KEY:
        print("⚠️ SERPER_API_KEY not found. Skipping web scraping.")
        return []

    print("\n🌐 Searching the web for official documentation...")
    all_urls = []
    headers = {'X-API-KEY': SERPER_API_KEY, 'Content-Type': 'application/json'}

    for search_config in KNOWLEDGE_SOURCES.get("web_searches", []):
        if not search_config.get("enabled", True):
            continue

        query = search_config["query"]
        payload = {"q": query, "num": 5}
        response = requests.post("https://google.serper.dev/search", headers=headers, json=payload)
        if response.status_code == 200:
            urls = [res["link"] for res in response.json().get("organic", [])]
            all_urls.extend(urls)
            print(f"🔗 Found {len(urls)} links for: {query}")
        else:
            print(f"❌ Serper API error for '{query}': {response.text}")

    if not all_urls: return []
        
    print("🕸️ Scraping content from URLs...")
    web_documents = WebBaseLoader(all_urls).load()
    print(f"📄 Successfully scraped {len(web_documents)} web pages.")
    return web_documents

def build_vector_db():
    """Chunk the collected documentation and persist it as a local vector store."""
    print("\n🔍 Loading Markdown documentation from repositories...")
    repo_documents = DirectoryLoader(
        REPOS_DIR, glob="**/*.md", loader_cls=TextLoader, loader_kwargs={"encoding": "utf-8"}
    ).load()
    print(f"📄 Found {len(repo_documents)} repo documentation files.")

    all_documents = repo_documents + search_and_scrape_docs() + _load_local_documents()

    print("\n✂️ Splitting documents into chunks...")
    chunks = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
    ).split_documents(all_documents)

    print("🧠 Generating embeddings and building Chroma database...")
    if os.path.exists(DB_DIR): shutil.rmtree(DB_DIR)
    
    Chroma.from_documents(
        documents=chunks, 
        embedding=HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL), 
        persist_directory=DB_DIR
    )
    print(f"✅ Knowledge base successfully built and saved to ./{DB_DIR}/")

if __name__ == "__main__":
    print("🚀 Starting Advanced RAG Knowledge Ingestion Phase")
    fetch_and_filter_docs()
    build_vector_db()