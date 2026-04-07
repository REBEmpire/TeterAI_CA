import re

with open('src/ui/web/src/components/graph/GraphNodeDetailPanel.tsx', 'r') as f:
    content = f.read()

# Fix duplicate properties in GraphNode
content = re.sub(
    r"  id: string\n  type: 'SPEC_SECTION' \| 'RFI' \| 'DESIGN_FLAW' \| 'CORRECTIVE_ACTION' \| 'SUBMITTAL' \| 'SCHEDULEREVIEW' \| 'PAYAPP' \| 'COSTANALYSIS' \| 'PARTY' \| string\n  id: string\n  type: 'SPEC_SECTION' \| 'RFI' \| 'DESIGN_FLAW' \| 'CORRECTIVE_ACTION' \| 'SUBMITTAL' \| 'SCHEDULEREVIEW' \| 'PAYAPP' \| 'COSTANALYSIS' \| 'PARTY' \| string",
    "  id: string\n  type: 'SPEC_SECTION' | 'RFI' | 'DESIGN_FLAW' | 'CORRECTIVE_ACTION' | 'SUBMITTAL' | 'SCHEDULEREVIEW' | 'PAYAPP' | 'COSTANALYSIS' | 'PARTY' | string",
    content
)

with open('src/ui/web/src/components/graph/GraphNodeDetailPanel.tsx', 'w') as f:
    f.write(content)
