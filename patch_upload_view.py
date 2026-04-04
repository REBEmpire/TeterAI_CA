with open('src/ui/web/src/views/UploadView.tsx', 'r') as f:
    content = f.read()

# Remove the bad edits from the UploadView.tsx
if "import { useNavigate }" in content:
    content = content.replace("import { useNavigate } from 'react-router-dom'", "")
    content = content.replace("  const navigate = useNavigate()", "")

with open('src/ui/web/src/views/UploadView.tsx', 'w') as f:
    f.write(content)
