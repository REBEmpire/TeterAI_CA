import re

with open('src/ui/web/src/views/ProjectIntelligenceView.tsx', 'r') as f:
    content = f.read()

# Add small SVG bar charts to compare cards
card_old = r"""                <div\n                  key=\{p\.project_id\}\n                  className="bg-white rounded border border-gray-200 p-4 shadow-sm flex flex-col"\n                >\n                  <h4 className="font-semibold text-teter-dark text-sm truncate mb-3" title=\{p\.project_name\}>\n                    \{p\.project_name\}\n                  <\/h4>\n                  <div className="space-y-2 flex-1">\n                    <div className="flex justify-between items-center text-xs">\n                      <span className="text-teter-gray-text">Total Docs:<\/span>\n                      <span className="font-medium text-teter-dark">\{p\.total_documents\}<\/span>\n                    <\/div>\n                    <div className="flex justify-between items-center text-xs">\n                      <span className="text-teter-gray-text">Response Rate:<\/span>\n                      <span className="font-medium text-teter-dark">\{\(p\.response_rate \* 100\)\.toFixed\(1\)\}%<\/span>\n                    <\/div>\n                    <div className="flex justify-between items-center text-xs">\n                      <span className="text-teter-gray-text">Total Parties:<\/span>\n                      <span className="font-medium text-teter-dark">\{p\.total_parties\}<\/span>\n                    <\/div>\n                  <\/div>\n                <\/div>"""

card_new = """                <div
                  key={p.project_id}
                  className="bg-white rounded border border-gray-200 p-4 shadow-sm flex flex-col"
                >
                  <h4 className="font-semibold text-teter-dark text-sm truncate mb-3" title={p.project_name}>
                    {p.project_name}
                  </h4>
                  <div className="space-y-3 flex-1">
                    <div className="flex justify-between items-center text-xs">
                      <span className="text-teter-gray-text">Total Docs:</span>
                      <span className="font-medium text-teter-dark">{p.total_documents}</span>
                    </div>
                    {/* Tiny inline doc type bar chart */}
                    {p.documents_by_type && Object.keys(p.documents_by_type).length > 0 && (
                      <div className="flex h-2 w-full rounded-full overflow-hidden mt-1 mb-2 bg-gray-100" title={Object.entries(p.documents_by_type).map(([k,v]) => `${k}: ${v}`).join(', ')}>
                        {Object.entries(p.documents_by_type).map(([type, count]) => {
                          const w = (count / Math.max(1, p.total_documents)) * 100
                          const color = type === 'RFI' ? 'bg-orange-500' :
                                        type === 'SUBMITTAL' ? 'bg-purple-500' :
                                        type === 'SCHEDULEREVIEW' ? 'bg-teal-500' :
                                        type === 'PAYAPP' ? 'bg-yellow-500' :
                                        type === 'COSTANALYSIS' ? 'bg-indigo-500' :
                                        'bg-gray-400'
                          return w > 0 ? <div key={type} className={`${color}`} style={{ width: `${w}%` }} /> : null
                        })}
                      </div>
                    )}

                    <div className="text-xs">
                      <div className="flex justify-between items-center mb-1">
                        <span className="text-teter-gray-text">Response Rate:</span>
                        <span className="font-medium text-teter-dark">{(p.response_rate * 100).toFixed(1)}%</span>
                      </div>
                      <div className="w-full bg-gray-200 rounded-full h-1.5 overflow-hidden">
                        <div className="bg-blue-500 h-1.5 rounded-full" style={{ width: `${p.response_rate * 100}%` }}></div>
                      </div>
                    </div>
                    <div className="flex justify-between items-center text-xs pt-1">
                      <span className="text-teter-gray-text">Total Parties:</span>
                      <span className="font-medium text-teter-dark">{p.total_parties}</span>
                    </div>
                  </div>
                </div>"""

content = re.sub(card_old, card_new, content)

with open('src/ui/web/src/views/ProjectIntelligenceView.tsx', 'w') as f:
    f.write(content)
