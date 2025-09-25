# server.py
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from app_chain import ask_with_evidence

app = FastAPI()

class Q(BaseModel):
    question: str

@app.get("/", response_class=HTMLResponse)
def root():
    return """
<!doctype html><meta charset="utf-8">
<title>GraphRAG Q&A</title>
<style>body{font-family:system-ui;margin:40px;max-width:900px}pre{background:#f6f6f6;padding:12px;border-radius:8px;overflow:auto}</style>
<h1>Neo4j + LangChain Q&A</h1>
<input id="q" placeholder="질문을 입력하세요" style="width:70%"/>
<button id="go">질의</button>
<pre id="out"></pre>
<script>
const $=(s)=>document.querySelector(s);
$("#go").onclick=async ()=>{
  const res=await fetch("/ask",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({question:$("#q").value.trim()})});
  const json=await res.json();
  $("#out").textContent=
    "Answer:\\n"+json.answer+"\\n\\nCypher:\\n"+(json.cypher||"(n/a)")+
    "\\n\\nRecords:\\n"+JSON.stringify(json.records,null,2);
};
</script>
"""

@app.post("/ask")
def ask(q: Q):
    return ask_with_evidence(q.question)

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)

