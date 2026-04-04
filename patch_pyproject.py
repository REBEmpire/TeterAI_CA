with open('pyproject.toml', 'r') as f:
    content = f.read()

if "apscheduler" not in content:
    content = content.replace('dependencies = [', 'dependencies = [\n    "apscheduler>=3.10.4",')

with open('pyproject.toml', 'w') as f:
    f.write(content)
