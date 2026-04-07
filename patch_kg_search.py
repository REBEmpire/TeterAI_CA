import re

with open('src/ui/web/src/views/KnowledgeGraphView.tsx', 'r') as f:
    content = f.read()

# 1. Update the SearchOverlay section
search_overlay_old = r"""          \{/\* Semantic search results overlay \*/\}\n          \{searchResults\.length > 0 && \(\n            <div className="absolute top-4 left-4 z-10 bg-white shadow-lg rounded p-3 max-w-xs max-h-64 overflow-y-auto">\n              <h3 className="text-xs font-semibold text-teter-gray-text uppercase tracking-wider mb-2\">\n                Search Results\n              <\/h3>\n              <ul className="space-y-2">\n                \{searchResults\.map\(\(res, i\) => \(\n                  <li key=\{i\} className="text-sm">\n                    <div className="flex items-center gap-2">\n                      <span className="w-2 h-2 rounded-full bg-blue-500" \/>\n                      <span className="font-semibold text-teter-dark truncate">\n                        \{res\.label\}\n                      <\/span>\n                    <\/div>\n                    <div className="text-xs text-teter-gray-text mt-0.5">\n                      Score: \{\(res\.score \* 100\)\.toFixed\(1\)\}%\n                    <\/div>\n                  <\/li>\n                \)\)\}\n              <\/ul>\n            <\/div>\n          \)\}\n        <\/div>\n      <\/div>"""

search_overlay_new = """          {/* Semantic search results overlay */}
          {searchResults.length > 0 && (
            <div className="absolute top-4 left-4 z-10 bg-white shadow-2xl rounded border border-gray-100 p-4 max-w-sm max-h-80 overflow-y-auto animate-slide-in-left flex flex-col">
              <div className="flex justify-between items-center mb-3">
                <h3 className="text-xs font-semibold text-teter-gray-text uppercase tracking-wider">
                  Search Results ({searchResults.length})
                </h3>
                <div className="flex gap-2">
                  <button
                    onClick={clearSearch}
                    className="text-xs text-gray-500 hover:text-red-500 transition-colors"
                  >
                    Clear
                  </button>
                </div>
              </div>
              <ul className="space-y-3 flex-1">
                {searchResults.map((res, i) => {
                  const nodeColorClass = res.node_type === 'RFI' ? 'bg-orange-500' :
                                         res.node_type === 'SPEC_SECTION' ? 'bg-blue-500' :
                                         res.node_type === 'DESIGN_FLAW' ? 'bg-red-500' :
                                         res.node_type === 'CORRECTIVE_ACTION' ? 'bg-green-500' :
                                         res.node_type === 'SUBMITTAL' ? 'bg-purple-500' :
                                         res.node_type === 'SCHEDULEREVIEW' ? 'bg-teal-500' :
                                         res.node_type === 'PAYAPP' ? 'bg-yellow-500' :
                                         res.node_type === 'PARTY' ? 'bg-pink-500' :
                                         'bg-gray-500';

                  return (
                  <li
                    key={i}
                    className="text-sm border border-gray-100 rounded p-2 hover:bg-gray-50 cursor-pointer transition-colors"
                    onClick={() => handleNavigateToNode(res.node_id)}
                  >
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <div className="flex items-center gap-1.5 overflow-hidden">
                        <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${nodeColorClass}`} />
                        <span className="font-semibold text-teter-dark truncate">
                          {res.label}
                        </span>
                      </div>
                      <span className="text-[10px] font-medium text-gray-500 uppercase tracking-wider bg-gray-100 px-1.5 py-0.5 rounded flex-shrink-0">
                        {res.node_type.replace('_', ' ')}
                      </span>
                    </div>

                    <div className="mt-2 w-full bg-gray-200 rounded-full h-1.5 flex overflow-hidden">
                      <div
                        className="bg-blue-500 h-1.5 rounded-full"
                        style={{ width: `${Math.max(10, res.score * 100)}%` }}
                      ></div>
                    </div>
                    <div className="text-xs text-right text-teter-gray-text mt-1">
                      {(res.score * 100).toFixed(1)}% match
                    </div>
                  </li>
                )})}
              </ul>
            </div>
          )}
        </div>
      </div>"""

if re.search(search_overlay_old, content):
    content = content.replace(search_overlay_old, search_overlay_new)
else:
    # Try regex approach if direct replace fails
    content = re.sub(
        r"          \{/\* Semantic search results overlay \*/\}.*?(?=\n        <\/div>\n      <\/div>)",
        search_overlay_new.replace("        </div>\n      </div>", ""),
        content,
        flags=re.DOTALL
    )

with open('src/ui/web/src/views/KnowledgeGraphView.tsx', 'w') as f:
    f.write(content)
