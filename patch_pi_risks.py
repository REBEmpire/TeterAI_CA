import re

with open('src/ui/web/src/views/ProjectIntelligenceView.tsx', 'r') as f:
    content = f.read()

# Update Structured AI Narrative sections
risks_old = r"""              <div className="bg-white rounded-lg border border-gray-200 p-5 shadow-sm space-y-4">\n                <div>\n                  <h4 className="text-sm font-semibold text-teter-dark mb-1">Risk Flags</h4>\n                  <p className="text-sm text-teter-gray-text whitespace-pre-wrap">\n                    \{narrative\.risk_flags\}\n                  <\/p>\n                <\/div>\n              <\/div>"""

risks_new = """              <div className="bg-white rounded-lg border border-gray-200 p-5 shadow-sm space-y-4 border-l-4 border-l-orange-500">
                <div>
                  <h4 className="text-sm font-semibold text-teter-dark mb-3">Risk Flags</h4>
                  <div className="space-y-3">
                    {narrative.risk_flags.split(/\\n|-/).filter(r => r.trim().length > 5).map((risk, i) => {
                      const text = risk.trim();
                      const isHigh = /high|critical|severe|urgent/i.test(text);
                      const isLow = /low|minor|monitor/i.test(text);
                      const severity = isHigh ? 'High' : isLow ? 'Low' : 'Medium';
                      const badgeColor = isHigh ? 'bg-red-100 text-red-800' : isLow ? 'bg-green-100 text-green-800' : 'bg-orange-100 text-orange-800';

                      return (
                        <div key={i} className="flex gap-3 items-start bg-gray-50 p-3 rounded-md border border-gray-100">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider mt-0.5 ${badgeColor}`}>
                            {severity}
                          </span>
                          <p className="text-sm text-teter-gray-text flex-1">
                            {text.replace(/^\\d+\\.\\s*/, '')}
                          </p>
                        </div>
                      );
                    })}
                    {(!narrative.risk_flags || narrative.risk_flags.trim().length === 0) && (
                      <p className="text-sm text-teter-gray-text">No active risk flags identified.</p>
                    )}
                  </div>
                </div>
              </div>"""

content = content.replace('              <div className="bg-white rounded-lg border border-gray-200 p-5 shadow-sm space-y-4">\n                <div>\n                  <h4 className="text-sm font-semibold text-teter-dark mb-1">Risk Flags</h4>\n                  <p className="text-sm text-teter-gray-text whitespace-pre-wrap">\n                    {narrative.risk_flags}\n                  </p>\n                </div>\n              </div>', risks_new.replace('\\n', '\\n').replace('\\d', '\\d').replace('\\s', '\\s'))

recs_old = r"""              <div className="bg-white rounded-lg border border-gray-200 p-5 shadow-sm space-y-4">\n                <div>\n                  <h4 className="text-sm font-semibold text-teter-dark mb-1">Recommendations</h4>\n                  <p className="text-sm text-teter-gray-text whitespace-pre-wrap">\n                    \{narrative\.recommendations\}\n                  <\/p>\n                <\/div>\n              <\/div>"""

recs_new = """              <div className="bg-white rounded-lg border border-gray-200 p-5 shadow-sm space-y-4 border-l-4 border-l-green-500">
                <div>
                  <h4 className="text-sm font-semibold text-teter-dark mb-3">Recommendations</h4>
                  <ul className="space-y-2">
                    {narrative.recommendations.split(/\\n|-/).filter(r => r.trim().length > 5).map((rec, i) => {
                      const text = rec.trim().replace(/^\\d+\\.\\s*/, '');
                      return (
                        <li key={i} className="flex gap-3 items-start">
                          <div className="flex-shrink-0 mt-0.5">
                            <svg className="w-4 h-4 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                          </div>
                          <p className="text-sm text-teter-gray-text flex-1">
                            {text}
                          </p>
                        </li>
                      );
                    })}
                    {(!narrative.recommendations || narrative.recommendations.trim().length === 0) && (
                      <p className="text-sm text-teter-gray-text">No current recommendations.</p>
                    )}
                  </ul>
                </div>
              </div>"""

content = content.replace('              <div className="bg-white rounded-lg border border-gray-200 p-5 shadow-sm space-y-4">\n                <div>\n                  <h4 className="text-sm font-semibold text-teter-dark mb-1">Recommendations</h4>\n                  <p className="text-sm text-teter-gray-text whitespace-pre-wrap">\n                    {narrative.recommendations}\n                  </p>\n                </div>\n              </div>', recs_new.replace('\\n', '\\n').replace('\\d', '\\d').replace('\\s', '\\s'))

# Status border
status_old = '              <div className="bg-white rounded-lg border border-gray-200 p-5 shadow-sm space-y-4">\n                <div>\n                  <h4 className="text-sm font-semibold text-teter-dark mb-1">Overview</h4>'

status_new = '              <div className="bg-white rounded-lg border border-gray-200 p-5 shadow-sm space-y-4 border-l-4 border-l-blue-500">\n                <div>\n                  <h4 className="text-sm font-semibold text-teter-dark mb-1">Overview</h4>'

content = content.replace(status_old, status_new)

with open('src/ui/web/src/views/ProjectIntelligenceView.tsx', 'w') as f:
    f.write(content)
