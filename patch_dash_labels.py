with open('src/ui/web/src/views/Dashboard.tsx', 'r') as f:
    content = f.read()

content = content.replace("{task.document_type}", "{DOC_TYPE_LABELS[task.document_type || 'UNKNOWN'] || task.document_type}")

with open('src/ui/web/src/views/Dashboard.tsx', 'w') as f:
    f.write(content)
