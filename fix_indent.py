import re
with open("src/agents/dispatcher/agent.py", "r") as f:
    text = f.read()

# I notice the traceback:
# E     File "/app/tests/../src/agents/dispatcher/agent.py", line 258
# E       except Exception as e:
# E   IndentationError: unexpected indent

lines = text.split('\n')
for i, line in enumerate(lines):
    if line.strip() == "except Exception as e:":
        print(f"Line {i+1}: {repr(line)}")
