import re

with open('src/knowledge_graph/ingestion.py', 'r') as f:
    content = f.read()

# Fix the syntax error in ingestion.py again. This time I'll just use the basic try/except properly
# Looking at the file, the syntax error is at `except Exception as e:` on line 472
# Let's just output the whole function to see the indentation
