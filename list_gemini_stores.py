import os
from google import genai

client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))
for store in client.file_search_stores.list():
    print(f"Store: {store.display_name} ({store.name})")
    for doc in client.file_search_stores.documents.list(parent=store.name):
        print(f"  - {doc.display_name}")
