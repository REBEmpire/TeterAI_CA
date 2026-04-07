import re

with open('src/knowledge_graph/client.py', 'r') as f:
    content = f.read()

# Fix truncation for graph endpoints
# Add summary_full and update summary to 300 chars
old_summary_graph = r'"summary":\s*\(row\.get\("summary"\) or ""\)\[:120\],'
new_summary_graph = '"summary":       (row.get("summary") or "")[:300],\n                            "summary_full":  row.get("summary") or "",'
content = re.sub(old_summary_graph, new_summary_graph, content)

# Fix truncation for search results
old_question_search = r'"question":\s*\(r\.get\("question"\) or ""\)\[:200\],'
new_question_search = '"question":   r.get("question") or "",'
content = re.sub(old_question_search, new_question_search, content)

with open('src/knowledge_graph/client.py', 'w') as f:
    f.write(content)
