import base64
import json

# Load JSON file
with open("service_account.json", "r") as f:
    data = f.read()

# Encode to Base64
encoded = base64.b64encode(data.encode("utf-8")).decode("utf-8")

print(encoded)
