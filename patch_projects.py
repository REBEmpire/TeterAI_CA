with open('src/ui/web/src/components/upload/DocumentUploadPanel.tsx', 'r') as f:
    lines = f.readlines()

new_lines = []
skip_next = False
for i, line in enumerate(lines):
    if "const [projects, setProjects] = useState<ProjectSummary[]>([])" in line:
        if i == 160: # Keep the first one
            new_lines.append(line)
        else:
            continue
    else:
        new_lines.append(line)

with open('src/ui/web/src/components/upload/DocumentUploadPanel.tsx', 'w') as f:
    f.writelines(new_lines)
