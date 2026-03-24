import os
import requests
import subprocess
import shutil
from dotenv import load_dotenv
from langchain_community.document_loaders import DirectoryLoader, TextLoader, WebBaseLoader
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

REPOS_DIR = "data/repos"
DB_DIR = "chroma_db"
SERPER_API_KEY = os.getenv("SERPER_API_KEY")

REPOSITORIES = {
    "promptfoo": "https://github.com/promptfoo/promptfoo.git",
    "pyrit": "https://github.com/Azure/PyRIT.git",
    "agentic-radar": "https://github.com/splx-ai/agentic-radar.git"
}

def fetch_and_filter_docs():
    """Shallow clones repos and aggressively deletes non-documentation files."""
    if not os.path.exists(REPOS_DIR):
        os.makedirs(REPOS_DIR)

    for name, url in REPOSITORIES.items():
        repo_path = os.path.join(REPOS_DIR, name)
        
        if not os.path.exists(repo_path):
            print(f"📥 Shallow cloning {name} from {url}...")
            subprocess.run(["git", "clone", "--depth", "1", url, repo_path], check=True)
        else:
            print(f"✅ {name} already exists. Pulling latest changes...")
            subprocess.run(["git", "-C", repo_path, "pull", "--depth", "1"], check=True)

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
    """Uses Serper API to find official docs, then scrapes the text."""
    if not SERPER_API_KEY:
        print("⚠️ SERPER_API_KEY not found. Skipping web scraping.")
        return []

    print("\n🌐 Searching the web for official documentation...")
    queries = ["site:promptfoo.dev/docs", "site:azure.github.io/PyRIT"]
    all_urls = []
    headers = {'X-API-KEY': SERPER_API_KEY, 'Content-Type': 'application/json'}

    for query in queries:
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
    """Loads markdown from repos, combines with web docs, and builds Chroma DB."""
    print("\n🔍 Loading Markdown documentation from repositories...")
    repo_documents = DirectoryLoader(
        REPOS_DIR, glob="**/*.md", loader_cls=TextLoader, loader_kwargs={"encoding": "utf-8"}
    ).load()
    print(f"📄 Found {len(repo_documents)} repo documentation files.")

    all_documents = repo_documents + search_and_scrape_docs()

    print("\n✂️ Splitting documents into chunks...")
    chunks = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200, length_function=len).split_documents(all_documents)

    print("🧠 Generating embeddings and building Chroma database...")
    if os.path.exists(DB_DIR): shutil.rmtree(DB_DIR)
    
    Chroma.from_documents(
        documents=chunks, 
        embedding=HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2"), 
        persist_directory=DB_DIR
    )
    print(f"✅ Knowledge base successfully built and saved to ./{DB_DIR}/")

if __name__ == "__main__":
    print("🚀 Starting Advanced RAG Knowledge Ingestion Phase")
    fetch_and_filter_docs()
    build_vector_db()