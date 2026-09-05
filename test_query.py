import requests
import json

response = requests.post("http://localhost:8000/api/query", json={"query": "Que relacion hay entre ERC y diabetes?"})
data = response.json()
print("Response Text:", data["response"])
print("Citations:")
for c in data["citations"]:
    print(c)
print("Evidence Count:", data["evidence_count"])
