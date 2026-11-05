import os

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(override=True)  # .env wins over anything set in the terminal
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

with open("seed/samples/SHP-24811_invoice.pdf", "rb") as f:    data = f.read()

resp = client.models.generate_content(
    model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
    contents=[types.Part.from_bytes(data=data, mime_type="application/pdf"),
              "Return the invoice number and total as JSON."],
)
print(resp.text)
